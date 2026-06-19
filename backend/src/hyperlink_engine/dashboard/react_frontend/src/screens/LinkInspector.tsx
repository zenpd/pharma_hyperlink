/**
 * Screen 3 — Link Inspector.  [LIVE]
 *
 * Master-detail. The link list and the detail pane are driven by the backend's
 * link data for the active run; severity filtering and selection are wired.
 *
 * The empty / loading / error layouts are preserved and are shown either when
 * the live fetch is in that state, or when a design-showcase route forces it
 * (#/links/empty, #/links/loading, #/links/error).
 */

import React, { useEffect, useState } from "react";
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
import { useActiveRun } from "../contexts/ActiveRun";
import { confidenceSplit, statusCounts, statusToSev, useReportData } from "../live";
import type { Link, LinkStatus } from "../types";

export type InspectorState = "data" | "empty" | "loading" | "error";

const baseName = (p: string): string => (p || "").split(/[\\/]/).pop() || p;

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

const InspectorHeader: React.FC<{ docName?: string; linkCount?: number }> = ({
  docName = "Link Inspector",
  linkCount = 0,
}) => (
  <div
    style={{
      padding: "14px 20px",
      display: "flex",
      alignItems: "flex-end",
      gap: 20,
      borderBottom: "1px solid var(--border)",
    }}
  >
    <div style={{ flex: 1, minWidth: 0 }}>
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
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {docName}
      </div>
      <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2, display: "flex", alignItems: "center", gap: 8 }}>
        <span>
          <span className="mono">{linkCount}</span> links
        </span>
      </div>
    </div>
  </div>
);

// ─────────────────────────────────────────────────────────────────────────────

export interface LinkInspectorProps {
  theme?: "light" | "dark";
  state?: InspectorState;
}

const conf = (n: number): number => Math.round((n || 0) * 100);

