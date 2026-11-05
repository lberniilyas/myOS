# Personal OS — #8 Backend, API & Service Architecture

## 1. Purpose

Design the backend architecture for the Personal OS.

The backend must provide a reliable foundation for:

* iPhone capture
* Text and voice processing
* AI extraction
* Event persistence
* Entity resolution
* Timeline queries
* Goals
* Projects
* Knowledge
* Habits
* Finance
* Device usage
* Insights
* Reviews
* AI memory
* Future integrations
* Background processing

The architecture should be powerful internally but simple externally.

The core principle is:

> **The frontend should never need to understand the complexity of the Personal OS backend.**

---

# 2. Recommended Technology Stack

Use a pragmatic V1 stack.

### Mobile

**iOS / SwiftUI**

### Backend

**Python**

**FastAPI**

### Database

**PostgreSQL**

### ORM

**SQLAlchemy**

### Migrations

**Alembic**

### Background jobs

Start simple with a task queue such as:

**Celery / Redis**

or another reliable job system.

Do not introduce distributed infrastructure unless required.

### AI

Use an abstraction layer that can support multiple model providers.

### Storage

Object storage for:

* Voice recordings
* Large attachments
* Imported documents

Do not store large binary files directly in PostgreSQL.

---

# 3. High-Level Architecture

The system should follow:

**iPhone**

↓

**API Gateway / FastAPI**

↓

**Authentication**

↓

**Application Services**

↓

**Domain Logic**

↓

**PostgreSQL**

External AI providers and integrations communicate through backend services.

Background processing runs separately when operations are slow.

Conceptually:

```text
                    ┌─────────────────────┐
                    │      iPhone App     │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │      FastAPI API    │
                    └──────────┬──────────┘
                               │
             ┌─────────────────┼─────────────────┐
             ▼                 ▼                 ▼
      Capture Service    Query Service     Account Service
             │                 │
             ▼                 ▼
       AI Services        PostgreSQL
             │
             ▼
       Background Jobs
```

Keep the architecture modular without prematurely splitting everything into microservices.

---

# 4. Start as a Modular Monolith

V1 should be a **modular monolith**, not a microservice ecosystem.

Use one backend application with clear internal modules.

Recommended modules:

```text
app/
├── api/
├── auth/
├── captures/
├── events/
├── projects/
├── goals/
├── tasks/
├── habits/
├── knowledge/
├── insights/
├── memories/
├── analytics/
├── ai/
├── integrations/
├── notifications/
├── jobs/
└── database/
```

Each module should have clear responsibilities.

---

# 5. Why Modular Monolith

A Personal OS V1 does not need:

* 15 deployed services
* Kubernetes
* service meshes
* complex message brokers
* distributed transactions

Those would add complexity before the product has proven its core interaction.

The backend should be easy to:

* Develop
* Debug
* Deploy
* Test
* Change

Split services only when there is a real technical reason.

---

# 6. API Responsibilities

The API should:

* Authenticate requests
* Validate input
* Authorize access
* Call application services
* Return structured responses
* Handle errors
* Never expose database internals unnecessarily

The API should not contain all business logic directly inside route handlers.

Bad:

```text
POST /captures
→ 500 lines of extraction/database logic
```

Better:

```text
POST /captures
→ CaptureService
→ AIExtractionService
→ Validation
→ ChangePlanner
→ Persistence
```

---

# 7. Layered Architecture

Use clear layers.

### API Layer

HTTP routes and request/response schemas.

### Application Layer

Use cases.

Examples:

* Create capture
* Process capture
* Correct event
* Create project
* Query timeline
* Generate review

### Domain Layer

Business rules.

Examples:

* Event validation
* Goal relationships
* Habit interpretation
* Duplicate detection

### Infrastructure Layer

External systems.

Examples:

* PostgreSQL
* AI providers
* Speech-to-text
* Object storage
* Notifications

This keeps the core system independent from specific providers.

---

# 8. Capture Service

The Capture Service is one of the most important backend components.

Responsibilities:

* Receive text
* Receive voice
* Store raw capture
* Create capture ID
* Process transcription
* Build context
* Invoke extraction
* Validate extraction
* Resolve entities
* Detect duplicates
* Create change plan
* Persist results
* Return status

