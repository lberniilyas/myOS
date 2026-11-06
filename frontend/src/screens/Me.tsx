import { useEffect, useState } from "react";

import { api, ApiError, saveTokens } from "../api";
import { navigate } from "../components";
import { UNDERSTANDING } from "../format";
import type { Goal, Habit, Knowledge, Project, Task, User } from "../types";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <>
      <h2>{title}</h2>
      <div className="card">{children}</div>
    </>
  );
}

function OpenRow({ to, label, sub, value }: { to: string; label: string; sub?: string; value?: string }) {
  return (
    <button className="row" onClick={() => navigate(to)}>
      <span className="label">
        {label}
        {sub && <span className="sub">{sub}</span>}
      </span>
      {value && <span className="faint">{value}</span>}
      <span className="faint" aria-hidden="true">
        ›
      </span>
    </button>
  );
}

function AddRow({ placeholder, onAdd }: { placeholder: string; onAdd: (value: string) => Promise<void> }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="row"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!value.trim()) return;
        try {
          await onAdd(value.trim());
          setValue("");
          setError(null);
        } catch (err) {
          setError(err instanceof ApiError ? err.message : "Couldn't add that.");
        }
      }}
    >
      <span className="label">
        <input className="field" placeholder={placeholder} value={value} onChange={(e) => setValue(e.target.value)} style={{ padding: "10px 12px" }} />
        {error && <span className="error">{error}</span>}
      </span>
      <button className="chip primary" disabled={!value.trim()}>
        Add
      </button>
    </form>
  );
}

export function Me({ user, onUser, notify }: { user: User | null; onUser: (user: User) => void; notify: (text: string) => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [habits, setHabits] = useState<Habit[]>([]);
  const [knowledge, setKnowledge] = useState<Knowledge[]>([]);
  const [openTasks, setOpenTasks] = useState<Task[]>([]);
  const [password, setPassword] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  function load() {
    api<Project[]>("/v1/projects").then(setProjects).catch(() => undefined);
    api<Goal[]>("/v1/goals").then(setGoals).catch(() => undefined);
    api<Habit[]>("/v1/habits").then(setHabits).catch(() => undefined);
    api<Knowledge[]>("/v1/knowledge?limit=50").then(setKnowledge).catch(() => undefined);
    api<Task[]>("/v1/tasks?open_only=true").then(setOpenTasks).catch(() => undefined);
  }

  useEffect(load, []);

  async function updateProfile(changes: Partial<User>) {
    try {
      onUser(await api<User>("/v1/me", { method: "PATCH", body: changes }));
      notify("Saved.");
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "Couldn't save.");
    }
  }

  async function exportData() {
    const data = await api<unknown>("/v1/me/export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `personal-os-export-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function signOut() {
    await api("/v1/auth/logout", { method: "POST" }).catch(() => undefined);
    saveTokens(null);
    window.dispatchEvent(new Event("pos:signed-out"));
  }

  async function deleteAccount() {
    try {
      await api("/v1/me", { method: "DELETE", body: { password } });
      saveTokens(null);
      window.dispatchEvent(new Event("pos:signed-out"));
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "Couldn't delete the account.");
    }
  }

  const zones = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone") ?? [];

  return (
    <>
      <h1>Me</h1>

      {user && (
        <>
          <h2>Profile</h2>
          <dl className="card">
          <div className="kv">
            <dt>Email</dt>
            <dd>{user.email}</dd>
          </div>
          <label className="kv">
            <dt>Timezone</dt>
            <dd>
              <select value={user.timezone} onChange={(e) => updateProfile({ timezone: e.target.value })} style={{ border: "none", background: "none", textAlign: "right", maxWidth: "58vw" }}>
                {(zones.includes(user.timezone) ? zones : [user.timezone, ...zones]).map((zone) => (
                  <option key={zone}>{zone}</option>
                ))}
              </select>
            </dd>
          </label>
          <label className="kv">
            <dt>Usual currency</dt>
            <dd>
              <input
                defaultValue={user.default_currency ?? ""}
                maxLength={3}
                placeholder="MAD"
                onBlur={(e) => {
                  const value = e.target.value.trim().toUpperCase();
                  if (value !== (user.default_currency ?? "")) updateProfile({ default_currency: value || null });
                }}
                style={{ border: "none", background: "none", textAlign: "right", width: 70 }}
              />
            </dd>
          </label>
          <label className="kv">
            <dt>Language for titles</dt>
            <dd>
              <select value={user.locale} onChange={(e) => updateProfile({ locale: e.target.value })} style={{ border: "none", background: "none" }}>
                <option value="en">English</option>
                <option value="fr">Français</option>
                <option value="ar">العربية</option>
              </select>
            </dd>
          </label>
          </dl>
        </>
      )}

      <Section title="Your lists">
        <OpenRow to="/tasks" label="Tasks" value={openTasks.length ? `${openTasks.length} open` : "none open"} />
        <OpenRow to="/deleted" label="Recently deleted" sub="Restore or erase deleted entries" />
      </Section>

      <Section title="Projects">
        {projects.map((p) => (
          <OpenRow
            key={p.id}
            to={`/project/${p.id}`}
            label={p.name}
            sub={p.aliases.length > 0 ? `also: ${p.aliases.join(", ")}` : undefined}
            value={p.status.toLowerCase()}
          />
        ))}
        <AddRow
          placeholder="New project"
          onAdd={async (name) => {
            await api("/v1/projects", { method: "POST", body: { name } });
            load();
          }}
        />
      </Section>

      <Section title="Goals">
        {goals.map((g) => (
          <OpenRow
            key={g.id}
            to={`/goal/${g.id}`}
            label={g.title}
            sub={g.projects.length > 0 ? g.projects.map((p) => p.name).join(", ") : undefined}
          />
        ))}
        <AddRow
          placeholder="New goal"
          onAdd={async (title) => {
            await api("/v1/goals", { method: "POST", body: { title } });
            load();
          }}
        />
      </Section>

      <Section title="Habits">
        {habits.map((h) => (
          <OpenRow
            key={h.id}
            to={`/habit/${h.id}`}
            label={h.name}
            value={h.target_count ? `${h.target_count}× ${h.frequency.toLowerCase()}` : h.frequency.toLowerCase()}
          />
        ))}
        <AddRow
          placeholder="New habit, e.g. Exercise"
          onAdd={async (name) => {
            await api("/v1/habits", { method: "POST", body: { name } });
            load();
          }}
        />
      </Section>

      <Section title="What you've learned">
        {knowledge.length === 0 && <div className="empty">Concepts appear here as you mention what you learn.</div>}
        {knowledge.map((k) => (
          <OpenRow
            key={k.id}
            to={`/knowledge/${k.id}`}
            label={k.title}
            sub={UNDERSTANDING[k.understanding_state] ?? k.understanding_state}
            value={`${k.evidence_count} entr${k.evidence_count === 1 ? "y" : "ies"}`}
          />
        ))}
      </Section>

      <Section title="Your data">
        <button className="row" onClick={exportData}>
          <span className="label">Export everything</span>
          <span className="faint">JSON</span>
        </button>
        <button className="row" onClick={signOut}>
          <span className="label">Sign out</span>
        </button>
        {confirmDelete ? (
          <div className="question stack">
            <p>This permanently deletes your account and everything in it.</p>
            <input className="field" type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <button className="button danger" onClick={deleteAccount} disabled={!password}>
              Delete forever
            </button>
          </div>
        ) : (
          <button className="row" onClick={() => setConfirmDelete(true)}>
            <span className="label error">Delete account</span>
          </button>
        )}
      </Section>
    </>
  );
}
