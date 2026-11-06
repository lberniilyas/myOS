import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { BackButton, ConfirmButton, EventRow, navigate } from "../components";
import { dayHeading, hoursLabel, localToday, UNDERSTANDING, whenLabel } from "../format";
import type { Goal, ProjectDetail } from "../types";

const STATUSES = [
  ["ACTIVE", "Active"],
  ["PAUSED", "Paused"],
  ["COMPLETED", "Done"],
  ["ARCHIVED", "Archived"],
];

export function Project({ id, notify }: { id: string; notify: (text: string) => void }) {
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [problem, setProblem] = useState<"missing" | "offline" | null>(null);
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [alias, setAlias] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<ProjectDetail>(`/v1/projects/${id}`)
      .then((data) => {
        setProject(data);
        setName(data.name);
        setProblem(null);
      })
      .catch((e) => setProblem(e instanceof ApiError && e.status === 404 ? "missing" : "offline"));
    api<Goal[]>("/v1/goals").then(setGoals).catch(() => undefined);
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

  if (problem === "missing") return <div className="empty">This project doesn't exist anymore.</div>;
  if (problem === "offline")
    return (
      <div className="empty">
        Can't reach your system right now.{" "}
        <button className="link" onClick={load}>
          Try again
        </button>
      </div>
    );
  if (!project) return null;

  const goalIds = project.goals.map((g) => g.id);
  const toggleGoal = (goalId: string) =>
    run(
      () =>
        api(`/v1/projects/${id}`, {
          method: "PATCH",
          body: { goal_ids: goalIds.includes(goalId) ? goalIds.filter((g) => g !== goalId) : [...goalIds, goalId] },
        }),
      "Saved.",
    );
  const today = localToday();
  const showTime = project.recent_events.some((e) => whenLabel(e));

  return (
    <>
      <BackButton />
      <div className="eyebrow">Project</div>
      {renaming ? (
        <form
          className="stack"
          style={{ margin: "4px 0 18px" }}
          onSubmit={(e) => {
            e.preventDefault();
            run(() => api(`/v1/projects/${id}`, { method: "PATCH", body: { name: name.trim() } }), "Renamed.").then(() => setRenaming(false));
          }}
        >
          <input className="field" value={name} onChange={(e) => setName(e.target.value)} aria-label="Project name" autoFocus />
          <div className="inline-actions">
            <button type="button" className="button secondary" onClick={() => setRenaming(false)}>
              Cancel
            </button>
            <button className="button" disabled={busy || !name.trim()}>
              Save
            </button>
          </div>
        </form>
      ) : (
        <h1>{project.name}</h1>
      )}

      <div className="chips">
        <button className="chip" onClick={() => setRenaming(true)} disabled={renaming}>
          Rename
        </button>
        {STATUSES.map(([value, label]) => (
          <button
            key={value}
            className={`chip ${project.status === value ? "selected" : ""}`}
            disabled={busy}
            onClick={() => run(() => api(`/v1/projects/${id}`, { method: "PATCH", body: { status: value } }), `Marked ${label.toLowerCase()}.`)}
          >
            {label}
          </button>
        ))}
      </div>

      <h2>Time invested</h2>
      <dl className="card">
        <div className="kv">
          <dt>Last 7 days</dt>
          <dd>{hoursLabel(project.stats.last_7_days_seconds)}</dd>
        </div>
        <div className="kv">
          <dt>Last 30 days</dt>
          <dd>{hoursLabel(project.stats.last_30_days_seconds)}</dd>
        </div>
        <div className="kv">
          <dt>All time</dt>
          <dd>{project.stats.total_display ?? "—"}</dd>
        </div>
        <div className="kv">
          <dt>Last worked on</dt>
          <dd>{project.stats.last_activity_on ? dayHeading(project.stats.last_activity_on, today) : "Not yet"}</dd>
        </div>
      </dl>

      <h2>Also called</h2>
      <div className="card question">
        <p className="faint" style={{ marginTop: 0 }}>
          Other names you use for it, so “the tender app” finds this project.
        </p>
        <div className="chips" style={{ marginBottom: 10 }}>
          {project.aliases.map((a) => (
            <button
              key={a}
              className="chip"
              aria-label={`Remove nickname ${a}`}
              disabled={busy}
              onClick={() => run(() => api(`/v1/projects/${id}/aliases/${encodeURIComponent(a)}`, { method: "DELETE" }), "Removed.")}
            >
              {a}
              <span className="remove">×</span>
            </button>
          ))}
        </div>
        <form
          className="inline-actions"
          onSubmit={(e) => {
            e.preventDefault();
            if (alias.trim())
              run(() => api(`/v1/projects/${id}/aliases`, { method: "POST", body: { alias: alias.trim() } }), "Added.").then(() => setAlias(""));
          }}
        >
          <input className="field compact" placeholder="Add a nickname" value={alias} onChange={(e) => setAlias(e.target.value)} aria-label="New nickname" />
          <button className="chip primary" disabled={busy || !alias.trim()} style={{ flex: "none" }}>
            Add
          </button>
        </form>
      </div>

      {goals.length > 0 && (
        <>
          <h2>Works toward</h2>
          <div className="card question">
            <div className="chips">
              {goals.map((g) => (
                <button key={g.id} className={`chip ${goalIds.includes(g.id) ? "selected" : ""}`} disabled={busy} onClick={() => toggleGoal(g.id)}>
                  {g.title}
                </button>
              ))}
            </div>
          </div>
        </>
      )}

      {project.open_tasks.length > 0 && (
        <>
          <div className="section-head">
            <h2>Open tasks</h2>
            <button className="link" onClick={() => navigate("/tasks")}>
              All tasks
            </button>
          </div>
          <div className="card">
            {project.open_tasks.map((t) => (
              <div className="row" key={t.id}>
                <span className="label">
                  {t.title}
                  {t.due_date && <span className="sub">Due {dayHeading(t.due_date, today)}</span>}
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      <h2>Recent entries</h2>
      {project.recent_events.length === 0 ? (
        <div className="card empty">Nothing recorded for this project yet.</div>
      ) : (
        <div className="card">
          {project.recent_events.map((event) => (
            <EventRow key={event.id} event={event} showTime={showTime} />
          ))}
        </div>
      )}

      {project.knowledge.length > 0 && (
        <>
          <h2>What you learned on it</h2>
          <div className="card">
            {project.knowledge.map((k) => (
              <button className="row" key={k.id} onClick={() => navigate(`/knowledge/${k.id}`)}>
                <span className="label">
                  {k.title}
                  <span className="sub">{UNDERSTANDING[k.understanding_state] ?? k.understanding_state}</span>
                </span>
              </button>
            ))}
          </div>
        </>
      )}

      <div className="stack" style={{ marginTop: 28 }}>
        <ConfirmButton
          label="Delete project"
          confirmLabel="Delete"
          question="Delete this project? Past entries keep their link; the name becomes free again."
          disabled={busy}
          onConfirm={() =>
            run(async () => {
              await api(`/v1/projects/${id}`, { method: "DELETE" });
              navigate("/me");
            }, "Project deleted.")
          }
        />
      </div>
    </>
  );
}
