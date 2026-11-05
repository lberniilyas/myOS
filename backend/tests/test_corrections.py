from sqlalchemy import select

from app.events.models import Event, EventRevision
from tests import factories as f
from tests.test_capture import capture


def log_study(client, auth, fake_ai, minutes=180, text="I studied AI for 3 hours"):
    fake_ai.respond(
        text,
        f.output(
            events=[
                f.event(
                    "STUDY", "AI study", text, topic="AI", time=f.when(duration_minutes=minutes)
                )
            ]
        ),
    )
    return capture(client, auth, text)["events_created"][0]


class TestNaturalCorrections:
    def test_actually_it_was_two_hours_updates_instead_of_duplicating(
        self, client, auth, fake_ai, db
    ):
        event = log_study(client, auth, fake_ai)
        fake_ai.respond(
            "Actually",
            f.output(
                intent="correct",
                corrections=[
                    f.correction(
                        "update",
                        "Actually, it was 2 hours",
                        target_ref="e1",
                        changes=f.changes(time=f.time_change(duration_minutes=120)),
                    )
                ],
            ),
        )
        result = capture(client, auth, "Actually, it was 2 hours")
        assert result["events_created"] == []
        assert result["events_updated"][0]["changes"] == ["duration"]
        assert result["message"] == "Updated AI study (duration)."
        events = db.scalars(select(Event).where(Event.deleted_at.is_(None))).all()
        assert len(events) == 1 and events[0].duration_seconds == 7200

        revisions = client.get(f"/v1/events/{event['id']}/revisions", headers=auth).json()
        assert revisions[0]["change_source"] == "AI_CORRECTION"
        assert revisions[0]["before"]["duration_seconds"] == 10800
        assert revisions[0]["after"]["duration_seconds"] == 7200

        # The model saw the earlier message so it could resolve "it".
        assert '"I studied AI for 3 hours" → recorded e1' in fake_ai.calls[-1]["user"]

    def test_moving_to_yesterday_and_deleting(self, client, auth, fake_ai):
        event = log_study(client, auth, fake_ai)
        fake_ai.respond(
            "yesterday",
            f.output(
                corrections=[
                    f.correction(
                        "update",
                        "that was yesterday",
                        target_ref="e1",
                        changes=f.changes(time=f.time_change(day=f.day("yesterday"))),
                    )
                ]
            ),
        )
        moved = capture(client, auth, "that was yesterday")
        assert moved["events_updated"][0]["event"]["occurred_on"] == "2026-10-03"

        fake_ai.respond(
            "Delete", f.output(corrections=[f.correction("delete", "Delete that", target_ref="e1")])
        )
        deleted = capture(client, auth, "Delete that")
        assert deleted["events_deleted"][0]["id"] == event["id"]
        assert client.get("/v1/timeline", headers=auth).json()["items"] == []
        restored = client.post(f"/v1/events/{event['id']}/restore", headers=auth)
        assert restored.status_code == 200 and restored.json()["deleted_at"] is None

    def test_split_one_session_into_two(self, client, auth, fake_ai, db):
        fake_ai.respond(
            "five hours",
            f.output(
                events=[
                    f.event(
                        "WORK",
                        "Work",
                        "worked five hours",
                        time=f.when(day=f.day("yesterday"), duration_minutes=300),
                    )
                ]
            ),
        )
        capture(client, auth, "I worked five hours yesterday")
        fake_ai.respond(
            "two hours were",
            f.output(
                corrections=[
                    f.correction(
                        "split",
                        "two hours were studying and three were coding",
                        target_ref="e1",
                        split_into=[
                            f.event(
                                "STUDY",
                                "Study",
                                "two hours were studying",
                                time=f.when(duration_minutes=120),
                            ),
                            f.event(
                                "WORK",
                                "Coding",
                                "three were coding",
                                time=f.when(duration_minutes=180),
                            ),
                        ],
                    )
                ]
            ),
        )
        result = capture(client, auth, "Actually, two hours were studying and three were coding")
        assert [e["title"] for e in result["events_created"]] == ["Study", "Coding"]
        # The replacements keep the original day, not today.
        assert {e["occurred_on"] for e in result["events_created"]} == {"2026-10-03"}
        assert len(result["events_deleted"]) == 1
        live = db.scalars(select(Event).where(Event.deleted_at.is_(None))).all()
        assert sorted(e.duration_seconds for e in live) == [7200, 10800]
        split = db.scalar(select(EventRevision).where(EventRevision.change_type == "SPLIT"))
        assert split is not None

    def test_ambiguous_target_asks_then_applies(self, client, auth, fake_ai):
        log_study(client, auth, fake_ai, text="I studied AI for 3 hours")
        log_study(client, auth, fake_ai, minutes=60, text="I studied math for 1 hour")
        fake_ai.respond(
            "make it",
            f.output(
                corrections=[
                    f.correction(
                        "update",
                        "make it 90 minutes",
                        candidate_refs=["e1", "e2"],
                        changes=f.changes(time=f.time_change(duration_minutes=90)),
                    )
                ]
            ),
        )
        result = capture(client, auth, "make it 90 minutes")
        question = result["clarifications"][0]
        assert question["kind"] == "CORRECTION_TARGET" and len(question["options"]) == 2
        chosen = next(o for o in question["options"] if "1h" in o["label"])
        answered = client.post(
            f"/v1/clarifications/{question['id']}/answer",
            json={"option_id": chosen["id"]},
            headers=auth,
        )
        assert answered.status_code == 200
        detail = client.get(f"/v1/events/{chosen['value']}", headers=auth).json()
        assert detail["duration_seconds"] == 5400

    def test_correct_endpoint_scopes_to_one_event(self, client, auth, fake_ai):
        event = log_study(client, auth, fake_ai)
        fake_ai.respond(
            "this was",
            f.output(
                corrections=[
                    f.correction(
                        "update",
                        "this was on Friday",
                        target_ref="e1",
                        changes=f.changes(
                            time=f.time_change(
                                day=f.day("weekday", weekday="friday", weekday_qualifier="none")
                            )
                        ),
                    )
                ]
            ),
        )
        result = client.post(
            f"/v1/events/{event['id']}/correct", json={"text": "this was on Friday"}, headers=auth
        ).json()
        assert result["events_updated"][0]["event"]["occurred_on"] == "2026-10-02"
        assert "<correction_scope>" in fake_ai.calls[-1]["user"]


