"""Read-only tools the assistant can call. Each one is a deterministic, user-scoped query."""

import json
import logging
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.ai.provider import ToolOutcome, ToolSpec
from app.analytics.service import habit_outcomes, money_totals, time_totals
from app.auth.models import User
from app.core.enums import OPEN_TASK_STATUSES, EventType, TaskStatus
from app.core.formatting import format_amount, format_duration
from app.core.periods import Period, resolve_period
from app.core.text import name_match_score
from app.errors import AppError
from app.events.models import Event, EventProject
from app.events.service import like_pattern, search_condition
from app.habits.models import Habit
from app.knowledge import service as knowledge_service
from app.knowledge.models import Knowledge, KnowledgeAlias
from app.projects.models import Project
from app.projects.service import to_detail
from app.tasks.models import Task

logger = logging.getLogger(__name__)

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
    "GOAL_PROGRESS",
    "OTHER",
]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _PeriodArgs(_Args):
    period: Period = Field(description="Named period, or 'custom' with start_date and end_date.")
    start_date: str | None = Field(description="YYYY-MM-DD, only for period='custom'.")
    end_date: str | None = Field(description="YYYY-MM-DD, only for period='custom'.")


class ActivityTotalsArgs(_PeriodArgs):
    event_types: list[EventTypeName] | None = Field(
        description="Limit to these types, e.g. ['STUDY']."
    )
    project: str | None = Field(description="Project name or nickname.")
    group_by: Literal["none", "event_type", "project", "day"]


class SpendingArgs(_PeriodArgs):
    kind: Literal["expense", "income"]
    category: str | None = Field(description="e.g. 'food', 'transport'.")
    group_by: Literal["none", "category", "day"]


class ListEventsArgs(_PeriodArgs):
    event_types: list[EventTypeName] | None
    project: str | None
    text: str | None = Field(description="Words to search for in titles and descriptions.")
    limit: int = Field(description="At most 50.")


class KnowledgeArgs(_PeriodArgs):
    text: str | None = Field(
        description=(
            "Only to look up one specific concept by name, e.g. 'RAG'. Use null to list "
            "everything the person learned in the period."
        )
    )


class ProjectSummaryArgs(_Args):
    project: str = Field(description="Project name or nickname.")


class HabitSummaryArgs(_PeriodArgs):
    habit: str | None = Field(description="Habit name; null for all habits.")


class NoArgs(_Args):
    pass


class TasksArgs(_Args):
    include_done: bool = Field(description="Also list tasks completed in the last 7 days.")


TOOLS = [
    ToolSpec(
        "get_activity_totals",
        "Total recorded time for a period, optionally by event type, project or day. Reports how many "
        "durations were approximate or missing.",
        ActivityTotalsArgs,
    ),
    ToolSpec(
        "get_spending",
        "Money spent or received in a period, per currency, optionally by category or day.",
        SpendingArgs,
    ),
    ToolSpec(
        "list_events",
        "List recorded events in a period, newest first, with filters.",
        ListEventsArgs,
    ),
    ToolSpec(
        "search_knowledge",
        "Concepts the person recorded learning in a period, with how well they reported "
        "knowing them. To answer 'what did I learn', call it with text=null.",
        KnowledgeArgs,
    ),
    ToolSpec(
        "get_project_summary",
        "One project's status, total time, recent activity and open tasks.",
        ProjectSummaryArgs,
    ),
    ToolSpec(
        "get_habit_summary",
        "How often each habit was completed or missed in a period.",
        HabitSummaryArgs,
    ),
    ToolSpec("list_projects", "All of the person's projects with their status.", NoArgs),
    ToolSpec("list_tasks", "Open tasks with due dates and projects, soonest first.", TasksArgs),
]
_ARGS = {tool.name: tool.input_model for tool in TOOLS}


class ToolError(Exception):
    pass


