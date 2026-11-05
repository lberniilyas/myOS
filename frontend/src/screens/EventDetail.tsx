import { useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { navigate } from "../components";
import { TYPE_LABELS, dayHeading, localToday, whenLabel } from "../format";
import type { CaptureResult, EventDetail as Detail } from "../types";

const SOURCE: Record<string, string> = {
  USER_TEXT: "Typed by you",
  USER_VOICE: "Spoken by you",
  MANUAL_INPUT: "Entered manually",
};

export function EventDetail({ id, notify, onChanged }: { id: string; notify: (text: string) => void; onChanged: () => void }) {
  const [event, setEvent] = useState<Detail | null>(null);
  const [missing, setMissing] = useState(false);
  const [correction, setCorrection] = useState("");
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [minutes, setMinutes] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    api<Detail>(`/v1/events/${id}`)
      .then((data) => {
        setEvent(data);
        setTitle(data.title);
        setMinutes(data.duration_seconds ? String(Math.round(data.duration_seconds / 60)) : "");
        setAmount(data.amount ?? "");
      })
      .catch(() => setMissing(true));
  }

  useEffect(load, [id]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save that.");
    } finally {
      setBusy(false);
    }
  }

  const correct = () =>
    run(async () => {
      const result = await api<CaptureResult>(`/v1/events/${id}/correct`, { method: "POST", body: { text: correction } });
      if (result.error) throw new ApiError(0, result.error.code, result.message);
      notify(result.message);
      setCorrection("");
      load();
    });

  const saveEdits = () =>
    run(async () => {
      const body: Record<string, unknown> = { title };
      if (minutes && Number(minutes) > 0) body.duration_minutes = Number(minutes);
      if (amount && event?.amount !== amount) body.amount = amount;
      await api(`/v1/events/${id}`, { method: "PATCH", body });
      setEditing(false);
      notify("Updated.");
      load();
    });

  const remove = () =>
    run(async () => {
      await api(`/v1/events/${id}`, { method: "DELETE" });
      notify("Deleted. Open it from history to undo.");
      load();
    });

  const restore = () =>
    run(async () => {
      await api(`/v1/events/${id}/restore`, { method: "POST" });
      notify("Restored.");
      load();
    });

  if (missing) return <div className="empty">This entry doesn't exist anymore.</div>;
  if (!event) return null;

  const time = whenLabel(event);
  const isMoney = event.event_type === "EXPENSE" || event.event_type === "INCOME";
  const rows: [string, string][] = [
    ["When", `${dayHeading(event.occurred_on, localToday())}${time ? ` · ${time}` : ""}`],
  ];
  if (event.duration_display) rows.push(["Duration", event.duration_display]);
  if (event.amount_display) rows.push([isMoney ? "Amount" : "Value", event.amount_display]);
  if (event.category) rows.push(["Category", event.category]);
  const topic = event.structured_data.topic as string | undefined;
  const output = event.structured_data.output as string | undefined;
  if (topic) rows.push(["Topic", topic]);
  if (output) rows.push(["Output", output]);
  if (event.area) rows.push(["Area", event.area.name]);
  const related: [string, string][] = [
    ...event.projects.map((p): [string, string] => ["Project", p.name]),
    ...event.goals.map((g): [string, string] => ["Goal", g.name]),
    ...event.knowledge.map((k): [string, string] => ["Knowledge", k.title]),
    ...event.habits.map((h): [string, string] => ["Habit", `${h.name} · ${h.outcome === "COMPLETED" ? "done" : "missed"}`]),
    ...event.tasks.map((t): [string, string] => ["Task", t.name]),
  ];
  if (event.related_event_count) related.push(["Related entries", String(event.related_event_count)]);

  return (
    <>
      <button className="back" onClick={() => history.back()}>
        ‹ Back
      </button>
      <div className="eyebrow">{TYPE_LABELS[event.event_type] ?? event.event_type}</div>
      <h1 style={{ textDecoration: event.deleted_at ? "line-through" : undefined }}>{event.title}</h1>

      <dl className="card" style={{ margin: 0 }}>
        {rows.map(([key, value]) => (
          <div className="kv" key={key}>
            <dt>{key}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>

      {event.description && <p className="muted" style={{ margin: "14px 4px" }}>{event.description}</p>}

      {related.length > 0 && (
        <>
          <h2>Connected to</h2>
          <dl className="card" style={{ margin: 0 }}>
            {related.map(([key, value], index) => (
              <div className="kv" key={index}>
                <dt>{key}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </>
      )}

      <h2>Where this came from</h2>
      <div className="card" style={{ padding: 16 }}>
        {event.provenance.evidence && <p className="quote" style={{ marginTop: 0 }}>“{event.provenance.evidence}”</p>}
        <p className="faint" style={{ margin: 0 }}>
          {SOURCE[event.provenance.source_type] ?? event.provenance.source_type}
          {event.provenance.confidence_label ? ` · ${event.provenance.confidence_label} confidence` : ""}
          {event.revision_count ? ` · edited ${event.revision_count}×` : ""}
        </p>
      </div>

      {event.deleted_at ? (
        <div className="stack" style={{ marginTop: 24 }}>
          <button className="button" onClick={restore} disabled={busy}>
            Restore this entry
          </button>
        </div>
      ) : (
        <>
          <h2>Fix something</h2>
          <div className="stack">
            <input
              className="field"
              placeholder="e.g. “it was yesterday” or “only 2 hours”"
              value={correction}
              onChange={(e) => setCorrection(e.target.value)}
            />
            <button className="button" disabled={busy || !correction.trim()} onClick={correct}>
              {busy ? "Updating…" : "Correct it"}
            </button>
            {editing ? (
              <div className="card stack" style={{ padding: 16 }}>
                <input className="field" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title" />
                <input className="field" inputMode="numeric" value={minutes} onChange={(e) => setMinutes(e.target.value)} placeholder="Minutes" />
                {isMoney && <input className="field" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Amount" />}
                <button className="button" onClick={saveEdits} disabled={busy}>
                  Save changes
                </button>
              </div>
            ) : (
              <button className="button secondary" onClick={() => setEditing(true)}>
                Edit details
              </button>
            )}
            <button className="button danger" onClick={remove} disabled={busy}>
              Delete entry
            </button>
          </div>
        </>
      )}
      {error && <p className="error">{error}</p>}
      {event.provenance.captured_at && (
        <p className="faint" style={{ textAlign: "center", marginTop: 20 }}>
          <button className="link" onClick={() => navigate("/timeline")}>
            Open timeline
          </button>
        </p>
      )}
    </>
  );
}
