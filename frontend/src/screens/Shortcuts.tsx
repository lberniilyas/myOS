import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api";
import { BackButton } from "../components";
import type { AccessKey, NewAccessKey } from "../types";

/** Copy text; over plain http (no clipboard API) select it so it can be copied by hand. */
async function copy(text: string, field: HTMLInputElement | null): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to selecting it */
  }
  field?.focus();
  field?.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  }
}

function CopyField({ id, label, value, notify }: { id: string; label: string; value: string; notify: (text: string) => void }) {
  const field = useRef<HTMLInputElement>(null);
  return (
    <div className="copy-field">
      <label htmlFor={id}>{label}</label>
      <div className="copy-row">
        <input id={id} ref={field} className="field mono" readOnly value={value} onFocus={(e) => e.target.select()} />
        <button className="chip" onClick={async () => notify((await copy(value, field.current)) ? "Copied." : "Selected; copy it from the menu.")}>
          Copy
        </button>
      </div>
    </div>
  );
}

function used(key: AccessKey): string {
  const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  const created = `Created ${day(key.created_at)}`;
  if (!key.last_used_at) return `${created} · never used`;
  const last = new Date(key.last_used_at);
  return `${created} · last used ${day(key.last_used_at)}, ${last.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
}

export function Shortcuts({ notify }: { notify: (text: string) => void }) {
  const [keys, setKeys] = useState<AccessKey[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [name, setName] = useState("iPhone Shortcut");
  const [created, setCreated] = useState<NewAccessKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);
  const url = `${window.location.origin}/v1/captures?background=true`;

  const load = useCallback(() => {
    api<AccessKey[]>("/v1/me/keys")
      .then((data) => {
        setKeys(data);
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, []);

  useEffect(load, [load]);

  async function create() {
    setBusy(true);
    try {
      setCreated(await api<NewAccessKey>("/v1/me/keys", { method: "POST", body: { name: name.trim() } }));
      load();
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "Couldn't create a key.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    setBusy(true);
    try {
      await api(`/v1/me/keys/${id}`, { method: "DELETE" });
      if (created?.id === id) setCreated(null);
      notify("Key revoked. Anything using it can no longer send entries.");
      load();
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "Couldn't revoke the key.");
    } finally {
      setBusy(false);
      setRevoking(null);
    }
  }

  return (
    <>
      <BackButton />
      <h1>Siri & Shortcuts</h1>
      <p className="muted" style={{ marginTop: -8 }}>
        Send an entry without opening the app: say “Hey Siri, Tell my system”, press the Action button, or tap an icon on your home screen.
      </p>

      {created && (
        <>
          <h2>Your new key</h2>
          <div className="card question stack">
            <CopyField id="new-key" label="Authorization header value" value={`Bearer ${created.key}`} notify={notify} />
            <p className="faint" style={{ margin: 0 }}>
              Shown only now. It goes in step 3 below. It can only send entries to your system, nothing else; if it's ever lost, revoke it here.
            </p>
            <button className="button secondary" onClick={() => setCreated(null)}>
              I've copied it
            </button>
          </div>
        </>
      )}

      <h2>Your keys</h2>
      {failed && (
        <p className="error">
          Can't reach your system right now.{" "}
          <button className="link" onClick={load}>
            Try again
          </button>
        </p>
      )}
      <div className="card">
        {keys && keys.length === 0 && <div className="empty">No keys yet. Create one to set up the Shortcut.</div>}
        {keys?.map((key) => (
          <div className="row" key={key.id}>
            <span className="label">
              {key.name} <span className="faint">…{key.hint}</span>
              <span className="sub">{used(key)}</span>
            </span>
            {revoking === key.id ? (
              <span className="chips">
                <button className="chip primary" disabled={busy} onClick={() => revoke(key.id)}>
                  Revoke
                </button>
                <button className="chip" onClick={() => setRevoking(null)}>
                  Keep
                </button>
              </span>
            ) : (
              <button className="chip" aria-label={`Revoke ${key.name}`} onClick={() => setRevoking(key.id)}>
                Revoke…
              </button>
            )}
          </div>
        ))}
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim() && !busy) create();
          }}
        >
          <span className="label">
            <label htmlFor="key-name" className="sub" style={{ marginBottom: 6 }}>
              Name of the new key
            </label>
            <input id="key-name" className="field" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} style={{ padding: "10px 12px" }} />
          </span>
          <button className="chip primary" disabled={busy || !name.trim()}>
            Create key
          </button>
        </form>
      </div>

      <h2>Set up the Shortcut</h2>
      <div className="card question">
        <ol className="steps">
          <li>
            Open the <b>Shortcuts</b> app, tap <b>+</b>, and name the shortcut <b>Tell my system</b>.
          </li>
          <li>
            Add the action <b>Dictate Text</b>. To type instead of speaking, use <b>Ask for Input</b>.
          </li>
          <li>
            Add <b>Get Contents of URL</b>, paste this address, then tap the arrow to show more:
            <CopyField id="capture-url" label="URL" value={url} notify={notify} />
            <ul>
              <li>
                <b>Method</b>: POST
              </li>
              <li>
                <b>Headers</b>: add <code>Authorization</code>, and as its value paste your key (it starts with <code>Bearer pos_key_</code>).
              </li>
              <li>
                <b>Request Body</b>: JSON, with two Text fields: <code>content</code> set to <b>Dictated Text</b> (tap it in the variables bar), and <code>input_type</code> set to <code>VOICE</code>.
              </li>
            </ul>
          </li>
          <li>
            Add <b>Get Dictionary Value</b>: get <b>Value</b> for <code>message</code> in <b>Contents of URL</b>.
          </li>
          <li>
            Add <b>Speak Text</b> with the <b>Dictionary Value</b>, or <b>Show Result</b> to read it.
          </li>
          <li>
            Done. Say “Hey Siri, Tell my system”, or choose it in <b>Settings → Action Button</b> or <b>Settings → Accessibility → Touch → Back Tap</b>.
          </li>
        </ol>
        <p className="faint" style={{ margin: "12px 0 0" }}>
          Your system answers “Saved. Understanding it…” at once, and the entry appears in the app moments later. If the server has been asleep, the first try can take up to a minute.
        </p>
      </div>
    </>
  );
}
