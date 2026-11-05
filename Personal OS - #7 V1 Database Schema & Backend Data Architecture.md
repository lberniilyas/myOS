# Personal OS — #7 V1 Database Schema & Backend Data Architecture

## 1. Purpose

Design the first production-quality database architecture for the Personal OS.

The database must support:

* Natural-language capture
* Voice capture
* Universal events
* Projects
* Goals
* Knowledge
* Tasks
* Habits
* Finance
* Device usage
* Insights
* AI memory
* Provenance
* Corrections
* Relationships
* Future integrations

The database must remain simple enough for V1 while being structurally strong enough to evolve.

The central principle is:

> **Build the database around the user's life and its relationships, not around app screens.**

---

# 2. Recommended V1 Stack

Use:

**PostgreSQL**

for the primary relational database.

Recommended backend:

**FastAPI + Python**

Use an ORM such as:

**SQLAlchemy**

Use migrations through:

**Alembic**

The database should be accessible only through backend services.

The iPhone app should never connect directly to PostgreSQL.

Architecture:

**iPhone**

↓

**API**

↓

**Application Services**

↓

**PostgreSQL**

External AI providers and integrations should also communicate through backend services.

---

# 3. Core V1 Tables

Start with these tables:

1. `users`
2. `areas`
3. `goals`
4. `systems`
5. `projects`
6. `habits`
7. `tasks`
8. `events`
9. `knowledge`
10. `sources`
11. `captures`
12. `insights`
13. `experiments`
14. `reviews`
15. `memories`

Relationship tables can be added where required.

Do not create a separate table for every possible event type.

---

# 4. Users

Table:

`users`

Fields:

* `id`
* `name`
* `email` if needed
* `timezone`
* `locale`
* `created_at`
* `updated_at`
* `preferences`
* `privacy_settings`

Use UUIDs for primary identifiers.

Example:

`id UUID PRIMARY KEY`

Do not use sequential public IDs.

---

# 5. Areas

Table:

`areas`

Purpose:

Represent broad life domains.

Example:

* Career
* Education
* Finance
* Health
* Personal
* Technology
* Relationships
* Projects

Fields:

* `id`
* `user_id`
* `name`
* `description`
* `created_at`
* `updated_at`

Areas are configurable.

Do not hard-code the system around a fixed set of categories.

---

# 6. Goals

Table:

`goals`

Fields:

* `id`
* `user_id`
* `area_id`
* `parent_goal_id`
* `title`
* `description`
* `status`
* `start_date`
* `target_date`
* `created_at`
* `updated_at`

Possible statuses:

* ACTIVE
* PAUSED
* COMPLETED
* CANCELLED
* ARCHIVED

A goal may have child goals.

Example:

Goal:

**Become an AI Engineer**

Child goals:

* Complete master's
* Build portfolio
* Gain professional experience

Avoid storing arbitrary "73% complete" values as the primary representation of progress.

Progress should be derived from evidence.

---

# 7. Systems

Table:

`systems`

A system represents a recurring mechanism supporting a goal.

Example:

Goal:

**Become an AI Engineer**

System:

**Weekly AI study system**

Fields:

* `id`
* `user_id`
* `goal_id`
* `title`
* `description`
* `status`
* `frequency`
* `created_at`
* `updated_at`

A system can be connected to:

* Habits
* Tasks
* Events
* Metrics

---

# 8. Projects

Table:

`projects`

Fields:

* `id`
* `user_id`
* `area_id`
* `parent_project_id`
* `name`
* `description`
* `status`
* `start_date`
* `target_date`
* `completed_at`
* `metadata`
* `created_at`
* `updated_at`

Statuses:

* PLANNED
* ACTIVE
* PAUSED
* COMPLETED
* CANCELLED
* ARCHIVED

Projects represent finite bodies of work.

Examples:

* TenderPilot
* BLANI
* Personal OS
* Master's applications

---

# 9. Project Aliases

Because natural language is used heavily, create:

`project_aliases`

Fields:

* `id`
* `project_id`
* `alias`
* `created_at`

