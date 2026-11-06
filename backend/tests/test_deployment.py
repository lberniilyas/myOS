"""Behaviour that matters once the app runs on the public internet (Vercel) and on flaky networks."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.captures.models import Capture
from app.captures.pipeline import MAX_ATTEMPTS
from app.config import get_settings, sqlalchemy_url
from app.events.models import Event
from app.main import create_app
from tests import factories as f

PASSWORD = "correct horse battery"


@pytest.fixture
def production(monkeypatch):
    """Settings as they are on Vercel, which sets VERCEL=1 in every function."""
    monkeypatch.setenv("VERCEL", "1")
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def sign_up(client, email: str):
    return client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})


class TestPublicDeployment:
    def test_sign_up_is_closed_without_an_allowlist(self, client, production):
        response = sign_up(client, "stranger@example.com")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "REGISTRATION_CLOSED"

    def test_only_allowlisted_emails_can_sign_up(self, client, production):
        production.setenv("ALLOWED_EMAILS", "Me@Example.com, partner@example.com")
        get_settings.cache_clear()
        assert sign_up(client, "me@example.com").status_code == 201
        assert sign_up(client, "stranger@example.com").status_code == 403

    def test_sign_up_stays_open_for_local_development(self, client, monkeypatch):
        monkeypatch.setenv("ALLOWED_EMAILS", "")  # a blank line in .env changes nothing
        get_settings.cache_clear()
        assert sign_up(client, "dev@example.com").status_code == 201
        get_settings.cache_clear()

    def test_render_counts_as_production_too(self, client, monkeypatch):
        monkeypatch.setenv("RENDER", "true")  # set by Render in every service
        get_settings.cache_clear()
        response = sign_up(client, "stranger@example.com")
        get_settings.cache_clear()
        assert response.json()["error"]["code"] == "REGISTRATION_CLOSED"

    def test_the_app_sends_security_headers_when_it_serves_the_pages(self, monkeypatch):
        monkeypatch.setenv("RENDER", "true")
        get_settings.cache_clear()
        with TestClient(create_app()) as client:
            for path in ("/", "/health", "/v1/me"):
                headers = client.get(path).headers
                assert "frame-ancestors 'none'" in headers["content-security-policy"], path
                assert headers["x-content-type-options"] == "nosniff"
        get_settings.cache_clear()

    def test_on_vercel_the_platform_adds_them_instead(self, production):
        # vercel.json sets them there; sending them twice would make X-Frame-Options invalid.
        with TestClient(create_app()) as client:
            assert "content-security-policy" not in client.get("/health").headers

    def test_api_docs_are_hidden(self, production):
        # Locally the web app answers unknown paths with its own page, so check the content.
        with TestClient(create_app()) as client:
            assert "swagger" not in client.get("/docs").text.lower()
            assert '"openapi"' not in client.get("/openapi.json").text

    @pytest.mark.parametrize(
        "given,expected",
        [
            (
                "postgres://u:p@host.neon.tech/db?sslmode=require",
                "postgresql+psycopg://u:p@host.neon.tech/db?sslmode=require",
            ),
            ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
            ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ],
    )
    def test_hosted_database_urls_are_accepted(self, given, expected):
        assert sqlalchemy_url(given) == expected


def send(client, auth, text_: str, client_id: str):
    response = client.post(
        "/v1/captures", json={"content": text_, "client_capture_id": client_id}, headers=auth
    )
    assert response.status_code == 200, response.text
    return response.json()


def studied():
    return f.output(events=[f.event("STUDY", "AI study", "Studied AI")])


class TestCapturesSurviveFailures:
    """The app resends anything not processed yet with the same id, so a resend is the retry."""

    def test_an_unexpected_ai_crash_fails_cleanly_and_the_resend_processes_it(
        self, client, auth, fake_ai, db, monkeypatch
    ):
        def crash(**_):
            raise RuntimeError("the SDK raised something new")

        client_id = str(uuid.uuid4())
        monkeypatch.setattr(fake_ai, "generate_structured", crash)
        failed = send(client, auth, "Studied AI", client_id)
        assert failed["capture"]["status"] == "FAILED"
        assert failed["error"] == {
            "code": "AI_ERROR",
            "message": "Something went wrong while understanding this.",
            "retryable": True,
        }

        monkeypatch.undo()
        fake_ai.respond("Studied", studied())
        done = send(client, auth, "Studied AI", client_id)
        assert done["capture"]["status"] == "PROCESSED" and done["events_created"]
        assert db.scalar(select(Capture.attempts)) == 2

    def test_a_capture_cut_off_mid_run_is_picked_up_again(self, client, auth, fake_ai, db):
        fake_ai.respond("Studied", studied())
        client_id = str(uuid.uuid4())
        first = send(client, auth, "Studied AI", client_id)
        # What a Vercel timeout or a restart during the AI call leaves behind.
        db.execute(
            text(
                "update captures set processing_status = 'PROCESSING', result = null, "
                "updated_at = now() - interval '11 minutes' where id = :id"
            ),
            {"id": first["capture"]["id"]},
        )
        db.execute(text("delete from events"))
        db.expire_all()

        again = send(client, auth, "Studied AI", client_id)
        assert again["capture"]["status"] == "PROCESSED"
        assert db.scalar(select(func.count(Event.id))) == 1

    def test_the_retry_endpoint_also_takes_stuck_captures(self, client, auth, fake_ai, db):
        fake_ai.respond("Studied", studied())
        first = send(client, auth, "Studied AI", str(uuid.uuid4()))
        db.execute(
            text(
                "update captures set processing_status = 'PROCESSING', "
                "updated_at = now() - interval '11 minutes' where id = :id"
            ),
            {"id": first["capture"]["id"]},
        )
        db.expire_all()
        response = client.post(f"/v1/captures/{first['capture']['id']}/retry", headers=auth)
        assert response.status_code == 200

    def test_a_capture_still_running_is_never_run_twice(self, client, auth, fake_ai, db):
        fake_ai.respond("Studied", studied())
        client_id = str(uuid.uuid4())
        first = send(client, auth, "Studied AI", client_id)
        # Another request is still running it (it started less than a minute ago).
        db.execute(
            text(
                "update captures set processing_status = 'PROCESSING', result = null where id = :id"
            ),
            {"id": first["capture"]["id"]},
        )
        db.expire_all()
        calls = len(fake_ai.calls)

        again = send(client, auth, "Studied AI", client_id)
        assert again["error"]["code"] == "STILL_PROCESSING" and again["error"]["retryable"]
        assert len(fake_ai.calls) == calls
        retry = client.post(f"/v1/captures/{first['capture']['id']}/retry", headers=auth)
        assert retry.status_code == 409

    def test_retries_stop_after_the_attempt_limit(self, client, auth, fake_ai, db):
        client_id = str(uuid.uuid4())
        failed = send(client, auth, "Studied AI", client_id)  # no scripted reply: it fails
        db.execute(
            text("update captures set attempts = :n where id = :id"),
            {"n": MAX_ATTEMPTS, "id": failed["capture"]["id"]},
        )
        db.expire_all()
        calls = len(fake_ai.calls)

        again = send(client, auth, "Studied AI", client_id)
        assert again["error"]["retryable"] is False
        assert len(fake_ai.calls) == calls

    def test_a_processed_capture_is_never_redone(self, client, auth, fake_ai, db):
        fake_ai.respond("Studied", studied())
        client_id = str(uuid.uuid4())
        send(client, auth, "Studied AI", client_id)
        again = send(client, auth, "Studied AI", client_id)
        assert again["error"] is None
        assert db.scalar(select(func.count(Event.id))) == 1
