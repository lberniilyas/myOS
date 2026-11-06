# Personal OS — Build Plan

This plan turns the ten spec documents in the project root into a build order, and records the decisions taken where the specs disagree or leave a gap. When a later spec changes a decision, update this file.

## 1. What the first iteration builds

The first milestone, taken from spec #9 ("First Complete Vertical Slice"), is:

> I tell my Personal OS what happened → it understands correctly → it records it → I can find it later → I can ask about it.

This iteration builds that slice end to end: the backend, plus the iPhone app as a home-screen web app (PWA). It covers steps 1–9 and 11–13 of the build sequence in spec #9.

| Area | In this iteration |
|---|---|
| Foundation | FastAPI app, config, logging with request IDs, one error format, Alembic migrations, test suite, local dev database |
| Data model | Users, sessions, areas, goals, projects (with aliases), tasks, habits, knowledge (with aliases), captures, sources, events, event links, event revisions, clarifications |
| Auth | Register, login, refresh, logout, profile, data export, account deletion |
| Capture | Text input and voice transcripts → AI extraction → validation → time and entity resolution → duplicate check → change plan → one transaction → short reply |
| Corrections | Natural-language corrections (update, delete, split), manual edits, soft delete with undo, revision history |
| Clarifications | Short follow-up questions attached to already-saved records |
| Retrieval | Timeline with cursor pagination, event detail with provenance, search, daily summary |
| Assistant | Questions about your own history, answered with database query tools |
| Evaluation | A golden dataset of realistic inputs and a script that scores extraction against it |
| App | Home-screen web app: Home, capture sheet, Timeline, event detail, Insights (ask your history), Me; offline capture queue |

**Not in this iteration:**

