import json
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.ai.extraction_schema import ExtractionOutput
from app.ai.schema_utils import inline_refs, strict_json_schema
from app.captures.time_resolution import apply_time_change, resolve_due, resolve_time
from app.core.enums import DayPeriod, DurationPrecision, TimePrecision
from app.core.formatting import format_amount, format_duration
from app.core.money import normalize_currency, parse_amount
from app.core.periods import resolve_period
from app.core.text import compact_key, name_match_score, quote_appears_in
from app.errors import ValidationFailedError
from tests.factories import day, time_change, when

CASA = ZoneInfo("Africa/Casablanca")
NOW_LOCAL = datetime(2026, 10, 4, 19, 42, tzinfo=CASA)  # a Sunday


class TestTimeResolution:
    def test_no_day_means_the_day_of_the_message_and_no_invented_times(self):
        resolved = resolve_time(when(duration_minutes=120, duration_precision="exact"), NOW_LOCAL)
        assert resolved.occurred_on == date(2026, 10, 4)
        assert resolved.occurred_at is None and resolved.ended_at is None
        assert resolved.duration_seconds == 7200
        assert resolved.time_precision == TimePrecision.DATE_ONLY
        assert resolved.duration_precision == DurationPrecision.EXACT

    def test_approximate_duration_stays_approximate(self):
        resolved = resolve_time(
            when(duration_minutes=180, duration_precision="approximate"), NOW_LOCAL
        )
        assert resolved.duration_precision == DurationPrecision.APPROXIMATE

    def test_vague_duration_is_unknown(self):
        resolved = resolve_time(when(duration_precision="vague"), NOW_LOCAL)
        assert resolved.duration_seconds is None
        assert resolved.duration_precision == DurationPrecision.UNKNOWN

    @pytest.mark.parametrize(
        ("day_ref", "expected"),
        [
            (day("yesterday"), date(2026, 10, 3)),
            (day("days_ago", days_ago=2), date(2026, 10, 2)),
            (day("weekday", weekday="monday", weekday_qualifier="none"), date(2026, 9, 28)),
            (day("weekday", weekday="sunday", weekday_qualifier="none"), date(2026, 10, 4)),
            (day("weekday", weekday="sunday", weekday_qualifier="last"), date(2026, 9, 27)),
            (day("date", date="2026-09-15"), date(2026, 9, 15)),
        ],
    )
    def test_day_references(self, day_ref, expected):
        assert resolve_time(when(day_ref), NOW_LOCAL).occurred_on == expected

    def test_clock_range_gives_exact_times_and_duration(self):
        resolved = resolve_time(
            when(start_time="14:00", end_time="17:00", clock_precision="exact"), NOW_LOCAL
        )
        assert resolved.occurred_at == datetime(2026, 10, 4, 14, 0, tzinfo=CASA)
        assert resolved.ended_at == datetime(2026, 10, 4, 17, 0, tzinfo=CASA)
        assert resolved.duration_seconds == 3 * 3600
        assert resolved.time_precision == TimePrecision.EXACT

    def test_range_across_midnight(self):
        resolved = resolve_time(
            when(day("yesterday"), start_time="23:00", end_time="01:30", clock_precision="exact"),
            NOW_LOCAL,
        )
        assert resolved.duration_seconds == int(2.5 * 3600)
        assert resolved.ended_at.date() == date(2026, 10, 4)

    def test_start_plus_duration_computes_end(self):
        resolved = resolve_time(
            when(
                start_time="15:00",
                clock_precision="approximate",
                duration_minutes=90,
                duration_precision="exact",
            ),
            NOW_LOCAL,
        )
        assert resolved.ended_at == datetime(2026, 10, 4, 16, 30, tzinfo=CASA)
        assert resolved.time_precision == TimePrecision.APPROXIMATE

    def test_future_events_are_flagged(self):
        assert resolve_time(when(start_time="22:00"), NOW_LOCAL).in_future
        assert resolve_time(when(day("date", date="2026-10-10")), NOW_LOCAL).in_future

    def test_impossible_duration_is_dropped_with_warning(self):
        resolved = resolve_time(when(duration_minutes=-30), NOW_LOCAL)
        assert resolved.duration_seconds is None
        assert resolved.warnings

    def test_unclear_day_is_marked(self):
        resolved = resolve_time(when(day("unclear")), NOW_LOCAL)
        assert resolved.date_unclear
        assert resolved.time_precision == TimePrecision.UNKNOWN

    def test_part_of_day_is_kept_without_a_clock_time(self):
        resolved = resolve_time(when(day("yesterday"), part_of_day="afternoon"), NOW_LOCAL)
        assert resolved.day_period == DayPeriod.AFTERNOON
        assert resolved.occurred_at is None

    def test_changing_duration_recomputes_the_end(self):
        base = when(start_time="14:00", end_time="16:00", clock_precision="exact")
        changed = apply_time_change(base, time_change(duration_minutes=180))
        resolved = resolve_time(changed, NOW_LOCAL)
        assert resolved.duration_seconds == 3 * 3600
        assert resolved.ended_at == datetime(2026, 10, 4, 17, 0, tzinfo=CASA)

    def test_due_dates_look_forward(self):
        from app.ai.extraction_schema import DueRef

        today = date(2026, 10, 4)
        assert resolve_due(
            DueRef(kind="tomorrow", days_from_now=None, weekday=None, date=None), today
        ) == date(2026, 10, 5)
        assert resolve_due(
            DueRef(kind="weekday", days_from_now=None, weekday="sunday", date=None), today
        ) == date(2026, 10, 11)