export const LinkInspector: React.FC<LinkInspectorProps> = ({ theme = "light", state = "data" }) => {
  useSkeletonKeyframes();
  const { activeRunId } = useActiveRun();
  const { links, loading, error } = useReportData(activeRunId);
  const [filter, setFilter] = useState<"all" | LinkStatus>("all");
  const [selIdx, setSelIdx] = useState(0);
  useEffect(() => {
    setSelIdx(0);
  }, [activeRunId, filter]);

  const root = (children: React.ReactNode) => (
    <div className={`hv-root ${theme === "dark" ? "theme-dark" : ""}`}>{children}</div>
  );

  // —— EMPTY STATE (forced route or no live links) ————————————————
  const emptyView = root(
    <>
      <TopBar theme={theme} activeTab="Dossiers" />
      <DossierBar>
        <CtdCrumb parts={["Dossier", "Links"]} current="Link Inspector" />
      </DossierBar>
      <InspectorHeader docName="No document selected" linkCount={0} />
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
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>No links to inspect</div>
          <div style={{ fontSize: 13, color: "var(--text-2)", marginBottom: 16 }}>
            This source has no detected hyperlinks. Run the pipeline, or pick a completed run from the
            Data source bar.
          </div>
        </div>
      </div>
    </>,
  );

  // —— LOADING STATE ————————————————————————————————————————
  const loadingView = root(
    <>
      <TopBar theme={theme} activeTab="Dossiers" />
      <DossierBar>
        <CtdCrumb parts={["Dossier", "Links"]} current="Link Inspector" />
      </DossierBar>
      <InspectorHeader docName="Loading…" linkCount={0} />
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
          <Skeleton w="100%" h={120} r={4} />
          <Skeleton w="100%" h={32} r={4} />
        </div>
      </div>
    </>,
  );

  // —— ERROR STATE ——————————————————————————————————————————
  const errorView = (msg: string) =>
    root(
      <>
        <TopBar theme={theme} activeTab="Dossiers" />
        <DossierBar>
          <CtdCrumb parts={["Dossier", "Links"]} current="Link Inspector" />
        </DossierBar>
        <InspectorHeader docName="Link Inspector" linkCount={0} />
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
                  Could not reach the engine API
                </div>
                <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 12 }}>
                  The dashboard talks to the FastAPI backend on <CodePath copy={false}>127.0.0.1:8000</CodePath>.{" "}
                  <strong>No data has been transmitted off-network.</strong>
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
                  }}
                >
                  {msg}
                </div>
              </div>
            </div>
          </div>
        </div>
      </>,
    );

  // Forced design-showcase routes win first.
  if (state === "empty") return emptyView;
  if (state === "loading") return loadingView;
  if (state === "error") return errorView("ERR · detection service unreachable");

  // —— LIVE DATA ————————————————————————————————————————————
  const counts = statusCounts(links);
  const filtered = filter === "all" ? links : links.filter((l) => l.status === filter);
  const sel: Link | undefined = filtered[selIdx] ?? filtered[0];

  if (loading) return loadingView;
  if (error) return errorView(error);
  if (links.length === 0) return emptyView;

  const split = sel ? confidenceSplit(sel) : { regex: 0, ner: 0, llm: 0, total: 0 };
  const selSev: SeverityKind = sel ? statusToSev(sel.status) : "neutral";

  const filterButtons: { lbl: string; n: number; color?: string; key: "all" | LinkStatus }[] = [
    { lbl: "All", n: counts.total, key: "all" },
    { lbl: "Broken", n: counts.broken, color: "var(--danger)", key: "broken" },
    { lbl: "Suspect", n: counts.suspicious, color: "var(--warning)", key: "suspicious" },
    { lbl: "Unverified", n: counts.unverified, color: "var(--info)", key: "unverified" },
    { lbl: "Valid", n: counts.ok, color: "var(--success)", key: "ok" },
  ];

  return root(
    <>
      <TopBar theme={theme} activeTab="Dossiers" />
      <DossierBar
        right={
          <span className="mono chip outline">{activeRunId || "demo seed"}</span>
        }
      >
        <CtdCrumb parts={["Dossier", "Links"]} current="Link Inspector" />
      </DossierBar>

      <InspectorHeader docName={sel ? baseName(sel.source_doc) : "Link Inspector"} linkCount={filtered.length} />

      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "420px 1fr", minHeight: 0 }}>
        {/* LEFT — link list */}
        <div style={{ borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", minHeight: 0 }}>
          {/* Filter strip */}
          <div
            style={{
              padding: "8px 12px",
              borderBottom: "1px solid var(--border)",
              display: "flex",
              gap: 4,
              background: "var(--surface-raised)",
              flexWrap: "wrap",
            }}
          >
            {filterButtons.map((f) => (
              <button
                key={f.lbl}
                onClick={() => setFilter(f.key)}
                className="btn btn-sm btn-ghost"
                style={{
                  height: 26,
                  padding: "0 8px",
                  fontSize: 11,
                  background: filter === f.key ? "var(--surface)" : "transparent",
                  border: filter === f.key ? "1px solid var(--border)" : "1px solid transparent",
                }}
              >
                {f.color && <span className="dot dot-sm" style={{ background: f.color }} />}
                {f.lbl}
                <span className="mono" style={{ marginLeft: 4, color: "var(--text-3)" }}>{f.n}</span>
              </button>
            ))}
          </div>

          {/* Link rows */}
          <div style={{ flex: 1, overflow: "auto" }}>
            {filtered.map((l, i) => {
              const sev = statusToSev(l.status);
              const c = conf(l.confidence);
              const active = i === selIdx;
              return (
                <div
                  key={`${l.source_doc}-${i}`}
                  onClick={() => setSelIdx(i)}
                  style={{
                    display: "flex",
                    gap: 10,
                    padding: "10px 14px",
                    borderBottom: "1px solid var(--border)",
                    background: active ? "var(--brand-tint)" : "transparent",
                    cursor: "pointer",
                    position: "relative",
                  }}
                >
                  {active && (
                    <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: "var(--brand)" }} />
                  )}
                  <SeverityIcon kind={sev} size={14} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span className="mono" style={{ fontSize: 10, color: "var(--text-3)" }}>
                        {`L-${String(i + 1).padStart(4, "0")}`}
                      </span>
                      <span
                        className="chip chip-sm"
                        style={{ background: "transparent", border: "1px solid var(--border)", color: "var(--text-2)" }}
                      >
                        {l.detected_by || l.status}
                      </span>
                    </div>
                    <div
                      style={{
                        fontSize: 13,
                        color: "var(--text-1)",
                        fontWeight: active ? 500 : 400,
                        marginTop: 3,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      &ldquo;{l.link_text}&rdquo;
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
                      → {l.target_doc || "—"}
                      {l.target_anchor ? `#${l.target_anchor}` : ""}
                    </div>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
                    <span
                      className="mono num"
                      style={{
                        fontSize: 11,
                        fontWeight: 500,
                        color: c < 60 ? "var(--danger-text)" : c < 80 ? "var(--warning-text)" : "var(--success-text)",
                      }}
                    >
                      {c}%
                    </span>
                    <div style={{ width: 40, height: 3, background: "var(--surface-sunken)", borderRadius: 2, overflow: "hidden" }}>
                      <div
                        style={{
                          width: `${c}%`,
                          height: "100%",
                          background: c < 60 ? "var(--danger)" : c < 80 ? "var(--warning)" : "var(--success)",
                        }}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
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
            <span>
              {filtered.length} of {counts.total}
            </span>
          </div>
        </div>

        {/* RIGHT — detail pane */}
        <div style={{ display: "flex", flexDirection: "column", minHeight: 0, background: "var(--bg)" }}>
          {sel ? (
            <>
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
                <SeverityIcon kind={selSev} size={20} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className="mono" style={{ fontSize: 11, color: "var(--text-3)" }}>
                      {`L-${String(selIdx + 1).padStart(4, "0")}`}
                    </span>
                    <SevChip
                      kind={selSev}
                      label={
                        sel.status === "broken"
                          ? "Broken"
                          : sel.status === "suspicious"
                          ? "Suspicious"
                          : sel.status === "unverified"
                          ? "Unverified"
                          : "Valid"
                      }
                    />
                    <span className="chip outline">{sel.detected_by || "regex"}</span>
                  </div>
                  <div
                    style={{
                      fontSize: 14,
                      fontWeight: 500,
                      marginTop: 3,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    &ldquo;{sel.link_text}&rdquo;
                  </div>
                </div>
              </div>

              <div
                style={{
                  flex: 1,
                  padding: 20,
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 16,
                  overflow: "auto",
                }}
              >
                {/* Source */}
                <div className="card" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
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
                    <Icon name="file-text" size={12} color="var(--text-2)" /> Source
                    <span style={{ marginLeft: "auto", textTransform: "none", letterSpacing: 0 }} className="mono">
                      {baseName(sel.source_doc)}
                    </span>
                  </div>
                  <div style={{ flex: 1, padding: 16, fontSize: 13, lineHeight: 1.6, color: "var(--text-1)" }}>
                    <div style={{ color: "var(--text-3)", fontSize: 11, marginBottom: 8 }}>{sel.link_location_descriptor || "—"}</div>
                    <p style={{ margin: 0 }}>
                      Reference text{" "}
                      <span
                        style={{
                          background: "var(--brand-tint)",
                          color: "var(--brand-pressed)",
                          padding: "1px 5px",
                          borderRadius: 3,
                          fontWeight: 500,
                        }}
                      >
                        {sel.link_text}
                      </span>{" "}
                      detected in <span className="mono">{baseName(sel.source_doc)}</span> by the{" "}
                      <strong>{sel.detected_by || "regex"}</strong> layer.
                    </p>
                  </div>
                </div>

                {/* Target */}
                <div className="card" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
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
                    <Icon name="target" size={12} color="var(--text-2)" /> Target
                    <span style={{ marginLeft: "auto", textTransform: "none", letterSpacing: 0 }} className="mono">
                      {sel.target_anchor || "—"}
                    </span>
                  </div>
                  <div style={{ flex: 1, padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
                    <div style={{ fontSize: 13 }}>
                      Resolves to{" "}
                      <CodePath copy={false}>{sel.target_doc || "— unresolved —"}</CodePath>
                    </div>
                    {sel.target_anchor && (
                      <div style={{ fontSize: 12, color: "var(--text-2)" }}>
                        Anchor: <span className="mono">{sel.target_anchor}</span>
                      </div>
                    )}
                    <div
                      style={{
                        marginTop: "auto",
                        padding: 10,
                        borderRadius: 4,
                        background: selSev === "success" ? "var(--success-tint)" : selSev === "blocker" ? "var(--danger-tint)" : "var(--warning-tint)",
                        color: selSev === "success" ? "var(--success-text)" : selSev === "blocker" ? "var(--danger-text)" : "var(--warning-text)",
                        fontSize: 12,
                      }}
                    >
                      <Icon
                        name={selSev === "success" ? "check-circle" : "alert"}
                        size={12}
                        color="currentColor"
                        style={{ verticalAlign: -1, marginRight: 6 }}
                      />
                      {sel.error_msg
                        ? sel.error_msg
                        : sel.status === "ok"
                        ? "Target resolved and verified."
                        : sel.status === "unverified"
                        ? "Target not yet verified against the backbone."
                        : sel.status === "suspicious"
                        ? "Target may be semantically unrelated — review suggested."
                        : "Target anchor did not resolve."}
                    </div>
                  </div>
                </div>

                {/* Confidence */}
                <div className="card" style={{ padding: 14, display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{ fontSize: 12, fontWeight: 600 }}>Confidence breakdown</div>
                  <ConfidenceMeter regex={split.regex} ner={split.ner} llm={split.llm} total={split.total} />
                  <div style={{ marginTop: 4, fontSize: 11, color: "var(--text-2)", lineHeight: 1.5 }}>
                    Detected by <strong>{sel.detected_by || "regex"}</strong>. The meter approximates each layer's
                    contribution to the {split.total}% overall confidence.
                  </div>
                </div>

                {/* Actions */}
                <div className="card" style={{ padding: 14, display: "flex", flexDirection: "column", gap: 10 }}>
                  <div style={{ fontSize: 12, fontWeight: 600 }}>Resolve</div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <button className="btn btn-primary btn-sm" style={{ justifyContent: "center" }}>
                      <Icon name="check" size={13} color="#fff" /> Approve
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
                  <div style={{ marginTop: "auto", paddingTop: 10, borderTop: "1px solid var(--border)", fontSize: 11, color: "var(--text-3)" }}>
                    <div className="mono">source: {activeRunId || "demo seed dossier"}</div>
                    <div style={{ marginTop: 4, display: "flex", alignItems: "center", gap: 4 }}>
                      <Icon name="shield-check" size={11} color="var(--success)" />
                      Decisions are audit-logged
                    </div>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div style={{ flex: 1, display: "grid", placeItems: "center", color: "var(--text-3)" }}>
              Select a link to inspect
            </div>
          )}
        </div>
      </div>
    </>,
  );
};
