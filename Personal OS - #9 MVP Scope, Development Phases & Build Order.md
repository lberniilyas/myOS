# Personal OS — #9 MVP Scope, Development Phases & Build Order

## 1. Purpose

Define the exact implementation roadmap for the Personal OS.

The system has a large long-term vision, but V1 must remain focused.

The goal is not to build every feature immediately.

The goal is to prove the core loop:

**Capture → Understand → Structure → Store → Retrieve → Reflect**

The MVP should establish a strong foundation that can later expand into:

* Automatic phone usage
* PC usage
* Finance integrations
* Calendar
* Advanced knowledge systems
* Experiments
* AI memory
* Deep analytics
* Predictive insights
* Automation

---

# 2. MVP Definition

The MVP is successful when a user can naturally tell the Personal OS what happened and the system reliably turns that input into useful structured information.

Example:

> "Today I studied AI for two hours, worked on TenderPilot for three hours, learned about RAG, spent 30 on lunch, and didn't exercise."

The system should:

1. Understand the input.
2. Identify multiple pieces of information.
3. Create the appropriate events.
4. Resolve TenderPilot to the correct project.
5. Record the expense.
6. Record the knowledge.
7. Record the missed habit if configured.
8. Show the result in the timeline.
9. Include the information in future queries.

That is the MVP.

---

# 3. MVP Product Principle

Do not ask:

> "How many features can we launch?"

Ask:

> "How well does the system understand the user's life?"

A smaller system that correctly understands natural language is more valuable than a large application full of disconnected features.

---

# 4. V1 Must-Have Features

V1 should include:

### Core

* User account
* Authentication
* Universal capture
* Text input
* Voice input
* AI extraction
* Multiple events from one input
* Event persistence
* Event editing
* Event deletion
* Timeline
* Search
* Basic projects
* Basic goals
* Basic knowledge
* Basic tasks
* Basic habits
* Basic finance events
* Basic daily summary
* Basic AI questions

These form the minimum useful Personal OS.

---

# 5. V1 Input Experience

The user opens the app and immediately sees:

**Tell me what happened...**

They can:

* Type
* Speak

No complicated setup is required.

Example:

> "I studied AI for two hours."

The system responds:

> "Logged 2h AI study."

This should take seconds.

---

# 6. V1 Event Types

Initially support:

* Study
* Work
* Project work
* Knowledge
* Expense
* Income
* Habit
* Task activity
* Journal/context
* Device usage when available

Do not build specialized event systems before these are reliable.

---

# 7. V1 Projects

Allow the user to create projects.

Example:

**TenderPilot**

Then natural language should resolve:

> "Worked on the tender app."

to:

**TenderPilot**

Projects should support:

* Name
* Description
* Status
* Aliases
* Related events
* Tasks
* Goals

---

# 8. V1 Goals

Allow basic goals.

Example:

**Become an AI engineer**

The system can connect:

* Study
* Projects
* Knowledge
* Tasks
* Work

to the goal.

Do not build sophisticated goal scoring yet.

The system should primarily show evidence.

---

# 9. V1 Knowledge

The system should automatically extract knowledge from captures.

Example:

> "Today I finally understood vector databases."

Creates:

Knowledge:

**Vector databases**

State:

**Reported understanding**

Related:

* AI study event
* Relevant project if applicable

The user should not have to manually maintain a knowledge database.

---

# 10. V1 Habits

Allow users to define a small number of habits.

Examples:

* Exercise
* Read
* Study
* Sleep routine

But derive habit activity from events whenever possible.

Example:

> "Went running this morning."

can automatically count toward an exercise habit.

---

# 11. V1 Finance

Finance should initially support manual/conversational capture.

Example:

> "Spent 35 on lunch."

The system records:

* Amount
* Currency
* Category
* Date
* Direction
* Source

Do not build bank integrations in the first MVP.

---

# 12. V1 Voice

Voice is important because low friction is a core product principle.

Implement:

**Tap → Speak → Transcribe → Understand → Save**

Support voice capture before building advanced voice conversations.

Raw audio retention should be configurable.

---

# 13. V1 Timeline

The timeline should show everything the system knows happened.

Example:

### Today

**19:30**

Food
35

**17:00–19:00**

TenderPilot
Project work
2h

**14:00–17:00**

AI Study
3h

**12:00**

Exercise
Completed

This proves that the universal event model works.

---

# 14. V1 Event Editing

The user must be able to fix mistakes.

Examples:

