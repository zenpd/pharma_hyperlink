/**
 * Screen 1 — Executive Summary / Dossier Overview.  [LIVE]
 *
 * Every figure on this screen is sourced from the FastAPI backend through
 * `useReportData` (score, links, anomalies, detection-trace) for the run
 * selected in the Run Selector — or the seeded demo dossier when none is
 * chosen. The layout, gauge, heatmap, trend and activity feed are unchanged;
 * only their inputs are now live.
 */

import React from "react";
import {
  Icon,
  RadialGauge,
  SevChip,
  Sparkline,
  TopBar,
  DossierBar,
} from "../components/shared";
import type { IconName } from "../components/shared";
import { useActiveRun } from "../contexts/ActiveRun";
import {
  anomalyCounts,
  avgConfidence,
  moduleAggs,
  moduleOf,
  ratio,
  statusCounts,
  traceTotals,
  useReportData,
} from "../live";
import { api } from "../api";

interface ActivityKindStyle {
  bg: string;
  color: string;
}

const ACTIVITY_STYLE: Record<string, ActivityKindStyle> = {
  success: { bg: "var(--success-tint)", color: "var(--success)" },
  warning: { bg: "var(--warning-tint)", color: "var(--warning)" },
  info: { bg: "var(--info-tint)", color: "var(--info)" },
  running: { bg: "var(--brand-tint)", color: "var(--brand)" },
  neutral: { bg: "var(--neutral-tint)", color: "var(--text-2)" },
  blocker: { bg: "var(--danger-tint)", color: "var(--danger)" },
};

interface TrendPoint {
  v: string;
  r: number;
}

const TrendChart: React.FC<{ data: TrendPoint[] }> = ({ data }) => {
  const W = 320,
    H = 140,
    PAD = { l: 28, r: 8, t: 8, b: 18 };
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;
  const min = 40,
    max = 100;
  const step = innerW / (data.length - 1);
  const points = data.map((d, i) => ({
    x: PAD.l + i * step,
    y: PAD.t + innerH - ((Math.max(min, Math.min(max, d.r)) - min) / (max - min)) * innerH,
    ...d,
  }));
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
  const area = `${path} L ${points[points.length - 1].x} ${PAD.t + innerH} L ${points[0].x} ${
    PAD.t + innerH
  } Z`;
  const gateY = PAD.t + innerH - ((95 - min) / (max - min)) * innerH;
  return (
    <svg
      width="100%"
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      style={{ display: "block" }}
    >
      {[50, 75, 100].map((p) => {
        if (p < min) return null;
        const yClamped = PAD.t + innerH - ((p - min) / (max - min)) * innerH;
        return (
          <g key={p}>
            <line
              x1={PAD.l}
              x2={W - PAD.r}
              y1={yClamped}
              y2={yClamped}
              stroke="var(--border)"
              strokeDasharray="2 3"
            />
            <text
              x={PAD.l - 6}
              y={yClamped + 3}
              fontSize="9"
              fill="var(--text-3)"
              textAnchor="end"
              fontFamily="var(--ff-mono)"
            >
              {p}
            </text>
          </g>
        );
      })}
      {/* gate */}
      <line x1={PAD.l} x2={W - PAD.r} y1={gateY} y2={gateY} stroke="var(--success)" strokeDasharray="3 2" />
      <text
        x={W - PAD.r - 2}
        y={gateY - 3}
        fontSize="9"
        fill="var(--success)"
        textAnchor="end"
        fontFamily="var(--ff-mono)"
      >
        gate 95
      </text>
      <path d={area} fill="var(--brand-tint)" opacity="0.6" />
      <path d={path} fill="none" stroke="var(--brand)" strokeWidth="1.5" strokeLinejoin="round" />
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={p.x} cy={p.y} r="2.5" fill="var(--surface)" stroke="var(--brand)" strokeWidth="1.5" />
          <text
            x={p.x}
            y={H - 4}
            fontSize="9"
            fill="var(--text-3)"
            textAnchor="middle"
            fontFamily="var(--ff-mono)"
          >
            {p.v}
          </text>
        </g>
      ))}
      <circle
        cx={points[points.length - 1].x}
        cy={points[points.length - 1].y}
        r="4"
        fill="var(--brand)"
      />
    </svg>
  );
};

export interface ExecSummaryProps {
  theme?: "light" | "dark";
}

interface ActivityItem {
  kind: keyof typeof ACTIVITY_STYLE;
  icon: IconName;
  who: string;
  what: string;
  when: string;
  meta: React.ReactNode;
}