Examples:

Project:

TenderPilot

Aliases:

* tender app
* tender project
* procurement AI
* hackathon project

This improves entity resolution.

---

# 10. Habits

Table:

`habits`

Fields:

* `id`
* `user_id`
* `area_id`
* `system_id`
* `name`
* `description`
* `frequency`
* `target`
* `status`
* `created_at`
* `updated_at`

A habit should define the behavior being tracked, not merely a streak.

Example:

**Exercise**

Target:

3 times/week

The actual behavior should be derived from events whenever possible.

---

# 11. Tasks

Table:

`tasks`

Fields:

* `id`
* `user_id`
* `project_id`
* `goal_id`
* `title`
* `description`
* `status`
* `priority`
* `due_at`
* `completed_at`
* `created_at`
* `updated_at`

Statuses:

* TODO
* IN_PROGRESS
* COMPLETED
* CANCELLED
* DEFERRED

Tasks represent intended actions.

Events represent things that happened.

Do not merge them.

---

# 12. Events

Table:

`events`

This is the most important table in the system.

Fields:

* `id`
* `user_id`
* `area_id`
* `event_type`
* `title`
* `description`
* `occurred_at`
* `ended_at`
* `duration_seconds`
* `time_precision`
* `structured_data`
* `user_reported_data`
* `observed_data`
* `ai_interpretation`
* `extraction_confidence`
* `source_id`
* `capture_id`
* `created_at`
* `updated_at`
* `corrected_at`
* `deleted_at`

---

# 13. Event Type

Keep the event-type system small.

Possible V1 values:

* STUDY
* WORK
* PROJECT_WORK
* KNOWLEDGE
* TASK_ACTIVITY
* HABIT
* EXPENSE
* INCOME
* DEVICE_USAGE
* JOURNAL
* SLEEP
* EXERCISE
* MILESTONE
* GOAL_PROGRESS
* OTHER

Do not create dozens of specialized event tables.

The event type determines how the event is interpreted.

---

# 14. Event Structured Data

Use PostgreSQL `JSONB` for flexible event-specific information.

Example:

```json
{
  "topic": "RAG",
  "output": "Understood vector databases",
  "amount": null
}
```

For an expense:

```json
{
  "amount": 30,
  "currency": "MAD",
  "category": "food",
  "merchant": "restaurant"
}
```

For device usage:

```json
{
  "device": "iphone",
  "application": "YouTube",
  "usage_seconds": 7200
}
```

The relational fields should contain information required for querying.

JSONB should contain flexible event-specific metadata.

Do not put everything into JSONB.

---

# 15. Time Representation

Events need flexible time precision.

Use:

`occurred_at`

`ended_at`

`duration_seconds`

and:

`time_precision`

Possible values:

* EXACT
* APPROXIMATE
* DATE_ONLY
* UNKNOWN

Example:

> "I studied for around 3 hours."

Store:

`duration_seconds = 10800`

`time_precision = APPROXIMATE`

Do not invent start/end timestamps.

---

# 16. Approximate Time

If the user says:

> "Yesterday afternoon."

Store the date and approximate period without inventing an exact timestamp.

If necessary, structured metadata can contain:

```json
{
  "time_period": "afternoon"
}
```

The system should preserve uncertainty.

---

# 17. Money Representation

Financial events should have consistent structured fields.

For financial events:

* amount
* currency
* direction
* category
* merchant
* account
* payment method if available
* transaction date

Example:

```json
{
  "amount": 30,
  "currency": "MAD",
  "direction": "EXPENSE",
  "category": "food"
}
```

Never infer a currency when it is genuinely unknown.

---

# 18. Event Relationships

Events can connect to multiple entities.

Create relationship tables rather than putting arrays of IDs into events.

Examples:

`event_goals`

* `event_id`
* `goal_id`

`event_projects`

* `event_id`
* `project_id`

`event_systems`

* `event_id`
* `system_id`

`event_habits`

* `event_id`
* `habit_id`

`event_tasks`

* `event_id`
* `task_id`

`event_knowledge`

