# Personal OS — Voice/Text Flow & Conversational Capture Architecture

## 1. Purpose

Design the Personal OS so that natural language and voice are the primary interfaces for recording life.

The user should not have to manually fill forms, select categories, choose modules, or answer a long sequence of questions.

The fundamental interaction should be:

**User says something → Personal OS understands it → extracts what matters → updates the system → responds briefly.**

The interface should feel like talking to a personal operating system, not filling out a tracker.

The architecture must support:

* Text input
* Voice input
* Short messages
* Long free-form journal entries
* Mixed-language input
* Follow-up conversations
* Corrections
* Ambiguous information
* Multiple events in one message
* Automatic relationship detection
* Minimal clarification
* Immediate feedback

---

# 2. Core Interaction Principle

The user should be able to say almost anything naturally.

Examples:

> "I studied AI for three hours today and worked on TenderPilot for another two."

> "Spent 35 on lunch."

> "Didn't really get much done today. I spent most of the afternoon on YouTube."

> "Today I learned how RAG actually works. The vector database part finally makes sense."

> "I worked on the backend for BLANI from 2 to 5."

> "I was supposed to study but ended up scrolling Instagram for two hours."

> "Yesterday I finished the API integration."

> "Actually, that was Monday, not yesterday."

The system should interpret these statements without forcing the user into a predefined input format.

---

# 3. Two Primary Capture Modes

The system should support two equivalent capture modes.

## Mode A — Text Capture

The user types naturally.

Example:

> "Today I studied AI for 2 hours, worked on my project for 3 hours, spent 20 on food and learned about vector databases."

The system processes the message as one capture session.

It may create multiple events:

1. Study event
2. Project work event
3. Expense event
4. Knowledge event

The user should not need to submit them separately.

---

## Mode B — Voice Capture

Voice should follow:

**Voice → Speech-to-Text → Transcript → Context → AI Extraction → Validation → Persistence**

The user speaks naturally.

Example:

> "Today was pretty productive. I studied AI for around three hours, then worked on TenderPilot for another two hours. I learned about RAG and finally understood how vector databases work. I spent about thirty on lunch."

The system converts this into structured information.

The original transcript should be preserved as the source.

Voice is simply another input channel.

The underlying extraction architecture should remain the same as text.

---

# 4. Universal Capture Pipeline

Every capture should follow this pipeline:

**INPUT**

↓

**INPUT NORMALIZATION**

↓

**CONTEXT BUILDING**

↓

**INTENT / CONTENT UNDERSTANDING**

↓

**INFORMATION EXTRACTION**

↓

**TIME RESOLUTION**

↓

**ENTITY RESOLUTION**

↓

**RELATIONSHIP RESOLUTION**

↓

**DUPLICATE DETECTION**

↓

**VALIDATION**

↓

**CHANGE PLAN**

↓

**PERSISTENCE**

↓

**DERIVED METRICS**

↓

**OPTIONAL ANALYSIS**

↓

**USER RESPONSE**

The user should never need to see this complexity.

---

# 5. Input Normalization

Normalize the input before extraction.

The system should identify:

* Input type
* Language
* User timezone
* Current date
* Conversation context
* Previous related messages
* Existing entities
* Existing projects
* Existing goals
* Existing habits
* Existing knowledge
* Existing events when relevant

Supported languages should include:

* English
* French
* Arabic
* Darija
* Mixed-language speech/text

Examples:

> "Lyoum qrit AI 2 hours."

> "J'ai travaillé sur TenderPilot pendant 3 heures."

> "Today خدمت على backend."

The user should not have to choose the language.

---

# 6. Context Builder

Before interpreting the input, construct the minimum context required to understand it.

Relevant context may include:

* Current date/time
* User timezone
* Recent events
* Active projects
* Active goals
* Known entities
* Known aliases
* Current conversation
* Previous user correction
* Existing habits
* Existing tasks

Do not blindly send the entire database to the model.

Use targeted context retrieval.

Example:

User:

> "I worked on it for two hours."

The system should look at recent conversation/context to determine what "it" refers to.

If there is only one obvious active project, resolve it automatically.

If there are several plausible projects, ask.

---

# 7. Intent Detection

The system should determine what the user is trying to do.

Possible intents include:

* Record something
* Correct something
* Delete something
* Update something
* Ask a question
* Ask about past activity
* Start a session
* End a session
* Create a task
* Create a goal
* Record knowledge
* Record expense/income
* Record habit behavior
* Reflect on the day
* Ask for an insight
* Ask for recommendations
* Continue an existing conversation

