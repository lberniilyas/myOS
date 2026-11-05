# Personal OS — #10 Testing, Evaluation & Reliability Architecture

## 1. Purpose

Define the testing and evaluation architecture for the Personal OS.

The system depends heavily on AI, natural language, voice transcription, entity resolution, and automated interpretation.

Traditional unit tests alone are not enough.

The system must be tested at multiple levels:

* Deterministic backend logic
* Database integrity
* API behavior
* AI extraction
* Entity resolution
* Duplicate detection
* Change planning
* Persistence
* Voice transcription
* Natural-language queries
* Analytics
* Insights
* End-to-end user flows

The central principle is:

> **AI behavior must be measurable, reproducible, observable, and continuously evaluated.**

---

# 2. Reliability Hierarchy

Not every part of the system requires the same level of certainty.

Use this hierarchy:

### Highest reliability

* Financial amounts
* Event timestamps
* Event identity
* Database writes
* User corrections
* Deletions
* Authentication
* Permissions

### High reliability

* Event type
* Project resolution
* Duration
* Relationships
* Habit detection
* Task extraction

### Moderate reliability

* Knowledge interpretation
* Context classification
* Semantic grouping

### Carefully qualified

* Insights
* Behavioral patterns
* Recommendations
* Possible causes

The system must become more conservative as it moves from facts toward interpretation.

---

# 3. Testing Layers

Implement multiple testing layers.

## Layer 1 — Unit Tests

Test deterministic functions independently.

Examples:

* Time parsing
* Duration calculation
* Currency parsing
* Event validation
* Event type mapping
* Date resolution
* Duplicate detection
* Metric calculations
* Permission checks

These tests should not require an LLM.

---

# 4. Layer 2 — Database Tests

Test:

* Constraints
* Foreign keys
* Unique indexes
* Soft deletion
* Relationships
* Cascades
* Transactions
* Concurrent updates
* Data isolation between users

Critical rule:

> One user's data must never be accessible through another user's queries.

---

# 5. Layer 3 — API Tests

Test every important endpoint.

Examples:

```text
POST /v1/captures
GET /v1/events
GET /v1/events/{id}
PATCH /v1/events/{id}
DELETE /v1/events/{id}
GET /v1/timeline
GET /v1/projects
POST /v1/projects
GET /v1/goals
GET /v1/knowledge
POST /v1/assistant/query
```

Verify:

* Authentication
* Validation
* Correct response structure
* Error handling
* Authorization
* Idempotency
* Database changes

---

# 6. Layer 4 — AI Extraction Tests

AI extraction requires a dedicated evaluation dataset.

Each test case should contain:

```text
input
expected_events
expected_fields
expected_relationships
expected_uncertainties
```

Example:

Input:

> "I studied machine learning for about two hours and worked on TenderPilot for another hour."

Expected:

### Event 1

Type:

STUDY

Duration:

approximately 2 hours

Topic:

Machine Learning

### Event 2

Type:

PROJECT_WORK

Duration:

approximately 1 hour

Project:

TenderPilot

The system should not invent exact start/end times.

---

# 7. Golden Dataset

Create a versioned collection of representative inputs.

Categories:

### Simple

> "I studied AI for 2 hours."

### Multiple events

> "I studied AI for 2h, worked on my project for 3h, and spent 20 on food."

### Approximate

> "I studied for around two hours."

### Date reference

> "Yesterday I worked on TenderPilot."

### Correction

> "Actually, that was 3 hours."

### Ambiguous

> "Worked on the app."

### Project alias

> "Spent the afternoon on the tender project."

### Knowledge

> "I finally understood how vector databases work."

### Habit

> "I went running this morning."

### Finance

> "Spent 35 at the restaurant."

### Mixed language

> "Lyouma qrit AI pendant deux heures."

### Long journal

Several paragraphs describing the day.

### Voice transcript

Natural speech with filler words and imperfect grammar.

---

# 8. Expected Output Evaluation

Do not evaluate only whether the LLM returned valid JSON.

Evaluate semantic correctness.

For every extracted event compare:

* Event type
* Title
* Duration
* Date
* Time precision
* Project
* Goal
* Knowledge
* Task
* Finance fields
* Habit
* Source
* Confidence

---

# 9. Important AI Metrics

Track:

### Extraction precision

How often extracted information is correct.

### Extraction recall

How much relevant information was successfully extracted.

### Field accuracy

Accuracy of individual fields.

### Relationship accuracy

Correct connections to projects, goals, habits, etc.

### False extraction rate

