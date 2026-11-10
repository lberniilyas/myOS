"""Instant saving: the reply comes as soon as the words are stored, the AI runs afterwards, and
a sweep finishes or retries anything a restart, a sleeping server or a busy AI interrupted."""

import asyncio
import time
import uuid
from contextlib import nullcontext, suppress

import pytest
from sqlalchemy import select, text

from app.ai.provider import AIProviderError
from app.captures import signals, worker
from app.captures.models import Capture
from app.captures.retries import AUTO_ATTEMPTS
from app.config import get_settings
from app.db.session import get_session_factory
from app.events.models import Event
from app.main import app
from tests import factories as f


@pytest.fixture
def sessions(db):
    """Background work uses the test's transaction instead of opening real sessions."""

    def factory():
        return nullcontext(db)

    app.dependency_overrides[get_session_factory] = lambda: factory
    yield factory
    app.dependency_overrides.pop(get_session_factory, None)


def study(text_: str = "Studied AI"):
    return f.output(events=[f.event("STUDY", "AI study", text_, time=f.when(duration_minutes=60))])


def save(client, auth, content: str, **extra):
    return client.post(
        "/v1/captures?background=true", json={"content": content, **extra}, headers=auth
    )


def status_of(db, capture_id) -> Capture:
    db.expire_all()
    return db.get(Capture, uuid.UUID(capture_id))


def age(db, capture_id, minutes: float) -> None:
    """Pretend the capture's last change happened `minutes` ago."""
    db.execute(
        text("update captures set updated_at = now() - make_interval(secs => :s) where id = :id"),
        {"s": minutes * 60, "id": capture_id},
    )


class TestInstantSaving:
    def test_the_reply_comes_before_the_understanding(self, client, auth, fake_ai, db, sessions):
        fake_ai.respond("Studied", study())
        response = save(client, auth, "Studied AI")
        assert response.status_code == 202
        reply = response.json()
        assert reply["capture"]["status"] == "PROCESSING"
        assert reply["message"] == "Saved. Understanding it…"
        assert reply["events_created"] == [] and reply["error"] is None
        # The test client runs the after-reply work before returning: the result is now stored.
        done = client.get(f"/v1/captures/{reply['capture']['id']}", headers=auth).json()
        assert done["capture"]["status"] == "PROCESSED"
        assert [e["title"] for e in done["events_created"]] == ["AI study"]

    def test_a_failure_the_server_will_retry_is_reported_as_such(
        self, client, auth, fake_ai, db, sessions
    ):
        fake_ai.error = AIProviderError("AI_RATE_LIMITED", "busy", retryable=True)
        reply = save(client, auth, "Studied AI").json()
        stored = client.get(f"/v1/captures/{reply['capture']['id']}", headers=auth).json()
        assert stored["capture"]["status"] == "FAILED" and stored["capture"]["will_retry"] is True
        assert (
            stored["message"]
            == "I couldn't process that yet. Your entry is saved and I'll try again shortly."
        )
        pending = client.get("/v1/captures?pending=true", headers=auth).json()
        assert [c["id"] for c in pending] == [reply["capture"]["id"]]
        assert client.get("/v1/captures?unfinished=true", headers=auth).json() == []

    def test_a_failure_that_needs_you_goes_to_home(self, client, auth, fake_ai, db, sessions):
        fake_ai.error = AIProviderError("AI_AUTH_FAILED", "The key was rejected.")
        reply = save(client, auth, "Studied AI").json()
        stored = client.get(f"/v1/captures/{reply['capture']['id']}", headers=auth).json()
        assert stored["capture"]["will_retry"] is False
        assert "Not processed yet" in stored["message"]
        assert [
            c["id"] for c in client.get("/v1/captures?unfinished=true", headers=auth).json()
        ] == [reply["capture"]["id"]]
        assert client.get("/v1/captures?pending=true", headers=auth).json() == []

    def test_resending_a_failed_capture_retries_it_after_the_reply(
        self, client, auth, fake_ai, db, sessions
    ):
        client_id = str(uuid.uuid4())
        fake_ai.error = AIProviderError("AI_RATE_LIMITED", "busy", retryable=True)
        save(client, auth, "Studied AI", client_capture_id=client_id)
        fake_ai.error = None
        fake_ai.respond("Studied", study())
        again = save(client, auth, "Studied AI", client_capture_id=client_id)
        assert again.status_code == 202
        assert db.scalar(select(Capture.processing_status)) == "PROCESSED"
        assert len(db.scalars(select(Event)).all()) == 1

    def test_serverless_hosts_answer_in_full_instead(self, client, auth, fake_ai, monkeypatch):
        monkeypatch.setenv("VERCEL", "1")
        get_settings.cache_clear()
        fake_ai.respond("Studied", study())
        response = save(client, auth, "Studied AI")
        get_settings.cache_clear()
        assert response.status_code == 200
        assert [e["title"] for e in response.json()["events_created"]] == ["AI study"]


