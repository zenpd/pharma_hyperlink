/**
 * Screen: Reference View
 *
 * A dedicated, focused page that opens when a user clicks a hyperlink in Run
 * Compare. It loads the *target* (hyperlinked) document, scrolls down to the
 * exact referenced table / section / paragraph, and flashes it — so the user
 * sees "where the link relates to" without losing the source context.
 *
 * Resolution flow (reuses existing backend endpoints, no inline doc swap):
 *   1. linkSnippet(runId, docHint, anchor)  → found_in (real target doc) + heading
 *   2. documentPreview(runId, found_in)      → the target document's paragraphs+links
 *   3. auto-scroll + highlight the paragraph matching the heading / number
 *
 * Clicking a link *inside* this view pushes a new reference onto an internal
 * history stack, so the reader can walk the cross-document chain back and forth.
 */

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { api } from "../api";
import { externalUrl, segmentParagraph } from "../components/BeforeAfter";
import { findRefBlockIndex, findRefEntryIndex } from "../refMatch";
import type { DocPreview, DocPreviewBlock, Link, LinkSnippet } from "../types";

// One hop in the cross-document reference chain.
export interface RefTarget {
  /** Target document hint (link.target_doc). May be empty for internal refs. */
  docHint: string;
  /** Anchor to locate: target_anchor or the link text. */
  anchor: string;
  /** The document the click came from (for the breadcrumb). */
  sourceDoc: string;
  /** The visible link text that was clicked (for the breadcrumb). */
  linkText: string;
  /** The injected bookmark slug (link.target_anchor), e.g. "ref_helget_2024".
   *  Lets a citation land on its References ENTRY rather than the first textual
   *  occurrence (the citation itself). */
  bookmarkAnchor?: string;
}

interface Props {
  onBack: () => void;
  active?: boolean;
  runId?: string;
  target?: RefTarget;
}

function linkColor(status: string) {
  if (status === "ok") return { bg: "#e8f5e9", color: "#1b5e20", border: "#81c784" };
  if (status === "unverified") return { bg: "#fff8e1", color: "#e65100", border: "#ffcc02" };
  return { bg: "#ffebee", color: "#b71c1c", border: "#ef9a9a" };
}

// Real-table rendering styles — mirror the BeforeAfter compare panels so a
// referenced table renders as a grid here too (instead of the scattered
// " | "-joined flattened text that table blocks carry in their `text` field).
const DOCX_TABLE_STYLE: CSSProperties = {
  borderCollapse: "collapse",
  width: "100%",
  margin: "4px 0 12px",
  fontSize: 12,
  background: "#fff",
};
const DOCX_CELL_STYLE: CSSProperties = {
  border: "1px solid #cfd8dc",
  padding: "3px 7px",
  textAlign: "left",
  verticalAlign: "top",
};

/** Locate the paragraph index to scroll to, given a heading and/or a number.
 *
 * Lands on the EXACT referenced section/table/figure. Uses the shared
 * boundary-safe, type-aware matcher (`findRefBlockIndex`, also used by the
 * compare panel and the Word viewer), so "Section 2.5" never hijacks to a
 * "Table 14.2.5.1" caption and a missing "2.7.3.3" no longer drops the reader
 * onto the root section (the old progressive "2.7.3.3 → 2.7 → 2" fallback).
 */
function findTargetIndex(
  preview: DocPreview,
  heading: string,
  anchor: string,
  bookmarkAnchor?: string,
): number | null {
  const paras = preview.paragraphs;

  // 0. Literature citation ("Helget LN, 2024") carries a ref_* bookmark slug.
  //    Jump to its References ENTRY, not the first textual "Helget" (the
  //    citation itself). Checked before the heading match for that reason.
  if (bookmarkAnchor && /^ref_/i.test(bookmarkAnchor)) {
    const ri = findRefEntryIndex(paras, bookmarkAnchor);
    if (ri >= 0) return ri;
  }

  // 0b. Typed reference (Figure / Table / Listing / Appendix / Section + number)
  //     → land on its DEFINITION caption ("Figure 2 …", "Appendix 1 …"), NOT the
  //     first textual mention. The snippet endpoint returns that first mention
  //     (a Table-of-Contents line or a "see Figure 2" body sentence) as its
  //     heading, so we must run the boundary-safe matcher BEFORE trusting the
  //     heading — otherwise the reader gets stuck on the first figure / the TOC
  //     instead of the root figure / appendix.
  // Fire for a typed reference anywhere in the text — "Section 6.1" at the start
  // OR embedded ("Study ID TMX-67_301 Section 6.1"), plus the "<kind>_ref_N" slug.
  const typedRef = (anchor || "").trim() || (heading || "").trim();
  if (
    /\b(figure|table|listing|appendix|section)s?\.?\s+\w/i.test(typedRef) ||
    /_ref_/i.test(typedRef)
  ) {
    const di = findRefBlockIndex(paras, typedRef);
    if (di >= 0) return di;
  }

  // 1. Exact heading text from the snippet (forward match ONLY — a short early
  //    paragraph must not match merely by being a substring of the heading,
  //    which used to land the reader on the document's root section). Skip the
  //    Table-of-Contents (dotted-leader lines) — it contains every heading title
  //    and was stealing the scroll on large PDFs.
  if (heading) {
    const needle = heading.slice(0, 60).toLowerCase();
    const hit = paras.find(
      (p) => !/\.{4,}/.test(p.text || "") && p.text.toLowerCase().includes(needle),
    );
    if (hit) return hit.index;
  }

  // 2. Boundary-safe, type-aware match on the reference text. Never resolves a
  //    Section/Appendix to a table block, and never root-drops.
  const idx = findRefBlockIndex(paras, anchor || heading);
  return idx >= 0 ? idx : null;
}

