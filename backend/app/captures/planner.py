"""Turn validated model output into an explicit change plan (spec #8 §16).

Nothing here writes to the database. Every rule that decides whether something may be
stored lives here, in code, not in the prompt (spec #4 §19).
"""

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.extraction_schema import (
    EXTRACTION_VERSION,
    Correction,
    ExtractedEvent,
    ExtractedTask,
    ExtractionOutput,
    MoneyInfo,
)
from app.captures.context import ExtractionContext
from app.captures.duplicates import ASK_THRESHOLD, duplicate_score
from app.captures.resolution import (
    KnowledgePlan,
    QuestionPlan,
    plan_knowledge,
    resolve_habit,
    resolve_project,
)
from app.captures.time_resolution import (
    ResolvedTime,
    apply_time_change,
    resolve_due,
    resolve_time,
    time_info_from_event,
)
from app.core.enums import (
    EXPENSE_CATEGORIES,
    INCOME_CATEGORIES,
    MONEY_EVENT_TYPES,
    TIMED_EVENT_TYPES,
    AmountPrecision,
    ChangeSource,
    ClarificationKind,
    CreatedBy,
    DurationPrecision,
    EventType,
    HabitOutcome,
    InputType,
    LinkSource,
    RevisionChangeType,
    SourceType,
)
from app.core.formatting import format_amount, format_duration
from app.core.money import normalize_currency, parse_amount
from app.core.text import NONE, PARTIAL, evidence_match, mention_key
from app.events.models import Event

MAX_QUESTIONS = 3
# One message may remove this many records without a confirmation; more needs a "yes".
MAX_SILENT_DELETES = 2
# Below this, the model itself isn't sure it was asked to delete, so ask first.
CONFIDENT_DELETE = 0.6


@dataclass
class NewEventPlan:
    temp_id: str
    values: dict
    project_links: list[tuple[uuid.UUID, LinkSource]] = field(default_factory=list)
    goal_ids: list[uuid.UUID] = field(default_factory=list)
    habit_links: list[tuple[uuid.UUID, HabitOutcome]] = field(default_factory=list)
    completes_task_ids: list[uuid.UUID] = field(default_factory=list)
    knowledge: list[KnowledgePlan] = field(default_factory=list)
    questions: list[QuestionPlan] = field(default_factory=list)


@dataclass
class UpdatePlan:
    event: Event
    values: dict
    change_type: RevisionChangeType
    change_source: ChangeSource
    changes: list[str]
    project_links: list[tuple[uuid.UUID, LinkSource]] | None = None  # None = leave as is
    knowledge: list[KnowledgePlan] = field(default_factory=list)
    questions: list[QuestionPlan] = field(default_factory=list)


@dataclass
class DeletePlan:
    event: Event
    change_type: RevisionChangeType = RevisionChangeType.DELETE


@dataclass
class TaskPlan:
    title: str
    due_date: object
    project_id: uuid.UUID | None
    goal_id: uuid.UUID | None


@dataclass
class ChangePlan:
    new_events: list[NewEventPlan] = field(default_factory=list)
    updates: list[UpdatePlan] = field(default_factory=list)
    deletes: list[DeletePlan] = field(default_factory=list)
    new_tasks: list[TaskPlan] = field(default_factory=list)
    unchanged: list[Event] = field(default_factory=list)
    questions: list[QuestionPlan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    question_text: str | None = None
    # Deletions held back until the person confirms them.
    deletes_to_confirm: list[Event] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.new_events or self.updates or self.deletes or self.new_tasks)


