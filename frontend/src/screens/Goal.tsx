import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { BackButton, ConfirmButton, EventRow, navigate } from "../components";
import { TYPE_LABELS, whenLabel } from "../format";
import type { EvidenceTotal, GoalDetail, Project } from "../types";

const STATUSES = [
  ["ACTIVE", "Active"],
  ["PAUSED", "Paused"],
  ["COMPLETED", "Reached"],
  ["ARCHIVED", "Archived"],
];

function Totals({ rows }: { rows: EvidenceTotal[] }) {
  if (rows.length === 0) return <div className="card empty">Nothing recorded yet.</div>;
  return (
    <dl className="card">
      {rows.map((row) => (
        <div className="kv" key={row.event_type}>
          <dt>
            {TYPE_LABELS[row.event_type] ?? row.event_type} · {row.events} entr{row.events > 1 ? "ies" : "y"}
          </dt>
          <dd>{row.display ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Goal({ id, notify }: { id: string; notify: (text: string) => void }) {
  const [goal, setGoal] = useState<GoalDetail | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [problem, setProblem] = useState<"missing" | "offline" | null>(null);
  const [title, setTitle] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<GoalDetail>(`/v1/goals/${id}`)
      .then((data) => {
        setGoal(data);
        setTitle(data.title);
        setProblem(null);
      })
      .catch((e) => setProblem(e instanceof ApiError && e.status === 404 ? "missing" : "offline"));
    api<Project[]>("/v1/projects").then(setProjects).catch(() => undefined);
  }, [id]);

  useEffect(load, [load]);

  async function run(action: () => Promise<unknown>, message?: string) {
    setBusy(true);
    try {
      await action();
      if (message) notify(message);
      load();
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "Couldn't save that.");
    } finally {
      setBusy(false);
    }
  }

  if (problem === "missing") return <div className="empty">This goal doesn't exist anymore.</div>;
  if (problem === "offline")
    return (
      <div className="empty">
        Can't reach your system right now.{" "}
        <button className="link" onClick={load}>
          Try again
        </button>
      </div>
    );
  if (!goal) return null;

  const toggleProject = (project: Project) => {
    const current = project.goals.map((g) => g.id);
    const goal_ids = current.includes(id) ? current.filter((g) => g !== id) : [...current, id];
    run(() => api(`/v1/projects/${project.id}`, { method: "PATCH", body: { goal_ids } }), "Saved.");
  };
  const linked = new Set(goal.projects.map((p) => p.id));

  return (
    <>
      <BackButton />
      <div className="eyebrow">Goal</div>
      {renaming ? (
        <form
          className="stack"
          style={{ margin: "4px 0 18px" }}
          onSubmit={(e) => {
            e.preventDefault();
            run(() => api(`/v1/goals/${id}`, { method: "PATCH", body: { title: title.trim() } }), "Renamed.").then(() => setRenaming(false));
          }}
        >
          <input className="field" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Goal" autoFocus />
          <div className="inline-actions">
            <button type="button" className="button secondary" onClick={() => setRenaming(false)}>
              Cancel
            </button>
            <button className="button" disabled={busy || !title.trim()}>
              Save
            </button>
          </div>
        </form>
      ) : (
        <h1>{goal.title}</h1>
      )}

      <div className="chips">
        <button className="chip" onClick={() => setRenaming(true)} disabled={renaming}>
          Rename
        </button>
        {STATUSES.map(([value, label]) => (
          <button
            key={value}
            className={`chip ${goal.status === value ? "selected" : ""}`}
            disabled={busy}
            onClick={() => run(() => api(`/v1/goals/${id}`, { method: "PATCH", body: { status: value } }), `Marked ${label.toLowerCase()}.`)}
          >
            {label}
          </button>
        ))}
      </div>

      <h2>Last 7 days</h2>
      <Totals rows={goal.last_7_days} />
      <h2>Last 30 days</h2>
      <Totals rows={goal.last_30_days} />

      <h2>Projects that serve it</h2>
      {projects.length === 0 ? (
        <div className="card empty">Add a project on the Me tab, then link it here.</div>
      ) : (
        <div className="card question">
          <p className="faint" style={{ marginTop: 0 }}>
            Work on a linked project counts as evidence for this goal.
          </p>
          <div className="chips">
            {projects.map((p) => (
              <button key={p.id} className={`chip ${linked.has(p.id) ? "selected" : ""}`} disabled={busy} onClick={() => toggleProject(p)}>
                {p.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {goal.open_task_count > 0 && (
        <p style={{ margin: "14px 4px" }}>
          <button className="link" onClick={() => navigate("/tasks")}>
            {goal.open_task_count} open task{goal.open_task_count > 1 ? "s" : ""} →
          </button>
        </p>
      )}

      <h2>Recent evidence</h2>
      {goal.recent_evidence.length === 0 ? (
        <div className="card empty">Entries linked to this goal or its projects show up here.</div>
      ) : (
        <div className="card">
          {goal.recent_evidence.map((event) => (
            <EventRow key={event.id} event={event} showTime={goal.recent_evidence.some((e) => whenLabel(e))} />
          ))}
        </div>
      )}

      <div className="stack" style={{ marginTop: 28 }}>
        <ConfirmButton
          label="Delete goal"
          confirmLabel="Delete"
          question="Delete this goal? Entries stay; they just stop counting toward it."
          disabled={busy}
          onConfirm={() =>
            run(async () => {
              await api(`/v1/goals/${id}`, { method: "DELETE" });
              navigate("/me");
            }, "Goal deleted.")
          }
        />
      </div>
    </>
  );
}
