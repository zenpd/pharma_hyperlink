/**
 * Screen: Dossier Graph
 *
 * Hierarchy: Dossier (run) → Documents → cross-doc Hyperlinks
 *
 * Layout
 *  • One large "Dossier" root node fixed at centre
 *  • Document nodes on a ring around it (d3.forceRadial)
 *  • Cross-doc links drawn as curved arcs between doc nodes
 *  • Thin grey spokes connect each doc back to the dossier root
 *
 * Interactions
 *  • Scroll/pinch → zoom   |   drag canvas → pan  (d3.zoom)
 *  • Drag individual nodes → pin/unpin
 *  • Click a doc node → navigate to Run Compare for that doc
 *  • Hover node/edge → tooltip
 */

import { useEffect, useLayoutEffect, useRef, useState, useCallback } from "react";
import * as d3 from "d3";
import { api } from "../api";
import type { RunGraph, GraphNode, GraphEdge } from "../types";

interface Props {
  onBack: () => void;
  onGoToCompare?: (runId: string, doc: string) => void;
}

// ── palette ──────────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  ok:         "#22c55e",
  unverified: "#f59e0b",
  broken:     "#ef4444",
};
const DETECTION_DASH: Record<string, string> = {
  regex: "none",
  ner:   "8,4",
  llm:   "2,5",
};
const DOC_COLOR: Record<string, string> = {
  pdf:  "#818cf8",
  docx: "#38bdf8",
};
const DOSSIER_COLOR = "#a78bfa";

// ── D3 simulation types ───────────────────────────────────────────────────────

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  kind: "dossier" | "doc";
  label: string;
  docType?: "pdf" | "docx";
  link_count: number;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  kind: "spoke" | "cross";
  edge?: GraphEdge;
}

// ── helpers ───────────────────────────────────────────────────────────────────

function shortName(id: string) {
  return id
    .replace(/_linked\.(docx|pdf)$/i, "")
    .replace(/\.(docx|pdf)$/i, "");
}

// ── component ────────────────────────────────────────────────────────────────