class TestRepeats:
    def test_model_flagged_repeat_merges_into_the_existing_event(self, client, auth, fake_ai, db):
        fake_ai.respond(
            "Started", f.output(events=[f.event("STUDY", "AI study", "Started studying AI")])
        )
        capture(client, auth, "Started studying AI")
        fake_ai.respond(
            "Finished",
            f.output(
                events=[
                    f.event(
                        "STUDY",
                        "AI study",
                        "Finished my AI session. It took about two hours",
                        time=f.when(duration_minutes=120, duration_precision="approximate"),
                        relation={"kind": "same_as_existing", "ref": "e1"},
                    )
                ]
            ),
        )
        result = capture(client, auth, "Finished my AI session. It took about two hours")
        assert result["events_created"] == []
        assert result["events_updated"][0]["changes"] == ["duration"]
        assert len(db.scalars(select(Event)).all()) == 1

    def test_similar_new_event_triggers_a_duplicate_question(self, client, auth, fake_ai, db):
        log_study(client, auth, fake_ai, minutes=120, text="studied AI for two hours")
        fake_ai.respond(
            "again",
            f.output(
                events=[
                    f.event(
                        "STUDY",
                        "AI study",
                        "AI study for two hours again",
                        topic="AI",
                        time=f.when(duration_minutes=120),
                    )
                ]
            ),
        )
        result = capture(client, auth, "AI study for two hours again")
        question = result["clarifications"][0]
        assert question["kind"] == "DUPLICATE"
        client.post(
            f"/v1/clarifications/{question['id']}/answer", json={"option_id": "same"}, headers=auth
        )
        assert len(db.scalars(select(Event).where(Event.deleted_at.is_(None))).all()) == 1


