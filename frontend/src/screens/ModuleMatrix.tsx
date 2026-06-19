/**
 * Screen: Module Matrix  (Streamlit "_render_module_matrix" equivalent)
 *
 * Groups all link records by CTD module (m1–m5, derived from source_doc path)
 * and shows a per-module status breakdown table — colour-coded like a heatmap.
 *
 * Maps exactly to Streamlit's:
 *   df["module"] = df["source_doc"].apply(_module_of)
 *   grouped = df.groupby(["module","status"]).size().unstack()
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useActiveRun } from "../contexts/ActiveRun";
import type { Link, ModuleRow } from "../types";

interface Props { onBack: () => void; }

function moduleOf(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/");
  for (const p of parts) {
    if (/^m[1-5]/i.test(p)) return p.slice(0, 2).toLowerCase();
  }
  // Fallback: look for m1–m5 pattern anywhere in the filename
  const m = path.match(/\bm([1-5])/i);
  return m ? `m${m[1]}` : "other";
}

const MODULE_LABELS: Record<string, string> = {
  m1: "m1 — Regional",
  m2: "m2 — Summaries",
  m3: "m3 — Quality",
  m4: "m4 — Nonclinical",
  m5: "m5 — Clinical",
  other: "Other / Unknown",
};

function healthColor(ratio: number): string {
  // ratio = bad/total
  if (ratio === 0) return "rgba(39,174,96,0.12)";
  if (ratio < 0.05) return "rgba(241,196,15,0.12)";
  if (ratio < 0.15) return "rgba(230,126,34,0.12)";
  return "rgba(231,76,60,0.12)";
}

function HealthBadge({ val, total, kind }: { val: number; total: number; kind: "ok" | "broken" | "warn" }) {
  if (val === 0) return <span style={{ color: "var(--text-muted)", fontSize: 12 }}>—</span>;
  const colors = {
    ok:     { color: "var(--success)",   bg: "rgba(39,174,96,0.1)" },
    broken: { color: "var(--danger)",    bg: "rgba(231,76,60,0.1)" },
    warn:   { color: "#f59e0b",          bg: "rgba(245,158,11,0.1)" },
  };
  const { color, bg } = colors[kind];
  const pct = total ? Math.round(val / total * 100) : 0;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 8, fontSize: 12,
      fontWeight: 600, color, background: bg,
    }}>
      {val}
      <span style={{ fontSize: 10, fontWeight: 400, color, opacity: 0.8 }}>({pct}%)</span>
    </span>
  );
}

export function ModuleMatrix({ onBack }: Props) {
  const { activeRunId } = useActiveRun();
  const [links, setLinks] = useState<Link[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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

  // Build per-module rows (matches Streamlit groupby logic)
  const rows = useMemo<ModuleRow[]>(() => {
    const acc: Record<string, ModuleRow> = {};
    for (const lnk of links) {
      const mod = moduleOf(lnk.source_doc);
      if (!acc[mod]) acc[mod] = { module: mod, ok: 0, broken: 0, unverified: 0, suspicious: 0, total: 0 };
      acc[mod].total++;
      if (lnk.status === "ok")         acc[mod].ok++;
      else if (lnk.status === "broken") acc[mod].broken++;
      else if (lnk.status === "unverified") acc[mod].unverified++;
      else if (lnk.status === "suspicious") acc[mod].suspicious++;
    }
    const order = ["m1","m2","m3","m4","m5","other"];
    return Object.values(acc).sort((a, b) =>
      (order.indexOf(a.module) - order.indexOf(b.module)) || a.module.localeCompare(b.module)
    );
  }, [links]);

  const totalLinks = links.length;
  const totalBroken = links.filter((l) => l.status === "broken").length;

  return (
    <div className="page">
      <button className="back-btn" onClick={onBack}>← Back to Dashboard</button>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
        <div className="page-title" style={{ margin: 0 }}>📦 Module Health Matrix</div>
        <button className="btn-ghost btn-sm" style={{ marginLeft: "auto" }} onClick={load}>↺ Refresh</button>
      </div>
      <div className="page-subtitle">
        Per-CTD-module link health · {totalLinks.toLocaleString()} total links
        {totalBroken > 0 && (
          <span style={{ marginLeft: 8, color: "var(--danger)", fontWeight: 600 }}>
            · {totalBroken} broken
          </span>
        )}
      </div>

      {loading && (
        <div className="center-state"><div className="spinner" /><h3>Loading links…</h3></div>
      )}

      {error && (
        <div className="error-msg"><strong>Failed to load</strong>{error}</div>
      )}

      {!loading && !error && rows.length === 0 && (
        <div className="center-state">
          <div style={{ fontSize: 48, marginBottom: 12 }}>📭</div>
          <h3>No link records found</h3>
          <p>Run the pipeline first to generate link data.</p>
        </div>
      )}

      {!loading && rows.length > 0 && (
        <>
          {/* ── Summary cards ── */}
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 20 }}>
            {[
              { label: "Modules",   val: rows.length,    color: "var(--text-primary)" },
              { label: "Total",     val: totalLinks,     color: "var(--text-primary)" },
              { label: "OK",        val: links.filter((l) => l.status === "ok").length,         color: "var(--success)" },
              { label: "Broken",    val: totalBroken,    color: totalBroken > 0 ? "var(--danger)" : "var(--success)" },
              { label: "Unverified",val: links.filter((l) => l.status === "unverified").length, color: "#f59e0b" },
            ].map((s) => (
              <div key={s.label} className="card" style={{ padding: "12px 20px", textAlign: "center", flex: 1, minWidth: 90 }}>
                <div style={{ fontSize: 22, fontWeight: 700, fontFamily: "monospace", color: s.color }}>{s.val}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>{s.label}</div>
              </div>
            ))}
          </div>

          {/* ── Matrix table (Streamlit groupby equivalent) ── */}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{
              padding: "12px 20px", borderBottom: "1px solid var(--border-color)",
              fontSize: 13, fontWeight: 600,
            }}>
              Link Status by CTD Module
            </div>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid var(--border-color)" }}>
                    {["Module","Total","✅ OK","❌ Broken","⚠️ Unverified","❓ Suspicious","Health"].map((h) => (
                      <th key={h} style={{
                        padding: "10px 16px", textAlign: h === "Module" ? "left" : "center",
                        fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
                        textTransform: "uppercase", letterSpacing: "0.05em",
                        background: "var(--card-bg)",
                      }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, idx) => {
                    const badRatio = row.total ? (row.broken + row.suspicious) / row.total : 0;
                    const healthPct = row.total ? Math.round(row.ok / row.total * 100) : 100;
                    return (
                      <tr
                        key={row.module}
                        style={{
                          borderBottom: "1px solid var(--border-color)",
                          background: idx % 2 === 0
                            ? healthColor(badRatio)
                            : "transparent",
                        }}
                      >
                        <td style={{ padding: "12px 16px", fontWeight: 600 }}>
                          <div style={{ fontSize: 13 }}>{MODULE_LABELS[row.module] ?? row.module}</div>
                          <div style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "monospace" }}>{row.module}</div>
                        </td>
                        <td style={{ textAlign: "center", padding: "12px 16px" }}>
                          <span style={{ fontWeight: 700, fontFamily: "monospace", fontSize: 15 }}>{row.total}</span>
                        </td>
                        <td style={{ textAlign: "center", padding: "12px 8px" }}>
                          <HealthBadge val={row.ok} total={row.total} kind="ok" />
                        </td>
                        <td style={{ textAlign: "center", padding: "12px 8px" }}>
                          <HealthBadge val={row.broken} total={row.total} kind="broken" />
                        </td>
                        <td style={{ textAlign: "center", padding: "12px 8px" }}>
                          <HealthBadge val={row.unverified} total={row.total} kind="warn" />
                        </td>
                        <td style={{ textAlign: "center", padding: "12px 8px" }}>
                          <HealthBadge val={row.suspicious} total={row.total} kind="warn" />
                        </td>
                        <td style={{ textAlign: "center", padding: "12px 16px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6, justifyContent: "center" }}>
                            <div style={{
                              width: 80, height: 8, borderRadius: 4,
                              background: "var(--border-color)", overflow: "hidden",
                            }}>
                              <div style={{
                                width: `${healthPct}%`, height: "100%", borderRadius: 4,
                                background: healthPct >= 95 ? "var(--success)" : healthPct >= 80 ? "#f59e0b" : "var(--danger)",
                              }} />
                            </div>
                            <span style={{
                              fontSize: 11, fontFamily: "monospace", fontWeight: 600,
                              color: healthPct >= 95 ? "var(--success)" : healthPct >= 80 ? "#f59e0b" : "var(--danger)",
                            }}>
                              {healthPct}%
                            </span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                {/* Totals row */}
                <tfoot>
                  <tr style={{ borderTop: "2px solid var(--border-color)", background: "var(--surface-sunken, rgba(0,0,0,0.02))" }}>
                    <td style={{ padding: "10px 16px", fontWeight: 700, fontSize: 13 }}>TOTAL</td>
                    <td style={{ textAlign: "center", padding: "10px 16px", fontWeight: 700, fontFamily: "monospace" }}>{totalLinks}</td>
                    <td style={{ textAlign: "center", padding: "10px 8px", fontWeight: 700, color: "var(--success)" }}>
                      {links.filter((l) => l.status === "ok").length}
                    </td>
                    <td style={{ textAlign: "center", padding: "10px 8px", fontWeight: 700, color: "var(--danger)" }}>
                      {totalBroken}
                    </td>
                    <td style={{ textAlign: "center", padding: "10px 8px", fontWeight: 700, color: "#f59e0b" }}>
                      {links.filter((l) => l.status === "unverified").length}
                    </td>
                    <td style={{ textAlign: "center", padding: "10px 8px", fontWeight: 700, color: "#f59e0b" }}>
                      {links.filter((l) => l.status === "suspicious").length}
                    </td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>

          {/* ── Legend ── */}
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 11, color: "var(--text-muted)", marginTop: 4, padding: "0 4px" }}>
            {[
              { color: "rgba(39,174,96,0.2)",  label: "0% bad — healthy" },
              { color: "rgba(241,196,15,0.2)", label: "<5% bad" },
              { color: "rgba(230,126,34,0.2)", label: "5–15% bad" },
              { color: "rgba(231,76,60,0.2)",  label: ">15% bad — critical" },
            ].map((l) => (
              <span key={l.label} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ width: 12, height: 12, borderRadius: 2, background: l.color, display: "inline-block", border: "1px solid rgba(0,0,0,0.08)" }} />
                {l.label}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
