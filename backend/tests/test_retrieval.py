import json
from datetime import datetime
from zoneinfo import ZoneInfo

from tests import factories as f
from tests.test_capture import capture


def manual(client, auth, **body):
    response = client.post("/v1/events", json=body, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


class TestEvents:
    def test_manual_event_with_times(self, client, auth):
        zone = ZoneInfo("Africa/Casablanca")
        event = manual(
            client,
            auth,
            event_type="STUDY",
            title="Deep work",
            occurred_at=datetime(2026, 10, 4, 14, 0, tzinfo=zone).isoformat(),
            ended_at=datetime(2026, 10, 4, 16, 30, tzinfo=zone).isoformat(),
        )
        assert event["duration_display"] == "2h 30m"
        assert event["local_time"] == "14:00" and event["time_precision"] == "EXACT"
        assert event["provenance"]["source_type"] == "MANUAL_INPUT"

    def test_patch_records_history(self, client, auth):
        event = manual(
            client, auth, event_type="EXPENSE", title="Lunch", amount="25", category="food"
        )
        assert event["currency"] == "MAD"
        updated = client.patch(
            f"/v1/events/{event['id']}", json={"amount": "30", "title": "Big lunch"}, headers=auth
        ).json()
        assert updated["amount"] == "30.00" and updated["revision_count"] == 1
        bad = client.patch(f"/v1/events/{event['id']}", json={"currency": "XYZ"}, headers=auth)
        assert bad.status_code == 422

    def test_permanent_delete(self, client, auth):
        event = manual(client, auth, event_type="STUDY", title="Oops")
        assert (
            client.delete(f"/v1/events/{event['id']}?permanent=true", headers=auth).status_code
            == 204
        )
        assert client.get(f"/v1/events/{event['id']}", headers=auth).status_code == 404


class TestTimeline:
    def test_newest_first_with_cursor_pagination(self, client, auth):
        for day in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"):
            manual(client, auth, event_type="STUDY", title=f"Study {day}", occurred_on=day)
        first = client.get("/v1/timeline", params={"limit": 3}, headers=auth).json()
        assert [e["occurred_on"] for e in first["items"]] == [
            "2026-10-04",
            "2026-10-03",
            "2026-10-02",
        ]
        second = client.get(
            "/v1/timeline", params={"limit": 3, "cursor": first["next_cursor"]}, headers=auth
        ).json()
        assert [e["occurred_on"] for e in second["items"]] == ["2026-10-01"]
        assert second["next_cursor"] is None
        assert (
            client.get("/v1/timeline", params={"cursor": "garbage"}, headers=auth).status_code
            == 422
        )

    def test_filters_and_search(self, client, auth, fake_ai):
        project = client.post("/v1/projects", json={"name": "TenderPilot"}, headers=auth).json()
        manual(
            client, auth, event_type="PROJECT_WORK", title="Auth fix", project_ids=[project["id"]]
        )
        manual(client, auth, event_type="STUDY", title="Vector databases reading")
        by_project = client.get(
            "/v1/timeline", params={"project_id": project["id"]}, headers=auth
        ).json()
        assert [e["title"] for e in by_project["items"]] == ["Auth fix"]
        by_type = client.get("/v1/timeline", params={"event_type": ["STUDY"]}, headers=auth).json()
        assert [e["title"] for e in by_type["items"]] == ["Vector databases reading"]
        found = client.get("/v1/search", params={"q": "vector"}, headers=auth).json()
        assert [e["title"] for e in found["events"]] == ["Vector databases reading"]
        assert (
            client.get("/v1/search", params={"q": "tender"}, headers=auth).json()["projects"][0][
                "name"
            ]
            == "TenderPilot"
        )


class TestDailySummary:
    def test_totals_only_include_recorded_data(self, client, auth, fake_ai):
        fake_ai.respond(
            "studied",
            f.output(
                events=[
                    f.event(
                        "STUDY",
                        "AI study",
                        "studied AI for 2 hours",
                        time=f.when(duration_minutes=120),
                    ),
                    f.event(
                        "STUDY",
                        "Math",
                        "math for about an hour",
                        time=f.when(duration_minutes=60, duration_precision="approximate"),
                    ),
                    f.event("EXPENSE", "Lunch", "25 on lunch", money=f.money("25", "food")),
                    f.event(
                        "EXPENSE",
                        "Taxi",
                        "10 euros taxi",
                        money=f.money("10", "transport", currency="EUR"),
                    ),
                    f.event(
                        "DEVICE_USAGE",
                        "YouTube",
                        "YouTube for 2 hours",
                        device={"device": "phone", "application": "YouTube"},
                        time=f.when(duration_minutes=120),
                    ),
                ]
            ),
        )
        capture(
            client,
            auth,
            "I studied AI for 2 hours, math for about an hour, 25 on lunch, 10 euros taxi, YouTube for 2 hours",
        )
        summary = client.get("/v1/summary/daily", headers=auth).json()
        assert summary["date"] == "2026-10-04"
        study = next(row for row in summary["time"] if row["key"] == "STUDY")
        assert (
            study["seconds"] == 3 * 3600
            and study["display"] == "~3h"
            and study["approximate_events"] == 1
        )
        assert {(s["currency"], s["amount"]) for s in summary["spending"]} == {
            ("MAD", "25.00"),
            ("EUR", "10.00"),
        }
        assert summary["devices"] == [{"device": "phone", "seconds": 7200, "display": "2h"}]
        assert summary["income"] == [] and summary["habits"] == []
        assert len(summary["recent_events"]) == 5
        empty = client.get("/v1/summary/daily", params={"date": "2026-10-01"}, headers=auth).json()
        assert empty["events_count"] == 0 and empty["time"] == []


class TestAssistant:
    def test_tools_compute_numbers_deterministically(self, client, auth, fake_ai):
        for day, minutes in (
            ("2026-09-29", 120),
            ("2026-09-30", 180),
            ("2026-10-01", 60),
            ("2026-09-21", 600),
        ):
            manual(
                client,
                auth,
                event_type="STUDY",
                title="Study",
                occurred_on=day,
                duration_minutes=minutes,
            )
        fake_ai.tool_plan = [
            (
                "get_activity_totals",
                {
                    "period": "this_week",
                    "start_date": None,
                    "end_date": None,
                    "event_types": ["STUDY"],
                    "project": None,
                    "group_by": "none",
                },
            ),
            ("get_project_summary", {"project": "Nonexistent"}),
        ]
        captured = {}

        def answer(records):
            captured["records"] = records
            return "You studied 6h this week."

        fake_ai.answer = answer
        response = client.post(
            "/v1/assistant/query", json={"message": "How much did I study this week?"}, headers=auth
        )
        assert response.status_code == 200
        totals, missing = captured["records"]
        rows = json.loads(totals.output)["rows"]
        assert rows[0]["seconds"] == 6 * 3600 and rows[0]["events"] == 3
        assert missing.is_error and "No project matches" in missing.output
        assert response.json()["evidence"][0] == {
            "tool": "get_activity_totals",
            "input": fake_ai.tool_plan[0][1],
            "ok": True,
        }
        assert "Weeks start on: Monday" in fake_ai.calls[0]["user"]

    def test_invalid_tool_arguments_are_reported_to_the_model(self, client, auth, fake_ai):
        fake_ai.tool_plan = [("get_spending", {"period": "someday"})]
        records = {}
        fake_ai.answer = lambda r: records.setdefault("r", r) and "ok"
        client.post("/v1/assistant/query", json={"message": "spend?"}, headers=auth)
        assert records["r"][0].is_error


def test_knowledge_search_explains_how_to_recover(client, auth, fake_ai):
    client.post("/v1/knowledge", json={"title": "Vector databases"}, headers=auth)
    args = {"period": "all_time", "start_date": None, "end_date": None}
    fake_ai.tool_plan = [
        ("search_knowledge", {**args, "text": "learned"}),
        ("search_knowledge", {**args, "text": None}),
    ]
    seen = {}
    fake_ai.answer = lambda records: seen.setdefault("r", records) and "ok"
    client.post("/v1/assistant/query", json={"message": "what did I learn?"}, headers=auth)
    by_name, everything = (json.loads(r.output) for r in seen["r"])
    assert by_name["knowledge"] == [] and "text=null" in by_name["note"]
    assert [k["title"] for k in everything["knowledge"]] == ["Vector databases"]


def test_project_totals_grouped_by_project_and_filtered_to_one(client, auth, fake_ai):
    project = client.post("/v1/projects", json={"name": "TenderPilot"}, headers=auth).json()
    manual(
        client,
        auth,
        event_type="PROJECT_WORK",
        title="Work",
        duration_minutes=90,
        project_ids=[project["id"]],
    )
    args = {"period": "today", "start_date": None, "end_date": None, "event_types": None}
    fake_ai.tool_plan = [
        ("get_activity_totals", {**args, "project": "TenderPilot", "group_by": "project"})
    ]
    seen = {}
    fake_ai.answer = lambda records: seen.setdefault("r", records) and "ok"
    assert (
        client.post("/v1/assistant/query", json={"message": "q"}, headers=auth).status_code == 200
    )
    rows = json.loads(seen["r"][0].output)["rows"]
    assert rows == [{**rows[0], "label": "TenderPilot", "seconds": 5400}]


def test_assistant_can_see_open_tasks(client, auth, fake_ai):
    client.post("/v1/tasks", json={"title": "Finish RAG", "due_date": "2026-10-05"}, headers=auth)
    client.post("/v1/tasks", json={"title": "Old", "due_date": "2026-10-01"}, headers=auth)
    fake_ai.tool_plan = [("list_tasks", {"include_done": False})]
    seen = {}
    fake_ai.answer = lambda records: seen.setdefault("r", records) and "ok"
    client.post("/v1/assistant/query", json={"message": "what's next?"}, headers=auth)
    tasks = json.loads(seen["r"][0].output)["tasks"]
    assert [(t["title"], t["overdue"]) for t in tasks] == [("Old", True), ("Finish RAG", False)]
