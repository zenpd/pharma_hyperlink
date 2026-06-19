/**
 * Screen: Export Center  (Streamlit "_render_export" equivalent)
 *
 * CSV + XLSX download buttons, plus pipeline-run CSV downloads.
 * Matches Streamlit's two-column col1/col2 layout.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import { useActiveRun } from "../contexts/ActiveRun";
import type { RunSummary } from "../types";

interface Props { onBack: () => void; }

export function ExportCenter({ onBack }: Props) {
  const { activeRunId } = useActiveRun();
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(true);

  useEffect(() => {
    api.pipeline.listRuns()
      .then((data) => { setRuns((data.runs ?? []).filter((r) => r.status === "done")); setLoadingRuns(false); })
      .catch(() => setLoadingRuns(false));
  }, []);

  const doneRuns = runs.filter((r) => r.status === "done" && r.total_links > 0);

  return (
    <div className="page">
      <button className="back-btn" onClick={onBack}>← Back to Dashboard</button>
      <div className="page-title">⬇️ Export Center</div>
      <div className="page-subtitle">Download link reports in CSV or XLSX format.</div>

      {/* ── Main dossier export (Streamlit col1 / col2) ── */}
      <div className="card" style={{ padding: "20px 24px" }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
          {activeRunId ? `Run Report — ${activeRunId}` : "Dossier Report (demo)"}
        </div>
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 16 }}>
          {activeRunId
            ? "Full link inventory from the run selected above — all documents in this pipeline run."
            : "Full link inventory from the seeded demo dossier — all modules, all documents."}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
          <ExportCard
            icon="📄"
            title="Download CSV"
            description="Comma-separated · all link records · filterable in Excel"
            btnLabel="⬇️ Download CSV"
            mime="text/csv"
            onClick={() => api.exportCsv(activeRunId)}
            accentColor="#27AE60"
          />
          <ExportCard
            icon="📊"
            title="Download XLSX"
            description="Excel workbook · conditional formatting · pivot-ready"
            btnLabel="⬇️ Download XLSX"
            mime="xlsx"
            onClick={() => api.exportXlsx(activeRunId)}
            accentColor="#1A73E8"
          />
          <ExportCard
            icon="🖨️"
            title="Print Report"
            description="Browser print dialog · optimised print stylesheet"
            btnLabel="🖨️ Print"
            onClick={() => window.print()}
            accentColor="#6B7280"
          />
        </div>
      </div>

      {/* ── Pipeline run exports ── */}
      <div className="card" style={{ padding: "20px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600 }}>Pipeline Run Exports</div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
              Download validation reports from individual pipeline runs.
            </div>
          </div>
          {loadingRuns && <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2, marginLeft: "auto" }} />}
        </div>

        {!loadingRuns && doneRuns.length === 0 && (
          <div style={{ fontSize: 13, color: "var(--text-muted)", padding: "12px 0" }}>
            No completed runs yet. Run the pipeline first.
          </div>
        )}

        {doneRuns.map((run) => (
          <div key={run.run_id} style={{
            display: "flex", alignItems: "center", gap: 16,
            padding: "12px 0",
            borderBottom: "1px solid var(--border-color)",
            flexWrap: "wrap",
          }}>
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ fontFamily: "monospace", fontSize: 12, fontWeight: 600 }}>{run.run_id}</div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                {run.dossier_id} · {run.total_links} links
                {run.score != null && (
                  <span style={{ marginLeft: 6, fontWeight: 600, color: run.score >= 90 ? "var(--success)" : "#f59e0b" }}>
                    · Score {run.score.toFixed(1)} ({run.grade})
                  </span>
                )}
              </div>
              {/* Linked file chips */}
              <div style={{ marginTop: 6, display: "flex", gap: 4, flexWrap: "wrap" }}>
                {(run.linked_files ?? []).map((f) => (
                  <button
                    key={f}
                    className="btn-ghost btn-sm"
                    style={{ fontFamily: "monospace", fontSize: 10, padding: "2px 8px" }}
                    onClick={() => api.pipeline.downloadLinked(run.run_id, f)}
                  >
                    ⬇ {f}
                  </button>
                ))}
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                className="btn-success btn-sm"
                onClick={() => api.pipeline.downloadCsv(run.run_id)}
              >
                ⬇ Report CSV
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* ── Format info ── */}
      <div className="card" style={{ padding: "16px 20px" }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12 }}>File Format Details</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16 }}>
          {[
            {
              fmt: "CSV",
              cols: "source_doc, link_text, link_location_descriptor, target_doc, target_anchor, status, confidence, detected_by, error_msg",
              note: "UTF-8 encoded, compatible with Excel, pandas, R",
            },
            {
              fmt: "XLSX",
              cols: "Same columns + conditional formatting (red = broken, yellow = unverified)",
              note: "Requires Excel 2007+ or LibreOffice",
            },
          ].map((f) => (
            <div key={f.fmt} style={{
              padding: "12px 14px", borderRadius: 8,
              background: "var(--surface-sunken, rgba(0,0,0,0.03))",
              border: "1px solid var(--border-color)",
            }}>
              <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6, fontFamily: "monospace" }}>.{f.fmt.toLowerCase()}</div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4, lineHeight: 1.5 }}>
                <strong>Columns:</strong> {f.cols}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{f.note}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Export card component ──────────────────────────────────────────────────────

interface ExportCardProps {
  icon: string;
  title: string;
  description: string;
  btnLabel: string;
  mime?: string;
  onClick: () => void;
  accentColor: string;
}

function ExportCard({ icon, title, description, btnLabel, onClick, accentColor }: ExportCardProps) {
  return (
    <div style={{
      padding: "16px 18px", borderRadius: 10,
      border: `1px solid ${accentColor}30`,
      background: `${accentColor}08`,
      display: "flex", flexDirection: "column", gap: 10,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 24 }}>{icon}</span>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{title}</div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{description}</div>
        </div>
      </div>
      <button
        onClick={onClick}
        style={{
          padding: "8px 16px", borderRadius: 6, cursor: "pointer",
          background: accentColor, color: "#fff",
          border: "none", fontSize: 13, fontWeight: 600,
          width: "100%", transition: "opacity 0.15s",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.85")}
        onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
      >
        {btnLabel}
      </button>
    </div>
  );
}
