import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { BackButton, ConfirmButton, navigate } from "../components";
import { dayHeading, localToday } from "../format";
import type { HabitDetail } from "../types";

const FREQUENCIES = [
  ["DAILY", "Daily", "today"],
  ["WEEKLY", "Weekly", "this week"],
  ["MONTHLY", "Monthly", "this month"],
];

export function Habit({ id, notify }: { id: string; notify: (text: string) => void }) {
  const [habit, setHabit] = useState<HabitDetail | null>(null);
  const [problem, setProblem] = useState<"missing" | "offline" | null>(null);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<HabitDetail>(`/v1/habits/${id}`)
      .then((data) => {
        setHabit(data);
        setTarget(data.target_count ? String(data.target_count) : "");
        setProblem(null);
      })
      .catch((e) => setProblem(e instanceof ApiError && e.status === 404 ? "missing" : "offline"));
  }, [id]);

  useEffect(load, [load]);

  async function save(body: Record<string, unknown>, message: string) {
    setBusy(true);
    try {
      await api(`/v1/habits/${id}`, { method: "PATCH", body });
      notify(message);
      load();
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "Couldn't save that.");
    } finally {
      setBusy(false);
    }
  }

  if (problem === "missing") return <div className="empty">This habit doesn't exist anymore.</div>;
  if (problem === "offline")
    return (
      <div className="empty">
        Can't reach your system right now.{" "}
        <button className="link" onClick={load}>
          Try again
        </button>
      </div>
    );
  if (!habit) return null;

  const period = FREQUENCIES.find(([value]) => value === habit.frequency)?.[2] ?? "this period";
  const { completed, missed, target_count } = habit.current_period;
  const today = localToday();

  return (
    <>
      <BackButton />
      <div className="eyebrow">Habit</div>
      <h1>{habit.name}</h1>

      <div className="card signal">
        {target_count ? `${completed} of ${target_count} ${period}` : `${completed} time${completed === 1 ? "" : "s"} ${period}`}
        {missed > 0 && <span className="faint"> · {missed} missed</span>}
      </div>

      <h2>How often</h2>
      <div className="card question">
        <div className="chips" style={{ marginBottom: 12 }}>
          {FREQUENCIES.map(([value, label]) => (
            <button
              key={value}
              className={`chip ${habit.frequency === value ? "selected" : ""}`}
              disabled={busy}
              onClick={() => save({ frequency: value }, `Now ${label.toLowerCase()}.`)}
            >
              {label}
            </button>
          ))}
        </div>
        <form
          className="inline-actions"
          onSubmit={(e) => {
            e.preventDefault();
            save({ target_count: target ? Number(target) : null }, target ? `Target: ${target}.` : "No target.");
          }}
        >
          <input
            className="field compact"
            inputMode="numeric"
            placeholder="Target, e.g. 3"
            value={target}
            onChange={(e) => setTarget(e.target.value.replace(/\D/g, ""))}
            aria-label={`Times ${period}`}
          />
          <button className="chip primary" disabled={busy} style={{ flex: "none" }}>
            Save
          </button>
        </form>
      </div>

      <h2>Recently</h2>
      {habit.recent.length === 0 ? (
        <div className="card empty">Say “went running” or “skipped the gym” and it counts here.</div>
      ) : (
        <div className="card">
          {habit.recent.map((r) => (
            <button className="row" key={r.event_id} onClick={() => navigate(`/event/${r.event_id}`)}>
              <span className="label">
                {r.title}
                <span className="sub">{dayHeading(r.occurred_on, today)}</span>
              </span>
              <span className={r.outcome === "COMPLETED" ? "value" : "faint"}>{r.outcome === "COMPLETED" ? "Done" : "Missed"}</span>
            </button>
          ))}
        </div>
      )}

      <div className="stack" style={{ marginTop: 28 }}>
        <ConfirmButton
          label="Archive habit"
          confirmLabel="Archive"
          question="Archive this habit? Its history stays; it stops being tracked."
          disabled={busy}
          onConfirm={async () => {
            try {
              await api(`/v1/habits/${id}`, { method: "DELETE" });
              notify("Habit archived.");
              navigate("/me");
            } catch (e) {
              notify(e instanceof ApiError ? e.message : "Couldn't archive that.");
            }
          }}
        />
      </div>
    </>
  );
}
