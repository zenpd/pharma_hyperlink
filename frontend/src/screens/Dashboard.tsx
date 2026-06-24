/**
 * Screen: Overview
 *
 * Clean Streamlit-style layout:
 *  - Score circle (CSS class, not SVG gauge)
 *  - Stats row: Total / OK / Broken / Suspicious / Unverified
 *  - Action buttons inline under the score
 *  - Top issues list
 *  - Recent links table
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import { useActiveRun } from "../contexts/ActiveRun";
import type { Anomaly, Link, ScoreResponse } from "../types";

interface Props {
  onViewIssues: () => void;
  onViewComparison?: () => void;
  onViewDetectionTrace?: () => void;
  onViewPipeline?: () => void;
}

type LoadState = "loading" | "error" | "done";

export function Dashboard({ onViewIssues, onViewComparison, onViewDetectionTrace, onViewPipeline }: Props) {
  const { activeRunId } = useActiveRun();
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [score, setScore]         = useState<ScoreResponse | null>(null);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [links, setLinks]         = useState<Link[]>([]);
  const [error, setError]         = useState("");
  const [lastUpdated, setLastUpdated] = useState("");

  function load() {
    setLoadState("loading");
    setError("");
    Promise.all([api.score(activeRunId), api.anomalies(activeRunId), api.links(activeRunId)])
      .then(([s, a, l]) => {
        setScore(s);
        setAnomalies(a);
        setLinks(l);
        setLoadState("done");
        setLastUpdated(new Date().toLocaleTimeString());
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "Unknown error");
        setLoadState("error");
      });
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [activeRunId]);

  if (loadState === "loading") {
    return (
      <div className="page">
        <div className="center-state">
          <div className="spinner" />
          <h3>Loading dashboard…</h3>
          <p>Fetching data from backend</p>
        </div>
      </div>
    );
  }

  if (loadState === "error") {
    return (
      <div className="page">
        <div className="error-msg">
          <strong>Backend Connection Error</strong>
          {error}
          <br />
          <small>
            Is FastAPI running? Try:{" "}
            <code>.venv\Scripts\uvicorn hyperlink_engine.dashboard.api:app --reload</code>
          </small>
        </div>
        <button className="btn-primary" onClick={load}>Retry</button>
      </div>
    );
  }

  if (!score) return null;

  const total        = links.length;
  const okLinks      = links.filter((l) => l.status === "ok").length;
  const brokenLinks  = links.filter((l) => l.status === "broken").length;
  const suspicious   = links.filter((l) => l.status === "suspicious").length;
  const unverified   = links.filter((l) => l.status === "unverified").length;
  const brokenRate   = total ? brokenLinks / total * 100 : 0;

  const computedScore = Math.max(
    0,
    100 - 5 * brokenRate - 2 * (suspicious + unverified) / Math.max(total, 1) * 100,
  );
  const displayScore = score.score || computedScore;

  const grade = displayScore >= 95 ? "A" : displayScore >= 85 ? "B" : displayScore >= 70 ? "C" : displayScore >= 55 ? "D" : "F";
  const tier  = displayScore >= 90 ? "pass" : displayScore >= 70 ? "warn" : "fail";

  const blockers = anomalies.filter((a) => a.severity === "blocker").length;
  const warnings  = anomalies.filter((a) => a.severity === "warning").length;

  return (
    <div className="page">
      <div className="page-title">Dossier Overview</div>
      <div className="page-subtitle">
        Submission readiness · Last updated: {lastUpdated}
        <button className="btn-ghost btn-sm" style={{ marginLeft: 8 }} onClick={load}>Refresh</button>
      </div>

      {/* Score card — circle + status badge + action buttons */}
      <div className="card">
        <div className="score-card">
          <div className={`score-circle ${tier}`}>
            <div className="score-num">{displayScore.toFixed(1)}</div>
            <div className="score-label">Grade {grade}</div>
          </div>
          <div className="score-info">
            <div className={`status-badge ${tier}`}>
              {tier === "pass" ? "Submission Ready" : tier === "warn" ? "Needs Review" : "Not Ready"}
            </div>
            <div className="score-meta">
              {total} links detected · {brokenLinks} broken · {unverified} unverified
            </div>
            <div className="btn-row" style={{ marginTop: 14 }}>
              {onViewPipeline && (
                <button className="btn-success btn-sm" onClick={onViewPipeline}>Run Pipeline</button>
              )}
              <button className="btn-primary btn-sm" onClick={onViewIssues}>
                Issues {anomalies.length > 0 && `(${anomalies.length})`}
              </button>
              {onViewComparison && (
                <button className="btn-ghost btn-sm" onClick={onViewComparison}>Compare Docs</button>
              )}
              {onViewDetectionTrace && (
                <button className="btn-ghost btn-sm" onClick={onViewDetectionTrace}>Detection Trace</button>
              )}
              <button className="btn-ghost btn-sm" onClick={() => api.exportCsv(activeRunId)}>Export CSV</button>
            </div>
          </div>
        </div>
      </div>

      {/* Stats row */}
      <div className="stats-row">
        <div className="stat-box">
          <div className="stat-num neutral">{total}</div>
          <div className="stat-label">Total Links</div>
        </div>
        <div className="stat-box">
          <div className="stat-num ok">{okLinks}</div>
          <div className="stat-label">OK</div>
        </div>
        <div className="stat-box">
          <div className="stat-num block">{brokenLinks}</div>
          <div className="stat-label">Broken</div>
        </div>
        <div className="stat-box">
          <div className="stat-num warn">{suspicious}</div>
          <div className="stat-label">Suspicious</div>
        </div>
        <div className="stat-box">
          <div className="stat-num warn">{unverified}</div>
          <div className="stat-label">Unverified</div>
        </div>
      </div>

      {/* Top issues */}
      {anomalies.length > 0 && (
        <div className="card">
          <div className="card-title">
            Top Issues
            {blockers > 0 && (
              <span style={{
                marginLeft: 8,
                background: "var(--danger-bg)", color: "var(--danger)",
                fontSize: 11, padding: "2px 7px", borderRadius: 4, fontWeight: 700,
              }}>
                {blockers} BLOCKER{blockers > 1 ? "S" : ""}
              </span>
            )}
            {warnings > 0 && (
              <span style={{
                marginLeft: 6,
                background: "var(--warning-bg)", color: "var(--warning)",
                fontSize: 11, padding: "2px 7px", borderRadius: 4, fontWeight: 600,
              }}>
                {warnings} warning{warnings > 1 ? "s" : ""}
              </span>
            )}
          </div>
          <div className="issue-list">
            {anomalies.slice(0, 3).map((a, i) => (
              <div key={i} className={`issue-card ${a.severity}`}>
                <div className="issue-header">
                  <span className={`sev-badge ${a.severity}`}>{a.severity}</span>
                  <span className="issue-title">{a.text}</span>
                </div>
                <div className="issue-meta">
                  <span>{a.document}</span>
                  <span>{a.kind.replace(/_/g, " ")}</span>
                  <span>Confidence: {Math.round(a.confidence * 100)}%</span>
                </div>
                {a.suggested_fix && (
                  <div className="issue-suggestion">{a.suggested_fix}</div>
                )}
              </div>
            ))}
          </div>
          {anomalies.length > 3 && (
            <div style={{ marginTop: 12, textAlign: "center" }}>
              <button className="btn-outline btn-sm" onClick={onViewIssues}>
                View all {anomalies.length} issues
              </button>
            </div>
          )}
        </div>
      )}

      {/* Recent links */}
      {links.length > 0 && (
        <div className="card">
          <div className="card-title">Recent Links (top 5 of {links.length})</div>
          <div style={{ overflowX: "auto" }}>
            <table className="link-table">
              <thead>
                <tr>
                  <th>Link Text</th>
                  <th>Source</th>
                  <th>Target</th>
                  <th>Status</th>
                  <th>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {links.slice(0, 5).map((l, i) => (
                  <tr key={i}>
                    <td style={{ fontWeight: 500 }}>{l.link_text}</td>
                    <td style={{ color: "var(--text-muted)", fontSize: 12 }}>{l.source_doc}</td>
                    <td style={{ color: "var(--text-muted)", fontSize: 12 }}>
                      {l.target_doc}
                      {l.target_anchor && (
                        <span style={{ color: "var(--primary)" }}> #{l.target_anchor}</span>
                      )}
                    </td>
                    <td>
                      <span className={`link-status ${l.status}`}>{l.status.toUpperCase()}</span>
                    </td>
                    <td style={{ fontSize: 12 }}>{Math.round(l.confidence * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {links.length > 5 && (
            <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 10, textAlign: "center" }}>
              Showing 5 of {links.length} total links
            </p>
          )}
        </div>
      )}
    </div>
  );
}