> "That was yesterday."

> "Change it to four hours."

> "That wasn't TenderPilot."

> "Delete that."

The system should update existing records.

This is essential because AI will not always be correct.

---

# 15. V1 Search

Support basic structured and text search.

Examples:

> "TenderPilot"

> "RAG"

> "food"

> "AI study"

Also support natural-language questions through the assistant.

---

# 16. V1 Personal OS Assistant

The assistant should answer basic questions from actual data.

Examples:

> "How much did I study this week?"

> "What did I work on yesterday?"

> "What did I learn this month?"

> "How much did I spend this week?"

> "How much time did I spend on TenderPilot?"

The system must query the database before answering.

---

# 17. V1 Daily Summary

Home should show a simple summary of today's actual data.

Example:

**Today**

Study
3h

Project work
2h

Phone
3h42

Spending
42

Knowledge
2 concepts

Tasks completed
3

Only show metrics for which reliable data exists.

---

# 18. V1 Insights

Keep insights simple.

Examples:

> "You've studied 30% less this week than your previous 4-week average."

> "TenderPilot received most of your project time this week."

> "Your spending on food increased compared with last week."

Insights should be based on enough data.

If there isn't enough evidence:

> Do not generate the insight.

---

# 19. V1 Weekly Review

A basic weekly review can include:

* Total study time
* Project time
* Spending
* Habits
* Tasks
* Knowledge
* Important events
* One or two evidence-based observations

Do not build a huge report.

The first version should be readable in under a few minutes.

---

# 20. What V1 Does NOT Need

Do not build these initially:

* Full bank synchronization
* Automatic PC monitoring
* Advanced iOS Screen Time integrations
* Wearable integrations
* Email analysis
* Browser monitoring
* Calendar synchronization
* Social media monitoring
* Location tracking
* Predictive life recommendations
* Autonomous agents
* Complex vector database
* Advanced knowledge graph visualization
* Social features
* Gamification
* Public profiles
* Multi-user collaboration

These are future layers.

---

# 21. Phase 0 — Foundation

Build:

* Repository
* Project structure
* Development environment
* PostgreSQL
* FastAPI
* SQLAlchemy
* Alembic
* Authentication
* Environment configuration
* Logging
* Basic tests
* CI if possible

Goal:

> Backend runs reliably and can store authenticated user data.

---

# 22. Phase 1 — Core Data Model

Implement:

* Users
* Areas
* Goals
* Projects
* Tasks
* Knowledge
* Habits
* Captures
* Sources
* Events

Then implement:

* Event relationships
* Provenance
* Time precision
* Structured event metadata

Goal:

> The system can represent a user's life as structured data.

---

# 23. Phase 2 — Text Capture

Build:

`POST /v1/captures`

Input:

> "I studied AI for two hours."

Pipeline:

**Text**

→ **Extraction**

→ **Validation**

→ **Entity resolution**

→ **Persistence**

→ **Response**

Goal:

> Natural language creates correct events.

---

# 24. Phase 3 — Multi-Event Capture

Expand from one event to many.

Example:

> "Studied AI for 2h, worked on TenderPilot for 3h and spent 20 on food."

System creates:

* Study
* Project work
* Expense

Goal:

> One sentence can update multiple parts of the Personal OS.

This is a major MVP milestone.

---

# 25. Phase 4 — Correction System

Implement:

* Event editing
* Natural-language correction
* Delete
* Merge
* Split

Examples:

> "Actually it was 4 hours."

> "That was yesterday."

> "The 20 was transportation."

Goal:

> The user can trust the system even when the AI makes mistakes.

---

# 26. Phase 5 — iPhone MVP

Build the first SwiftUI application.

Screens:

1. Home
2. Capture
3. Timeline
4. Event detail
5. Insights
6. Me

Do not build additional screens unless required.

---

# 27. Phase 6 — Voice

Add:

* Microphone
* Audio capture
* Speech-to-text
* Transcript
* Existing extraction pipeline
* Processing state
* Error recovery

Goal:

> Speaking should be as useful as typing.

---

# 28. Phase 7 — Search & Assistant

Implement:

* Global search
* Structured queries
* Assistant endpoint
* Tool-based data retrieval
* Evidence-based responses

Examples:

> "What did I spend this week?"

> "Why was last week less productive?"

Goal:

> The system can answer questions about the user's own life.

---

# 29. Phase 8 — Analytics

Implement deterministic metrics:

