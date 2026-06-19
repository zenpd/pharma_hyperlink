/**
 * Screen 5 — Export & Submission Gate Center.  [LIVE]
 *
 * The format chooser drives real downloads (run-scoped or demo CSV/XLSX from
 * the backend). The bundle summary, readiness gauge, and the blocking-issues
 * list are all computed from live score / links / anomalies. The compliance
 * posture cards are static (they describe the deployment, not run data).
 */

import React from "react";
import { CtdCrumb, DossierBar, Icon, RadialGauge, TopBar } from "../components/shared";
import type { IconName } from "../components/shared";
import { useActiveRun } from "../contexts/ActiveRun";
import { anomalyCounts, statusCounts, useReportData } from "../live";
import { api } from "../api";

export interface ExportGateProps {
  theme?: "light" | "dark";
}

export const ExportGate: React.FC<ExportGateProps> = ({ theme = "light" }) => {
  const { activeRunId } = useActiveRun();
  const { score, links, anomalies, loading } = useReportData(activeRunId);

  const sc = statusCounts(links);
  const anc = anomalyCounts(anomalies);
  const readiness = Math.round(score?.score ?? 0);
  const grade = score?.grade ?? "—";
  const ready = score?.is_submission_ready ?? false;
  const broken = score?.broken_links ?? sc.broken;
  const blockers = score?.blocker_anomalies ?? anc.blocker;
  const docsCovered = new Set(links.map((l) => l.source_doc)).size;
  const dossierId = score?.dossier_id ?? "demo";

  // Live blocking issues — what stands between this dossier and submission.
  const blockingLinks = links.filter((l) => l.status === "broken").slice(0, 6);
  const blockingAnoms = anomalies.filter((a) => a.severity === "blocker").slice(0, 6);

  const formats: {
    name: string;
    desc: string;
    icon: IconName;
    onClick?: () => void;
    enabled: boolean;
  }[] = [
    {
      name: "CSV",
      desc: `Flat link inventory · all ${sc.total} rows`,
      icon: "file-text",
      onClick: () => api.exportCsv(activeRunId),
      enabled: true,
    },
    {
      name: "XLSX",
      desc: "Conditional formatting by severity (red/yellow status fills)",
      icon: "file",
      onClick: () => api.exportXlsx(activeRunId),
      enabled: true,
    },
    {
      name: "PDF",
      desc: "Management gate summary — coming from the reporting layer",
      icon: "file-text",
      enabled: false,
    },
  ];

  return (
    <div className={`hv-root ${theme === "dark" ? "theme-dark" : ""}`}>
      <TopBar theme={theme} activeTab="Reports" />
      <DossierBar
        right={
          <button className="btn btn-secondary btn-sm">
            <Icon name="history" size={12} /> Past exports
          </button>
        }
      >
        <Icon name="package" size={15} color="var(--text-2)" />
        <span style={{ fontWeight: 600 }}>{dossierId}</span>
        <div className="divider-v" style={{ height: 16, margin: "0 4px" }} />
        <CtdCrumb parts={["Dossier"]} current="Export & Gate Center" />
        <span className="mono chip outline">{activeRunId || "demo seed"}</span>
      </DossierBar>

      <div
        style={{
          flex: 1,
          padding: 20,
          display: "grid",
          gridTemplateColumns: "1.1fr 1fr",
          gridTemplateRows: "auto 1fr",
          gap: 16,
          minHeight: 0,
        }}
      >
        {/* —— Format chooser —— */}
        <div className="card" style={{ padding: 16, gridColumn: "1", gridRow: "1" }}>
          <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>Export Bundle</div>
              <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>
                Download the validation report for {activeRunId || "the demo dossier"}
              </div>
            </div>
            <span style={{ marginLeft: "auto" }} className="chip outline mono">
              {sc.total} links
            </span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
            {formats.map((f) => (
              <button
                key={f.name}
                onClick={f.onClick}
                disabled={!f.enabled}
                style={{
                  position: "relative",
                  padding: 12,
                  textAlign: "left",
                  border: `1px solid ${f.enabled ? "var(--brand)" : "var(--border)"}`,
                  background: f.enabled ? "var(--brand-tint)" : "var(--surface)",
                  borderRadius: 4,
                  cursor: f.enabled ? "pointer" : "not-allowed",
                  opacity: f.enabled ? 1 : 0.55,
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                  fontFamily: "inherit",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <Icon name={f.icon} size={16} color={f.enabled ? "var(--brand-pressed)" : "var(--text-2)"} />
                  <span style={{ fontWeight: 600, fontSize: 13, color: f.enabled ? "var(--brand-pressed)" : "var(--text-1)" }}>
                    {f.name}
                  </span>
                  {f.enabled && (
                    <span style={{ marginLeft: "auto" }}>
                      <Icon name="download" size={13} color="var(--brand-pressed)" />
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 11, color: "var(--text-2)" }}>{f.desc}</div>
              </button>
            ))}
          </div>
          <div
            style={{
              marginTop: 12,
              paddingTop: 12,
              borderTop: "1px solid var(--border)",
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: 12,
              fontSize: 12,
            }}
          >
            <div>
              <div style={{ color: "var(--text-3)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                Scope
              </div>
              <span className="mono" style={{ fontSize: 11 }}>{activeRunId || "demo seed"} · all docs</span>
            </div>
            <div>
              <div style={{ color: "var(--text-3)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                Include
              </div>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                <span className="chip success chip-sm">{sc.ok} ok</span>
                <span className="chip warning chip-sm">{sc.suspicious} suspect</span>
                <span className="chip danger chip-sm">{sc.broken} broken</span>
              </div>
            </div>
            <div>
              <div style={{ color: "var(--text-3)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                Unverified
              </div>
              <span className="mono" style={{ fontSize: 11 }}>{sc.unverified} links</span>
            </div>
          </div>
        </div>

        {/* —— Submission readiness (live) — spans rows —— */}
        <div
          className="card"
          style={{
            padding: 16,
            gridColumn: "2",
            gridRow: "1 / span 2",
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>Submission Readiness</div>
              <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>
                Gate threshold ≥ 95 · 21 CFR Part 11 posture
              </div>
            </div>
            <span style={{ marginLeft: "auto" }} className={`chip ${ready ? "success" : "warning"}`}>
              <Icon name={ready ? "shield-check" : "clock"} size={10} /> {ready ? "Ready" : "Blocked"}
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 16, paddingBottom: 12, borderBottom: "1px solid var(--border)" }}>
            <RadialGauge value={readiness} size={104} />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, flex: 1 }}>
              {[
                { lbl: "Grade", val: grade, warn: false },
                { lbl: "Broken links", val: String(broken), warn: broken > 0 },
                { lbl: "Blocker anomalies", val: String(blockers), warn: blockers > 0 },
                { lbl: "Docs covered", val: String(docsCovered), warn: false },
              ].map((s) => (
                <div key={s.lbl} style={{ padding: 8, background: "var(--surface-raised)", borderRadius: 4 }}>
                  <div style={{ color: "var(--text-3)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    {s.lbl}
                  </div>
                  <div className="mono num" style={{ fontSize: 18, fontWeight: 600, marginTop: 2, color: s.warn ? "var(--danger-text)" : "var(--text-1)" }}>
                    {s.val}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Blocking issues list (live) */}
          <div style={{ marginTop: 12, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Blocking issues
            </span>
            <span className="chip outline chip-sm mono">{broken + blockers}</span>
          </div>
          <div style={{ flex: 1, overflow: "auto", marginTop: 8 }}>
            {broken + blockers === 0 && (
              <div style={{ padding: 24, textAlign: "center", color: "var(--success)", fontSize: 13 }}>
                <Icon name="check-circle" size={20} color="var(--success)" />
                <div style={{ marginTop: 6 }}>No blocking issues — clear to submit.</div>
              </div>
            )}
            {blockingLinks.map((l, i) => (
              <div key={`l${i}`} style={{ display: "flex", gap: 10, padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
                <div style={{ width: 20, height: 20, borderRadius: 4, flexShrink: 0, display: "grid", placeItems: "center", background: "var(--danger-tint)", color: "var(--danger)" }}>
                  <Icon name="link-broken" size={11} color="currentColor" strokeWidth={2} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12 }}>
                    <span style={{ fontWeight: 500 }}>{l.source_doc}</span>
                    <span style={{ color: "var(--text-2)" }}> · broken link</span>
                  </div>
                  <div className="mono" style={{ fontSize: 10, color: "var(--text-3)", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    “{l.link_text}” → {l.target_doc || l.target_anchor || "unresolved"}
                  </div>
                </div>
              </div>
            ))}
            {blockingAnoms.map((a, i) => (
              <div key={`a${i}`} style={{ display: "flex", gap: 10, padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
                <div style={{ width: 20, height: 20, borderRadius: 4, flexShrink: 0, display: "grid", placeItems: "center", background: "var(--danger-tint)", color: "var(--danger)" }}>
                  <Icon name="alert" size={11} color="currentColor" strokeWidth={2} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12 }}>
                    <span style={{ fontWeight: 500 }}>{a.document || "Engine"}</span>
                    <span style={{ color: "var(--text-2)" }}> · {a.kind}</span>
                  </div>
                  <div className="mono" style={{ fontSize: 10, color: "var(--text-3)", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {a.text}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* —— Compliance + bundle —— */}
        <div
          style={{
            gridColumn: "1",
            gridRow: "2",
            display: "flex",
            flexDirection: "column",
            gap: 12,
            minHeight: 0,
          }}
        >
          <div className="card" style={{ padding: 14 }}>
            <div style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>
              Compliance Posture
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
              {(
                [
                  { icon: "shield-check" as IconName, title: "21 CFR Part 11", desc: "Audit-logged · electronic signatures" },
                  { icon: "cpu" as IconName, title: "On-prem inference", desc: "No external data transmission" },
                  { icon: "file-text" as IconName, title: "PDF/A-2b validated", desc: "Long-term archival format" },
                  { icon: "lock" as IconName, title: "GxP environment", desc: "Isolated VPC" },
                ] as const
              ).map((b) => (
                <div
                  key={b.title}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 8,
                    padding: 10,
                    border: "1px solid var(--success-tint)",
                    background: "var(--success-tint)",
                    borderRadius: 4,
                  }}
                >
                  <Icon name={b.icon} size={14} color="var(--success)" strokeWidth={2} />
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "var(--success-text)" }}>{b.title}</div>
                    <div style={{ fontSize: 11, color: "var(--success-text)", opacity: 0.85, marginTop: 2 }}>{b.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="card" style={{ padding: 16, flex: 1, display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center" }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>Bundle Preview</div>
                <div className="mono" style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>
                  {dossierId}-{activeRunId || "demo"}.zip
                </div>
              </div>
              <div style={{ marginLeft: "auto", textAlign: "right" }}>
                <div className="mono num" style={{ fontSize: 18, fontWeight: 600 }}>{sc.total}</div>
                <div className="mono" style={{ fontSize: 10, color: "var(--text-3)" }}>links exported</div>
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, fontSize: 11 }}>
              {[
                { lbl: "Docs covered", val: String(docsCovered) },
                { lbl: "Readiness", val: String(readiness) },
                { lbl: "Grade", val: grade },
              ].map((x) => (
                <div key={x.lbl} style={{ padding: 8, background: "var(--surface-raised)", borderRadius: 4 }}>
                  <div style={{ color: "var(--text-3)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    {x.lbl}
                  </div>
                  <div className="mono num" style={{ fontSize: 16, fontWeight: 600, marginTop: 2 }}>{x.val}</div>
                </div>
              ))}
            </div>

            {!ready && (
              <div
                style={{
                  marginTop: "auto",
                  padding: "10px 12px",
                  border: "1px solid var(--warning-tint)",
                  background: "var(--warning-tint)",
                  borderRadius: 4,
                  fontSize: 11,
                  color: "var(--warning-text)",
                  display: "flex",
                  gap: 8,
                  alignItems: "flex-start",
                }}
              >
                <Icon name="alert" size={12} color="var(--warning)" strokeWidth={2} />
                <div>
                  <strong style={{ display: "block", marginBottom: 2 }}>
                    {broken + blockers} blocking issue{broken + blockers === 1 ? "" : "s"} unresolved.
                  </strong>
                  Exporting tags the bundle as <span className="mono">DRAFT</span> until the gate passes.
                </div>
              </div>
            )}

            <div style={{ display: "flex", gap: 8, marginTop: ready ? "auto" : 0 }}>
              <button className="btn btn-secondary" onClick={() => api.exportCsv(activeRunId)}>
                <Icon name="download" size={13} /> CSV
              </button>
              <button
                className="btn btn-primary"
                style={{ marginLeft: "auto", height: 36, padding: "0 16px" }}
                onClick={() => api.exportXlsx(activeRunId)}
                disabled={loading}
              >
                <Icon name="download" size={14} color="#fff" /> Export bundle (XLSX)
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
