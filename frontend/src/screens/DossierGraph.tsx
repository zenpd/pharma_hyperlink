/**
 * Screen: Dossier Graph
 *
 * D3 force-directed visualization of document connectivity within a pipeline run.
 * Nodes = documents (sized by outbound link count, colored by file type).
 * Edges = cross-document hyperlinks (colored by health, style by detection method).
 *
 * Features:
 *  - Zoom / pan (d3.zoom, mouse wheel + drag canvas)
 *  - Drag individual nodes
 *  - Hover tooltip (doc stats, edge details)
 *  - Click node → filters to that document in the sidebar list
 *  - Legend: edge health colors + detection method styles
 *  - Stats bar: doc count, edge count, total links
 */

import { useEffect, useRef, useState, useCallback } from "react";
import * as d3 from "d3";
import { api } from "../api";
import type { RunGraph, GraphNode, GraphEdge } from "../types";

interface Props {
  onBack: () => void;
  onGoToCompare?: (runId: string, doc: string) => void;
}

// ── color / style maps ───────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  ok: "#22c55e",
  broken: "#ef4444",
  unverified: "#f59e0b",
};

const DETECTION_DASH: Record<string, string> = {
  regex: "none",
  ner: "6,3",
  llm: "2,4",
};

const NODE_FILL: Record<string, string> = {
  pdf: "#6366f1",
  docx: "#0ea5e9",
};

// ── simulation node/link types ───────────────────────────────────────────────

interface SimNode extends GraphNode, d3.SimulationNodeDatum {}
interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  edge: GraphEdge;
}

// ── component ────────────────────────────────────────────────────────────────

