/**
 * Login — PLAN SEVEN.
 *
 * Shown full-screen whenever the security gate is active and there is no
 * session. Email + password against the backend's SuperTokens routes
 * (/api/auth/signin, /api/auth/signup) via the Auth context. POC note: a
 * self-service sign-up creates an account with NO roles — it sees only
 * unclassified documents until an admin grants a role.
 */

import { useState, type FormEvent } from "react";
import { useAuth } from "../contexts/Auth";

export function Login() {
  const { login, signup } = useAuth();
  const [isSignup, setIsSignup] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await (isSignup ? signup(email, password) : login(email, password));
      // Success → AuthProvider state flips and the App shell renders.
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const input: React.CSSProperties = {
    width: "100%",
    padding: "10px 12px",
    borderRadius: 8,
    border: "1px solid var(--border, #d1d5db)",
    background: "var(--card-bg, #fff)",
    color: "var(--text, #111)",
    fontSize: 14,
    boxSizing: "border-box",
  };

  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg, #f3f4f6)",
      }}
    >
      <form
        onSubmit={submit}
        style={{
          width: 360,
          padding: "32px 28px",
          borderRadius: 12,
          background: "var(--surface, #fff)",
          border: "1px solid var(--border, #e5e7eb)",
          boxShadow: "0 10px 30px rgba(0,0,0,0.08)",
        }}
      >
        <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 2 }}>
          Hyperlink Engine
        </div>
        <div style={{ fontSize: 12, color: "var(--text-muted, #6b7280)", marginBottom: 20 }}>
          🔐 Security gate is on — sign in to continue. All data stays on-prem.
        </div>

        <label style={{ display: "block", fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
          Email
        </label>
        <input
          style={{ ...input, marginBottom: 12 }}
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />

        <label style={{ display: "block", fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
          Password
        </label>
        <input
          style={{ ...input, marginBottom: 16 }}
          type="password"
          autoComplete={isSignup ? "new-password" : "current-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          minLength={8}
          required
        />

        {error && (
          <div
            style={{
              marginBottom: 12,
              padding: "8px 10px",
              borderRadius: 6,
              fontSize: 12,
              color: "#991b1b",
              background: "#fef2f2",
              border: "1px solid #fecaca",
            }}
          >
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={busy}
          style={{
            width: "100%",
            padding: "10px 0",
            borderRadius: 8,
            border: "none",
            cursor: busy ? "wait" : "pointer",
            fontSize: 14,
            fontWeight: 600,
            color: "#fff",
            background: "var(--primary, #2563eb)",
            opacity: busy ? 0.7 : 1,
          }}
        >
          {busy ? "…" : isSignup ? "Create account" : "Sign in"}
        </button>

        <div style={{ marginTop: 14, fontSize: 12, textAlign: "center" }}>
          {isSignup ? "Already have an account?" : "No account yet?"}{" "}
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              setError("");
              setIsSignup((v) => !v);
            }}
          >
            {isSignup ? "Sign in" : "Sign up"}
          </a>
        </div>

        {isSignup && (
          <div style={{ marginTop: 10, fontSize: 11, color: "var(--text-muted, #6b7280)", lineHeight: 1.5 }}>
            New accounts start with no clearance — you'll see unclassified
            documents only until an administrator grants you a role.
          </div>
        )}
      </form>
    </div>
  );
}
