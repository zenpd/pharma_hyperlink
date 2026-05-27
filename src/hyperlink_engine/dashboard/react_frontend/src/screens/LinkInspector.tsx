/**
 * Screen 3 — Link Inspector.
 *
 * Master-detail layout. Includes empty / loading / error states so the
 * caller can render the same screen for every state-of-the-world.
 *
 * Compliance: the error state explicitly states "No data has been
 * transmitted off-network" — this is a regulated reassurance per the
 * design README, not flavor text.
 */

import React, { useEffect } from "react";
import {
  CodePath,
  ConfidenceMeter,
  CtdCrumb,
  DossierBar,
  Icon,
  SevChip,
  SeverityIcon,
  TopBar,
} from "../components/shared";
import type { SeverityKind } from "../components/shared";

export type InspectorState = "data" | "empty" | "loading" | "error";

interface LinkRow {
  id: string;
  text: string;
  target: string;
  sev: SeverityKind;
  conf: number;
  type: string;
  src: string;
  active?: boolean;
}

const LINKS: LinkRow[] = [
  { id: "L-00214", text: "see Section 2.5.4.3", target: "m2.5.4#sec-2-5-4-3", sev: "blocker", conf: 41, type: "Broken target", src: "Pivotal Design Rationale" },
  { id: "L-00215", text: "Study CBV-301", target: "m5.3.5.1/CBV-301-CSR.pdf#p32", sev: "warning", conf: 73, type: "Stale Study ID", src: "Pivotal Design Rationale", active: true },
  { id: "L-00216", text: "cf. Table 14-2.1", target: "m5.3.5.3/T14-2.1.pdf", sev: "success", conf: 96, type: "Resolved", src: "Pivotal Design Rationale" },
  { id: "L-00217", text: "Figure 7", target: "m2.7.3/figure-7.svg", sev: "success", conf: 98, type: "Resolved", src: "Pivotal Design Rationale" },
  { id: "L-00218", text: "see Appendix C", target: "— unresolved —", sev: "blocker", conf: 22, type: "Orphaned ref", src: "Pivotal Design Rationale" },
  { id: "L-00219", text: "Table 11.4.2", target: "m5.3.5.1/CBV-302-CSR.pdf#t11-4-2", sev: "warning", conf: 68, type: "Suspicious target", src: "Pivotal Design Rationale" },
  { id: "L-00220", text: "Section 4.2.1", target: "m2.5.4.2.1", sev: "info", conf: 84, type: "Blue-text · no link", src: "Pivotal Design Rationale" },
  { id: "L-00221", text: "Protocol v3.0", target: "m5.3.1.1/protocol-v3.pdf", sev: "success", conf: 99, type: "Resolved", src: "Pivotal Design Rationale" },
  { id: "L-00222", text: "Investigator Brochure", target: "m1.14/IB-2024-09.pdf", sev: "success", conf: 97, type: "Resolved", src: "Pivotal Design Rationale" },
  { id: "L-00223", text: "see Module 4.2.3.4", target: "m4.2.3.4", sev: "warning", conf: 62, type: "Style mutation", src: "Pivotal Design Rationale" },
];

// ─────────────────────────────────────────────────────────────────────────────
// Skeleton — used only by the loading state.
// ─────────────────────────────────────────────────────────────────────────────

interface SkeletonProps {
  w: number | string;
  h?: number;
  r?: number;
  style?: React.CSSProperties;
}

const Skeleton: React.FC<SkeletonProps> = ({ w, h = 10, r = 3, style = {} }) => (
  <div
    style={{
      width: w,
      height: h,
      borderRadius: r,
      background:
        "linear-gradient(90deg, var(--surface-raised), var(--surface-sunken), var(--surface-raised))",
      backgroundSize: "200% 100%",
      animation: "hv-sk 1.4s ease-in-out infinite",
      ...style,
    }}
  />
);