export function ReferenceView({ onBack, active = true, runId, target }: Props) {
  // Internal history stack for back-and-forth across the reference chain.
  const [stack, setStack] = useState<RefTarget[]>(target ? [target] : []);

  // Reset the stack whenever a new top-level target arrives from Run Compare.
  useEffect(() => {
    if (target) setStack([target]);
  }, [target?.docHint, target?.anchor, target?.linkText]);

  const current = stack.length ? stack[stack.length - 1] : null;

  const [snippet, setSnippet] = useState<LinkSnippet | null>(null);
  const [preview, setPreview] = useState<DocPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [highlightPara, setHighlightPara] = useState<number | null>(null);
  // Whether we managed to scroll to the referenced spot (null = not resolved yet).
  const [located, setLocated] = useState<boolean | null>(null);

  // Keyed by block index; holds <p> or <table> elements (widened from <p> only
  // now that table blocks render as real grids and need their own scroll anchor).
  const paraRefs = useRef<Record<number, HTMLElement | null>>({});
  const scrollBoxRef = useRef<HTMLDivElement | null>(null);

  // Resolve the destination (snippet → found_in → preview) for the current hop.
  useEffect(() => {
    if (!runId || !current) {
      setPreview(null);
      setSnippet(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    setPreview(null);
    setSnippet(null);
    setLocated(null);

    (async () => {
      try {
        // 1. Ask the backend where this reference actually lands.
        const snip = await api.pipeline.linkSnippet(runId, current.docHint, current.anchor);
        if (cancelled) return;
        setSnippet(snip);

        // 2. Load the document that actually contains the section/table.
        const targetDoc = snip.found_in || current.docHint;
        if (!targetDoc) {
          setError("Could not resolve which document this reference points to.");
          setLoading(false);
          return;
        }
        const prev = await api.pipeline.documentPreview(runId, targetDoc);
        if (cancelled) return;
        setPreview(prev);
        setLoading(false);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Failed to load referenced document");
        setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [runId, current?.docHint, current?.anchor, current?.linkText]);

  // Auto-scroll + flash once the preview has painted.
  useEffect(() => {
    if (!preview || !current) return;
    // When the backend could NOT match the anchor it returns matched:false with
    // heading = the document's first paragraph. Trusting that heading makes us
    // "locate" paragraph 0 and scroll to the top — the exact bug we're fixing.
    // So only use the heading as a locator when the snippet actually matched;
    // otherwise fall back to the dotted-number search on the link text.
    const heading = snippet?.matched === false ? "" : (snippet?.heading ?? "");
    const idx = findTargetIndex(
      preview, heading, current.anchor || current.linkText, current.bookmarkAnchor,
    );
    if (idx == null) {
      setLocated(false);
      // Nothing matched — make sure the reader sees the document from the top.
      scrollBoxRef.current?.scrollTo({ top: 0 });
      return;
    }
    setLocated(true);
    const tid = window.setTimeout(() => scrollToIndex(idx), 180);
    return () => window.clearTimeout(tid);
  }, [preview, snippet, current?.anchor]);

  // Smooth-scroll + flash the matched block. We pin it near the TOP of the scroll
  // box (not centered): a section heading like "6.1 Study Design" should land at the
  // top of the view, not mid-screen under the running page header / parent "6.0"
  // heading — which read as "it didn't scroll exactly to 6.1". Scrolling the box
  // directly (vs scrollIntoView) also avoids the outer page jumping.
  function scrollToIndex(idx: number) {
    const el = paraRefs.current[idx];
    const box = scrollBoxRef.current;
    if (el && box) {
      const top =
        box.scrollTop + (el.getBoundingClientRect().top - box.getBoundingClientRect().top) - 16;
      box.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    } else {
      el?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    setHighlightPara(idx);
    window.setTimeout(() => setHighlightPara(null), 2400);
  }

  const targetDocName = useMemo(
    () => snippet?.found_in || preview?.doc_name || current?.docHint || "",
    [snippet, preview, current],
  );

  // Does this link point back into the document already on screen?
  // (internal anchor with no target doc, or a target doc that *is* this doc).
  function isSameDocRef(link: Link): boolean {
    const td = (link.target_doc || "").trim().toLowerCase();
    if (!td) return true; // internal bookmark — same document by definition
    const candidates = [targetDocName, preview?.doc_name, preview?.orig_path]
      .filter(Boolean)
      .map((s) => String(s).toLowerCase());
    return candidates.some((c) => c === td || c.endsWith(td) || td.endsWith(c));
  }

  // Click a link inside the referenced document.
  //  · Same-document reference → scroll in place (no redirect / reload).
  //  · Cross-document reference → push a new hop onto the chain.
  function handleInnerLink(link: Link) {
    // External website → always open externally; never push a new reference hop.
    const url = externalUrl(link);
    if (url) {
      window.open(url, "_blank", "noopener,noreferrer");
      return;
    }
    // Locate by the human link text (carries the dotted number) — not the
    // injected bookmark slug in target_anchor, which the resolver can't parse.
    const anchor = link.link_text || link.target_anchor;

    // In-page scroll for same-doc refs — mirrors the Before/After behavior.
    if (preview && isSameDocRef(link)) {
      const idx = findTargetIndex(preview, "", anchor);
      if (idx != null) {
        scrollToIndex(idx);
        return;
      }
      // Fall through to a redirect only if we genuinely can't locate it here.
    }

    setStack((s) => [
      ...s,
      {
        docHint: link.target_doc || "",
        anchor,
        sourceDoc: targetDocName,
        linkText: link.link_text,
      },
    ]);
  }

  function popStack() {
    setStack((s) => (s.length > 1 ? s.slice(0, -1) : s));
  }

  // ── block renderers ────────────────────────────────────────────────────────

  /** Turn link/plain segments into spans; link spans follow the reference chain. */
  function renderSegments(segments: ReturnType<typeof segmentParagraph>) {
    return segments.map((seg, si) => {
      if (!seg.isLink || !seg.link) return <span key={si}>{seg.text}</span>;
      const c = linkColor(seg.link.status);
      return (
        <span
          key={si}
          onClick={() => handleInnerLink(seg.link!)}
          style={{
            background: c.bg, color: c.color, border: `1px solid ${c.border}`,
            borderRadius: 3, padding: "0 3px", cursor: "pointer",
            fontWeight: 500, textDecoration: "underline", textDecorationStyle: "dotted",
          }}
          title={`${seg.link.status.toUpperCase()}: ${seg.link.target_anchor || seg.link.target_doc || "—"}`}
        >
          {seg.text}
        </span>
      );
    });
  }

  /** Render one document block — a real <table> for table blocks, else a <p>.
   *  Both carry the scroll ref + flash highlight keyed by block index, so
   *  scroll-to-reference lands on (and flashes) a table grid just like a para. */
  function renderBlock(b: DocPreviewBlock) {
    const links = preview?.links ?? [];
    const flash = highlightPara === b.index;
    if (b.type === "image" && b.src) {
      return (
        <img key={b.index} ref={(el) => { paraRefs.current[b.index] = el; }}
          src={b.src} alt="figure"
          style={{ display: "block", maxWidth: "100%", height: "auto", margin: "8px 0",
                   border: "1px solid #eee", borderRadius: 4,
                   boxShadow: flash ? "0 0 0 2px #ffe08a" : "none", transition: "box-shadow 0.4s" }} />
      );
    }
    if (b.type === "table" && b.rows && b.rows.length > 0) {
      return (
        <table
          key={b.index}
          ref={(el) => { paraRefs.current[b.index] = el; }}
          style={{
            ...DOCX_TABLE_STYLE,
            background: flash ? "#fff3cd" : "#fff",
            boxShadow: flash ? "0 0 0 2px #ffe08a" : "none",
            transition: "background 0.4s, box-shadow 0.4s",
          }}
        >
          <tbody>
            {b.rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td key={ci} style={DOCX_CELL_STYLE}>
                    {renderSegments(segmentParagraph(cell, links, { inTable: true }))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    }
    return (
      <p
        key={b.index}
        ref={(el) => { paraRefs.current[b.index] = el; }}
        style={{
          margin: "0 0 9px", padding: "2px 5px", borderRadius: 4,
          color: "#333",
          background: flash ? "#fff3cd" : "transparent",
          boxShadow: flash ? "0 0 0 2px #ffe08a" : "none",
          transition: "background 0.4s, box-shadow 0.4s",
        }}
      >
        {renderSegments(segmentParagraph(b.text, links))}
      </p>
    );
  }

  return (
    <div className="page" style={{ maxWidth: 1100 }}>
      <button className="back-btn" onClick={onBack}>← Back to Run Compare</button>
      <div className="page-title">Reference View</div>
      <div className="page-subtitle">
        The referenced section / table in the hyperlinked document, scrolled into view.
      </div>

      {/* Breadcrumb / context banner */}
      {current && (
        <div className="card" style={{ padding: "12px 16px", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          {stack.length > 1 && (
            <button className="btn-ghost" style={{ fontSize: 12, padding: "3px 9px" }} onClick={popStack}>
              ⤺ Previous reference
            </button>
          )}
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>From</span>
          <span style={{ fontSize: 13, fontWeight: 600, fontFamily: "monospace" }}>{current.sourceDoc}</span>
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>—</span>
          <span style={{
            fontSize: 12, fontWeight: 600, color: "#1b5e20",
            background: "#e8f5e9", border: "1px solid #81c784",
            borderRadius: 4, padding: "1px 7px",
          }}>
            “{current.linkText}”
          </span>
          <span style={{ fontSize: 16, color: "var(--primary)" }}>→</span>
          <span style={{ fontSize: 16 }}>{snippet?.is_table ? "📊" : "📄"}</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#1a73e8", fontFamily: "monospace", wordBreak: "break-all" }}>
            {targetDocName || "resolving…"}
          </span>
          {snippet?.heading && (
            <span style={{ fontSize: 13, color: "var(--text)", marginLeft: 4 }}>
              · {snippet.heading}
            </span>
          )}
        </div>
      )}

      {loading && (
        <div className="center-state">
          <div className="spinner" />
          <h3>Resolving referenced document…</h3>
        </div>
      )}

      {error && (
        <div className="error-msg"><strong>Could not open reference</strong>{error}</div>
      )}

      {!loading && !error && preview && located === false && (
        <div style={{
          marginTop: 12, padding: "8px 14px", borderRadius: 6,
          background: "#fff8e1", border: "1px solid #ffcc02", color: "#7a5a00", fontSize: 12.5,
        }}>
          Exact anchor not located in this document — showing it from the top.
        </div>
      )}

      {/* Target document panel */}
      {!loading && !error && preview && (
        <div className="card" style={{ marginTop: 12, padding: 0 }}>
          <div style={{
            padding: "10px 14px", borderBottom: "1px solid var(--border)",
            background: "#e8f5e9", borderRadius: "8px 8px 0 0",
            display: "flex", alignItems: "center", gap: 8,
          }}>
            <div style={{ fontWeight: 700, fontSize: 13 }}>
              Hyperlinked document
            </div>
            <div style={{ fontSize: 11, color: "#444", fontFamily: "monospace", wordBreak: "break-all" }}>
              {preview.orig_path}
            </div>
            <span style={{
              marginLeft: "auto", background: "#c8e6c9",
              borderRadius: 4, padding: "2px 7px", fontSize: 11, color: "#1b5e20", fontWeight: 600,
            }}>
              {preview.total_links} links
            </span>
          </div>

          <div style={{
            fontSize: 11, color: "#555", background: "#f9fbe7",
            borderBottom: "1px solid #e6ee9c", padding: "5px 14px",
          }}>
            Click any highlighted link to follow the reference chain.
          </div>

          <div
            ref={scrollBoxRef}
            style={{ padding: "14px 18px", maxHeight: "62vh", overflowY: "auto", fontSize: 13.5, lineHeight: 1.7 }}
          >
            {preview.paragraphs.map(renderBlock)}
          </div>
        </div>
      )}

      {!runId && (
        <div className="center-state">
          <div style={{ fontSize: 48, marginBottom: 12 }}>🔗</div>
          <h3>No reference selected</h3>
          <p>Open this page by clicking a hyperlink in Run Compare.</p>
        </div>
      )}
    </div>
  );
}
