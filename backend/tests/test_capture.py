import uuid

from sqlalchemy import select

from app.ai.provider import AIProviderError
from app.captures.models import Capture
from app.events.models import Event
from tests import factories as f

MESSAGE = (
    "Today I studied AI for about three hours, worked on the tender app for two hours fixing the "
    "authentication bug, finally understood vector databases, skipped the gym, and spent 25 on lunch."
)


def setup_world(client, auth) -> dict:
    project = client.post(
        "/v1/projects", json={"name": "TenderPilot", "aliases": ["tender app"]}, headers=auth
    ).json()
    habit = client.post(
        "/v1/habits", json={"name": "Exercise", "target_count": 3}, headers=auth
    ).json()
    return {"project": project, "habit": habit}


def capture(client, auth, text, **extra):
    response = client.post("/v1/captures", json={"content": text, **extra}, headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def full_day_output():
    return f.output(
        events=[
            f.event(
                "STUDY",
                "AI study",
                "studied AI for about three hours",
                topic="AI",
                time=f.when(duration_minutes=180, duration_precision="approximate"),
            ),
            f.event(
                "PROJECT_WORK",
                "TenderPilot work",
                "worked on the tender app for two hours fixing the authentication bug",
                output="fixed the authentication bug",
                project=f.project("the tender app"),
                time=f.when(duration_minutes=120, duration_precision="exact"),
            ),
            f.event(
                "KNOWLEDGE",
                "Vector databases",
                "finally understood vector databases",
                knowledge=[f.knowledge("Vector databases", "reported_understanding")],
            ),
            f.event(
                "HABIT",
                "Gym missed",
                "skipped the gym",
                habit={"ref": "h1", "name": "gym", "status": "missed"},
            ),
            f.event("EXPENSE", "Lunch", "spent 25 on lunch", money=f.money("25", "food")),
        ]
    )


class TestMultiEventCapture:
    def test_one_message_updates_several_parts_of_the_system(self, client, auth, fake_ai, db):
        world = setup_world(client, auth)
        fake_ai.respond("studied AI", full_day_output())
        result = capture(client, auth, MESSAGE)

        assert result["capture"]["status"] == "PROCESSED"
        assert result["error"] is None
        types = [e["event_type"] for e in result["events_created"]]
        assert types == ["STUDY", "PROJECT_WORK", "KNOWLEDGE", "HABIT", "EXPENSE"]

        study, work, _, _, lunch = result["events_created"]
        assert study["duration_display"] == "~3h" and study["occurred_at"] is None
        assert study["time_precision"] == "DATE_ONLY" and study["occurred_on"] == "2026-10-04"
        assert work["projects"] == [{"id": world["project"]["id"], "name": "TenderPilot"}]
        assert (
            lunch["amount"] == "25.00"
            and lunch["currency"] == "MAD"
            and lunch["category"] == "food"
        )
        assert result["message"].startswith("Logged ~3h AI study, 2h TenderPilot work")
        assert [k["title"] for k in result["knowledge_created"]] == ["Vector databases"]
        assert result["clarifications"] == []

        habit_detail = client.get(f"/v1/habits/{world['habit']['id']}", headers=auth).json()
        assert habit_detail["recent"][0]["outcome"] == "MISSED"

        # Every event traces back to the same capture and to the user's exact words.
        events = db.scalars(select(Event)).all()
        assert {e.capture_id for e in events} == {uuid.UUID(result["capture"]["id"])}
        assert all(e.evidence and e.evidence in MESSAGE for e in events)

    def test_context_sent_to_the_model_uses_refs_not_ids(self, client, auth, fake_ai):
        world = setup_world(client, auth)
        fake_ai.respond("studied", f.output())
        capture(client, auth, "I studied today")
        prompt = fake_ai.calls[0]["user"]
        assert "p1: TenderPilot [ACTIVE] — also called: tender app" in prompt
        assert "h1: Exercise (3 per week)" in prompt
        assert world["project"]["id"] not in prompt
        assert "<message>\nI studied today\n</message>" in prompt

    def test_existing_knowledge_is_reused_and_understanding_only_rises(self, client, auth, fake_ai):
        client.post(
            "/v1/knowledge",
            json={"title": "Retrieval-Augmented Generation", "aliases": ["RAG"]},
            headers=auth,
        )
        fake_ai.respond(
            "RAG",
            f.output(
                events=[
                    f.event(
                        "STUDY",
                        "RAG study",
                        "studied RAG",
                        knowledge=[f.knowledge("RAG", "studied")],
                    )
                ]
            ),
        )
        result = capture(client, auth, "I studied RAG")
        assert result["knowledge_created"] == []
        items = client.get("/v1/knowledge", headers=auth).json()
        assert (
            len(items) == 1
            and items[0]["understanding_state"] == "STUDIED"
            and items[0]["evidence_count"] == 1
        )


class TestNeverInvent:
    def test_items_without_matching_evidence_are_dropped(self, client, auth, fake_ai):
        fake_ai.respond(
            "studied",
            f.output(
                events=[
                    f.event("STUDY", "AI study", "I studied AI"),
                    f.event(
                        "EXPENSE", "Coffee", "bought a coffee for 5", money=f.money("5", "food")
                    ),
                ]
            ),
        )
        result = capture(client, auth, "I studied AI yesterday")
        assert [e["title"] for e in result["events_created"]] == ["AI study"]
        assert any("Coffee" in w for w in result["warnings"])

    def test_future_events_are_not_logged(self, client, auth, fake_ai):
        fake_ai.respond(
            "tonight",
            f.output(
                events=[
                    f.event(
                        "STUDY", "Study", "study at 22:00 tonight", time=f.when(start_time="22:00")
                    )
                ]
            ),
        )
        result = capture(client, auth, "I will study at 22:00 tonight")
        assert result["events_created"] == []
        assert result["message"] == "I didn't find anything to record in that."

    def test_unreadable_amount_creates_no_number_and_asks(self, client, auth, fake_ai):
        fake_ai.respond(
            "a lot",
            f.output(
                events=[
                    f.event(
                        "EXPENSE",
                        "Shopping",
                        "spent a lot on shopping",
                        money=f.money("a lot", "shopping"),
                    )
                ]
            ),
        )
        result = capture(client, auth, "I spent a lot on shopping")
        assert result["events_created"][0]["amount"] is None
        assert result["clarifications"][0]["kind"] == "AMOUNT"
        assert result["capture"]["status"] == "NEEDS_CLARIFICATION"

    def test_no_currency_without_a_default(self, client, fake_ai):
        from tests.conftest import register

        tokens = register(client, "nocurrency@example.com", default_currency=None)
        auth = {"Authorization": f"Bearer {tokens['access_token']}"}
        fake_ai.respond(
            "lunch",
            f.output(
                events=[
                    f.event("EXPENSE", "Lunch", "spent 25 on lunch", money=f.money("25", "food"))
                ]
            ),
        )
        result = capture(client, auth, "spent 25 on lunch")
        assert result["events_created"][0]["currency"] is None


class TestReliability:
    def test_same_client_id_never_duplicates(self, client, auth, fake_ai, db):
        fake_ai.respond("studied", f.output(events=[f.event("STUDY", "Study", "studied")]))
        client_id = str(uuid.uuid4())
        first = capture(client, auth, "I studied", client_capture_id=client_id)
        second = capture(client, auth, "I studied", client_capture_id=client_id)
        assert first["capture"]["id"] == second["capture"]["id"]
        assert len(db.scalars(select(Event)).all()) == 1
        assert len(fake_ai.calls) == 1

    def test_accidental_double_submit_is_ignored(self, client, auth, fake_ai, db):
        fake_ai.respond("studied", f.output(events=[f.event("STUDY", "Study", "studied")]))
        capture(client, auth, "I studied")
        capture(client, auth, "I studied")
        assert len(db.scalars(select(Event)).all()) == 1

    def test_ai_failure_keeps_the_capture_and_retry_works(self, client, auth, fake_ai, db):
        fake_ai.error = AIProviderError("AI_RATE_LIMITED", "Rate limited", retryable=True)
        failed = capture(client, auth, "I studied for an hour")
        assert failed["capture"]["status"] == "FAILED"
        assert failed["error"]["code"] == "AI_RATE_LIMITED" and failed["error"]["retryable"]
        stored = db.get(Capture, uuid.UUID(failed["capture"]["id"]))
        assert stored.raw_text == "I studied for an hour"

        fake_ai.error = None
        fake_ai.respond(
            "studied",
            f.output(
                events=[
                    f.event(
                        "STUDY", "Study", "studied for an hour", time=f.when(duration_minutes=60)
                    )
                ]
            ),
        )
        retried = client.post(f"/v1/captures/{failed['capture']['id']}/retry", headers=auth).json()
        assert retried["capture"]["status"] == "PROCESSED"
        assert retried["events_created"][0]["duration_display"] == "1h"
        again = client.post(f"/v1/captures/{failed['capture']['id']}/retry", headers=auth)
        assert again.status_code == 409

    def test_ai_switched_off_still_saves_the_capture(self, client, auth, db):
        from app.ai.provider import get_ai_provider
        from app.main import app

        app.dependency_overrides[get_ai_provider] = lambda: None
        result = capture(client, auth, "I studied")
        assert result["error"]["code"] == "AI_NOT_CONFIGURED"
        assert db.scalar(select(Capture.raw_text)) == "I studied"


class TestQuestionsAndTasks:
    def test_questions_are_routed_to_the_assistant(self, client, auth, fake_ai):
        client.post(
            "/v1/events",
            json={"event_type": "EXPENSE", "title": "Lunch", "amount": "40", "category": "food"},
            headers=auth,
        )
        fake_ai.respond(
            "how much", f.output(intent="question", question="How much did I spend this week?")
        )
        fake_ai.tool_plan = [
            (
                "get_spending",
                {
                    "period": "this_week",
                    "start_date": None,
                    "end_date": None,
                    "kind": "expense",
                    "category": None,
                    "group_by": "none",
                },
            )
        ]
        fake_ai.answer = lambda records: (
            f"You spent {__import__('json').loads(records[0].output)['rows'][0]['display']} this week."
        )
        result = capture(client, auth, "how much did I spend this week?")
        assert result["events_created"] == []
        assert result["answer"]["text"] == "You spent 40 MAD this week."
        assert result["answer"]["evidence"][0]["tool"] == "get_spending"

    def test_tasks_are_created_and_completed(self, client, auth, fake_ai):
        fake_ai.respond(
            "need to",
            f.output(
                tasks=[
                    f.task(
                        "Finish the backend",
                        "need to finish the backend tomorrow",
                        due_kind="tomorrow",
                    )
                ]
            ),
        )
        created = capture(client, auth, "I need to finish the backend tomorrow")
        assert created["tasks_created"][0]["due_date"] == "2026-10-05"

        fake_ai.respond(
            "finished",
            f.output(
                events=[
                    f.event(
                        "PROJECT_WORK", "Backend", "finished the backend", completes_task_ref="t1"
                    )
                ]
            ),
        )
        done = capture(client, auth, "I finished the backend")
        assert done["tasks_completed"][0]["title"] == "Finish the backend"
        assert client.get("/v1/tasks", params={"open_only": True}, headers=auth).json() == []

    def test_duplicate_task_is_not_added_twice(self, client, auth, fake_ai):
        client.post("/v1/tasks", json={"title": "Finish the backend"}, headers=auth)
        fake_ai.respond(
            "need to", f.output(tasks=[f.task("Finish the backend", "need to finish the backend")])
        )
        result = capture(client, auth, "I need to finish the backend")
        assert result["tasks_created"] == []
        assert "already on your list" in result["warnings"][0]
