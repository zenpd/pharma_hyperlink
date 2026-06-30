import { useEffect, useState, useMemo, useCallback } from "react";
import { api } from "../api";
import { useActiveRun } from "../contexts/ActiveRun";
import type { DocPreview, Link } from "../types";

interface Props {
  onBack: () => void;
}

interface SnippetResult {
  heading: string;
  snippet: string;
  is_table?: boolean;
  matched?: boolean;
  message?: string;
}

// ── helpers ──────────────────────────────────────────────────────────────────

function normalizeWs(s: string) {
  return s.replace(/\s+/g, " ").trim();
}

/**
 * Return a list of {text, isLink, link?} segments for a paragraph.
 *
 * Normalises internal whitespace before searching so that text collapsed
 * differently by PyMuPDF vs the extractor still matches (fixes scanned PDFs).
 */
function segmentParagraph(
  paraText: string,
  links: Link[]
): Array<{ text: string; isLink: boolean; link?: Link }> {
  type Span = { start: number; end: number; link: Link };
  const normalPara = normalizeWs(paraText);
  const spans: Span[] = [];

  for (const link of links) {
    if (!link.link_text) continue;
    const needle = normalizeWs(link.link_text);
    if (!needle) continue;

    let idx = 0;
    while (idx < normalPara.length) {
      const pos = normalPara.indexOf(needle, idx);
      if (pos === -1) break;
      const overlaps = spans.some((s) => pos < s.end && pos + needle.length > s.start);
      if (!overlaps) {
        spans.push({ start: pos, end: pos + needle.length, link });
        break;
      }
      idx = pos + 1;
    }
  }

  spans.sort((a, b) => a.start - b.start);

  const segments: Array<{ text: string; isLink: boolean; link?: Link }> = [];
  let cursor = 0;
  for (const span of spans) {
    if (cursor < span.start) {
      segments.push({ text: normalPara.slice(cursor, span.start), isLink: false });
    }
    segments.push({ text: normalPara.slice(span.start, span.end), isLink: true, link: span.link });
    cursor = span.end;
  }
  if (cursor < normalPara.length) {
    segments.push({ text: normalPara.slice(cursor), isLink: false });
  }
  return segments;
}

function linkColor(status: string) {
  if (status === "ok") return { bg: "#e8f5e9", color: "#1b5e20", border: "#81c784" };
  if (status === "unverified") return { bg: "#fff8e1", color: "#e65100", border: "#ffcc02" };
  return { bg: "#ffebee", color: "#b71c1c", border: "#ef9a9a" };
}

// ── SnippetPanel ─────────────────────────────────────────────────────────────

interface SnippetPanelProps {
  link: Link;
  runId: string;
  onClose: () => void;
}

