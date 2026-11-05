from enum import StrEnum


class EventType(StrEnum):
    STUDY = "STUDY"
    WORK = "WORK"
    PROJECT_WORK = "PROJECT_WORK"
    KNOWLEDGE = "KNOWLEDGE"
    TASK_ACTIVITY = "TASK_ACTIVITY"
    HABIT = "HABIT"
    EXERCISE = "EXERCISE"
    EXPENSE = "EXPENSE"
    INCOME = "INCOME"
    DEVICE_USAGE = "DEVICE_USAGE"
    SLEEP = "SLEEP"
    JOURNAL = "JOURNAL"
    STATE = "STATE"
    MILESTONE = "MILESTONE"
    GOAL_PROGRESS = "GOAL_PROGRESS"
    OTHER = "OTHER"


# Event types whose meaning includes "for how long", used for duration questions and totals.
TIMED_EVENT_TYPES = frozenset(
    {
        EventType.STUDY,
        EventType.WORK,
        EventType.PROJECT_WORK,
        EventType.TASK_ACTIVITY,
        EventType.EXERCISE,
        EventType.DEVICE_USAGE,
        EventType.SLEEP,
    }
)
MONEY_EVENT_TYPES = frozenset({EventType.EXPENSE, EventType.INCOME})


class TimePrecision(StrEnum):
    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"
    DATE_ONLY = "DATE_ONLY"
    UNKNOWN = "UNKNOWN"


class DurationPrecision(StrEnum):
    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"
    UNKNOWN = "UNKNOWN"


class AmountPrecision(StrEnum):
    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"


class DayPeriod(StrEnum):
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"
    EVENING = "EVENING"
    NIGHT = "NIGHT"


class SourceType(StrEnum):
    USER_TEXT = "USER_TEXT"
    USER_VOICE = "USER_VOICE"
    MANUAL_INPUT = "MANUAL_INPUT"
    IOS_AUTOMATION = "IOS_AUTOMATION"
    PC_AGENT = "PC_AGENT"
    CALENDAR = "CALENDAR"
    FINANCIAL_IMPORT = "FINANCIAL_IMPORT"
    INTEGRATION = "INTEGRATION"
    AI_GENERATED = "AI_GENERATED"
    OTHER = "OTHER"


class InputType(StrEnum):
    TEXT = "TEXT"
    VOICE = "VOICE"
    MANUAL = "MANUAL"
    IMPORT = "IMPORT"
    AUTOMATION = "AUTOMATION"
    INTEGRATION = "INTEGRATION"


class CaptureStatus(StrEnum):
    CAPTURED = "CAPTURED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    FAILED = "FAILED"


class CreatedBy(StrEnum):
    USER = "USER"
    AI_EXTRACTION = "AI_EXTRACTION"
    SYSTEM = "SYSTEM"
    INTEGRATION = "INTEGRATION"


class LinkSource(StrEnum):
    AI = "AI"
    USER = "USER"
    CLARIFICATION = "CLARIFICATION"
    INFERRED = "INFERRED"


class HabitOutcome(StrEnum):
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class ProjectStatus(StrEnum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ARCHIVED = "ARCHIVED"


class GoalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ARCHIVED = "ARCHIVED"


class TaskStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DEFERRED = "DEFERRED"


OPEN_TASK_STATUSES = frozenset({TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.DEFERRED})


class TaskPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class HabitFrequency(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class HabitStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class KnowledgeType(StrEnum):
    CONCEPT = "CONCEPT"
    SKILL = "SKILL"
    TOOL = "TOOL"
    FACT = "FACT"
    OTHER = "OTHER"


class UnderstandingState(StrEnum):
    UNKNOWN = "UNKNOWN"
    ENCOUNTERED = "ENCOUNTERED"
    STUDIED = "STUDIED"
    REPORTED_UNDERSTANDING = "REPORTED_UNDERSTANDING"
    DEMONSTRATED = "DEMONSTRATED"


UNDERSTANDING_RANK = {state: rank for rank, state in enumerate(UnderstandingState)}


class ClarificationKind(StrEnum):
    PROJECT_CHOICE = "PROJECT_CHOICE"
    CREATE_PROJECT = "CREATE_PROJECT"
    DURATION = "DURATION"
    EXPENSE_CATEGORY = "EXPENSE_CATEGORY"
    AMOUNT = "AMOUNT"
    DUPLICATE = "DUPLICATE"
    CORRECTION_TARGET = "CORRECTION_TARGET"
    DATE = "DATE"


class ClarificationStatus(StrEnum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    DISMISSED = "DISMISSED"
    EXPIRED = "EXPIRED"


class RevisionChangeType(StrEnum):
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    RESTORE = "RESTORE"
    MERGE = "MERGE"
    SPLIT = "SPLIT"


class ChangeSource(StrEnum):
    USER_EDIT = "USER_EDIT"
    AI_CORRECTION = "AI_CORRECTION"
    CLARIFICATION = "CLARIFICATION"
    DUPLICATE_MERGE = "DUPLICATE_MERGE"
    SYSTEM = "SYSTEM"


EXPENSE_CATEGORIES = (
    "food",
    "groceries",
    "transport",
    "housing",
    "utilities",
    "health",
    "education",
    "shopping",
    "electronics",
    "entertainment",
    "subscriptions",
    "travel",
    "gifts",
    "personal_care",
    "fees",
    "other",
)
INCOME_CATEGORIES = ("salary", "freelance", "gift", "refund", "investment", "other")