export function DossierGraph({ onBack, onGoToCompare }: Props) {
  const [runs, setRuns]       = useState<{ run_id: string }[]>([]);
  const [runId, setRunId]     = useState<string | null>(null);
  const [graph, setGraph]     = useState<RunGraph | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");

  const [tooltip, setTooltip] = useState<{ x: number; y: number; html: string } | null>(null);
  const [dims, setDims]       = useState({ w: 900, h: 620 });

  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef       = useRef<SVGSVGElement>(null);
  const simRef       = useRef<d3.Simulation<SimNode, SimLink> | null>(null);

  // Measure container after layout
  useLayoutEffect(() => {
    function measure() {
      if (containerRef.current) {
        const r = containerRef.current.getBoundingClientRect();
        if (r.width > 100 && r.height > 100) {
          setDims({ w: r.width, h: r.height });
        }
      }
    }
    measure();
    const obs = new ResizeObserver(measure);
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  // Load run list once
  useEffect(() => {
    api.pipeline.listRuns()
      .then((data) => {
        const done = (data.runs ?? [])
          .filter((r) => r.status === "done")
          .sort((a, b) => b.run_id.localeCompare(a.run_id));
        setRuns(done);
        if (done.length > 0) setRunId(done[0].run_id);
      }).catch(() => {});
  }, []);

  // Load graph when run selection changes
  useEffect(() => {
    if (!runId) return;
    setLoading(true);
    setError("");
    setGraph(null);
    api.pipeline.runGraph(runId)
      .then((g) => { setGraph(g); setLoading(false); })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "Failed to load graph");
        setLoading(false);
      });
  }, [runId]);

  // Build / rebuild D3 scene
  const buildGraph = useCallback(() => {
    if (!graph || !svgRef.current) return;

    simRef.current?.stop();
    simRef.current = null;

    const { w, h } = dims;
    const cx = w / 2;
    const cy = h / 2;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    // ── Arrow markers ─────────────────────────────────────────────────────
    const defs = svg.append("defs");
    Object.entries(STATUS_COLOR).forEach(([status, color]) => {
      defs.append("marker")
        .attr("id", `arr-${status}`)
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 24)
        .attr("refY", 0)
        .attr("markerWidth", 5)
        .attr("markerHeight", 5)
        .attr("orient", "auto")
        .append("path")
        .attr("fill", color)
        .attr("d", "M0,-5L10,0L0,5");
    });

    // Soft glow filter for dossier node
    const filter = defs.append("filter").attr("id", "glow");
    filter.append("feGaussianBlur").attr("stdDeviation", "6").attr("result", "blur");
    const merge = filter.append("feMerge");
    merge.append("feMergeNode").attr("in", "blur");
    merge.append("feMergeNode").attr("in", "SourceGraphic");

    // ── Zoom / pan ────────────────────────────────────────────────────────
    const zoomG = svg.append("g");
    svg.call(
      d3.zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.1, 8])
        .on("zoom", (ev) => zoomG.attr("transform", ev.transform)),
    );

    // ── Simulation data ───────────────────────────────────────────────────
    const maxLinks = Math.max(1, ...graph.nodes.map((n) => n.link_count));
    const nodeR    = d3.scaleSqrt().domain([0, maxLinks]).range([16, 44]);

    // Root dossier node (fixed at centre)
    const dossierNode: SimNode = {
      id: "__dossier__",
      kind: "dossier",
      label: runId ?? "Dossier",
      link_count: graph.stats.total_links,
      fx: cx,
      fy: cy,
    };

    const docNodes: SimNode[] = graph.nodes.map((n: GraphNode) => ({
      id: n.id,
      kind: "doc",
      label: n.label,
      docType: n.type as "pdf" | "docx",
      link_count: n.link_count,
    }));

    const allNodes: SimNode[] = [dossierNode, ...docNodes];
    const nodeById = new Map(allNodes.map((n) => [n.id, n]));

    // Spokes: dossier → every doc
    const spokeLinks: SimLink[] = docNodes.map((d) => ({
      source: dossierNode,
      target: d,
      kind: "spoke",
    }));

    // Cross-doc edges
    const crossLinks: SimLink[] = graph.edges
      .map((e: GraphEdge) => {
        const src = nodeById.get(e.source);
        const tgt = nodeById.get(e.target);
        if (!src || !tgt) return null;
        return { source: src, target: tgt, kind: "cross", edge: e } as SimLink;
      })
      .filter((l): l is SimLink => l !== null);

    const allLinks: SimLink[] = [...spokeLinks, ...crossLinks];

    // Radial ring radius — scales with doc count
    const ringR = Math.min(cx, cy) * 0.72 * (1 + Math.log2(Math.max(1, docNodes.length)) * 0.07);

    // ── Simulation ────────────────────────────────────────────────────────
    simRef.current = d3.forceSimulation<SimNode>(allNodes)
      .force("link", d3.forceLink<SimNode, SimLink>(allLinks)
        .id((d) => d.id)
        .distance((l) => l.kind === "spoke" ? ringR : ringR * 0.9)
        .strength((l) => l.kind === "spoke" ? 1 : 0.2))
      .force("charge",  d3.forceManyBody<SimNode>().strength((d) => d.kind === "dossier" ? -800 : -350))
      .force("radial",  d3.forceRadial<SimNode>(ringR, cx, cy).strength((d) => d.kind === "doc" ? 0.85 : 0))
      .force("collide", d3.forceCollide<SimNode>().radius((d) => (d.kind === "dossier" ? 52 : nodeR(d.link_count)) + 14))
      .alphaDecay(0.025);

    // ── Draw spoke edges (behind everything) ─────────────────────────────
    const spokeG = zoomG.append("g");
    const spokeSel = spokeG.selectAll("line")
      .data(spokeLinks)
      .enter()
      .append("line")
      .attr("stroke", "#334155")
      .attr("stroke-width", 1)
      .attr("stroke-dasharray", "3,4")
      .attr("stroke-opacity", 0.55)
      .attr("pointer-events", "none");

    // ── Draw cross-doc edges ──────────────────────────────────────────────
    const edgeWidth = d3.scaleLinear()
      .domain([1, Math.max(1, d3.max(graph.edges, (e: GraphEdge) => e.count) ?? 1)])
      .range([1.5, 5])
      .clamp(true);

    const crossG = zoomG.append("g");
    const crossSel = crossG.selectAll("path")
      .data(crossLinks)
      .enter()
      .append("path")
      .attr("fill", "none")
      .attr("stroke", (d) => STATUS_COLOR[(d.edge?.status) ?? "unverified"])
      .attr("stroke-width", (d) => edgeWidth(d.edge?.count ?? 1))
      .attr("stroke-dasharray", (d) => DETECTION_DASH[d.edge?.detected_by ?? "regex"] ?? "none")
      .attr("stroke-opacity", 0.8)
      .attr("marker-end", (d) => `url(#arr-${d.edge?.status ?? "unverified"})`)
      .style("cursor", "crosshair")
      .on("mouseenter", (ev: MouseEvent, d) => {
        const e = d.edge!;
        const src = (d.source as SimNode).label;
        const tgt = (d.target as SimNode).label;
        const byMethod = Object.entries(e.detected_by_counts)
          .map(([m, c]) => `<span style="color:#94a3b8">${m}</span> ${c}`)
          .join(" · ");
        setTooltip({
          x: ev.clientX + 14,
          y: ev.clientY - 10,
          html: `<b>${src} → ${tgt}</b><br>${e.count} link${e.count !== 1 ? "s" : ""}
                 &nbsp;·&nbsp;<span style="color:${STATUS_COLOR[e.status]}">${e.status}</span><br>
                 <span style="font-size:11px">${byMethod}</span>`,
        });
      })
      .on("mousemove", (ev: MouseEvent) =>
        setTooltip((t) => t ? { ...t, x: ev.clientX + 14, y: ev.clientY - 10 } : null))
      .on("mouseleave", () => setTooltip(null));

    // Edge count labels (only when ≥ 2)
    const edgeLabelG = zoomG.append("g");
    const edgeLabelSel = edgeLabelG.selectAll("text")
      .data(crossLinks.filter((l) => (l.edge?.count ?? 0) >= 2))
      .enter()
      .append("text")
      .attr("fill", "#94a3b8")
      .attr("font-size", 10)
      .attr("text-anchor", "middle")
      .attr("pointer-events", "none")
      .text((d) => String(d.edge?.count ?? ""));

    // ── Draw doc nodes ────────────────────────────────────────────────────
    const docG = zoomG.append("g");
    const docSel = docG.selectAll<SVGGElement, SimNode>("g")
      .data(docNodes)
      .enter()
      .append("g")
      .style("cursor", "pointer")
      .call(
        d3.drag<SVGGElement, SimNode>()
          .on("start", (ev, d) => {
            if (!ev.active) simRef.current?.alphaTarget(0.3).restart();
            d.fx = d.x; d.fy = d.y;
          })
          .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
          .on("end",  (ev, d) => {
            if (!ev.active) simRef.current?.alphaTarget(0);
            d.fx = null; d.fy = null;
          }),
      )
      .on("click", (_ev, d) => {
        if (onGoToCompare && runId) onGoToCompare(runId, d.id);
      })
      .on("mouseenter", (ev: MouseEvent, d) => {
        setTooltip({
          x: ev.clientX + 14,
          y: ev.clientY - 10,
          html: `<b>${d.label}</b><br>${(d.docType ?? "").toUpperCase()}
                 &nbsp;·&nbsp;${d.link_count} outbound link${d.link_count !== 1 ? "s" : ""}
                 ${onGoToCompare ? "<br><span style='color:#818cf8;font-size:11px'>Click to open in Run Compare</span>" : ""}`,
        });
      })
      .on("mousemove", (ev: MouseEvent) =>
        setTooltip((t) => t ? { ...t, x: ev.clientX + 14, y: ev.clientY - 10 } : null))
      .on("mouseleave", () => setTooltip(null));

    // Glow ring
    docSel.append("circle")
      .attr("r", (d) => nodeR(d.link_count) + 7)
      .attr("fill", "none")
      .attr("stroke", (d) => DOC_COLOR[d.docType ?? "pdf"])
      .attr("stroke-width", 1)
      .attr("stroke-opacity", 0.3);

    // Body
    docSel.append("circle")
      .attr("r", (d) => nodeR(d.link_count))
      .attr("fill", (d) => DOC_COLOR[d.docType ?? "pdf"])
      .attr("fill-opacity", 0.9)
      .attr("stroke", "#0f172a")
      .attr("stroke-width", 1.5);

    // Link count text
    docSel.append("text")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("fill", "#fff")
      .attr("font-size", (d) => Math.max(10, nodeR(d.link_count) * 0.45))
      .attr("font-weight", "700")
      .attr("pointer-events", "none")
      .text((d) => d.link_count > 0 ? d.link_count : "");

    // Doc name label
    docSel.append("text")
      .attr("text-anchor", "middle")
      .attr("dy", (d) => nodeR(d.link_count) + 15)
      .attr("fill", "#cbd5e1")
      .attr("font-size", 11)
      .attr("font-weight", "500")
      .attr("pointer-events", "none")
      .text((d) => d.label.length > 20 ? d.label.slice(0, 18) + "…" : d.label);

    // ── Draw dossier root node (on top) ───────────────────────────────────
    const rootG = zoomG.append("g");
    const rootNode = rootG.append("g")
      .datum(dossierNode)
      .style("cursor", "default");

    // Animated pulse rings
    for (let i = 0; i < 3; i++) {
      rootNode.append("circle")
        .attr("r", 50 + i * 14)
        .attr("fill", "none")
        .attr("stroke", DOSSIER_COLOR)
        .attr("stroke-width", 1)
        .attr("stroke-opacity", 0.12 - i * 0.03);
    }

    rootNode.append("circle")
      .attr("r", 48)
      .attr("fill", DOSSIER_COLOR)
      .attr("fill-opacity", 0.18)
      .attr("stroke", DOSSIER_COLOR)
      .attr("stroke-width", 2)
      .attr("filter", "url(#glow)");

    rootNode.append("circle")
      .attr("r", 34)
      .attr("fill", DOSSIER_COLOR)
      .attr("fill-opacity", 0.95)
      .attr("stroke", "#0f172a")
      .attr("stroke-width", 2);

    // Dossier icon SVG (link icon)
    rootNode.append("text")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("font-size", 18)
      .attr("fill", "#fff")
      .attr("pointer-events", "none")
      .text("⛓");

    rootNode.append("text")
      .attr("text-anchor", "middle")
      .attr("dy", 52)
      .attr("fill", "#c4b5fd")
      .attr("font-size", 12)
      .attr("font-weight", "600")
      .attr("pointer-events", "none")
      .text("Dossier");

    rootNode.append("text")
      .attr("text-anchor", "middle")
      .attr("dy", 66)
      .attr("fill", "#7c3aed")
      .attr("font-size", 10)
      .attr("pointer-events", "none")
      .text(`${graph.stats.doc_count} docs · ${graph.stats.total_links} links`);

    rootNode
      .on("mouseenter", (ev: MouseEvent) => {
        setTooltip({
          x: ev.clientX + 14,
          y: ev.clientY - 10,
          html: `<b>Dossier / Run</b><br>${runId}<br>
                 ${graph.stats.doc_count} documents · ${graph.stats.total_links} links · ${graph.stats.edge_count} connections`,
        });
      })
      .on("mousemove", (ev: MouseEvent) =>
        setTooltip((t) => t ? { ...t, x: ev.clientX + 14, y: ev.clientY - 10 } : null))
      .on("mouseleave", () => setTooltip(null));

    // ── Tick ──────────────────────────────────────────────────────────────
    simRef.current.on("tick", () => {
      spokeSel
        .attr("x1", (d) => (d.source as SimNode).x ?? 0)
        .attr("y1", (d) => (d.source as SimNode).y ?? 0)
        .attr("x2", (d) => (d.target as SimNode).x ?? 0)
        .attr("y2", (d) => (d.target as SimNode).y ?? 0);

      crossSel.attr("d", (d) => {
        const s = d.source as SimNode;
        const t = d.target as SimNode;
        const dx = (t.x ?? 0) - (s.x ?? 0);
        const dy = (t.y ?? 0) - (s.y ?? 0);
        const dr = Math.sqrt(dx * dx + dy * dy) * 1.3;
        return `M${s.x},${s.y} A${dr},${dr} 0 0,1 ${t.x},${t.y}`;
      });

      edgeLabelSel
        .attr("x", (d) => {
          const s = d.source as SimNode;
          const t = d.target as SimNode;
          return ((s.x ?? 0) + (t.x ?? 0)) / 2;
        })
        .attr("y", (d) => {
          const s = d.source as SimNode;
          const t = d.target as SimNode;
          return ((s.y ?? 0) + (t.y ?? 0)) / 2 - 8;
        });

      docSel.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);

      // Dossier root stays at centre (fx/fy), but keep the DOM node there
      rootNode.attr("transform", `translate(${cx},${cy})`);
    });

    return () => { simRef.current?.stop(); };
  }, [graph, dims, runId, onGoToCompare]);

  useEffect(() => {
    const cleanup = buildGraph();
    return cleanup;
  }, [buildGraph]);

  const isEmpty  = graph && graph.nodes.length === 0;
  const noEdges  = graph && graph.edges.length === 0 && graph.nodes.length > 0;
  const showSVG  = !loading && !error && graph && !isEmpty;

  return (
    <div
      className="page"
      style={{ maxWidth: "none", height: "100%", display: "flex", flexDirection: "column", padding: 0 }}
    >
      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 24px 0", flexShrink: 0 }}>
        <button className="back-btn" onClick={onBack} style={{ marginBottom: 0 }}>← Back</button>
        <div>
          <div className="page-title" style={{ fontFamily: "var(--ff-display)", marginBottom: 2 }}>
            Dossier Graph
          </div>
          <div className="page-subtitle" style={{ marginBottom: 0 }}>
            Dossier → Documents → Hyperlink connectivity
          </div>
        </div>
      </div>

      {/* ── Controls bar ── */}
      <div style={{
        display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap",
        padding: "10px 24px 10px", flexShrink: 0,
        borderBottom: "1px solid var(--border)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Run</span>
          <select
            value={runId ?? ""}
            onChange={(e) => setRunId(e.target.value || null)}
            style={{
              fontSize: 13, padding: "4px 8px", borderRadius: 6,
              border: "1px solid var(--border)", background: "var(--surface)",
              color: "var(--text)", minWidth: 260,
            }}
          >
            {runs.length === 0 && <option value="">No completed runs</option>}
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>{r.run_id}</option>
            ))}
          </select>
        </div>

        {graph && (
          <div style={{ display: "flex", gap: 14, fontSize: 12, color: "var(--text-muted)" }}>
            <StatPill label="docs"    value={graph.stats.doc_count}    />
            <StatPill label="connections" value={graph.stats.edge_count} />
            <StatPill label="links"   value={graph.stats.total_links}   />
          </div>
        )}

        {/* Legend */}
        <div style={{ display: "flex", gap: 10, marginLeft: "auto", alignItems: "center", flexWrap: "wrap" }}>
          <LegItem color="#22c55e" label="OK" />
          <LegItem color="#f59e0b" label="Unverified" />
          <LegItem color="#ef4444" label="Broken" />
          <span style={{ width: 1, height: 14, background: "var(--border)", display: "inline-block", margin: "0 2px" }} />
          <LegItem color="#818cf8" label="PDF"  circle />
          <LegItem color="#38bdf8" label="DOCX" circle />
          <span style={{ width: 1, height: 14, background: "var(--border)", display: "inline-block", margin: "0 2px" }} />
          <span style={{ fontSize: 10, color: "var(--text-muted)" }}>— regex</span>
          <span style={{ fontSize: 10, color: "var(--text-muted)" }}>– – NER</span>
          <span style={{ fontSize: 10, color: "var(--text-muted)" }}>·· LLM</span>
        </div>
      </div>

      {/* ── Canvas ── */}
      <div
        ref={containerRef}
        style={{
          flex: 1, position: "relative",
          margin: "16px 24px 24px",
          borderRadius: 12,
          border: "1px solid var(--border)",
          overflow: "hidden",
          background: "#080f1e",
          minHeight: 400,
        }}
      >
        {/* Loading */}
        {loading && (
          <Overlay>
            <Spinner />
            <span style={{ marginTop: 12, fontSize: 13, color: "#94a3b8" }}>Building graph…</span>
          </Overlay>
        )}

        {/* Error */}
        {error && <Overlay><span style={{ color: "#ef4444", fontSize: 13 }}>{error}</span></Overlay>}

        {/* Empty run */}
        {isEmpty && (
          <Overlay>
            <span style={{ color: "#64748b", fontSize: 13 }}>No documents found in this run.</span>
          </Overlay>
        )}

        {/* No cross-doc edges warning */}
        {noEdges && !loading && (
          <div style={{
            position: "absolute", top: 12, left: "50%", transform: "translateX(-50%)",
            background: "rgba(245,158,11,0.12)", border: "1px solid #d97706",
            borderRadius: 8, padding: "6px 16px", fontSize: 12, color: "#fbbf24", zIndex: 2,
          }}>
            No cross-document links — only internal or external links were detected.
          </div>
        )}

        {/* SVG */}
        <svg
          ref={svgRef}
          width={dims.w}
          height={dims.h}
          style={{ display: showSVG ? "block" : "none", width: "100%", height: "100%" }}
        />

        {/* Tooltip */}
        {tooltip && (
          <div
            style={{
              position: "fixed",
              left: tooltip.x, top: tooltip.y,
              background: "#1e293b",
              border: "1px solid #334155",
              borderRadius: 8,
              padding: "8px 12px",
              fontSize: 12, color: "#e2e8f0",
              pointerEvents: "none", zIndex: 9999,
              maxWidth: 300,
              boxShadow: "0 8px 28px rgba(0,0,0,0.5)",
              lineHeight: 1.6,
            }}
            dangerouslySetInnerHTML={{ __html: tooltip.html }}
          />
        )}

        {/* Hint */}
        {showSVG && (
          <div style={{
            position: "absolute", bottom: 10, right: 12,
            fontSize: 10, color: "#475569",
            background: "rgba(8,15,30,0.7)", borderRadius: 6, padding: "3px 8px",
          }}>
            Scroll to zoom · Drag to pan · Drag node to pin · Click doc to open Run Compare
          </div>
        )}
      </div>
    </div>
  );
}

// ── sub-components ────────────────────────────────────────────────────────────

function Overlay({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      position: "absolute", inset: 0,
      display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center",
    }}>
      {children}
    </div>
  );
}

function Spinner() {
  return (
    <svg width="36" height="36" viewBox="0 0 36 36" style={{ animation: "spin 1s linear infinite" }}>
      <style>{`@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}`}</style>
      <circle cx="18" cy="18" r="14" stroke="#6366f1" strokeWidth="3"
        fill="none" strokeDasharray="60" strokeDashoffset="20" />
    </svg>
  );
}

function StatPill({ label, value }: { label: string; value: number }) {
  return (
    <span>
      <strong style={{ color: "var(--text)" }}>{value}</strong>
      <span style={{ marginLeft: 4 }}>{label}</span>
    </span>
  );
}

function LegItem({ color, label, circle }: { color: string; label: string; circle?: boolean }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--text-muted)" }}>
      {circle
        ? <span style={{ width: 10, height: 10, borderRadius: "50%", background: color, flexShrink: 0 }} />
        : <span style={{ width: 18, height: 2, background: color, borderRadius: 1, flexShrink: 0 }} />
      }
      {label}
    </span>
  );
}

// Silence unused import warning — shortName used by callers
void shortName;
