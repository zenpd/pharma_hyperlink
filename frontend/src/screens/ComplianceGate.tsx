/**
 * Screen: Compliance Gate
 *
 * Stage 3 of the architecture:
 *   Approved run → eCTD v4.0 checklist → Submit to domain-specific authority
 *
 * Authorities: FDA CDER, EMA, PMDA, Health Canada
 */

import { useEffect, useState } from "react";
import { ApiError, api } from "../api";
import type { ComplianceItem, ComplianceResult } from "../types";

interface Props {
  onBack: () => void;
  preselectedRunId?: string;
}

type AuthorityKey = "FDA_CDER" | "EMA" | "PMDA" | "HEALTH_CANADA";

const AUTHORITIES: { key: AuthorityKey; label: string; region: string; flag: string }[] = [
  { key: "FDA_CDER",      label: "FDA CDER (ESG)",        region: "US",     flag: "🇺🇸" },
  { key: "EMA",           label: "EMA (EUDRALINK)",        region: "EU",     flag: "🇪🇺" },
  { key: "PMDA",          label: "PMDA (Japan)",           region: "JP",     flag: "🇯🇵" },
  { key: "HEALTH_CANADA", label: "Health Canada",          region: "CA",     flag: "🇨🇦" },
];

function itemIcon(status: ComplianceItem["status"]) {
  if (status === "pass")     return { icon: "✓", color: "var(--success)" };
  if (status === "fail")     return { icon: "✕", color: "var(--danger)" };
  if (status === "warning")  return { icon: "⚠", color: "#f59e0b" };
  return                            { icon: "⏳", color: "var(--brand)" };
}

