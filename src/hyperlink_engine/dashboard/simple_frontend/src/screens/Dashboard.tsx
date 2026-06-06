import { useEffect, useState } from "react";
import { api } from "../api";
import type { Anomaly, Link, ScoreResponse } from "../types";

interface Props {
  onViewIssues: () => void;
  onViewComparison?: () => void;
  onViewDetectionTrace?: () => void;
}

type LoadState = "loading" | "error" | "done";

function scoreClass(score: number) {
  if (score >= 85) return "pass";
  if (score >= 60) return "warn";
  return "fail";
}

function statusLabel(s: ScoreResponse) {
  if (s.is_submission_ready) return "READY FOR SUBMISSION";
  if (s.score >= 60) return "NEEDS REVIEW";
  return "NOT READY";
}

export function Dashboard({ onViewIssues, onViewComparison, onViewDetectionTrace }: Props) {
  const [state, setState] = useState<LoadState>("loading");
  const [score, setScore] = useState<ScoreResponse | null>(null);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [links, setLinks] = useState<Link[]>([]);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState("");

  useEffect(() => {
    Promise.all([api.score(), api.anomalies(), api.links()])
      .then(([s, a, l]) => {
        setScore(s);
        setAnomalies(a);
        setLinks(l);
        setState("done");
        setLastUpdated(new Date().toLocaleTimeString());
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "Unknown error");
        setState("error");
      });
  }, []);

  if (state === "loading") {
    return (
      <div className="page">
        <div className="center-state">
          <div className="spinner" />
          <h3>Loading dashboard…</h3>
          <p>Fetching data from backend on localhost:8000</p>
        </div>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="page">
        <div className="error-msg">
          <strong>Backend Connection Error</strong>
          {error}
          <br />
          <small>
            Is FastAPI running? Try:{" "}
            <code>poetry run uvicorn src.hyperlink_engine.dashboard.api:app --reload</code>
          </small>
        </div>
        <button
          className="btn-primary"
          onClick={() => { setState("loading"); setError(""); }}
        >
          Retry
        </button>
      </div>
    );
  }

  if (!score) return null;

  const cls = scoreClass(score.score);
  const blockers = anomalies.filter((a) => a.severity === "blocker").length;
  const warnings = anomalies.filter((a) => a.severity === "warning").length;
  const infoCount = anomalies.filter((a) => a.severity === "info").length;
  const brokenLinks = links.filter((l) => l.status === "broken").length;
  const okLinks = links.filter((l) => l.status === "ok").length;

  return (
    <div className="page">
      {/* ── Score Card ── */}
      <div className="card">
        <div className="card-title">Submission Readiness</div>
        <div className="score-card">
          <div className={`score-circle ${cls}`}>
            <span className="score-num">{Math.round(score.score)}%</span>
            <span className="score-label">Score</span>
          </div>

          <div className="score-info">
            <div className={`status-badge ${cls}`}>
              {cls === "pass" ? "✅" : cls === "warn" ? "⚠️" : "❌"}
              {statusLabel(score)}
            </div>

            <p className="score-meta">Grade: <strong>{score.grade ?? "N/A"}</strong></p>
            <p className="score-meta">
              Broken Links: <strong style={{ color: score.broken_links > 0 ? "var(--danger)" : "var(--success)" }}>
                {score.broken_links}
              </strong>
            </p>
            <p className="score-meta">
              Blocker Anomalies: <strong style={{ color: score.blocker_anomalies > 0 ? "var(--danger)" : "var(--success)" }}>
                {score.blocker_anomalies}
              </strong>
            </p>
            <p className="score-meta" style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
              Last updated: {lastUpdated}
            </p>

            <div className="progress-wrap" style={{ marginTop: 12 }}>
              <div
                className={`progress-fill ${cls}`}
                style={{ width: `${score.score}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* ── Stats Row ── */}
      <div className="stats-row">
        <div className="stat-box">
          <div className="stat-num ok">{okLinks}</div>
          <div className="stat-label">Valid Links</div>
        </div>
        <div className="stat-box">
          <div className="stat-num block">{brokenLinks}</div>
          <div className="stat-label">Broken Links</div>
        </div>
        <div className="stat-box">
          <div className="stat-num block">{blockers}</div>
          <div className="stat-label">Blockers</div>
        </div>
        <div className="stat-box">
          <div className="stat-num warn">{warnings}</div>
          <div className="stat-label">Warnings</div>
        </div>
        <div className="stat-box">
          <div className="stat-num neutral">{infoCount}</div>
          <div className="stat-label">Info</div>
        </div>
        <div className="stat-box">
          <div className="stat-num neutral">{links.length}</div>
          <div className="stat-label">Total Links</div>
        </div>
      </div>

      {/* ── Quick Actions ── */}
      <div className="card">
        <div className="card-title">Actions</div>
        <div className="btn-row">
          <button className="btn-primary" onClick={onViewIssues}>
            🔍 View All Issues ({anomalies.length})
          </button>
          {onViewComparison && (
            <button className="btn-primary" onClick={onViewComparison}>
              📄 Compare Documents
            </button>
          )}
          {onViewDetectionTrace && (
            <button className="btn-primary" onClick={onViewDetectionTrace}>
              🔬 Detection Layer Trace
            </button>
          )}
          <button className="btn-success" onClick={api.exportCsv}>
            ⬇️ Download CSV
          </button>
          <button className="btn-success" onClick={api.exportXlsx}>
            ⬇️ Download XLSX
          </button>
          <button className="btn-ghost" onClick={() => window.print()}>
            🖨️ Print Report
          </button>
        </div>
      </div>

      {/* ── Top Issues Preview ── */}
      {anomalies.length > 0 && (
        <div className="card">
          <div className="card-title">
            Top Issues to Fix
            {blockers > 0 && (
              <span
                style={{
                  marginLeft: 8,
                  background: "var(--danger-bg)",
                  color: "var(--danger)",
                  fontSize: 11,
                  padding: "2px 7px",
                  borderRadius: 4,
                  fontWeight: 700,
                }}
              >
                {blockers} BLOCKER{blockers > 1 ? "S" : ""}
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
                </div>
                {a.suggested_fix && (
                  <div className="issue-suggestion">{a.suggested_fix}</div>
                )}
              </div>
            ))}
          </div>

          {anomalies.length > 3 && (
            <div style={{ marginTop: 14, textAlign: "center" }}>
              <button className="btn-outline" onClick={onViewIssues}>
                View all {anomalies.length} issues →
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── Link Table Preview ── */}
      {links.length > 0 && (
        <div className="card">
          <div className="card-title">Recent Links ({links.length} total)</div>
          <div style={{ overflowX: "auto" }}>
            <table className="link-table">
              <thead>
                <tr>
                  <th>Link Text</th>
                  <th>Source Document</th>
                  <th>Target</th>
                  <th>Status</th>
                  <th>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {links.slice(0, 5).map((l, i) => (
                  <tr key={i}>
                    <td style={{ fontWeight: 500 }}>{l.link_text}</td>
                    <td style={{ color: "var(--text-muted)" }}>{l.source_doc}</td>
                    <td style={{ color: "var(--text-muted)", fontSize: 12 }}>
                      {l.target_doc}
                      {l.target_anchor && <span style={{ color: "var(--primary)" }}> #{l.target_anchor}</span>}
                    </td>
                    <td>
                      <span className={`link-status ${l.status}`}>
                        {l.status.toUpperCase()}
                      </span>
                    </td>
                    <td>
                      <div className="conf-bar-wrap">
                        <div className="conf-bar-bg">
                          <div
                            className="conf-bar-fill"
                            style={{ width: `${Math.round(l.confidence * 100)}%` }}
                          />
                        </div>
                        <span className="conf-text">{Math.round(l.confidence * 100)}%</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {links.length > 5 && (
            <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 10, textAlign: "center" }}>
              Showing 5 of {links.length} links · Download CSV for full list
            </p>
          )}
        </div>
      )}
    </div>
  );
}
