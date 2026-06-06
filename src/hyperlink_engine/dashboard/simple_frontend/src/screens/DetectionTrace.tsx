import { useEffect, useState } from "react";
import { api } from "../api";
import type { DetectionTraceData } from "../types";

interface Props {
  onBack: () => void;
}

export function DetectionTrace({ onBack }: Props) {
  const [data, setData] = useState<DetectionTraceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    api
      .detectionTrace()
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "Unknown error");
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="page">
        <div className="center-state">
          <div className="spinner" />
          <p>Loading detection trace…</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="page">
        <div className="error-msg">
          <strong>Error loading detection trace</strong>
          {error}
        </div>
        <button className="btn-primary" onClick={onBack}>
          ← Back to Dashboard
        </button>
      </div>
    );
  }

  return (
    <div className="page" style={{ maxWidth: 1400 }}>
      {/* ── Header ── */}
      <div className="card">
        <div className="card-title">
          🔍 Detection Layer Trace
          <button
            className="btn-ghost"
            onClick={onBack}
            style={{ float: "right", marginTop: -4, fontSize: 12 }}
          >
            ← Back to Dashboard
          </button>
        </div>
        <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "6px 0 0" }}>
          Shows which detection layer (regex, NER, or Ollama LLM) was responsible
          for identifying each reference link across the dossier.
        </p>

        {/* Summary Stats */}
        <div style={{ display: "flex", gap: 16, marginTop: 12, flexWrap: "wrap" }}>
          <div
            style={{
              background: "#f5f5f5",
              padding: "12px 16px",
              borderRadius: 6,
              border: "1px solid var(--border)",
            }}
          >
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>
              Total Documents
            </div>
            <div style={{ fontSize: 18, fontWeight: 700 }}>{data.total_docs}</div>
          </div>

          <div
            style={{
              background: "#f5f5f5",
              padding: "12px 16px",
              borderRadius: 6,
              border: "1px solid var(--border)",
            }}
          >
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>
              Total Links
            </div>
            <div style={{ fontSize: 18, fontWeight: 700 }}>{data.total_links}</div>
          </div>
        </div>
      </div>

      {/* ── Per-Document Breakdown Table ── */}
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card-title">Per-Document Detection Breakdown</div>
        <p style={{ color: "var(--text-muted)", fontSize: 12, marginBottom: 12 }}>
          🟦 Regex only · 🟩 NER triggered · 🟪 Ollama triggered · 🟧 Mixed sources
        </p>

        <div style={{ overflowX: "auto" }}>
          <table className="link-table">
            <thead>
              <tr>
                <th>Document</th>
                <th>Total</th>
                <th style={{ background: "#e8f5e9", color: "#1b5e20" }}>Regex Only</th>
                <th style={{ background: "#fff8e1", color: "#e65100" }}>NER Triggered</th>
                <th style={{ background: "#ffebee", color: "#b71c1c" }}>Ollama Triggered</th>
                <th style={{ background: "#f3e5f5", color: "#6a1b9a" }}>Mixed</th>
              </tr>
            </thead>
            <tbody>
              {data.per_doc.map((doc) => {
                const regexPct = ((doc.regex_only / doc.total_links) * 100).toFixed(0);
                const nerPct = ((doc.ner_triggered / doc.total_links) * 100).toFixed(0);
                const llmPct = ((doc.llm_triggered / doc.total_links) * 100).toFixed(0);
                const mixedPct = ((doc.mixed / doc.total_links) * 100).toFixed(0);

                return (
                  <tr key={doc.doc_name}>
                    <td style={{ fontWeight: 500 }}>{doc.doc_name}</td>
                    <td>{doc.total_links}</td>
                    <td style={{ background: "#e8f5e9", color: "#1b5e20", fontWeight: 500 }}>
                      {doc.regex_only} ({regexPct}%)
                    </td>
                    <td style={{ background: "#fff8e1", color: "#e65100", fontWeight: 500 }}>
                      {doc.ner_triggered} ({nerPct}%)
                    </td>
                    <td style={{ background: "#ffebee", color: "#b71c1c", fontWeight: 500 }}>
                      {doc.llm_triggered} ({llmPct}%)
                    </td>
                    <td style={{ background: "#f3e5f5", color: "#6a1b9a", fontWeight: 500 }}>
                      {doc.mixed} ({mixedPct}%)
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Summary by Layer */}
        <div style={{ marginTop: 20, padding: "12px 0", borderTop: "1px solid var(--border)" }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>Overall Detection Layer Distribution</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
            {(() => {
              const totalRegex = data.per_doc.reduce((sum, d) => sum + d.regex_only, 0);
              const totalNer = data.per_doc.reduce((sum, d) => sum + d.ner_triggered, 0);
              const totalLlm = data.per_doc.reduce((sum, d) => sum + d.llm_triggered, 0);
              const totalMixed = data.per_doc.reduce((sum, d) => sum + d.mixed, 0);

              const stats = [
                { label: "Regex Only", count: totalRegex, pct: (totalRegex / data.total_links * 100).toFixed(1), bg: "#e8f5e9", color: "#1b5e20" },
                { label: "NER Triggered", count: totalNer, pct: (totalNer / data.total_links * 100).toFixed(1), bg: "#fff8e1", color: "#e65100" },
                { label: "Ollama Triggered", count: totalLlm, pct: (totalLlm / data.total_links * 100).toFixed(1), bg: "#ffebee", color: "#b71c1c" },
                { label: "Mixed", count: totalMixed, pct: (totalMixed / data.total_links * 100).toFixed(1), bg: "#f3e5f5", color: "#6a1b9a" },
              ];

              return stats.map((stat) => (
                <div
                  key={stat.label}
                  style={{
                    background: stat.bg,
                    color: stat.color,
                    padding: "12px 14px",
                    borderRadius: 6,
                    border: `1px solid ${stat.color}`,
                  }}
                >
                  <div style={{ fontSize: 11, fontWeight: 500, marginBottom: 4 }}>{stat.label}</div>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>{stat.count}</div>
                  <div style={{ fontSize: 10, opacity: 0.8 }}>{stat.pct}% of total</div>
                </div>
              ));
            })()}
          </div>
        </div>
      </div>

      {/* ── Legend ── */}
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card-title">Detection Layer Legend</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 16 }}>
          <div>
            <h4 style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 600 }}>🟦 Regex Only</h4>
            <p style={{ margin: 0, fontSize: 12, color: "var(--text-muted)" }}>
              Reference detected by regex pattern matching alone. High confidence, pattern-driven approach.
            </p>
          </div>
          <div>
            <h4 style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 600 }}>🟩 NER Triggered</h4>
            <p style={{ margin: 0, fontSize: 12, color: "var(--text-muted)" }}>
              Reference detected by spaCy NER when regex pattern didn't match. Context-aware entity extraction.
            </p>
          </div>
          <div>
            <h4 style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 600 }}>🟪 Ollama Triggered</h4>
            <p style={{ margin: 0, fontSize: 12, color: "var(--text-muted)" }}>
              Reference disambiguated by local Ollama LLM when regex + NER confidence was below threshold. Last-resort refinement.
            </p>
          </div>
          <div>
            <h4 style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 600 }}>🟧 Mixed</h4>
            <p style={{ margin: 0, fontSize: 12, color: "var(--text-muted)" }}>
              Reference involving multiple detection layers or conflict resolution. Complex references requiring multiple passes.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
