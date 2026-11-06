"""Entity resolution: connect the user's words to existing projects, habits and knowledge.

The model may propose a ref; code double-checks it, and falls back to deterministic name
matching. Ambiguity turns into a question instead of a guess, and nothing is created just
because the wording differs (spec #4 §12).
"""

import uuid
from dataclasses import dataclass, field

from app.ai.extraction_schema import KnowledgeMention, ProjectMention
from app.captures.context import ExtractionContext
from app.core.enums import ClarificationKind, LinkSource, ProjectStatus, UnderstandingState
from app.core.text import compact_key, name_match_score

STRONG_MATCH = 0.85
CERTAIN_MATCH = 0.95

UNDERSTANDING_FROM_MODEL = {
    "encountered": UnderstandingState.ENCOUNTERED,
    "studied": UnderstandingState.STUDIED,
    "reported_understanding": UnderstandingState.REPORTED_UNDERSTANDING,
    "demonstrated": UnderstandingState.DEMONSTRATED,
}


@dataclass
class QuestionPlan:
    kind: ClarificationKind
    question: str
    options: list[dict]
    payload: dict = field(default_factory=dict)


@dataclass
class ProjectResolution:
    project_id: uuid.UUID | None = None
    source: LinkSource = LinkSource.AI
    question: QuestionPlan | None = None


@dataclass
class KnowledgePlan:
    key: str
    title: str
    aliases: list[str]
    understanding: UnderstandingState
    existing_id: uuid.UUID | None = None


def _project_choice(text: str, projects: list, *, learn_alias: bool) -> QuestionPlan:
    names = [p.name for p in projects]
    listed = ", ".join(names[:-1]) + f" or {names[-1]}" if len(names) > 1 else names[0]
    options = [{"id": str(p.id), "label": p.name, "value": str(p.id)} for p in projects]
    options.append({"id": "none", "label": "None of these", "value": None})
    return QuestionPlan(
        kind=ClarificationKind.PROJECT_CHOICE,
        question=f"Which project did you mean by “{text}” — {listed}?",
        options=options,
        # A named mention ("the tender app") is remembered as a nickname once the user picks.
        payload={"mention": text if learn_alias else None},
    )


def resolve_project(mention: ProjectMention, ctx: ExtractionContext) -> ProjectResolution:
    if mention.ref and mention.ref in ctx.projects:
        return ProjectResolution(project_id=ctx.projects[mention.ref].id, source=LinkSource.AI)

    projects = list(ctx.projects.values())
    if mention.kind == "generic":
        active = [p for p in projects if p.status == ProjectStatus.ACTIVE]
        if len(active) == 1:
            return ProjectResolution(project_id=active[0].id, source=LinkSource.INFERRED)
        if len(active) > 1:
            return ProjectResolution(
                question=_project_choice(mention.text, active[:4], learn_alias=False)
            )
        return ProjectResolution()

    scored = sorted(
        (
            (name_match_score(mention.text, [p.name] + [a.alias for a in p.aliases]), p)
            for p in projects
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    scored = [(score, p) for score, p in scored if score >= 0.75]
    if scored:
        best_score, best = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if best_score >= CERTAIN_MATCH and runner_up < STRONG_MATCH:
            return ProjectResolution(project_id=best.id, source=LinkSource.AI)
        if best_score >= STRONG_MATCH and len(scored) == 1:
            return ProjectResolution(project_id=best.id, source=LinkSource.AI)
        return ProjectResolution(
            question=_project_choice(mention.text, [p for _, p in scored[:4]], learn_alias=True)
        )

    name = mention.text.strip()[:200]
    if not compact_key(name):
        return ProjectResolution()
    return ProjectResolution(
        question=QuestionPlan(
            kind=ClarificationKind.CREATE_PROJECT,
            question=f"I don't have a project called “{name}”. Create it?",
            options=[
                {"id": "create", "label": f"Create “{name}”", "value": name},
                {"id": "no", "label": "Not a project", "value": None},
            ],
            payload={"name": name},
        )
    )


def plan_knowledge(mention: KnowledgeMention, ctx: ExtractionContext) -> KnowledgePlan | None:
    title = mention.title.strip()[:300]
    key = compact_key(title)
    if not key:
        return None
    understanding = UNDERSTANDING_FROM_MODEL.get(
        mention.understanding, UnderstandingState.ENCOUNTERED
    )
    aliases = [alias.strip() for alias in mention.aliases if compact_key(alias)]
    if mention.ref and mention.ref in ctx.knowledge:
        existing = ctx.knowledge[mention.ref]
        return KnowledgePlan(
            existing.title_key, existing.title, aliases, understanding, existing.id
        )
    keys = {key} | {compact_key(alias) for alias in aliases}
    for existing in ctx.knowledge.values():
        known = {existing.title_key} | {alias.alias_key for alias in existing.aliases}
        if keys & known:
            return KnowledgePlan(
                existing.title_key, existing.title, aliases, understanding, existing.id
            )
    return KnowledgePlan(key, title, aliases, understanding)


def resolve_habit(ref: str | None, name: str | None, ctx: ExtractionContext) -> uuid.UUID | None:
    if ref and ref in ctx.habits:
        return ctx.habits[ref].id
    if name:
        best = max(
            ((name_match_score(name, [habit.name]), habit) for habit in ctx.habits.values()),
            key=lambda pair: pair[0],
            default=(0.0, None),
        )
        if best[0] >= STRONG_MATCH:
            return best[1].id
    return None
