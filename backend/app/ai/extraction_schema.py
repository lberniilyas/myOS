"""The structured output contract between the extraction model and the application (v1).

The model proposes; the application validates every field before anything is stored.
Dates are never computed by the model: it reports *references* ("yesterday", "last Monday")
and the time resolver turns them into calendar dates in the user's timezone.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import EXPENSE_CATEGORIES, INCOME_CATEGORIES

EXTRACTION_VERSION = "extraction-v1"

EventTypeName = Literal[
    "STUDY",
    "WORK",
    "PROJECT_WORK",
    "KNOWLEDGE",
    "TASK_ACTIVITY",
    "HABIT",
    "EXERCISE",
    "EXPENSE",
    "INCOME",
    "DEVICE_USAGE",
    "SLEEP",
    "JOURNAL",
    "STATE",
    "MILESTONE",
    "OTHER",
]
Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MoneyCategory = Literal[tuple(dict.fromkeys(EXPENSE_CATEGORIES + INCOME_CATEGORIES))]  # type: ignore[valid-type]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DayRef(_Strict):
    kind: Literal[
        "today", "yesterday", "days_ago", "weekday", "date", "not_mentioned", "unclear"
    ] = Field(
        description=(
            "How the user placed this on the calendar. 'not_mentioned' when they gave no day "
            "(the system then uses the day of the message). 'unclear' when they referred to a "
            "day too vaguely to place ('some time ago', 'the other day')."
        )
    )
    days_ago: int | None = Field(description="For kind=days_ago, e.g. 2 for 'two days ago'.")
    weekday: Weekday | None = Field(description="For kind=weekday.")
    weekday_qualifier: Literal["last", "this", "none"] | None = Field(
        description="For kind=weekday: 'last' for 'last Monday', 'this' for 'this Monday', 'none' for plain 'Monday'."
    )
    date: str | None = Field(description="For kind=date: the explicit calendar date as YYYY-MM-DD.")


class TimeInfo(_Strict):
    day: DayRef
    start_time: str | None = Field(
        description="Start clock time as HH:MM (24h), only when the user gave one."
    )
    end_time: str | None = Field(
        description="End clock time as HH:MM (24h), only when the user gave one."
    )
    clock_precision: Literal["exact", "approximate"] | None = Field(
        description="'approximate' for 'around 3', 'about 2pm'; null when no clock time."
    )
    part_of_day: Literal["morning", "afternoon", "evening", "night"] | None
    duration_minutes: float | None = Field(
        description="Length in minutes when the user stated or clearly implied one. Null when not stated."
    )
    duration_precision: Literal["exact", "approximate", "vague"] | None = Field(
        description=(
            "'approximate' for hedged amounts ('about 2 hours', 'a couple of hours'); 'vague' for "
            "spans with no number ('for a while', 'some time') - then duration_minutes is null."
        )
    )
    expression: str | None = Field(
        description="The user's own wording for the time, e.g. 'around 3 hours this afternoon'."
    )


class TimeChange(_Strict):
    """Only the parts the user changed; null means unchanged."""

    day: DayRef | None
    start_time: str | None
    end_time: str | None
    clock_precision: Literal["exact", "approximate"] | None
    part_of_day: Literal["morning", "afternoon", "evening", "night"] | None
    duration_minutes: float | None
    duration_precision: Literal["exact", "approximate"] | None


class ProjectMention(_Strict):
    text: str = Field(description="How the user referred to the project, in their words.")
    ref: str | None = Field(
        description="The p-ref of a known project when it clearly matches; else null."
    )
    kind: Literal["named", "generic"] = Field(
        description="'named' when the user named it ('TenderPilot', 'the tender app'); 'generic' for 'my project', 'the app'."
    )


class KnowledgeMention(_Strict):
    title: str = Field(description="The concept's canonical name, e.g. 'Vector databases'.")
    ref: str | None = Field(description="The k-ref of known knowledge when it is the same concept.")
    understanding: Literal["encountered", "studied", "reported_understanding", "demonstrated"] = (
        Field(
            description=(
                "'reported_understanding' only when the user says they understand it; 'demonstrated' "
                "only when they built or applied something with it."
            )
        )
    )
    aliases: list[str] = Field(description="Other names the user used for it, e.g. ['RAG'].")


class MoneyInfo(_Strict):
    amount: str | None = Field(
        description="Plain decimal string like '25' or '12.50'. Null if no number was given."
    )
    amount_precision: Literal["exact", "approximate"] | None
    currency: str | None = Field(
        description="ISO 4217 code only when the user said or wrote a currency (dh/dirham -> MAD, € -> EUR, $ -> USD). Otherwise null."
    )
    category: MoneyCategory | None
    merchant: str | None


class HabitInfo(_Strict):
    ref: str | None = Field(
        description="h-ref of the configured habit this satisfies or misses; null if none is configured."
    )
    name: str | None = Field(
        description="The habit as the user said it, e.g. 'exercise', 'reading'."
    )
    status: Literal["completed", "missed"]


class DeviceInfo(_Strict):
    device: Literal["phone", "pc", "tablet", "tv", "other"]
    application: str | None


class StateInfo(_Strict):
    dimension: Literal[
        "mood",
        "energy",
        "focus",
        "stress",
        "motivation",
        "productivity",
        "satisfaction",
        "health",
        "other",
    ]
    value: str = Field(
        description="Short, in the user's sense: 'low', 'distracted', 'very productive'."
    )


class Relation(_Strict):
    kind: Literal["new", "same_as_existing"] = Field(
        description="'same_as_existing' when the message describes an event already listed in recent events."
    )
    ref: str | None = Field(description="The e-ref of that existing event, for same_as_existing.")


class ExtractedEvent(_Strict):
    event_type: EventTypeName
    title: str = Field(description="2-5 words in the output language, e.g. 'AI study', 'Lunch'.")
    description: str | None = Field(
        description="Extra detail the user gave, without interpretation."
    )
    topic: str | None = Field(description="Subject of study/work/reading when stated, e.g. 'RAG'.")
    output: str | None = Field(
        description="Concrete result the user reported, e.g. 'fixed the authentication bug'."
    )
    time: TimeInfo
    project: ProjectMention | None
    knowledge: list[KnowledgeMention]
    habit: HabitInfo | None
    completes_task_ref: str | None = Field(
        description="t-ref of an open task this event finished, only if the user said it's done."
    )
    goal_ref: str | None = Field(
        description="g-ref only if the user explicitly tied this to that goal."
    )
    area_ref: str | None = Field(description="a-ref when the life area is clear.")
    money: MoneyInfo | None
    device: DeviceInfo | None
    state: StateInfo | None
    relation: Relation
    is_user_estimate: bool = Field(description="True when the user hedged ('I think', 'probably').")
    evidence: str = Field(description="A verbatim excerpt of the message that supports this event.")
    confidence: float = Field(description="0 to 1.")


class EventChanges(_Strict):
    """Fields to change on an existing event; null means unchanged."""

    event_type: EventTypeName | None
    title: str | None
    description: str | None
    topic: str | None
    output: str | None
    time: TimeChange | None
    project: ProjectMention | None
    remove_project: bool
    money: MoneyInfo | None


class Correction(_Strict):
    action: Literal["update", "delete", "split"]
    target_ref: str | None = Field(description="e-ref of the event being corrected, when clear.")
    candidate_refs: list[str] = Field(
        description="When it is unclear which event is meant: the plausible e-refs."
    )
    changes: EventChanges | None = Field(description="For action=update.")
    split_into: list[ExtractedEvent] = Field(
        description="For action=split: the events that replace the original."
    )
    evidence: str = Field(
        description="A verbatim excerpt of the message that asks for this change."
    )
    confidence: float


class DueRef(_Strict):
    kind: Literal["today", "tomorrow", "days_from_now", "weekday", "date", "none"]
    days_from_now: int | None
    weekday: Weekday | None
    date: str | None = Field(description="YYYY-MM-DD for kind=date.")


class ExtractedTask(_Strict):
    title: str = Field(description="Imperative, e.g. 'Finish the RAG implementation'.")
    due: DueRef
    project: ProjectMention | None
    goal_ref: str | None
    evidence: str = Field(
        description="A verbatim excerpt of the message that states this intention."
    )
    confidence: float


class ExtractionOutput(_Strict):
    language: str | None = Field(
        description="Main language(s) of the message, e.g. 'en', 'fr', 'ary' (Darija), 'mixed'."
    )
    intent: Literal["record", "correct", "question", "mixed", "other"]
    events: list[ExtractedEvent]
    corrections: list[Correction]
    tasks: list[ExtractedTask]
    question: str | None = Field(
        description="When the user asks about their own history: the question, restated plainly."
    )
