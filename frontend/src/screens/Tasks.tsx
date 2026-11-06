import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { navigate } from "../components";
import { dueLabel, localToday } from "../format";
import type { Task } from "../types";

function TaskRow({ task, onChanged, notify }: { task: Task; onChanged: () => void; notify: (text: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(task.title);
  const [due, setDue] = useState(task.due_date ?? "");
  const [busy, setBusy] = useState(false);
  const done = task.status === "COMPLETED";
  const today = localToday();
  // A finished task is no longer due, let alone overdue.
  const due_ = task.due_date && !done ? dueLabel(task.due_date, today) : null;

  async function change(body: Record<string, unknown>, message?: string) {
    setBusy(true);
    try {
      await api(`/v1/tasks/${task.id}`, { method: "PATCH", body });
      if (message) notify(message);
      setEditing(false);
      onChanged();
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "Couldn't save that.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await api(`/v1/tasks/${task.id}`, { method: "DELETE" });
      notify("Task deleted.");
      onChanged();
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "Couldn't delete that.");
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <div className="row editing stack">
        <input className="field compact" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Task" />
        <input className="field compact" type="date" value={due} onChange={(e) => setDue(e.target.value)} aria-label="Due date" />
        <div className="inline-actions">
          <button className="chip" onClick={() => setEditing(false)} disabled={busy}>
            Cancel
          </button>
          <button className="chip" onClick={remove} disabled={busy} style={{ color: "var(--danger)" }}>
            Delete
          </button>
          <button
            className="chip primary"
            disabled={busy || !title.trim()}
            onClick={() => change({ title: title.trim(), due_date: due || null }, "Saved.")}
          >
            Save
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="row">
      <button
        className={`check ${done ? "done" : ""}`}
        aria-label={done ? `Reopen ${task.title}` : `Mark ${task.title} done`}
        disabled={busy}
        onClick={() => change({ status: done ? "TODO" : "COMPLETED" }, done ? "Reopened." : "Done.")}
      >
        {done ? "✓" : ""}
      </button>
      <button className="label" style={{ textAlign: "left" }} onClick={() => setEditing(true)}>
        <span className={done ? "done-title" : undefined}>{task.title}</span>
        {(due_ || task.project) && (
          <span className={`sub ${due_?.overdue && !done ? "overdue" : ""}`}>
            {[due_?.text, task.project?.name].filter(Boolean).join(" · ")}
          </span>
        )}
      </button>
    </div>
  );
}

export function Tasks({ notify }: { notify: (text: string) => void }) {
  const [open, setOpen] = useState<Task[] | null>(null);
  const [done, setDone] = useState<Task[]>([]);
  const [failed, setFailed] = useState(false);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");

  const load = useCallback(() => {
    Promise.all([api<Task[]>("/v1/tasks?open_only=true"), api<Task[]>("/v1/tasks?status=COMPLETED")])
      .then(([openTasks, completed]) => {
        const recent = new Date(Date.now() - 14 * 86400000).toISOString();
        setOpen(openTasks);
        setDone(completed.filter((t) => (t.completed_at ?? "") >= recent).sort((a, b) => (b.completed_at ?? "").localeCompare(a.completed_at ?? "")));
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, []);

  useEffect(load, [load]);

  async function add(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    try {
      await api("/v1/tasks", { method: "POST", body: { title: title.trim(), due_date: due || null } });
      setTitle("");
      setDue("");
      load();
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "Couldn't add that.");
    }
  }

  return (
    <>
      <button className="back" onClick={() => (history.length > 1 ? history.back() : navigate("/home"))}>
        ‹ Back
      </button>
      <h1>Tasks</h1>
      <form className="card stack" style={{ padding: 12 }} onSubmit={add}>
        <input className="field compact" placeholder="New task" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="New task" />
        <div className="inline-actions">
          <input className="field compact" type="date" value={due} onChange={(e) => setDue(e.target.value)} aria-label="Due date (optional)" />
          <button className="chip primary" disabled={!title.trim()}>
            Add
          </button>
        </div>
      </form>

      {failed && (
        <p className="error" style={{ margin: "12px 4px" }}>
          Can't reach your system right now.{" "}
          <button className="link" onClick={load}>
            Try again
          </button>
        </p>
      )}

      <h2>To do</h2>
      {open && open.length === 0 ? (
        <div className="card empty">Nothing to do. Say “I need to…” and it lands here.</div>
      ) : (
        <div className="card">
          {(open ?? []).map((task) => (
            <TaskRow key={task.id} task={task} onChanged={load} notify={notify} />
          ))}
        </div>
      )}

      {done.length > 0 && (
        <>
          <h2>Done recently</h2>
          <div className="card">
            {done.map((task) => (
              <TaskRow key={task.id} task={task} onChanged={load} notify={notify} />
            ))}
          </div>
        </>
      )}
    </>
  );
}