* `event_id`
* `knowledge_id`

This supports many-to-many relationships.

---

# 19. Knowledge

Table:

`knowledge`

Fields:

* `id`
* `user_id`
* `area_id`
* `title`
* `description`
* `knowledge_type`
* `understanding_state`
* `created_at`
* `updated_at`

Possible understanding states:

* ENCOUNTERED
* STUDIED
* REPORTED_UNDERSTANDING
* DEMONSTRATED
* UNKNOWN

Do not turn every mentioned concept into a "skill."

---

# 20. Knowledge Aliases

Natural language may use multiple names for the same concept.

Optional:

`knowledge_aliases`

Example:

RAG

Aliases:

* retrieval augmented generation
* retrieval-augmented generation

This improves entity resolution.

---

# 21. Captures

Table:

`captures`

A capture represents the original user interaction.

Fields:

* `id`
* `user_id`
* `input_type`
* `raw_text`
* `transcript`
* `language`
* `captured_at`
* `processing_status`
* `model_provider`
* `model_name`
* `extraction_version`
* `created_at`

Input types:

* TEXT
* VOICE
* MANUAL
* IMPORT
* AUTOMATION
* INTEGRATION

The capture is the provenance root for events created from the interaction.

---

# 22. Capture Processing Status

Possible states:

* CAPTURED
* PROCESSING
* PROCESSED
* NEEDS_CLARIFICATION
* FAILED
* SYNC_PENDING

This allows reliable asynchronous processing.

---

# 23. Sources

Table:

`sources`

Purpose:

Track where information originated.

Fields:

* `id`
* `user_id`
* `source_type`
* `external_id`
* `metadata`
* `created_at`

Possible source types:

* USER_TEXT
* USER_VOICE
* MANUAL_INPUT
* IOS_AUTOMATION
* PC_AGENT
* CALENDAR
* FINANCIAL_IMPORT
* INTEGRATION
* AI_GENERATED
* OTHER

Every important event should have provenance.

---

# 24. Provenance Chain

The system should be able to trace:

**User input**

→ **Capture**

→ **AI extraction**

→ **Event**

→ **Metric**

→ **Insight**

Example:

User said:

> "I studied AI for 3 hours."

That should be traceable to:

Capture #123

→ Study Event #456

→ Weekly Study Metric

→ Weekly Insight

This makes AI behavior auditable.

---

# 25. AI Extraction Metadata

Do not hide AI-generated information inside normal user data.

Store:

* Model provider
* Model
* Extraction version
* Confidence
* Timestamp
* Original capture
* Validation status

If the extraction system changes later, you should be able to understand how an event was created.

---

# 26. Insights

Table:

`insights`

Fields:

* `id`
* `user_id`
* `title`
* `statement`
* `insight_type`
* `confidence`
* `period_start`
* `period_end`
* `created_at`
* `model_provider`
* `model_version`
* `status`

Possible statuses:

* ACTIVE
* DISMISSED
* ARCHIVED

Insights should reference their evidence.

---

# 27. Insight Evidence

Create:

`insight_evidence`

Fields:

* `insight_id`
* `event_id`
* `metric_id` if metrics are persisted
* `description`

An insight must be traceable to the information supporting it.

Example:

Insight:

> "Your study time decreased over the last two weeks."

Evidence:

* Week 1 study events
* Week 2 study events
* Previous baseline

---

# 28. Metrics

Metrics should generally be derived from events.

If a metric needs persistence, create:

`metrics`

Fields:

* `id`
* `user_id`
* `metric_type`
* `period_start`
* `period_end`
* `value`
* `unit`
* `calculation_version`
* `created_at`

Examples:

* Study hours/week
* Project hours/week
* Spending/week
* Exercise frequency
* Phone usage/day

Do not store duplicate metrics everywhere.

---

# 29. Experiments

Table:

`experiments`

Fields:

* `id`
* `user_id`
* `title`
* `hypothesis`
* `description`
* `start_date`
* `end_date`
* `status`
* `result`
* `created_at`
* `updated_at`

Possible statuses:

* PLANNED
* ACTIVE
* COMPLETED
* CANCELLED

Experiments allow the Personal OS to test behavioral changes.

---

# 30. Reviews

Table:

`reviews`

Fields:

* `id`
* `user_id`
* `review_type`
* `period_start`
* `period_end`
* `summary`
* `created_at`
* `model_version`

Types:

* DAILY
* WEEKLY
* MONTHLY
* CUSTOM

Reviews should be generated from underlying events and metrics rather than treated as the primary source of truth.

---

# 31. Memories

Table:

`memories`

Fields:

* `id`
* `user_id`
* `memory_type`
* `content`
* `importance`
* `confidence`
* `source_event_id`
* `created_at`
* `updated_at`
* `expires_at`
* `status`

Possible statuses:

* ACTIVE
* ARCHIVED
* DELETED

Memory should be separate from events.

---

# 32. Memory Principles

A memory should have:

* Reason for retention
* Evidence
* Confidence
* Editable content
* Deletion capability
* Optional expiration

Do not let the AI silently accumulate unlimited permanent memories.

---

# 33. Corrections

When a user corrects an event:

Example:

> "That was 4 hours, not 3."

Update the existing event.

Do not create:

Event A = 3h

Event B = 4h

unless the user explicitly means there were two different sessions.

Maintain audit information where necessary.

---

# 34. Soft Deletion

Important user data should generally support soft deletion.

Use:

`deleted_at`

rather than immediately destroying the record.

This supports:

* Undo
* Auditing
* Recovery
* Debugging

Permanent deletion should still be possible when the user explicitly requests it.

---

# 35. Duplicate Prevention

Events should have mechanisms for duplicate detection.

Potential duplicate signals:

* Same user
* Same event type
* Similar title
* Similar time
* Same project
* Same source
* Similar duration

Do not rely solely on exact string matching.

However, duplicate detection should never silently merge events when confidence is low.

---

# 36. Database Constraints

Use database constraints for important integrity rules.

Examples:

* Foreign keys
* NOT NULL where appropriate
* Unique constraints for aliases
* Valid status values
* Valid event types
* User ownership constraints

Business logic should remain in the application layer.

---

# 37. Indexing

Index fields frequently used for retrieval.

Important indexes:

`events.user_id`

`events.occurred_at`

`events.event_type`

`events.project_id` where applicable

`events.source_id`

`events.capture_id`

`projects.user_id`

`goals.user_id`

`tasks.user_id`

`knowledge.user_id`

For timeline queries, an index such as:

`(user_id, occurred_at DESC)`

should be highly important.

---

# 38. Full-Text / Semantic Search

V1 can begin with PostgreSQL full-text search.

Search across:

* Event titles
* Event descriptions
* Knowledge
* Projects
* Tasks
* Memories

Semantic/vector search can be added later.

Do not introduce vector infrastructure just because the application uses AI.

Use it when it provides clear value.

---

# 39. API Layer

The iPhone app should communicate with the backend through APIs.

Example:

`POST /captures`

Creates a new capture.

`GET /timeline`

Retrieves events.

`GET /events/{id}`

Retrieves one event.

`PATCH /events/{id}`

Updates an event.

`DELETE /events/{id}`

Deletes an event.

`GET /insights`

Retrieves insights.

`GET /goals`

Retrieves goals.

`GET /projects`

Retrieves projects.

`GET /knowledge`

Retrieves knowledge.

`GET /reviews`

Retrieves reviews.

The API should expose user-level concepts, not raw database implementation details.

---

# 40. Capture API

Example:

`POST /captures`

Input:

```json
{
  "input_type": "TEXT",
  "content": "I studied AI for two hours and worked on TenderPilot for three."
}
```

Backend:

1. Create capture.
2. Process input.
3. Extract events.
4. Validate.
5. Resolve entities.
6. Detect duplicates.
7. Persist.
8. Return created/updated entities.

---

# 41. Authentication

Every request must be associated with an authenticated user.

Never trust `user_id` supplied by the mobile client as the authority for ownership.

The backend should derive the authenticated user from the authentication context.