def _clamp(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _event_label(event: Event) -> str:
    parts = [event.title, event.occurred_on.isoformat()]
    if duration := format_duration(event.duration_seconds, event.duration_precision):
        parts.append(duration)
    if amount := format_amount(event.amount, event.currency, event.amount_precision):
        parts.append(amount)
    return " · ".join(parts)


class Planner:
    def __init__(self, db: Session, ctx: ExtractionContext) -> None:
        self.db = db
        self.ctx = ctx
        self.plan = ChangePlan()
        self.text = ctx.capture.text
        self.now_local = ctx.now_local
        self.source_type = (
            SourceType.USER_VOICE
            if ctx.capture.input_type == InputType.VOICE
            else SourceType.USER_TEXT
        )
        self._temp_ids = 0
        # Events this plan replaces (a split), which new events must not be compared with.
        self._replacing: set[uuid.UUID] = set()

    # --- entry point -----------------------------------------------------------------------

    def run(self, output: ExtractionOutput) -> ChangePlan:
        for correction in output.corrections:
            self.plan_correction(correction)
        self._hold_back_bulk_deletes()
        for extracted in output.events:
            self.plan_event(extracted)
        for task in output.tasks:
            self.plan_task(task)
        if output.intent == "question" and self.plan.is_empty():
            self.plan.question_text = (output.question or self.text).strip()
        self._cap_questions()
        return self.plan

    def _evidence(self, evidence: str, what: str) -> str | None:
        """How well the quote matches the message, or None (with a warning) when it doesn't."""
        level = evidence_match(self.text, evidence) if evidence else NONE
        if level == NONE:
            self.plan.warnings.append(
                f"Skipped “{what}” because it couldn't be traced to your words."
            )
            return None
        return level

    def _cap_questions(self) -> None:
        budget = MAX_QUESTIONS
        # Questions about the message as a whole (which entry, delete these?) come first.
        holders = [self.plan.questions]
        holders += [p.questions for p in self.plan.new_events]
        holders += [u.questions for u in self.plan.updates]
        for questions in holders:
            keep = questions[:budget]
            budget -= len(keep)
            questions[:] = keep

    # --- new events ----------------------------------------------------------------------

    def plan_event(self, extracted: ExtractedEvent, *, default_day=None) -> NewEventPlan | None:
        title = extracted.title.strip()[:300] or extracted.event_type.replace("_", " ").title()
        evidence = self._evidence(extracted.evidence, title)
        if evidence is None:
            return None
        resolved = resolve_time(
            extracted.time, self.now_local, default_day=default_day, said=extracted.evidence
        )
        self.plan.warnings.extend(f"{title}: {w}" for w in resolved.warnings)
        if resolved.in_future:
            self.plan.warnings.append(
                f"Didn't log “{title}” because it sounds like it hasn't happened yet."
            )
            return None

        relation = extracted.relation
        if relation.kind == "same_as_existing" and relation.ref in self.ctx.events:
            self._plan_merge(self.ctx.events[relation.ref], extracted, resolved)
            return None

        event_type = EventType(extracted.event_type)
        values = self._base_values(extracted, title, event_type, resolved)
        plan = NewEventPlan(temp_id=self._next_temp_id(), values=values)
        self._apply_money(event_type, extracted.money, values, plan.questions, title)
        self._apply_links(extracted, plan)

        if event_type in TIMED_EVENT_TYPES and resolved.duration_seconds is None:
            if extracted.time.duration_precision == "vague":
                plan.questions.append(self._duration_question(title))
        if resolved.date_unclear:
            plan.questions.append(self._date_question(title))
        self._check_duplicate(plan, event_type)
        if evidence == PARTIAL:
            # Saved, so nothing is lost, but the words only partly support it: ask first of all.
            values["structured_data"]["evidence_check"] = "partial"
            plan.questions.insert(0, self._keep_question(values))
        self.plan.new_events.append(plan)
        return plan

    def _keep_question(self, values: dict) -> QuestionPlan:
        shown = values["title"]
        detail = format_amount(
            values["amount"], values["currency"], values["amount_precision"]
        ) or format_duration(values["duration_seconds"], values["duration_precision"])
        if detail:
            shown = f"{shown} — {detail}"
        return QuestionPlan(
            kind=ClarificationKind.CONFIRM,
            question=f"I wasn't sure about this one. Keep “{shown}”?",
            options=[
                {"id": "keep", "label": "Keep it", "value": "keep"},
                {"id": "remove", "label": "Remove it", "value": "remove"},
            ],
            payload={"reason": "evidence"},
        )

    def _next_temp_id(self) -> str:
        self._temp_ids += 1
        return f"n{self._temp_ids}"

    def _base_values(
        self, extracted: ExtractedEvent, title: str, event_type: EventType, resolved: ResolvedTime
    ) -> dict:
        structured: dict = {}
        if extracted.topic and extracted.topic.strip():
            structured["topic"] = extracted.topic.strip()
        if extracted.output and extracted.output.strip():
            structured["output"] = extracted.output.strip()
        if extracted.device is not None:
            structured["device"] = extracted.device.model_dump()
        if extracted.state is not None:
            structured["state"] = extracted.state.model_dump()
        if extracted.time.expression:
            structured["time_expression"] = extracted.time.expression
        if extracted.is_user_estimate:
            structured["user_estimate"] = True
        return {
            "user_id": self.ctx.user.id,
            "capture_id": self.ctx.capture.id,
            "source_type": self.source_type,
            "created_by": CreatedBy.AI_EXTRACTION,
            "event_type": event_type,
            "title": title,
            "description": (extracted.description or "").strip() or None,
            "category": None,
            "occurred_on": resolved.occurred_on,
            "occurred_at": resolved.occurred_at,
            "ended_at": resolved.ended_at,
            "duration_seconds": resolved.duration_seconds,
            "time_precision": resolved.time_precision,
            "duration_precision": resolved.duration_precision,
            "day_period": resolved.day_period,
            "amount": None,
            "currency": None,
            "amount_precision": None,
            "structured_data": structured,
            "evidence": extracted.evidence.strip(),
            "extraction_confidence": _clamp(extracted.confidence),
            "extraction_version": EXTRACTION_VERSION,
            "area_id": None,
        }

    def _apply_money(
        self,
        event_type: EventType,
        money: MoneyInfo | None,
        values: dict,
        questions: list,
        title: str,
    ) -> None:
        if event_type not in MONEY_EVENT_TYPES:
            return
        structured = values["structured_data"]
        amount = parse_amount(money.amount) if money else None
        if money and money.amount and amount is None:
            self.plan.warnings.append(f"Couldn't read the amount “{money.amount}” for {title}.")
        currency = normalize_currency(money.currency) if money else None
        if money and money.currency and currency is None:
            self.plan.warnings.append(
                f"Didn't recognise the currency “{money.currency}” for {title}."
            )
        if currency is None and amount is not None and self.ctx.user.default_currency:
            currency = self.ctx.user.default_currency
            structured["currency_source"] = "default"
        allowed = EXPENSE_CATEGORIES if event_type == EventType.EXPENSE else INCOME_CATEGORIES
        category = money.category if money and money.category in allowed else None
        if money and money.merchant:
            structured["merchant"] = money.merchant.strip()
        values.update(
            amount=amount,
            currency=currency if amount is not None else None,
            amount_precision=(
                AmountPrecision.APPROXIMATE
                if money and money.amount_precision == "approximate"
                else AmountPrecision.EXACT
            )
            if amount is not None
            else None,
            category=category,
        )
        if amount is None:
            questions.append(
                QuestionPlan(
                    kind=ClarificationKind.AMOUNT,
                    question=f"How much was “{title}”?",
                    options=[],
                    payload={"answer_type": "amount"},
                )
            )
        elif category is None and event_type == EventType.EXPENSE:
            shown = format_amount(amount, currency)
            choices = ("food", "transport", "shopping", "groceries", "entertainment", "other")
            questions.append(
                QuestionPlan(
                    kind=ClarificationKind.EXPENSE_CATEGORY,
                    question=f"What was the {shown} for?",
                    options=[
                        {"id": c, "label": c.replace("_", " ").title(), "value": c} for c in choices
                    ],
                )
            )

    def _apply_links(self, extracted: ExtractedEvent, plan: NewEventPlan) -> None:
        ctx = self.ctx
        values = plan.values
        if extracted.project is not None:
            resolution = resolve_project(extracted.project, ctx)
            if resolution.project_id is not None:
                plan.project_links.append((resolution.project_id, resolution.source))
            if resolution.question is not None:
                plan.questions.append(resolution.question)
        seen = set()
        for mention in extracted.knowledge:
            knowledge = plan_knowledge(mention, ctx)
            if knowledge is not None and knowledge.key not in seen:
                seen.add(knowledge.key)
                plan.knowledge.append(knowledge)
        if extracted.habit is not None:
            outcome = (
                HabitOutcome.COMPLETED
                if extracted.habit.status == "completed"
                else HabitOutcome.MISSED
            )
            habit_id = resolve_habit(extracted.habit.ref, extracted.habit.name, ctx)
            if habit_id is not None:
                plan.habit_links.append((habit_id, outcome))
            else:
                values["structured_data"]["habit"] = {
                    "name": extracted.habit.name,
                    "status": extracted.habit.status,
                }
        if extracted.completes_task_ref in ctx.tasks:
            plan.completes_task_ids.append(ctx.tasks[extracted.completes_task_ref].id)
        if extracted.goal_ref in ctx.goals:
            plan.goal_ids.append(ctx.goals[extracted.goal_ref].id)
        if extracted.area_ref in ctx.areas:
            values["area_id"] = ctx.areas[extracted.area_ref].id
        elif plan.project_links:
            project = next(
                (p for p in ctx.projects.values() if p.id == plan.project_links[0][0]), None
            )
            if project is not None:
                values["area_id"] = project.area_id

    def _duration_question(self, title: str) -> QuestionPlan:
        options = [
            {"id": "30", "label": "~30m", "value": 30},
            {"id": "60", "label": "~1h", "value": 60},
            {"id": "120", "label": "~2h", "value": 120},
            {"id": "180", "label": "~3h", "value": 180},
            {"id": "unknown", "label": "Not sure", "value": None},
        ]
        return QuestionPlan(ClarificationKind.DURATION, f"About how long was “{title}”?", options)

    def _date_question(self, title: str) -> QuestionPlan:
        today = self.now_local.date()
        days = [
            ("Today", today),
            ("Yesterday", today - timedelta(days=1)),
            ("2 days ago", today - timedelta(days=2)),
        ]
        options = [
            {"id": d.isoformat(), "label": label, "value": d.isoformat()} for label, d in days
        ]
        options.append({"id": "unknown", "label": "Not sure", "value": None})
        return QuestionPlan(ClarificationKind.DATE, f"When was “{title}”?", options)

    def _check_duplicate(self, plan: NewEventPlan, event_type: EventType) -> None:
        values = plan.values
        candidates = self.db.scalars(
            select(Event).where(
                Event.user_id == self.ctx.user.id,
                Event.deleted_at.is_(None),
                Event.event_type == event_type,
                Event.occurred_on == values["occurred_on"],
            )
        ).all()
        project_ids = {project_id for project_id, _ in plan.project_links}
        leaving = self._replacing | {d.event.id for d in self.plan.deletes}
        best, best_score = None, 0.0
        for existing in candidates:
            if existing.id in leaving:
                continue
            score = duplicate_score(
                event_type=event_type,
                title=values["title"],
                topic=values["structured_data"].get("topic"),
                occurred_at=values["occurred_at"],
                ended_at=values["ended_at"],
                duration_seconds=values["duration_seconds"],
                amount=values["amount"],
                category=values["category"],
                project_ids=project_ids,
                existing=existing,
            )
            if score > best_score:
                best, best_score = existing, score
        if best is not None and best_score >= ASK_THRESHOLD:
            plan.questions.insert(
                0,
                QuestionPlan(
                    kind=ClarificationKind.DUPLICATE,
                    question=f"Is “{values['title']}” the same as the entry you already have ({_event_label(best)})?",
                    options=[
                        {"id": "same", "label": "Same — keep one", "value": "same"},
                        {"id": "different", "label": "Different — keep both", "value": "different"},
                    ],
                    payload={"existing_event_id": str(best.id)},
                ),
            )

    # --- merges ------------------------------------------------------------------------------

    def _plan_merge(
        self, existing: Event, extracted: ExtractedEvent, resolved: ResolvedTime
    ) -> None:
        values: dict = {}
        changes: list[str] = []
        if resolved.duration_seconds is not None and (
            existing.duration_seconds is None
            or (
                existing.duration_precision != DurationPrecision.EXACT
                and resolved.duration_precision == DurationPrecision.EXACT
            )
        ):
            values.update(
                duration_seconds=resolved.duration_seconds,
                duration_precision=resolved.duration_precision,
            )
            changes.append("duration")
        if resolved.occurred_at is not None and existing.occurred_at is None:
            values.update(
                occurred_at=resolved.occurred_at,
                occurred_on=resolved.occurred_on,
                time_precision=resolved.time_precision,
                day_period=None,
            )
            changes.append("start time")
        if resolved.ended_at is not None and existing.ended_at is None:
            start = values.get("occurred_at", existing.occurred_at)
            if start is None or resolved.ended_at >= start:
                values["ended_at"] = resolved.ended_at
                changes.append("end time")
        structured = dict(existing.structured_data or {})
        for name, value in (("topic", extracted.topic), ("output", extracted.output)):
            if value and value.strip() and not structured.get(name):
                structured[name] = value.strip()
                changes.append(name)
        if structured != (existing.structured_data or {}):
            values["structured_data"] = structured
        if extracted.description and not existing.description:
            values["description"] = extracted.description.strip()
            changes.append("details")

        project_links = None
        if extracted.project is not None and not existing.project_links:
            resolution = resolve_project(extracted.project, self.ctx)
            if resolution.project_id is not None:
                project_links = [(resolution.project_id, resolution.source)]
                changes.append("project")
        known = {link.knowledge_id for link in existing.knowledge_links}
        knowledge = [
            k
            for k in (plan_knowledge(m, self.ctx) for m in extracted.knowledge)
            if k is not None and k.existing_id not in known
        ]
        if knowledge:
            changes.append("knowledge")
        if not changes:
            self.plan.unchanged.append(existing)
            return
        self.plan.updates.append(
            UpdatePlan(
                event=existing,
                values=values,
                change_type=RevisionChangeType.MERGE,
                change_source=ChangeSource.DUPLICATE_MERGE,
                changes=changes,
                project_links=project_links,
                knowledge=knowledge,
            )
        )

    # --- corrections ---------------------------------------------------------------------

    def _hold_back_bulk_deletes(self) -> None:
        """Removing many records at once, or on a hunch, waits for a yes (spec #4 §44)."""
        plain = [d for d in self.plan.deletes if d.change_type == RevisionChangeType.DELETE]
        if len(plain) > MAX_SILENT_DELETES:
            self.plan.deletes = [d for d in self.plan.deletes if d not in plain]
            self.plan.deletes_to_confirm += [d.event for d in plain]
        targets = list({event.id: event for event in self.plan.deletes_to_confirm}.values())
        if not targets:
            return
        if len(targets) == 1:
            question = f"Delete “{_event_label(targets[0])}”?"
        else:
            shown = ", ".join(e.title for e in targets[:5]) + ("…" if len(targets) > 5 else "")
            question = f"Delete these {len(targets)} entries: {shown}?"
        self.plan.questions.insert(
            0,
            QuestionPlan(
                kind=ClarificationKind.CONFIRM,
                question=question,
                options=[
                    {"id": "remove", "label": "Delete", "value": "remove"},
                    {"id": "keep", "label": "Keep", "value": "keep"},
                ],
                payload={"reason": "delete", "event_ids": [str(e.id) for e in targets]},
            ),
        )

    def plan_correction(self, correction: Correction) -> None:
        evidence = self._evidence(correction.evidence, "correction")
        if evidence is None:
            return
        if evidence == PARTIAL:
            # Changing or removing a saved record needs the person's own words, not a guess.
            self.plan.warnings.append(
                "I didn't change anything because I wasn't sure what you meant."
            )
            return
        target = self.ctx.events.get(correction.target_ref) if correction.target_ref else None
        if target is None:
            candidates = [
                self.ctx.events[r]
                for r in dict.fromkeys(correction.candidate_refs)
                if r in self.ctx.events
            ]
            if len(candidates) == 1:
                target = candidates[0]
            elif len(candidates) > 1:
                self.plan.questions.append(
                    QuestionPlan(
                        kind=ClarificationKind.CORRECTION_TARGET,
                        question="Which entry should I change?",
                        options=[
                            {"id": str(e.id), "label": _event_label(e), "value": str(e.id)}
                            for e in candidates[:4]
                        ],
                        payload={"correction": correction.model_dump(mode="json")},
                    )
                )
                return
            else:
                self.plan.warnings.append("I couldn't tell which entry you wanted to change.")
                return
        self.apply_correction(target, correction)

    def apply_correction(
        self, target: Event, correction: Correction, *, confirmed: bool = False
    ) -> None:
        """confirmed: the person already picked this entry in answer to a question."""
        if correction.action == "delete":
            if confirmed or correction.confidence >= CONFIDENT_DELETE:
                self.plan.deletes.append(DeletePlan(target))
            else:
                self.plan.deletes_to_confirm.append(target)
            return
        if correction.action == "split":
            self._replacing.add(target.id)
            planned = [
                self.plan_event(item, default_day=target.occurred_on)
                for item in correction.split_into
            ]
            planned = [p for p in planned if p is not None]
            if not planned:
                self.plan.warnings.append(f"Couldn't split “{target.title}”.")
                return
            for p in planned:
                p.values["structured_data"]["split_from"] = str(target.id)
            self.plan.deletes.append(DeletePlan(target, RevisionChangeType.SPLIT))
            return
        self._plan_update(target, correction)

    def _plan_update(self, target: Event, correction: Correction) -> None:
        change = correction.changes
        if change is None:
            self.plan.warnings.append(f"Nothing to change on “{target.title}”.")
            return
        values: dict = {}
        changes: list[str] = []
        questions: list[QuestionPlan] = []
        if change.time is not None:
            base = time_info_from_event(target, self.now_local.tzinfo)
            resolved = resolve_time(
                apply_time_change(base, change.time), self.now_local, default_day=target.occurred_on
            )
            if resolved.in_future:
                self.plan.warnings.append(f"Didn't move “{target.title}” into the future.")
            else:
                for name, label in (
                    ("occurred_on", "date"),
                    ("occurred_at", "time"),
                    ("ended_at", None),
                    ("duration_seconds", "duration"),
                    ("time_precision", None),
                    ("duration_precision", None),
                    ("day_period", None),
                ):
                    new_value = getattr(resolved, name)
                    if new_value != getattr(target, name):
                        values[name] = new_value
                        if label and label not in changes:
                            changes.append(label)
        event_type = target.event_type
        if change.event_type and change.event_type != target.event_type.value:
            event_type = EventType(change.event_type)
            values["event_type"] = event_type
            changes.append("type")
        if change.title and change.title.strip() and change.title.strip() != target.title:
            values["title"] = change.title.strip()[:300]
            changes.append("title")
        if change.description is not None and change.description.strip():
            values["description"] = change.description.strip()
            changes.append("details")
        structured = dict(target.structured_data or {})
        for name in ("topic", "output"):
            value = getattr(change, name)
            if value and value.strip() and structured.get(name) != value.strip():
                structured[name] = value.strip()
                changes.append(name)
        if structured != (target.structured_data or {}):
            values["structured_data"] = structured

        project_links = None
        if change.remove_project:
            if target.project_links:
                project_links = []
                changes.append("project")
        elif change.project is not None:
            resolution = resolve_project(change.project, self.ctx)
            if resolution.project_id is not None:
                project_links = [(resolution.project_id, resolution.source)]
                changes.append("project")
            elif resolution.question is not None:
                questions.append(resolution.question)

        if change.money is not None and event_type in MONEY_EVENT_TYPES:
            money = change.money
            amount = parse_amount(money.amount)
            if amount is not None and amount != target.amount:
                values["amount"] = amount
                values["amount_precision"] = (
                    AmountPrecision.APPROXIMATE
                    if money.amount_precision == "approximate"
                    else AmountPrecision.EXACT
                )
                changes.append("amount")
            currency = normalize_currency(money.currency)
            if currency and currency != target.currency:
                values["currency"] = currency
                changes.append("currency")
            allowed = EXPENSE_CATEGORIES if event_type == EventType.EXPENSE else INCOME_CATEGORIES
            if money.category in allowed and money.category != target.category:
                values["category"] = money.category
                changes.append("category")

        if not changes and not questions:
            self.plan.warnings.append(f"“{target.title}” already matches that.")
            return
        self.plan.updates.append(
            UpdatePlan(
                event=target,
                values=values,
                change_type=RevisionChangeType.UPDATE,
                change_source=ChangeSource.AI_CORRECTION,
                changes=changes,
                project_links=project_links,
                questions=questions,
            )
        )

    # --- tasks -------------------------------------------------------------------------------

    def plan_task(self, task: ExtractedTask) -> None:
        title = task.title.strip()[:500]
        # A partly matching task is kept: it is only an intention, easy to see and remove.
        if not title or self._evidence(task.evidence, title) is None:
            return
        key = mention_key(title)
        for existing in self.ctx.tasks.values():
            existing_key = mention_key(existing.title)
            if key == existing_key or SequenceMatcher(None, key, existing_key).ratio() >= 0.9:
                self.plan.warnings.append(f"“{existing.title}” is already on your list.")
                return
        due = resolve_due(task.due, self.now_local.date()) if task.due.kind != "none" else None
        project_id = None
        if task.project is not None:
            project_id = resolve_project(task.project, self.ctx).project_id
        goal_id = self.ctx.goals[task.goal_ref].id if task.goal_ref in self.ctx.goals else None
        self.plan.new_tasks.append(
            TaskPlan(title=title, due_date=due, project_id=project_id, goal_id=goal_id)
        )


def build_plan(db: Session, ctx: ExtractionContext, output: ExtractionOutput) -> ChangePlan:
    return Planner(db, ctx).run(output)
