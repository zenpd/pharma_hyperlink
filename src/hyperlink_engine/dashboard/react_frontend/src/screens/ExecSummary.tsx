/**
 * Screen 1 — Executive Summary / Dossier Overview.
 *
 * Layout: `1fr 340px` grid below TopBar+DossierBar.
 *   Left:  KPI strip (gauge + 4 KPI cards) + heatmap + trend
 *   Right: activity feed
 */

import React from "react";
import {
  CtdCrumb,
  Icon,
  RadialGauge,
  SevChip,
  Sparkline,
  TopBar,
  DossierBar,
} from "../components/shared";
import type { IconName } from "../components/shared";

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
    y: PAD.t + innerH - ((d.r - min) / (max - min)) * innerH,
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

export const ExecSummary: React.FC<ExecSummaryProps> = ({ theme = "light" }) => {
  const categories = [
    "Cross-doc",
    "TOC anchors",
    "Study refs",
    "Lit citations",
    "Hyperlink labels",
    "TS/datasets",
  ];
  const modules = ["m1", "m2", "m3", "m4", "m5"];
  const heat: number[][] = [
    [0.97, 0.94, 0.88, 0.82, 0.91, 0.79],
    [0.95, 0.92, 0.86, 0.74, 0.88, 0.83],
    [0.71, 0.68, 0.55, 0.42, 0.78, 0.61],
    [0.83, 0.81, 0.69, 0.58, 0.85, 0.72],
    [0.62, 0.58, 0.47, 0.39, 0.74, 0.51],
  ];
  const heatColor = (v: number): string => {
    if (v >= 0.95) return "var(--heat-5)";
    if (v >= 0.85) return "var(--heat-4)";
    if (v >= 0.7) return "var(--heat-3)";
    if (v >= 0.55) return "var(--heat-2)";
    if (v >= 0.4) return "var(--heat-1)";
    return "var(--heat-0)";
  };

  const trend: TrendPoint[] = [
    { v: "0001", r: 48 },
    { v: "0002", r: 56 },
    { v: "0003", r: 61 },
    { v: "0004", r: 65 },
    { v: "0005", r: 72 },
    { v: "0006", r: 71 },
    { v: "0007", r: 78 },
    { v: "0008", r: 84 },
    { v: "0009", r: 82 },
  ];

  interface ActivityItem {
    kind: keyof typeof ACTIVITY_STYLE;
    icon: IconName;
    who: string;
    what: string;
    when: string;
    meta: React.ReactNode;
  }

  const activity: ActivityItem[] = [
    {
      kind: "success",
      icon: "check-circle",
      who: "V. Iyer · QC Lead",
      what: "Approved gate review for m2.5.3",
      when: "14:38",
      meta: <span className="mono chip outline chip-sm">Step 4/5</span>,
    },
    {
      kind: "running",
      icon: "play",
      who: "Pipeline · run-0091",
      what: "Validation pass started",
      when: "14:22",
      meta: (
        <span className="chip info chip-sm">
          <Icon name="cpu" size={9} />
          On-prem
        </span>
      ),
    },
    {
      kind: "warning",
      icon: "alert",
      who: "Engine",
      what: "34 anomalies flagged in m3.2.S",
      when: "14:01",
      meta: <span className="chip warning chip-sm">Style mutation</span>,
    },
    {
      kind: "info",
      icon: "shield-check",
      who: "Audit",
      what: "Sequence 0009 sealed · hash 0xa3f…",
      when: "13:54",
      meta: null,
    },
    {
      kind: "success",
      icon: "sparkles",
      who: "Engine",
      what: "Auto-resolved 47 cross-doc refs in m5.3",
      when: "13:12",
      meta: <span className="mono chip outline chip-sm">+47</span>,
    },
    {
      kind: "neutral",
      icon: "user",
      who: "D. Park · Author",
      what: "Reassigned 12 anomalies to SME pool",
      when: "12:46",
      meta: null,
    },
    {
      kind: "warning",
      icon: "link-broken",
      who: "Engine",
      what: "6 broken targets in Clinical Overview",
      when: "12:30",
      meta: <span className="chip danger chip-sm">Blocker</span>,
    },
    {
      kind: "info",
      icon: "git-branch",
      who: "M. Tanaka · RA",
      what: "Branched draft for PMDA Q-response",
      when: "11:18",
      meta: null,
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
            <button className="btn btn-primary btn-sm">
              <Icon name="download" size={13} color="#fff" /> Export Submission Package
            </button>
          </>
        }
      >
        <Icon name="package" size={15} color="var(--text-2)" />
        <span style={{ fontWeight: 600 }}>NDA 215842 · Brenzavir 50mg Tablets</span>
        <span className="mono" style={{ fontSize: 11, color: "var(--text-3)" }}>
          IND-104772
        </span>
        <div className="divider-v" style={{ height: 16, margin: "0 4px" }} />
        <span style={{ color: "var(--text-2)", fontSize: 12 }}>Sequence</span>
        <span className="mono chip outline">0009 — Initial NDA</span>
        <Icon name="chevron-down" size={12} color="var(--text-3)" />
        <div className="divider-v" style={{ height: 16, margin: "0 4px" }} />
        <span className="chip success">
          <Icon name="check" size={10} /> Inference: On-prem
        </span>
        <span className="chip outline">PMDA · FDA · EMA</span>
      </DossierBar>

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
              <RadialGauge value={82} />
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
                  Submission-ready
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    fontSize: 12,
                    color: "var(--success)",
                  }}
                >
                  <Icon name="arrow-up" size={11} color="var(--success)" />
                  <span className="mono num">+4</span>
                  <span style={{ color: "var(--text-3)" }}>vs 0008</span>
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
                    13 blockers remaining
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
              {[
                {
                  label: "Total Hyperlinks",
                  value: "2,147",
                  sub: (
                    <>
                      <span className="mono">1,894</span> auto ·{" "}
                      <span className="mono">253</span> manual
                    </>
                  ),
                  spark: [120, 180, 240, 380, 520, 740, 980, 1340, 1620, 1894, 2080, 2147],
                  sparkColor: "var(--brand)",
                  badge: null as React.ReactNode,
                  custom: null as React.ReactNode,
                },
                {
                  label: "Broken Links",
                  value: "13",
                  sub: <span style={{ color: "var(--danger-text)" }}>↓ 47 fixed since 0008</span>,
                  spark: [89, 76, 64, 58, 42, 38, 31, 24, 18, 16, 14, 13],
                  sparkColor: "var(--danger)",
                  badge: <SevChip kind="blocker" label="Blocker" />,
                  custom: null,
                },
                {
                  label: "Anomalies",
                  value: "127",
                  sub: (
                    <>
                      <span style={{ color: "var(--warning-text)" }}>34 warn</span>
                      {" · "}
                      <span style={{ color: "var(--info-text)" }}>93 info</span>
                    </>
                  ),
                  spark: [220, 198, 176, 158, 142, 138, 132, 130, 128, 127, 127, 127],
                  sparkColor: "var(--warning)",
                  badge: null,
                  custom: null,
                },
                {
                  label: "Pipeline Status",
                  value: (<span style={{ fontSize: 22 }}>500 / 500</span>) as unknown as string,
                  sub: (
                    <>
                      <span className="mono">3h 42m</span> · finished 14:22
                    </>
                  ),
                  spark: null as number[] | null,
                  sparkColor: "var(--brand)",
                  badge: null,
                  custom: (
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
                      <span className="chip success">
                        <Icon name="check" size={10} />
                        Complete
                      </span>
                    </div>
                  ),
                },
              ].map((k, i) => (
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
                  {k.spark && (
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
                    CTD modules × link categories · readiness 0–100
                  </div>
                </div>
                <div style={{ display: "flex", gap: 4 }}>
                  <button
                    className="btn btn-sm btn-ghost"
                    style={{ color: "var(--text-1)", background: "var(--surface-raised)" }}
                  >
                    Readiness
                  </button>
                  <button className="btn btn-sm btn-ghost" style={{ color: "var(--text-2)" }}>
                    Severity
                  </button>
                  <button className="btn btn-sm btn-ghost" style={{ color: "var(--text-2)" }}>
                    Volume
                  </button>
                </div>
              </div>

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
                {modules.map((m, ri) => (
                  <React.Fragment key={m}>
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
                      <span>{m}</span>
                      <span className="mono" style={{ fontSize: 10, color: "var(--text-3)" }}>
                        {Math.round((heat[ri].reduce((a, b) => a + b, 0) / heat[ri].length) * 100)}
                      </span>
                    </div>
                    {heat[ri].map((v, ci) => (
                      <div
                        key={ci}
                        className="heat"
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
                <span>Low readiness</span>
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
                    Readiness across Sequences
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>0001 → 0009</div>
                </div>
                <span className="chip outline mono">Δ +34 since 0001</span>
              </div>

              <TrendChart data={trend} />

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
                    Avg run time
                  </div>
                  <div
                    className="mono num"
                    style={{ color: "var(--text-1)", fontSize: 14, fontWeight: 500, marginTop: 2 }}
                  >
                    3h 28m
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
                    Manual rework rate
                  </div>
                  <div
                    className="mono num"
                    style={{ color: "var(--text-1)", fontSize: 14, fontWeight: 500, marginTop: 2 }}
                  >
                    11.8%
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
            <div style={{ display: "flex", gap: 4 }}>
              {["All", "Runs", "Audit"].map((label, idx) => (
                <button
                  key={label}
                  className="btn btn-sm btn-ghost"
                  style={{
                    height: 24,
                    padding: "0 6px",
                    fontSize: 11,
                    color: idx === 0 ? "var(--text-1)" : "var(--text-2)",
                    background: idx === 0 ? "var(--surface)" : "transparent",
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div style={{ flex: 1, overflow: "hidden", padding: "0 4px" }}>
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

// Suppress unused-warning for CtdCrumb import (kept available for parity)
export const _ctdSentinel = CtdCrumb;
