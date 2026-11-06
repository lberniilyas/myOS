// Tests for the parts of the app that must never lose an entry or sign the person out by mistake.
// Run with: npm test (Node's built-in test runner; TypeScript types are stripped by Node).
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

class MemoryStorage {
  private items = new Map<string, string>();
  getItem(key: string) {
    return this.items.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.items.set(key, String(value));
  }
  removeItem(key: string) {
    this.items.delete(key);
  }
  clear() {
    this.items.clear();
  }
}

const storage = new MemoryStorage();
const page = new EventTarget();
Object.defineProperty(globalThis, "localStorage", { value: storage, configurable: true });
Object.defineProperty(globalThis, "window", { value: page, configurable: true });

type Call = { url: string; method: string; body: unknown; auth: string | null };
let calls: Call[] = [];
let reply: (call: Call) => Response | Promise<Response>;
globalThis.fetch = (async (input: string | URL | Request, init: RequestInit = {}) => {
  const headers = (init.headers ?? {}) as Record<string, string>;
  const call = {
    url: String(input),
    method: init.method ?? "GET",
    body: init.body ? JSON.parse(String(init.body)) : undefined,
    auth: headers.Authorization ?? null,
  };
  calls.push(call);
  return reply(call);
}) as typeof fetch;

const { api, ApiError, flushQueue, isSignedIn, pendingCaptures, saveTokens, sendCapture } = await import("../src/api.ts");

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const processed = (extra: object = {}) => json(200, { capture: { id: "c1" }, message: "Logged it.", error: null, ...extra });
const busyAi = () => processed({ error: { code: "AI_RATE_LIMITED", message: "busy", retryable: true } });
const networkDown = () => Promise.reject(new TypeError("Load failed"));
const captureCalls = () => calls.filter((c) => c.url === "/v1/captures");

let signedOut = 0;
page.addEventListener("pos:signed-out", () => {
  signedOut += 1;
});

beforeEach(() => {
  storage.clear();
  calls = [];
  signedOut = 0;
  saveTokens({ access_token: "access-1", refresh_token: "refresh-1" });
});

test("an entry stays queued when the network is down", async () => {
  reply = networkDown;
  assert.equal(await sendCapture("Studied AI", "TEXT"), null);
  assert.deepEqual(pendingCaptures().map((p) => p.content), ["Studied AI"]);
});

test("an entry stays queued when the server or its proxy fails (502)", async () => {
  reply = () => new Response("<h1>Bad gateway</h1>", { status: 502 });
  assert.equal(await sendCapture("Studied AI", "TEXT"), null);
  assert.equal(pendingCaptures().length, 1);
});

test("an entry stays queued while the AI is busy, and leaves once processed", async () => {
  reply = busyAi;
  const first = await sendCapture("Studied AI", "TEXT");
  assert.equal(first?.error?.code, "AI_RATE_LIMITED");
  assert.equal(pendingCaptures().length, 1);

  reply = () => processed();
  assert.equal(await flushQueue(), 1);
  assert.equal(pendingCaptures().length, 0);
  // The resend used the same id, so the server can't record it twice.
  const ids = captureCalls().map((c) => (c.body as { client_capture_id: string }).client_capture_id);
  assert.equal(new Set(ids).size, 1);
});

test("an entry the server will never accept is dropped and reported", async () => {
  reply = () => json(422, { error: { code: "VALIDATION_FAILED", message: "Some fields are invalid." } });
  await assert.rejects(sendCapture("x", "TEXT"), (error: unknown) => error instanceof ApiError && error.status === 422);
  assert.equal(pendingCaptures().length, 0);
});

test("the queue goes out in order, stops at the first failure and counts only real sends", async () => {
  reply = networkDown;
  await sendCapture("first", "TEXT");
  await sendCapture("second", "TEXT");
  await sendCapture("third", "TEXT");
  calls = [];
  let sent = 0;
  reply = () => (sent++ === 0 ? processed() : busyAi());
  assert.equal(await flushQueue(), 1);
  assert.deepEqual(pendingCaptures().map((p) => p.content), ["second", "third"]);
  assert.deepEqual(captureCalls().map((c) => (c.body as { content: string }).content), ["first", "second"]);
});

test("two flushes at once send each entry only once", async () => {
  reply = networkDown;
  await sendCapture("only once", "VOICE");
  calls = [];
  reply = () => processed();
  const [a, b] = await Promise.all([flushQueue(), flushQueue()]);
  assert.equal(a + b, 2); // both callers see the same single run
  assert.equal(captureCalls().length, 1);
});

test("entries get a valid id over plain http, where crypto.randomUUID is missing", async () => {
  const original = crypto.randomUUID;
  Object.defineProperty(crypto, "randomUUID", { value: undefined, configurable: true });
  try {
    reply = networkDown;
    await sendCapture("from the phone over http", "TEXT");
    assert.match(pendingCaptures()[0].client_capture_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  } finally {
    Object.defineProperty(crypto, "randomUUID", { value: original, configurable: true });
  }
});

test("an expired access token is renewed quietly and the request retried", async () => {
  reply = (call) => {
    if (call.url === "/v1/auth/refresh") return json(200, { access_token: "access-2", refresh_token: "refresh-2" });
    return call.auth === "Bearer access-2" ? json(200, { ok: true }) : json(401, { error: { code: "TOKEN_EXPIRED" } });
  };
  assert.deepEqual(await api("/v1/me"), { ok: true });
  assert.equal(signedOut, 0);
  assert.ok(isSignedIn());
});

for (const [name, failure] of [
  ["the network drops", () => networkDown()],
  ["the server is down", () => new Response("down", { status: 503 })],
  ["the server errors", () => json(500, { error: { code: "INTERNAL_ERROR" } })],
] as const) {
  test(`you stay signed in when renewing fails because ${name}`, async () => {
    reply = (call) => (call.url === "/v1/auth/refresh" ? failure() : json(401, { error: { code: "TOKEN_EXPIRED" } }));
    await assert.rejects(api("/v1/me"), (error: unknown) => error instanceof ApiError && error.code === "UNREACHABLE");
    assert.equal(signedOut, 0);
    assert.ok(isSignedIn(), "tokens must survive a failed renewal");
  });
}

test("only a refused session signs you out, and queued entries survive it", async () => {
  reply = networkDown;
  await sendCapture("written offline", "TEXT");
  reply = (call) => json(401, { error: { code: call.url === "/v1/auth/refresh" ? "SESSION_EXPIRED" : "TOKEN_EXPIRED" } });
  await flushQueue();
  assert.equal(signedOut, 1);
  assert.equal(isSignedIn(), false);
  assert.deepEqual(pendingCaptures().map((p) => p.content), ["written offline"]);
});