Do not assume every message is a new event.

For example:

> "Actually, make that three hours."

This is a correction.

It should modify the existing event rather than create another event.

---

# 8. Extraction

Extract only information actually supported by the user's input.

For each possible event identify:

* Event type
* Title
* Description
* Date
* Start time
* End time
* Duration
* Approximation/precision
* Area
* Project
* Goal
* Habit
* Knowledge
* Task
* Financial information
* Device information
* User-reported state
* Output/result
* Source
* Confidence

Never invent missing information.

If the user says:

> "I studied AI for a while."

Do not convert "a while" into 2 hours.

Store the duration as unknown/approximate.

If the user says:

> "I spent around 30 on food."

Store approximately 30, not exactly 30.

---

# 9. Multiple Events From One Input

One input can produce multiple events.

Example:

> "I studied AI for two hours, worked on TenderPilot for three hours, learned about RAG, spent 25 on lunch and didn't exercise."

Possible structured events:

### Event 1

Type: Study
Duration: 2h
Topic: AI

### Event 2

Type: Project Work
Duration: 3h
Project: TenderPilot

### Event 3

Type: Knowledge
Topic: RAG
State: Learned

### Event 4

Type: Expense
Amount: 25
Category: Food

### Event 5

Type: Habit
Habit: Exercise
Status: Missed
Source: User report

All events should remain connected to the same original capture.

---

# 10. Time Interpretation

Natural language time must be resolved carefully.

Examples:

> "today"

> "yesterday"

> "this morning"

> "last night"

> "around 3"

> "from 2 to 5"

> "for about two hours"

> "after lunch"

The system should use:

* User timezone
* Current date/time
* Conversation context
* Existing event context

Do not create false precision.

Represent time with appropriate precision:

* Exact timestamp
* Date + approximate time
* Date only
* Approximate duration
* Unknown

Example:

> "I studied yesterday."

Do not invent a start/end time.

---

# 11. Conversational Follow-Ups

The system should ask questions only when clarification is genuinely necessary.

Bad:

> "You studied AI. What category should I use?"

The user should never have to provide information the system can infer.

Good:

> "Which project did you mean?"

Only ask when multiple interpretations materially affect the resulting data.

Example:

> "I worked on the project for two hours."

If the user has:

* TenderPilot
* BLANI
* Personal OS

and the context does not identify which one:

> "Which project — TenderPilot, BLANI, or Personal OS?"

Keep clarification short.

---

# 12. Never Over-Confirm

Do not ask:

> "You studied AI for 3 hours. Should I save this?"

If confidence is high, save it.

The default behavior should be:

**Understand → Save → Briefly acknowledge**

Example:

> "Logged: 3h AI study."

Not:

> "I detected an AI study event lasting approximately 3 hours. Would you like me to save it?"

The system should behave like an assistant, not a form.

---

# 13. Confidence-Based Behavior

Use confidence internally.

### High confidence

Automatically save.

Example:

> "I worked on TenderPilot for 3 hours."

### Medium confidence

Save with appropriate uncertainty if safe.

Example:

> "I spent around three hours working."

Store approximately 3h.

### Low confidence

Ask a clarification if the ambiguity materially changes the record.

Example:

> "I worked on it for a while."

If "it" cannot be resolved:

> "What were you working on?"

Do not expose technical confidence scores unless useful.

---

# 14. Corrections

Corrections are first-class interactions.

Examples:

> "Actually, I studied for four hours, not three."

> "That was yesterday, not today."

> "The 30 wasn't food. It was transport."

> "Delete that expense."

The system should identify the referenced existing event and modify it.

Do not create contradictory events.

Maintain an audit trail of important changes.

---

# 15. Follow-Up Context

Conversation should maintain short-term context.

Example:

User:

> "I studied AI for two hours."

System:

> "Logged 2h AI study."

User:

> "Actually make it three."

The system understands that "it" refers to the previous study event.

User:

> "And I spent 20 afterwards."

The system can interpret "afterwards" relative to the conversation/event context.

Conversation context should not become permanent memory automatically.

---

# 16. Natural Language Does Not Mean Everything Becomes Permanent Memory

Separate:

### Event

Something that happened.

### Conversation context

Temporary context needed to understand the current interaction.

### Memory

Information intentionally retained for future interactions.

Example:

> "I'm planning to move to France next year."

This may be relevant as a long-term memory.

But:

> "I'm tired today."

should normally remain a user-reported state/event rather than permanent memory.

The memory engine decides what qualifies as durable memory according to the separate memory architecture.

---

