/**
 * Screen 6 — Pipeline Run Detail.
 *
 * Layout: `1fr (main) | 520px (logs aside)`. Main holds the stepper
 * (6 horizontal steps), metrics grid, and artifacts table. Logs aside
 * is JSON-structured, level-coloured, with tail-mode indicator.
 */

import React, { useEffect } from "react";
import {
  CtdCrumb,
  DossierBar,
  Icon,
  Sparkline,
  TopBar,
} from "../components/shared";
import type { IconName } from "../components/shared";

type StepStatus = "success" | "running" | "pending" | "error";
type LogLevel = "ERROR" | "WARN" | "INFO" | "DEBUG";

interface Step {
  name: string;
  duration: string;
  status: StepStatus;
  items: string;
  metric: string;
  progress?: number;
}

interface LogRow {
  ts: string;
  lvl: LogLevel;
  src: string;
  msg: string;
  meta?: Record<string, string | number>;
}

const STEPS: Step[] = [
  { name: "Ingestion", duration: "00:12:04", status: "success", items: "500 docs · 2.1 GB", metric: "42 MB/s" },
  { name: "Parsing", duration: "00:34:21", status: "success", items: "500 docs · 18,422 sections", metric: "23.8 docs/s" },
  { name: "Detection", duration: "01:18:42", status: "success", items: "2,147 candidates", metric: "~457 links/min" },
  { name: "Injection", duration: "00:48:11", status: "success", items: "1,894 auto-injected", metric: "88.2% auto rate" },
  { name: "Validation", duration: "00:42:08", status: "running", items: "1,683 / 2,147 validated", metric: "In progress", progress: 78 },
  { name: "Reporting", duration: "—", status: "pending", items: "queued", metric: "—" },
];

const LOGS: LogRow[] = [
  { ts: "14:22:18.412", lvl: "INFO", src: "validator", msg: "Validation pass started for sequence 0009", meta: { run: "0091", seq: "0009" } },
  { ts: "14:22:18.567", lvl: "INFO", src: "validator", msg: "Loaded 2,147 link candidates from injection store" },
  { ts: "14:22:19.024", lvl: "INFO", src: "resolver.docx", msg: "Resolving cross-doc anchors · m1", meta: { count: 142 } },
  { ts: "14:22:21.198", lvl: "INFO", src: "resolver.pdf", msg: "Opening CSR target index · 691 PDFs cached" },
  { ts: "14:24:02.881", lvl: "WARN", src: "ner.study-id", msg: 'Low-confidence match · "CBV-301"', meta: { link_id: "L-00215", confidence: 0.73 } },
  { ts: "14:24:02.892", lvl: "WARN", src: "ner.study-id", msg: 'Canonical form differs · suggested "CBV-301-AME-2"' },
  { ts: "14:31:14.038", lvl: "ERROR", src: "resolver.docx", msg: 'Anchor missing in target · "Appendix C"', meta: { link_id: "L-00218", source: "m2.5.1" } },
  { ts: "14:38:55.214", lvl: "INFO", src: "audit", msg: "V. Iyer · signed gate review · m2.5.3", meta: { hash: "0xa3f1c8…", alg: "ECDSA-P256" } },
  { ts: "14:42:08.501", lvl: "INFO", src: "audit", msg: "D. Park · signed as Author · NDA 215842/0009", meta: { hash: "0x7b29ab…" } },
  { ts: "14:42:12.118", lvl: "INFO", src: "validator", msg: "Checkpoint · 1,683 / 2,147 (78.4%)" },
  { ts: "14:42:12.119", lvl: "INFO", src: "validator", msg: "Throughput · 457 links/min · ETA 00:14:22" },
];

const lvlColor = (l: LogLevel): string =>
  l === "ERROR" ? "var(--danger)" : l === "WARN" ? "var(--warning)" : l === "INFO" ? "var(--info)" : "var(--text-2)";

const lvlBg = (l: LogLevel): string =>
  l === "ERROR"
    ? "var(--danger-tint)"
    : l === "WARN"
    ? "var(--warning-tint)"
    : l === "INFO"
    ? "var(--info-tint)"
    : "transparent";

// Inject pulse keyframes once (used by the tail-mode dot).
function usePulseKeyframes(): void {
  useEffect(() => {
    if (typeof document === "undefined") return;
    if (document.getElementById("hv-pulse-kf")) return;
    const s = document.createElement("style");
    s.id = "hv-pulse-kf";
    s.textContent =
      "@keyframes hv-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }";
    document.head.appendChild(s);
  }, []);
}

