/**
 * Screen 4 — Anomaly Browser.  [LIVE]
 *
 * Anomalies are pulled from the backend for the active run and grouped by
 * kind. Severity filtering, group expand/collapse, and row selection (driving
 * the bulk-action bar) are all wired client-side.
 */

import React, { useMemo, useState } from "react";
import { CtdCrumb, DossierBar, Icon, SevChip, TopBar } from "../components/shared";
import type { SeverityKind } from "../components/shared";
import { useActiveRun } from "../contexts/ActiveRun";
import { anomalyCounts, anomalyGroups, useReportData } from "../live";
import { api } from "../api";
import type { Anomaly } from "../types";

const KIND_DESC: Record<string, string> = {
  blue_text_no_link: "Text styled as a hyperlink but missing the underlying anchor.",
  blue_text_without_link: "Text styled as a hyperlink but missing the underlying anchor.",
  orphaned_reference: "Source text refers to a section/figure/table that does not exist.",
  orphaned_ref: "Source text refers to a section/figure/table that does not exist.",
  broken_link: "Hyperlink anchor does not resolve to an existing object in the dossier.",
  broken_target: "Hyperlink anchor does not resolve to an existing object in the dossier.",
  circular_reference: "Reference chain forms a cycle within the dossier.",
  circular_ref: "Reference chain forms a cycle within the dossier.",
  deprecated_id: "Cited identifier was superseded by a newer registry entry.",
  deprecated_reference: "Cited document version superseded by a newer sequence.",
  stale_study_id: "Detected study identifier does not match the canonical registry entry.",
  suspicious_target: "LLM flagged the target as semantically unrelated to source context.",
  style_mutation: "Hyperlink character style diverges from the dossier-wide style guide.",
};

const humanize = (kind: string): string =>
  (kind || "anomaly").replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const descFor = (kind: string, count: number): string =>
  KIND_DESC[kind] ?? `${count} occurrence${count === 1 ? "" : "s"} detected by the validation layer.`;

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
    }}
  >
    <span style={{ color: active ? "var(--brand)" : "var(--text-3)", fontSize: 11 }}>{label}:</span>
    <span style={{ fontWeight: active ? 500 : 400 }}>{value}</span>
  </div>
);

export interface AnomalyBrowserProps {
  theme?: "light" | "dark";
}

type SevFilter = "all" | "blocker" | "warning" | "info";