How often the model invents information.

### Clarification rate

How often the system asks the user for clarification.

### Unnecessary clarification rate

How often clarification was avoidable.

### Correction rate

How often users correct generated records.

---

# 10. Never Invent Data

Create explicit tests for hallucination.

Input:

> "I studied AI yesterday."

Expected:

* Study event
* Date = yesterday

Must NOT create:

* Exact duration
* Exact start time
* Exact end time
* Location
* Specific AI topic

unless the input contains those facts.

This should be a hard evaluation rule.

---

# 11. Uncertainty Tests

Input:

> "I studied for around two hours."

The system should preserve:

**duration ≈ 2h**

not:

**duration = 2h 00m**

Similarly:

> "I spent roughly 30."

should not become falsely precise about the amount or category if the context does not establish them.

---

# 12. Time Evaluation

Time is especially important.

Test:

* Today
* Yesterday
* Last night
* This morning
* Monday
* Last Monday
* Two days ago
* Earlier today
* Around 5
* For two hours
* From 3 to 5
* Before lunch
* After my class

The system should resolve relative times using:

* User timezone
* Capture timestamp
* Conversation context
* User locale

Do not depend exclusively on the LLM to calculate dates.

---

# 13. Entity Resolution Evaluation

Test aliases.

If the user has:

**Project**

TenderPilot

Aliases:

* tender app
* tender project
* procurement app
* TenderPilot

Then:

> "Worked on the procurement app."

should resolve to TenderPilot when context supports it.

If two projects could match equally well, the system should ask.

---

# 14. Duplicate Detection Tests

Input:

> "I studied AI for 2 hours."

Then:

> "Actually I studied AI for two hours this afternoon."

The system should detect whether this is:

* A correction
* A duplicate
* A separate event

It should not automatically create two identical study sessions.

---

# 15. Correction Tests

Test natural corrections:

> "Change that to 3 hours."

> "That was yesterday."

> "It wasn't TenderPilot."

> "The 30 was for transportation."

> "Delete that expense."

The system should identify the target event using conversation context.

If multiple events could match:

Ask for clarification.

---

# 16. Change Plan Testing

AI should never directly modify the database.

Test the pipeline:

```text
Input
↓
AI interpretation
↓
Proposed changes
↓
Validation
↓
Application rules
↓
Persistence
```

Test that invalid changes are rejected.

Example:

AI proposes:

```text
duration_seconds = -500
```

The application must reject it.

---

# 17. Transaction Testing

When one input produces multiple events, persistence should be handled safely.

Example:

> "Studied AI, worked on TenderPilot, and spent 30 on food."

If persistence fails halfway through, the system must not leave the database in an inconsistent state.

Use transactions where appropriate.

---

# 18. Idempotency Testing

Mobile networks can fail.

A request may be sent twice.

Test:

```text
same capture_id
same request
same payload
```

The system should not create duplicate events.

Every capture should have a stable identifier.

---

# 19. Offline Testing

The iPhone may lose connectivity.

Test:

1. User records input offline.
2. App stores it locally.
3. Connection returns.
4. Capture synchronizes.
5. Backend processes it.
6. Duplicate submission is prevented.

The user should not lose captured information.

---

# 20. Voice Testing

Voice introduces additional uncertainty.

Test:

* Background noise
* Fast speech
* Long pauses
* Filler words
* Mixed languages
* Darija
* French
* English
* Code/project names
* Numbers
* Dates
* Currency amounts

Example:

> "Lyouma qrit AI pendant deux heures."

The system should preserve meaning even if transcription is imperfect.

---

# 21. Speech-to-Text Evaluation

Keep transcription separate from extraction evaluation.

Measure:

**Audio → Transcript accuracy**

and separately:

**Transcript → Structured data accuracy**

This helps identify where failures originate.

If the transcript is wrong, the extraction model should not be blamed for every failure.

---

# 22. Multilingual Evaluation

Create evaluation datasets for:

* English
* French
* Arabic
* Darija
* Mixed Darija/French
* Mixed Darija/English
* Mixed French/English

Do not assume that a model performing well in English will perform equally well in Darija.

---

# 23. Assistant Evaluation

The Personal OS assistant must be evaluated differently from extraction.

Questions:

> "How many hours did I study this week?"

Expected:

A database-derived number.

Questions:

> "What did I work on yesterday?"

Expected:

A list based on stored events.

Questions:

> "Did I spend more this week than last week?"

Expected:

A calculation.

Questions:

> "Why was I less productive?"

Expected:

