import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { BackButton, navigate } from "../components";
import { dayHeading, eventValue, localToday, TYPE_MARKS } from "../format";
import type { DeletedEvent } from "../types";

export function Deleted({ notify, onChanged }: { notify: (text: string) => void; onChanged: () => void }) {
  const [items, setItems] = useState<DeletedEvent[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [erasing, setErasing] = useState<string | null>(null);

  const load = useCallback(() => {
    api<DeletedEvent[]>("/v1/events/deleted")
      .then((data) => {
        setItems(data);
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, []);

  useEffect(load, [load]);

  async function act(id: string, action: () => Promise<unknown>, message: string) {
    setBusy(id);
    try {
      await action();
      notify(message);
      onChanged();
      load();
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "Couldn't do that.");
    } finally {
      setBusy(null);
      setErasing(null);
    }
  }

  const today = localToday();

  return (
    <>
      <BackButton />
      <h1>Recently deleted</h1>
      <p className="muted" style={{ marginTop: -8 }}>
        Deleted entries stay here until you erase them for good.
      </p>
      {failed && (
        <p className="error">
          Can't reach your system right now.{" "}
          <button className="link" onClick={load}>
            Try again
          </button>
        </p>
      )}
      {items && items.length === 0 && <div className="card empty">Nothing deleted.</div>}
      {items && items.length > 0 && (
        <div className="card">
          {items.map((event) => (
            <div className="notice" key={event.id}>
              <button className="row" style={{ padding: 0 }} onClick={() => navigate(`/event/${event.id}`)}>
                <span className="mark">{TYPE_MARKS[event.event_type] ?? "•"}</span>
                <span className="label">
                  {event.title}
                  <span className="sub">
                    {dayHeading(event.occurred_on, today)} · deleted {dayHeading(event.deleted_at.slice(0, 10), today).toLowerCase()}
                  </span>
                </span>
                <span className="value">{eventValue(event)}</span>
              </button>
              {erasing === event.id ? (
                <div className="stack" style={{ marginTop: 10 }}>
                  <p className="text">Erase it for good, together with the words it came from? This can't be undone.</p>
                  <div className="inline-actions">
                    <button className="chip" onClick={() => setErasing(null)}>
                      Cancel
                    </button>
                    <button
                      className="chip primary"
                      style={{ background: "var(--danger)", borderColor: "var(--danger)" }}
                      disabled={busy === event.id}
                      onClick={() => act(event.id, () => api(`/v1/events/${event.id}?permanent=true`, { method: "DELETE" }), "Erased.")}
                    >
                      Erase
                    </button>
                  </div>
                </div>
              ) : (
                <div className="inline-actions" style={{ marginTop: 10 }}>
                  <button
                    className="chip primary"
                    disabled={busy === event.id}
                    onClick={() => act(event.id, () => api(`/v1/events/${event.id}/restore`, { method: "POST" }), "Restored.")}
                  >
                    Restore
                  </button>
                  <button className="chip" disabled={busy === event.id} onClick={() => setErasing(event.id)}>
                    Erase for good
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
