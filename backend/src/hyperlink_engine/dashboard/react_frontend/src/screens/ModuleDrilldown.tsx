/**
 * Screen 2 — Module Drill-down.  [LIVE]
 *
 * The CTD tree, per-module rollup and document table are all derived from the
 * backend's link + anomaly data for the active run (or the demo dossier).
 * Module selection and the document search box are wired client-side.
 */

import React, { useMemo, useState } from "react";
import {
  CtdCrumb,
  Icon,
  SevChip,
  Sparkline,
  TopBar,
  DossierBar,
  TreeRow,
} from "../components/shared";
import { useActiveRun } from "../contexts/ActiveRun";
import { docAggs, docSev, moduleAggs, ratio, useReportData } from "../live";
import type { DocAgg } from "../live";
import { api } from "../api";

const baseName = (p: string): string => (p || "").split(/[\\/]/).pop() || p;
const niceName = (p: string): string =>
  baseName(p)
    .replace(/\.(docx|pdf|doc)$/i, "")
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());

export interface ModuleDrilldownProps {
  theme?: "light" | "dark";
}

export const ModuleDrilldown: React.FC<ModuleDrilldownProps> = ({ theme = "light" }) => {
  const { activeRunId } = useActiveRun();
  const { links, anomalies, loading } = useReportData(activeRunId);

  const allDocs = useMemo(() => docAggs(links, anomalies), [links, anomalies]);
  const mods = useMemo(() => moduleAggs(links), [links]);

  const [selectedModule, setSelectedModule] = useState<string>("");
  const [query, setQuery] = useState("");

  // Default selection = first module with links.
  const activeModule = selectedModule || (mods[0]?.module ?? "");

  const moduleDocs = useMemo(
    () => allDocs.filter((d) => d.module === activeModule),
    [allDocs, activeModule],
  );
  const visibleDocs = useMemo(
    () =>
      moduleDocs.filter(
        (d) => !query.trim() || d.doc.toLowerCase().includes(query.trim().toLowerCase()),
      ),
    [moduleDocs, query],
  );

  // Per-module header stats
  const stat = useMemo(() => {
    const t = moduleDocs.reduce(
      (acc, d) => {
        acc.total += d.total;
        acc.ok += d.ok;
        acc.broken += d.broken;
        acc.anomalies += d.anomalies;
        return acc;
      },
      { total: 0, ok: 0, broken: 0, anomalies: 0 },
    );
    return {
      docs: moduleDocs.length,
      links: t.total,
      broken: t.broken,
      anomalies: t.anomalies,
      readiness: t.total ? Math.round(ratio(t.ok, t.total) * 100) : 0,
    };
  }, [moduleDocs]);

  const totalDocs = allDocs.length;
  const totalLinks = links.length;

  return (
    <div className={`hv-root ${theme === "dark" ? "theme-dark" : ""}`}>
      <TopBar theme={theme} activeTab="Dossiers" />
      <DossierBar
        right={
          <>
            <button className="btn btn-secondary btn-sm">
              <Icon name="columns" size={12} /> Columns
            </button>
            <button className="btn btn-secondary btn-sm" onClick={() => api.exportCsv(activeRunId)}>
              <Icon name="download" size={12} /> Export view
            </button>
          </>
        }
      >
        <Icon name="package" size={15} color="var(--text-2)" />
        <span style={{ fontWeight: 600 }}>{activeRunId || "Demo seed dossier"}</span>
        <div className="divider-v" style={{ height: 16, margin: "0 4px" }} />
        <CtdCrumb parts={["Dossier", "Modules"]} current={activeModule || "—"} />
      </DossierBar>

      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "260px 1fr", minHeight: 0 }}>
        {/* LEFT — CTD tree */}
        <aside
          style={{
            background: "var(--surface-sunken)",
            borderRight: "1px solid var(--border)",
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
          }}
        >
          <div style={{ padding: "12px 12px 8px 12px" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "0 8px",
                height: 28,
                border: "1px solid var(--border)",
                borderRadius: 4,
                background: "var(--surface)",
              }}
            >
              <Icon name="search" size={12} color="var(--text-3)" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                style={{
                  border: "none",
                  background: "transparent",
                  height: 26,
                  padding: 0,
                  fontSize: 12,
                  flex: 1,
                  outline: "none",
                  fontFamily: "inherit",
                  color: "var(--text-1)",
                }}
                placeholder="Filter documents…"
                aria-label="Filter documents"
              />
            </div>
          </div>
          <div style={{ flex: 1, padding: "0 6px 12px 6px", overflow: "auto" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "6px 8px",
                fontSize: 10,
                color: "var(--text-3)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
              }}
            >
              <span>CTD Structure</span>
              <span className="mono" style={{ fontSize: 10 }}>{totalDocs} docs</span>
            </div>
            {mods.length === 0 && (
              <div style={{ padding: 12, fontSize: 12, color: "var(--text-3)" }}>
                {loading ? "Loading…" : "No documents"}
              </div>
            )}
            {mods.map((m) => {
              const isOpen = m.module === activeModule;
              const docsIn = allDocs.filter((d) => d.module === m.module);
              return (
                <React.Fragment key={m.module}>
                  <TreeRow
                    depth={0}
                    active={isOpen}
                    expandable
                    open={isOpen}
                    label={`${m.module} — ${docsIn.length} doc${docsIn.length === 1 ? "" : "s"}`}
                    badge={m.total}
                    icon={
                      <Icon
                        name={isOpen ? "folder-open" : "folder"}
                        size={12}
                        color={isOpen ? "var(--brand)" : "var(--text-2)"}
                      />
                    }
                    onClick={() => setSelectedModule(m.module)}
                  />
                  {isOpen &&
                    docsIn.map((d) => (
                      <TreeRow
                        key={d.doc}
                        depth={1}
                        label={niceName(d.doc)}
                        badge={d.total}
                        icon={<Icon name="file-text" size={12} color="var(--text-2)" />}
                      />
                    ))}
                </React.Fragment>
              );
            })}
          </div>
          <div
            style={{
              padding: "10px 12px",
              borderTop: "1px solid var(--border)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              fontSize: 11,
              color: "var(--text-2)",
            }}
          >
            <span>
              <Icon name="folder" size={11} color="var(--text-3)" style={{ verticalAlign: -1, marginRight: 4 }} />
              {totalDocs} documents
            </span>
            <span className="mono" style={{ color: "var(--text-1)" }}>{totalLinks} links</span>
          </div>
        </aside>

        {/* RIGHT — main */}
        <main style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
          {/* Section header */}
          <div
            style={{
              padding: "14px 20px",
              display: "flex",
              alignItems: "flex-end",
              gap: 20,
              borderBottom: "1px solid var(--border)",
            }}
          >
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                {activeModule || "—"}
              </div>
              <div style={{ fontFamily: "var(--ff-display)", fontSize: 20, fontWeight: 600, letterSpacing: "-0.01em" }}>
                {activeModule ? `Module ${activeModule.replace("m", "")}` : "Modules"}
              </div>
              <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>
                {stat.docs} document{stat.docs === 1 ? "" : "s"} ·{" "}
                source <span className="mono">{activeRunId || "demo seed"}</span>
              </div>
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              {[
                { label: "Docs", val: String(stat.docs), warn: false },
                { label: "Links", val: String(stat.links), warn: false },
                { label: "Broken", val: String(stat.broken), warn: stat.broken > 0 },
                { label: "Anomalies", val: String(stat.anomalies), warn: false },
                { label: "Readiness", val: String(stat.readiness), warn: false },
              ].map((s) => (
                <div
                  key={s.label}
                  style={{
                    borderLeft: "1px solid var(--border)",
                    paddingLeft: 12,
                    display: "flex",
                    flexDirection: "column",
                  }}
                >
                  <span style={{ fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    {s.label}
                  </span>
                  <span
                    className="mono num"
                    style={{
                      fontSize: 18,
                      fontWeight: 600,
                      marginTop: 2,
                      color: s.warn ? "var(--danger-text)" : "var(--text-1)",
                    }}
                  >
                    {s.val}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Filter strip */}
          <div
            style={{
              padding: "10px 20px",
              display: "flex",
              alignItems: "center",
              gap: 8,
              borderBottom: "1px solid var(--border)",
              background: "var(--surface-raised)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "0 8px",
                height: 28,
                border: "1px solid var(--border)",
                borderRadius: 4,
                background: "var(--surface)",
                width: 280,
              }}
            >
              <Icon name="search" size={12} color="var(--text-3)" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                style={{
                  border: "none",
                  background: "transparent",
                  height: 26,
                  padding: 0,
                  fontSize: 12,
                  flex: 1,
                  outline: "none",
                  fontFamily: "inherit",
                  color: "var(--text-1)",
                }}
                placeholder="Search documents…"
                aria-label="Search documents"
              />
            </div>
            {mods.map((m) => (
              <span
                key={m.module}
                onClick={() => setSelectedModule(m.module)}
                className={`chip ${m.module === activeModule ? "brand" : "outline"}`}
                style={{ cursor: "pointer" }}
              >
                {m.module}
                <span className="mono" style={{ marginLeft: 4, opacity: 0.7 }}>{m.total}</span>
              </span>
            ))}
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text-2)" }}>
              Showing <span className="mono" style={{ color: "var(--text-1)" }}>{visibleDocs.length} / {moduleDocs.length}</span>
            </div>
          </div>

          {/* Doc table */}
          <div style={{ flex: 1, overflow: "auto", position: "relative" }}>
            <table className="tbl">
              <colgroup>
                <col />
                <col style={{ width: 340 }} />
                <col style={{ width: 96 }} />
                <col style={{ width: 80 }} />
                <col style={{ width: 90 }} />
                <col style={{ width: 130 }} />
                <col style={{ width: 110 }} />
              </colgroup>
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Path</th>
                  <th style={{ textAlign: "right" }}>Links</th>
                  <th style={{ textAlign: "right" }}>Broken</th>
                  <th style={{ textAlign: "right" }}>Anomalies</th>
                  <th>Status mix</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {visibleDocs.length === 0 && (
                  <tr>
                    <td colSpan={7} style={{ textAlign: "center", color: "var(--text-3)", padding: 28 }}>
                      {loading ? "Loading documents…" : "No documents match"}
                    </td>
                  </tr>
                )}
                {visibleDocs.map((d: DocAgg, i) => {
                  const sev = docSev(d);
                  return (
                    <tr key={d.doc} style={{ background: i === 0 ? "var(--brand-tint)" : undefined }}>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <Icon name="file-text" size={14} color="var(--text-2)" />
                          <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                            <span
                              style={{
                                color: "var(--text-1)",
                                fontWeight: 500,
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {niceName(d.doc)}
                            </span>
                            <span className="mono" style={{ fontSize: 10, color: "var(--text-3)" }}>
                              {Math.round(d.avgConf * 100)}% avg conf
                            </span>
                          </div>
                        </div>
                      </td>
                      <td>
                        <span className="mono" style={{ fontSize: 11, color: "var(--text-2)" }}>{baseName(d.doc)}</span>
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <span className="mono num" style={{ color: "var(--text-1)", fontWeight: 500 }}>{d.total}</span>
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {d.broken > 0 ? (
                          <span className="mono num" style={{ color: "var(--danger-text)", fontWeight: 600 }}>{d.broken}</span>
                        ) : (
                          <span className="mono num" style={{ color: "var(--text-disabled)" }}>0</span>
                        )}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {d.anomalies > 0 ? (
                          <span className="mono num" style={{ color: "var(--text-1)" }}>{d.anomalies}</span>
                        ) : (
                          <span className="mono num" style={{ color: "var(--text-disabled)" }}>0</span>
                        )}
                      </td>
                      <td>
                        <Sparkline
                          data={[d.ok, d.unverified, d.suspicious, d.broken].map((n) => n + 0.01)}
                          width={110}
                          height={20}
                          color={
                            sev === "blocker"
                              ? "var(--danger)"
                              : sev === "warning"
                              ? "var(--warning)"
                              : sev === "info"
                              ? "var(--info)"
                              : "var(--success)"
                          }
                        />
                      </td>
                      <td>
                        <SevChip
                          kind={sev}
                          label={
                            sev === "blocker"
                              ? "Blocker"
                              : sev === "warning"
                              ? "Warning"
                              : sev === "info"
                              ? "Unverified"
                              : "Valid"
                          }
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Footer */}
          <div
            style={{
              height: 36,
              flexShrink: 0,
              borderTop: "1px solid var(--border)",
              display: "flex",
              alignItems: "center",
              padding: "0 20px",
              fontSize: 12,
              color: "var(--text-2)",
              background: "var(--surface-raised)",
            }}
          >
            <span>
              {visibleDocs.length} of {moduleDocs.length} documents in {activeModule || "—"} · {totalLinks} links total
            </span>
          </div>
        </main>
      </div>
    </div>
  );
};