* Daily study time
* Weekly study time
* Project time
* Spending
* Habit frequency
* Task completion
* Device usage where available

Build personal baselines.

Goal:

> The system can measure change rather than simply store events.

---

# 30. Phase 9 — Insights

Build:

* Pattern detection
* Baseline comparison
* Change detection
* Evidence linking
* Insight generation

Example:

**Observation**

> Study time decreased from 12h/week to 8h/week.

**Associated change**

> Late-night phone usage increased during the same period.

**Interpretation**

> These changes occurred together, but this does not establish causation.

Goal:

> The system begins helping the user understand patterns.

---

# 31. Phase 10 — Reviews

Implement:

* Daily review
* Weekly review
* Monthly review later

Reviews should be generated from:

**Events → Metrics → Evidence → AI interpretation**

Not from an LLM inventing a summary from memory.

---

# 32. Phase 11 — Memory

Implement controlled AI memory.

The system can retain useful long-term information.

Each memory should have:

* Content
* Source
* Confidence
* Importance
* Created date
* Optional expiration
* Edit
* Delete

Goal:

> The Personal OS becomes more useful over time without becoming opaque.

---

# 33. Phase 12 — Automatic Data

Only after the core system works should automatic sources be introduced.

Potential order:

### First

Calendar

### Then

iPhone device data where Apple APIs and permissions permit

### Then

PC usage

### Then

Other integrations

Automatic sources should feed the same event architecture.

---

# 34. Phase 13 — PC Agent

Eventually build a lightweight desktop agent.

Potential data:

* Application usage
* Active computer time
* Development tools
* Study tools
* Browser usage where explicitly enabled
* Work sessions

The PC agent should send structured events.

It should not become a separate application ecosystem.

---

# 35. Phase 14 — Advanced Finance

Later add:

* Financial account integrations
* Transaction imports
* Investment tracking
* Recurring expenses
* Budget analysis
* Financial goals

All financial data should still connect to the universal event model.

---

# 36. Phase 15 — Experiment Engine

Eventually allow the user to define experiments.

Example:

**Hypothesis**

> Reducing late-night phone use may improve morning study consistency.

Experiment:

2 weeks.

Metrics:

* Sleep timing
* Study start time
* Study duration
* Phone usage

Result:

Measured from actual events.

The system should help evaluate the experiment without pretending to establish scientific causation from one person's data.

---

# 37. Phase 16 — Advanced Intelligence

Only after sufficient historical data exists, introduce:

* More sophisticated pattern detection
* Personal baselines
* Context-aware recommendations
* Goal risk detection
* Behavioral experiments
* Predictive signals
* Deeper personal knowledge retrieval

Do not build these before the data foundation is trustworthy.

---

# 38. Development Priority

Always prioritize in this order:

### 1. Data correctness

Wrong data destroys trust.

### 2. Capture friction

If recording information is annoying, the system will become empty.

### 3. Retrieval

The user must be able to find what was recorded.

### 4. Measurement

The system must turn events into useful metrics.

### 5. Understanding

Insights should be based on evidence.

### 6. Action

Only then should the system recommend changes.

---

# 39. Feature Evaluation Rule

Before adding a feature, ask:

### Does it improve capture?

or

### Does it improve understanding?

or

### Does it improve action?

If it does none of these:

**Do not build it yet.**

---

# 40. MVP Success Metrics

Do not measure MVP success mainly by:

* Number of screens
* Number of database tables
* Number of AI calls
* Number of features

Measure:

### Capture success

Can users record information naturally?

### Extraction accuracy

Did the system understand correctly?

### Correction rate

How often must users fix the AI?

### Clarification rate

How often does the system unnecessarily ask questions?

### Retrieval success

Can users find their history?

### Response speed

Does capture feel immediate?

### Retention of useful history

Does the system become more useful after weeks of use?

---

# 41. Most Important Product Metric

A key metric should be:

> **Percentage of natural user inputs that become correct structured records without manual form filling.**

Example:

100 natural inputs

→ 92 correctly processed automatically

→ 5 required clarification

→ 3 required correction

This is much more meaningful than "we have 20 features."

---

# 42. Quality Thresholds

Before moving to the next phase, establish practical quality thresholds.

For example:

### Capture

High reliability.

### Extraction

Very low rate of invented information.

### Time

No systematic false precision.

### Finance

Extremely conservative with amounts and currencies.

### Entity resolution

Known projects should resolve reliably.

### Corrections

Existing events should update rather than duplicate.

### Assistant

Never invent personal history.