export function ComplianceGate({ onBack, preselectedRunId }: Props) {
  const [runId, setRunId] = useState(preselectedRunId ?? "");
  const [result, setResult] = useState<ComplianceResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ status?: number; text: string } | null>(null);
  const [authority, setAuthority] = useState<AuthorityKey>("FDA_CDER");
  const [submitting, setSubmitting] = useState(false);
  const [submitResult, setSubmitResult] = useState<{ reference_number: string } | null>(null);

  // Auto-load if a run_id was passed in
  useEffect(() => {
    if (preselectedRunId) {
      setRunId(preselectedRunId);
      runCheck(preselectedRunId);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preselectedRunId]);

  function runCheck(rid: string) {
    if (!rid.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setSubmitResult(null);
    api.compliance.check(rid.trim())
      .then((r) => { setResult(r); setLoading(false); })
      .catch((e: unknown) => {
        if (e instanceof ApiError) setError({ status: e.status, text: e.detail });
        else setError({ text: e instanceof Error ? e.message : "Unknown error" });
        setLoading(false);
      });
  }

  async function handleSubmit() {
    if (!result || !result.overall_pass) return;
    setSubmitting(true);
    try {
      const resp = await api.compliance.submit(runId, authority);
      setSubmitResult(resp);
    } catch (e) {
      alert(`Submission failed: ${e instanceof Error ? e.message : e}`);
    } finally {
      setSubmitting(false);
    }
  }

  const allPass = result?.overall_pass ?? false;
  const passCount = result?.items.filter((i) => i.status === "pass").length ?? 0;
  const failCount = result?.items.filter((i) => i.status === "fail").length ?? 0;
  const warnCount = result?.items.filter((i) => i.status === "warning").length ?? 0;

  return (
    <div className="page">
      <button className="back-btn" onClick={onBack}>← Back to Dashboard</button>
      <div className="page-title">🏛 Compliance Gate</div>
      <div className="page-subtitle">
        Stage 3: eCTD v4.0 readiness check before submission to regulatory authority.
      </div>

      {/* ── Run ID input ── */}
      <div className="card" style={{ padding: "16px 20px" }}>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <label style={{ fontSize: 12, color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
              Run ID (from completed pipeline run)
            </label>
            <input
              type="text"
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              placeholder="e.g. a1b2c3d4-..."
              style={{
                width: "100%", boxSizing: "border-box",
                padding: "8px 12px", borderRadius: 6,
                border: "1px solid var(--border-color)",
                fontSize: 13, fontFamily: "monospace",
                background: "var(--card-bg)", color: "var(--text-primary)",
              }}
            />
          </div>
          <button
            className="btn-primary"
            disabled={loading || !runId.trim()}
            onClick={() => runCheck(runId)}
          >
            {loading ? "⏳ Checking…" : "🔬 Run Compliance Check"}
          </button>
        </div>
      </div>

      {/* 403 — classified run, caller lacks clearance: dedicated lock card */}
      {error && error.status === 403 && (
        <div className="card" style={{
          padding: "36px 28px", textAlign: "center",
          background: "linear-gradient(135deg, rgba(239,68,68,0.06), transparent)",
          border: "1px solid rgba(239,68,68,0.25)",
        }}>
          <div style={{
            width: 64, height: 64, borderRadius: "50%", margin: "0 auto 14px",
            background: "rgba(239,68,68,0.1)",
            display: "grid", placeItems: "center", fontSize: 28,
          }}>
            🔒
          </div>
          <div style={{ fontSize: 17, fontWeight: 700, color: "var(--danger)" }}>
            Access Denied
          </div>
          <div style={{
            fontSize: 13, color: "var(--text-muted)",
            maxWidth: 440, margin: "8px auto 0", lineHeight: 1.6,
          }}>
            {error.text.toLowerCase().includes("classified")
              ? "This run is classified. Administrator clearance is required to view its compliance status."
              : error.text}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 16 }}>
            Signed in with the wrong account? Sign out from the header and log in as an administrator.
          </div>
        </div>
      )}

      {/* Any other failure (404, network, …) — compact error box */}
      {error && error.status !== 403 && (
        <div className="error-msg">
          <strong>Check failed</strong>
          {error.status === 404 ? `Run "${runId.trim()}" was not found — check the Run ID.` : error.text}
        </div>
      )}

      {loading && (
        <div className="center-state">
          <div className="spinner" />
          <h3>Running eCTD v4.0 compliance check…</h3>
          <p>Validating backbone, naming conventions, cross-references…</p>
        </div>
      )}

      {result && (
        <>
          {/* ── Summary banner ── */}
          <div className="card" style={{
            padding: "16px 24px",
            background: allPass
              ? "linear-gradient(135deg, rgba(34,197,94,0.08), rgba(34,197,94,0.02))"
              : "linear-gradient(135deg, rgba(239,68,68,0.08), rgba(239,68,68,0.02))",
            border: `1px solid ${allPass ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.2)"}`,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
              <div style={{ fontSize: 36 }}>{allPass ? "✅" : "❌"}</div>
              <div>
                <div style={{
                  fontSize: 16, fontWeight: 700,
                  color: allPass ? "var(--success)" : "var(--danger)",
                }}>
                  {allPass ? "eCTD v4.0 Compliant — Ready for Submission" : "Compliance Check Failed — Action Required"}
                </div>
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
                  {result.dossier_id} · {result.ectd_version} · checked {new Date(result.checked_at).toLocaleString()}
                </div>
              </div>
              <div style={{ marginLeft: "auto", display: "flex", gap: 20 }}>
                <div style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 22, fontWeight: 700, color: "var(--success)" }}>{passCount}</div>
                  <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}>Pass</div>
                </div>
                {warnCount > 0 && (
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: 22, fontWeight: 700, color: "#f59e0b" }}>{warnCount}</div>
                    <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}>Warn</div>
                  </div>
                )}
                {failCount > 0 && (
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: 22, fontWeight: 700, color: "var(--danger)" }}>{failCount}</div>
                    <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}>Fail</div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* ── Checklist ── */}
          <div className="card" style={{ padding: "16px 20px" }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 14 }}>eCTD v4.0 Checklist</div>
            {result.items.map((item) => {
              const { icon, color } = itemIcon(item.status);
              return (
                <div key={item.id} style={{
                  display: "flex", alignItems: "flex-start", gap: 12,
                  padding: "10px 0", borderBottom: "1px solid var(--border-color)",
                }}>
                  <div style={{
                    width: 26, height: 26, borderRadius: "50%",
                    background: item.status === "pass" ? "rgba(34,197,94,0.1)"
                      : item.status === "fail" ? "rgba(239,68,68,0.1)"
                      : item.status === "warning" ? "rgba(245,158,11,0.1)"
                      : "rgba(99,102,241,0.1)",
                    display: "grid", placeItems: "center",
                    fontSize: 13, flexShrink: 0, color,
                  }}>
                    {icon}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{item.label}</div>
                    <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>{item.description}</div>
                    {item.detail && (
                      <div style={{
                        marginTop: 4, padding: "4px 8px", borderRadius: 4,
                        background: "var(--surface-sunken, rgba(0,0,0,0.03))",
                        fontFamily: "monospace", fontSize: 11, color: "var(--text-muted)",
                      }}>
                        {item.detail}
                      </div>
                    )}
                  </div>
                  <div style={{ fontWeight: 600, fontSize: 12, color, flexShrink: 0 }}>
                    {item.status.toUpperCase()}
                  </div>
                </div>
              );
            })}
          </div>

          {/* ── Submit to authority (only if all pass) ── */}
          {allPass && !submitResult && (
            <div className="card" style={{ padding: "20px 24px" }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 16 }}>
                📤 Submit to Regulatory Authority
              </div>
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 20 }}>
                {AUTHORITIES.map((auth) => (
                  <button
                    key={auth.key}
                    onClick={() => setAuthority(auth.key)}
                    style={{
                      padding: "10px 16px", borderRadius: 8, cursor: "pointer",
                      border: `2px solid ${authority === auth.key ? "var(--brand)" : "var(--border-color)"}`,
                      background: authority === auth.key ? "rgba(99,102,241,0.08)" : "transparent",
                      fontSize: 13, fontWeight: authority === auth.key ? 600 : 400,
                      transition: "all 0.15s",
                      color: "var(--text-primary)",
                    }}
                  >
                    <div>{auth.flag} {auth.label}</div>
                    <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>{auth.region}</div>
                  </button>
                ))}
              </div>

              <div style={{
                padding: "12px 16px", borderRadius: 8, marginBottom: 16,
                background: "rgba(99,102,241,0.06)",
                border: "1px solid rgba(99,102,241,0.15)",
                fontSize: 12, color: "var(--text-muted)",
              }}>
                ℹ️ This will upload the hyperlinked dossier package to{" "}
                <strong style={{ color: "var(--text-primary)" }}>
                  {AUTHORITIES.find((a) => a.key === authority)?.label}
                </strong>.{" "}
                An electronic receipt number will be generated. This action is audit-logged and cannot be undone.
              </div>

              <button
                className="btn-primary"
                disabled={submitting}
                onClick={handleSubmit}
                style={{ fontSize: 14, padding: "10px 24px" }}
              >
                {submitting ? "⏳ Submitting…" : `📤 Submit to ${AUTHORITIES.find((a) => a.key === authority)?.label}`}
              </button>
            </div>
          )}

          {/* ── Submission success ── */}
          {submitResult && (
            <div className="card" style={{
              padding: "24px 28px",
              background: "linear-gradient(135deg, rgba(34,197,94,0.08), transparent)",
              border: "1px solid rgba(34,197,94,0.3)",
              textAlign: "center",
            }}>
              <div style={{ fontSize: 48, marginBottom: 12 }}>🎉</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: "var(--success)", marginBottom: 8 }}>
                Successfully Submitted!
              </div>
              <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 16 }}>
                Submitted to{" "}
                <strong>{AUTHORITIES.find((a) => a.key === authority)?.label}</strong>
              </div>
              <div style={{
                display: "inline-block", padding: "8px 16px", borderRadius: 8,
                background: "var(--surface-sunken, rgba(0,0,0,0.04))",
                fontFamily: "monospace", fontSize: 14, fontWeight: 700,
              }}>
                Reference: {submitResult.reference_number}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 12 }}>
                This submission has been recorded in the audit trail.
              </div>
            </div>
          )}
        </>
      )}

      {/* ── Empty state ── */}
      {!loading && !error && !result && (
        <div className="center-state" style={{ marginTop: 40 }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>🏛</div>
          <h3>Enter a Run ID above to check compliance</h3>
          <p>Or go to <strong>Review Queue</strong> and click "Compliance Gate" on an approved run.</p>
        </div>
      )}
    </div>
  );
}