export const ExecSummary: React.FC<ExecSummaryProps> = ({ theme = "light" }) => {
  const { activeRunId, runs } = useActiveRun();
  const { score, links, anomalies, trace, loading, error } = useReportData(activeRunId);

  // ── Derived live figures ──────────────────────────────────────────────
  const sc = statusCounts(links);
  const anc = anomalyCounts(anomalies);
  const tt = traceTotals(trace);
  const mods = moduleAggs(links);
  const readiness = Math.round(score?.score ?? 0);
  const grade = score?.grade ?? "—";
  const broken = score?.broken_links ?? sc.broken;
  const blockers = score?.blocker_anomalies ?? anc.blocker;
  const totalLinks = links.length || trace?.total_links || 0;
  const docCount = trace?.total_docs || new Set(links.map((l) => l.source_doc)).size;
  const ready = score?.is_submission_ready ?? false;
  const dossierId = score?.dossier_id ?? "demo";

  // Per-module detection-layer rollup (for the heatmap's regex/ner/llm cols).
  const modTrace = new Map<string, { regex: number; ner: number; llm: number; total: number }>();
  trace?.per_doc.forEach((d) => {
    const m = moduleOf(d.doc_name);
    const cur = modTrace.get(m) ?? { regex: 0, ner: 0, llm: 0, total: 0 };
    cur.regex += d.regex_only;
    cur.ner += d.ner_triggered;
    cur.llm += d.llm_triggered;
    cur.total += d.total_links;
    modTrace.set(m, cur);
  });

  const categories = ["OK rate", "No broken", "No suspect", "Regex", "NER", "LLM"];
  const heat: number[][] = mods.map((m) => {
    const mt = modTrace.get(m.module) ?? { regex: 0, ner: 0, llm: 0, total: 0 };
    return [
      ratio(m.ok, m.total),
      m.total ? 1 - ratio(m.broken, m.total) : 0,
      m.total ? 1 - ratio(m.suspicious, m.total) : 0,
      ratio(mt.regex, mt.total),
      ratio(mt.ner, mt.total),
      ratio(mt.llm, mt.total),
    ];
  });
  const heatColor = (v: number): string => {
    if (v >= 0.95) return "var(--heat-5)";
    if (v >= 0.85) return "var(--heat-4)";
    if (v >= 0.7) return "var(--heat-3)";
    if (v >= 0.55) return "var(--heat-2)";
    if (v >= 0.4) return "var(--heat-1)";
    return "var(--heat-0)";
  };

  // Run-history trend (oldest → newest). Needs ≥2 completed runs to plot.
  const ordered = [...runs].reverse();
  const trend: TrendPoint[] = ordered
    .filter((r) => r.score != null)
    .map((r, i) => ({ v: r.run_id.slice(-4) || String(i + 1), r: r.score as number }));

  // ── Live activity feed ────────────────────────────────────────────────
  const activity: ActivityItem[] = [];
  if (score) {
    activity.push({
      kind: ready ? "success" : "warning",
      icon: "target",
      who: "Readiness",
      what: `Score ${readiness} (${grade}) · ${ready ? "submission-ready" : "not yet ready"}`,
      when: "now",
      meta: <span className={`chip ${ready ? "success" : "warning"} chip-sm`}>gate ≥ 95</span>,
    });
  }
  activity.push({
    kind: "info",
    icon: "cpu",
    who: "Engine",
    what: `${totalLinks} links across ${docCount} document${docCount === 1 ? "" : "s"}`,
    when: activeRunId || "demo",
    meta: (
      <span className="chip info chip-sm">
        <Icon name="cpu" size={9} /> On-prem
      </span>
    ),
  });
  if (tt.total) {
    activity.push({
      kind: "info",
      icon: "sparkles",
      who: "Detection",
      what: `${tt.llm} via LLM · ${tt.ner} NER · ${tt.regex} regex-only`,
      when: "trace",
      meta: <span className="mono chip outline chip-sm">{Math.round(avgConfidence(links) * 100)}% avg</span>,
    });
  }
  links
    .filter((l) => l.status === "broken")
    .slice(0, 4)
    .forEach((l) =>
      activity.push({
        kind: "blocker",
        icon: "link-broken",
        who: l.source_doc,
        what: `Broken → ${l.target_doc || l.target_anchor || "unresolved"}`,
        when: "",
        meta: <span className="chip danger chip-sm">Blocker</span>,
      }),
    );
  anomalies.slice(0, 6).forEach((a) =>
    activity.push({
      kind: a.severity === "blocker" ? "blocker" : a.severity === "warning" ? "warning" : "info",
      icon: "alert",
      who: a.document || "Engine",
      what: a.text,
      when: "",
      meta: <span className="chip outline chip-sm">{a.kind}</span>,
    }),
  );

  // KPI cards (live)
  const kpis = [
    {
      label: "Total Hyperlinks",
      value: totalLinks.toLocaleString(),
      sub: (
        <>
          <span className="mono">{sc.ok}</span> ok · <span className="mono">{sc.unverified}</span> unverified
        </>
      ),
      spark: mods.map((m) => m.total),
      sparkColor: "var(--brand)",
      badge: null as React.ReactNode,
      custom: null as React.ReactNode,
    },
    {
      label: "Broken Links",
      value: String(broken),
      sub: <span style={{ color: broken ? "var(--danger-text)" : "var(--success-text)" }}>{broken ? "needs fixing" : "none — clean"}</span>,
      spark: mods.map((m) => m.broken),
      sparkColor: "var(--danger)",
      badge: broken ? <SevChip kind="blocker" label="Blocker" /> : <SevChip kind="success" label="Clean" />,
      custom: null,
    },
    {
      label: "Anomalies",
      value: String(anomalies.length),
      sub: (
        <>
          <span style={{ color: "var(--warning-text)" }}>{anc.warning} warn</span>
          {" · "}
          <span style={{ color: "var(--info-text)" }}>{anc.info} info</span>
        </>
      ),
      spark: [anc.blocker, anc.warning, anc.info],
      sparkColor: "var(--warning)",
      badge: null,
      custom: null,
    },
    {
      label: "Data Source",
      value: (<span style={{ fontSize: 20 }}>{activeRunId ? "Live run" : "Demo seed"}</span>) as unknown as string,
      sub: <span className="mono" style={{ fontSize: 11 }}>{activeRunId || dossierId}</span>,
      spark: null as number[] | null,
      sparkColor: "var(--brand)",
      badge: null,
      custom: (
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
          <span className={`chip ${ready ? "success" : "warning"}`}>
            <Icon name={ready ? "check" : "clock"} size={10} />
            {ready ? "Ready" : "In review"}
          </span>
        </div>
      ),
    },
  ];

  return (
    <div className={`hv-root ${theme === "dark" ? "theme-dark" : ""}`}>
      <TopBar theme={theme} activeTab="Dashboard" />
      <DossierBar
        right={
          <>
            <button className="btn btn-secondary btn-sm">
              <Icon name="history" size={13} /> Versions
            </button>
            <button className="btn btn-secondary btn-sm">
              <Icon name="shield-check" size={13} color="var(--success)" /> 21 CFR Audit Log
            </button>
            <button className="btn btn-primary btn-sm" onClick={() => api.exportXlsx(activeRunId)}>
              <Icon name="download" size={13} color="#fff" /> Export Submission Package
            </button>
          </>
        }
      >
        <Icon name="package" size={15} color="var(--text-2)" />
        <span style={{ fontWeight: 600 }}>{dossierId}</span>
        <div className="divider-v" style={{ height: 16, margin: "0 4px" }} />
        <span style={{ color: "var(--text-2)", fontSize: 12 }}>Source</span>
        <span className="mono chip outline">{activeRunId ? activeRunId : "Demo seed dossier"}</span>
        <div className="divider-v" style={{ height: 16, margin: "0 4px" }} />
        <span className="chip success">
          <Icon name="check" size={10} /> Inference: On-prem
        </span>
        <span className="chip outline">Grade {grade}</span>
        {loading && <span className="chip outline chip-sm mono">loading…</span>}
      </DossierBar>

      {error && (
        <div
          style={{
            padding: "8px 16px",
            background: "var(--danger-tint)",
            color: "var(--danger-text)",
            fontSize: 12,
            borderBottom: "1px solid var(--border)",
          }}
        >
          <Icon name="alert" size={12} color="var(--danger)" style={{ verticalAlign: -1, marginRight: 6 }} />
          {error}
        </div>
      )}

      <div
        style={{
          flex: 1,
          display: "grid",
          gridTemplateColumns: "1fr 340px",
          minHeight: 0,
        }}
      >
        {/* LEFT */}
        <div
          style={{
            padding: 16,
            display: "flex",
            flexDirection: "column",
            gap: 12,
            overflow: "hidden",
          }}
        >
          {/* KPI Strip */}
          <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 12 }}>
            <div
              className="card"
              style={{ padding: 16, display: "flex", alignItems: "center", gap: 16 }}
            >
              <RadialGauge value={readiness} />
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--text-3)",
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                  }}
                >
                  Overall Readiness
                </div>
                <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text-1)" }}>
                  {ready ? "Submission-ready" : "Not yet ready"}
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    fontSize: 12,
                    color: ready ? "var(--success)" : "var(--warning)",
                  }}
                >
                  <Icon name={ready ? "check" : "alert"} size={11} color={ready ? "var(--success)" : "var(--warning)"} />
                  <span className="mono num">{grade}</span>
                  <span style={{ color: "var(--text-3)" }}>grade</span>
                </div>
                <div
                  style={{
                    marginTop: 8,
                    paddingTop: 8,
                    borderTop: "1px solid var(--border)",
                    fontSize: 11,
                    color: "var(--text-2)",
                  }}
                >
                  <div>
                    Gate threshold{" "}
                    <span className="mono" style={{ color: "var(--text-1)" }}>
                      ≥ 95
                    </span>
                  </div>
                  <div
                    className="mono"
                    style={{ fontSize: 10, color: "var(--text-3)", marginTop: 2 }}
                  >
                    {blockers} blocker{blockers === 1 ? "" : "s"} remaining
                  </div>
                </div>
              </div>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(4, 1fr)",
                gap: 12,
              }}
            >
              {kpis.map((k, i) => (
                <div
                  key={i}
                  className="card"
                  style={{ padding: 14, display: "flex", flexDirection: "column", gap: 6 }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      fontSize: 11,
                      color: "var(--text-3)",
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                    }}
                  >
                    <span>{k.label}</span>
                    {k.badge}
                  </div>
                  <div
                    className="mono num"
                    style={{
                      fontSize: 28,
                      fontWeight: 600,
                      color: "var(--text-1)",
                      letterSpacing: "-0.02em",
                      lineHeight: 1.1,
                    }}
                  >
                    {k.value}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-2)" }}>{k.sub}</div>
                  {k.spark && k.spark.length > 1 && (
                    <div style={{ marginTop: 4 }}>
                      <Sparkline data={k.spark} width={200} height={26} color={k.sparkColor} />
                    </div>
                  )}
                  {k.custom}
                </div>
              ))}
            </div>
          </div>

          {/* Heatmap + Trend */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1.4fr 1fr",
              gap: 12,
              flex: 1,
              minHeight: 0,
            }}
          >
            <div
              className="card"
              style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-1)" }}>
                    Module Health Matrix
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>
                    CTD modules × link quality &amp; detection coverage · 0–100
                  </div>
                </div>
                <span className="chip outline mono">{mods.length} module{mods.length === 1 ? "" : "s"}</span>
              </div>

              {mods.length === 0 ? (
                <div style={{ flex: 1, display: "grid", placeItems: "center", color: "var(--text-3)", fontSize: 13 }}>
                  {loading ? "Loading link data…" : "No link data for this source"}
                </div>
              ) : (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: `60px repeat(${categories.length}, 1fr)`,
                    gap: 2,
                    alignItems: "stretch",
                  }}
                >
                  <div />
                  {categories.map((c) => (
                    <div
                      key={c}
                      style={{
                        fontSize: 10,
                        color: "var(--text-2)",
                        textAlign: "center",
                        padding: "4px 2px",
                        lineHeight: 1.2,
                      }}
                    >
                      {c}
                    </div>
                  ))}
                  {mods.map((m, ri) => (
                    <React.Fragment key={m.module}>
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          paddingRight: 8,
                          fontSize: 12,
                          color: "var(--text-1)",
                          fontWeight: 500,
                        }}
                      >
                        <span>{m.module}</span>
                        <span className="mono" style={{ fontSize: 10, color: "var(--text-3)" }}>
                          {Math.round((heat[ri].reduce((a, b) => a + b, 0) / heat[ri].length) * 100)}
                        </span>
                      </div>
                      {heat[ri].map((v, ci) => (
                        <div
                          key={ci}
                          className="heat"
                          title={`${m.module} · ${categories[ci]} · ${Math.round(v * 100)}`}
                          style={{
                            background: heatColor(v),
                            borderRadius: 2,
                            minHeight: 44,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            color: v >= 0.7 ? "#fff" : "var(--text-1)",
                            fontSize: 12,
                            fontFamily: "var(--ff-mono)",
                            cursor: "pointer",
                          }}
                        >
                          {Math.round(v * 100)}
                        </div>
                      ))}
                    </React.Fragment>
                  ))}
                </div>
              )}

              <div
                style={{
                  marginTop: "auto",
                  paddingTop: 10,
                  borderTop: "1px solid var(--border)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  fontSize: 11,
                  color: "var(--text-2)",
                }}
              >
                <span>Low</span>
                <div style={{ display: "flex", gap: 2 }}>
                  {[
                    "var(--heat-0)",
                    "var(--heat-1)",
                    "var(--heat-2)",
                    "var(--heat-3)",
                    "var(--heat-4)",
                    "var(--heat-5)",
                  ].map((c) => (
                    <div key={c} style={{ width: 28, height: 12, background: c, borderRadius: 2 }} />
                  ))}
                </div>
                <span>High</span>
              </div>
            </div>

            <div
              className="card"
              style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-1)" }}>
                    Readiness across Runs
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>
                    {trend.length >= 2 ? `${trend[0].v} → ${trend[trend.length - 1].v}` : "completed runs"}
                  </div>
                </div>
                <span className="chip outline mono">{runs.length} runs</span>
              </div>

              {trend.length >= 2 ? (
                <TrendChart data={trend} />
              ) : (
                <div
                  style={{
                    height: 140,
                    display: "grid",
                    placeItems: "center",
                    textAlign: "center",
                    color: "var(--text-3)",
                    fontSize: 12,
                    lineHeight: 1.5,
                  }}
                >
                  <div>
                    <div style={{ fontSize: 32, fontWeight: 600, color: "var(--text-1)" }} className="mono num">
                      {readiness}
                    </div>
                    Run a few pipelines — readiness
                    <br />
                    history charts here after 2+ runs.
                  </div>
                </div>
              )}

              <div
                style={{
                  marginTop: "auto",
                  paddingTop: 10,
                  borderTop: "1px solid var(--border)",
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 8,
                  fontSize: 11,
                }}
              >
                <div>
                  <div
                    style={{
                      color: "var(--text-3)",
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                      fontSize: 10,
                    }}
                  >
                    Avg confidence
                  </div>
                  <div
                    className="mono num"
                    style={{ color: "var(--text-1)", fontSize: 14, fontWeight: 500, marginTop: 2 }}
                  >
                    {Math.round(avgConfidence(links) * 100)}%
                  </div>
                </div>
                <div>
                  <div
                    style={{
                      color: "var(--text-3)",
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                      fontSize: 10,
                    }}
                  >
                    Verified rate
                  </div>
                  <div
                    className="mono num"
                    style={{ color: "var(--text-1)", fontSize: 14, fontWeight: 500, marginTop: 2 }}
                  >
                    {totalLinks ? Math.round(ratio(sc.ok, totalLinks) * 100) : 0}%
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT RAIL — Activity */}
        <aside
          style={{
            borderLeft: "1px solid var(--border)",
            background: "var(--surface-sunken)",
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
          }}
        >
          <div
            style={{
              padding: "14px 16px",
              borderBottom: "1px solid var(--border)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600 }}>Activity</div>
            <span className="chip outline chip-sm mono">{activity.length}</span>
          </div>
          <div style={{ flex: 1, overflow: "auto", padding: "0 4px" }}>
            {activity.length === 0 && (
              <div style={{ padding: 20, color: "var(--text-3)", fontSize: 12, textAlign: "center" }}>
                {loading ? "Loading…" : "No activity for this source."}
              </div>
            )}
            {activity.map((a, i) => {
              const s = ACTIVITY_STYLE[a.kind] ?? ACTIVITY_STYLE.neutral;
              return (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    gap: 10,
                    padding: "10px 12px",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  <div
                    style={{
                      width: 24,
                      height: 24,
                      borderRadius: 4,
                      display: "grid",
                      placeItems: "center",
                      flexShrink: 0,
                      background: s.bg,
                      color: s.color,
                    }}
                  >
                    <Icon name={a.icon} size={13} color="currentColor" />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, color: "var(--text-1)", lineHeight: 1.35 }}>
                      <span style={{ fontWeight: 500 }}>{a.who}</span>{" "}
                      <span style={{ color: "var(--text-2)" }}>{a.what}</span>
                    </div>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        marginTop: 4,
                      }}
                    >
                      <span className="mono" style={{ fontSize: 10, color: "var(--text-3)" }}>
                        {a.when}
                      </span>
                      {a.meta}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </aside>
      </div>
    </div>
  );
};