Evidence plus qualified interpretation.

---

# 24. Assistant Anti-Hallucination Rule

The assistant must never invent personal history.

If data does not exist:

> "I don't have enough recorded data to answer that."

Not:

> "You probably..."

unless clearly labeled as a hypothesis and grounded in available evidence.

---

# 25. Analytics Testing

Analytics should be deterministic.

Example:

If events are:

* Monday: 2h
* Tuesday: 3h
* Wednesday: 1h

Then weekly study time must equal:

**6h**

The LLM should never be responsible for calculating this.

---

# 26. Insight Evaluation

Insights require stricter controls.

Every insight should have:

* Statement
* Time range
* Supporting events
* Supporting metrics
* Comparison baseline
* Confidence
* Interpretation type

Interpretation types:

* Observation
* Association
* Hypothesis
* Causation only when genuinely supported

The default should be observation or association.

---

# 27. Insight Example

Bad:

> "You use your phone at night, therefore you are less productive."

Better:

> "During the last three weeks, higher late-night phone usage coincided with lower morning study time."

Then:

> "This is an association, not proof that phone usage caused the decrease."

---

# 28. Regression Testing

Every important AI bug should become a permanent test case.

Example:

Bug:

> "I studied around 2 hours" became exactly 2h.

Add that input to the regression dataset.

Future model changes must continue to pass it.

The evaluation dataset should grow over time.

---

# 29. Model Versioning

Store:

* Model provider
* Model name
* Model version where available
* Extraction schema version
* Prompt version
* Application version
* Processing timestamp

This allows investigation when behavior changes.

---

# 30. Prompt Versioning

Treat prompts as code.

Store prompts in version-controlled files.

Example:

```text
prompts/
    extraction/
        v1/
        v2/
    assistant/
        v1/
    insights/
        v1/
```

Do not hide important production prompts inside random application files.

---

# 31. Structured Output Schemas

Use strict schemas for AI outputs.

For example:

```text
ExtractionResult
├── events[]
├── knowledge[]
├── tasks[]
├── corrections[]
└── clarifications[]
```

Every object must pass schema validation before reaching the application layer.

---

# 32. Observability

Every capture should be traceable.

Store or log appropriate metadata:

```text
capture_id
user_id
input_type
processing_started
processing_finished
model
prompt_version
extraction_result
validation_result
change_plan
persistence_result
errors
latency
```

Avoid storing sensitive raw information in logs unnecessarily.

---

# 33. AI Cost Monitoring

Track:

* Tokens
* Model
* Request count
* Processing time
* Cost estimate
* Retry count

Use cheaper deterministic logic where possible.

Do not use an LLM to answer:

> "How many hours did I study?"

Query the database.

---

# 34. Performance Testing

Important latency targets should be measured.

Measure:

* App → API latency
* Text extraction time
* Voice transcription time
* Full capture processing time
* Timeline query time
* Assistant response time

The user should receive immediate feedback even when processing continues asynchronously.

---

# 35. Asynchronous Processing Tests

For operations such as:

* Insights
* Reviews
* Embeddings
* Long analysis
* Memory suggestions

test background processing.

The capture itself should not depend on slow optional analysis.

---

# 36. Security Testing

Test:

* Authentication
* Authorization
* Token expiration
* User isolation
* Input validation
* SQL injection protection
* Rate limiting
* Secure secrets
* File/audio access
* API abuse
* Data export
* Data deletion

Personal OS data is highly sensitive.

Security is part of the product, not an infrastructure afterthought.

---

# 37. Privacy Testing

Verify:

* Only authorized users can access their data.
* AI providers receive only required information.
* Logs do not accidentally expose personal data.
* Deleted records are handled according to the chosen retention policy.
* Users can understand what is stored.
* Users can export their data.
* Users can delete their data.

---

# 38. User Correction as Evaluation Data

Corrections are extremely valuable.

If the system predicted:

**Project = A**

and the user changed it to:

**Project = B**

store the correction as an evaluation signal.

Over time this reveals:

* Weak entity resolution
* Bad aliases
* Ambiguous language
* Extraction failures
* Missing context

The system should improve from these patterns without silently retraining itself.

---

# 39. Human Evaluation

Automated metrics are not enough.

Periodically review real captures manually.

Evaluate:

* Did the system understand the user?
* Did it invent anything?
* Did it preserve uncertainty?
* Did it create the correct events?
* Did it ask unnecessary questions?
* Did it connect the right entities?
* Did it respond appropriately?

Human review should focus especially on difficult cases.

