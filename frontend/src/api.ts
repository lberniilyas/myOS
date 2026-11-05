import type { CaptureResult } from "./types";

const TOKENS_KEY = "pos.tokens";

type Tokens = { access_token: string; refresh_token: string };

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
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

let refreshing: Promise<boolean> | null = null;

async function refresh(): Promise<boolean> {
  const tokens = readTokens();
  if (!tokens) return false;
  refreshing ??= fetch("/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: tokens.refresh_token }),
  })
    .then(async (response) => {
      if (!response.ok) {
        saveTokens(null);
        return false;
      }
      saveTokens(await response.json());
      return true;
    })
    .catch(() => false)
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
  if (response.status === 401 && auth && (await refresh())) response = await send();
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
 * Send a capture. It stays in the local queue until the server has processed it, so a network
 * failure, a server error or a busy AI never loses it; the queue resends it with the same id.
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
    const result = await api<CaptureResult>("/v1/captures", { method: "POST", body: item });
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
        const result = await api<CaptureResult>("/v1/captures", { method: "POST", body: item });
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
