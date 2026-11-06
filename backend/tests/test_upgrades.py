"""Fixes from the November 2026 audit: nothing silently lost, true numbers, undoable deletes,
search that finds things, visible failures, a sign-in that lasts, and clean input handling."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from app.auth.models import AuthSession
from app.captures.time_resolution import resolve_time
from app.core.money import parse_amount
from app.core.text import evidence_match
from app.events.models import Event
from tests import factories as f
from tests.conftest import register


def capture(client, auth, fake_ai, message: str, output) -> dict:
    fake_ai.respond(message, output)
    response = client.post("/v1/captures", json={"content": message}, headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def study(message: str = "Studied AI for 2 hours", minutes: int = 120, precision: str = "exact"):
    return f.output(
        events=[
            f.event(
                "STUDY",
                "AI study",
                message,
                topic="AI",
                time=f.when(duration_minutes=minutes, duration_precision=precision),
            )
        ]
    )


def answer(client, auth, question: dict, option: str) -> dict:
    response = client.post(
        f"/v1/clarifications/{question['id']}/answer", json={"option_id": option}, headers=auth
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestNothingSilentlyLost:
    @pytest.mark.parametrize(
        "message,quote,expected",
        [
            (
                "Oh and I paid 300 dirhams for my internet bill.",
                "I also paid 300 dirhams for my internet bill",
                "close",
            ),
            ("I didn't go to the gym today", "I went to the gym", "partial"),
            ("I studied AI", "I studied AI for 3 hours", "none"),
            ("Spent 25 on lunch", "Spent 25 on lunch", "exact"),
            ("Spent 25 on lunch", "lunch", "exact"),
            ("Spent 25 on lunch", "dinner", "none"),
            ("j'ai payé 300 dh pour internet", "et j'ai payé 300 dh pour internet", "close"),
        ],
    )
    def test_evidence_is_graded(self, message, quote, expected):
        assert evidence_match(message, quote) == expected

    def test_a_quote_reworded_only_in_filler_words_is_kept(self, client, auth, fake_ai):
        message = "I was tired. Oh and I paid 300 dirhams for my internet bill."
        result = capture(
            client,
            auth,
            fake_ai,
            message,
            f.output(
                events=[
                    f.event(
                        "EXPENSE",
                        "Internet bill",
                        "I also paid 300 dirhams for my internet bill",
                        money=f.money("300", "utilities", "MAD"),
                    )
                ]
            ),
        )
        assert [e["amount_display"] for e in result["events_created"]] == ["300 MAD"]
        assert result["clarifications"] == [] and result["warnings"] == []

    def test_a_quote_that_may_differ_in_meaning_is_saved_and_confirmed(self, client, auth, fake_ai):
        result = capture(
            client,
            auth,
            fake_ai,
            "I didn't go to the gym today",
            f.output(events=[f.event("EXERCISE", "Gym", "I went to the gym")]),
        )
        assert len(result["events_created"]) == 1
        question = result["clarifications"][0]
        assert question["kind"] == "CONFIRM" and "Keep “Gym”" in question["question"]
        done = answer(client, auth, question, "remove")
        assert done["events"] == []
        assert client.get("/v1/timeline", headers=auth).json()["items"] == []

    def test_keeping_a_confirmed_record(self, client, auth, fake_ai, db):
        result = capture(
            client,
            auth,
            fake_ai,
            "I didn't go to the gym today",
            f.output(events=[f.event("EXERCISE", "Gym", "I went to the gym")]),
        )
        answer(client, auth, result["clarifications"][0], "keep")
        event = db.get(Event, uuid.UUID(result["events_created"][0]["id"]))
        assert event.deleted_at is None
        assert event.structured_data["evidence_check"] == "confirmed"

    def test_a_quote_with_a_number_not_in_the_message_is_dropped(self, client, auth, fake_ai):
        result = capture(
            client, auth, fake_ai, "I studied AI", study("I studied AI for 3 hours", 180)
        )
        assert result["events_created"] == []
        assert any("couldn't be traced" in w for w in result["warnings"])

    def test_a_past_twelve_hour_time_that_would_be_in_the_future_is_read_as_morning(
        self, client, auth, fake_ai, clock
    ):
        clock.moment = datetime(2026, 10, 4, 11, 19, tzinfo=UTC)  # 11:19 in Casablanca
        message = "Around 5 I had a call with a client for 20 minutes."
        result = capture(
            client,
            auth,
            fake_ai,
            message,
            f.output(
                events=[
                    f.event(
                        "WORK",
                        "Client call",
                        "Around 5 I had a call with a client for 20 minutes",
                        time=f.when(
                            start_time="17:00",
                            clock_precision="approximate",
                            duration_minutes=20,
                            duration_precision="exact",
                            expression="Around 5 ... for 20 minutes",
                        ),
                    )
                ]
            ),
        )
        [event] = result["events_created"]
        assert event["local_time"] == "05:00" and event["duration_display"] == "20m"
        assert any("Read the time as 05:00" in w for w in result["warnings"])

    @pytest.mark.parametrize(
        "evidence",
        ["I'll call the client at 5", "call with the client at 5pm", "call at 17:00"],
    )
    def test_future_or_explicit_afternoon_times_are_not_moved(
        self, client, auth, fake_ai, clock, evidence
    ):
        clock.moment = datetime(2026, 10, 4, 11, 19, tzinfo=UTC)
        result = capture(
            client,
            auth,
            fake_ai,
            evidence,
            f.output(
                events=[f.event("WORK", "Client call", evidence, time=f.when(start_time="17:00"))]
            ),
        )
        assert result["events_created"] == []


class TestNumbersStayTrue:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1.200", Decimal("1200.00")),
            ("12.500", Decimal("12500.00")),
            ("1.200,50", Decimal("1200.50")),
            ("1 200", Decimal("1200.00")),
            ("0.500", Decimal("0.50")),
            ("12.50", Decimal("12.50")),
            ("١٢", Decimal("12.00")),
            ("1e3", None),
            ("+5", None),
            ("Infinity", None),
        ],
    )
    def test_amounts(self, raw, expected):
        assert parse_amount(raw) == expected

    def test_durations_count_real_time_across_a_clock_change(self):
        zone = ZoneInfo("America/New_York")
        now = datetime(2026, 11, 1, 12, 0, tzinfo=zone)  # clocks went back at 02:00 that night
        spanned = resolve_time(f.when(start_time="00:30", end_time="03:30"), now)
        assert spanned.duration_seconds == 4 * 3600
        timed = resolve_time(f.when(start_time="00:30", duration_minutes=240), now)
        assert timed.ended_at.strftime("%H:%M") == "03:30"

    def test_editing_the_title_keeps_an_approximate_duration(self, client, auth, fake_ai):
        result = capture(
            client, auth, fake_ai, "Studied AI for about 2 hours", study(precision="approximate")
        )
        event_id = result["events_created"][0]["id"]
        # What the edit form sends: the new title and the minutes it shows.
        edited = client.patch(
            f"/v1/events/{event_id}",
            json={"title": "AI study, edited", "duration_minutes": 120},
            headers=auth,
        ).json()
        assert edited["duration_precision"] == "APPROXIMATE" and edited["duration_seconds"] == 7200
        changed = client.patch(
            f"/v1/events/{event_id}", json={"duration_minutes": 90}, headers=auth
        ).json()
        assert changed["duration_precision"] == "EXACT" and changed["duration_seconds"] == 5400

    def test_an_amount_typed_by_hand_gets_the_usual_currency(self, client, auth, fake_ai):
        result = capture(
            client,
            auth,
            fake_ai,
            "Bought a phone",
            f.output(events=[f.event("EXPENSE", "Phone", "Bought a phone", money=f.money(None))]),
        )
        event_id = result["events_created"][0]["id"]
        edited = client.patch(f"/v1/events/{event_id}", json={"amount": "2500"}, headers=auth)
        assert edited.json()["amount_display"] == "2500 MAD"

    def test_an_expense_without_amount_is_not_shown_as_zero(self, client, auth, fake_ai):
        capture(
            client,
            auth,
            fake_ai,
            "Bought a phone",
            f.output(events=[f.event("EXPENSE", "Phone", "Bought a phone", money=f.money(None))]),
        )
        [row] = client.get("/v1/summary/daily", headers=auth).json()["spending"]
        assert row["display"] is None and row["events_without_amount"] == 1

    def test_splitting_never_asks_whether_the_parts_repeat_the_original(
        self, client, auth, fake_ai
    ):
        capture(
            client, auth, fake_ai, "Studied AI for 3 hours", study("Studied AI for 3 hours", 180)
        )
        message = "split that: 2 hours of AI and 1 hour of math"
        result = capture(
            client,
            auth,
            fake_ai,
            message,
            f.output(
                intent="correct",
                corrections=[
                    f.correction(
                        "split",
                        "split that",
                        target_ref="e1",
                        split_into=[
                            f.event(
                                "STUDY",
                                "AI study",
                                "2 hours of AI",
                                topic="AI",
                                time=f.when(duration_minutes=120, duration_precision="exact"),
                            ),
                            f.event(
                                "STUDY",
                                "Math study",
                                "1 hour of math",
                                topic="Math",
                                time=f.when(duration_minutes=60, duration_precision="exact"),
                            ),
                        ],
                    )
                ],
            ),
        )
        assert len(result["events_created"]) == 2 and result["clarifications"] == []

    def test_deleting_an_entry_reopens_the_task_it_completed(self, client, auth, fake_ai):
        task = client.post("/v1/tasks", json={"title": "Write the report"}, headers=auth).json()
        message = "Finished writing the report"
        result = capture(
            client,
            auth,
            fake_ai,
            message,
            f.output(events=[f.event("TASK_ACTIVITY", "Report", message, completes_task_ref="t1")]),
        )
        event_id = result["events_created"][0]["id"]
        status = lambda: client.get(f"/v1/tasks/{task['id']}", headers=auth).json()["status"]  # noqa: E731
        assert status() == "COMPLETED"
        client.delete(f"/v1/events/{event_id}", headers=auth)
        assert status() == "TODO"
        client.post(f"/v1/events/{event_id}/restore", headers=auth)
        assert status() == "COMPLETED"

    def test_questions_about_a_deleted_entry_go_away(self, client, auth, fake_ai):
        result = capture(
            client,
            auth,
            fake_ai,
            "Worked for a while",
            f.output(
                events=[
                    f.event(
                        "WORK",
                        "Work",
                        "Worked for a while",
                        time=f.when(duration_precision="vague"),
                    )
                ]
            ),
        )
        assert client.get("/v1/clarifications", headers=auth).json()
        client.delete(f"/v1/events/{result['events_created'][0]['id']}", headers=auth)
        assert client.get("/v1/clarifications", headers=auth).json() == []
        stored = client.get(f"/v1/captures/{result['capture']['id']}", headers=auth).json()
        assert stored["capture"]["status"] == "PROCESSED"


class TestSaferDeleting:
    def _three_expenses(self, client, auth, fake_ai):
        for index in range(3):
            message = f"Spent {index + 10} on thing {index}"
            capture(
                client,
                auth,
                fake_ai,
                message,
                f.output(
                    events=[
                        f.event(
                            "EXPENSE",
                            f"Thing {index}",
                            message,
                            money=f.money(str(index + 10), "other"),
                        )
                    ]
                ),
            )

    def test_one_clear_delete_runs_at_once(self, client, auth, fake_ai):
        capture(client, auth, fake_ai, "Studied AI for 2 hours", study())
        result = capture(
            client,
            auth,
            fake_ai,
            "delete that",
            f.output(intent="correct", corrections=[f.correction("delete", "delete that", "e1")]),
        )
        assert [e["title"] for e in result["events_deleted"]] == ["AI study"]

    def test_a_delete_the_model_isnt_sure_about_is_asked_first(self, client, auth, fake_ai):
        capture(client, auth, fake_ai, "Studied AI for 2 hours", study())
        unsure = f.correction("delete", "maybe drop that", "e1").model_copy(
            update={"confidence": 0.3}
        )
        result = capture(
            client,
            auth,
            fake_ai,
            "hmm maybe drop that",
            f.output(intent="correct", corrections=[unsure]),
        )
        assert result["events_deleted"] == []
        [question] = result["clarifications"]
        assert question["kind"] == "CONFIRM" and question["question"].startswith("Delete “AI study")
        assert result["message"] == question["question"]

    def test_many_deletes_from_one_message_wait_for_a_yes(self, client, auth, fake_ai):
        self._three_expenses(client, auth, fake_ai)
        message = "delete everything from today"
        result = capture(
            client,
            auth,
            fake_ai,
            message,
            f.output(
                intent="correct",
                corrections=[f.correction("delete", message, f"e{i}") for i in (1, 2, 3)],
            ),
        )
        assert result["events_deleted"] == []
        question = result["clarifications"][0]
        assert question["question"].startswith("Delete these 3 entries")
        assert len(client.get("/v1/timeline", headers=auth).json()["items"]) == 3
        answer(client, auth, question, "remove")
        assert client.get("/v1/timeline", headers=auth).json()["items"] == []

    def test_keeping_them_changes_nothing(self, client, auth, fake_ai):
        self._three_expenses(client, auth, fake_ai)
        message = "delete everything from today"
        result = capture(
            client,
            auth,
            fake_ai,
            message,
            f.output(
                intent="correct",
                corrections=[f.correction("delete", message, f"e{i}") for i in (1, 2, 3)],
            ),
        )
        answer(client, auth, result["clarifications"][0], "keep")
        assert len(client.get("/v1/timeline", headers=auth).json()["items"]) == 3

    def test_recently_deleted_lists_newest_first_and_restores(self, client, auth, clock):
        ids = []
        for title in ("First", "Second"):
            ids.append(
                client.post(
                    "/v1/events", json={"event_type": "OTHER", "title": title}, headers=auth
                ).json()["id"]
            )
        client.delete(f"/v1/events/{ids[0]}", headers=auth)
        clock.moment += timedelta(minutes=1)
        client.delete(f"/v1/events/{ids[1]}", headers=auth)
        deleted = client.get("/v1/events/deleted", headers=auth).json()
        assert [e["title"] for e in deleted] == ["Second", "First"] and deleted[0]["deleted_at"]
        client.post(f"/v1/events/{ids[0]}/restore", headers=auth)
        assert [e["title"] for e in client.get("/v1/events/deleted", headers=auth).json()] == [
            "Second"
        ]

    def test_a_permanent_delete_also_erases_the_words(self, client, auth, fake_ai):
        message = "Saw my doctor about a private thing"
        result = capture(
            client, auth, fake_ai, message, f.output(events=[f.event("OTHER", "Doctor", message)])
        )
        event_id = result["events_created"][0]["id"]
        assert (
            client.delete(f"/v1/events/{event_id}?permanent=true", headers=auth).status_code == 204
        )
        export = json.dumps(client.get("/v1/me/export", headers=auth).json(), ensure_ascii=False)
        assert "private thing" not in export

    def test_the_words_stay_while_another_entry_comes_from_them(self, client, auth, fake_ai):
        message = "Studied AI and spent 30 on food"
        result = capture(
            client,
            auth,
            fake_ai,
            message,
            f.output(
                events=[
                    f.event("STUDY", "AI study", "Studied AI"),
                    f.event("EXPENSE", "Food", "spent 30 on food", money=f.money("30", "food")),
                ]
            ),
        )
        first = result["events_created"][0]["id"]
        client.delete(f"/v1/events/{first}?permanent=true", headers=auth)
        stored = client.get(f"/v1/captures/{result['capture']['id']}", headers=auth)
        assert stored.status_code == 200


class TestSearchFindsThings:
    @pytest.fixture
    def world(self, client, auth, fake_ai):
        client.post(
            "/v1/projects", json={"name": "TenderPilot", "aliases": ["tender app"]}, headers=auth
        )
        message = "Fixed the auth bug and read about retrieval, lunch with Sara for 25"
        capture(
            client,
            auth,
            fake_ai,
            message,
            f.output(
                events=[
                    f.event(
                        "PROJECT_WORK",
                        "Bug fix",
                        "Fixed the auth bug",
                        project=f.project("x", "p1"),
                    ),
                    f.event(
                        "KNOWLEDGE",
                        "Reading",
                        "read about retrieval",
                        knowledge=[f.knowledge("Retrieval-Augmented Generation", aliases=["RAG"])],
                    ),
                    f.event(
                        "EXPENSE", "Meal", "lunch with Sara for 25", money=f.money("25", "food")
                    ),
                ]
            ),
        )

    @pytest.mark.parametrize(
        "query,title",
        [
            ("TenderPilot", "Bug fix"),
            ("tender app", "Bug fix"),
            ("RAG", "Reading"),
            ("Sara", "Meal"),
            ("food", "Meal"),
        ],
    )
    def test_timeline_search(self, client, auth, world, query, title):
        items = client.get("/v1/timeline", params={"q": query}, headers=auth).json()["items"]
        assert [e["title"] for e in items] == [title]

    @pytest.mark.parametrize("query", ["%", "_", "\\"])
    def test_typed_wildcards_match_literally(self, client, auth, world, query):
        assert client.get("/v1/timeline", params={"q": query}, headers=auth).json()["items"] == []
        assert client.get("/v1/search", params={"q": query}, headers=auth).json()["projects"] == []


class TestFailedEntriesAreVisible:
    def test_failed_and_stuck_entries_are_listed(self, client, auth, fake_ai, db):
        failed = client.post(
            "/v1/captures",
            json={"content": "No reply scripted", "client_capture_id": str(uuid.uuid4())},
            headers=auth,
        ).json()
        capture(client, auth, fake_ai, "Studied AI for 2 hours", study())
        stuck = capture(client, auth, fake_ai, "Studied math", study("Studied math"))
        db.execute(
            text(
                "update captures set processing_status = 'PROCESSING', "
                "updated_at = now() - interval '11 minutes' where id = :id"
            ),
            {"id": stuck["capture"]["id"]},
        )
        listed = client.get("/v1/captures?unfinished=true", headers=auth).json()
        assert {c["id"] for c in listed} == {failed["capture"]["id"], stuck["capture"]["id"]}
        assert all(
            c["client_capture_id"] is not None or c["id"] == stuck["capture"]["id"] for c in listed
        )

    def test_a_failed_message_can_be_removed_with_its_words(self, client, auth):
        failed = client.post(
            "/v1/captures", json={"content": "No reply scripted"}, headers=auth
        ).json()
        assert (
            client.delete(f"/v1/captures/{failed['capture']['id']}", headers=auth).status_code
            == 204
        )
        assert client.get("/v1/captures", headers=auth).json() == []

    def test_a_message_with_entries_cant_be_removed_from_under_them(self, client, auth, fake_ai):
        result = capture(client, auth, fake_ai, "Studied AI for 2 hours", study())
        response = client.delete(f"/v1/captures/{result['capture']['id']}", headers=auth)
        assert response.status_code == 409


class TestStaysSignedIn:
    def test_the_session_lasts_a_year_and_each_refresh_extends_it(self, client, db, clock):
        tokens = register(client)
        expires = datetime.fromisoformat(tokens["refresh_expires_at"])
        assert expires - clock.now() == timedelta(days=365)
        clock.moment += timedelta(days=300)
        later = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert later.status_code == 200
        assert datetime.fromisoformat(
            later.json()["refresh_expires_at"]
        ) - clock.now() == timedelta(days=365)

    def test_a_lost_refresh_reply_doesnt_sign_you_out(self, client):
        tokens = register(client)
        old = {"refresh_token": tokens["refresh_token"]}
        lost = client.post("/v1/auth/refresh", json=old).json()  # reply never reached the phone
        again = client.post("/v1/auth/refresh", json=old)
        assert again.status_code == 200
        # Both of the newest refresh tokens work, so two tabs racing don't sign each other out.
        assert (
            client.post(
                "/v1/auth/refresh", json={"refresh_token": lost["refresh_token"]}
            ).status_code
            == 200
        )

    def test_signing_out_ends_every_token_of_the_session(self, client, db):
        tokens = register(client)
        old = {"refresh_token": tokens["refresh_token"]}
        new = client.post("/v1/auth/refresh", json=old).json()
        client.post("/v1/auth/logout", headers={"Authorization": f"Bearer {new['access_token']}"})
        assert client.post("/v1/auth/refresh", json=old).status_code == 401
        assert (
            client.post(
                "/v1/auth/refresh", json={"refresh_token": new["refresh_token"]}
            ).status_code
            == 401
        )
        assert db.scalar(select(AuthSession.revoked_at)) is not None


class TestCleanInput:
    @pytest.mark.parametrize(
        "route,payload",
        [
            ("/v1/events", {"event_type": "OTHER", "title": "   "}),
            ("/v1/tasks", {"title": "   "}),
            ("/v1/goals", {"title": " "}),
            ("/v1/projects", {"name": "  "}),
            ("/v1/habits", {"name": "\t"}),
            ("/v1/knowledge", {"title": " "}),
            ("/v1/areas", {"name": " "}),
        ],
    )
    def test_blank_names_are_refused(self, client, auth, route, payload):
        assert client.post(route, json=payload, headers=auth).status_code == 422

    def test_names_are_trimmed(self, client, auth):
        task = client.post("/v1/tasks", json={"title": "  Call the bank  "}, headers=auth).json()
        assert task["title"] == "Call the bank"

    def test_text_with_a_nul_character_is_refused(self, client, auth):
        response = client.post("/v1/captures", json={"content": "hello\u0000world"}, headers=auth)
        assert response.status_code == 422

    def test_search_with_a_nul_character_is_refused(self, client, auth):
        assert client.get("/v1/timeline", params={"q": "a\u0000b"}, headers=auth).status_code == 422

    def test_absurd_amounts_are_refused(self, client, auth):
        response = client.post(
            "/v1/events",
            json={"event_type": "EXPENSE", "title": "x", "amount": "99999999999999999999"},
            headers=auth,
        )
        assert response.status_code == 422

    def test_preferences_null_keeps_them(self, client, auth):
        assert client.patch("/v1/me", json={"preferences": None}, headers=auth).status_code == 200

    def test_a_habit_cant_use_another_persons_area(self, client, auth):
        area = client.get("/v1/areas", headers=auth).json()[0]["id"]
        other = {"Authorization": f"Bearer {register(client, 'other@example.com')['access_token']}"}
        habit = client.post("/v1/habits", json={"name": "Read"}, headers=other).json()
        response = client.patch(f"/v1/habits/{habit['id']}", json={"area_id": area}, headers=other)
        assert response.status_code == 404
        unknown = client.patch(
            f"/v1/habits/{habit['id']}", json={"area_id": str(uuid.uuid4())}, headers=other
        )
        assert unknown.status_code == 404

    def test_a_goal_cant_sit_under_its_own_sub_goal(self, client, auth):
        a = client.post("/v1/goals", json={"title": "A"}, headers=auth).json()
        b = client.post(
            "/v1/goals", json={"title": "B", "parent_goal_id": a["id"]}, headers=auth
        ).json()
        c = client.post(
            "/v1/goals", json={"title": "C", "parent_goal_id": b["id"]}, headers=auth
        ).json()
        assert (
            client.patch(
                f"/v1/goals/{a['id']}", json={"parent_goal_id": c["id"]}, headers=auth
            ).status_code
            == 422
        )

    def test_a_project_cant_sit_under_its_own_sub_project(self, client, auth):
        a = client.post("/v1/projects", json={"name": "Alpha"}, headers=auth).json()
        b = client.post(
            "/v1/projects", json={"name": "Beta", "parent_project_id": a["id"]}, headers=auth
        ).json()
        response = client.patch(
            f"/v1/projects/{a['id']}", json={"parent_project_id": b["id"]}, headers=auth
        )
        assert response.status_code == 422

    def test_an_unknown_api_path_is_a_json_404(self, client):
        response = client.get("/v1/does-not-exist")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


def test_an_event_date_is_unchanged_by_the_dst_helpers():
    # A day without a clock change still adds up the plain way.
    now = datetime(2026, 6, 1, 12, 0, tzinfo=ZoneInfo("Africa/Casablanca"))
    resolved = resolve_time(f.when(start_time="09:00", end_time="11:30"), now)
    assert resolved.duration_seconds == 9000 and resolved.occurred_on == date(2026, 6, 1)
