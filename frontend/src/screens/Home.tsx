import { useCallback, useEffect, useState } from "react";

import { api, ApiError, flushQueue, pendingCaptures } from "../api";
import { ClarificationCard, EventRow, navigate } from "../components";
import { dueLabel, failureReason, greeting, localToday, whenLabel } from "../format";
import type { CaptureListItem, CaptureResult, Clarification, DailySummary, Task, User } from "../types";

type Row = { label: string; value: string; sub?: string };

const TIME_ORDER = ["STUDY", "PROJECT_WORK", "WORK", "TASK_ACTIVITY", "EXERCISE", "SLEEP"];

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function summaryRows(summary: DailySummary): Row[] {
  // Device time is listed per device below, so it isn't repeated as a total here.
  const time = summary.time
    .filter((t) => t.key !== "DEVICE_USAGE")
    .sort((a, b) => TIME_ORDER.indexOf(a.key) - TIME_ORDER.indexOf(b.key));
  const rows: Row[] = time.map((t) => ({
    label: t.label,
    value: t.display ?? "—",
    sub: t.events_without_duration ? `${t.events_without_duration} without a duration` : undefined,
  }));
  summary.devices.forEach((d) => rows.push({ label: d.device === "pc" ? "PC" : d.device === "phone" ? "Phone" : d.device, value: d.display ?? "—" }));
  summary.spending.forEach((s) =>
    rows.push({
      label: "Spending",
      value: s.display ?? "—",
      sub: s.events_without_amount
        ? `${plural(s.events, "item", "items")}, ${s.events_without_amount} without an amount`
        : plural(s.events, "item", "items"),
    }),
  );
  summary.income.forEach((s) => rows.push({ label: "Income", value: s.display ?? "—" }));
  if (summary.habits.length) {
    const done = summary.habits.filter((h) => h.status === "COMPLETED").length;
    rows.push({ label: "Habits", value: `${done}/${summary.habits.length}`, sub: summary.habits.map((h) => h.name).join(", ") });
  }
  if (summary.knowledge.length) {
    rows.push({ label: "Knowledge", value: String(summary.knowledge.length), sub: summary.knowledge.map((k) => k.title).join(", ") });
  }
  if (summary.tasks_completed.length) rows.push({ label: "Tasks done", value: String(summary.tasks_completed.length) });
  return rows;
}