// Inject skeleton keyframes once into the document.
function useSkeletonKeyframes(): void {
  useEffect(() => {
    if (typeof document === "undefined") return;
    if (document.getElementById("hv-skeleton-kf")) return;
    const s = document.createElement("style");
    s.id = "hv-skeleton-kf";
    s.textContent =
      "@keyframes hv-sk { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }";
    document.head.appendChild(s);
  }, []);
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared header.
// ─────────────────────────────────────────────────────────────────────────────

const InspectorHeader: React.FC = () => (
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
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 11,
          color: "var(--text-3)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        <Icon name="link" size={11} color="var(--text-3)" />
        Link Inspector
      </div>
      <div
        style={{
          fontFamily: "var(--ff-display)",
          fontSize: 20,
          fontWeight: 600,
          letterSpacing: "-0.01em",
          marginTop: 2,
        }}
      >
        Pivotal Study Design Rationale
      </div>
      <div
        style={{
          fontSize: 12,
          color: "var(--text-2)",
          marginTop: 2,
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <CodePath>m2/2.5/2.5.1/pivotal-design-rationale.docx</CodePath>
        <span>·</span>
        <span>
          <span className="mono">154</span> links
        </span>
      </div>
    </div>
    <div style={{ display: "flex", gap: 8 }}>
      <button className="btn btn-secondary btn-sm">
        <Icon name="filter" size={12} /> Sev: All
      </button>
      <button className="btn btn-secondary btn-sm">
        <Icon name="refresh" size={12} /> Re-resolve all
      </button>
      <button className="btn btn-primary btn-sm">
        <Icon name="check" size={12} color="#fff" /> Approve batch (4)
      </button>
    </div>
  </div>
);

// ─────────────────────────────────────────────────────────────────────────────
// Top-level component.
// ─────────────────────────────────────────────────────────────────────────────

export interface LinkInspectorProps {
  theme?: "light" | "dark";
  state?: InspectorState;
}

export const LinkInspector: React.FC<LinkInspectorProps> = ({
  theme = "light",
  state = "data",
}) => {
  useSkeletonKeyframes();

  // —— EMPTY STATE ————————————————————————————————————————————
  if (state === "empty") {
    return (
      <div className={`hv-root ${theme === "dark" ? "theme-dark" : ""}`}>
        <TopBar theme={theme} />
        <DossierBar>
          <CtdCrumb parts={["Dossier", "m2", "2.5", "2.5.1"]} current="Link Inspector" />
        </DossierBar>
        <InspectorHeader />
        <div style={{ flex: 1, display: "grid", placeItems: "center", background: "var(--bg)" }}>
          <div style={{ textAlign: "center", maxWidth: 360 }}>
            <div
              style={{
                width: 56,
                height: 56,
                margin: "0 auto 16px",
                borderRadius: 8,
                background: "var(--surface-raised)",
                border: "1px solid var(--border)",
                display: "grid",
                placeItems: "center",
              }}
            >
              <Icon name="link" size={22} color="var(--text-3)" />
            </div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>
              No links to inspect
            </div>
            <div style={{ fontSize: 13, color: "var(--text-2)", marginBottom: 16 }}>
              This document has no detected hyperlinks. Run detection to scan for
              cross-references, study IDs, and table anchors.
            </div>
            <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
              <button className="btn btn-secondary btn-sm">Read the docs</button>
              <button className="btn btn-primary btn-sm">
                <Icon name="play" size={12} color="#fff" /> Run detection
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // —— LOADING STATE —————————————————————————————————————————
  if (state === "loading") {
    return (
      <div className={`hv-root ${theme === "dark" ? "theme-dark" : ""}`}>
        <TopBar theme={theme} />
        <DossierBar>
          <CtdCrumb parts={["Dossier", "m2", "2.5", "2.5.1"]} current="Link Inspector" />
        </DossierBar>
        <InspectorHeader />
        <div style={{ flex: 1, display: "grid", gridTemplateColumns: "420px 1fr", minHeight: 0 }}>
          <div style={{ borderRight: "1px solid var(--border)", overflow: "hidden" }}>
            {Array.from({ length: 12 }).map((_, i) => (
              <div
                key={i}
                style={{
                  padding: "14px 16px",
                  borderBottom: "1px solid var(--border)",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                <Skeleton w={12} h={12} r={6} />
                <div style={{ flex: 1 }}>
                  <Skeleton w="60%" h={10} />
                  <Skeleton w="80%" h={8} style={{ marginTop: 6 }} />
                </div>
                <Skeleton w={48} h={18} r={4} />
              </div>
            ))}
          </div>
          <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
            <Skeleton w="40%" h={14} />
            <Skeleton w="70%" h={10} />
            <div style={{ marginTop: 12, padding: 16, border: "1px solid var(--border)", borderRadius: 6 }}>
              <Skeleton w="100%" h={10} />
              <Skeleton w="92%" h={10} style={{ marginTop: 8 }} />
              <Skeleton w="88%" h={10} style={{ marginTop: 8 }} />
              <Skeleton w="50%" h={10} style={{ marginTop: 8 }} />
            </div>
            <Skeleton w="100%" h={120} r={4} />
            <Skeleton w="100%" h={32} r={4} />
          </div>
        </div>
      </div>
    );
  }

  // —— ERROR STATE ———————————————————————————————————————————
  if (state === "error") {
    return (
      <div className={`hv-root ${theme === "dark" ? "theme-dark" : ""}`}>
        <TopBar theme={theme} />
        <DossierBar>
          <CtdCrumb parts={["Dossier", "m2", "2.5", "2.5.1"]} current="Link Inspector" />
        </DossierBar>
        <InspectorHeader />
        <div style={{ flex: 1, display: "grid", placeItems: "center", background: "var(--bg)" }}>
          <div
            style={{
              maxWidth: 460,
              padding: 24,
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              boxShadow: "var(--shadow-1)",
            }}
          >
            <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
              <div
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: 6,
                  background: "var(--danger-tint)",
                  color: "var(--danger)",
                  display: "grid",
                  placeItems: "center",
                  flexShrink: 0,
                }}
              >
                <Icon name="alert" size={18} color="currentColor" strokeWidth={2} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
                  Detection service unreachable
                </div>
                <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 12 }}>
                  The on-prem inference cluster <CodePath copy={false}>infer-prod-02</CodePath> did
                  not respond within 30s. <strong>No data has been transmitted off-network.</strong>
                </div>
                <div
                  style={{
                    padding: 10,
                    background: "var(--surface-sunken)",
                    border: "1px solid var(--border)",
                    borderRadius: 4,
                    fontFamily: "var(--ff-mono)",
                    fontSize: 11,
                    color: "var(--text-2)",
                    marginBottom: 12,
                  }}
                >
                  ERR · ECONNREFUSED 10.42.7.12:8443
                  <br />
                  trace_id: 91f3a2-c81b-4e1d
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn btn-secondary btn-sm">Copy trace ID</button>
                  <button className="btn btn-secondary btn-sm">Open audit log</button>
                  <button className="btn btn-primary btn-sm" style={{ marginLeft: "auto" }}>
                    <Icon name="refresh" size={12} color="#fff" /> Retry
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // —— DATA STATE —————————————————————————————————————————————
  return (
    <div className={`hv-root ${theme === "dark" ? "theme-dark" : ""}`}>
      <TopBar theme={theme} activeTab="Dossiers" />
      <DossierBar
        right={
          <>
            <button className="btn btn-secondary btn-sm">
              <Icon name="chevron-left" size={12} /> Prev doc
            </button>
            <button className="btn btn-secondary btn-sm">
              Next doc <Icon name="chevron-right" size={12} />
            </button>
          </>
        }
      >
        <CtdCrumb parts={["Dossier", "m2", "2.5", "2.5.1"]} current="Link Inspector" />
      </DossierBar>

      <InspectorHeader />

      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "420px 1fr", minHeight: 0 }}>
        {/* LEFT — link list */}
        <div
          style={{
            borderRight: "1px solid var(--border)",
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
          }}
        >
          {/* Filter strip */}
          <div
            style={{
              padding: "8px 12px",
              borderBottom: "1px solid var(--border)",
              display: "flex",
              gap: 4,
              background: "var(--surface-raised)",
            }}
          >
            {[
              { lbl: "All", n: 154, active: true, color: undefined as string | undefined },
              { lbl: "Blocker", n: 4, color: "var(--danger)" },
              { lbl: "Warn", n: 14, color: "var(--warning)" },
              { lbl: "Info", n: 22, color: "var(--info)" },
              { lbl: "Valid", n: 114, color: "var(--success)" },
            ].map((f, i) => (
              <button
                key={i}
                className="btn btn-sm btn-ghost"
                style={{
                  height: 26,
                  padding: "0 8px",
                  fontSize: 11,
                  background: f.active ? "var(--surface)" : "transparent",
                  border: f.active ? "1px solid var(--border)" : "1px solid transparent",
                }}
              >
                {f.color && <span className="dot dot-sm" style={{ background: f.color }} />}
                {f.lbl}
                <span className="mono" style={{ marginLeft: 4, color: "var(--text-3)" }}>
                  {f.n}
                </span>
              </button>
            ))}
          </div>

          {/* Link rows */}
          <div style={{ flex: 1, overflow: "hidden" }}>
            {LINKS.map((l) => (
              <div
                key={l.id}
                style={{
                  display: "flex",
                  gap: 10,
                  padding: "10px 14px",
                  borderBottom: "1px solid var(--border)",
                  background: l.active ? "var(--brand-tint)" : "transparent",
                  cursor: "pointer",
                  position: "relative",
                }}
              >
                {l.active && (
                  <div
                    style={{
                      position: "absolute",
                      left: 0,
                      top: 0,
                      bottom: 0,
                      width: 2,
                      background: "var(--brand)",
                    }}
                  />
                )}
                <SeverityIcon kind={l.sev} size={14} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span className="mono" style={{ fontSize: 10, color: "var(--text-3)" }}>
                      {l.id}
                    </span>
                    <span
                      className="chip chip-sm"
                      style={{
                        background: "transparent",
                        border: "1px solid var(--border)",
                        color: "var(--text-2)",
                      }}
                    >
                      {l.type}
                    </span>
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      color: "var(--text-1)",
                      fontWeight: l.active ? 500 : 400,
                      marginTop: 3,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    &ldquo;{l.text}&rdquo;
                  </div>
                  <div
                    className="mono"
                    style={{
                      fontSize: 10,
                      color: "var(--text-3)",
                      marginTop: 3,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    → {l.target}
                  </div>
                </div>
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "flex-end",
                    gap: 4,
                  }}
                >
                  <span
                    className="mono num"
                    style={{
                      fontSize: 11,
                      fontWeight: 500,
                      color:
                        l.conf < 60
                          ? "var(--danger-text)"
                          : l.conf < 80
                          ? "var(--warning-text)"
                          : "var(--success-text)",
                    }}
                  >
                    {l.conf}%
                  </span>
                  <div
                    style={{
                      width: 40,
                      height: 3,
                      background: "var(--surface-sunken)",
                      borderRadius: 2,
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        width: `${l.conf}%`,
                        height: "100%",
                        background:
                          l.conf < 60
                            ? "var(--danger)"
                            : l.conf < 80
                            ? "var(--warning)"
                            : "var(--success)",
                      }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div
            style={{
              height: 32,
              flexShrink: 0,
              borderTop: "1px solid var(--border)",
              background: "var(--surface-raised)",
              display: "flex",
              alignItems: "center",
              padding: "0 14px",
              fontSize: 11,
              color: "var(--text-2)",
            }}
          >
            <span>10 of 154</span>
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 4 }}>
              <button className="btn btn-icon btn-sm btn-ghost" aria-label="Previous">
                <Icon name="chevron-left" size={11} />
              </button>
              <span className="mono">1 / 16</span>
              <button className="btn btn-icon btn-sm btn-ghost" aria-label="Next">
                <Icon name="chevron-right" size={11} />
              </button>
            </div>
          </div>
        </div>

        {/* RIGHT — detail pane */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
            background: "var(--bg)",
          }}
        >
          {/* Detail header */}
          <div
            style={{
              padding: "14px 20px",
              display: "flex",
              alignItems: "center",
              gap: 12,
              background: "var(--surface)",
              borderBottom: "1px solid var(--border)",
            }}
          >
            <SeverityIcon kind="warning" size={20} />
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="mono" style={{ fontSize: 11, color: "var(--text-3)" }}>
                  L-00215
                </span>
                <SevChip kind="warning" label="Warning" />
                <span className="chip outline">Stale Study ID</span>
              </div>
              <div style={{ fontSize: 14, fontWeight: 500, marginTop: 3 }}>
                &ldquo;Study CBV-301&rdquo; → resolved with low confidence
              </div>
            </div>
            <button className="btn btn-icon btn-sm btn-ghost" aria-label="Open externally">
              <Icon name="external" size={13} />
            </button>
            <button className="btn btn-icon btn-sm btn-ghost" aria-label="More">
              <Icon name="more-h" size={13} />
            </button>
          </div>

          {/* Body 2×2 grid */}
          <div
            style={{
              flex: 1,
              padding: 20,
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 16,
              overflow: "hidden",
            }}
          >
            {/* Source */}
            <div
              className="card"
              style={{ display: "flex", flexDirection: "column", minHeight: 0 }}
            >
              <div
                style={{
                  padding: "10px 14px",
                  borderBottom: "1px solid var(--border)",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 11,
                  color: "var(--text-2)",
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                }}
              >
                <Icon name="file-text" size={12} color="var(--text-2)" /> Source · DOCX
                <span
                  style={{ marginLeft: "auto", textTransform: "none", letterSpacing: 0 }}
                  className="mono"
                >
                  page 18 · ¶ 4
                </span>
              </div>
              <div
                style={{
                  flex: 1,
                  padding: 16,
                  overflow: "hidden",
                  fontFamily: '"Iowan Old Style","Charter",Georgia,serif',
                  fontSize: 13,
                  lineHeight: 1.6,
                  color: "var(--text-1)",
                }}
              >
                <p style={{ margin: 0, color: "var(--text-3)" }}>
                  …pharmacokinetic profile was characterized across the Phase II program, supporting
                  the dose-ranging strategy described in{" "}
                  <span style={{ color: "var(--brand-pressed)" }}>Section 2.5.3.1</span>.
                </p>
                <p style={{ margin: "12px 0 0" }}>
                  The pivotal trial design (
                  <span
                    style={{
                      background: "var(--warning-tint)",
                      color: "var(--warning-text)",
                      padding: "1px 5px",
                      borderRadius: 3,
                      fontWeight: 500,
                      borderBottom: "2px solid var(--warning)",
                    }}
                  >
                    Study CBV-301
                  </span>
                  ) was selected based on the demonstrated separation in the Day-28 viral load
                  endpoint, with adaptive enrichment for prior treatment-experienced patients.
                </p>
                <p style={{ margin: "12px 0 0", color: "var(--text-3)" }}>
                  Endpoints were aligned with the FDA Type-C meeting minutes (March 2024) and
                  pre-specified in the Statistical Analysis Plan…
                </p>
                <div
                  style={{
                    marginTop: 16,
                    padding: 8,
                    background: "var(--warning-tint)",
                    borderRadius: 4,
                    fontSize: 11,
                    color: "var(--warning-text)",
                    fontFamily: "var(--ff-sans)",
                  }}
                >
                  <Icon
                    name="alert"
                    size={11}
                    color="currentColor"
                    style={{ verticalAlign: -1, marginRight: 4 }}
                  />
                  Detected Study ID format{" "}
                  <span
                    className="mono"
                    style={{
                      background: "rgba(255,255,255,.5)",
                      padding: "0 4px",
                      borderRadius: 2,
                    }}
                  >
                    CBV-301
                  </span>{" "}
                  — registry shows the canonical ID is{" "}
                  <span
                    className="mono"
                    style={{
                      background: "rgba(255,255,255,.5)",
                      padding: "0 4px",
                      borderRadius: 2,
                    }}
                  >
                    CBV-301-AME-2
                  </span>{" "}
                  (amended 2024-08-12).
                </div>
              </div>
            </div>

            {/* Target preview */}
            <div
              className="card"
              style={{ display: "flex", flexDirection: "column", minHeight: 0 }}
            >
              <div
                style={{
                  padding: "10px 14px",
                  borderBottom: "1px solid var(--border)",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 11,
                  color: "var(--text-2)",
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                }}
              >
                <Icon name="file" size={12} color="var(--text-2)" /> Target · PDF
                <span
                  style={{ marginLeft: "auto", textTransform: "none", letterSpacing: 0 }}
                  className="mono"
                >
                  CBV-301-CSR.pdf p32
                </span>
              </div>
              <div
                style={{
                  flex: 1,
                  padding: 14,
                  overflow: "hidden",
                  background: "var(--surface-sunken)",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                <div
                  style={{
                    width: "85%",
                    aspectRatio: "8.5 / 11",
                    background: "#fff",
                    border: "1px solid var(--border-strong)",
                    boxShadow: "var(--shadow-1)",
                    padding: "18px 22px",
                    fontSize: 6,
                    color: "#000",
                    fontFamily: "Times, serif",
                    position: "relative",
                    lineHeight: 1.4,
                  }}
                >
                  <div
                    style={{
                      borderBottom: "0.5px solid #999",
                      paddingBottom: 4,
                      marginBottom: 6,
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: 5,
                      color: "#666",
                    }}
                  >
                    <span>CBV-301 Clinical Study Report — Amended</span>
                    <span>Page 32 of 1,284</span>
                  </div>
                  <div style={{ fontWeight: 700, fontSize: 8, marginBottom: 4 }}>
                    5.3.2 Study Design Schematic
                  </div>
                  <p style={{ margin: "0 0 4px" }}>
                    The randomized, double-blind, placebo-controlled multicenter design enrolled
                    1,142 participants across 38 sites in 11 countries. Stratification factors
                    included baseline viral load, prior treatment status, and HLA-B*5701 carrier
                    state.
                  </p>
                  <div
                    style={{
                      margin: "6px 0",
                      padding: 6,
                      background: "var(--warning-tint)",
                      border: "0.5px solid var(--warning)",
                      borderRadius: 2,
                      color: "#000",
                      position: "relative",
                    }}
                  >
                    <strong style={{ fontSize: 7 }}>Study Identifier: CBV-301-AME-2</strong>
                    <span style={{ display: "block", marginTop: 2 }}>
                      (formerly CBV-301; amended per Protocol Amendment 2, 2024-08-12)
                    </span>
                    <div
                      style={{
                        position: "absolute",
                        top: -1,
                        right: -1,
                        width: 10,
                        height: 10,
                        background: "var(--warning)",
                        borderRadius: "50%",
                        border: "1.5px solid #fff",
                      }}
                    />
                  </div>
                  <p style={{ margin: "0 0 4px" }}>
                    The primary endpoint was the proportion of participants achieving HIV-1 RNA
                    &lt; 50 copies/mL at Week 48, with key secondary endpoints assessed at Week
                    24…
                  </p>
                  <p style={{ margin: 0 }}>
                    Sample size was determined based on a two-sided alpha of 0.025 to provide 90%
                    power assuming a 12% treatment difference in the primary endpoint between the
                    active and comparator arms…
                  </p>
                </div>
                <div className="mono" style={{ fontSize: 10, color: "var(--text-2)" }}>
                  Anchor matched · header ¶2
                </div>
              </div>
            </div>

            {/* AI breakdown */}
            <div
              className="card"
              style={{
                padding: 14,
                display: "flex",
                flexDirection: "column",
                gap: 12,
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 600 }}>Confidence breakdown</div>
              <ConfidenceMeter regex={18} ner={34} llm={21} total={73} />
              <div
                style={{
                  marginTop: 4,
                  fontSize: 11,
                  color: "var(--text-2)",
                  lineHeight: 1.5,
                }}
              >
                Regex match on study-ID pattern was exact, but NER + LLM disagree on whether the
                unsuffixed form is the canonical reference. LLM suggests appending{" "}
                <span className="mono" style={{ color: "var(--text-1)" }}>
                  -AME-2
                </span>
                .
              </div>
              <div
                style={{
                  marginTop: "auto",
                  padding: "10px 12px",
                  background: "var(--brand-tint)",
                  borderRadius: 4,
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 8,
                  border: "1px solid var(--brand-tint-2)",
                }}
              >
                <Icon name="sparkles" size={13} color="var(--brand-pressed)" />
                <div style={{ flex: 1, fontSize: 12, color: "var(--brand-pressed)" }}>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>Suggested fix</div>
                  <div>
                    Replace{" "}
                    <span className="mono">&ldquo;Study CBV-301&rdquo;</span> with{" "}
                    <span
                      className="mono"
                      style={{
                        background: "rgba(255,255,255,.7)",
                        padding: "0 4px",
                        borderRadius: 2,
                      }}
                    >
                      &ldquo;Study CBV-301-AME-2&rdquo;
                    </span>{" "}
                    and re-anchor.
                  </div>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div
              className="card"
              style={{ padding: 14, display: "flex", flexDirection: "column", gap: 10 }}
            >
              <div style={{ fontSize: 12, fontWeight: 600 }}>Resolve</div>
              <div
                style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}
              >
                <button className="btn btn-primary btn-sm" style={{ justifyContent: "center" }}>
                  <Icon name="check" size={13} color="#fff" /> Approve fix
                </button>
                <button className="btn btn-secondary btn-sm" style={{ justifyContent: "center" }}>
                  <Icon name="x" size={13} /> Reject
                </button>
                <button className="btn btn-secondary btn-sm" style={{ justifyContent: "center" }}>
                  <Icon name="refresh" size={13} /> Re-resolve
                </button>
                <button className="btn btn-secondary btn-sm" style={{ justifyContent: "center" }}>
                  <Icon name="flag" size={13} /> Flag SME
                </button>
              </div>
              <div
                style={{
                  marginTop: "auto",
                  paddingTop: 10,
                  borderTop: "1px solid var(--border)",
                  fontSize: 11,
                  color: "var(--text-3)",
                }}
              >
                <div className="mono">L-00215 · last modified 14:21 by run-0091</div>
                <div style={{ marginTop: 4, display: "flex", alignItems: "center", gap: 4 }}>
                  <Icon name="shield-check" size={11} color="var(--success)" />
                  Approval will be signed and audit-logged
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
