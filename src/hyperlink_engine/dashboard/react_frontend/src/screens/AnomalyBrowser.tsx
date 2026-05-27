/**
 * Screen 4 — Anomaly Browser.
 *
 * Grouped by anomaly type. Bulk-action bar appears when items are selected.
 */

import React from "react";
import { CtdCrumb, DossierBar, Icon, SevChip, TopBar } from "../components/shared";
import type { SeverityKind } from "../components/shared";

interface AnomalyItem {
  id: string;
  doc: string;
  path: string;
  snippet: string;
  detected: string;
  sev: SeverityKind;
  active?: boolean;
}

interface AnomalyGroup {
  type: string;
  count: number;
  sev: SeverityKind;
  desc: string;
  items: AnomalyItem[];
}

const GROUPS: AnomalyGroup[] = [
  {
    type: "Blue-text · no link", count: 47, sev: "info",
    desc: "Text styled as hyperlink but missing the underlying href anchor.",
    items: [
      { id: "A-3204", doc: "Clinical Overview", path: "m2.5.4.2", snippet: 'see "Section 4.2.1"', detected: "14:01", sev: "info" },
      { id: "A-3217", doc: "Risk Evaluation Plan", path: "m2.5.1", snippet: 'reference "Table 11.3"', detected: "14:01", sev: "info" },
      { id: "A-3242", doc: "Pivotal Design Rationale", path: "m2.5.1", snippet: 'cf. "Appendix B-3"', detected: "14:02", sev: "info" },
      { id: "A-3268", doc: "PMDA Bridging Strategy", path: "m2.5.1", snippet: 'per "Figure 2-4"', detected: "14:02", sev: "info" },
    ],
  },
  {
    type: "Stale Study ID", count: 12, sev: "warning",
    desc: "Detected study identifier does not match the canonical registry entry.",
    items: [
      { id: "A-3301", doc: "Pivotal Design Rationale", path: "m2.5.1", snippet: "Study CBV-301 → CBV-301-AME-2", detected: "14:02", sev: "warning", active: true },
      { id: "A-3308", doc: "Clinical Pharmacology", path: "m2.5.3", snippet: "CBV-204 → CBV-204-FIN", detected: "14:02", sev: "warning" },
      { id: "A-3329", doc: "Efficacy Summary", path: "m2.5.4", snippet: "CBV-219 → CBV-219-DSC", detected: "14:03", sev: "warning" },
    ],
  },
  {
    type: "Broken target", count: 13, sev: "blocker",
    desc: "Hyperlink anchor does not resolve to an existing object in the dossier.",
    items: [
      { id: "A-3401", doc: "Pivotal Design Rationale", path: "m2.5.1", snippet: "→ m5.3.5.1/T14-x.x (anchor missing)", detected: "14:03", sev: "blocker" },
      { id: "A-3408", doc: "Phase II → III Bridging", path: "m2.5.1", snippet: "→ m2.7.2#fig-7 (not found)", detected: "14:03", sev: "blocker" },
    ],
  },
  {
    type: "Style mutation", count: 28, sev: "warning",
    desc: "Hyperlink character style diverges from the dossier-wide style guide.",
    items: [
      { id: "A-3501", doc: "Hepatic Impairment Strategy", path: "m2.5.1", snippet: "Color: #1A5AB8 (expected #1F4E8C)", detected: "14:04", sev: "warning" },
    ],
  },
  {
    type: "Orphaned ref", count: 9, sev: "blocker",
    desc: "Source text refers to a section/figure/table that does not exist in the dossier.",
    items: [
      { id: "A-3601", doc: "Pivotal Design Rationale", path: "m2.5.1", snippet: '"see Appendix C" (no Appendix C)', detected: "14:04", sev: "blocker" },
    ],
  },
  {
    type: "Circular ref", count: 4, sev: "warning",
    desc: "Reference chain forms a cycle within the dossier.",
    items: [
      { id: "A-3701", doc: "Risk Evaluation Plan", path: "m2.5.1", snippet: "§4.2 → §6.1 → §4.2", detected: "14:05", sev: "warning" },
    ],
  },
  {
    type: "Suspicious target", count: 6, sev: "warning",
    desc: "LLM flagged target as semantically unrelated to source context.",
    items: [
      { id: "A-3801", doc: "Comparator Selection", path: "m2.5.1", snippet: "Citing PK section from a safety table", detected: "14:05", sev: "warning" },
    ],
  },
  {
    type: "Deprecated reference", count: 8, sev: "warning",
    desc: "Cited document version superseded by a newer sequence.",
    items: [
      { id: "A-3901", doc: "Dose Selection Justification", path: "m2.5.1", snippet: "Protocol v2.0 → v3.0", detected: "14:05", sev: "warning" },
    ],
  },
];