export const AnomalyBrowser: React.FC<AnomalyBrowserProps> = ({ theme = "light" }) => {
  const { activeRunId } = useActiveRun();
  const { anomalies, loading } = useReportData(activeRunId);

  const [sevFilter, setSevFilter] = useState<SevFilter>("all");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const counts = anomalyCounts(anomalies);
  const filtered = useMemo(
    () => (sevFilter === "all" ? anomalies : anomalies.filter((a) => a.severity === sevFilter)),
    [anomalies, sevFilter],
  );
  const groups = useMemo(() => anomalyGroups(filtered), [filtered]);
  const total = filtered.length;

  const idOf = (kind: string, i: number) => `${kind}#${i}`;
  const toggleSel = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleGroup = (kind: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });

  const sevFilters: { k: SevFilter; label: string; n: number }[] = [
    { k: "all", label: "All", n: anomalies.length },
    { k: "blocker", label: "Blocker", n: counts.blocker },
    { k: "warning", label: "Warning", n: counts.warning },
    { k: "info", label: "Info", n: counts.info },
  ];

  return (
    <div className={`hv-root ${theme === "dark" ? "theme-dark" : ""}`}>
      <TopBar theme={theme} activeTab="Anomalies" />
      <DossierBar
        right={
          <button className="btn btn-secondary btn-sm" onClick={() => api.exportXlsx(activeRunId)}>
            <Icon name="download" size={12} /> Export selection
          </button>
        }
      >
        <Icon name="package" size={15} color="var(--text-2)" />
        <span style={{ fontWeight: 600 }}>{activeRunId || "Demo seed dossier"}</span>
        <div className="divider-v" style={{ height: 16, margin: "0 4px" }} />
        <CtdCrumb parts={["Dossier"]} current="Anomaly Browser" />
        <span className="chip outline mono">{anomalies.length} anomalies</span>
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
        <div style={{ display: "flex", gap: 4, background: "var(--surface-raised)", borderRadius: 4, padding: 2 }}>
          {sevFilters.map((f) => (
            <button
              key={f.k}
              className="btn btn-sm"
              onClick={() => setSevFilter(f.k)}
              style={{
                height: 26,
                padding: "0 10px",
                fontSize: 12,
                background: sevFilter === f.k ? "var(--surface)" : "transparent",
                border: sevFilter === f.k ? "1px solid var(--border)" : "1px solid transparent",
                color: sevFilter === f.k ? "var(--text-1)" : "var(--text-2)",
              }}
            >
              {f.label}
              <span className="mono" style={{ marginLeft: 4, color: "var(--text-3)" }}>{f.n}</span>
            </button>
          ))}
        </div>

        <FilterDropdown label="Type" value={`${groups.length} types`} />
        <FilterDropdown label="Status" value="Open" active />

        <div style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-3)" }} className="mono">
          {activeRunId ? `run ${activeRunId}` : "demo seed"} {loading ? "· loading…" : ""}
        </div>
      </div>

      {/* Bulk action bar (only when something is selected) */}
      {selected.size > 0 && (
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
            <span className="mono">{selected.size}</span> selected
          </span>
          <div className="divider-v" style={{ height: 18, background: "var(--brand-tint-2)" }} />
          {[
            { icon: "check" as const, label: "Acknowledge" },
            { icon: "user" as const, label: "Assign to reviewer…" },
            { icon: "flag" as const, label: "Flag for SME" },
          ].map((b) => (
            <button key={b.label} className="btn btn-sm btn-ghost" style={{ color: "var(--brand-pressed)", height: 26 }}>
              <Icon name={b.icon} size={12} /> {b.label}
            </button>
          ))}
          <button
            className="btn btn-sm btn-ghost"
            style={{ color: "var(--brand-pressed)", height: 26, marginLeft: "auto" }}
            onClick={() => setSelected(new Set())}
          >
            <Icon name="x" size={12} /> Clear
          </button>
        </div>
      )}

      {/* List */}
      <div style={{ flex: 1, overflow: "auto", background: "var(--bg)" }}>
        {groups.length === 0 && (
          <div style={{ padding: 40, textAlign: "center", color: "var(--text-3)", fontSize: 13 }}>
            {loading ? "Loading anomalies…" : "No anomalies for this source 🎉"}
          </div>
        )}
        {groups.map((g) => {
          const open = !collapsed.has(g.kind);
          return (
            <div key={g.kind} style={{ borderBottom: "1px solid var(--border)", background: "var(--surface)" }}>
              <div
                onClick={() => toggleGroup(g.kind)}
                style={{
                  padding: "10px 20px",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  background: "var(--surface-raised)",
                  borderBottom: "1px solid var(--border)",
                  cursor: "pointer",
                }}
              >
                <Icon name={open ? "chevron-down" : "chevron-right"} size={12} color="var(--text-3)" />
                <SevChip kind={g.sev} label={humanize(g.kind)} />
                <span className="mono num" style={{ fontSize: 12, color: "var(--text-2)" }}>{g.count}</span>
                <span style={{ fontSize: 12, color: "var(--text-3)", flex: 1 }}>· {descFor(g.kind, g.count)}</span>
              </div>

              {open && (
                <table className="tbl dense">
                  <colgroup>
                    <col style={{ width: 28 }} />
                    <col style={{ width: 90 }} />
                    <col style={{ width: 110 }} />
                    <col style={{ width: 240 }} />
                    <col />
                    <col style={{ width: 90 }} />
                  </colgroup>
                  <tbody>
                    {g.items.map((item: Anomaly, idx) => {
                      const id = idOf(g.kind, idx);
                      const sev: SeverityKind =
                        item.severity === "blocker" ? "blocker" : item.severity === "warning" ? "warning" : "info";
                      return (
                        <tr key={id} style={{ background: selected.has(id) ? "var(--brand-tint)" : undefined }}>
                          <td>
                            <input
                              type="checkbox"
                              checked={selected.has(id)}
                              onChange={() => toggleSel(id)}
                              aria-label={`Select ${id}`}
                            />
                          </td>
                          <td>
                            <span className="mono" style={{ fontSize: 11, color: "var(--text-2)" }}>
                              {String(idx + 1).padStart(4, "0")}
                            </span>
                          </td>
                          <td>
                            <SevChip
                              kind={sev}
                              label={sev === "blocker" ? "Blocker" : sev === "warning" ? "Warning" : "Info"}
                            />
                          </td>
                          <td>
                            <span style={{ color: "var(--text-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block" }}>
                              {item.document || "—"}
                            </span>
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
                              title={item.suggested_fix || item.text}
                            >
                              {item.text}
                              {item.suggested_fix ? `  ·  fix: ${item.suggested_fix}` : ""}
                            </span>
                          </td>
                          <td style={{ textAlign: "right" }}>
                            <span className="mono num" style={{ fontSize: 11, color: "var(--text-3)" }}>
                              {Math.round((item.confidence || 0) * 100)}%
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          );
        })}
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
        <span>
          {total} shown · {counts.blocker} blocker · {counts.warning} warning · {counts.info} info
        </span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: "var(--text-3)" }} className="mono">
            {activeRunId ? `run ${activeRunId}` : "demo seed dossier"}
          </span>
        </div>
      </div>
    </div>
  );
};
