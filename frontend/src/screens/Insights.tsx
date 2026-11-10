import { useEffect, useState } from "react";

import { api, ApiError } from "../api";
import type { DailySummary } from "../types";
import { WeekReview } from "./WeekReview";

const SUGGESTIONS = [
  "How much did I study this week?",
  "What did I work on yesterday?",
  "How much did I spend this month?",
  "What did I learn recently?",
  "Which project got most of my time this month?",
];

type Exchange = { question: string; answer: string };

function lastDays(count: number): string[] {
  const days: string[] = [];
  const now = new Date();
  for (let i = count - 1; i >= 0; i--) {
    const day = new Date(now.getTime() - i * 86400000 - now.getTimezoneOffset() * 60000);
    days.push(day.toISOString().slice(0, 10));
  }
  return days;
}

export function Insights() {
  const [question, setQuestion] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [week, setWeek] = useState<{ day: string; study: number; project: number }[]>([]);

  useEffect(() => {
    Promise.all(lastDays(7).map((day) => api<DailySummary>(`/v1/summary/daily?date=${day}`)))
      .then((summaries) =>
        setWeek(
          summaries.map((s) => ({
            day: s.date,
            study: s.time.find((t) => t.key === "STUDY")?.seconds ?? 0,
            project: s.time.find((t) => t.key === "PROJECT_WORK")?.seconds ?? 0,
          })),
        ),
      )
      .catch(() => undefined);
  }, []);

  async function ask(text: string) {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ answer: string }>("/v1/assistant/query", { method: "POST", body: { message: text.trim() } });
      setExchanges((current) => [{ question: text.trim(), answer: result.answer }, ...current]);
      setQuestion("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't reach the assistant.");
    } finally {
      setBusy(false);
    }
  }

  const max = Math.max(1, ...week.map((d) => d.study + d.project));
  const hours = (seconds: number) => (seconds / 3600).toFixed(seconds % 3600 === 0 ? 0 : 1);

  return (
    <>
      <h1>Insights</h1>
      <WeekReview />

      <h2>Ask</h2>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
      >
        <input className="field" placeholder="Ask about your life…" value={question} onChange={(e) => setQuestion(e.target.value)} />
        <button className="button" disabled={busy || !question.trim()}>
          {busy ? "Looking at your records…" : "Ask"}
        </button>
      </form>
      {error && <p className="error">{error}</p>}

      {exchanges.length === 0 && (
        <div className="chips" style={{ marginTop: 14 }}>
          {SUGGESTIONS.map((s) => (
            <button key={s} className="chip" onClick={() => ask(s)} disabled={busy}>
              {s}
            </button>
          ))}
        </div>
      )}

      {exchanges.map((exchange, index) => (
        <div className="card" key={index} style={{ marginTop: 14, padding: 16 }}>
          <p className="faint" style={{ marginTop: 0 }}>
            {exchange.question}
          </p>
          <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{exchange.answer}</p>
        </div>
      ))}

      {week.some((d) => d.study + d.project > 0) && (
        <>
          <h2>Focused time · last 7 days</h2>
          <div className="card" style={{ padding: "16px 16px 10px" }}>
            {week.map((d) => (
              <div key={d.day} style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                <span className="faint" style={{ width: 34 }}>
                  {new Date(`${d.day}T12:00:00`).toLocaleDateString(undefined, { weekday: "short" })}
                </span>
                <div style={{ flex: 1, height: 8, borderRadius: 4, background: "var(--surface-2)", overflow: "hidden", display: "flex" }}>
                  <div style={{ width: `${(d.study / max) * 100}%`, background: "var(--accent)" }} />
                  <div style={{ width: `${(d.project / max) * 100}%`, background: "var(--ink-2)" }} />
                </div>
                <span className="faint" style={{ width: 40, textAlign: "right" }}>
                  {hours(d.study + d.project)}h
                </span>
              </div>
            ))}
            <p className="faint" style={{ margin: "6px 0 4px" }}>
              <span style={{ color: "var(--accent)" }}>■</span> Study <span style={{ color: "var(--ink-2)", marginLeft: 10 }}>■</span> Project work
            </p>
          </div>
        </>
      )}
    </>
  );
}