It should orchestrate the capture lifecycle.

---

# 9. Capture Lifecycle

A capture should follow:

```text
RECEIVED
   ↓
STORED
   ↓
PROCESSING
   ↓
TRANSCRIBED (voice)
   ↓
UNDERSTOOD
   ↓
EXTRACTED
   ↓
VALIDATED
   ↓
RESOLVED
   ↓
DEDUPLICATED
   ↓
PERSISTED
   ↓
COMPLETED
```

If clarification is required:

```text
→ NEEDS_CLARIFICATION
```

If something fails:

```text
→ FAILED
```

The original capture must remain available.

---

# 10. Capture API

Recommended endpoint:

`POST /v1/captures`

Support:

* Text
* Voice
* Future attachment inputs

Example:

```json
{
  "input_type": "text",
  "content": "I studied AI for two hours today."
}
```

Response can immediately return:

```json
{
  "capture_id": "...",
  "status": "processing"
}
```

The client can then receive the result through:

* polling
* WebSocket
* Server-Sent Events
* push notification

Choose the simplest reliable approach for V1.

---

# 11. Voice API

Recommended flow:

`POST /v1/captures/voice`

The backend should:

1. Receive audio.
2. Store it temporarily.
3. Create capture.
4. Transcribe.
5. Preserve transcript.
6. Process transcript through the normal extraction pipeline.
7. Store events.
8. Return result.

Voice should eventually reuse the same capture pipeline as text.

---

# 12. Do Not Create Separate AI Logic for Voice

Voice and text should converge as early as possible.

Correct:

```text
Voice
 ↓
STT
 ↓
Text
 ↓
Normal Capture Pipeline
```

Not:

```text
Voice → completely separate AI architecture
Text → completely separate AI architecture
```

This prevents duplicated logic.

---

# 13. AI Provider Abstraction

Create a provider interface.

Conceptually:

```text
AIProvider
├── generate_structured_output()
├── generate_text()
└── embed()
```

Possible implementations:

```text
OpenAIProvider
AnthropicProvider
GoogleProvider
LocalModelProvider
```

The rest of the application should not care which provider is being used.

---

# 14. Speech-to-Text Abstraction

Similarly:

```text
SpeechToTextProvider
```

Possible implementations:

* Apple/local transcription
* Cloud provider
* Other STT service

The Capture Service should simply call:

```text
transcribe(audio)
```

and receive a transcript.

---

# 15. AI Extraction Service

Responsibilities:

* Understand user input
* Extract structured information
* Detect ambiguity
* Suggest entities
* Suggest relationships
* Identify corrections
* Return structured output

It should NOT:

* Directly modify the database
* Decide authorization
* Execute arbitrary SQL
* Delete user data
* Perform financial calculations
* Invent missing information

---

# 16. Change Planner

The Change Planner converts AI output into safe application operations.

Example:

AI says:

```text
Create:
Study event
Duration: 2 hours
Topic: AI
```

The Change Planner determines:

```text
CREATE event
LINK event → user
LINK event → AI knowledge
LINK event → relevant project
```

The planner should produce explicit changes before persistence.

---

# 17. Persistence Service

Only the Persistence Service should perform the final database mutations for important AI-generated changes.

Responsibilities:

* Create
* Update
* Delete
* Relationship management
* Transactions
* Ownership validation
* Audit information

This creates a safety boundary between AI output and the database.

---

# 18. Query Service

Create a dedicated query/application layer for reading data.

Examples:

* Timeline
* Daily summary
* Project history
* Goal evidence
* Spending
* Study time
* Habit history

Queries should be deterministic.

Do not ask an LLM to reconstruct structured information that PostgreSQL can provide directly.

---

# 19. Timeline API

Example:

`GET /v1/timeline`

Parameters:

* `start`
* `end`
* `event_type`
* `area_id`
* `project_id`
* `limit`
* `cursor`

Response:

```json
{
  "items": [],
  "next_cursor": "..."
}
```

Use cursor-based pagination rather than relying only on page numbers for large timelines.

---

# 20. Event API

Recommended endpoints:

`GET /v1/events/{id}`

`PATCH /v1/events/{id}`

`DELETE /v1/events/{id}`

`POST /v1/events/{id}/correct`

