import { useCallback, useEffect, useState } from "react";

import { api, pendingCaptures } from "../api";
import { ClarificationCard, EventRow, navigate } from "../components";
import { greeting } from "../format";
import type { Clarification, DailySummary, User } from "../types";

type Row = { label: string; value: string; sub?: string };

const TIME_ORDER = ["STUDY", "PROJECT_WORK", "WORK", "TASK_ACTIVITY", "EXERCISE", "SLEEP"];

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
  summary.spending.forEach((s) => rows.push({ label: "Spending", value: s.display ?? s.amount, sub: `${s.events} item${s.events > 1 ? "s" : ""}` }));
  summary.income.forEach((s) => rows.push({ label: "Income", value: s.display ?? s.amount }));
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

export function Home({ user, onCapture, refreshKey, notify }: { user: User | null; onCapture: () => void; refreshKey: number; notify: (text: string) => void }) {
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [questions, setQuestions] = useState<Clarification[]>([]);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    Promise.all([api<DailySummary>("/v1/summary/daily"), api<Clarification[]>("/v1/clarifications")])
      .then(([daily, open]) => {
        setSummary(daily);
        setQuestions(open);
        setError(false);
      })
      .catch(() => setError(true));
  }, []);

  useEffect(load, [load, refreshKey]);

  const rows = summary ? summaryRows(summary) : [];
  const pending = pendingCaptures().length;
  const firstName = user?.name?.split(" ")[0];

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

      {pending > 0 && (
        <p className="faint" style={{ margin: "12px 4px" }}>
          {pending} entr{pending > 1 ? "ies" : "y"} waiting to sync.
        </p>
      )}
      {error && (
        <p className="error" style={{ margin: "12px 4px" }}>
          Can't reach your system right now.
        </p>
      )}

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

      {summary && summary.recent_events.length > 0 && (
        <>
          <h2>Recent</h2>
          <div className="card">
            {summary.recent_events.map((event) => (
              <EventRow key={event.id} event={event} />
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
