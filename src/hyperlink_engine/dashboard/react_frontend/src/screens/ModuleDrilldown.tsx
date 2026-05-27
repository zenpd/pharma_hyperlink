/**
 * Screen 2 — Module Drill-down.
 *
 * Layout: `260px (CTD tree aside) | 1fr (main)`.
 * Production hardening: replace inline <table> with TanStack Table +
 * @tanstack/react-virtual once the API wires up (it's designed for ≥ 2,000 rows).
 */

import React from "react";
import {
  CtdCrumb,
  Icon,
  SevChip,
  Sparkline,
  TopBar,
  DossierBar,
  TreeRow,
} from "../components/shared";
import type { IconName, SeverityKind } from "../components/shared";

interface TreeNode {
  d: number;
  lbl: string;
  icon: IconName;
  badge: number;
  open?: boolean;
  active?: boolean;
}

interface DocRow {
  id: string;
  name: string;
  path: string;
  linksAuto: number;
  linksMan: number;
  broken: number;
  anomalies: number;
  lastRun: string;
  status: SeverityKind;
  sev: SeverityKind;
}

const TREE: TreeNode[] = [
  { d: 0, lbl: "m1 — Regional", icon: "folder", badge: 142, open: true },
  { d: 1, lbl: "1.1 Cover Letter", icon: "file-text", badge: 8 },
  { d: 1, lbl: "1.2 Application Form", icon: "file-text", badge: 12 },
  { d: 1, lbl: "1.3 Administrative Info", icon: "folder", badge: 64, open: true },
  { d: 2, lbl: "1.3.1 Labeling", icon: "file-text", badge: 28 },
  { d: 2, lbl: "1.3.4 Financial Disclosure", icon: "file-text", badge: 36 },
  { d: 0, lbl: "m2 — Summaries", icon: "folder-open", badge: 318, open: true },
  { d: 1, lbl: "2.3 Quality Overall Summary", icon: "file-text", badge: 47 },
  { d: 1, lbl: "2.4 Nonclinical Overview", icon: "file-text", badge: 38 },
  { d: 1, lbl: "2.5 Clinical Overview", icon: "folder-open", badge: 124, open: true, active: true },
  { d: 2, lbl: "2.5.1 Product Development", icon: "file-text", badge: 22, active: true },
  { d: 2, lbl: "2.5.2 Overview of Biopharmaceutics", icon: "file-text", badge: 18 },
  { d: 2, lbl: "2.5.3 Clinical Pharmacology", icon: "file-text", badge: 41 },
  { d: 2, lbl: "2.5.4 Efficacy", icon: "file-text", badge: 24 },
  { d: 2, lbl: "2.5.5 Safety", icon: "file-text", badge: 19 },
  { d: 0, lbl: "m3 — Quality", icon: "folder", badge: 612 },
  { d: 0, lbl: "m4 — Nonclinical", icon: "folder", badge: 384 },
  { d: 0, lbl: "m5 — Clinical Study Reports", icon: "folder", badge: 691 },
];