The correction endpoint can allow natural-language correction:

> "Actually this happened yesterday."

The correction can go through the same interpretation architecture.

---

# 21. Project API

Examples:

`GET /v1/projects`

`POST /v1/projects`

`GET /v1/projects/{id}`

`PATCH /v1/projects/{id}`

`DELETE /v1/projects/{id}`

Projects should expose:

* Recent events
* Tasks
* Goals
* Knowledge
* Time invested
* Milestones

These should be assembled by queries rather than duplicated into project records.

---

# 22. Goal API

Examples:

`GET /v1/goals`

`POST /v1/goals`

`GET /v1/goals/{id}`

`PATCH /v1/goals/{id}`

A goal response should be able to include evidence:

* Related events
* Projects
* Tasks
* Systems
* Metrics

Avoid fake progress percentages unless they are explicitly defined by the user.

---

# 23. AI Conversation API

Use a separate endpoint for reflective conversation.

Example:

`POST /v1/assistant`

Input:

```json
{
  "message": "Why have I been studying less this month?"
}
```

The backend should:

1. Classify the request.
2. Retrieve relevant data.
3. Calculate required metrics.
4. Build evidence.
5. Give evidence to the AI.
6. Generate an explanation.
7. Return the response.

The LLM should not independently browse the entire database.

---

# 24. Assistant Tools

The Personal OS AI can use controlled backend tools.

Examples:

```text
get_events()
get_project()
get_goal()
get_metrics()
get_habits()
get_spending()
search_knowledge()
get_recent_activity()
```

Tool access should be explicit.

Do not expose unrestricted database access.

---

# 25. Tool-Calling Architecture

Conceptually:

```text
User
 ↓
Personal OS Assistant
 ↓
Intent
 ↓
Allowed Tool
 ↓
Structured Data
 ↓
Analysis
 ↓
Response
```

Example:

User:

> "How much did I spend this week?"

Assistant:

→ `get_spending(start, end)`

Backend returns:

`42`

Assistant:

> "You've spent 42 this week."

---

# 26. AI Must Not Guess User Data

If the database does not contain enough information:

Say so.

Example:

> "I don't have reliable phone-usage data for those days."

Do not fabricate an estimate.

---

# 27. Analytics Service

The Analytics Service should calculate:

* Totals
* Averages
* Trends
* Comparisons
* Frequencies
* Baselines
* Goal evidence
* Habit patterns

Example:

```text
study_hours_this_week()
study_hours_previous_week()
study_hours_4_week_average()
```

The AI can then interpret those results.

---

# 28. Personal Baseline Engine

The system should gradually establish baselines.

Examples:

* Typical study time
* Typical project time
* Typical phone usage
* Typical spending
* Typical exercise frequency
* Typical sleep pattern

Do not establish baselines from insufficient data.

For example:

> "Your usual study time is 3.2 hours."

should only appear when enough historical data exists.

---

# 29. Insight Engine

The Insight Engine should run separately from capture.

Capture:

> "I studied for 3 hours."

Insight engine:

> "Your study time has been increasing."

These are different responsibilities.

Possible triggers:

* Scheduled daily analysis
* Weekly analysis
* User requests
* Significant changes
* Experiment completion

Do not generate expensive AI analysis after every tiny event.

---

# 30. Background Job Architecture

Use background jobs for:

* Voice transcription
* AI extraction when appropriate
* Embedding generation
* Insight generation
* Daily reviews
* Weekly reviews
* Large imports
* Integration synchronization

Example:

```text
Capture
 ↓
Queue
 ↓
Worker
 ↓
Process
 ↓
Database
 ↓
Notify client
```

---

# 31. Idempotency

Important operations should be idempotent.

If the same request is accidentally sent twice, the backend should not create duplicate events.

Use:

* Capture IDs
* Request IDs
* Idempotency keys
* Source IDs

This is especially important for mobile networks.

---

# 32. Mobile Network Reliability

Assume the phone may:

* Lose connection
* Retry requests
* Background the application
* Upload slowly
* Send duplicate requests

The backend must handle these cases safely.

Never assume:

> One request = exactly one successful processing.

---

# 33. Offline Capture

Eventually support:

```text
iPhone
 ↓
Local capture queue
 ↓
Internet available
 ↓
Sync API
 ↓
Backend
```

The user should be able to capture information even when temporarily offline.

V1 can begin with basic retry support if full offline mode is too large.

---

# 34. Local iPhone Storage

Use local storage for:

* Pending captures
* Recent timeline cache
* User preferences
* Temporary state
* Drafts

Do not treat the local device database as the ultimate source of truth.

The backend remains the canonical synchronized source.

---

# 35. Sync Architecture

Each local object should have:

* Local ID
* Server ID
* Updated timestamp
* Sync status

Potential states:

* LOCAL_ONLY
* SYNCING
* SYNCED
* CONFLICT
* FAILED

Conflict resolution should be explicit.

Do not blindly overwrite newer information.

---

# 36. Authentication

Use secure authentication suitable for mobile.

Support:

* Secure token/session management
* Refresh tokens
* Secure device storage
* Logout
* Session revocation

Never store sensitive authentication credentials in ordinary application storage.

---

# 37. Authorization

Every backend operation must verify:

**Who is the user?**

**Does the user own this resource?**

**Is the user allowed to modify it?**

For example:

User A must never be able to access:

`/events/{User B event ID}`

Even if User A somehow knows the ID.

---

# 38. Security Boundaries

Important boundaries:

### Client

Untrusted.

### API

Authenticated and validated.

### AI

Untrusted interpreter.

### Application layer

Business-rule authority.

### Database

Source of truth.

Never allow:

**LLM → direct database mutation**

---

# 39. Secrets

API keys must never be embedded in:

* iOS application code
* Frontend JavaScript
* Database records exposed to clients
* Git repositories

Keep provider credentials on the backend.

Use environment variables or a secure secrets manager.

---

# 40. Logging

Log enough to debug the system without logging unnecessary sensitive information.

Useful metadata:

* Request ID
* User ID
* Capture ID
* Processing stage
* Duration
* Model/provider
* Error type
* Status

Avoid logging full private journal content by default.

---

# 41. Observability

Track:

* API latency
* AI latency
* STT latency
* Processing failures
* Queue delays
* Database errors
* Extraction failures
* Duplicate detection
* Clarification rate
* User correction rate

Important product metric:

> **How often does the system correctly understand the user's natural input?**

---

# 42. AI Evaluation

Maintain a test dataset of realistic user inputs.

Examples:

* Simple study entry
* Multiple events
* Darija
* French
* Mixed language
* Approximate time
* Correction
* Ambiguous project
* Expense
* Habit
* Long journal
* Voice transcript

Evaluate:

* Extraction accuracy
* Time accuracy
* Entity resolution
* Duplicate detection
* Relationship accuracy
* Clarification quality
* False assumptions

Do not rely on subjective testing alone.

---

# 43. API Versioning

Use:

`/v1/...`

from the beginning.

This makes future API changes safer.

Avoid breaking the mobile app whenever backend architecture evolves.

---

# 44. Error Model

Use consistent API errors.

Example:

```json
{
  "error": {
    "code": "CAPTURE_PROCESSING_FAILED",
    "message": "The capture could not be processed."
  }
}
```

Do not expose:

* Stack traces
* Database errors
* Provider secrets
* Internal architecture details

to the client.

---

# 45. Rate Limiting

Protect expensive endpoints.

Especially:

* AI requests
* Voice processing
* Assistant queries
* Large searches
* Imports

Normal timeline reads can have different limits.

Rate limiting should protect both infrastructure and AI costs.

---

# 46. Cost Control

AI should not be invoked unnecessarily.

Use:

### Deterministic code for:

* Arithmetic
* Aggregation
* Date calculations
* Filtering
* Sorting
* Simple categorization
* Validation

Use:

### AI for:

* Natural-language understanding
* Semantic extraction
* Ambiguity
* Entity resolution
* Conversation
* Reflection
* Insight explanation

This dramatically reduces cost and increases reliability.

---

# 47. Caching

Cache appropriate expensive operations.

Examples:

* Repeated analytics queries
* Recent summaries
* Stable project information
* Knowledge search
* Generated weekly reviews

Do not cache data in a way that can cause stale critical information.

Financial and recent event data should prioritize correctness.

---

# 48. Deployment