Exact numerical thresholds should be determined from testing rather than arbitrarily fixed at the beginning.

---

# 43. First Real User Test

Use the system personally for several weeks.

Record normal life naturally:

> "Studied AI for 2h."

> "Worked on TenderPilot."

> "Spent 30 on food."

> "Didn't exercise."

> "Read about RAG."

> "Spent too much time on YouTube."

Do not artificially structure inputs to make the system look good.

Real usage will reveal:

* Missing event types
* Bad extraction
* Friction
* Ambiguity
* Missing relationships
* Poor UI decisions
* Unnecessary questions
* Useful insights

---

# 44. Build From Real Inputs

Create an evaluation dataset from actual natural language inputs.

Include:

* Short entries
* Long entries
* Voice transcripts
* Darija
* French
* English
* Mixed language
* Corrections
* Ambiguous references
* Multiple events
* Approximate times
* Finance
* Projects
* Knowledge
* Habits
* Emotional/contextual statements

Use this dataset continuously during development.

---

# 45. Don't Overbuild AI

The first Personal OS does not need a giant autonomous AI agent.

It needs a reliable interpreter.

The hierarchy should be:

**Deterministic code**

for facts and calculations.

**LLM**

for language and semantic understanding.

**Analytics**

for measurement.

**AI**

for interpretation.

**User**

for final decisions.

---

# 46. Don't Overbuild the UI

The first app should be almost boring.

A user should immediately know:

> Where do I tell it something?

> Where do I see what happened?

> Where do I see patterns?

> Where do I manage my system?

If those four things are obvious, the UX is working.

---

# 47. Don't Overbuild the Database

The database should be extensible, not enormous.

Start with:

**User**

**Event**

**Capture**

**Source**

**Project**

**Goal**

**Task**

**Knowledge**

**Area**

Then add complexity when actual requirements appear.

---

# 48. First Complete Vertical Slice

Before implementing the rest of the roadmap, make one complete path work:

```text id="x19q3f"
User
 ↓
iPhone
 ↓
Voice/Text
 ↓
Capture API
 ↓
AI Extraction
 ↓
Validation
 ↓
Project Resolution
 ↓
Event Creation
 ↓
PostgreSQL
 ↓
Timeline
 ↓
Assistant Query
 ↓
Answer
```

If this works reliably, the architecture is already proving itself.

---

# 49. Recommended Build Sequence

The actual implementation order should be:

### Step 1

Repository + backend foundation

### Step 2

PostgreSQL schema

### Step 3

Authentication

### Step 4

Event/capture APIs

### Step 5

Text extraction

### Step 6

Entity resolution

### Step 7

Timeline

### Step 8

Event correction

### Step 9

SwiftUI Home + Capture

### Step 10

Voice

### Step 11

Projects / Goals / Knowledge

### Step 12

Search

### Step 13

Personal OS Assistant

### Step 14

Analytics

### Step 15

Insights

### Step 16

Reviews

### Step 17

Memory

### Step 18

Automatic integrations

---

# 50. Definition of MVP Done

The MVP is done when a real user can:

1. Open the iPhone app.
2. Speak or type naturally.
3. Describe several things that happened.
4. Have the system extract them correctly.
5. See them in the timeline.
6. Correct mistakes naturally.
7. Search the history.
8. Ask questions about their history.
9. See basic daily/weekly measurements.
10. Receive a small number of evidence-based insights.

And most importantly:

> **The user does not need to maintain multiple trackers manually.**

---

# 51. Final Product Loop

The complete V1 should establish:

**CAPTURE**

I tell the system what happened.

↓

**STRUCTURE**

AI converts messy information into structured events.

↓

**STORE**

The backend preserves the information and its provenance.

↓

**CONNECT**

Events connect to projects, goals, knowledge, habits, and tasks.

↓

**MEASURE**

Analytics calculates what actually happened.

↓

**UNDERSTAND**

The system identifies meaningful patterns.

↓

**REFLECT**

The user sees what matters.

↓

**ADJUST**

The user decides what to change.

↓

**EXECUTE**

The user acts.

↓

**CAPTURE AGAIN**

The system observes the next cycle.

---

# 52. Final MVP Principle

Do not build the Personal OS as a giant application that happens to contain AI.

Build the smallest system that proves this idea:

> **A person can live normally, tell the system what happened in natural language, and gradually build a structured understanding of their own life without becoming a full-time data-entry operator.**

That is the product.

Everything else is expansion.