# 17. User-Reported vs Observed Data

The system must preserve provenance.

Example:

User says:

> "I spent about 4 hours on YouTube."

Later an automatic device integration reports:

> YouTube usage: 3h42.

Do not silently replace the user's statement.

Store both sources if relevant:

**User-reported:** ~4h
**Observed:** 3h42

The system may use observed data for measurement while retaining the user's report as context.

---

# 18. Subjective Information

Natural language often contains subjective information.

Examples:

> "Today was productive."

> "I felt focused."

> "I wasted the whole afternoon."

> "I was exhausted."

These should not automatically become objective measurements.

Store them as:

**User-reported state / perception**

The system can later compare subjective reports with observed behavior.

Example:

> User reported: "Very productive."

Observed:

* 4h focused work
* 3h social media
* 1 completed task

The system can present this comparison during reflection without judging the user.

---

# 19. Productivity Capture

Do not reduce productivity to a single AI-generated score.

Instead capture:

* Activity
* Duration
* Output
* Result
* Context
* Project
* Focus state if reported
* Interruptions when available
* User perception

Example:

> "I worked on the backend for 3 hours and finished the authentication system."

Store:

**Activity:** Backend development
**Duration:** 3h
**Project:** Relevant project
**Output:** Authentication system completed

This allows productivity to be analyzed later.

---

# 20. Knowledge Capture

Knowledge should be extracted naturally.

Example:

> "Today I finally understood how vector databases work."

Create a knowledge record around:

* Topic
* Concept
* Source if provided
* Date encountered
* User's understanding state
* Related study/project
* Evidence

Do not automatically claim:

> "User is proficient in vector databases."

Instead:

> Encountered / studied / reported understanding

Demonstrated understanding can be captured later through actual work or explicit evidence.

---

# 21. Finance Capture

Financial information should be extractable conversationally.

Examples:

> "Spent 40 on lunch."

> "Paid 300 for my laptop."

> "My salary came in today, 1200."

Extract:

* Amount
* Currency
* Direction
* Category
* Merchant if available
* Date
* Account/source if available
* Description
* Confidence
* Provenance

Never invent a currency.

If the currency is genuinely ambiguous and materially important, ask.

---

# 22. Habit Capture

Habits should normally be inferred from events rather than requiring separate habit logging.

Example:

> "I went to the gym for an hour."

This can satisfy an exercise habit if the user has one.

Example:

> "Didn't exercise today."

This can record a missed habit if exercise is a configured habit.

Do not force:

> "Did you complete Exercise Habit? Yes/No."

Natural behavior should be the primary source.

---

# 23. Task Capture

Create a task only when the user expresses actionable intent.

Example:

> "I need to finish the backend tomorrow."

Create:

Task: Finish backend
Due: Tomorrow

But:

> "I worked on the backend for two hours."

creates an event, not a task.

Distinguish:

**Task = something to do**

**Event = something that happened**

---

# 24. Project Resolution

Projects should be resolved automatically where possible.

Example:

> "Worked on the tender app for two hours."

If "tender app" is an alias for TenderPilot, resolve it to:

Project: TenderPilot

Maintain aliases.

Possible aliases:

* TenderPilot
* tender app
* tender project
* hackathon project

Do not create duplicate projects because the user used a different name.

---

# 25. Relationship Resolution

Events should automatically connect to relevant entities.

Example:

> "I spent three hours working on TenderPilot and finished the PDF extraction module."

Possible relationships:

Event
→ Project: TenderPilot
→ Goal: Hackathon submission
→ Task: PDF extraction
→ Knowledge: document extraction
→ Output: module completed

Only create relationships supported by context.

---

# 26. Capture Response

After successful capture, response should be short.

Examples:

> "Logged 2h AI study and your 25 food expense."

> "Logged the TenderPilot session — 3h, authentication completed."

> "Got it. Updated yesterday's study session from 2h to 3h."

Do not repeat the entire extracted JSON.

Do not overwhelm the user with internal details.

---

# 27. When Multiple Things Were Captured

The response can summarize the major changes.

Example:

User:

> "Studied AI for 2 hours, worked on TenderPilot for 3, spent 20 on food and learned about RAG."

Response:

> "Logged 2h AI study, 3h TenderPilot work, a 20 food expense, and your RAG learning."

No need for a confirmation for every item.

---

# 28. Error Handling

If processing fails:

Do not pretend the data was saved.

Say clearly:

> "I couldn't save that yet. Your entry is still here — try again."

If only part of the input was successfully processed:

> "I logged the study session and expense, but I couldn't determine which project you meant."

