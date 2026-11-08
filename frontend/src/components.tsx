import { useEffect, useRef, useState, type ReactNode } from "react";

import { api, ApiError, followCapture, sendCapture, stillWorking } from "./api";
import { TYPE_MARKS, eventValue, whenLabel } from "./format";
import type { CaptureResult, Clarification, EventSummary } from "./types";

export function navigate(path: string): void {
  window.location.hash = path;
}

// --- tab bar ---------------------------------------------------------------------------------

const ICONS: Record<string, ReactNode> = {
  home: <path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6h-4v6H5a1 1 0 0 1-1-1z" />,
  timeline: (
    <>
      <circle cx="6" cy="6" r="1.6" />
      <circle cx="6" cy="12" r="1.6" />
      <circle cx="6" cy="18" r="1.6" />
      <path d="M10 6h10M10 12h10M10 18h10" />
    </>
  ),
  insights: <path d="M4 19h16M7 16V11M12 16V6M17 16v-3" />,
  me: (
    <>
      <circle cx="12" cy="8.5" r="3.5" />
      <path d="M5 20c1.2-3.6 4-5.2 7-5.2s5.8 1.6 7 5.2" />
    </>
  ),
};

export function TabBar({ current }: { current: string }) {
  const tabs = [
    ["home", "Home"],
    ["timeline", "Timeline"],
    ["insights", "Insights"],
    ["me", "Me"],
  ];
  return (
    <div className="tabs">
      <nav>
        {tabs.map(([key, label]) => (
          <button key={key} className={`tab ${current === key ? "active" : ""}`} onClick={() => navigate(`/${key}`)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              {ICONS[key]}
            </svg>
            {label}
          </button>
        ))}
      </nav>
    </div>
  );
}

// --- sheet -----------------------------------------------------------------------------------

export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <div className="sheet" role="dialog" aria-label={title}>
        <div className="grabber" />
        <div className="sheet-head">
          <h3>{title}</h3>
          <button className="link" onClick={onClose}>
            Done
          </button>
        </div>
        {children}
      </div>
    </>
  );
}

export function BackButton() {
  return (
    <button className="back" onClick={() => history.back()}>
      ‹ Back
    </button>
  );
}

/** A destructive action that needs a second, deliberate tap. */
export function ConfirmButton({
  label,
  confirmLabel,
  question,
  onConfirm,
  disabled = false,
}: {
  label: string;
  confirmLabel: string;
  question: string;
  onConfirm: () => void;
  disabled?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <button className="button danger" onClick={() => setAsking(true)} disabled={disabled}>
        {label}
      </button>
    );
  }
  return (
    <div className="card question">
      <p>{question}</p>
      <div className="inline-actions">
        <button className="button secondary" onClick={() => setAsking(false)}>
          Cancel
        </button>
        <button
          className="button"
          style={{ background: "var(--danger)" }}
          disabled={disabled}
          onClick={() => {
            setAsking(false);
            onConfirm();
          }}
        >
          {confirmLabel}
        </button>
      </div>
    </div>
  );
}

export function Toast({ text, onDone }: { text: string; onDone: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDone, 3200);
    return () => clearTimeout(timer);
  }, [text, onDone]);
  return <div className="toast">{text}</div>;
}

// --- events ----------------------------------------------------------------------------------

export function EventRow({ event, showTime = true }: { event: EventSummary; showTime?: boolean }) {
  const project = event.projects[0]?.name;
  return (
    <button className="row" onClick={() => navigate(`/event/${event.id}`)}>
      {showTime && <span className="time">{whenLabel(event)}</span>}
      <span className="mark">{TYPE_MARKS[event.event_type] ?? "•"}</span>
      <span className="label">
        {event.title}
        {project && <span className="sub">{project}</span>}
      </span>
      <span className="value">{eventValue(event)}</span>
    </button>
  );
}

// --- clarifications ----------------------------------------------------------------------------