class AssistantTools:
    def __init__(self, db: Session, user: User, today: date) -> None:
        self.db, self.user, self.today = db, user, today
        self.event_ids: list[str] = []

    def execute(self, name: str, arguments: dict) -> ToolOutcome:
        model = _ARGS.get(name)
        if model is None:
            return ToolOutcome(json.dumps({"error": f"Unknown tool {name}."}), is_error=True)
        try:
            args = model.model_validate(arguments)
            result = getattr(self, name)(args)
        except ValidationError as exc:
            return ToolOutcome(
                json.dumps({"error": f"Invalid arguments: {exc.errors()[:3]}"}, default=str),
                is_error=True,
            )
        except (ToolError, AppError) as exc:
            return ToolOutcome(json.dumps({"error": str(exc)}), is_error=True)
        except Exception:  # noqa: BLE001 - one broken tool must not sink the whole answer
            logger.exception("Assistant tool %s failed", name)
            self.db.rollback()
            return ToolOutcome(
                json.dumps({"error": "This lookup failed on the server."}), is_error=True
            )
        return ToolOutcome(json.dumps(result, default=str, ensure_ascii=False))

    def _period(self, args: _PeriodArgs) -> tuple[date, date]:
        try:
            start = date.fromisoformat(args.start_date) if args.start_date else None
            end = date.fromisoformat(args.end_date) if args.end_date else None
        except ValueError as exc:
            raise ToolError("Dates must be YYYY-MM-DD.") from exc
        return resolve_period(
            args.period, self.today, week_start=self.user.week_start, start=start, end=end
        )

    def _project(self, name: str) -> Project:
        projects = self.db.scalars(
            select(Project).where(Project.user_id == self.user.id, Project.deleted_at.is_(None))
        ).all()
        scored = sorted(
            (
                (name_match_score(name, [p.name] + [a.alias for a in p.aliases]), p)
                for p in projects
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if not scored or scored[0][0] < 0.75:
            raise ToolError(
                f"No project matches '{name}'. Known: {', '.join(p.name for p in projects) or 'none'}."
            )
        if len(scored) > 1 and scored[1][0] >= 0.85 and scored[0][0] < 1.0:
            raise ToolError(f"'{name}' could mean {scored[0][1].name} or {scored[1][1].name}.")
        return scored[0][1]

    def get_activity_totals(self, args: ActivityTotalsArgs) -> dict:
        start, end = self._period(args)
        project_id = self._project(args.project).id if args.project else None
        types = [EventType(t) for t in args.event_types] if args.event_types else None
        rows = time_totals(
            self.db,
            self.user.id,
            start=start,
            end=end,
            event_types=types,
            project_id=project_id,
            group_by=None if args.group_by == "none" else args.group_by,
        )
        return {"start": start, "end": end, "rows": rows}

    def get_spending(self, args: SpendingArgs) -> dict:
        start, end = self._period(args)
        rows = money_totals(
            self.db,
            self.user.id,
            start=start,
            end=end,
            event_type=EventType.EXPENSE if args.kind == "expense" else EventType.INCOME,
            category=args.category.lower() if args.category else None,
            group_by=None if args.group_by == "none" else args.group_by,
        )
        return {"start": start, "end": end, "rows": rows}

    def list_events(self, args: ListEventsArgs) -> dict:
        start, end = self._period(args)
        stmt = select(Event).where(
            Event.user_id == self.user.id,
            Event.deleted_at.is_(None),
            Event.occurred_on.between(start, end),
        )
        if args.event_types:
            stmt = stmt.where(Event.event_type.in_(args.event_types))
        if args.project:
            project = self._project(args.project)
            stmt = stmt.where(
                exists().where(
                    EventProject.event_id == Event.id, EventProject.project_id == project.id
                )
            )
        if args.text and args.text.strip():
            stmt = stmt.where(search_condition(args.text))
        limit = max(1, min(args.limit, 50))
        events = self.db.scalars(
            stmt.order_by(Event.occurred_on.desc(), Event.sort_at.desc()).limit(limit)
        ).all()
        self.event_ids.extend(str(e.id) for e in events)
        return {
            "start": start,
            "end": end,
            "events": [
                {
                    "date": e.occurred_on,
                    "type": e.event_type.value,
                    "title": e.title,
                    "duration": format_duration(e.duration_seconds, e.duration_precision),
                    "amount": format_amount(e.amount, e.currency, e.amount_precision),
                    "topic": (e.structured_data or {}).get("topic"),
                    "output": (e.structured_data or {}).get("output"),
                    "projects": [link.project.name for link in e.project_links],
                }
                for e in events
            ],
        }

    def search_knowledge(self, args: KnowledgeArgs) -> dict:
        start, end = self._period(args)
        stmt = select(Knowledge).where(
            Knowledge.user_id == self.user.id, Knowledge.deleted_at.is_(None)
        )
        if args.text and args.text.strip():
            pattern = like_pattern(args.text)
            alias_ids = select(KnowledgeAlias.knowledge_id).where(
                KnowledgeAlias.alias.ilike(pattern, escape="\\")
            )
            stmt = stmt.where(
                or_(Knowledge.title.ilike(pattern, escape="\\"), Knowledge.id.in_(alias_ids))
            )
        items = self.db.scalars(stmt.order_by(Knowledge.updated_at.desc()).limit(50)).all()
        stats = knowledge_service.evidence_stats(self.db, [k.id for k in items])
        result = []
        for k in items:
            count, last_seen = stats.get(k.id, (0, None))
            if args.period != "all_time" and not (
                (k.first_encountered_on and start <= k.first_encountered_on <= end)
                or (last_seen and start <= last_seen <= end)
            ):
                continue
            result.append(
                {
                    "title": k.title,
                    "aliases": [a.alias for a in k.aliases],
                    "understanding": k.understanding_state.value,
                    "first_encountered": k.first_encountered_on,
                    "last_seen": last_seen,
                    "evidence_events": count,
                }
            )
        response: dict = {"start": start, "end": end, "knowledge": result}
        if not result and args.text:
            response["note"] = (
                f"No concept is named like '{args.text}'. Call again with text=null to list "
                "everything learned in this period."
            )
        return response

    def get_project_summary(self, args: ProjectSummaryArgs) -> dict:
        project = self._project(args.project)
        total = time_totals(self.db, self.user.id, start=None, end=None, project_id=project.id)[0]
        last_30 = time_totals(
            self.db,
            self.user.id,
            start=resolve_period("last_30_days", self.today)[0],
            end=self.today,
            project_id=project.id,
        )[0]
        detail = to_detail(self.db, self.user, project, self.today)
        return {
            "name": project.name,
            "status": project.status.value,
            "total": total,
            "last_30_days": last_30,
            "last_activity_on": detail.stats.last_activity_on,
            "open_tasks": [t.title for t in detail.open_tasks],
            "recent": [
                f"{e.occurred_on} {e.title} {e.duration_display or ''}".strip()
                for e in detail.recent_events[:5]
            ],
        }

    def get_habit_summary(self, args: HabitSummaryArgs) -> dict:
        start, end = self._period(args)
        habit_id = None
        if args.habit:
            habits = self.db.scalars(select(Habit).where(Habit.user_id == self.user.id)).all()
            best = max(
                ((name_match_score(args.habit, [h.name]), h) for h in habits),
                key=lambda p: p[0],
                default=(0, None),
            )
            if best[0] < 0.75:
                raise ToolError(f"No habit matches '{args.habit}'.")
            habit_id = best[1].id
        return {
            "start": start,
            "end": end,
            "habits": habit_outcomes(
                self.db, self.user.id, start=start, end=end, habit_id=habit_id
            ),
        }

    def list_projects(self, args: NoArgs) -> dict:
        projects = self.db.scalars(
            select(Project)
            .where(Project.user_id == self.user.id, Project.deleted_at.is_(None))
            .order_by(Project.name)
        ).all()
        return {
            "projects": [
                {"name": p.name, "status": p.status.value, "aliases": [a.alias for a in p.aliases]}
                for p in projects
            ]
        }

    def list_tasks(self, args: TasksArgs) -> dict:
        tasks = self.db.scalars(
            select(Task)
            .where(Task.user_id == self.user.id, Task.deleted_at.is_(None))
            .order_by(Task.due_date.nulls_last(), Task.created_at)
        ).all()
        recent = self.today - timedelta(days=7)
        result = []
        for task in tasks:
            done = task.status == TaskStatus.COMPLETED
            if task.status in OPEN_TASK_STATUSES or (
                args.include_done
                and done
                and task.completed_at
                and task.completed_at.date() >= recent
            ):
                project = self.db.get(Project, task.project_id) if task.project_id else None
                result.append(
                    {
                        "title": task.title,
                        "status": task.status.value,
                        "due": task.due_date,
                        "overdue": bool(task.due_date and task.due_date < self.today and not done),
                        "project": project.name if project else None,
                    }
                )
        return {"today": self.today, "tasks": result}