Never silently drop information.

---

# 29. Offline / Poor Connectivity

The mobile experience should be resilient.

If possible:

**Capture locally → queue → synchronize → process**

The user should not lose a voice note or text because of temporary connectivity problems.

Maintain:

* Capture ID
* Timestamp
* Input type
* Raw input
* Processing status
* Retry state

Possible states:

`CAPTURED`

`PROCESSING`

`PROCESSED`

`NEEDS_CLARIFICATION`

`FAILED`

`SYNC_PENDING`

---

# 30. Voice UX

Voice capture should be extremely fast.

Suggested flow:

**Tap microphone**

↓

**Speak**

↓

**Stop**

↓

**Transcript appears**

↓

**AI processes**

↓

**Events saved**

↓

**Short response**

Avoid forcing the user through multiple screens.

The user should be able to speak naturally for several seconds or minutes.

For longer recordings, support:

* Streaming or chunked transcription
* Background processing where technically possible
* Recovery from interruptions
* Transcript preservation

---

# 31. Voice Feedback

The system should communicate processing state clearly.

Example:

**Listening...**

↓

**Understanding...**

↓

**Logged**

Avoid unnecessary animations.

Do not make the user wait for complex analysis before confirming that the basic capture succeeded.

Critical persistence should happen before optional insight generation.

---

# 32. Long Journal Input

Long-form entries should be treated differently from short captures.

Example:

> "Today was weird. I woke up late, couldn't focus in the morning, then around 2pm I started working on TenderPilot..."

The system should extract structured events while preserving the original journal/context.

Potential output:

* Sleep/wake context
* Productivity events
* Project work
* Knowledge
* Habits
* Expenses
* Subjective state
* Journal/context event

The user should not need to structure the journal manually.

---

# 33. Capture Sessions

Each user interaction should have a capture/session identifier.

One capture session may generate multiple events.

Example:

`capture_123`

→ Study event
→ Project event
→ Expense event
→ Knowledge event

This preserves provenance and makes corrections/debugging possible.

---

# 34. No Forced Categorization

The user should never be required to decide:

* Which module?
* Which category?
* Which database?
* Which event type?
* Which metric?
* Which relationship?

The system should determine these from the content.

The user should only provide information naturally.

---

# 35. Minimal Manual Input

Manual structured controls can exist for cases where precision matters.

Examples:

* Exact expense
* Start/stop timer
* Correct event
* Edit date
* Edit duration
* Delete event

But manual forms are secondary.

Primary interface:

**Tell the system what happened.**

---

# 36. Capture vs Reflection

The system should distinguish between:

## Capture

"I studied AI for two hours."

The system records information.

## Reflection

"Why have I been less productive this week?"

The system analyzes historical information.

Capture should be fast.

Reflection can be deeper.

Do not mix the two unnecessarily.

---

# 37. Conversation Types

The AI should support several conversation modes:

### Capture

> "I worked on BLANI for 2 hours."

### Correction

> "Actually that was yesterday."

### Query

> "How much did I spend this week?"

### Reflection

> "Why was this week different from last week?"

### Planning

> "What should I focus on tomorrow?"

### Review

> "Give me my weekly review."

### Investigation

> "Why do I keep missing my study sessions?"

The same Personal OS AI can handle these, but the backend should route them to the appropriate operation.

---

# 38. Data Query vs LLM Guess

When answering questions about the user's history:

**Query structured data first.**

Then let the AI interpret the results.

Example:

User:

> "How much did I study this week?"

Do not ask the LLM to estimate from memory.

Instead:

Database query
→ Study events
→ Aggregate duration
→ Return factual result
→ AI formats answer.

This principle applies to:

* Spending
* Screen time
* PC usage
* Study time
* Project time
* Habit completion
* Goals
* Knowledge
* Reviews

---

# 39. Evidence-Based Reflection

For questions such as:

> "Why was I less productive this week?"

The system should:

1. Query relevant events.
2. Calculate comparable metrics.
3. Identify observable differences.
4. Identify recurring associations.
5. Distinguish observation from hypothesis.
6. Explain uncertainty.

Example:

**Observed:**
Study time decreased from 12h to 6h.

**Observed:**
Average late-night phone usage increased.

**Possible association:**
Lower study time occurred during the same period as higher late-night phone usage.

Do not claim:

> "Your phone caused your lower productivity."

unless there is appropriate evidence.

---

# 40. Personal Baseline

Interpretation should be based primarily on the user's own history.

Avoid generic statements such as:

> "You should study 4 hours every day."

