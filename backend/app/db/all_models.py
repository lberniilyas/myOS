"""Import every model so SQLAlchemy can resolve relationships and Alembic sees all tables."""

from app.areas.models import Area
from app.auth.models import AuthSession, User
from app.captures.models import Capture, Clarification, Source
from app.events.models import (
    Event,
    EventGoal,
    EventHabit,
    EventKnowledge,
    EventProject,
    EventRevision,
    EventTask,
)
from app.goals.models import Goal
from app.habits.models import Habit
from app.knowledge.models import Knowledge, KnowledgeAlias
from app.projects.models import Project, ProjectAlias, project_goals
from app.tasks.models import Task

__all__ = [
    "Area",
    "AuthSession",
    "Capture",
    "Clarification",
    "Event",
    "EventGoal",
    "EventHabit",
    "EventKnowledge",
    "EventProject",
    "EventRevision",
    "EventTask",
    "Goal",
    "Habit",
    "Knowledge",
    "KnowledgeAlias",
    "Project",
    "ProjectAlias",
    "Source",
    "Task",
    "User",
    "project_goals",
]
