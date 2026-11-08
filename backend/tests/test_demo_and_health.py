"""The deterministic demo AI used by browser tests, and the health check deploys are verified with."""

import pytest

from app.ai.demo_provider import DemoAIProvider, understand
from app.ai.provider import get_ai_provider
from app.config import get_settings


@pytest.fixture
def demo(client):
    from app.main import app

    provider = DemoAIProvider()
    app.dependency_overrides[get_ai_provider] = lambda: provider
    return provider


def capture(client, auth, text):
    response = client.post("/v1/captures", json={"content": text}, headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


class TestDemoAI:
    def test_understands_the_basic_phrasings(self):
        out = understand(
            "Studied AI for 2 hours, worked on TenderPilot for 30 minutes and spent 30 on lunch"
        )
        kinds = [(e["event_type"], e["time"]["duration_minutes"]) for e in out["events"]]
        assert kinds == [("STUDY", 120.0), ("PROJECT_WORK", 30.0), ("EXPENSE", None)]
        assert out["events"][2]["money"]["category"] == "food"

    def test_its_output_passes_the_real_pipeline(self, client, auth, demo):
        result = capture(client, auth, "Studied AI for 2 hours and spent 30 dh on a taxi")
        created = {
            (e["event_type"], e["duration_display"], e["amount_display"])
            for e in result["events_created"]
        }
        assert created == {("STUDY", "2h", None), ("EXPENSE", None, "30 MAD")}
        assert result["warnings"] == []

    def test_tasks_and_habits(self, client, auth, demo):
        client.post("/v1/habits", json={"name": "Exercise"}, headers=auth)
        result = capture(client, auth, "I need to call the bank tomorrow")
        assert [t["title"] for t in result["tasks_created"]] == ["Call the bank"]
        result = capture(client, auth, "Went for a run this morning")
        assert result["events_created"][0]["event_type"] == "EXERCISE"

    def test_questions_are_answered_from_the_records(self, client, auth, demo):
        capture(client, auth, "Studied AI for 2 hours")
        result = capture(client, auth, "How much did I study this week?")
        assert result["answer"]["text"] == "You studied 2h this week."

    def test_failure_controls(self, client, auth, demo):
        failed = capture(client, auth, "Studied AI for 1 hour [fail]")
        assert failed["error"]["code"] == "AI_RATE_LIMITED"
        first = capture(client, auth, "Studied AI for 1 hour [fail once]")
        assert first["error"]["code"] == "AI_RATE_LIMITED"
        retried = client.post(f"/v1/captures/{first['capture']['id']}/retry", headers=auth).json()
        assert retried["events_created"]

    def test_it_is_never_used_in_production(self, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "demo")
        get_settings.cache_clear()
        assert isinstance(get_ai_provider(), DemoAIProvider)
        monkeypatch.setenv("RENDER", "true")
        get_settings.cache_clear()
        assert get_ai_provider() is None
        get_settings.cache_clear()


class TestHealth:
    def test_reports_the_deployed_commit(self, client, monkeypatch):
        assert client.get("/health").json()["release"] == "dev"
        monkeypatch.setenv("RENDER_GIT_COMMIT", "9fdc53dcc87b")
        get_settings.cache_clear()
        assert client.get("/health").json()["release"] == "9fdc53dcc87b"
        get_settings.cache_clear()