---

# 40. Evaluation Dashboard

Eventually build an internal developer dashboard.

Show:

### Capture metrics

* Total captures
* Successful captures
* Failed captures
* Clarifications
* Corrections

### AI metrics

* Extraction accuracy
* Field accuracy
* Hallucination rate
* Entity resolution accuracy
* Duplicate detection accuracy

### System metrics

* Latency
* Errors
* Queue size
* API availability
* AI cost

### User metrics

* Captures per day
* Natural-language usage
* Retention
* Corrections per user

This dashboard is for development, not necessarily part of the user's Personal OS.

---

# 41. Release Gates

Do not promote a new version simply because it works locally.

A release should pass:

### Backend tests

All critical tests pass.

### Database tests

No integrity failures.

### API tests

Critical endpoints pass.

### AI regression tests

No unacceptable regression.

### Security tests

No critical vulnerability.

### Migration tests

Database migrations work forward and, where supported, safely recover.

### Mobile tests

Core capture flow works.

### Real-user test

At least a small amount of real usage has been reviewed.

---

# 42. Failure Classification

Every failure should be classified.

### A — User input ambiguity

The system could not know.

### B — Speech transcription failure

Audio was incorrectly transcribed.

### C — AI extraction failure

Transcript was clear but interpretation was wrong.

### D — Entity resolution failure

Correct information but wrong entity.

### E — Validation failure

Invalid structured output.

### F — Persistence failure

Database/application error.

### G — Analytics failure

Stored data correct but metric incorrect.

### H — Insight failure

Evidence was interpreted incorrectly.

### I — UX failure

The system technically worked but created unnecessary friction.

This makes debugging much faster.

---

# 43. Error Handling Principle

Never hide uncertainty.

If the system is unsure, it should communicate that uncertainty appropriately.

Examples:

> "I recorded this as approximately 2 hours."

> "I found two projects that could match. Which one?"

> "I recorded the expense, but I couldn't determine the category."

This is better than confident incorrect data.

---

# 44. Testing Pyramid

Use:

**Many unit tests**

↓

**Many integration tests**

↓

**API/end-to-end tests**

↓

**AI evaluation dataset**

↓

**Real-user evaluation**

Do not depend exclusively on expensive end-to-end AI tests.

---

# 45. Continuous Evaluation

Every meaningful change should trigger evaluation.

Changes include:

* AI model
* Prompt
* Extraction schema
* Entity resolution logic
* Database schema
* Application logic
* Voice provider
* STT model
* Analytics logic

A model that is "better" in general may still be worse for this specific Personal OS.

---

# 46. AI Model Replacement Test

The architecture should allow switching models.

Before replacing a model:

1. Run the existing evaluation dataset.
2. Run the candidate model.
3. Compare results.
4. Identify regressions.
5. Check cost and latency.
6. Review difficult examples.
7. Deploy gradually.

Do not switch models based only on benchmark scores.

---

# 47. Shadow Testing

For major AI changes, optionally run:

**Current model → production**

**New model → shadow evaluation**

without changing user data.

Compare outputs before deployment.

This reduces risk.

---

# 48. Canary Releases

For important changes:

1. Deploy to a small subset.
2. Monitor errors and corrections.
3. Compare against previous version.
4. Expand gradually.

Avoid changing the entire AI pipeline at once.

---

# 49. Core Trust Principle

The Personal OS should prefer:

**Incomplete but correct**

over:

**Complete but invented**

For example:

> "I know you studied today, but I don't know exactly how long."

is better than inventing a duration.

---

# 50. Final Reliability Architecture

The complete reliability loop should be:

```text
User Input
    ↓
Capture
    ↓
Transcription
    ↓
AI Extraction
    ↓
Schema Validation
    ↓
Business Validation
    ↓
Entity Resolution
    ↓
Duplicate Detection
    ↓
Change Plan
    ↓
Persistence
    ↓
Automated Tests
    ↓
Observability
    ↓
User Correction
    ↓
Evaluation Dataset
    ↓
Regression Testing
    ↓
System Improvement
```

---

# 51. Final Principle

The Personal OS should never become a system the user has to "believe."

It should become a system the user can **inspect, correct, test, and trust**.

Every important number should come from data.

Every important event should have provenance.

Every AI interpretation should be distinguishable from a fact.

Every correction should improve the system's understanding of its own failure modes.

And every new version should be evaluated against what the system already knew how to do.

> **Trust is not a feature added after the AI works. Trust is the architecture that makes the AI usable.**
