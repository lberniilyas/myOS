import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { BackButton, ConfirmButton, EventRow, navigate } from "../components";
import { dayHeading, localToday, UNDERSTANDING, whenLabel } from "../format";
import type { KnowledgeDetail } from "../types";

export function Knowledge({ id, notify }: { id: string; notify: (text: string) => void }) {
  const [item, setItem] = useState<KnowledgeDetail | null>(null);
  const [problem, setProblem] = useState<"missing" | "offline" | null>(null);
  const [alias, setAlias] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<KnowledgeDetail>(`/v1/knowledge/${id}`)
      .then((data) => {
        setItem(data);
        setProblem(null);
      })
      .catch((e) => setProblem(e instanceof ApiError && e.status === 404 ? "missing" : "offline"));
  }, [id]);

  useEffect(load, [load]);

  async function save(body: Record<string, unknown>, message: string) {
    setBusy(true);
    try {
      await api(`/v1/knowledge/${id}`, { method: "PATCH", body });
      notify(message);
      load();
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "Couldn't save that.");
    } finally {
      setBusy(false);
    }
  }

  if (problem === "missing") return <div className="empty">This concept doesn't exist anymore.</div>;
  if (problem === "offline")
    return (
      <div className="empty">
        Can't reach your system right now.{" "}
        <button className="link" onClick={load}>
          Try again
        </button>
      </div>
    );
  if (!item) return null;

  return (
    <>
      <BackButton />
      <div className="eyebrow">What you learned</div>
      <h1>{item.title}</h1>
      {item.first_encountered_on && (
        <p className="faint" style={{ marginTop: -10 }}>
          First recorded {dayHeading(item.first_encountered_on, localToday()).toLowerCase()}
        </p>
      )}

      <h2>How well you know it</h2>
      <div className="card question">
        <div className="chips">
          {Object.entries(UNDERSTANDING)
            .filter(([value]) => value !== "UNKNOWN")
            .map(([value, label]) => (
              <button
                key={value}
                className={`chip ${item.understanding_state === value ? "selected" : ""}`}
                disabled={busy}
                onClick={() => save({ understanding_state: value }, "Saved.")}
              >
                {label}
              </button>
            ))}
        </div>
      </div>

      <h2>Also called</h2>
      <div className="card question">
        {item.aliases.length > 0 && (
          <div className="chips" style={{ marginBottom: 10 }}>
            {item.aliases.map((a) => (
              <span key={a} className="chip">
                {a}
              </span>
            ))}
          </div>
        )}
        <form
          className="inline-actions"
          onSubmit={(e) => {
            e.preventDefault();
            if (alias.trim()) save({ add_aliases: [alias.trim()] }, "Added.").then(() => setAlias(""));
          }}
        >
          <input className="field compact" placeholder="Add another name, e.g. RAG" value={alias} onChange={(e) => setAlias(e.target.value)} aria-label="Another name" />
          <button className="chip primary" disabled={busy || !alias.trim()} style={{ flex: "none" }}>
            Add
          </button>
        </form>
      </div>

      <h2>Where it came up</h2>
      {item.evidence.length === 0 ? (
        <div className="card empty">No entries mention it anymore.</div>
      ) : (
        <div className="card">
          {item.evidence.map((event) => (
            <EventRow key={event.id} event={event} showTime={item.evidence.some((e) => whenLabel(e))} />
          ))}
        </div>
      )}

      <div className="stack" style={{ marginTop: 28 }}>
        <ConfirmButton
          label="Delete this concept"
          confirmLabel="Delete"
          question="Delete it from what you've learned? The entries that mention it stay."
          disabled={busy}
          onConfirm={async () => {
            try {
              await api(`/v1/knowledge/${id}`, { method: "DELETE" });
              notify("Deleted.");
              navigate("/me");
            } catch (e) {
              notify(e instanceof ApiError ? e.message : "Couldn't delete that.");
            }
          }}
        />
      </div>
    </>
  );
}
