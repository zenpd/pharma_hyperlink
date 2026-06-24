/**
 * Screen: Review Queue (HITL — Human In The Loop)
 *
 * Stage 2 of the architecture:
 *   Hyperlinked docs → Compliance Officer reviews → Approve / Reject
 *
 * Shows all completed pipeline runs.
 * Reviewer can approve (advances to Compliance Gate) or reject (comments required).
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import type { ReviewRun, ReviewStatus } from "../types";

interface Props {
  onBack: () => void;
  onGoToCompliance: (runId: string) => void;
}

function statusBadge(s: ReviewStatus) {
  const map: Record<ReviewStatus, { label: string; color: string; bg: string }> = {
    pending_review: { label: "Pending Review", color: "#f59e0b", bg: "rgba(245,158,11,0.1)" },
    approved:       { label: "Approved",        color: "var(--success)", bg: "var(--success-bg, rgba(34,197,94,0.1))" },
    rejected:       { label: "Rejected",        color: "var(--danger)", bg: "rgba(239,68,68,0.1)" },
    submitted:      { label: "Submitted",       color: "#6366f1", bg: "rgba(99,102,241,0.1)" },
  };
  const s2 = map[s] ?? map.pending_review;
  return (
    <span style={{
      display: "inline-block", padding: "2px 10px", borderRadius: 10,
      fontSize: 11, fontWeight: 600, color: s2.color, background: s2.bg,
    }}>
      {s2.label}
    </span>
  );
}

function gradeColor(g: string) {
  if (g === "A") return "var(--success)";
  if (g === "B") return "#f59e0b";
  return "var(--danger)";
}

export function ReviewQueue({ onBack, onGoToCompliance }: Props) {
  const [runs, setRuns] = useState<ReviewRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [rejectTarget, setRejectTarget] = useState<string | null>(null);
  const [rejectComment, setRejectComment] = useState("");
  const [busy, setBusy] = useState<string | null>(null); // run_id being actioned

  function loadQueue() {
    setLoading(true);
    api.review.queue()
      .then((data) => { setRuns(data.runs); setLoading(false); })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "Unknown error");
        setLoading(false);
      });
  }

  useEffect(() => { loadQueue(); }, []);

  async function handleApprove(runId: string) {
    setBusy(runId);
    try {
      await api.review.approve(runId, "Approved by compliance officer");
      setRuns((prev) => prev.map((r) => r.run_id === runId ? { ...r, review_status: "approved" } : r));
    } catch (e) {
      alert(`Approve failed: ${e instanceof Error ? e.message : e}`);
    } finally {
      setBusy(null);
    }
  }

  async function handleReject(runId: string) {
    if (!rejectComment.trim()) {
      alert("Please enter a rejection reason.");
      return;
    }
    setBusy(runId);
    try {
      await api.review.reject(runId, rejectComment.trim());
      setRuns((prev) => prev.map((r) => r.run_id === runId
        ? { ...r, review_status: "rejected", review_comment: rejectComment.trim() }
        : r));
      setRejectTarget(null);
      setRejectComment("");
    } catch (e) {
      alert(`Reject failed: ${e instanceof Error ? e.message : e}`);
    } finally {
      setBusy(null);
    }
  }

  const pending = runs.filter((r) => r.review_status === "pending_review");
  const actioned = runs.filter((r) => r.review_status !== "pending_review");

  return (
    <div className="page">
      <button className="back-btn" onClick={onBack}>← Back to Dashboard</button>

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
        <div className="page-title" style={{ margin: 0 }}>🔍 Review Queue</div>
        {pending.length > 0 && (
          <span style={{
            padding: "2px 10px", borderRadius: 10, fontSize: 12, fontWeight: 700,
            background: "rgba(245,158,11,0.15)", color: "#b45309",
          }}>
            {pending.length} pending
          </span>
        )}
        <button
          className="btn-ghost btn-sm"
          style={{ marginLeft: "auto" }}
          onClick={loadQueue}
        >
          ↻ Refresh
        </button>
      </div>
      <div className="page-subtitle">
        Stage 2: Compliance officer reviews hyperlinked output before FDA/eCTD compliance check.
      </div>

      {loading && (
        <div className="center-state">
          <div className="spinner" />
          <h3>Loading review queue…</h3>
        </div>
      )}

      {error && (
        <div className="error-msg">
          <strong>Failed to load review queue</strong>
          {error}
        </div>
      )}

      {!loading && !error && runs.length === 0 && (
        <div className="center-state">
          <div style={{ fontSize: 48, marginBottom: 12 }}>📭</div>
          <h3>No runs in review queue</h3>
          <p>Run the pipeline first, then completed runs appear here.</p>
          <button className="btn-primary" onClick={onBack}>← Go to Pipeline</button>
        </div>
      )}

      {/* ── Pending section ── */}
      {pending.length > 0 && (
        <>
          <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", margin: "20px 0 10px" }}>
            Awaiting Review ({pending.length})
          </div>
          {pending.map((run) => (
            <div key={run.run_id} className="card" style={{ padding: "16px 20px", marginBottom: 12 }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
                {/* Left: metadata */}
                <div style={{ flex: 1, minWidth: 200 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                    {statusBadge(run.review_status)}
                    <span style={{ fontFamily: "monospace", fontSize: 12, color: "var(--text-muted)" }}>
                      {run.run_id}
                    </span>
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
                    {run.dossier_id}
                  </div>
                  <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
                    <div>
                      <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}>Score</div>
                      <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "monospace", color: gradeColor(run.grade) }}>
                        {run.score?.toFixed(1)}
                        <span style={{ fontSize: 12, marginLeft: 4 }}>({run.grade})</span>
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}>Links</div>
                      <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "monospace" }}>{run.total_links}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}>Broken</div>
                      <div style={{
                        fontSize: 18, fontWeight: 700, fontFamily: "monospace",
                        color: run.broken_links > 0 ? "var(--danger)" : "var(--success)",
                      }}>
                        {run.broken_links}
                      </div>
                    </div>
                  </div>
                  {/* Linked files */}
                  <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {run.linked_files.slice(0, 5).map((f) => (
                      <span key={f} style={{
                        display: "inline-block", padding: "1px 8px", borderRadius: 4,
                        background: "var(--surface-sunken, rgba(0,0,0,0.04))",
                        fontFamily: "monospace", fontSize: 10,
                      }}>
                        📄 {f}
                      </span>
                    ))}
                    {run.linked_files.length > 5 && (
                      <span style={{ fontSize: 10, color: "var(--text-muted)" }}>+{run.linked_files.length - 5} more</span>
                    )}
                  </div>
                </div>

                {/* Right: actions */}
                <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 180 }}>
                  <button
                    className="btn-success"
                    disabled={busy === run.run_id}
                    onClick={() => handleApprove(run.run_id)}
                  >
                    {busy === run.run_id ? "⏳ Processing…" : "✓ Approve"}
                  </button>
                  <button
                    className="btn-ghost"
                    style={{ color: "var(--danger)", borderColor: "var(--danger)" }}
                    disabled={busy === run.run_id}
                    onClick={() => { setRejectTarget(run.run_id); setRejectComment(""); }}
                  >
                    ✕ Reject
                  </button>
                  <button
                    className="btn-outline btn-sm"
                    onClick={() => onGoToCompliance(run.run_id)}
                  >
                    🔬 Preview Compliance
                  </button>
                </div>
              </div>

              {/* Reject comment box */}
              {rejectTarget === run.run_id && (
                <div style={{ marginTop: 14, padding: "12px 16px", background: "rgba(239,68,68,0.06)", borderRadius: 8, border: "1px solid rgba(239,68,68,0.2)" }}>
                  <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: "var(--danger)" }}>
                    Rejection reason (required)
                  </div>
                  <textarea
                    rows={3}
                    value={rejectComment}
                    onChange={(e) => setRejectComment(e.target.value)}
                    placeholder="Describe why this run needs to be reprocessed…"
                    style={{
                      width: "100%", boxSizing: "border-box",
                      padding: "8px 10px", borderRadius: 6,
                      border: "1px solid var(--border-color)",
                      fontSize: 13, resize: "vertical",
                      background: "var(--card-bg)", color: "var(--text-primary)",
                    }}
                  />
                  <div className="btn-row" style={{ marginTop: 8 }}>
                    <button
                      className="btn-ghost btn-sm"
                      style={{ color: "var(--danger)" }}
                      disabled={busy === run.run_id}
                      onClick={() => handleReject(run.run_id)}
                    >
                      Confirm Rejection
                    </button>
                    <button className="btn-ghost btn-sm" onClick={() => setRejectTarget(null)}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </>
      )}

      {/* ── Actioned section ── */}
      {actioned.length > 0 && (
        <>
          <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", margin: "24px 0 10px" }}>
            Reviewed ({actioned.length})
          </div>
          {actioned.map((run) => (
            <div key={run.run_id} className="card" style={{ padding: "12px 18px", marginBottom: 8, opacity: 0.85 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                {statusBadge(run.review_status)}
                <span style={{ fontFamily: "monospace", fontSize: 12, color: "var(--text-muted)" }}>{run.run_id}</span>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{run.dossier_id}</span>
                <span style={{ fontFamily: "monospace", fontSize: 13, color: gradeColor(run.grade) }}>
                  {run.score?.toFixed(1)} ({run.grade})
                </span>
                {run.review_comment && (
                  <span style={{ fontSize: 11, color: "var(--text-muted)", fontStyle: "italic" }}>
                    "{run.review_comment}"
                  </span>
                )}
                {run.review_status === "approved" && (
                  <button
                    className="btn-primary btn-sm"
                    style={{ marginLeft: "auto" }}
                    onClick={() => onGoToCompliance(run.run_id)}
                  >
                    → Compliance Gate
                  </button>
                )}
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
