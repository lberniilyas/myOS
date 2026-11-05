"""Persist a change plan. Callers run this inside one transaction (spec #8 §44)."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.captures.models import Capture, Clarification
from app.captures.planner import ChangePlan
from app.captures.resolution import KnowledgePlan, QuestionPlan
from app.core.enums import ChangeSource, LinkSource, TaskStatus
from app.events.models import Event, EventGoal, EventHabit, EventKnowledge, EventProject, EventTask
from app.events.service import record_revision, snapshot, soft_delete
from app.knowledge import service as knowledge_service
from app.knowledge.models import Knowledge
from app.tasks.models import Task


@dataclass
class AppliedChanges:
    created: list[Event] = field(default_factory=list)
    updated: list[tuple[Event, list[str]]] = field(default_factory=list)
    deleted: list[Event] = field(default_factory=list)
    unchanged: list[Event] = field(default_factory=list)
    tasks_created: list[Task] = field(default_factory=list)
    tasks_completed: list[Task] = field(default_factory=list)
    knowledge_created: list[Knowledge] = field(default_factory=list)
    clarifications: list[Clarification] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class _KnowledgeResolver:
    def __init__(self, db: Session, user_id: uuid.UUID, result: AppliedChanges) -> None:
        self.db, self.user_id, self.result = db, user_id, result
        self.by_key: dict[str, Knowledge] = {}

    def get(self, plan: KnowledgePlan, occurred_on) -> Knowledge:
        knowledge = None
        if plan.existing_id is not None:
            knowledge = self.db.get(Knowledge, plan.existing_id)
        if knowledge is None:
            knowledge = self.by_key.get(plan.key) or knowledge_service.find_by_key(
                self.db, self.user_id, plan.key
            )
        if knowledge is None:
            knowledge = knowledge_service.create_knowledge(
                self.db,
                self.user_id,
                plan.title,
                understanding=plan.understanding,
                aliases=plan.aliases,
                first_encountered_on=occurred_on,
            )
            self.result.knowledge_created.append(knowledge)
        else:
            knowledge_service.raise_understanding(knowledge, plan.understanding)
            for alias in plan.aliases:
                knowledge_service.add_alias(self.db, knowledge, alias)
            if (
                knowledge.first_encountered_on is None
                or occurred_on < knowledge.first_encountered_on
            ):
                knowledge.first_encountered_on = occurred_on
        self.by_key[plan.key] = knowledge
        return knowledge


def _clarification(
    capture: Capture, question: QuestionPlan, event_id: uuid.UUID | None
) -> Clarification:
    return Clarification(
        user_id=capture.user_id,
        capture_id=capture.id,
        event_id=event_id,
        kind=question.kind,
        question=question.question,
        options=question.options,
        payload=question.payload,
    )


def apply_plan(db: Session, capture: Capture, plan: ChangePlan, now: datetime) -> AppliedChanges:
    result = AppliedChanges(warnings=list(plan.warnings), unchanged=list(plan.unchanged))
    knowledge = _KnowledgeResolver(db, capture.user_id, result)

    for planned in plan.new_events:
        event = Event(**planned.values)
        event.project_links = [
            EventProject(project_id=pid, link_source=src) for pid, src in planned.project_links
        ]
        event.goal_links = [
            EventGoal(goal_id=gid, link_source=LinkSource.AI) for gid in planned.goal_ids
        ]
        event.habit_links = [
            EventHabit(habit_id=hid, outcome=outcome, link_source=LinkSource.AI)
            for hid, outcome in planned.habit_links
        ]
        links = {}
        for item in planned.knowledge:
            entry = knowledge.get(item, event.occurred_on)
            links[entry.id] = EventKnowledge(knowledge_id=entry.id, link_source=LinkSource.AI)
        event.knowledge_links = list(links.values())
        for task_id in planned.completes_task_ids:
            task = db.get(Task, task_id)
            if task is None or task.deleted_at is not None:
                continue
            if task.status != TaskStatus.COMPLETED:
                task.status = TaskStatus.COMPLETED
                task.completed_at = event.ended_at or event.occurred_at or now
                result.tasks_completed.append(task)
            event.task_links.append(EventTask(task_id=task.id, link_source=LinkSource.AI))
        db.add(event)
        db.flush()
        result.created.append(event)
        for question in planned.questions:
            result.clarifications.append(_clarification(capture, question, event.id))

    for update in plan.updates:
        event = update.event
        before = snapshot(event)
        for name, value in update.values.items():
            setattr(event, name, value)
        if update.project_links is not None:
            event.project_links = [
                EventProject(project_id=pid, link_source=src) for pid, src in update.project_links
            ]
        existing_knowledge = {link.knowledge_id for link in event.knowledge_links}
        for item in update.knowledge:
            entry = knowledge.get(item, event.occurred_on)
            if entry.id not in existing_knowledge:
                event.knowledge_links.append(
                    EventKnowledge(knowledge_id=entry.id, link_source=LinkSource.AI)
                )
                existing_knowledge.add(entry.id)
        event.corrected_at = now
        record_revision(
            db,
            event,
            before,
            change_type=update.change_type,
            change_source=update.change_source,
            capture_id=capture.id,
        )
        result.updated.append((event, update.changes))
        for question in update.questions:
            result.clarifications.append(_clarification(capture, question, event.id))

    for delete in plan.deletes:
        soft_delete(
            db,
            delete.event,
            change_source=ChangeSource.AI_CORRECTION,
            change_type=delete.change_type,
            capture_id=capture.id,
            now=now,
        )
        result.deleted.append(delete.event)

    for planned_task in plan.new_tasks:
        task = Task(
            user_id=capture.user_id,
            capture_id=capture.id,
            title=planned_task.title,
            due_date=planned_task.due_date,
            project_id=planned_task.project_id,
            goal_id=planned_task.goal_id,
        )
        db.add(task)
        result.tasks_created.append(task)

    for question in plan.questions:
        result.clarifications.append(_clarification(capture, question, None))
    for clarification in result.clarifications:
        db.add(clarification)
    db.flush()
    return result