class TestTheSweep:
    def _capture(self, client, auth, fake_ai, error=None) -> str:
        fake_ai.error = error
        reply = save(client, auth, f"Studied AI {uuid.uuid4().hex[:6]}").json()
        fake_ai.error = None
        return reply["capture"]["id"]

    def test_retries_wait_their_turn_then_succeed(self, client, auth, fake_ai, db, sessions, clock):
        busy = AIProviderError("AI_RATE_LIMITED", "busy", retryable=True)
        capture_id = self._capture(client, auth, fake_ai, busy)
        fake_ai.respond("Studied", study())
        age(db, capture_id, 0.5)
        assert worker.due_for_work(db, 60) == []  # the first pause is a minute
        age(db, capture_id, 1.5)
        assert worker.sweep(sessions, fake_ai, clock, 60) == (1, None)  # nothing left
        assert status_of(db, capture_id).processing_status == "PROCESSED"

    def test_pauses_grow_with_each_attempt(self, client, auth, fake_ai, db, sessions):
        busy = AIProviderError("AI_RATE_LIMITED", "busy", retryable=True)
        capture_id = self._capture(client, auth, fake_ai, busy)
        db.execute(text("update captures set attempts = 3 where id = :id"), {"id": capture_id})
        age(db, capture_id, 10)
        assert worker.due_for_work(db, 60) == []  # after the 3rd attempt the pause is 15 minutes
        age(db, capture_id, 16)
        assert worker.due_for_work(db, 60) == [uuid.UUID(capture_id)]

    def test_it_stops_retrying_after_five_attempts(self, client, auth, fake_ai, db, sessions):
        busy = AIProviderError("AI_RATE_LIMITED", "busy", retryable=True)
        capture_id = self._capture(client, auth, fake_ai, busy)
        db.execute(
            text("update captures set attempts = :n where id = :id"),
            {"n": AUTO_ATTEMPTS, "id": capture_id},
        )
        age(db, capture_id, 600)
        assert worker.due_for_work(db, 60) == []
        unfinished = client.get("/v1/captures?unfinished=true", headers=auth).json()
        assert [c["id"] for c in unfinished] == [capture_id]

    def test_failures_that_need_a_person_are_never_retried(
        self, client, auth, fake_ai, db, sessions
    ):
        capture_id = self._capture(
            client, auth, fake_ai, AIProviderError("AI_AUTH_FAILED", "bad key")
        )
        age(db, capture_id, 600)
        assert worker.due_for_work(db, 60) == []

    def test_it_finishes_captures_a_restart_interrupted(
        self, client, auth, fake_ai, db, sessions, clock
    ):
        # Stored but never understood: the state a restart leaves behind.
        fake_ai.error = AIProviderError("AI_AUTH_FAILED", "not reached")
        never_started = save(client, auth, "Studied AI").json()["capture"]["id"]
        cut_off = save(client, auth, "Read about maths").json()["capture"]["id"]
        fake_ai.error = None
        for capture_id, status, attempts in (
            (never_started, "CAPTURED", 0),
            (cut_off, "PROCESSING", 1),
        ):
            db.execute(
                text(
                    "update captures set processing_status = :s, attempts = :n, error_code = null,"
                    " error_detail = null, response_text = null where id = :id"
                ),
                {"s": status, "n": attempts, "id": capture_id},
            )
        fake_ai.respond("Studied", study())
        maths = f.event(
            "STUDY", "Maths study", "Read about maths", time=f.when(duration_minutes=30)
        )
        fake_ai.respond("maths", f.output(events=[maths]))
        age(db, never_started, 2)
        age(db, cut_off, 11)
        assert set(worker.due_for_work(db, 60)) == {uuid.UUID(never_started), uuid.UUID(cut_off)}
        assert worker.sweep(sessions, fake_ai, clock, 60)[0] == 2
        assert {status_of(db, c).processing_status for c in (never_started, cut_off)} == {
            "PROCESSED"
        }

    def test_a_capture_is_never_understood_twice(self, client, auth, fake_ai, db, sessions, clock):
        capture_id = self._capture(
            client, auth, fake_ai, AIProviderError("AI_TIMEOUT", "slow", retryable=True)
        )
        fake_ai.respond("Studied", study())
        calls = len(fake_ai.calls)
        worker.run_capture(sessions, uuid.UUID(capture_id), fake_ai, clock)
        worker.run_capture(sessions, uuid.UUID(capture_id), fake_ai, clock)  # already done
        assert len(fake_ai.calls) == calls + 1
        assert len(db.scalars(select(Event)).all()) == 1

    def test_it_knows_when_the_next_capture_is_due(self, client, auth, fake_ai, db, sessions):
        assert worker.seconds_until_next(db, 60) is None  # nothing pending
        needs_you = self._capture(client, auth, fake_ai, AIProviderError("AI_AUTH_FAILED", "key"))
        assert worker.seconds_until_next(db, 60) is None  # waits for the person, not the sweep
        busy = AIProviderError("AI_RATE_LIMITED", "busy", retryable=True)
        capture_id = self._capture(client, auth, fake_ai, busy)
        assert worker.seconds_until_next(db, 60) == 60  # the first retry, a minute after failing
        age(db, capture_id, 2)
        assert worker.seconds_until_next(db, 60) == 0  # overdue: now
        assert needs_you != capture_id

    def test_a_failure_wakes_the_sweep(self, client, auth, fake_ai, sessions):
        nudges = []
        signals.listen(lambda: nudges.append(1))
        try:
            self._capture(
                client, auth, fake_ai, AIProviderError("AI_TIMEOUT", "slow", retryable=True)
            )
        finally:
            signals.listen(None)
        assert nudges == [1]

    def test_a_broken_wake_up_never_breaks_saving(self, client, auth, fake_ai, db, sessions):
        def broken():
            raise RuntimeError("event loop is closed")

        signals.listen(broken)
        try:
            capture_id = self._capture(
                client, auth, fake_ai, AIProviderError("AI_TIMEOUT", "x", retryable=True)
            )
        finally:
            signals.listen(None)
        assert status_of(db, capture_id).processing_status == "FAILED"