export interface PipelineRunProps {
  theme?: "light" | "dark";
}

export const PipelineRun: React.FC<PipelineRunProps> = ({ theme = "light" }) => {
  usePulseKeyframes();

  return (
    <div className={`hv-root ${theme === "dark" ? "theme-dark" : ""}`}>
      <TopBar theme={theme} activeTab="Pipelines" />
      <DossierBar
        right={
          <>
            <button className="btn btn-secondary btn-sm"><Icon name="pause" size={12}/> Pause</button>
            <button className="btn btn-secondary btn-sm"><Icon name="x" size={12}/> Cancel</button>
            <button className="btn btn-secondary btn-sm"><Icon name="download" size={12}/> Export logs</button>
          </>
        }
      >
        <Icon name="cpu" size={15} color="var(--text-2)"/>
        <CtdCrumb parts={["Dossier", "Pipelines"]} current="run-0091" />
        <span className="chip info"><Icon name="play" size={10}/>Running</span>
        <span className="mono" style={{ fontSize: 11, color: "var(--text-3)" }}>
          Started 10:38 · Elapsed 3h 42m
        </span>
      </DossierBar>

      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 520px", minHeight: 0 }}>
        {/* LEFT — stepper + metrics + artifacts */}
        <div style={{
          padding: 20, display: "flex", flexDirection: "column",
          gap: 16, overflow: "hidden",
        }}>
          {/* Header */}
          <div style={{ display: "flex", alignItems: "flex-end", gap: 24 }}>
            <div>
              <div style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                Pipeline Run
              </div>
              <div style={{ fontFamily: "var(--ff-display)", fontSize: 24, fontWeight: 600, letterSpacing: "-0.015em", marginTop: 2 }}>
                run-0091 · Sequence 0009
              </div>
              <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 4 }}>
                Triggered by <span style={{ color: "var(--text-1)", fontWeight: 500 }}>V. Iyer</span> · cluster{" "}
                <span className="mono">infer-prod-01</span> · region <span className="mono">eu-west-1</span>
              </div>
            </div>
            <div style={{ marginLeft: "auto", display: "flex", gap: 16 }}>
              {[
                { lbl: "Docs processed", val: "500 / 500" },
                { lbl: "Throughput", val: "457 lpm" },
                { lbl: "GPU util", val: "74%" },
                { lbl: "ETA", val: "14m 22s" },
              ].map((s) => (
                <div key={s.lbl} style={{ borderLeft: "1px solid var(--border)", paddingLeft: 12 }}>
                  <div style={{ fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    {s.lbl}
                  </div>
                  <div className="mono num" style={{ fontSize: 16, fontWeight: 600, marginTop: 2 }}>
                    {s.val}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Stepper */}
          <div className="card" style={{ padding: 16 }}>
            <div style={{ display: "flex", alignItems: "stretch", gap: 0, position: "relative" }}>
              {STEPS.map((s, i) => {
                const isLast = i === STEPS.length - 1;
                const dotColor =
                  s.status === "success"
                    ? "var(--success)"
                    : s.status === "running"
                    ? "var(--brand)"
                    : s.status === "error"
                    ? "var(--danger)"
                    : "var(--border-strong)";
                return (
                  <div key={s.name} style={{ flex: 1, position: "relative" }}>
                    {!isLast && (
                      <div style={{
                        position: "absolute",
                        top: 11, left: "50%", right: "-50%",
                        height: 2,
                        background: s.status === "success" ? "var(--success)" : "var(--border-strong)",
                      }} />
                    )}
                    <div style={{
                      position: "relative", zIndex: 1, width: 24, height: 24,
                      margin: "0 auto", borderRadius: "50%",
                      background: s.status === "pending" ? "var(--surface)" : dotColor,
                      border:
                        s.status === "pending"
                          ? "2px solid var(--border-strong)"
                          : s.status === "running"
                          ? "2px solid var(--brand)"
                          : "none",
                      display: "grid", placeItems: "center",
                      boxShadow: s.status === "running" ? "0 0 0 4px var(--brand-tint)" : "none",
                    }}>
                      {s.status === "success" && <Icon name="check" size={12} color="#fff" strokeWidth={3} />}
                      {s.status === "running" && (
                        <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#fff" }} />
                      )}
                      {s.status === "pending" && (
                        <span className="mono" style={{ fontSize: 10, color: "var(--text-3)" }}>
                          {i + 1}
                        </span>
                      )}
                    </div>
                    <div style={{ textAlign: "center", marginTop: 10 }}>
                      <div style={{
                        fontSize: 12, fontWeight: 600,
                        color: s.status === "pending" ? "var(--text-3)" : "var(--text-1)",
                      }}>
                        {s.name}
                      </div>
                      <div className="mono num" style={{ fontSize: 11, color: "var(--text-2)", marginTop: 2 }}>
                        {s.duration}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 4, lineHeight: 1.3 }}>
                        {s.items}
                      </div>
                      {s.status === "running" && s.progress != null && (
                        <div style={{ marginTop: 6, padding: "0 14px" }}>
                          <div style={{ height: 4, background: "var(--surface-sunken)", borderRadius: 2, overflow: "hidden" }}>
                            <div style={{ width: `${s.progress}%`, height: "100%", background: "var(--brand)" }} />
                          </div>
                          <div className="mono" style={{ fontSize: 10, color: "var(--brand-pressed)", marginTop: 4 }}>
                            {s.progress}%
                          </div>
                        </div>
                      )}
                      <div className="mono" style={{ fontSize: 10, color: "var(--text-3)", marginTop: 4 }}>
                        {s.metric}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Metrics */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
            {[
              { title: "Throughput", val: "457", unit: "links/min", data: [220, 340, 412, 380, 445, 480, 467, 491, 470, 459, 463, 457], color: "var(--brand)" },
              { title: "Avg latency", val: "142", unit: "ms", data: [220, 198, 180, 162, 158, 144, 148, 152, 140, 145, 142, 142], color: "var(--viz-1)" },
              { title: "Detection precision", val: "94.8", unit: "%", data: [82, 84, 85, 88, 90, 91, 92, 93, 94, 94, 95, 94.8], color: "var(--success)" },
            ].map((m) => (
              <div key={m.title} className="card" style={{ padding: 12 }}>
                <div style={{ fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  {m.title}
                </div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 4 }}>
                  <span className="mono num" style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.01em" }}>
                    {m.val}
                  </span>
                  <span className="mono" style={{ fontSize: 11, color: "var(--text-3)" }}>
                    {m.unit}
                  </span>
                </div>
                <div style={{ marginTop: 6 }}>
                  <Sparkline data={m.data} width={260} height={32} color={m.color} />
                </div>
              </div>
            ))}
          </div>

          {/* Artifacts */}
          <div className="card" style={{ padding: 16, flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>Artifacts</div>
                <div style={{ fontSize: 11, color: "var(--text-2)", marginTop: 2 }}>
                  Produced by this run · model artifacts shared with CAPTIS®
                </div>
              </div>
              <span style={{ marginLeft: "auto" }} className="chip outline mono">14 artifacts</span>
            </div>
            <table className="tbl dense">
              <thead>
                <tr>
                  <th>Artifact</th>
                  <th>Type</th>
                  <th style={{ textAlign: "right" }}>Size</th>
                  <th>Hash</th>
                  <th>Produced</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { n: "link-inventory.parquet", t: "inventory", s: "14.2 MB", h: "0x91f3a2…", when: "Detection" },
                  { n: "anomaly-report.json", t: "report", s: "842 KB", h: "0xc4f82e…", when: "Detection" },
                  { n: "injection-log.ndjson", t: "log", s: "6.1 MB", h: "0x4d2c8e…", when: "Injection" },
                  { n: "confidence-distrib.png", t: "chart", s: "124 KB", h: "0x7b29ab…", when: "Detection" },
                  { n: "embeddings-v3.4.bin", t: "model", s: "218 MB", h: "0xa3f1c8…", when: "Detection" },
                ].map((a) => (
                  <tr key={a.n}>
                    <td><span className="mono" style={{ fontSize: 11 }}>{a.n}</span></td>
                    <td><span className="chip outline chip-sm">{a.t}</span></td>
                    <td style={{ textAlign: "right" }}><span className="mono num">{a.s}</span></td>
                    <td>
                      <span className="mono" style={{ fontSize: 11, color: "var(--text-2)" }}>
                        {a.h}
                      </span>
                    </td>
                    <td><span style={{ fontSize: 11, color: "var(--text-2)" }}>{a.when}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* RIGHT — logs */}
        <aside style={{
          borderLeft: "1px solid var(--border)",
          background: "var(--surface-sunken)",
          display: "flex", flexDirection: "column", minHeight: 0,
        }}>
          <div style={{
            padding: "12px 16px",
            borderBottom: "1px solid var(--border)",
            background: "var(--surface)",
            display: "flex", alignItems: "center", gap: 8,
          }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>Logs</div>
            <span className="chip outline mono chip-sm">JSON-structured</span>
            <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
              <button className="btn btn-icon btn-sm btn-ghost" aria-label="Find in logs"><Icon name="search" size={12}/></button>
              <button className="btn btn-icon btn-sm btn-ghost" aria-label="Download logs"><Icon name="download" size={12}/></button>
            </div>
          </div>

          {/* Filter strip */}
          <div style={{
            padding: "8px 16px",
            display: "flex", alignItems: "center", gap: 6,
            borderBottom: "1px solid var(--border)",
            background: "var(--surface)",
            fontSize: 11,
          }}>
            <span style={{ color: "var(--text-3)" }}>Level:</span>
            {[
              { l: "ERROR", n: 8, color: "var(--danger)", active: false },
              { l: "WARN", n: 47, color: "var(--warning)", active: true },
              { l: "INFO", n: 1284, color: "var(--info)", active: true },
              { l: "DEBUG", n: 0, color: "var(--text-3)", active: false },
            ].map((f) => (
              <button key={f.l} className="btn btn-sm btn-ghost" style={{
                height: 22, padding: "0 6px", fontSize: 10,
                background: f.active ? "var(--surface-raised)" : "transparent",
                border: "1px solid " + (f.active ? "var(--border)" : "transparent"),
              }}>
                <span className="dot dot-sm" style={{ background: f.color }} />
                {f.l}{" "}
                <span className="mono" style={{ color: "var(--text-3)", marginLeft: 3 }}>{f.n}</span>
              </button>
            ))}
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ color: "var(--text-3)" }}>Source:</span>
              <button className="btn btn-sm btn-ghost" style={{
                height: 22, padding: "0 6px", fontSize: 10, background: "var(--surface-raised)",
              }}>
                all <Icon name="chevron-down" size={9} />
              </button>
            </div>
          </div>

          {/* Log body */}
          <div style={{
            flex: 1, overflow: "hidden",
            fontFamily: "var(--ff-mono)",
            fontSize: 11, lineHeight: 1.55,
            padding: 0,
          }}>
            {LOGS.map((l, i) => (
              <div key={i} style={{
                padding: "6px 16px",
                borderBottom: "1px solid var(--border)",
                background: lvlBg(l.lvl) === "transparent" ? "transparent" : lvlBg(l.lvl),
                display: "grid", gridTemplateColumns: "90px 50px 1fr", gap: 8,
                alignItems: "baseline",
              }}>
                <span style={{ color: "var(--text-3)", fontSize: 10 }}>{l.ts}</span>
                <span style={{ color: lvlColor(l.lvl), fontWeight: 600, fontSize: 10 }}>
                  {l.lvl}
                </span>
                <div style={{ color: "var(--text-1)", overflow: "hidden" }}>
                  <span style={{ color: "var(--text-3)" }}>[{l.src}] </span>
                  {l.msg}
                  {l.meta && (
                    <div style={{
                      marginTop: 4, padding: "4px 6px",
                      background: "rgba(0,0,0,0.03)",
                      borderRadius: 3,
                      color: "var(--text-2)", fontSize: 10,
                    }}>
                      <span style={{ color: "var(--text-3)" }}>{"{"}</span>
                      {Object.entries(l.meta).map(([k, v], j, arr) => (
                        <span key={k}>
                          <span style={{ color: "var(--viz-2)" }}>{k}</span>
                          <span style={{ color: "var(--text-3)" }}>: </span>
                          <span style={{ color: "var(--viz-6)" }}>"{String(v)}"</span>
                          {j < arr.length - 1 && (
                            <span style={{ color: "var(--text-3)" }}>, </span>
                          )}
                        </span>
                      ))}
                      <span style={{ color: "var(--text-3)" }}>{"}"}</span>
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div style={{
              padding: "10px 16px", color: "var(--text-3)",
              fontSize: 10, textAlign: "center",
            }}>
              · streaming ·
            </div>
          </div>

          {/* Footer */}
          <div style={{
            height: 30, flexShrink: 0,
            borderTop: "1px solid var(--border)",
            background: "var(--surface)",
            display: "flex", alignItems: "center", padding: "0 16px",
            fontSize: 11, color: "var(--text-2)",
          }}>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span className="dot dot-sm" style={{
                background: "var(--brand)", animation: "hv-pulse 1.4s infinite",
              }} />
              Tail mode · 1,339 lines
            </span>
            <span className="mono" style={{ marginLeft: "auto", color: "var(--text-3)" }}>
              ⌘F to find
            </span>
          </div>
        </aside>
      </div>
    </div>
  );
};