const DOCS: DocRow[] = [
  { id: "m251-001", name: "Product Development Rationale", path: "m2/2.5/2.5.1/product-dev-rationale.docx", linksAuto: 84, linksMan: 6, broken: 0, anomalies: 2, lastRun: "14:22", status: "success", sev: "success" },
  { id: "m251-002", name: "Formulation History", path: "m2/2.5/2.5.1/formulation-history.docx", linksAuto: 58, linksMan: 4, broken: 1, anomalies: 8, lastRun: "14:22", status: "warning", sev: "warning" },
  { id: "m251-003", name: "Pivotal Study Design Rationale", path: "m2/2.5/2.5.1/pivotal-design-rationale.docx", linksAuto: 142, linksMan: 12, broken: 4, anomalies: 18, lastRun: "14:22", status: "blocker", sev: "blocker" },
  { id: "m251-004", name: "Phase II → III Bridging", path: "m2/2.5/2.5.1/phase-bridging.docx", linksAuto: 96, linksMan: 8, broken: 0, anomalies: 3, lastRun: "14:21", status: "success", sev: "success" },
  { id: "m251-005", name: "Dose Selection Justification", path: "m2/2.5/2.5.1/dose-selection.docx", linksAuto: 73, linksMan: 9, broken: 2, anomalies: 11, lastRun: "14:21", status: "warning", sev: "warning" },
  { id: "m251-006", name: "Comparator Selection", path: "m2/2.5/2.5.1/comparator-selection.docx", linksAuto: 41, linksMan: 3, broken: 0, anomalies: 1, lastRun: "14:21", status: "success", sev: "success" },
  { id: "m251-007", name: "PMDA Bridging Strategy", path: "m2/2.5/2.5.1/pmda-bridging-strategy.docx", linksAuto: 67, linksMan: 14, broken: 3, anomalies: 22, lastRun: "14:21", status: "blocker", sev: "blocker" },
  { id: "m251-008", name: "Risk Evaluation Plan", path: "m2/2.5/2.5.1/risk-evaluation.docx", linksAuto: 89, linksMan: 5, broken: 0, anomalies: 4, lastRun: "14:20", status: "success", sev: "success" },
  { id: "m251-009", name: "Special Population Justification", path: "m2/2.5/2.5.1/special-pop.docx", linksAuto: 52, linksMan: 7, broken: 1, anomalies: 6, lastRun: "14:20", status: "warning", sev: "warning" },
  { id: "m251-010", name: "Hepatic Impairment Strategy", path: "m2/2.5/2.5.1/hepatic-impairment.docx", linksAuto: 38, linksMan: 2, broken: 0, anomalies: 0, lastRun: "14:20", status: "success", sev: "success" },
  { id: "m251-011", name: "Renal Impairment Strategy", path: "m2/2.5/2.5.1/renal-impairment.docx", linksAuto: 44, linksMan: 3, broken: 0, anomalies: 2, lastRun: "14:20", status: "success", sev: "success" },
  { id: "m251-012", name: "Pediatric Investigation Plan", path: "m2/2.5/2.5.1/pip.docx", linksAuto: 78, linksMan: 11, broken: 2, anomalies: 14, lastRun: "14:19", status: "warning", sev: "warning" },
];

export interface ModuleDrilldownProps {
  theme?: "light" | "dark";
}