def _loop(**timing):
    return worker.run_forever(
        lambda: nullcontext(None), lambda: None, None, retry_unit_seconds=1, **timing
    )


async def _until(condition, seconds: float = 10) -> bool:
    """Wait for the condition rather than a fixed time, so a busy machine can't fail a test."""
    deadline = asyncio.get_running_loop().time() + seconds
    while not condition() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
    return condition()


class TestTheLoop:
    """The loop the server runs: it sleeps while there's nothing to do, so a hosted database
    (Neon) can scale to zero even when the server is kept awake."""

    def test_it_survives_a_failing_sweep(self, monkeypatch):
        runs = []

        def flaky_sweep(*args):
            runs.append(1)
            if len(runs) == 1:
                raise RuntimeError("database briefly unreachable")
            return 0, 0.0  # something is due: look again after the shortest pause

        monkeypatch.setattr(worker, "sweep", flaky_sweep)

        async def scenario():
            task = asyncio.create_task(_loop(interval_seconds=0.01, idle_seconds=30))
            kept_going = await _until(lambda: len(runs) >= 3)
            alive = not task.done()
            task.cancel()
            return kept_going and alive

        assert asyncio.run(scenario()), "the loop stopped after a failed sweep"

    def test_with_nothing_pending_it_waits_until_a_capture_fails(self, monkeypatch):
        runs = []
        monkeypatch.setattr(worker, "sweep", lambda *args: runs.append(1) or (0, None))

        async def scenario():
            task = asyncio.create_task(_loop(interval_seconds=0.01, idle_seconds=30))
            await _until(lambda: len(runs) >= 1)
            await asyncio.sleep(0.5)
            while_idle = len(runs)
            signals.changed()  # what the pipeline does when a capture fails
            woke = await _until(lambda: len(runs) >= 2)
            task.cancel()
            return while_idle, woke

        while_idle, woke = asyncio.run(scenario())
        assert while_idle == 1, "an idle loop kept querying the database"
        assert woke, "a failed capture didn't wake the loop"

    def test_it_sleeps_until_the_next_retry_is_due(self, monkeypatch):
        sweeps: list[float] = []

        def sweep(*args):
            sweeps.append(time.monotonic())
            return 0, 0.3  # the next retry is due in 0.3 s

        monkeypatch.setattr(worker, "sweep", sweep)

        async def scenario():
            task = asyncio.create_task(_loop(interval_seconds=0.01, idle_seconds=30))
            done = await _until(lambda: len(sweeps) >= 3)
            task.cancel()
            return done

        assert asyncio.run(scenario()), "it didn't wake for the due retry"
        gaps = [later - earlier for earlier, later in zip(sweeps, sweeps[1:], strict=False)]
        assert all(gap >= 0.25 for gap in gaps), gaps  # not before it was due

    def test_it_stops_listening_when_the_server_stops(self, monkeypatch):
        monkeypatch.setattr(worker, "sweep", lambda *args: (0, None))

        async def scenario():
            task = asyncio.create_task(_loop(interval_seconds=0.01, idle_seconds=30))
            await asyncio.sleep(0.05)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        asyncio.run(scenario())
        assert signals._listener is None