V1 deployment can be simple:

```text
iPhone
   ↓
HTTPS
   ↓
FastAPI
   ↓
PostgreSQL
   ↓
Background Worker
   ↓
AI / External APIs
```

Use HTTPS everywhere.

Database should not be publicly accessible.

Workers should communicate through secure internal infrastructure.

---

# 49. Environment Separation

Maintain:

* Development
* Staging
* Production

Do not experiment directly on production data.

Use separate:

* Databases
* API credentials
* AI keys
* Storage buckets
* Logging environments

---

# 50. Testing Strategy

Use several layers.

### Unit tests

Test:

* Business rules
* Time interpretation helpers
* Financial calculations
* Validation
* Duplicate logic

### Integration tests

Test:

* API → database
* Capture → persistence
* Authentication
* Relationships

### AI evaluation tests

Test:

* Extraction
* Entity resolution
* Corrections
* Ambiguity

### End-to-end tests

Simulate:

**iPhone capture → backend → AI → database → response**

---

# 51. V1 Backend Priority

Build in this order:

### Phase 1

* Authentication
* PostgreSQL
* User
* Events
* Captures
* Projects
* Goals
* Knowledge
* Tasks

### Phase 2

* Capture API
* AI extraction
* Validation
* Entity resolution
* Persistence

### Phase 3

* Timeline API
* Event editing
* Search
* Home summary

### Phase 4

* Voice
* Background jobs
* Clarification flow

### Phase 5

* Analytics
* Insights
* Reviews

### Phase 6

* Integrations
* Device data
* Advanced automation

---

# 52. First End-to-End Milestone

Before building advanced features, the backend must successfully handle:

```text
iPhone
 ↓
POST /v1/captures
 ↓
Capture created
 ↓
AI extraction
 ↓
Validation
 ↓
Project resolution
 ↓
Event creation
 ↓
PostgreSQL
 ↓
Timeline updated
 ↓
Response returned
```

Example:

User:

> "I studied AI for two hours and worked on TenderPilot for three."

Database should contain:

**Study event**

2h

**Project work event**

3h

Project:

TenderPilot

Both connected to:

**One capture**

---

# 53. Architecture Rule

The backend should make it easy to add new data sources later.

Future sources could include:

* iOS device data
* macOS/Windows PC agent
* Calendar
* Browser
* Financial accounts
* Wearables
* Email
* Files
* Location-derived context where explicitly permitted
* External productivity tools

Each should feed into the same underlying model.

For example:

**PC agent**

→ Source

→ Event

→ Timeline

→ Analytics

not:

**PC agent**

→ completely separate PC database.

---

# 54. Final Architecture

The complete V1 architecture should be:

```text
                         ┌─────────────────────┐
                         │      iPhone         │
                         │   SwiftUI Client    │
                         └──────────┬──────────┘
                                    │
                                  HTTPS
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │      FastAPI        │
                         │     API Layer       │
                         └──────────┬──────────┘
                                    │
                    ┌───────────────┼────────────────┐
                    ▼               ▼                ▼
              Capture Service  Query Service   Auth Service
                    │               │
                    ▼               ▼
              AI Services      Application Logic
                    │               │
                    └───────┬───────┘
                            ▼
                     Persistence Layer
                            │
                            ▼
                     ┌──────────────┐
                     │ PostgreSQL   │
                     └──────┬───────┘
                            │
              ┌─────────────┼──────────────┐
              ▼             ▼              ▼
          Analytics      Insights       Memory
              │             │              │
              └─────────────┼──────────────┘
                            ▼
                     Background Jobs
                            │
                 ┌──────────┼──────────┐
                 ▼          ▼          ▼
                STT         AI     Integrations
```

---

# 55. Final Architectural Principle

The Personal OS should be built as:

**One backend**

**One coherent data model**

**One source of truth**

**Many input sources**

**Many intelligent views**

**Controlled AI**

**Evidence-based analytics**

**User-owned data**

The architecture should remain simple until complexity is justified.

The most important backend capability is not "AI."

It is:

> **Reliably turning messy real-world information about the user's life into structured, trustworthy, connected data.**

Everything else — dashboards, insights, reviews, predictions, experiments, and automation — is built on top of that foundation.
