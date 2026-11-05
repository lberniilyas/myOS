import { useState } from "react";

import { api, ApiError, saveTokens } from "../api";

export function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("MAD");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body =
        mode === "login"
          ? { email, password, device_name: "iPhone web app" }
          : {
              email,
              password,
              name: name || null,
              timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
              default_currency: currency.trim().toUpperCase() || null,
              device_name: "iPhone web app",
            };
      const tokens = await api<{ access_token: string; refresh_token: string }>(`/v1/auth/${mode}`, {
        method: "POST",
        body,
        auth: false,
      });
      saveTokens(tokens);
      onSignedIn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Can't reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app" style={{ paddingBottom: 40 }}>
      <div style={{ marginTop: "12vh" }}>
        <div className="eyebrow">Personal OS</div>
        <h1>{mode === "login" ? "Welcome back." : "Create your system."}</h1>
        <p className="muted" style={{ marginTop: -8 }}>
          Tell it what happened. It structures, connects and learns.
        </p>
      </div>
      <form className="stack" onSubmit={submit} style={{ marginTop: 28 }}>
        {mode === "register" && (
          <input className="field" placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} />
        )}
        <input
          className="field"
          type="email"
          autoComplete="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <input
          className="field"
          type="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          placeholder={mode === "login" ? "Password" : "Password (10+ characters)"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {mode === "register" && (
          <input
            className="field"
            placeholder="Usual currency (e.g. MAD)"
            value={currency}
            maxLength={3}
            onChange={(e) => setCurrency(e.target.value)}
          />
        )}
        {error && <p className="error">{error}</p>}
        <button className="button" disabled={busy}>
          {busy ? "One moment…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
      </form>
      <p style={{ textAlign: "center", marginTop: 20 }}>
        <button className="link" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "New here? Create an account" : "Already have an account? Sign in"}
        </button>
      </p>
    </div>
  );
}