Instead:

> "Your recent average has been around 2.5 hours/day, while your goal-related weeks have averaged closer to 3.5."

The system should learn the user's normal patterns over time.

---

# 41. Privacy

Natural language and voice may contain extremely sensitive information.

The system must:

* Preserve provenance
* Minimize unnecessary data exposure
* Encrypt sensitive data where appropriate
* Avoid sending unnecessary personal information to external AI providers
* Allow deletion
* Allow editing
* Clearly identify integrations
* Make AI processing understandable
* Never sell or expose personal data

Voice recordings should have explicit retention rules.

If raw audio is not needed after transcription, allow deletion according to the user's settings.

---

# 42. AI Provider Independence

Do not tightly couple the conversational system to one model provider.

Create an abstraction layer:

`AIProvider`

Possible implementations:

* OpenAI
* Anthropic
* Google
* Local model
* Future provider

The Personal OS architecture should remain independent from the specific model.

---

# 43. Model Responsibilities

Use deterministic code whenever possible.

### LLM should handle:

* Natural language understanding
* Semantic extraction
* Entity interpretation
* Ambiguity detection
* Relationship suggestions
* Conversation
* Explanation
* Reflection
* Planning

### Application code should handle:

* Validation
* Business rules
* Date calculations
* Financial calculations
* Aggregations
* Persistence
* Authorization
* Deduplication logic
* Data integrity

### Database should handle:

* Storage
* Relationships
* Queries
* Constraints
* Indexing

### Analytics layer should handle:

* Metrics
* Trends
* Comparisons
* Statistical calculations

Do not use an LLM where deterministic computation is more reliable.

---

# 44. Core User Experience Test

The architecture should pass this test:

> "I should be able to tell my Personal OS what happened in my day exactly like I would tell another person."

The system should then:

**Understand**

→ **Structure**

→ **Connect**

→ **Store**

→ **Measure**

→ **Learn**

→ **Help me improve**

without forcing the user to manually operate a collection of trackers.

---

# 45. Example End-to-End Interaction

### User

> "Today was pretty productive. I studied AI for around three hours, worked on TenderPilot for two hours, finally understood RAG and vector databases, spent 30 on lunch, and completely skipped exercise."

### System internally identifies:

**Event 1**
Study — ~3h — AI

**Event 2**
Project Work — 2h — TenderPilot

**Event 3**
Knowledge — RAG

**Event 4**
Knowledge — Vector Databases

**Event 5**
Expense — ~30 — Food/Lunch

**Event 6**
Habit — Exercise — Missed

**Event 7**
Subjective state — User reported day as productive

All events reference the same capture session.

### User-facing response

> "Logged your study, TenderPilot work, RAG/vector database learning, lunch expense, and missed exercise."

The complexity stays behind the interface.

---

# 46. Final Architecture

The complete capture architecture should be:

**TEXT / VOICE**

↓

**CAPTURE SERVICE**

↓

**INPUT NORMALIZATION**

↓

**STT (if voice)**

↓

**CONTEXT BUILDER**

↓

**INTENT ROUTER**

↓

**EXTRACTION MODEL**

↓

**STRUCTURED OUTPUT**

↓

**SCHEMA VALIDATION**

↓

**BUSINESS VALIDATION**

↓

**TIME RESOLUTION**

↓

**ENTITY RESOLUTION**

↓

**RELATIONSHIP RESOLUTION**

↓

**DUPLICATE DETECTION**

↓

**CHANGE PLANNER**

↓

**PERSISTENCE SERVICE**

↓

**EVENT / ENTITY DATABASE**

↓

**DERIVED METRICS**

↓

**ANALYSIS / INSIGHT ENGINE**

↓

**PERSONAL OS AI**

↓

**SHORT USER RESPONSE**

---

# 47. V1 Scope

The first implementation should support:

### Input

* Text
* Voice
* English
* French
* Darija
* Arabic
* Mixed language

### Extraction

* Study
* Work
* Project work
* Knowledge
* Expense
* Habit
* Journal/context
* Tasks

### Intelligence

* Basic entity resolution
* Basic time resolution
* Duplicate detection
* Corrections
* Multiple events from one input
* Minimal clarification
* Provenance
* Confidence

### UX

* One universal capture field
* Microphone
* Transcript
* Processing state
* Short confirmation
* Timeline
* Event editing

Do not attempt to build the complete intelligence system before the core capture loop is reliable.

The first milestone is:

**"I tell my Personal OS what happened → it understands correctly → it records it → I can find it later."**

Everything else builds on this foundation.