class TestClarifications:
    def test_project_choice_links_and_learns_the_nickname(self, client, auth, fake_ai):
        tp = client.post("/v1/projects", json={"name": "TenderPilot"}, headers=auth).json()
        client.post("/v1/projects", json={"name": "BLANI"}, headers=auth)
        fake_ai.respond(
            "on the app",
            f.output(
                events=[
                    f.event(
                        "PROJECT_WORK",
                        "Project work",
                        "worked on the app",
                        project=f.project("the app", kind="generic"),
                    )
                ]
            ),
        )
        result = capture(client, auth, "I worked on the app for a bit")
        question = result["clarifications"][0]
        assert question["kind"] == "PROJECT_CHOICE"
        assert {o["label"] for o in question["options"]} == {
            "TenderPilot",
            "BLANI",
            "None of these",
        }
        answer = client.post(
            f"/v1/clarifications/{question['id']}/answer",
            json={"option_id": tp["id"]},
            headers=auth,
        ).json()
        assert answer["events"][0]["projects"][0]["name"] == "TenderPilot"
        assert (
            client.get(f"/v1/captures/{result['capture']['id']}", headers=auth).json()["capture"][
                "status"
            ]
            == "PROCESSED"
        )
        assert client.get("/v1/clarifications", headers=auth).json() == []
        # "the app" is generic, so it isn't learned as a nickname.
        assert client.get(f"/v1/projects/{tp['id']}", headers=auth).json()["aliases"] == []

    def test_named_unknown_project_offers_to_create_it(self, client, auth, fake_ai):
        fake_ai.respond(
            "Personal OS",
            f.output(
                events=[
                    f.event(
                        "PROJECT_WORK",
                        "Personal OS work",
                        "worked on Personal OS",
                        project=f.project("Personal OS"),
                    )
                ]
            ),
        )
        result = capture(client, auth, "I worked on Personal OS")
        question = result["clarifications"][0]
        assert question["kind"] == "CREATE_PROJECT"
        client.post(
            f"/v1/clarifications/{question['id']}/answer",
            json={"option_id": "create"},
            headers=auth,
        )
        projects = client.get("/v1/projects", headers=auth).json()
        assert [p["name"] for p in projects] == ["Personal OS"]
        assert (
            client.get(f"/v1/projects/{projects[0]['id']}", headers=auth).json()["stats"][
                "event_count"
            ]
            == 1
        )

    def test_vague_duration_asks_how_long(self, client, auth, fake_ai):
        fake_ai.respond(
            "a while",
            f.output(
                events=[
                    f.event(
                        "STUDY",
                        "Study",
                        "studied for a while",
                        time=f.when(duration_precision="vague"),
                    )
                ]
            ),
        )
        result = capture(client, auth, "I studied for a while")
        question = result["clarifications"][0]
        assert question["kind"] == "DURATION"
        answered = client.post(
            f"/v1/clarifications/{question['id']}/answer", json={"option_id": "60"}, headers=auth
        ).json()
        assert answered["events"][0]["duration_display"] == "~1h"
        repeat = client.post(
            f"/v1/clarifications/{question['id']}/answer", json={"option_id": "60"}, headers=auth
        )
        assert repeat.status_code == 409

    def test_expense_category_and_amount_questions(self, client, auth, fake_ai):
        fake_ai.respond(
            "spent 50",
            f.output(events=[f.event("EXPENSE", "Expense", "I spent 50", money=f.money("50"))]),
        )
        result = capture(client, auth, "I spent 50")
        question = result["clarifications"][0]
        assert (
            question["kind"] == "EXPENSE_CATEGORY"
            and question["question"] == "What was the 50 MAD for?"
        )
        client.post(
            f"/v1/clarifications/{question['id']}/answer",
            json={"option_id": "transport"},
            headers=auth,
        )
        event = client.get(f"/v1/events/{result['events_created'][0]['id']}", headers=auth).json()
        assert event["category"] == "transport" and event["revision_count"] == 1
        bad = client.post(
            f"/v1/clarifications/{question['id']}/answer", json={"option_id": "x"}, headers=auth
        )
        assert bad.status_code == 409