const FilterDropdown: React.FC<{ label: string; value: string; active?: boolean }> = ({
  label,
  value,
  active,
}) => (
  <div
    style={{
      display: "flex",
      alignItems: "center",
      gap: 6,
      padding: "0 10px",
      height: 30,
      border: `1px solid ${active ? "var(--brand-tint-2)" : "var(--border)"}`,
      background: active ? "var(--brand-tint)" : "var(--surface)",
      color: active ? "var(--brand-pressed)" : "var(--text-1)",
      borderRadius: 4,
      fontSize: 12,
      cursor: "pointer",
    }}
  >
    <span style={{ color: active ? "var(--brand)" : "var(--text-3)", fontSize: 11 }}>
      {label}:
    </span>
    <span style={{ fontWeight: active ? 500 : 400 }}>{value}</span>
    <Icon name="chevron-down" size={11} color="currentColor" />
  </div>
);

export interface AnomalyBrowserProps {
  theme?: "light" | "dark";
}

export const AnomalyBrowser: React.FC<AnomalyBrowserProps> = ({ theme = "light" }) => {
  const totalAnomalies = GROUPS.reduce((a, g) => a + g.count, 0);

  return (
    <div className={`hv-root ${theme === "dark" ? "theme-dark" : ""}`}>
      <TopBar theme={theme} activeTab="Anomalies" />
      <DossierBar
        right={
          <>
            <button className="btn btn-secondary btn-sm">
              <Icon name="users" size={12} /> Bulk assign
            </button>
            <button className="btn btn-secondary btn-sm">
              <Icon name="download" size={12} /> Export selection
            </button>
          </>
        }
      >
        <Icon name="package" size={15} color="var(--text-2)" />
        <span style={{ fontWeight: 600 }}>NDA 215842 · Brenzavir</span>
        <div className="divider-v" style={{ height: 16, margin: "0 4px" }} />
        <CtdCrumb parts={["Dossier"]} current="Anomaly Browser" />
        <span className="chip outline mono">{totalAnomalies} anomalies</span>
      </DossierBar>

      {/* Filter bar */}
      <div
        style={{
          padding: "12px 20px",
          display: "flex",
          alignItems: "center",
          gap: 10,
          borderBottom: "1px solid var(--border)",
          background: "var(--surface)",
          flexWrap: "wrap",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "0 10px",
            height: 30,
            border: "1px solid var(--border)",
            borderRadius: 4,
            background: "var(--surface)",
            width: 300,
          }}
        >
          <Icon name="search" size={13} color="var(--text-3)" />
          <input
            style={{
              border: "none",
              background: "transparent",
              height: 28,
              padding: 0,
              fontSize: 13,
              flex: 1,
              outline: "none",
              fontFamily: "inherit",
              color: "var(--text-1)",
            }}
            placeholder="Search anomalies, docs, IDs…"
            aria-label="Search anomalies"
          />
          <span className="kbd">/</span>
        </div>

        <FilterDropdown label="Severity" value="Blocker, Warning" active />
        <FilterDropdown label="Type" value="All 8 types" />
        <FilterDropdown label="Module" value="All modules" />
        <FilterDropdown label="Status" value="Open" active />
        <FilterDropdown label="Assignee" value="Any" />

        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            alignItems: "center",
            gap: 4,
            background: "var(--surface-raised)",
            borderRadius: 4,
            padding: 2,
          }}
        >
          <span style={{ fontSize: 11, color: "var(--text-3)", padding: "0 8px" }}>Group by</span>
          <button
            className="btn btn-sm"
            style={{
              height: 24,
              padding: "0 8px",
              fontSize: 11,
              background: "var(--surface)",
              border: "1px solid var(--border)",
            }}
          >
            Type
          </button>
          <button
            className="btn btn-sm btn-ghost"
            style={{ height: 24, padding: "0 8px", fontSize: 11, color: "var(--text-2)" }}
          >
            Document
          </button>
          <button
            className="btn btn-sm btn-ghost"
            style={{ height: 24, padding: "0 8px", fontSize: 11, color: "var(--text-2)" }}
          >
            Severity
          </button>
        </div>
      </div>

      {/* Bulk action bar */}
      <div
        style={{
          height: 40,
          flexShrink: 0,
          padding: "0 20px",
          display: "flex",
          alignItems: "center",
          gap: 12,
          borderBottom: "1px solid var(--border)",
          background: "var(--brand-tint)",
          color: "var(--brand-pressed)",
        }}
      >
        <Icon name="check-circle" size={14} color="var(--brand-pressed)" strokeWidth={2} />
        <span style={{ fontSize: 13, fontWeight: 500 }}>
          <span className="mono">4</span> selected
        </span>
        <div className="divider-v" style={{ height: 18, background: "var(--brand-tint-2)" }} />
        {[
          { icon: "check" as const, label: "Acknowledge" },
          { icon: "user" as const, label: "Assign to reviewer…" },
          { icon: "flag" as const, label: "Flag for SME" },
          { icon: "download" as const, label: "Export" },
        ].map((b) => (
          <button
            key={b.label}
            className="btn btn-sm btn-ghost"
            style={{ color: "var(--brand-pressed)", height: 26 }}
          >
            <Icon name={b.icon} size={12} /> {b.label}
          </button>
        ))}
        <span style={{ marginLeft: "auto", fontSize: 11, opacity: 0.8 }} className="mono">
          ⌘⇧A · Select all
        </span>
        <button
          className="btn btn-sm btn-ghost"
          style={{ color: "var(--brand-pressed)", height: 26 }}
        >
          <Icon name="x" size={12} /> Clear
        </button>
      </div>

      {/* List */}
      <div style={{ flex: 1, overflow: "hidden", background: "var(--bg)" }}>
        {GROUPS.map((g, gi) => (
          <div
            key={g.type}
            style={{
              borderBottom: "1px solid var(--border)",
              background: "var(--surface)",
            }}
          >
            <div
              style={{
                padding: "10px 20px",
                display: "flex",
                alignItems: "center",
                gap: 10,
                background: "var(--surface-raised)",
                borderBottom: "1px solid var(--border)",
              }}
            >
              <Icon
                name={gi < 4 ? "chevron-down" : "chevron-right"}
                size={12}
                color="var(--text-3)"
              />
              <SevChip kind={g.sev} label={g.type} />
              <span className="mono num" style={{ fontSize: 12, color: "var(--text-2)" }}>
                {g.count}
              </span>
              <span style={{ fontSize: 12, color: "var(--text-3)", flex: 1 }}>· {g.desc}</span>
              <button
                className="btn btn-sm btn-ghost"
                style={{ height: 24, padding: "0 8px", fontSize: 11 }}
              >
                View all {g.count}
              </button>
            </div>

            {gi < 4 && (
              <table className="tbl dense">
                <colgroup>
                  <col style={{ width: 28 }} />
                  <col style={{ width: 96 }} />
                  <col style={{ width: 100 }} />
                  <col style={{ width: 220 }} />
                  <col />
                  <col style={{ width: 100 }} />
                  <col style={{ width: 88 }} />
                  <col style={{ width: 32 }} />
                </colgroup>
                <tbody>
                  {g.items.map((item) => (
                    <tr
                      key={item.id}
                      style={{ background: item.active ? "var(--brand-tint)" : undefined }}
                    >
                      <td>
                        <input
                          type="checkbox"
                          defaultChecked={item.active}
                          aria-label={`Select ${item.id}`}
                        />
                      </td>
                      <td>
                        <span className="mono" style={{ fontSize: 11, color: "var(--text-2)" }}>
                          {item.id}
                        </span>
                      </td>
                      <td>
                        <SevChip
                          kind={item.sev}
                          label={
                            item.sev === "blocker"
                              ? "Blocker"
                              : item.sev === "warning"
                              ? "Warning"
                              : item.sev === "info"
                              ? "Info"
                              : "Valid"
                          }
                        />
                      </td>
                      <td>
                        <div style={{ display: "flex", flexDirection: "column" }}>
                          <span style={{ color: "var(--text-1)" }}>{item.doc}</span>
                          <span
                            className="mono"
                            style={{ fontSize: 10, color: "var(--text-3)" }}
                          >
                            {item.path}
                          </span>
                        </div>
                      </td>
                      <td>
                        <span
                          style={{
                            fontFamily: "var(--ff-mono)",
                            fontSize: 11,
                            color: "var(--text-2)",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            display: "block",
                          }}
                        >
                          {item.snippet}
                        </span>
                      </td>
                      <td>
                        <span
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 5,
                            fontSize: 11,
                            color: "var(--text-2)",
                          }}
                        >
                          <div
                            style={{
                              width: 18,
                              height: 18,
                              borderRadius: "50%",
                              background: "var(--brand-tint)",
                              color: "var(--brand-pressed)",
                              display: "grid",
                              placeItems: "center",
                              fontSize: 9,
                              fontWeight: 600,
                            }}
                          >
                            VI
                          </div>
                          V. Iyer
                        </span>
                      </td>
                      <td>
                        <span
                          className="mono"
                          style={{ fontSize: 11, color: "var(--text-3)" }}
                        >
                          {item.detected}
                        </span>
                      </td>
                      <td>
                        <button
                          className="btn btn-icon btn-sm btn-ghost"
                          aria-label={`Open menu for ${item.id}`}
                        >
                          <Icon name="more-h" size={12} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ))}
      </div>

      {/* Footer */}
      <div
        style={{
          height: 36,
          flexShrink: 0,
          borderTop: "1px solid var(--border)",
          background: "var(--surface-raised)",
          display: "flex",
          alignItems: "center",
          padding: "0 20px",
          fontSize: 12,
          color: "var(--text-2)",
        }}
      >
        <span>{totalAnomalies} anomalies · 13 blocker · 34 warning · 80 info</span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: "var(--text-3)" }} className="mono">
            Updated 14:22 from run-0091
          </span>
          <button className="btn btn-sm btn-ghost" aria-label="Refresh">
            <Icon name="refresh" size={12} />
          </button>
        </div>
      </div>
    </div>
  );
};