Every database query should enforce user ownership.

---

# 42. Privacy Boundary

The backend should ensure:

**User A cannot access User B's events.**

This must be enforced at the application/database level.

Do not rely only on frontend filtering.

Every resource query must be scoped to the authenticated user.

---

# 43. API Response Design

Responses should be optimized for the mobile application.

Example capture response:

```json
{
  "capture_id": "...",
  "status": "PROCESSED",
  "events_created": [
    {
      "id": "...",
      "type": "STUDY",
      "title": "AI study",
      "duration_seconds": 7200
    }
  ],
  "events_updated": [],
  "clarifications_needed": []
}
```

Do not expose internal AI reasoning or hidden chain-of-thought.

Return structured results and concise explanations.

---

# 44. Transaction Strategy

When multiple events are generated from one capture, persistence should be handled transactionally where appropriate.

Example:

One capture creates:

* Study event
* Project event
* Expense event

The system should avoid leaving half the capture persisted if a critical database operation fails.

Use transactions for atomic operations.

Long-running AI processing can happen asynchronously before persistence.

---

# 45. Asynchronous Processing

Some operations should not block the user's interaction.

Potential asynchronous jobs:

* Long voice transcription
* Insight generation
* Weekly reviews
* Embedding generation
* Pattern analysis
* Large imports
* External synchronization

Basic capture should remain as fast as possible.

---

# 46. Event Sourcing vs Normal CRUD

Do not over-engineer the first version into a full event-sourcing architecture.

The application can use normal relational CRUD while preserving:

* Source
* Provenance
* Corrections
* Audit metadata

The word "event" in the Personal OS model does not require technical event sourcing.

---

# 47. Versioning

Version important AI-derived structures.

For example:

`extraction_version = 1.2`

If the extraction system changes, you should know which version generated each event.

This enables future reprocessing.

---

# 48. Reprocessing

The system should eventually support:

**Original capture**

→ **New extraction model**

→ **Compare**

→ **Optional update**

Never overwrite the original input.

This allows improvements to the AI without losing history.

---

# 49. V1 Relationship Graph

The essential relationships are:

**User**

→ Areas

→ Goals

→ Systems

→ Projects

→ Habits

→ Tasks

→ Events

→ Knowledge

→ Insights

→ Experiments

→ Reviews

→ Memories

Events sit at the center because they provide evidence of what actually happened.

---

# 50. Simplified V1 Database

If implementation speed is the priority, start with:

### Required

* users
* areas
* projects
* goals
* tasks
* events
* knowledge
* captures
* sources

### Add shortly after

* habits
* systems
* insights
* memories

### Later

* experiments
* reviews
* metrics
* integrations
* device data
* financial imports

Do not block the MVP on every advanced entity.

---

# 51. Database Philosophy

The database should answer questions such as:

> What did I do today?

> How much did I study this month?

> What projects am I spending time on?

> What have I learned?

> How much did I spend?

> Which habits am I actually performing?

> What changed compared with last month?

> Which goals are receiving real effort?

> What patterns repeatedly appear?

> What evidence supports this insight?

If the database cannot answer these questions cleanly, the architecture needs improvement.

---

# 52. Final V1 Architecture

The backend should conceptually be:

**iPhone**

↓

**Authentication**

↓

**API**

↓

**Capture Service**

↓

**AI Extraction Service**

↓

**Validation / Entity Resolution**

↓

**Change Planner**

↓

**Persistence Service**

↓

**PostgreSQL**

↓

**Analytics**

↓

**Insights**

↓

**API**

↓

**iPhone**

The database remains the structured source of truth.

The AI interprets.

The application validates.

The database stores.

The analytics layer calculates.

The UI presents.

---

# 53. Final Rule

Do not build a database that mirrors the screens.

Build a structured representation of the user's life.

Then build:

* Timeline
* Home
* Finance
* Goals
* Projects
* Knowledge
* Habits
* Insights
* Reviews

as different views over that same underlying system.

The core architectural principle is:

> **One coherent personal data model. Many intelligent views.**