function SnippetPanel({ link, runId, onClose }: SnippetPanelProps) {
  const [snippet, setSnippet] = useState<SnippetResult | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const doc = link.target_doc || link.source_doc;
    const anchor = link.target_anchor || "";
    api.pipeline.linkSnippet(runId, doc, anchor)
      .then((r) => { setSnippet(r as SnippetResult); setLoading(false); })
      .catch(() => { setSnippet({ heading: "—", snippet: "Could not load snippet.", matched: false }); setLoading(false); });
  }, [link, runId]);

  const c = linkColor(link.status);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        zIndex: 2000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "var(--surface, #fff)",
          borderRadius: 10,
          boxShadow: "0 8px 32px rgba(0,0,0,0.25)",
          padding: "24px 28px",
          maxWidth: 560,
          width: "90%",
          maxHeight: "80vh",
          overflowY: "auto",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
              Link destination
            </div>
            <div style={{ fontSize: 15, fontWeight: 700 }}>
              <span
                style={{
                  background: c.bg, color: c.color, border: `1px solid ${c.border}`,
                  borderRadius: 3, padding: "1px 6px", marginRight: 8, fontSize: 12,
                }}
              >
                {link.status.toUpperCase()}
              </span>
              {link.link_text}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer", color: "var(--text-muted)", lineHeight: 1 }}
          >
            ×
          </button>
        </div>

        {/* Meta row */}
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 12, color: "var(--text-muted)", marginBottom: 14 }}>
          {link.target_doc && (
            <span>📄 <strong style={{ color: "var(--text)" }}>{link.target_doc}</strong></span>
          )}
          {link.target_anchor && (
            <span>⚓ <code style={{ fontSize: 11 }}>{link.target_anchor}</code></span>
          )}
          {link.link_location_descriptor && (
            <span>📍 {link.link_location_descriptor}</span>
          )}
          {link.detected_by && (
            <span>🔍 detected by <strong style={{ color: "var(--text)" }}>{link.detected_by}</strong></span>
          )}
        </div>

        {/* Snippet content */}
        {loading ? (
          <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text-muted)", fontSize: 13 }}>
            <div className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
            Loading destination content…
          </div>
        ) : snippet ? (
          <div style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}>
            {snippet.heading && snippet.heading !== "—" && (
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>
                {snippet.is_table ? "📊 " : "📑 "}{snippet.heading}
              </div>
            )}
            {snippet.snippet && (
              <div
                style={{
                  fontSize: 13,
                  lineHeight: 1.6,
                  color: "#444",
                  background: "var(--surface-alt, #f8f8f8)",
                  borderRadius: 6,
                  padding: "10px 14px",
                  borderLeft: "3px solid var(--primary, #1976d2)",
                }}
              >
                {snippet.snippet}
              </div>
            )}
            {snippet.message && (
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 8 }}>{snippet.message}</div>
            )}
            {snippet.matched === false && (
              <div style={{ fontSize: 11, color: "#e65100", marginTop: 8 }}>
                ⚠ Could not locate exact section — showing document start
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ── component ────────────────────────────────────────────────────────────────

export function Comparison({ onBack }: Props) {
  const { activeRunId } = useActiveRun();
  const [docNames, setDocNames] = useState<string[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null);
  const [preview, setPreview] = useState<DocPreview | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [activeLink, setActiveLink] = useState<Link | null>(null);

  useEffect(() => {
    setLoadingList(true);
    setSelectedDoc(null);
    setPreview(null);
    api.links(activeRunId).then((links) => {
      const seen = new Set<string>();
      const names: string[] = [];
      for (const l of links) {
        if (!seen.has(l.source_doc)) {
          seen.add(l.source_doc);
          names.push(l.source_doc);
        }
      }
      setDocNames(names.sort());
      setLoadingList(false);
    }).catch(() => setLoadingList(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRunId]);

  useEffect(() => {
    if (!selectedDoc) return;
    setLoadingPreview(true);
    setPreview(null);
    api
      .documentPreview(selectedDoc, activeRunId)
      .then((p) => { setPreview(p); setLoadingPreview(false); })
      .catch(() => setLoadingPreview(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDoc, activeRunId]);

  const linkMap = useMemo(() => {
    if (!preview) return new Map<string, Link>();
    const m = new Map<string, Link>();
    for (const l of preview.links) {
      if (l.link_text && !m.has(normalizeWs(l.link_text))) {
        m.set(normalizeWs(l.link_text), l);
      }
    }
    return m;
  }, [preview]);

  const handleLinkClick = useCallback((link: Link) => {
    setActiveLink(link);
  }, []);

  return (
    <div className="page" style={{ maxWidth: 1400 }}>
      {/* ── Header ── */}
      <div className="card">
        <div className="card-title">
          📄 Document Comparison — Before & After
          <button
            className="btn-ghost"
            onClick={onBack}
            style={{ float: "right", marginTop: -4, fontSize: 12 }}
          >
            ← Back to Dashboard
          </button>
        </div>
        <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "6px 0 0" }}>
          Select a document to see its text before (original) and after (hyperlinks injected).
          Click a highlighted word to preview the link destination.
        </p>

        {/* Legend */}
        <div style={{ display: "flex", gap: 16, marginTop: 10, flexWrap: "wrap" }}>
          {[
            { label: "Valid internal link", bg: "#e8f5e9", color: "#1b5e20", border: "#81c784" },
            { label: "External / unverified link", bg: "#fff8e1", color: "#e65100", border: "#ffcc02" },
            { label: "Broken link", bg: "#ffebee", color: "#b71c1c", border: "#ef9a9a" },
          ].map((l) => (
            <span
              key={l.label}
              style={{
                background: l.bg, color: l.color, border: `1px solid ${l.border}`,
                borderRadius: 4, padding: "2px 8px", fontSize: 12, fontWeight: 500,
              }}
            >
              {l.label}
            </span>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        {/* ── Document List ── */}
        <div className="card" style={{ minWidth: 220, maxWidth: 240, flexShrink: 0 }}>
          <div className="card-title" style={{ fontSize: 13, marginBottom: 8 }}>
            Documents ({docNames.length})
          </div>
          {loadingList ? (
            <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading…</div>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {docNames.map((name) => (
                <li key={name}>
                  <button
                    onClick={() => setSelectedDoc(name)}
                    style={{
                      width: "100%", textAlign: "left", padding: "7px 10px", marginBottom: 3,
                      borderRadius: 5, border: "1px solid",
                      borderColor: selectedDoc === name ? "var(--primary)" : "var(--border)",
                      background: selectedDoc === name ? "var(--primary-bg)" : "transparent",
                      color: selectedDoc === name ? "var(--primary)" : "var(--text)",
                      cursor: "pointer", fontSize: 12, fontWeight: selectedDoc === name ? 600 : 400,
                      wordBreak: "break-all",
                    }}
                  >
                    📄 {name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* ── Preview Panels ── */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {!selectedDoc && (
            <div className="card">
              <div className="center-state" style={{ padding: "40px 20px" }}>
                <p style={{ fontSize: 15, color: "var(--text-muted)" }}>
                  👈 Select a document from the list to compare
                </p>
              </div>
            </div>
          )}

          {selectedDoc && loadingPreview && (
            <div className="card">
              <div className="center-state" style={{ padding: "40px 20px" }}>
                <div className="spinner" />
                <p>Loading document preview…</p>
              </div>
            </div>
          )}

          {selectedDoc && !loadingPreview && preview && (
            <>
              {/* Stats row */}
              <div className="stats-row" style={{ marginBottom: 12 }}>
                <div className="stat-box">
                  <div className="stat-num neutral">{preview.total_links}</div>
                  <div className="stat-label">Links Added</div>
                </div>
                <div className="stat-box">
                  <div className="stat-num ok">{preview.ok_links}</div>
                  <div className="stat-label">Valid</div>
                </div>
                <div className="stat-box">
                  <div className="stat-num warn">{preview.unverified_links}</div>
                  <div className="stat-label">External</div>
                </div>
                <div className="stat-box">
                  <div className="stat-num block">{preview.broken_links}</div>
                  <div className="stat-label">Broken</div>
                </div>
                <div className="stat-box">
                  <div className="stat-num neutral">{preview.paragraphs.length}</div>
                  <div className="stat-label">Paragraphs</div>
                </div>
              </div>

              {/* Side-by-side panels */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                {/* BEFORE */}
                <div className="card" style={{ padding: 0 }}>
                  <div style={{
                    padding: "10px 14px", borderBottom: "1px solid var(--border)",
                    background: "#f5f5f5", borderRadius: "8px 8px 0 0",
                    display: "flex", alignItems: "center", gap: 8,
                  }}>
                    <span style={{ fontSize: 18 }}>📃</span>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 13 }}>BEFORE (Original)</div>
                      <div style={{ fontSize: 11, color: "#666" }}>{preview.orig_path}</div>
                    </div>
                    <span style={{ marginLeft: "auto", background: "#eee", borderRadius: 4, padding: "2px 7px", fontSize: 11, color: "#555" }}>
                      No hyperlinks
                    </span>
                  </div>
                  <div style={{ padding: "12px 14px", maxHeight: 520, overflowY: "auto", fontSize: 13, lineHeight: 1.65 }}>
                    {preview.paragraphs.map((p) => (
                      <p key={p.index} style={{ margin: "0 0 8px", color: "#444" }}>{p.text}</p>
                    ))}
                  </div>
                </div>

                {/* AFTER */}
                <div className="card" style={{ padding: 0 }}>
                  <div style={{
                    padding: "10px 14px", borderBottom: "1px solid var(--border)",
                    background: "#e8f5e9", borderRadius: "8px 8px 0 0",
                    display: "flex", alignItems: "center", gap: 8,
                  }}>
                    <span style={{ fontSize: 18 }}>🔗</span>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 13 }}>AFTER (Hyperlinked)</div>
                      <div style={{ fontSize: 11, color: "#444" }}>{preview.doc_name ?? selectedDoc}</div>
                    </div>
                    <span style={{ marginLeft: "auto", background: "#c8e6c9", borderRadius: 4, padding: "2px 7px", fontSize: 11, color: "#1b5e20", fontWeight: 600 }}>
                      {preview.total_links} links added ✓
                    </span>
                  </div>
                  <div style={{ padding: "12px 14px", maxHeight: 520, overflowY: "auto", fontSize: 13, lineHeight: 1.65, position: "relative" }}>
                    {preview.paragraphs.map((p) => {
                      const segments = segmentParagraph(p.text, preview.links);
                      return (
                        <p key={p.index} style={{ margin: "0 0 8px", color: "#444" }}>
                          {segments.map((seg, si) => {
                            if (!seg.isLink || !seg.link) return <span key={si}>{seg.text}</span>;
                            const c = linkColor(seg.link.status);
                            return (
                              <span
                                key={si}
                                title={`Click to preview: ${seg.link.target_anchor || seg.link.target_doc || "—"}`}
                                style={{
                                  background: c.bg, color: c.color, border: `1px solid ${c.border}`,
                                  borderRadius: 3, padding: "0 3px", cursor: "pointer",
                                  fontWeight: 500, textDecoration: "underline", textDecorationStyle: "dotted",
                                }}
                                onClick={() => handleLinkClick(seg.link!)}
                              >
                                {seg.text}
                              </span>
                            );
                          })}
                        </p>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Link table */}
              <div className="card" style={{ marginTop: 12 }}>
                <div className="card-title">All Injected Links ({preview.total_links})</div>
                <div style={{ overflowX: "auto", maxHeight: 280, overflowY: "auto" }}>
                  <table className="link-table">
                    <thead>
                      <tr>
                        <th>Link Text</th>
                        <th>Target</th>
                        <th>Location</th>
                        <th>Status</th>
                        <th>Confidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.links.map((l, i) => (
                        <tr
                          key={i}
                          style={{ cursor: "pointer" }}
                          onClick={() => handleLinkClick(l)}
                          title="Click to preview link destination"
                        >
                          <td style={{ fontWeight: 500, color: "var(--primary)", textDecoration: "underline", textDecorationStyle: "dotted" }}>
                            {l.link_text}
                          </td>
                          <td
                            style={{ fontSize: 11, color: "var(--text-muted)", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                            title={l.target_anchor || l.target_doc}
                          >
                            {l.target_anchor || l.target_doc || "—"}
                          </td>
                          <td style={{ fontSize: 11, color: "var(--text-muted)" }}>
                            {l.link_location_descriptor || "—"}
                          </td>
                          <td>
                            <span className={`link-status ${l.status}`}>{l.status.toUpperCase()}</span>
                          </td>
                          <td>{Math.round(l.confidence * 100)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Snippet Panel (modal) ── */}
      {activeLink && (
        <SnippetPanel
          link={activeLink}
          runId={activeRunId ?? ""}
          onClose={() => setActiveLink(null)}
        />
      )}
    </div>
  );
}
