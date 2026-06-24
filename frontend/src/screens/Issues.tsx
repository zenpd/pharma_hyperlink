import { useEffect, useState } from "react";
import { api } from "../api";
import { useActiveRun } from "../contexts/ActiveRun";
import type { Anomaly, SeverityFilter } from "../types";

interface Props {
  onBack: () => void;
}

type IssueState = Anomaly & { _id: string; _status: "open" | "fixed" | "ignored" };

export function Issues({ onBack }: Props) {
  const { activeRunId } = useActiveRun();
  const [issues, setIssues] = useState<IssueState[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<SeverityFilter>("all");

  useEffect(() => {
    setLoading(true);
    setError("");
    api
      .anomalies(activeRunId)
      .then((data) => {
        setIssues(
          data.map((a, i) => ({
            ...a,
            _id: `issue-${i}`,
            _status: "open" as const,
          }))
        );
        setLoading(false);
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "Unknown error");
        setLoading(false);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRunId]);

  const markFixed = (id: string) => {
    setIssues((prev) =>
      prev.map((i) => (i._id === id ? { ...i, _status: "fixed" } : i))
    );
  };

  const markIgnored = (id: string) => {
    setIssues((prev) =>
      prev.map((i) => (i._id === id ? { ...i, _status: "ignored" } : i))
    );
  };

  const markOpen = (id: string) => {
    setIssues((prev) =>
      prev.map((i) => (i._id === id ? { ...i, _status: "open" } : i))
    );
  };

  const visible = issues.filter((i) => {
    if (filter !== "all" && i.severity !== filter) return false;
    return true;
  });

  const counts = {
    all: issues.length,
    blocker: issues.filter((i) => i.severity === "blocker").length,
    warning: issues.filter((i) => i.severity === "warning").length,
    info: issues.filter((i) => i.severity === "info").length,
  };

  const fixed = issues.filter((i) => i._status === "fixed").length;
  const ignored = issues.filter((i) => i._status === "ignored").length;

  if (loading) {
    return (
      <div className="page">
        <button className="back-btn" onClick={onBack}>← Back to Dashboard</button>
        <div className="center-state">
          <div className="spinner" />
          <h3>Loading issues…</h3>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page">
        <button className="back-btn" onClick={onBack}>← Back to Dashboard</button>
        <div className="error-msg">
          <strong>Failed to load issues</strong>
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <button className="back-btn" onClick={onBack}>← Back to Dashboard</button>

      <div className="page-title">Issues & Anomalies</div>
      <div className="page-subtitle">
        Review and resolve detected issues before submission.{" "}
        {fixed > 0 && (
          <span style={{ color: "var(--success)", fontWeight: 600 }}>
            {fixed} fixed
          </span>
        )}
        {ignored > 0 && (
          <span style={{ color: "var(--text-muted)", marginLeft: 8 }}>
            {ignored} ignored
          </span>
        )}
      </div>

      {/* ── Progress ── */}
      {issues.length > 0 && (
        <div className="card" style={{ padding: "16px 24px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>
              Resolution progress
            </span>
            <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
              {fixed} / {issues.length} resolved
            </span>
          </div>
          <div className="progress-wrap" style={{ height: 8 }}>
            <div
              className="progress-fill pass"
              style={{ width: `${Math.round((fixed / issues.length) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* ── Filters ── */}
      <div className="filter-row">
        <span>Filter:</span>
        {(["all", "blocker", "warning", "info"] as SeverityFilter[]).map((f) => (
          <button
            key={f}
            className={`filter-btn ${filter === f ? `active-${f}` : ""}`}
            onClick={() => setFilter(f)}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)} ({counts[f]})
          </button>
        ))}
      </div>

      {/* ── Issue list ── */}
      {visible.length === 0 ? (
        <div className="center-state">
          <div className="icon">✅</div>
          <h3>No issues in this category</h3>
          <p>Try changing the filter or switching back to Dashboard.</p>
        </div>
      ) : (
        <div className="issue-list">
          {visible.map((issue) => (
            <div
              key={issue._id}
              className={`issue-card ${issue.severity} ${issue._status !== "open" ? issue._status : ""}`}
            >
              <div className="issue-header">
                <span className={`sev-badge ${issue.severity}`}>
                  {issue.severity}
                </span>
                <span className="issue-title">{issue.text}</span>
                {issue._status === "fixed" && (
                  <span
                    style={{
                      marginLeft: "auto",
                      fontSize: 11,
                      background: "var(--success-bg)",
                      color: "var(--success)",
                      padding: "2px 8px",
                      borderRadius: 4,
                      fontWeight: 700,
                    }}
                  >
                    ✓ FIXED
                  </span>
                )}
                {issue._status === "ignored" && (
                  <span
                    style={{
                      marginLeft: "auto",
                      fontSize: 11,
                      background: "var(--border)",
                      color: "var(--text-muted)",
                      padding: "2px 8px",
                      borderRadius: 4,
                      fontWeight: 700,
                    }}
                  >
                    IGNORED
                  </span>
                )}
              </div>

              <div className="issue-meta">
                <span>
                  📄 {issue.document}
                </span>
                <span>
                  🔖 {issue.kind.replace(/_/g, " ")}
                </span>
                <span>
                  Confidence: {Math.round(issue.confidence * 100)}%
                </span>
              </div>

              {issue.suggested_fix && (
                <div className="issue-suggestion">{issue.suggested_fix}</div>
              )}

              <div
                className="conf-bar-wrap"
                style={{ marginBottom: 12 }}
                title={`Detection confidence: ${Math.round(issue.confidence * 100)}%`}
              >
                <span style={{ fontSize: 11, color: "var(--text-muted)", minWidth: 70 }}>
                  Confidence
                </span>
                <div className="conf-bar-bg">
                  <div
                    className="conf-bar-fill"
                    style={{ width: `${Math.round(issue.confidence * 100)}%` }}
                  />
                </div>
                <span className="conf-text">
                  {Math.round(issue.confidence * 100)}%
                </span>
              </div>

              {issue._status === "open" ? (
                <div className="issue-actions">
                  <button
                    className="btn-success btn-sm"
                    onClick={() => markFixed(issue._id)}
                  >
                    ✓ Mark as Fixed
                  </button>
                  <button
                    className="btn-ghost btn-sm"
                    onClick={() => markIgnored(issue._id)}
                  >
                    Ignore
                  </button>
                </div>
              ) : (
                <div className="issue-actions">
                  <button
                    className="btn-ghost btn-sm"
                    onClick={() => markOpen(issue._id)}
                  >
                    ↩ Reopen
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Bottom actions ── */}
      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-title">Export Results</div>
        <div className="btn-row">
          <button className="btn-success" onClick={() => api.exportCsv(activeRunId)}>
            ⬇️ Download CSV
          </button>
          <button className="btn-success" onClick={() => api.exportXlsx(activeRunId)}>
            ⬇️ Download XLSX
          </button>
          <button className="btn-ghost" onClick={() => window.print()}>
            🖨️ Print
          </button>
          <button className="btn-outline" onClick={onBack}>
            ← Back to Dashboard
          </button>
        </div>
      </div>
    </div>
  );
}
