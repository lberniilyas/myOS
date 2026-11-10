"""The weekly review: numbers from records, fair comparisons, and observations from fixed rules."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.events.models import Event, EventHabit
from tests.conftest import register

# Wednesday 7 October 2026 (Casablanca). The week runs Monday 5 to Sunday 11 October.
WEDNESDAY = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
MONDAY = date(2026, 10, 5)


@pytest.fixture(autouse=True)
def midweek(clock):
    clock.moment = WEDNESDAY


def add(client, auth, event_type: str, on: date, **fields) -> dict:
    payload = {"event_type": event_type, "title": fields.pop("title", event_type.title())}
    response = client.post(
        "/v1/events", json={**payload, "occurred_on": on.isoformat(), **fields}, headers=auth
    )
    assert response.status_code == 201, response.text
    return response.json()


def study(client, auth, on: date, minutes: float, **fields) -> dict:
    return add(client, auth, "STUDY", on, duration_minutes=minutes, **fields)


def spend(client, auth, on: date, amount: str, currency: str = "MAD", **fields) -> dict:
    return add(client, auth, "EXPENSE", on, amount=amount, currency=currency, **fields)


def review(client, auth, week: date | None = None) -> dict:
    url = "/v1/review/weekly" + (f"?week={week.isoformat()}" if week else "")
    response = client.get(url, headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def metric(data: dict, key: str) -> dict:
    return next(m for m in data["metrics"] if m["key"] == key)


def weeks_ago(n: int, weekday: int = 0) -> date:
    return MONDAY - timedelta(weeks=n) + timedelta(days=weekday)


class TestComparisons:
    def test_a_week_in_progress_is_compared_with_the_same_days_of_earlier_weeks(self, client, auth):
        study(client, auth, MONDAY, 120)
        study(client, auth, weeks_ago(1, 0), 60)  # last Monday: counted
        study(client, auth, weeks_ago(1, 4), 300)  # last Friday: after Wednesday, not counted
        data = review(client, auth)
        assert data["week"] == {
            "start": "2026-10-05",
            "end": "2026-10-11",
            "is_current": True,
            "days_counted": 3,
            "compared_through": "Wednesday",
        }
        row = metric(data, "STUDY")
        assert row["this_week"] == {"value": 7200, "display": "2h"}
        assert row["last_week"] == {"value": 3600, "display": "1h"}
        assert row["change"] == "+1h" and row["direction"] == "up"

    def test_the_average_only_counts_weeks_since_you_started_recording(self, client, auth):
        study(client, auth, weeks_ago(2, 1), 60)  # first ever entry, two weeks ago
        study(client, auth, weeks_ago(1, 1), 180)
        study(client, auth, MONDAY, 120)
        data = review(client, auth)
        assert data["weeks_in_average"] == 2
        assert metric(data, "STUDY")["average"] == {"value": 7200, "display": "2h"}

    def test_a_new_account_has_nothing_to_compare_with(self, client, auth):
        study(client, auth, MONDAY, 600)
        data = review(client, auth)
        assert data["weeks_in_average"] == 0
        assert metric(data, "STUDY")["average"] is None
        assert data["observations"] == []

    def test_a_past_week_is_reviewed_whole(self, client, auth):
        study(client, auth, weeks_ago(1, 6), 90)  # last Sunday
        data = review(client, auth, weeks_ago(1, 3))
        assert data["week"]["start"] == "2026-09-28" and data["week"]["days_counted"] == 7
        assert data["week"]["compared_through"] is None and not data["week"]["is_current"]
        assert data["next_week"] == "2026-10-05" and data["previous_week"] == "2026-09-21"
        assert metric(data, "STUDY")["this_week"]["display"] == "1h 30m"
        assert review(client, auth)["next_week"] is None

    def test_a_week_that_hasnt_started_is_refused(self, client, auth):
        response = client.get("/v1/review/weekly?week=2026-10-12", headers=auth)
        assert response.status_code == 422

    def test_your_week_start_is_respected(self, client, auth):
        client.patch("/v1/me", json={"week_start": 6}, headers=auth)  # Sunday
        study(client, auth, date(2026, 10, 4), 60)  # Sunday: in this week now
        data = review(client, auth)
        assert data["week"]["start"] == "2026-10-04" and data["week"]["days_counted"] == 4
        assert metric(data, "STUDY")["this_week"]["value"] == 3600

    def test_study_and_project_work_always_show_other_time_only_with_data(self, client, auth):
        data = review(client, auth)
        assert [m["key"] for m in data["metrics"]] == ["STUDY", "PROJECT_WORK"]
        assert metric(data, "STUDY")["this_week"]["display"] == "0m"
        add(client, auth, "EXERCISE", weeks_ago(1), duration_minutes=45)
        assert "EXERCISE" in [m["key"] for m in review(client, auth)["metrics"]]

    def test_deleted_entries_and_other_peoples_records_are_left_out(self, client, auth):
        gone = study(client, auth, MONDAY, 60)
        client.delete(f"/v1/events/{gone['id']}", headers=auth)
        other = {"Authorization": f"Bearer {register(client, 'b@example.com')['access_token']}"}
        study(client, other, MONDAY, 600)
        assert metric(review(client, auth), "STUDY")["this_week"]["value"] == 0

    def test_entries_without_a_duration_are_pointed_out(self, client, auth):
        add(client, auth, "STUDY", MONDAY)
        note = metric(review(client, auth), "STUDY")["note"]
        assert note == "1 entry has no duration, so the total may be higher."

    def test_currencies_are_never_added_together(self, client, auth):
        spend(client, auth, MONDAY, "100")
        spend(client, auth, MONDAY, "20", "EUR")
        data = review(client, auth)
        assert metric(data, "SPENDING:MAD")["this_week"]["display"] == "100 MAD"
        assert metric(data, "SPENDING:EUR")["this_week"]["display"] == "20 EUR"

    def test_no_ai_is_involved(self, client, auth, fake_ai):
        study(client, auth, MONDAY, 60)
        review(client, auth)
        assert fake_ai.calls == []


class TestObservations:
    def test_a_big_change_on_the_average_is_called_out_with_its_numbers(self, client, auth):
        for n in (1, 2, 3, 4):
            study(client, auth, weeks_ago(n), 120)
        study(client, auth, MONDAY, 240)
        assert review(client, auth)["observations"] == [
            {
                "text": "Study is up 100% on your 4-week average by Wednesday: 4h against 2h.",
                "metric": "STUDY",
            }
        ]

    def test_small_changes_are_not_worth_a_sentence(self, client, auth):
        for n in (1, 2, 3, 4):
            study(client, auth, weeks_ago(n), 600)
        study(client, auth, MONDAY, 660)  # +1h, but only 10%
        assert review(client, auth)["observations"] == []

    def test_a_usual_activity_missing_this_week_is_noticed(self, client, auth):
        for n in (1, 2):
            study(client, auth, weeks_ago(n), 90)
        texts = [o["text"] for o in review(client, auth)["observations"]]
        assert texts == [
            "No study recorded yet this week; your 2-week average by Wednesday is 1h 30m."
        ]

    def test_with_one_earlier_week_it_compares_with_last_week(self, client, auth):
        study(client, auth, weeks_ago(1), 60)
        study(client, auth, MONDAY, 180)
        texts = [o["text"] for o in review(client, auth)["observations"]]
        assert texts == ["Study is up 200% on last week by Wednesday: 3h against 1h."]

    def test_spending_changes_and_the_main_category(self, client, auth):
        for n in (1, 2):
            spend(client, auth, weeks_ago(n), "200", category="food")
        spend(client, auth, MONDAY, "300", category="food")
        spend(client, auth, MONDAY, "100", category="transport")
        texts = [o["text"] for o in review(client, auth)["observations"]]
        assert texts == [
            "Spending is up 100% on your 2-week average by Wednesday: 400 MAD against 200 MAD.",
            "Food was 75% of your spending this week: 300 MAD of 400 MAD.",
        ]

    def test_the_project_that_got_most_of_the_time(self, client, auth):
        a = client.post("/v1/projects", json={"name": "TenderPilot"}, headers=auth).json()
        b = client.post("/v1/projects", json={"name": "Blog"}, headers=auth).json()
        add(client, auth, "PROJECT_WORK", MONDAY, duration_minutes=90, project_ids=[a["id"]])
        add(client, auth, "PROJECT_WORK", MONDAY, duration_minutes=30, project_ids=[b["id"]])
        texts = [o["text"] for o in review(client, auth)["observations"]]
        assert "TenderPilot got 75% of your project time this week: 1h 30m of 2h." in texts

    def test_never_more_than_three_strongest_first(self, client, auth):
        for n in (1, 2):
            study(client, auth, weeks_ago(n), 60)
            add(client, auth, "PROJECT_WORK", weeks_ago(n), duration_minutes=60)
            add(client, auth, "EXERCISE", weeks_ago(n), duration_minutes=60)
            spend(client, auth, weeks_ago(n), "100")
        study(client, auth, MONDAY, 300)  # +400%
        add(client, auth, "PROJECT_WORK", MONDAY, duration_minutes=180)  # +200%
        add(client, auth, "EXERCISE", MONDAY, duration_minutes=150)  # +150%
        spend(client, auth, MONDAY, "160")  # +60%
        observations = review(client, auth)["observations"]
        assert [o["metric"] for o in observations] == ["STUDY", "PROJECT_WORK", "EXERCISE"]


class TestHabits:
    def _habit(self, client, auth, name: str, frequency: str, target: int | None = None) -> dict:
        body = {"name": name, "frequency": frequency, "target_count": target}
        response = client.post("/v1/habits", json=body, headers=auth)
        assert response.status_code == 201, response.text
        return response.json()

    def _check_in(self, client, auth, db, habit: dict, on: date) -> None:
        event = add(client, auth, "HABIT", on, title=f"{habit['name']} done")
        db.add(EventHabit(event_id=event["id"], habit_id=habit["id"], outcome="COMPLETED"))
        db.flush()

    def test_progress_against_weekly_targets_and_daily_habits(self, client, auth, db):
        gym = self._habit(client, auth, "Gym", "WEEKLY", 3)
        read = self._habit(client, auth, "Reading", "DAILY")
        for day in (0, 1, 2):
            self._check_in(client, auth, db, gym, MONDAY + timedelta(days=day))
        self._check_in(client, auth, db, read, MONDAY)
        self._check_in(client, auth, db, read, MONDAY + timedelta(days=1))
        data = review(client, auth)
        assert [(h["name"], h["display"]) for h in data["habits"]] == [
            ("Gym", "3 of 3"),
            ("Reading", "2 of 3 days"),
        ]
        assert metric(data, "HABITS")["this_week"]["value"] == 5
        texts = [o["text"] for o in data["observations"]]
        assert "Gym: weekly target reached, 3 of 3." in texts

    def test_falling_behind_a_target_is_noticed(self, client, db, clock):
        clock.moment = WEDNESDAY + timedelta(days=4)  # Sunday: the last day
        auth = {"Authorization": f"Bearer {register(client, 'sun@example.com')['access_token']}"}
        gym = self._habit(client, auth, "Gym", "WEEKLY", 3)
        self._check_in(client, auth, db, gym, MONDAY)
        texts = [o["text"] for o in review(client, auth)["observations"]]
        assert "Gym: 1 of 3, with 0 days left this week." in texts

    def test_a_finished_week_that_missed_the_target(self, client, auth, db):
        gym = self._habit(client, auth, "Gym", "WEEKLY", 2)
        self._check_in(client, auth, db, gym, weeks_ago(1, 2))
        texts = [o["text"] for o in review(client, auth, weeks_ago(1))["observations"]]
        assert "Gym: 1 of 2, short of the target." in texts

    def test_no_habits_no_habit_row(self, client, auth, db):
        assert "HABITS" not in [m["key"] for m in review(client, auth)["metrics"]]
        assert db.scalar(select(Event)) is None
