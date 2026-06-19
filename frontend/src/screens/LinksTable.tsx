/**
 * Screen: Link Inspector  (Streamlit "_render_anomaly_browser" equivalent)
 *
 * Full filterable table of all link records, matching Streamlit's:
 *  - status multiselect  → ["broken","suspicious","unverified","ok"]
 *  - doc name text filter
 *  - Columns: source_doc, link_text, status, target_anchor, error_msg
 *  - "Showing X of Y link records" caption
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useActiveRun } from "../contexts/ActiveRun";
import type { Link, LinkStatus } from "../types";

interface Props { onBack: () => void; }

const STATUS_OPTIONS: { key: LinkStatus; label: string; color: string }[] = [
  { key: "broken",     label: "Broken",     color: "var(--danger)"  },
  { key: "suspicious", label: "Suspicious", color: "#f59e0b"        },
  { key: "unverified", label: "Unverified", color: "#f59e0b"        },
  { key: "ok",         label: "OK",         color: "var(--success)" },
];

const PAGE_SIZE = 50;

export function LinksTable({ onBack }: Props) {
  const { activeRunId } = useActiveRun();
  const [links, setLinks]         = useState<Link[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState("");
  const [docFilter, setDocFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<Set<LinkStatus>>(
    new Set(["broken", "suspicious"])  // default: show problems first (matches Streamlit default)
  );
  const [sortCol, setSortCol]     = useState<keyof Link>("status");
  const [sortAsc, setSortAsc]     = useState(true);
  const [page, setPage]           = useState(0);

  function load() {
    setLoading(true);
    setError("");
    api.links(activeRunId)
      .then((data) => { setLinks(data); setLoading(false); })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "Unknown error");
        setLoading(false);
      });
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [activeRunId]);

  function toggleStatus(s: LinkStatus) {
    setStatusFilter((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s); else next.add(s);
      return next;
    });
    setPage(0);
  }

  function handleSort(col: keyof Link) {
    if (sortCol === col) setSortAsc((a) => !a);
    else { setSortCol(col); setSortAsc(true); }
    setPage(0);
  }

  const filtered = useMemo(() => {
    let out = links;
    // Status filter (if nothing selected → show all)
    if (statusFilter.size > 0 && statusFilter.size < STATUS_OPTIONS.length) {
      out = out.filter((l) => statusFilter.has(l.status));
    }
    // Doc name text filter
    if (docFilter.trim()) {
      const q = docFilter.toLowerCase();
      out = out.filter((l) => l.source_doc.toLowerCase().includes(q));
    }
    // Sort
    out = [...out].sort((a, b) => {
      const av = String(a[sortCol] ?? "");
      const bv = String(b[sortCol] ?? "");
      return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    });
    return out;
  }, [links, statusFilter, docFilter, sortCol, sortAsc]);

  const pageCount  = Math.ceil(filtered.length / PAGE_SIZE);
  const pageItems  = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  function statusColor(s: string) {
    if (s === "ok")         return "var(--success)";
    if (s === "broken")     return "var(--danger)";
    if (s === "suspicious") return "#f59e0b";
    if (s === "unverified") return "#f59e0b";
    return "var(--text-muted)";
  }

  function SortArrow({ col }: { col: keyof Link }) {
    if (sortCol !== col) return <span style={{ opacity: 0.3 }}>↕</span>;
    return <span>{sortAsc ? "↑" : "↓"}</span>;
  }

  return (
    <div className="page">
      <button className="back-btn" onClick={onBack}>← Back to Dashboard</button>

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
        <div className="page-title" style={{ margin: 0 }}>🔗 Link Inspector</div>
        <button className="btn-ghost btn-sm" style={{ marginLeft: "auto" }} onClick={load}>↺ Refresh</button>
      </div>
      <div className="page-subtitle">
        Full link record table with status and document filters.
      </div>

      {/* ── Filters (Streamlit col1/col2) ── */}
      <div className="card" style={{ padding: "14px 20px" }}>
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap", alignItems: "flex-end" }}>
          {/* Status filter multiselect */}
          <div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Status filter
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              {STATUS_OPTIONS.map((opt) => {
                const active = statusFilter.has(opt.key);
                return (
                  <button
                    key={opt.key}
                    onClick={() => toggleStatus(opt.key)}
                    style={{
                      padding: "4px 12px", borderRadius: 16, fontSize: 12, cursor: "pointer",
                      border: `1px solid ${active ? opt.color : "var(--border-color)"}`,
                      background: active ? `${opt.color}18` : "transparent",
                      color: active ? opt.color : "var(--text-muted)",
                      fontWeight: active ? 600 : 400,
                      transition: "all 0.12s",
                    }}
                  >
                    {opt.label}
                    <span style={{ marginLeft: 4, opacity: 0.7, fontSize: 10 }}>
                      ({links.filter((l) => l.status === opt.key).length})
                    </span>
                  </button>
                );
              })}
              <button
                className="btn-ghost btn-sm"
                onClick={() => { setStatusFilter(new Set()); setPage(0); }}
              >
                All
              </button>
            </div>
          </div>

          {/* Doc name text filter */}
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Filter by document name
            </div>
            <input
              type="text"
              value={docFilter}
              onChange={(e) => { setDocFilter(e.target.value); setPage(0); }}
              placeholder="e.g. csr-sp-2026"
              style={{
                width: "100%", boxSizing: "border-box",
                padding: "7px 12px", borderRadius: 6,
                border: "1px solid var(--border-color)",
                fontSize: 13,
                background: "var(--card-bg)", color: "var(--text-primary)",
              }}
            />
          </div>
        </div>

        {/* Caption: "Showing X of Y link records" */}
        <div style={{ marginTop: 10, fontSize: 12, color: "var(--text-muted)" }}>
          Showing <strong>{filtered.length.toLocaleString()}</strong> of{" "}
          <strong>{links.length.toLocaleString()}</strong> link records
          {pageCount > 1 && ` · Page ${page + 1} / ${pageCount}`}
        </div>
      </div>

      {loading && (
        <div className="center-state"><div className="spinner" /><h3>Loading links…</h3></div>
      )}
      {error && (
        <div className="error-msg"><strong>Failed to load</strong>{error}</div>
      )}

      {!loading && !error && (
        <>
          {filtered.length === 0 ? (
            <div className="center-state">
              <div style={{ fontSize: 48, marginBottom: 12 }}>🔍</div>
              <h3>No links match current filters</h3>
              <p>Adjust status or document filters above.</p>
            </div>
          ) : (
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <thead>
                    <tr style={{ borderBottom: "2px solid var(--border-color)" }}>
                      {(
                        [
                          { col: "source_doc",  label: "Source Document" },
                          { col: "link_text",   label: "Link Text" },
                          { col: "status",      label: "Status" },
                          { col: "target_doc",  label: "Target Doc" },
                          { col: "target_anchor", label: "Target Anchor" },
                          { col: "confidence",  label: "Confidence" },
                          { col: "detected_by", label: "Detected By" },
                          { col: "error_msg",   label: "Error" },
                        ] as { col: keyof Link; label: string }[]
                      ).map(({ col, label }) => (
                        <th
                          key={col}
                          onClick={() => handleSort(col)}
                          style={{
                            padding: "10px 14px",
                            textAlign: "left",
                            fontSize: 11,
                            fontWeight: 700,
                            color: "var(--text-muted)",
                            textTransform: "uppercase",
                            letterSpacing: "0.05em",
                            cursor: "pointer",
                            userSelect: "none",
                            whiteSpace: "nowrap",
                            background: "var(--card-bg)",
                          }}
                        >
                          {label} <SortArrow col={col} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {pageItems.map((lnk, i) => (
                      <tr
                        key={i}
                        style={{
                          borderBottom: "1px solid var(--border-color)",
                          background: lnk.status === "broken"
                            ? "rgba(231,76,60,0.03)"
                            : i % 2 === 0 ? "transparent" : "rgba(0,0,0,0.012)",
                        }}
                      >
                        <td style={{ padding: "8px 14px", fontFamily: "monospace", fontSize: 11, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {lnk.source_doc}
                        </td>
                        <td style={{ padding: "8px 14px", fontWeight: 500, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {lnk.link_text}
                        </td>
                        <td style={{ padding: "8px 14px" }}>
                          <span style={{
                            display: "inline-block", padding: "2px 10px",
                            borderRadius: 10, fontSize: 11, fontWeight: 700,
                            color: statusColor(lnk.status),
                            background: `${statusColor(lnk.status)}18`,
                          }}>
                            {lnk.status.toUpperCase()}
                          </span>
                        </td>
                        <td style={{ padding: "8px 14px", fontFamily: "monospace", fontSize: 11, color: "var(--text-muted)", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {lnk.target_doc || "—"}
                        </td>
                        <td style={{ padding: "8px 14px", fontFamily: "monospace", fontSize: 11, color: "var(--text-muted)", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {lnk.target_anchor || "—"}
                        </td>
                        <td style={{ padding: "8px 14px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                            <div style={{
                              width: 44, height: 6, borderRadius: 3,
                              background: "var(--border-color)", overflow: "hidden", flexShrink: 0,
                            }}>
                              <div style={{
                                width: `${Math.round(lnk.confidence * 100)}%`,
                                height: "100%",
                                background: lnk.confidence >= 0.9 ? "var(--success)" : lnk.confidence >= 0.7 ? "#f59e0b" : "var(--danger)",
                                borderRadius: 3,
                              }} />
                            </div>
                            <span style={{ fontSize: 10, fontFamily: "monospace" }}>
                              {Math.round(lnk.confidence * 100)}%
                            </span>
                          </div>
                        </td>
                        <td style={{ padding: "8px 14px", fontSize: 11, color: "var(--text-muted)" }}>
                          {lnk.detected_by ? (
                            <span style={{
                              padding: "1px 6px", borderRadius: 4,
                              background: "var(--surface-sunken, rgba(0,0,0,0.04))",
                              fontFamily: "monospace", fontSize: 10,
                            }}>
                              {lnk.detected_by}
                            </span>
                          ) : "—"}
                        </td>
                        <td style={{
                          padding: "8px 14px", fontSize: 11,
                          color: lnk.error_msg ? "var(--danger)" : "var(--text-muted)",
                          maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}>
                          {lnk.error_msg || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {pageCount > 1 && (
                <div style={{
                  padding: "12px 20px", borderTop: "1px solid var(--border-color)",
                  display: "flex", alignItems: "center", gap: 8, fontSize: 12,
                }}>
                  <button className="btn-ghost btn-sm" disabled={page === 0} onClick={() => setPage(0)}>«</button>
                  <button className="btn-ghost btn-sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>‹ Prev</button>
                  <span style={{ color: "var(--text-muted)", flex: 1, textAlign: "center" }}>
                    Page {page + 1} of {pageCount} · {filtered.length.toLocaleString()} records
                  </span>
                  <button className="btn-ghost btn-sm" disabled={page >= pageCount - 1} onClick={() => setPage((p) => p + 1)}>Next ›</button>
                  <button className="btn-ghost btn-sm" disabled={page >= pageCount - 1} onClick={() => setPage(pageCount - 1)}>»</button>
                </div>
              )}
            </div>
          )}

          {/* Export buttons */}
          <div className="card" style={{ padding: "14px 20px" }}>
            <div className="btn-row">
              <button className="btn-success" onClick={() => api.exportCsv(activeRunId)}>⬇️ Download Full CSV</button>
              <button className="btn-success" onClick={() => api.exportXlsx(activeRunId)}>⬇️ Download XLSX</button>
              <button className="btn-ghost" onClick={() => window.print()}>🖨️ Print</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