/** Messages the server couldn't turn into entries, with what can be done about each. */
function NeedsAttention({ items, waiting, onChanged, notify }: { items: CaptureListItem[]; waiting: number; onChanged: () => void; notify: (text: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null);

  async function act(id: string, action: () => Promise<unknown>) {
    setBusy(id);
    try {
      await action();
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "Couldn't reach your system.");
    } finally {
      setBusy(null);
      onChanged();
    }
  }

  return (
    <>
      <h2>Not processed yet</h2>
      <div className="card">
        {waiting > 0 && (
          <div className="notice">
            <p className="text">{plural(waiting, "entry is", "entries are")} waiting on this phone to be sent.</p>
            <button
              className="chip"
              disabled={busy === "queue"}
              onClick={() =>
                act("queue", async () => {
                  const sent = await flushQueue();
                  notify(sent ? `Sent ${plural(sent, "entry", "entries")}.` : "Still can't send them; I'll keep trying.");
                })
              }
            >
              Send now
            </button>
          </div>
        )}
        {items.map((item) => (
          <div className="notice" key={item.id}>
            <p className="text">“{(item.text ?? "").slice(0, 140)}{(item.text ?? "").length > 140 ? "…" : ""}”</p>
            <p className="faint" style={{ margin: "0 0 8px" }}>
              {failureReason(item.status === "PROCESSING" ? "STILL_PROCESSING" : item.error_code)} Your words are saved.
            </p>
            <div className="chips">
              <button
                className="chip primary"
                disabled={busy === item.id}
                onClick={() =>
                  act(item.id, async () => {
                    const result = await api<CaptureResult>(`/v1/captures/${item.id}/retry`, { method: "POST" });
                    notify(result.error ? "Still couldn't process it. Try again later." : result.message);
                  })
                }
              >
                {busy === item.id ? "Trying…" : "Try again"}
              </button>
              <button
                className="chip"
                disabled={busy === item.id}
                onClick={() =>
                  act(item.id, async () => {
                    await api(`/v1/captures/${item.id}`, { method: "DELETE" });
                    notify("Removed.");
                  })
                }
              >
                Remove
              </button>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

export function Home({ user, onCapture, refreshKey, notify }: { user: User | null; onCapture: () => void; refreshKey: number; notify: (text: string) => void }) {
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [questions, setQuestions] = useState<Clarification[]>([]);
  const [unfinished, setUnfinished] = useState<CaptureListItem[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    Promise.all([
      api<DailySummary>("/v1/summary/daily"),
      api<Clarification[]>("/v1/clarifications"),
      api<CaptureListItem[]>("/v1/captures?unfinished=true&limit=10"),
      api<Task[]>("/v1/tasks?open_only=true"),
    ])
      .then(([daily, open, stuck, openTasks]) => {
        setSummary(daily);
        setQuestions(open);
        // Entries still in this phone's queue are being retried already; list them once, below.
        const queued = new Set(pendingCaptures().map((p) => p.client_capture_id));
        setUnfinished(stuck.filter((c) => !c.client_capture_id || !queued.has(c.client_capture_id)));
        setTasks(openTasks);
        setError(false);
      })
      .catch(() => setError(true));
  }, []);

  useEffect(load, [load, refreshKey]);

  const rows = summary ? summaryRows(summary) : [];
  const waiting = pendingCaptures().length;
  const firstName = user?.name?.split(" ")[0];
  const today = localToday();
  const nextTask = tasks.find((t) => t.due_date) ?? tasks[0];
  const nextDue = nextTask?.due_date ? dueLabel(nextTask.due_date, today) : null;
  const recent = summary?.recent_events ?? [];

  return (
    <>
      <div className="eyebrow">Personal OS</div>
      <h1>
        {greeting()}
        {firstName ? `, ${firstName}` : ""}.
      </h1>

      <button className="tell" onClick={onCapture}>
        <span className="dot" />
        Tell me what happened…
      </button>

      {error && (
        <p className="error" style={{ margin: "12px 4px" }}>
          Can't reach your system right now.{" "}
          <button className="link" onClick={load}>
            Try again
          </button>
        </p>
      )}

      {(unfinished.length > 0 || waiting > 0) && <NeedsAttention items={unfinished} waiting={waiting} onChanged={load} notify={notify} />}

      {questions.length > 0 && (
        <>
          <h2>One quick question</h2>
          <div className="card">
            <ClarificationCard
              key={questions[0].id}
              item={questions[0]}
              onAnswered={(message) => {
                notify(message);
                load();
              }}
            />
          </div>
        </>
      )}

      <h2>Today</h2>
      {summary && rows.length === 0 ? (
        <div className="card empty">Nothing recorded yet today. Tell your system what happened.</div>
      ) : (
        <div className="card">
          {rows.map((row, index) => (
            <div className="row" key={index}>
              <span className="label">
                {row.label}
                {row.sub && <span className="sub">{row.sub}</span>}
              </span>
              <span className="value">{row.value}</span>
            </div>
          ))}
        </div>
      )}

      {tasks.length > 0 && (
        <div className="card" style={{ marginTop: 12 }}>
          <button className="row" onClick={() => navigate("/tasks")}>
            <span className="label">
              Tasks · {tasks.length} open
              {nextTask && (
                <span className={`sub ${nextDue?.overdue ? "overdue" : ""}`}>
                  Next: {nextTask.title}
                  {nextDue ? ` · ${nextDue.text}` : ""}
                </span>
              )}
            </span>
            <span className="faint" aria-hidden="true">
              ›
            </span>
          </button>
        </div>
      )}

      {recent.length > 0 && (
        <>
          <h2>Recent</h2>
          <div className="card">
            {recent.map((event) => (
              <EventRow key={event.id} event={event} showTime={recent.some((e) => whenLabel(e))} />
            ))}
          </div>
          <p style={{ textAlign: "center", marginTop: 14 }}>
            <button className="link" onClick={() => navigate("/timeline")}>
              See everything →
            </button>
          </p>
        </>
      )}
    </>
  );
}