- **Server-side speech-to-text.** V1 takes voice as text: the browser's speech recognition where iOS allows it, or the iPhone keyboard's dictation key. Uploading audio for Gemini transcription comes later, behind its own provider interface.
- **Hosting.** It runs on your PC for now; reaching it from anywhere over HTTPS needs a tunnel or a host (see the README).
- **Later phases:** insights, reviews, memory, experiments, automatic data sources and integrations (spec #9 phases 8–16), plus rate limiting and background workers.

## 2. Decisions that resolve the specs

| # | Topic | What the specs say | Decision |
|---|---|---|---|
| 1 | Pipeline order | #5 §4 runs validation after entity resolution; #5 §46 and #4 §52 run it before. | Schema validation right after extraction, then time resolution, entity resolution, business validation (it needs the resolved values), duplicate detection, change plan, persistence. |
| 2 | Voice and normalization | #5 §46 normalizes input before speech-to-text. | Speech-to-text first; normalization works on the transcript. |
| 3 | Event types | #3, #7 and #9 each list different types; none has a type for "I felt distracted", which #4 §30 and #5 §18 require. | #7's list plus `STATE` for user-reported states. Habit outcomes use the `HABIT` type plus a link status, not `HABIT_COMPLETED`/`HABIT_MISSED`. Creating a task is a task record, not an event. |
| 4 | Time precision | #7 has one `time_precision` field, which can't express "exactly 2 hours, start unknown". | Separate `time_precision` (when it started) and `duration_precision` (how long). Every event also stores `occurred_on`, its date in your timezone, so daily totals never drift across midnight. |
| 5 | Money | #7 puts amounts in JSON but also says fields used for queries must be relational. | `amount` (decimal), `currency` and `amount_precision` are real columns, with database checks. Merchant and other details go in `structured_data`. |
| 6 | Currency | Never invent a currency (#4 §28), but #7's examples assume MAD. | Use a currency the user stated; otherwise use their profile default if set; otherwise leave it empty. |
| 7 | Event ↔ project link | #7 §37 indexes `events.project_id`; #7 §18 requires link tables. | Link tables (`event_projects`, `event_goals`, `event_knowledge`, `event_tasks`, `event_habits`). |
| 8 | Facts vs interpretation | #7 §12 puts `ai_interpretation` on events; #3 §14 says interpretations live apart from facts. | Events hold facts only. `source_type` tells user reports from device observations. Interpretations will live in insights. |
| 9 | Capture processing | #8 §10 returns "processing" and has the client poll; #2 and #5 expect an immediate short reply. | V1 processes synchronously and replies right away. The raw capture is committed first, so a failure never loses it; a retry endpoint reprocesses it. Background workers come with long voice notes and insights. |
| 10 | Clarifications | Some sections ask before saving; #2 §4 saves first, then asks. | Always save what's safe, then attach optional questions to the saved record. Answering a question patches that record. This needs a `clarifications` table. |
| 11 | Duplicates | Auto-merge (#4 §20) vs never merge silently (#7 §35). | The model can say a statement repeats a known event, which merges into it. The deterministic check only ever asks; it never drops an event on its own. |
| 12 | Task due dates | #7 has `due_at`; captured tasks are day-level ("tomorrow"). | `due_date` (a date) in V1. |
| 13 | Build order | #9 §49 builds projects/goals/knowledge at step 11, after entity resolution (step 6), which needs projects. | Basic CRUD for projects, goals, knowledge, tasks and habits ships with the data model; richer views come later. |
| 14 | API paths | `/captures` (#7), `/v1/captures` (#8); `POST /v1/assistant` (#8) vs `POST /v1/assistant/query` (#10); `TEXT` vs `text`. | Everything under `/v1`. The assistant is at `POST /v1/assistant/query`. Enum values are uppercase. |
| 15 | Systems entity | In the data model (#3, #7) but not in V1's required tables (#7 §50, #9 §47). | Deferred. |
| 16 | Auth method | Not specified. | Email and password (Argon2 hashes), with opaque server-side session tokens: access tokens last 1 hour, refresh tokens 30 days and rotate on use. Sign in with Apple can come later. |
| 17 | AI provider | Provider-neutral interface (#4 §45, #5 §42, #8 §13). | `AIProvider` interface with Gemini (default) and Claude implementations, plus a scripted fake for tests. Dates, sums and matching are done in code, never by the model (#4 §35, #10 §12). |
| 18 | Hallucination guard | "Never invent" (#4 §44, #10 §10). | Every extracted item must quote the exact words it came from. The pipeline checks that quote against the input and drops anything that fails. |
| 19 | iPhone app | Native SwiftUI (#8 §2, #9 §26). | Your call (2026-10-24): a PWA, a website added to the home screen. It needs no Mac, and the backend serves it from the same address. |
| 20 | AI model | Unspecified. | Your call (2026-10-24): Gemini, free tier. Real tests on 2026-10-25 showed `gemini-3.8-flash` taking over 100 s per message on the free tier, so extraction and the assistant use `gemini-3.5-flash-lite` (3–6 s, 22/22 evaluation cases passed), falling back once to `gemini-3.1-flash-lite` when rate limited or overloaded. The free tier lets Google use the content to improve its products, which conflicts with spec #1 §17 (privacy); switch to a paid key before recording sensitive data. |

## 3. Architecture

A modular monolith (spec #8 §4) in `backend/app/`:

```text
api surface      auth · captures · events · projects · goals · tasks · habits · knowledge · areas
                 summary · search · assistant · me (export, delete)
capture pipeline captures/pipeline.py
                   store capture → build context → extract (AI) → validate schema
                   → resolve time → resolve entities → validate rules → detect duplicates
                   → plan changes → apply in one transaction → reply
ai layer         ai/provider.py (interface) · ai/gemini_provider.py · ai/anthropic_provider.py · ai/fake_provider.py
                 ai/prompts/<task>/<version>/system.md (prompts are versioned files, spec #10 §30)
deterministic    core/ (time parsing, text matching, money, periods, formatting) · analytics/
storage          PostgreSQL via SQLAlchemy 2 + Alembic
app              frontend/ (React + Vite PWA), served by the backend at /
```

The boundary from spec #8 §38 holds throughout: **the model interprets, the application validates, the database stores, analytics calculates.**

## 4. Roadmap

Status: ✅ done · 🔄 in progress · ⬜ not started

| Step | Spec #9 step | Status |
|---|---|---|
| Backend foundation, dev database, migrations, tests | 1–2 | ✅ |
| Authentication, profile, export, account deletion | 3 | ✅ |
| Capture and event APIs | 4 | ✅ |
| Extraction with Gemini (Claude optional), validation, hallucination guard | 5 | ✅ verified with real Gemini: 22/22 evaluation cases |
| Entity resolution (projects, aliases, knowledge, habits, tasks) | 6 | ✅ |
| Timeline, event detail, search, daily summary | 7, 12 | ✅ |
| Corrections, revisions, clarifications | 8 | ✅ |
| Home-screen app: Home, Capture, Timeline, Event detail, Insights, Me | 9 | ✅ |
| Assistant over database tools | 13 | ✅ |
| Extraction evaluation set and runner | spec #10 | ✅ |
| Voice: browser speech + keyboard dictation; server transcription later | 10 | 🔄 |
| HTTPS hosting so the app works away from home | — | 🔄 Vercel (2026-11-05) or Render (2026-11-06) with Neon; both configured, steps in the README |
| Analytics baselines | 14 | ⬜ |
| Insights, reviews, memory | 15–17 | ⬜ |
| Automatic sources (calendar, device data, PC agent) | 18 | ⬜ |