class TestText:
    def test_compact_key_ignores_spacing_case_and_accents(self):
        assert compact_key("Tender Pilot") == compact_key("tenderpilot") == "tenderpilot"
        assert compact_key("Étude IA") == "etudeia"

    def test_name_matching(self):
        assert name_match_score("the tender app", ["TenderPilot", "tender app"]) == 1.0
        assert name_match_score("tender project", ["TenderPilot"]) >= 0.85
        assert name_match_score("travel", ["TenderPilot"]) < 0.75

    def test_evidence_must_appear_in_the_message(self):
        message = "Today I studied AI for 2 hours, and spent 25 on lunch."
        assert quote_appears_in(message, "studied AI for 2 hours")
        assert quote_appears_in(message, "Studied ai for 2 hours")
        assert quote_appears_in(message, "studied AI ... spent 25")
        assert not quote_appears_in(message, "studied machine learning")
        assert not quote_appears_in(message, "")
        assert quote_appears_in("Lyouma qrit AI pendant deux heures", "qrit AI pendant deux heures")


class TestMoneyAndFormatting:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("25", Decimal("25.00")),
            ("12.5", Decimal("12.50")),
            ("1,200", Decimal("1200.00")),
            ("12,50", Decimal("12.50")),
        ],
    )
    def test_parse_amount(self, raw, expected):
        assert parse_amount(raw) == expected

    @pytest.mark.parametrize("raw", ["a lot", "-5", "0", None, "", True])
    def test_rejects_non_amounts(self, raw):
        assert parse_amount(raw) is None

    def test_currency(self):
        assert normalize_currency("mad") == "MAD"
        assert normalize_currency("DH") is None

    def test_formatting(self):
        assert format_duration(5 * 3600 + 42 * 60) == "5h 42m"
        assert format_duration(3 * 3600, "APPROXIMATE") == "~3h"
        assert format_duration(45 * 60) == "45m"
        assert format_amount(Decimal("25.00"), "MAD") == "25 MAD"
        assert format_amount(Decimal("12.50"), None) == "12.50"


class TestPeriods:
    def test_weeks_start_on_monday_by_default(self):
        assert resolve_period("this_week", date(2026, 10, 4)) == (
            date(2026, 9, 28),
            date(2026, 10, 4),
        )
        assert resolve_period("last_week", date(2026, 10, 4)) == (
            date(2026, 9, 21),
            date(2026, 9, 27),
        )

    def test_months(self):
        assert resolve_period("last_month", date(2026, 3, 15)) == (
            date(2026, 2, 1),
            date(2026, 2, 28),
        )

    def test_custom_needs_both_dates(self):
        with pytest.raises(ValidationFailedError):
            resolve_period("custom", date(2026, 10, 4), start=date(2026, 1, 1))


def test_extraction_schema_fits_structured_output_rules():
    schema = strict_json_schema(ExtractionOutput)

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            assert "minimum" not in node and "default" not in node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    assert "properties" in schema["$defs"]["ExtractedEvent"]
    assert "title" in schema["$defs"]["ExtractedEvent"]["properties"]
    inlined = json.dumps(inline_refs(schema))
    assert "$ref" not in inlined and "$defs" not in inlined


def test_reply_wording_avoids_repeated_words():
    from decimal import Decimal as D

    from app.captures.summary import describe
    from app.events.models import Event

    def make(event_type, title, **kw):
        return Event(
            event_type=event_type,
            title=title,
            structured_data=kw.pop("data", {}),
            duration_precision="EXACT",
            **kw,
        )

    assert describe(make("STUDY", "Study session", duration_seconds=7200)) == "2h Study session"
    assert (
        describe(make("STUDY", "AI study", duration_seconds=3600, data={"topic": "AI"}))
        == "1h AI study"
    )
    assert describe(make("EXPENSE", "Expense", amount=D("50"), currency="MAD")) == "50 MAD expense"
    assert (
        describe(make("EXPENSE", "Lunch", amount=D("25"), currency="MAD", category="food"))
        == "25 MAD food expense"
    )