export const ModuleDrilldown: React.FC<ModuleDrilldownProps> = ({ theme = "light" }) => (
  <div className={`hv-root ${theme === "dark" ? "theme-dark" : ""}`}>
    <TopBar theme={theme} activeTab="Dossiers" />
    <DossierBar
      right={
        <>
          <button className="btn btn-secondary btn-sm"><Icon name="filter" size={12}/> Filters · 2</button>
          <button className="btn btn-secondary btn-sm"><Icon name="columns" size={12}/> Columns</button>
          <button className="btn btn-secondary btn-sm"><Icon name="download" size={12}/> Export view</button>
          <button className="btn btn-primary btn-sm"><Icon name="play" size={11} color="#fff"/> Re-run validation</button>
        </>
      }
    >
      <Icon name="package" size={15} color="var(--text-2)" />
      <span style={{ fontWeight: 600 }}>NDA 215842 · Brenzavir</span>
      <div className="divider-v" style={{ height: 16, margin: "0 4px" }} />
      <CtdCrumb parts={["Dossier", "m2 — Summaries", "2.5 Clinical Overview"]} current="2.5.1 Product Development" />
    </DossierBar>

    <div style={{ flex: 1, display: "grid", gridTemplateColumns: "260px 1fr", minHeight: 0 }}>
      {/* LEFT — CTD tree */}
      <aside style={{
        background: "var(--surface-sunken)",
        borderRight: "1px solid var(--border)",
        display: "flex", flexDirection: "column", minHeight: 0,
      }}>
        <div style={{ padding: "12px 12px 8px 12px" }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "0 8px", height: 28,
            border: "1px solid var(--border)", borderRadius: 4,
            background: "var(--surface)",
          }}>
            <Icon name="search" size={12} color="var(--text-3)" />
            <input
              style={{
                border: "none", background: "transparent", height: 26, padding: 0,
                fontSize: 12, flex: 1, outline: "none", fontFamily: "inherit",
                color: "var(--text-1)",
              }}
              placeholder="Filter tree…"
              aria-label="Filter CTD tree"
            />
          </div>
        </div>
        <div style={{ flex: 1, padding: "0 6px 12px 6px", overflow: "hidden" }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "6px 8px", fontSize: 10, color: "var(--text-3)",
            textTransform: "uppercase", letterSpacing: "0.08em",
          }}>
            <span>CTD Structure</span>
            <span className="mono" style={{ fontSize: 10 }}>500 docs</span>
          </div>
          {TREE.map((n, i) => (
            <TreeRow
              key={i}
              depth={n.d}
              active={n.active}
              expandable={n.icon === "folder" || n.icon === "folder-open"}
              open={n.open}
              label={n.lbl}
              badge={n.badge}
              icon={
                <Icon
                  name={n.icon}
                  size={12}
                  color={n.active ? "var(--brand)" : "var(--text-2)"}
                />
              }
            />
          ))}
        </div>
        <div style={{
          padding: "10px 12px", borderTop: "1px solid var(--border)",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          fontSize: 11, color: "var(--text-2)",
        }}>
          <span>
            <Icon name="folder" size={11} color="var(--text-3)" style={{ verticalAlign: -1, marginRight: 4 }}/>
            500 documents
          </span>
          <span className="mono" style={{ color: "var(--text-1)" }}>2,147 links</span>
        </div>
      </aside>

      {/* RIGHT — main */}
      <main style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
        {/* Section header */}
        <div style={{
          padding: "14px 20px",
          display: "flex", alignItems: "flex-end", gap: 20,
          borderBottom: "1px solid var(--border)",
        }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>m2.5.1</div>
            <div style={{ fontFamily: "var(--ff-display)", fontSize: 20, fontWeight: 600, letterSpacing: "-0.01em" }}>
              Product Development
            </div>
            <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>
              12 documents · last validated <span className="mono">14:22</span> from <span className="mono">run-0091</span>
            </div>
          </div>
          <div style={{ display: "flex", gap: 12 }}>
            {[
              { label: "Docs", val: "12", warn: false },
              { label: "Links", val: "836", warn: false },
              { label: "Broken", val: "13", warn: true },
              { label: "Anomalies", val: "91", warn: false },
              { label: "Readiness", val: "74", warn: false },
            ].map((s) => (
              <div
                key={s.label}
                style={{
                  borderLeft: "1px solid var(--border)", paddingLeft: 12,
                  display: "flex", flexDirection: "column",
                }}
              >
                <span style={{ fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  {s.label}
                </span>
                <span className="mono num" style={{
                  fontSize: 18, fontWeight: 600, marginTop: 2,
                  color: s.warn ? "var(--danger-text)" : "var(--text-1)",
                }}>
                  {s.val}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Filter strip */}
        <div style={{
          padding: "10px 20px",
          display: "flex", alignItems: "center", gap: 8,
          borderBottom: "1px solid var(--border)",
          background: "var(--surface-raised)",
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "0 8px", height: 28,
            border: "1px solid var(--border)", borderRadius: 4,
            background: "var(--surface)", width: 280,
          }}>
            <Icon name="search" size={12} color="var(--text-3)" />
            <input
              style={{
                border: "none", background: "transparent", height: 26, padding: 0,
                fontSize: 12, flex: 1, outline: "none", fontFamily: "inherit",
                color: "var(--text-1)",
              }}
              placeholder="Search documents…"
              aria-label="Search documents"
            />
          </div>
          <span className="chip brand"><Icon name="filter" size={10}/>Status: blocker, warning <Icon name="x" size={10}/></span>
          <span className="chip outline">Has broken: any <Icon name="chevron-down" size={10}/></span>
          <span className="chip outline">Modified: last 24h <Icon name="chevron-down" size={10}/></span>
          <span className="chip outline">+ Add filter</span>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text-2)" }}>
            Showing <span className="mono" style={{ color: "var(--text-1)" }}>12 / 12</span>
            <button className="btn btn-sm btn-ghost" aria-label="Toggle density"><Icon name="sliders" size={12}/></button>
          </div>
        </div>

        {/* Doc table */}
        <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
          <table className="tbl">
            <colgroup>
              <col style={{ width: 28 }} />
              <col />
              <col style={{ width: 320 }} />
              <col style={{ width: 96 }} />
              <col style={{ width: 80 }} />
              <col style={{ width: 90 }} />
              <col style={{ width: 130 }} />
              <col style={{ width: 88 }} />
              <col style={{ width: 130 }} />
              <col style={{ width: 32 }} />
            </colgroup>
            <thead>
              <tr>
                <th><input type="checkbox" aria-label="Select all" /></th>
                <th>Document</th>
                <th>Path</th>
                <th style={{ textAlign: "right" }}>Links</th>
                <th style={{ textAlign: "right" }}>Broken</th>
                <th style={{ textAlign: "right" }}>Anomalies</th>
                <th>Trend</th>
                <th>Last Run</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {DOCS.map((d, i) => (
                <tr key={d.id} style={{ background: i === 0 ? "var(--brand-tint)" : undefined }}>
                  <td><input type="checkbox" aria-label={`Select ${d.name}`} /></td>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <Icon name="chevron-right" size={12} color="var(--text-3)" />
                      <Icon name="file-text" size={14} color="var(--text-2)" />
                      <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                        <span style={{
                          color: "var(--text-1)", fontWeight: 500,
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}>
                          {d.name}
                        </span>
                        <span className="mono" style={{ fontSize: 10, color: "var(--text-3)" }}>{d.id}</span>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className="mono" style={{ fontSize: 11, color: "var(--text-2)" }}>{d.path}</span>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <span className="mono num" style={{ color: "var(--text-1)", fontWeight: 500 }}>{d.linksAuto + d.linksMan}</span>
                    <span className="mono" style={{ fontSize: 10, color: "var(--text-3)", marginLeft: 4 }}>({d.linksMan}m)</span>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {d.broken > 0
                      ? <span className="mono num" style={{ color: "var(--danger-text)", fontWeight: 600 }}>{d.broken}</span>
                      : <span className="mono num" style={{ color: "var(--text-disabled)" }}>0</span>}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {d.anomalies > 0
                      ? <span className="mono num" style={{ color: "var(--text-1)" }}>{d.anomalies}</span>
                      : <span className="mono num" style={{ color: "var(--text-disabled)" }}>0</span>}
                  </td>
                  <td>
                    <Sparkline
                      data={[12, 8, 14, 6, 4, d.broken + d.anomalies / 4]}
                      width={110}
                      height={20}
                      color={
                        d.sev === "blocker"
                          ? "var(--danger)"
                          : d.sev === "warning"
                          ? "var(--warning)"
                          : "var(--success)"
                      }
                    />
                  </td>
                  <td>
                    <span className="mono" style={{ fontSize: 11, color: "var(--text-2)" }}>{d.lastRun}</span>
                  </td>
                  <td>
                    <SevChip
                      kind={d.sev}
                      label={d.sev === "blocker" ? "Blocker" : d.sev === "warning" ? "Warning" : "Valid"}
                    />
                  </td>
                  <td>
                    <button className="btn btn-icon btn-sm btn-ghost" aria-label={`Open menu for ${d.name}`}>
                      <Icon name="more-h" size={13} color="var(--text-3)" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div style={{
          height: 36, flexShrink: 0,
          borderTop: "1px solid var(--border)",
          display: "flex", alignItems: "center", padding: "0 20px",
          fontSize: 12, color: "var(--text-2)",
          background: "var(--surface-raised)",
        }}>
          <span>12 of 12 documents · 2,147 links · virtualized for ≥ 2,000 rows</span>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 4 }}>
            <span className="mono" style={{ fontSize: 11, color: "var(--text-3)", marginRight: 8 }}>50 / page</span>
            <button className="btn btn-icon btn-sm btn-ghost" disabled style={{ opacity: 0.4 }} aria-label="Previous page">
              <Icon name="chevron-left" size={12} />
            </button>
            <span className="mono" style={{ fontSize: 11 }}>1 / 1</span>
            <button className="btn btn-icon btn-sm btn-ghost" disabled style={{ opacity: 0.4 }} aria-label="Next page">
              <Icon name="chevron-right" size={12} />
            </button>
          </div>
        </div>
      </main>
    </div>
  </div>
);