export function DossierGraph({ onBack, onGoToCompare }: Props) {
  const [runs, setRuns] = useState<{ run_id: string; label: string }[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [graph, setGraph] = useState<RunGraph | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tooltip, setTooltip] = useState<{ x: number; y: number; html: string } | null>(null);
  const [highlighted, setHighlighted] = useState<string | null>(null);

  const svgRef = useRef<SVGSVGElement>(null);
  const simRef = useRef<d3.Simulation<SimNode, SimLink> | null>(null);

  // Load run list
  useEffect(() => {
    api.pipeline.listRuns().then((data) => {
      const done = (data.runs ?? [])
        .filter((r) => r.status === "done")
        .sort((a, b) => b.run_id.localeCompare(a.run_id));
      setRuns(done.map((r) => ({ run_id: r.run_id, label: r.run_id })));
      if (done.length > 0) setRunId(done[0].run_id);
    }).catch(() => {});
  }, []);

  // Load graph when run changes
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

  // Build / rebuild the D3 scene whenever graph data changes
  const buildGraph = useCallback(() => {
    if (!graph || !svgRef.current) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = svgRef.current.clientWidth || 900;
    const height = svgRef.current.clientHeight || 640;

    // Arrow markers — one per status color
    const defs = svg.append("defs");
    Object.entries(STATUS_COLOR).forEach(([status, color]) => {
      defs.append("marker")
        .attr("id", `arrow-${status}`)
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 22)
        .attr("refY", 0)
        .attr("markerWidth", 6)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("fill", color)
        .attr("d", "M0,-5L10,0L0,5");
    });

    // Zoom / pan container
    const g = svg.append("g");
    svg.call(
      d3.zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.15, 5])
        .on("zoom", (event) => g.attr("transform", event.transform)),
    );

    // Prepare simulation data
    const nodes: SimNode[] = graph.nodes.map((n) => ({ ...n }));
    const nodeById = new Map(nodes.map((n) => [n.id, n]));

    const links: SimLink[] = graph.edges
      .map((e) => {
        const src = nodeById.get(e.source);
        const tgt = nodeById.get(e.target);
        if (!src || !tgt) return null;
        return { source: src, target: tgt, edge: e } as SimLink;
      })
      .filter((l): l is SimLink => l !== null);

    const maxLinks = Math.max(1, ...nodes.map((n) => n.link_count));
    const nodeRadius = d3.scaleSqrt().domain([0, maxLinks]).range([14, 46]);
    const edgeWidth = d3.scaleLinear()
      .domain([1, Math.max(1, d3.max(graph.edges, (e) => e.count) ?? 1)])
      .range([1.5, 6])
      .clamp(true);

    // Force simulation
    simRef.current = d3.forceSimulation<SimNode>(nodes)
      .force("link", d3.forceLink<SimNode, SimLink>(links).id((d) => d.id).distance(160).strength(0.5))
      .force("charge", d3.forceManyBody().strength(-600))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide<SimNode>().radius((d) => nodeRadius(d.link_count) + 10));

    // ── Draw edges ──────────────────────────────────────────────────────────
    const edgeG = g.append("g").attr("class", "edges");
    const link = edgeG.selectAll("path")
      .data(links)
      .enter()
      .append("path")
      .attr("fill", "none")
      .attr("stroke", (d) => STATUS_COLOR[d.edge.status] ?? "#94a3b8")
      .attr("stroke-width", (d) => edgeWidth(d.edge.count))
      .attr("stroke-dasharray", (d) => DETECTION_DASH[d.edge.detected_by] ?? "none")
      .attr("stroke-opacity", 0.7)
      .attr("marker-end", (d) => `url(#arrow-${d.edge.status})`)
      .style("cursor", "default")
      .on("mouseenter", (event: MouseEvent, d) => {
        const methodCounts = Object.entries(d.edge.detected_by_counts)
          .map(([m, c]) => `${m}: ${c}`)
          .join(", ");
        setTooltip({
          x: event.clientX + 12,
          y: event.clientY - 8,
          html: `
            <div style="font-weight:600;margin-bottom:4px">${shortLabel(d.edge.source as unknown as SimNode)} → ${shortLabel(d.edge.target as unknown as SimNode)}</div>
            <div>${d.edge.count} link${d.edge.count !== 1 ? "s" : ""} · ${d.edge.status}</div>
            <div style="margin-top:2px;color:#94a3b8">${methodCounts}</div>
          `,
        });
      })
      .on("mousemove", (event: MouseEvent) => {
        setTooltip((t) => t ? { ...t, x: event.clientX + 12, y: event.clientY - 8 } : null);
      })
      .on("mouseleave", () => setTooltip(null));

    // Edge count labels on edges with ≥2 links
    const edgeLabel = g.append("g").attr("class", "edge-labels")
      .selectAll("text")
      .data(links.filter((l) => l.edge.count >= 2))
      .enter()
      .append("text")
      .attr("fill", "#94a3b8")
      .attr("font-size", 10)
      .attr("text-anchor", "middle")
      .attr("pointer-events", "none")
      .text((d) => `${d.edge.count}`);

    // ── Draw nodes ──────────────────────────────────────────────────────────
    const nodeG = g.append("g").attr("class", "nodes");
    const node = nodeG.selectAll("g")
      .data(nodes)
      .enter()
      .append("g")
      .style("cursor", "pointer")
      .call(
        d3.drag<SVGGElement, SimNode>()
          .on("start", (event, d) => {
            if (!event.active) simRef.current?.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
          .on("end", (event, d) => {
            if (!event.active) simRef.current?.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          }),
      )
      .on("click", (_event, d) => {
        setHighlighted((h) => h === d.id ? null : d.id);
        if (onGoToCompare && runId) onGoToCompare(runId, d.id);
      })
      .on("mouseenter", (event: MouseEvent, d) => {
        setTooltip({
          x: event.clientX + 14,
          y: event.clientY - 12,
          html: `
            <div style="font-weight:600;margin-bottom:4px">${d.label}</div>
            <div>${d.type.toUpperCase()} · ${d.link_count} outbound link${d.link_count !== 1 ? "s" : ""}</div>
          `,
        });
      })
      .on("mousemove", (event: MouseEvent) => {
        setTooltip((t) => t ? { ...t, x: event.clientX + 14, y: event.clientY - 12 } : null);
      })
      .on("mouseleave", () => setTooltip(null));

    // Outer glow ring
    node.append("circle")
      .attr("r", (d) => nodeRadius(d.link_count) + 5)
      .attr("fill", "none")
      .attr("stroke", (d) => NODE_FILL[d.type] ?? "#6366f1")
      .attr("stroke-width", 1.5)
      .attr("stroke-opacity", 0.25);

    // Node body
    node.append("circle")
      .attr("r", (d) => nodeRadius(d.link_count))
      .attr("fill", (d) => NODE_FILL[d.type] ?? "#6366f1")
      .attr("fill-opacity", 0.92)
      .attr("stroke", "#1e1b4b")
      .attr("stroke-width", 1.5);

    // Link count badge
    node.append("text")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("fill", "#fff")
      .attr("font-size", (d) => Math.max(10, nodeRadius(d.link_count) * 0.45))
      .attr("font-weight", "700")
      .attr("pointer-events", "none")
      .text((d) => d.link_count > 0 ? d.link_count : "");

    // Node label below circle
    node.append("text")
      .attr("text-anchor", "middle")
      .attr("dy", (d) => nodeRadius(d.link_count) + 14)
      .attr("fill", "#e2e8f0")
      .attr("font-size", 11)
      .attr("font-weight", "500")
      .attr("pointer-events", "none")
      .text((d) => d.label.length > 22 ? d.label.slice(0, 20) + "…" : d.label);

    // ── Tick handler ────────────────────────────────────────────────────────
    simRef.current.on("tick", () => {
      link.attr("d", (d) => {
        const src = d.source as SimNode;
        const tgt = d.target as SimNode;
        const dx = (tgt.x ?? 0) - (src.x ?? 0);
        const dy = (tgt.y ?? 0) - (src.y ?? 0);
        const dr = Math.sqrt(dx * dx + dy * dy) * 1.4; // curve radius
        return `M${src.x},${src.y} A${dr},${dr} 0 0,1 ${tgt.x},${tgt.y}`;
      });

      edgeLabel.attr("x", (d) => {
        const src = d.source as SimNode;
        const tgt = d.target as SimNode;
        return ((src.x ?? 0) + (tgt.x ?? 0)) / 2;
      }).attr("y", (d) => {
        const src = d.source as SimNode;
        const tgt = d.target as SimNode;
        return ((src.y ?? 0) + (tgt.y ?? 0)) / 2 - 8;
      });

      node.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    return () => { simRef.current?.stop(); };
  }, [graph, onGoToCompare, runId]);

  useEffect(() => {
    const cleanup = buildGraph();
    return cleanup;
  }, [buildGraph]);

  // Reheat on resize
  useEffect(() => {
    const obs = new ResizeObserver(() => simRef.current?.alpha(0.3).restart());
    if (svgRef.current) obs.observe(svgRef.current);
    return () => obs.disconnect();
  }, []);

  const isEmpty = graph && graph.nodes.length === 0;
  const noEdges = graph && graph.edges.length === 0 && graph.nodes.length > 0;

  return (
    <div className="page" style={{ maxWidth: "none", height: "100%", display: "flex", flexDirection: "column" }}>
      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 24px 0", flexShrink: 0 }}>
        <button className="back-btn" onClick={onBack} style={{ marginBottom: 0 }}>← Back</button>
        <div>
          <div className="page-title" style={{ fontFamily: "var(--ff-display)", marginBottom: 2 }}>Dossier Graph</div>
          <div className="page-subtitle" style={{ marginBottom: 0 }}>
            Document connectivity — hyperlink topology across the run
          </div>
        </div>
      </div>

      {/* ── Controls bar ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "12px 24px", flexShrink: 0, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <label style={{ fontSize: 12, color: "var(--text-muted)", whiteSpace: "nowrap" }}>Run</label>
          <select
            value={runId ?? ""}
            onChange={(e) => setRunId(e.target.value || null)}
            style={{
              fontSize: 13, padding: "4px 8px", borderRadius: 6,
              border: "1px solid var(--border)", background: "var(--surface)",
              color: "var(--text)", minWidth: 280,
            }}
          >
            {runs.length === 0 && <option value="">No completed runs</option>}
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>{r.run_id}</option>
            ))}
          </select>
        </div>

        {graph && (
          <div style={{ display: "flex", gap: 16, fontSize: 12, color: "var(--text-muted)" }}>
            <span><strong style={{ color: "var(--text)" }}>{graph.stats.doc_count}</strong> docs</span>
            <span><strong style={{ color: "var(--text)" }}>{graph.stats.edge_count}</strong> connections</span>
            <span><strong style={{ color: "var(--text)" }}>{graph.stats.total_links}</strong> links</span>
          </div>
        )}

        {/* Legend */}
        <div style={{ display: "flex", gap: 14, marginLeft: "auto", alignItems: "center", flexWrap: "wrap" }}>
          <LegendItem color="#22c55e" label="OK" />
          <LegendItem color="#f59e0b" label="Unverified" />
          <LegendItem color="#ef4444" label="Broken" />
          <LegendItem color="#6366f1" label="PDF" shape="circle" />
          <LegendItem color="#0ea5e9" label="DOCX" shape="circle" />
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>—— regex</span>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>- - NER</span>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>·· LLM</span>
        </div>
      </div>

      {/* ── Graph canvas ── */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden", margin: "0 24px 24px" }}>
        {loading && (
          <div style={overlayStyle}>
            <Spinner />
            <span style={{ marginTop: 12, color: "var(--text-muted)", fontSize: 14 }}>Building graph…</span>
          </div>
        )}
        {error && (
          <div style={{ ...overlayStyle, color: "#ef4444" }}>{error}</div>
        )}
        {isEmpty && (
          <div style={overlayStyle}>
            <span style={{ color: "var(--text-muted)", fontSize: 14 }}>No documents detected in this run.</span>
          </div>
        )}
        {noEdges && !loading && (
          <div style={{
            position: "absolute", top: 12, left: "50%", transform: "translateX(-50%)",
            background: "rgba(245,158,11,0.12)", border: "1px solid #f59e0b",
            borderRadius: 8, padding: "6px 14px", fontSize: 12, color: "#f59e0b", zIndex: 2,
          }}>
            No cross-document links found — only internal or external links detected.
          </div>
        )}
        <svg
          ref={svgRef}
          style={{
            width: "100%", height: "100%",
            background: "var(--surface, #0f172a)",
            borderRadius: 12,
            border: "1px solid var(--border)",
            display: "block",
          }}
        />

        {/* Tooltip */}
        {tooltip && (
          <div
            style={{
              position: "fixed",
              left: tooltip.x,
              top: tooltip.y,
              background: "#1e293b",
              border: "1px solid #334155",
              borderRadius: 8,
              padding: "8px 12px",
              fontSize: 12,
              color: "#e2e8f0",
              pointerEvents: "none",
              zIndex: 9999,
              maxWidth: 280,
              boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
              lineHeight: 1.5,
            }}
            dangerouslySetInnerHTML={{ __html: tooltip.html }}
          />
        )}

        {/* Help hint */}
        {!loading && graph && graph.nodes.length > 0 && (
          <div style={{
            position: "absolute", bottom: 12, right: 12,
            fontSize: 11, color: "var(--text-muted)",
            background: "rgba(15,23,42,0.75)", borderRadius: 6, padding: "4px 10px",
          }}>
            Scroll to zoom · Drag to pan · Drag node to pin · Click node to navigate
          </div>
        )}
      </div>
    </div>
  );
}

// ── helpers ───────────────────────────────────────────────────────────────────

function shortLabel(node: SimNode): string {
  return node?.label ?? String(node);
}

const overlayStyle: React.CSSProperties = {
  position: "absolute", inset: 0, display: "flex", flexDirection: "column",
  alignItems: "center", justifyContent: "center",
};

function Spinner() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" style={{ animation: "spin 1s linear infinite" }}>
      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
      <circle cx="16" cy="16" r="12" stroke="#6366f1" strokeWidth="3" fill="none" strokeDasharray="50" strokeDashoffset="20" />
    </svg>
  );
}

function LegendItem({ color, label, shape = "line" }: { color: string; label: string; shape?: "line" | "circle" }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--text-muted)" }}>
      {shape === "circle"
        ? <span style={{ width: 10, height: 10, borderRadius: "50%", background: color, display: "inline-block" }} />
        : <span style={{ width: 18, height: 2, background: color, display: "inline-block", borderRadius: 1 }} />
      }
      {label}
    </span>
  );
}