export function ClarificationCard({ item, onAnswered }: { item: Clarification; onAnswered: (message: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function answer(body: { option_id?: string; value?: string }) {
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ message: string }>(`/v1/clarifications/${item.id}/answer`, { method: "POST", body });
      onAnswered(result.message);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save that. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function dismiss() {
    setBusy(true);
    await api(`/v1/clarifications/${item.id}/dismiss`, { method: "POST" }).catch(() => undefined);
    onAnswered("Okay, skipped.");
  }

  return (
    <div className="question">
      <p>{item.question}</p>
      {item.answer_type === "amount" ? (
        <div className="chips">
          <input
            className="field"
            inputMode="decimal"
            placeholder="Amount"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            style={{ flex: 1, minWidth: 0 }}
          />
          <button className="chip primary" disabled={busy || !amount} onClick={() => answer({ value: amount })}>
            Save
          </button>
        </div>
      ) : (
        <div className="chips">
          {item.options.map((option) => (
            <button key={option.id} className="chip" disabled={busy} onClick={() => answer({ option_id: option.id })}>
              {option.label}
            </button>
          ))}
        </div>
      )}
      <div style={{ marginTop: 10 }}>
        <button className="faint" onClick={dismiss} disabled={busy}>
          Skip
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

// --- capture -----------------------------------------------------------------------------------

type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
};

function speechRecognition(): (new () => Recognition) | null {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  if (!window.isSecureContext) return null;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function understoodLines(result: CaptureResult): string[] {
  const lines = result.events_created.map((e) => [e.title, eventValue(e)].filter(Boolean).join(" — "));
  result.events_updated.forEach((u) => lines.push(`${u.event.title} — updated ${u.changes.join(", ")}`));
  result.events_deleted.forEach((d) => lines.push(`${d.title} — removed`));
  result.tasks_created.forEach((t) => lines.push(`Task: ${t.title}${t.due_date ? ` (due ${t.due_date})` : ""}`));
  result.tasks_completed?.forEach((t) => lines.push(`Task done: ${t.title}`));
  return lines;
}

const DRAFT_KEY = "pos.capture-draft";

function readDraft(): string {
  try {
    return localStorage.getItem(DRAFT_KEY) ?? "";
  } catch {
    return "";
  }
}

function writeDraft(text: string): void {
  try {
    if (text) localStorage.setItem(DRAFT_KEY, text);
    else localStorage.removeItem(DRAFT_KEY);
  } catch {
    /* storage unavailable: the draft lasts while the sheet is open */
  }
}

export function CaptureSheet({ onClose, onSaved, language }: { onClose: () => void; onSaved: () => void; language: string }) {
  const [text, setTextState] = useState(readDraft);
  const setText = (value: string) => {
    setTextState(value);
    writeDraft(value);
  };
  const [listening, setListening] = useState(false);
  const [usedVoice, setUsedVoice] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CaptureResult | null>(null);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answered, setAnswered] = useState<string[]>([]);
  const [slow, setSlow] = useState(false);
  const recognition = useRef<Recognition | null>(null);
  const base = useRef("");
  const savedRef = useRef(onSaved);
  savedRef.current = onSaved;
  const Speech = speechRecognition();

  useEffect(() => () => recognition.current?.stop(), []);

  // Saved at once; the understanding arrives afterwards. Follow it while the sheet is open
  // (Home shows it too, so closing the sheet loses nothing).
  const following = result && stillWorking(result) ? result.capture.id : null;
  useEffect(() => {
    if (!following) return;
    const stop = new AbortController();
    setSlow(false);
    const onUpdate = (latest: CaptureResult) => {
      setResult(latest);
      if (!stillWorking(latest)) savedRef.current(); // Home shows the new entries
    };
    followCapture(following, { onUpdate, signal: stop.signal }).then((done) => {
      if (!done && !stop.signal.aborted) setSlow(true);
    });
    return () => stop.abort();
  }, [following]);

  function startOver() {
    setResult(null);
    setText("");
    setUsedVoice(false);
    setAnswered([]);
    setSlow(false);
  }

  function toggleMic() {
    if (!Speech) return;
    if (listening) {
      recognition.current?.stop();
      return;
    }
    const rec = new Speech();
    rec.lang = language === "fr" ? "fr-FR" : language === "ar" ? "ar-MA" : navigator.language || "en-US";
    rec.continuous = true;
    rec.interimResults = true;
    base.current = text ? `${text.trim()} ` : "";
    rec.onresult = (event) => {
      let spoken = "";
      for (let i = 0; i < event.results.length; i++) spoken += event.results[i][0].transcript;
      setText(base.current + spoken);
    };
    rec.onend = () => setListening(false);
    rec.onerror = (event) => {
      setListening(false);
      if (event.error === "not-allowed") setError("Microphone access was blocked. Use the keyboard mic instead.");
    };
    recognition.current = rec;
    rec.start();
    setListening(true);
    setUsedVoice(true);
  }

  async function submit() {
    recognition.current?.stop();
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await sendCapture(text.trim(), usedVoice ? "VOICE" : "TEXT");
      writeDraft(""); // it is on the server or in the send queue now
      if (saved === null) setOffline(true);
      else setResult(saved);
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't send that.");
    } finally {
      setBusy(false);
    }
  }

  if (offline) {
    return (
      <Sheet title="Saved for later" onClose={onClose}>
        <div className="card reply">I can't reach your system right now. I kept your entry on this phone and will send it automatically.</div>
      </Sheet>
    );
  }

  if (result && stillWorking(result)) {
    return (
      <Sheet title="Saved" onClose={onClose}>
        <div className="card" role="status">
          <div className="reply working">
            <span className="spinner" aria-hidden="true" />
            <span>{slow ? "Still working on it. It's saved, and it'll show on Home when it's ready." : result.message}</span>
          </div>
          <p className="faint working-hint">You can close this or keep going; it'll show on Home.</p>
        </div>
        <div className="stack" style={{ marginTop: 16 }}>
          <button className="button secondary" onClick={startOver}>
            Tell me something else
          </button>
        </div>
      </Sheet>
    );
  }

  if (result) {
    const lines = understoodLines(result);
    const open = result.clarifications.filter((c) => !answered.includes(c.id));
    return (
      <Sheet title={result.error ? "Not processed yet" : "Saved"} onClose={onClose}>
        <div className="card">
          <div className="reply">{result.error ? result.message : result.answer?.text ?? (lines.length ? "I understood:" : result.message)}</div>
          {lines.length > 0 && (
            <ul className="understood">
              {lines.map((line, index) => (
                <li key={index}>{line}</li>
              ))}
            </ul>
          )}
        </div>
        {result.warnings.length > 0 && (
          <p className="faint" style={{ margin: "12px 4px" }}>
            {result.warnings.join(" ")}
          </p>
        )}
        {open.map((item) => (
          <div className="card" key={item.id} style={{ marginTop: 12 }}>
            <ClarificationCard
              item={item}
              onAnswered={() => {
                setAnswered((ids) => [...ids, item.id]);
                onSaved();
              }}
            />
          </div>
        ))}
        <div className="stack" style={{ marginTop: 16 }}>
          <button className="button secondary" onClick={startOver}>
            Tell me something else
          </button>
        </div>
      </Sheet>
    );
  }

  return (
    <Sheet title="Tell your system" onClose={onClose}>
      <div className="stack">
        <textarea
          className="field"
          autoFocus
          placeholder="I studied AI for two hours, worked on my project, spent 25 on lunch…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        {Speech ? (
          <>
            <button className={`mic ${listening ? "on" : ""}`} onClick={toggleMic} aria-label={listening ? "Stop" : "Speak"}>
              <span className="core" />
            </button>
            <p className="faint" style={{ textAlign: "center", margin: 0 }}>
              {listening ? "Listening… tap to stop" : "Tap to speak"}
            </p>
          </>
        ) : (
          <p className="faint" style={{ textAlign: "center" }}>
            Tip: tap the 🎙 on your keyboard to dictate.
          </p>
        )}
        {error && <p className="error">{error}</p>}
        <button className="button" disabled={busy || !text.trim()} onClick={submit}>
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
    </Sheet>
  );
}
