import type { CaptureResult } from "./types";

const TOKENS_KEY = "pos.tokens";

type Tokens = { access_token: string; refresh_token: string };

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function readTokens(): Tokens | null {
  try {
    const raw = localStorage.getItem(TOKENS_KEY);
    return raw ? (JSON.parse(raw) as Tokens) : null;
  } catch {
    return null;
  }
}

export function saveTokens(tokens: Tokens | null): void {
  try {
    if (tokens) localStorage.setItem(TOKENS_KEY, JSON.stringify({ access_token: tokens.access_token, refresh_token: tokens.refresh_token }));
    else localStorage.removeItem(TOKENS_KEY);
  } catch {
    /* storage unavailable: the session lasts until the page closes */
  }
}

export const isSignedIn = (): boolean => readTokens() !== null;

type RefreshOutcome = "renewed" | "refused" | "unreachable";
let refreshing: Promise<RefreshOutcome> | null = null;

/** Renew the session. Only a refresh token the server refuses ends it: a dropped connection,
 * a sleeping server or a 5xx leaves the person signed in, to try again later. */
async function refresh(): Promise<RefreshOutcome> {
  const tokens = readTokens();
  if (!tokens) return "refused";
  refreshing ??= fetch("/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: tokens.refresh_token }),
  })
    .then(async (response): Promise<RefreshOutcome> => {
      if (response.ok) {
        saveTokens(await response.json());
        return "renewed";
      }
      if (response.status === 401) {
        saveTokens(null);
        return "refused";
      }
      return "unreachable";
    })
    .catch((): RefreshOutcome => "unreachable")
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export async function api<T>(path: string, options: { method?: string; body?: unknown; auth?: boolean } = {}): Promise<T> {
  const { method = "GET", body, auth = true } = options;
  const send = () => {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const tokens = readTokens();
    if (auth && tokens) headers.Authorization = `Bearer ${tokens.access_token}`;
    return fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  };
  let response = await send();
  if (response.status === 401 && auth) {
    const outcome = await refresh();
    if (outcome === "renewed") response = await send();
    else if (outcome === "unreachable") throw new ApiError(503, "UNREACHABLE", "Can't reach your system right now.");
  }
  if (response.status === 401 && auth) {
    saveTokens(null);
    window.dispatchEvent(new Event("pos:signed-out"));
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = data?.error ?? {};
    throw new ApiError(response.status, error.code ?? "HTTP_ERROR", error.message ?? "Something went wrong.");
  }
  return data as T;
}

// --- offline capture queue -----------------------------------------------------------------

const QUEUE_KEY = "pos.pending-captures";
// The server replies as soon as the words are stored and understands them afterwards. Hosts
// that can't work after replying (serverless) ignore the flag and reply in full.
const CAPTURE_URL = "/v1/captures?background=true";

export type PendingCapture = { client_capture_id: string; content: string; input_type: "TEXT" | "VOICE"; captured_at: string };

export function pendingCaptures(): PendingCapture[] {
  try {
    return JSON.parse(localStorage.getItem(QUEUE_KEY) ?? "[]") as PendingCapture[];
  } catch {
    return [];
  }
}

function writeQueue(items: PendingCapture[]): void {
  try {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(items));
  } catch {
    /* ignore */
  }
}

/** A random v4 UUID. crypto.randomUUID only exists over HTTPS; getRandomValues also works on plain http. */
function newCaptureId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function dequeue(id: string): void {
  writeQueue(pendingCaptures().filter((p) => p.client_capture_id !== id));
}

// Sending again later can still work after these: signed out, timeouts, rate limits, server
// or proxy errors (a 502 when the server is down). Other errors (e.g. 422) never will.
function worthRetrying(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true; // network failure
  return error.status === 401 || error.status === 408 || error.status === 429 || error.status >= 500;
}

/**
 * Send a capture. It stays in the local queue until the server has it for good, so a network
 * failure, a server error or a busy AI never loses it; the queue resends it with the same id.
 * Once stored, the server finishes it (and retries a busy AI) by itself.
 * Returns null when it is kept for later without any reply from the server.
 */
export async function sendCapture(content: string, inputType: "TEXT" | "VOICE"): Promise<CaptureResult | null> {
  const item: PendingCapture = {
    client_capture_id: newCaptureId(),
    content,
    input_type: inputType,
    captured_at: new Date().toISOString(),
  };
  writeQueue([...pendingCaptures(), item]);
  try {
    const result = await api<CaptureResult>(CAPTURE_URL, { method: "POST", body: item });
    if (!result.error?.retryable) dequeue(item.client_capture_id);
    return result;
  } catch (error) {
    if (worthRetrying(error)) return null;
    dequeue(item.client_capture_id);
    throw error;
  }
}

let flushing: Promise<number> | null = null;

/** Resend queued captures in order; stops at the first one that still can't go through. */
export function flushQueue(): Promise<number> {
  flushing ??= (async () => {
    let sent = 0;
    for (const item of pendingCaptures()) {
      try {
        const result = await api<CaptureResult>(CAPTURE_URL, { method: "POST", body: item });
        if (result.error?.retryable) break;
        sent += 1;
      } catch (error) {
        if (worthRetrying(error)) break;
      }
      dequeue(item.client_capture_id);
    }
    return sent;
  })().finally(() => {
    flushing = null;
  });
  return flushing;
}

// --- following a capture the server is still understanding --------------------------------

/** The server has the words and is still working on them: understanding them now, or
 * waiting to try a busy AI again. */
export function stillWorking(result: CaptureResult): boolean {
  const { status, will_retry } = result.capture;
  return status === "CAPTURED" || status === "PROCESSING" || (status === "FAILED" && will_retry === true);
}

const pause = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });

/**
 * Ask about a saved capture until the server is done with it, passing each new state to
 * onUpdate. Resolves with the final result, or null if it is still being worked on after
 * `forMs`, the wait was cancelled, or the capture is gone. A dropped connection only means
 * asking again at the next turn.
 */
export async function followCapture(
  id: string,
  { onUpdate, signal, everyMs = 1500, forMs = 180_000 }: { onUpdate: (result: CaptureResult) => void; signal?: AbortSignal; everyMs?: number; forMs?: number },
): Promise<CaptureResult | null> {
  const deadline = Date.now() + forMs;
  while (!signal?.aborted && Date.now() < deadline) {
    await pause(everyMs, signal);
    if (signal?.aborted) break;
    try {
      const result = await api<CaptureResult>(`/v1/captures/${id}`);
      if (signal?.aborted) break;
      onUpdate(result);
      if (!stillWorking(result)) return result;
    } catch (error) {
      if (error instanceof ApiError && (error.status === 404 || error.status === 401)) return null;
    }
  }
  return null;
}
