/**
 * BeforeAfter — side-by-side document compare widget.
 *
 * Renders BEFORE (original paragraphs, plain) vs AFTER (same paragraphs with
 * injected links highlighted) plus an injected-links table.
 *
 * Clicking a highlighted link in the AFTER panel opens the target document
 * via the optional onLinkClick callback (provided by RunCompare).
 */

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { DocPreview, DocPreviewBlock, Link, LinkEdit } from "../types";
import { api } from "../api";
import { findRefBlockIndex, findRefEntryIndex } from "../refMatch";

// ── helpers ──────────────────────────────────────────────────────────────────

/** Split a paragraph into link / non-link segments (non-overlapping spans).
 *
 * Highlights the link text wherever it appears in the paragraph via a plain
 * `indexOf` search (robust against synthetic / misaligned location descriptors).
 * Each link is placed at most once per paragraph (first non-overlapping match)
 * to avoid duplicate highlights when the same phrase recurs.
 */
// A "bare number" link text: "5.3", "14.2.1.1", "2.3", "2.3%", "16-2-5" …
// — i.e. just a dotted/dashed number with no Section/Table/etc. prefix. These
// are the source of false-positive highlights (lab values in tables, and
// substrings of longer numbers), so they get extra-strict matching rules.
const BARE_NUMBER = /^\d+(?:[.\-]\d+)*%?$/;

/**
 * True when a phrase occurrence is the DEFINITION (caption / heading / bibliography
 * entry) rather than a citation — i.e. it starts the paragraph and is followed by a
 * title separator or a Title-Case continuation. Mirrors the backend's
 * `_caption_def_num` shape test so the preview never boxes a target the engine
 * deliberately did NOT hyperlink (e.g. "Table 8.1.1: Study Design Parameters",
 * "Helget LN et al. …"). A mid-sentence citation ("…see Table 8.1.1") is unaffected.
 */
function isDefinitionOccurrence(paraText: string, pos: number, needle: string): boolean {
  if (paraText.slice(0, pos).trim() !== "") return false; // not at the paragraph start
  const rest = paraText.slice(pos + needle.length).replace(/^\s+/, "");
  if (rest === "") return true; // bare heading ("Appendix 1")
  if (":.\-—\t".includes(rest[0])) return true; // "Table 1: …", "Figure 2 — …"
  return /[A-Z]/.test(rest[0]); // Title-Case continuation ("Helget LN …", "Table 1 Summary")
}

/** The paragraph index a link belongs to, parsed from its location descriptor
 * ("p11.r1:c0-32" / "p11.hl0" → 11), or null when unknown (older runs). Used to
 * scope a link's highlight to its OWN paragraph, so a short link_text like
 * "Protocol" from ¶6 never boxes the same word inside ¶11's compound link. */
export function linkParagraphIndex(link: Link): number | null {
  const m = /^p(\d+)\./.exec(link.link_location_descriptor || "");
  return m ? parseInt(m[1], 10) : null;
}

export function segmentParagraph(
  paraText: string,
  links: Link[],
  opts?: { inTable?: boolean },
): Array<{ text: string; isLink: boolean; link?: Link }> {
  type Span = { start: number; end: number; link: Link };
  const spans: Span[] = [];

  // Numeric cells inside tables (counts, percentages, lab values) must never be
  // linked. `inTable` is set when segmenting individual cells of a real table
  // grid; the legacy " | "-joined flattened-row path is still detected too.
  const isTableRow = (opts?.inTable ?? false) || paraText.includes(" | ");

  for (const link of links) {
    const needle = link.link_text;
    if (!needle) continue;

    const bareNumber = BARE_NUMBER.test(needle.trim());
    // Suppress bare-number links inside table rows entirely — that is where the
    // false positives cluster ("AST | 7 | 2.3 %"), and a raw number in a data
    // cell is never a real cross-reference.
    if (bareNumber && isTableRow) continue;

    let idx = 0;
    while (idx < paraText.length) {
      const pos = paraText.indexOf(needle, idx);
      if (pos === -1) break;

      // For bare numbers, require a numeric word boundary so "5.3" does not
      // match inside "5.3.1" / "5.3.5" / "15.3" (otherwise we box a fragment
      // of a longer number).
      if (bareNumber) {
        const before = pos > 0 ? paraText[pos - 1] : "";
        const after = paraText[pos + needle.length] ?? "";
        if (/[\d.\-]/.test(before) || /[\d.\-]/.test(after)) {
          idx = pos + 1;
          continue;
        }
      }

      // The caption/heading/bibliography-entry occurrence is the link TARGET, not
      // a source — the engine doesn't hyperlink it, so the preview must not box it
      // (users read a box as a clickable link). Skip past it and keep looking.
      if (isDefinitionOccurrence(paraText, pos, needle)) {
        idx = pos + needle.length;
        continue;
      }

      // NOTE: the engine now links the ACRONYM in "Statistical Analysis Plan (SAP)"
      // (not the spelled-out form), so the preview MUST box "(SAP)"/"(CSR)" — the
      // old skip-the-parenthetical-restatement guard was removed.
      const overlaps = spans.some((s) => pos < s.end && pos + needle.length > s.start);
      if (!overlaps) {
        spans.push({ start: pos, end: pos + needle.length, link });
        // Place this link once per paragraph (first occurrence) — enough to
        // make it visible and clickable without over-highlighting repeats.
        break;
      }
      idx = pos + 1;
    }
  }

  spans.sort((a, b) => a.start - b.start);

  const segments: Array<{ text: string; isLink: boolean; link?: Link }> = [];
  let cursor = 0;
  for (const span of spans) {
    if (cursor < span.start) segments.push({ text: paraText.slice(cursor, span.start), isLink: false });
    segments.push({ text: paraText.slice(span.start, span.end), isLink: true, link: span.link });
    cursor = span.end;
  }
  if (cursor < paraText.length) segments.push({ text: paraText.slice(cursor), isLink: false });
  return segments;
}

function linkColor(status: string) {
  if (status === "ok") return { bg: "#e8f5e9", color: "#1b5e20", border: "#81c784" };
  if (status === "unverified") return { bg: "#fff8e1", color: "#e65100", border: "#ffcc02" };
  return { bg: "#ffebee", color: "#b71c1c", border: "#ef9a9a" };
}

/**
 * The external website URL of a link, or "" when it isn't a web link.
 *
 * Single source of truth for "is this a link to the open web?" — imported by
 * RunCompare and ReferenceView so every routing branch agrees. An external link
 * must ALWAYS open in a new tab and must NEVER route to Reference View or
 * trigger scroll-to-reference.
 *
 * Resolution order:
 *   1. Authoritative `link_kind` from the backend ("external_url" ⇒ a real
 *      website; the backend already re-classifies cross-doc refs away from
 *      external_url, so trusting it here is safe).
 *   2. Fallback for older runs that predate `link_kind`: a raw http(s) target.
 *      A cross-doc target like "csr-…_linked.docx" fails the URL test, so it is
 *      correctly NOT treated as external.
 */
export function externalUrl(link: Link): string {
  const anchor = (link.target_anchor || "").trim();
  const doc = (link.target_doc || "").trim();
  const isUrl = (s: string) => /^https?:\/\//i.test(s);
  if (link.link_kind === "external_url") {
    if (isUrl(anchor)) return anchor;
    if (isUrl(doc)) return doc;
    // link_kind says external but neither field is a URL → nothing to open.
    return "";
  }
  if (link.link_kind && link.link_kind !== "external_url") return ""; // authoritative non-web
  // No link_kind (legacy run) → infer from a raw http(s) target.
  if (isUrl(anchor)) return anchor;
  if (isUrl(doc)) return doc;
  return "";
}

/** True when the link points to the open web (and must open in a new tab). */
export const isExternalLink = (link: Link): boolean => externalUrl(link) !== "";

/** Last path segment of a filename or path ("a/b/c.docx" → "c.docx"). */
const baseName = (s: string) => s.split(/[\\/]/).pop() ?? s;

// Real-table rendering styles (replaces the old " | "-joined flattened rows).
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

// ── component ────────────────────────────────────────────────────────────────

interface Props {
  preview: DocPreview;
  /** Path label shown under the AFTER header. */
  afterPath?: string;
  /** Title shown in the AFTER panel header, e.g. the lifecycle stage label. */
  afterTitle?: string;
  /**
   * Called when user clicks a highlighted link in the AFTER panel.
   * The optional second argument is the snippet heading text — RunCompare
   * uses it to auto-scroll the newly loaded document to the target paragraph.
   */
  onLinkClick?: (link: Link, scrollTarget?: string) => void;
  /**
   * Run id for this preview. When provided, clicking a cross-document link
   * shows a Google-style destination snippet (target heading + excerpt)
   * instead of immediately navigating. Falls back to onLinkClick when absent.
   * Also enables the inline link-edit buttons in the links table.
   */
  runId?: string;
  /**
   * When set, the AFTER panel scrolls to (and highlights) the first paragraph
   * whose text contains this string, immediately after the preview mounts.
   * Typically the `heading` value from the last LinkSnippet response — passed
   * by RunCompare after "Open document →" navigation so the user lands on the
   * exact section/table rather than the document top.
   */
  scrollTarget?: string;
  /**
   * The run's available document filenames (RunCompare's docOptions). Lets the
   * right-hand Viewer List mark which linked targets can be opened in this run
   * versus ones that weren't part of the upload.
   */
  runDocs?: string[];
  /**
   * Called when the user clicks a document in the right-hand Viewer List.
   * RunCompare uses it to switch the compare view to that target document.
   */
  onSelectRelatedDoc?: (docBasename: string) => void;
}

export function BeforeAfter({ preview, afterPath, afterTitle, onLinkClick, runId, scrollTarget, runDocs, onSelectRelatedDoc }: Props) {
  const [tooltip, setTooltip] = useState<{ text: string; x: number; y: number } | null>(null);

  // Local mutable copy of links so inline edits reflect immediately in the UI
  // without requiring a full preview reload from the parent.
  const [localLinks, setLocalLinks] = useState<Link[]>(preview.links);
  useEffect(() => { setLocalLinks(preview.links); }, [preview]);

  // Bucket links by their own paragraph so highlighting is scoped per-paragraph:
  // a link is boxed ONLY in the paragraph it was injected into. Without this, a
  // short link_text ("Protocol", "TMX-67_301") from one paragraph also matches —
  // and boxes — the same words inside another paragraph's compound link, making a
  // single continuous link look split. Links with no descriptor (older runs) fall
  // back to every paragraph, preserving prior behaviour.
  const { byPara: linksByPara, anyPara: linksAnyPara } = useMemo(() => {
    const byPara = new Map<number, Link[]>();
    const anyPara: Link[] = [];
    for (const l of localLinks) {
      const pi = linkParagraphIndex(l);
      if (pi === null) anyPara.push(l);
      else byPara.set(pi, [...(byPara.get(pi) ?? []), l]);
    }
    return { byPara, anyPara };
  }, [localLinks]);
  const linksForBlock = (b: { index: number; para_index?: number }): Link[] => {
    const pi = b.para_index;
    // Tables / blocks without a paragraph coordinate keep the prior behaviour.
    if (typeof pi !== "number") return localLinks;
    return [...(linksByPara.get(pi) ?? []), ...linksAnyPara];
  };

  // Inline edit state — tracks which row is being edited and its draft values.
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<LinkEdit>({});
  const [editSaving, setEditSaving] = useState(false);

  const afterLabel = useMemo(
    () => afterPath ?? preview.orig_path.replace(/\.(docx|pdf)$/i, (_m, e) => `_linked.${e.toLowerCase()}`),
    [afterPath, preview.orig_path],
  );

  // Basename of the AFTER panel's linked file (e.g. "csr-sp-2026-001-body_linked.docx").
  // Used by isInternal to detect same-document links that were tagged with the
  // _linked.docx suffix by the pipeline's resolve_targets stage.
  const afterDocName = useMemo(() => afterLabel.split(/[\\/]/).pop() ?? afterLabel, [afterLabel]);

  // Break links down by what they actually point to (mirrors isInternal logic).
  const counts = useMemo(() => {
    let external = 0, crossDoc = 0, internal = 0;
    for (const l of localLinks) {
      if (isExternalLink(l)) { external += 1; continue; }
      const td = (l.target_doc || "").split(/[\\/]/).pop() ?? "";
      if (td && td !== afterDocName && /_linked\.(docx|pdf)$/i.test(td)) crossDoc += 1;
      else internal += 1;
    }
    return { external, crossDoc, internal };
  }, [localLinks, afterDocName]);

  // Distinct cross-document targets THIS document links to, for the Viewer List
  // (third pane). Grouped by target document with a link count + the link texts.
  const relatedDocs = useMemo(() => {
    type Ref = { text: string; page?: number | null };
    const map = new Map<string, { doc: string; count: number; pdf: boolean; refs: Ref[] }>();
    for (const l of localLinks) {
      if (isExternalLink(l)) continue;                                    // external web — not a document
      const td = baseName(l.target_doc || "");
      if (!td || td === afterDocName || !/_linked\.(docx|pdf)$/i.test(td)) continue; // self / internal
      const e = map.get(td) ?? { doc: td, count: 0, pdf: /\.pdf$/i.test(td), refs: [] };
      e.count += 1;
      // One chip per distinct reference text, carrying the page the target PDF
      // opens to (PLAN TWELVE). First page seen for a text wins.
      if (l.link_text && !e.refs.some((r) => r.text === l.link_text)) {
        e.refs.push({ text: l.link_text, page: l.target_page ?? null });
      }
      map.set(td, e);
    }
    return [...map.values()].sort((a, b) => b.count - a.count);
  }, [localLinks, afterDocName]);

  // Basenames of documents available in this run → tells the Viewer List which
  // related targets can actually be opened (vs ones not part of the upload).
  const runDocBasenames = useMemo(
    () => new Set((runDocs ?? []).map(baseName)),
    [runDocs],
  );

  // Per-paragraph refs in the AFTER panel so an internal reference click can
  // scroll the panel to the target section/table and briefly highlight it.
  const afterRefs = useRef<Record<number, HTMLElement | null>>({});
  const [highlightPara, setHighlightPara] = useState<number | null>(null);

  /** A link is "internal" when it points within this same document.
   *
   *  Three cases are treated as internal:
   *    1. No target_doc at all  (pure bookmark anchor)
   *    2. target_doc is the SAME _linked.docx we are already viewing
   *    3. target_doc is a bare original filename (no _linked suffix)
   *
   *  A link is cross-document only when target_doc names a *different*
   *  _linked.docx file (resolve_targets always writes the _linked form).
   */
  function isInternal(link: Link): boolean {
    if (isExternalLink(link)) return false;
    const td = (link.target_doc || "").split(/[\\/]/).pop() ?? "";
    if (!td) return true;                       // no target doc → bookmark
    if (td === afterDocName) return true;       // same _linked.docx we're viewing
    if (/_linked\.(docx|pdf)$/i.test(td)) return false; // a *different* linked doc
    return true;                                // bare original filename → internal
  }

  /** Scroll the AFTER panel to the referenced table / section / figure.
   *
   *  Search priority (highest → lowest):
   *    1. Caption paragraph: "Table 14.2.1.1 …", "Section 2.5.3 …", "Figure 11 …"
   *    2. Table ROW that contains the number (now visible via _read_docx_blocks)
   *    3. Any heading that starts with the dotted number
   *    4. Any paragraph that merely contains the number
   *
   *  Returns true when a target was located and scrolled to.
   */
  function scrollToInternal(link: Link): boolean {
    // A literature citation ("Helget LN, 2024") carries a ref_* bookmark anchor —
    // jump to its References ENTRY, not to the first textual "Helget" (which is the
    // citation itself). Falls through to the type-aware text matcher for everything
    // else (Table/Section/Figure/Appendix).
    const anchor = link.target_anchor || "";
    let idx = /^ref_/i.test(anchor) ? findRefEntryIndex(preview.paragraphs, anchor) : -1;
    // Type-aware, boundary-safe matching (shared with the Word DocViewer): a
    // Section/Appendix link never resolves to a table block, and "2.5" won't
    // match inside "14.2.5.1". This is what stopped non-table links from
    // wrongly redirecting to a table.
    if (idx < 0) idx = findRefBlockIndex(preview.paragraphs, link.link_text);
    if (idx < 0) return false;

    const el = afterRefs.current[idx];
    if (!el) return false;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlightPara(idx);
    window.setTimeout(() => setHighlightPara(null), 2200);
    return true;
  }

  // ── Auto-scroll when a cross-doc navigation lands on a new preview ─────────
  // scrollTarget is the `heading` text from the last snippet response.  After
  // the new document's paragraphs are rendered we find the matching paragraph
  // (first 60 chars are enough to locate it) and scroll to it with a flash.
  useEffect(() => {
    if (!scrollTarget || !preview) return;
    const needle = scrollTarget.slice(0, 60).toLowerCase();
    const target = preview.paragraphs.find(
      (p) => p.text.toLowerCase().includes(needle) || needle.includes(p.text.slice(0, 40).toLowerCase()),
    );
    if (!target) return;
    // Small delay so the DOM has painted after the preview state update.
    const tid = window.setTimeout(() => {
      const el = afterRefs.current[target.index];
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      setHighlightPara(target.index);
      window.setTimeout(() => setHighlightPara(null), 2200);
    }, 150);
    return () => window.clearTimeout(tid);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview, scrollTarget]);

  /** Route a clicked link.
   *
   *  External URLs always open in a tab. Otherwise behaviour depends on whether
   *  the "Preview popover before opening" toggle is on:
   *
   *  • Popover ENABLED (default) — the convenient in-place mode:
   *      – internal section/table that exists in *this* doc → scroll + highlight
   *        here, no redirect.
   *      – everything else → destination snippet popover (searches the run).
   *
   *  • Popover DISABLED — every reference (internal section, table, AND
   *    cross-doc) hands off to the parent, which opens the dedicated Reference
   *    View page and scrolls to the relationship target. We deliberately skip
   *    the in-place `scrollToInternal` here so section/table links redirect to
   *    Reference View just like cross-doc links do.
   */
  function handleLink(link: Link) {
    // External website → ALWAYS open in a new tab, before any other routing, so
    // an external link can never be sent into Reference View.
    const url = externalUrl(link);
    if (url) { window.open(url, "_blank", "noopener,noreferrer"); return; }

    // Every other reference — same-document citations / tables / sections AND
    // cross-document links — opens the dedicated Reference View page, which
    // resolves the destination document and scrolls to the referenced spot.
    if (onLinkClick) { onLinkClick(link); return; }

    // Fallback only for screens with no Reference View wired (e.g. the demo
    // Comparison screen): scroll within this document if the ref is internal.
    if (isInternal(link)) scrollToInternal(link);
  }

  // ── block renderers (shared by BEFORE / AFTER panels) ──────────────────────

  /** Turn link/plain segments into spans — used for the AFTER panel and table
   *  cells. Link spans are clickable + show a hover tooltip. */
  function renderSegments(segments: ReturnType<typeof segmentParagraph>) {
    const clickable = !!onLinkClick || !!runId;
    return segments.map((seg, si) => {
      if (!seg.isLink || !seg.link) return <span key={si}>{seg.text}</span>;
      const c = linkColor(seg.link.status);
      return (
        <span
          key={si}
          style={{
            background: c.bg,
            color: c.color,
            border: `1px solid ${c.border}`,
            borderRadius: 3,
            padding: "0 3px",
            cursor: clickable ? "pointer" : "default",
            fontWeight: 500,
            textDecoration: "underline",
            textDecorationStyle: "dotted",
          }}
          onClick={() => clickable && handleLink(seg.link!)}
          onMouseEnter={(e) => {
            const rect = (e.target as HTMLElement).getBoundingClientRect();
            const target = seg.link!.target_anchor || seg.link!.target_doc || "—";
            setTooltip({
              text: `${seg.link!.status.toUpperCase()}: ${target}${clickable ? " (click to preview)" : ""}`,
              x: rect.left,
              y: rect.bottom + 4,
            });
          }}
          onMouseLeave={() => setTooltip(null)}
        >
          {seg.text}
        </span>
      );
    });
  }

  /** BEFORE panel — plain content (no links, no scroll refs). */
  function renderBeforeBlock(b: DocPreviewBlock) {
    if (b.type === "table" && b.rows && b.rows.length > 0) {
      return (
        <table key={b.index} className="docx-table" style={DOCX_TABLE_STYLE}>
          <tbody>
            {b.rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td key={ci} style={DOCX_CELL_STYLE}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    }
    if (b.type === "image" && b.src) {
      return (
        <img key={b.index} src={b.src} alt="figure"
          style={{ display: "block", maxWidth: "100%", height: "auto", margin: "6px 0",
                   border: "1px solid #eee", borderRadius: 4 }} />
      );
    }
    return <p key={b.index} style={{ margin: "0 0 8px", color: "#444" }}>{b.text}</p>;
  }

  /** AFTER panel — links highlighted; per-block scroll ref + flash highlight. */
  function renderAfterBlock(b: DocPreviewBlock) {
    const flash = highlightPara === b.index;
    if (b.type === "image" && b.src) {
      return (
        <img key={b.index}
          ref={(el) => { afterRefs.current[b.index] = el; }}
          src={b.src} alt="figure"
          style={{ display: "block", maxWidth: "100%", height: "auto", margin: "6px 0",
                   border: "1px solid #eee", borderRadius: 4,
                   outline: flash ? "3px solid #ffc107" : "none", transition: "outline 0.4s" }} />
      );
    }
    if (b.type === "table" && b.rows && b.rows.length > 0) {
      return (
        <table
          key={b.index}
          ref={(el) => { afterRefs.current[b.index] = el; }}
          className="docx-table"
          style={{ ...DOCX_TABLE_STYLE, background: flash ? "#fff3cd" : "#fff", transition: "background 0.4s" }}
        >
          <tbody>
            {b.rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td key={ci} style={DOCX_CELL_STYLE}>
                    {renderSegments(segmentParagraph(cell, linksForBlock(b), { inTable: true }))}
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
        ref={(el) => { afterRefs.current[b.index] = el; }}
        style={{
          margin: "0 0 8px", padding: "1px 4px", borderRadius: 4,
          color: "#444",
          background: flash ? "#fff3cd" : "transparent",
          transition: "background 0.4s",
        }}
      >
        {renderSegments(segmentParagraph(b.text, linksForBlock(b)))}
      </p>
    );
  }

  return (
    <>
      {/* Stats row — broken down by link type so the demo is self-explanatory */}
      <div className="stats-row" style={{ marginBottom: 12 }}>
        <div className="stat-box"><div className="stat-num neutral">{preview.total_links}</div><div className="stat-label">Links Added</div></div>
        <div className="stat-box"><div className="stat-num neutral">{counts.internal}</div><div className="stat-label">Internal</div></div>
        <div className="stat-box"><div className="stat-num ok">{counts.crossDoc}</div><div className="stat-label">Cross-Doc</div></div>
        <div className="stat-box"><div className="stat-num warn">{counts.external}</div><div className="stat-label">External Web</div></div>
        <div className="stat-box"><div className="stat-num block">{preview.broken_links}</div><div className="stat-label">Broken</div></div>
      </div>

      {/* Side-by-side panels — BEFORE | AFTER | Viewer List */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr) 300px", gap: 12 }}>

        {/* BEFORE panel — plain text, no links */}
        <div className="card" style={{ padding: 0 }}>
          <div style={{
            padding: "10px 14px",
            borderBottom: "1px solid var(--border)",
            background: "#f5f5f5",
            borderRadius: "8px 8px 0 0",
            display: "flex", alignItems: "center", gap: 8,
          }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 13 }}>BEFORE</div>
              <div style={{ fontSize: 11, color: "#666", wordBreak: "break-all" }}>{preview.orig_path}</div>
            </div>
            <span style={{
              marginLeft: "auto", background: "#eee",
              borderRadius: 4, padding: "2px 7px", fontSize: 11, color: "#555",
            }}>
              No hyperlinks
            </span>
          </div>
          <div style={{ padding: "12px 14px", maxHeight: 520, overflowY: "auto", fontSize: 13, lineHeight: 1.65 }}>
            {preview.paragraphs.map(renderBeforeBlock)}
          </div>
        </div>

        {/* AFTER panel — highlighted links; click opens target doc */}
        <div className="card" style={{ padding: 0 }}>
          <div style={{
            padding: "10px 14px",
            borderBottom: "1px solid var(--border)",
            background: "#e8f5e9",
            borderRadius: "8px 8px 0 0",
            display: "flex", alignItems: "center", gap: 8,
          }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 13 }}>AFTER ({afterTitle ?? "Hyperlinked"})</div>
              <div style={{ fontSize: 11, color: "#444", wordBreak: "break-all" }}>{afterLabel}</div>
            </div>
            <span style={{
              marginLeft: "auto", background: "#c8e6c9",
              borderRadius: 4, padding: "2px 7px", fontSize: 11, color: "#1b5e20", fontWeight: 600,
            }}>
              {preview.total_links} links added
            </span>
          </div>

          {onLinkClick && (
            <div style={{
              padding: "5px 14px",
              fontSize: 11, color: "#555",
              background: "#f9fbe7",
              borderBottom: "1px solid #e6ee9c",
            }}>
              Click a highlighted link to open the target document
            </div>
          )}

          <div style={{ padding: "12px 14px", maxHeight: 520, overflowY: "auto", fontSize: 13, lineHeight: 1.65, position: "relative" }}>
            {preview.paragraphs.map(renderAfterBlock)}
          </div>
        </div>

        {/* VIEWER LIST panel — documents this one hyperlinks to */}
        <div className="card" style={{ padding: 0 }}>
          <div style={{
            padding: "10px 14px",
            borderBottom: "1px solid var(--border)",
            background: "#eef2ff",
            borderRadius: "8px 8px 0 0",
          }}>
            <div style={{ fontWeight: 700, fontSize: 13 }}>📎 LINKED DOCUMENTS</div>
            <div style={{ fontSize: 11, color: "#555" }}>Referenced from this document</div>
          </div>
          <div style={{ padding: "10px 12px", maxHeight: 520, overflowY: "auto" }}>
            {relatedDocs.length === 0 ? (
              <div style={{ fontSize: 12, color: "#888", lineHeight: 1.5 }}>
                No cross-document links — this document only has internal or external links.
              </div>
            ) : (
              relatedDocs.map((rd) => {
                const available = runDocBasenames.size === 0 || runDocBasenames.has(rd.doc);
                const niceName = rd.doc.replace(/_linked\.(docx|pdf)$/i, "");
                // PLAN TWELVE: clicking a related doc opens it in a NEW TAB,
                // scrolled to the reference. A PDF opens the ORIGINAL pdf at
                // #page=N; a Word/other doc opens the app's DocViewer at the
                // reference (browsers can't render .docx inline). Falls back to the
                // in-app switch only when there's no runId (demo Comparison screen).
                const opensInTab = available && !!runId;
                const clickable = available && (opensInTab || !!onSelectRelatedDoc);
                const openDoc = (ref?: { text?: string; page?: number | null }) => {
                  if (!available) return;
                  if (rd.pdf && runId) {
                    api.pipeline.openPdfAtPage(runId, rd.doc, ref?.page ?? rd.refs[0]?.page ?? null);
                  } else if (runId) {
                    api.pipeline.openDocViewer(runId, rd.doc, ref?.text ?? rd.refs[0]?.text);
                  } else {
                    onSelectRelatedDoc?.(rd.doc);
                  }
                };
                return (
                  <div
                    key={rd.doc}
                    onClick={() => openDoc()}
                    title={
                      !available ? `${rd.doc} is not part of this run`
                      : opensInTab ? `Open ${niceName} in a new tab`
                      : `Open ${rd.doc}`
                    }
                    style={{
                      border: "1px solid var(--border)",
                      borderRadius: 7,
                      padding: "8px 10px",
                      marginBottom: 8,
                      background: available ? "#fff" : "rgba(0,0,0,0.03)",
                      cursor: clickable ? "pointer" : "default",
                      opacity: available ? 1 : 0.65,
                      transition: "background 0.15s, border-color 0.15s",
                    }}
                    onMouseEnter={(e) => { if (clickable) e.currentTarget.style.borderColor = "var(--primary)"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border)"; }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ fontSize: 14 }}>📄</span>
                      <span style={{
                        fontWeight: 600, fontSize: 12, color: "var(--primary)",
                        flex: 1, wordBreak: "break-all",
                      }}>
                        {niceName}
                      </span>
                      {opensInTab && (
                        <span
                          title={rd.pdf
                            ? "Opens the original PDF in a new tab, scrolled to the reference"
                            : "Opens the document in a new tab, scrolled to the reference"}
                          style={{ fontSize: 10, color: "#3949ab", whiteSpace: "nowrap" }}
                        >
                          ↗ new tab
                        </span>
                      )}
                      <span style={{
                        background: "#c8e6c9", color: "#1b5e20",
                        borderRadius: 4, padding: "1px 6px", fontSize: 10, fontWeight: 700,
                        whiteSpace: "nowrap",
                      }}>
                        {rd.count} link{rd.count === 1 ? "" : "s"}
                      </span>
                    </div>
                    {opensInTab ? (
                      // Dropdown of EVERY reference into this doc (no 6-cap). Picking
                      // one opens that doc in a new tab scrolled to the reference:
                      // PDF → #page=N (label shows "→ p.N" or "opens at top" when the
                      // ref is whole-document); Word → DocViewer scrolled to the text.
                      <div
                        style={{ marginTop: 6 }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <select
                          defaultValue=""
                          title="Pick a reference to open this document scrolled to it"
                          onChange={(e) => {
                            const idx = Number(e.currentTarget.value);
                            if (!Number.isNaN(idx) && rd.refs[idx]) openDoc(rd.refs[idx]);
                            e.currentTarget.selectedIndex = 0; // reset to the placeholder
                          }}
                          style={{
                            width: "100%", fontSize: 11, padding: "4px 6px",
                            borderRadius: 5, border: "1px solid var(--border)",
                            background: "#fff", color: "#3c4043", cursor: "pointer",
                          }}
                        >
                          <option value="" disabled>
                            ↳ Jump to a reference… ({rd.refs.length})
                          </option>
                          {rd.refs.map((r, ti) => (
                            <option key={ti} value={ti}>
                              {rd.pdf
                                ? `${r.text}${r.page ? `  → p.${r.page}` : "  — opens at top"}`
                                : r.text}
                            </option>
                          ))}
                        </select>
                      </div>
                    ) : (
                      // Demo / no-runId path: keep the original read-only chip list.
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                        {rd.refs.slice(0, 6).map((r, ti) => (
                          <span
                            key={ti}
                            style={{
                              background: "#f1f3f4", color: "#3c4043",
                              borderRadius: 3, padding: "1px 5px", fontSize: 10,
                              maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                            }}
                          >
                            {r.text}
                          </span>
                        ))}
                        {rd.refs.length > 6 && (
                          <span style={{ fontSize: 10, color: "#888" }}>+{rd.refs.length - 6} more</span>
                        )}
                      </div>
                    )}
                    {!available && (
                      <div style={{ fontSize: 10, color: "#b71c1c", marginTop: 5, fontStyle: "italic" }}>
                        not in this run
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Injected links table */}
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card-title">
          Injected Links ({localLinks.length})
          {runId && (
            <span style={{ fontSize: 11, fontWeight: 400, marginLeft: 10, color: "var(--text-muted)" }}>
              ✏️ click a row's edit button to correct a wrong target
            </span>
          )}
        </div>
        <div style={{ overflowX: "auto", maxHeight: 320, overflowY: "auto" }}>
          <table className="link-table">
            <thead>
              <tr>
                <th>Link Text</th>
                <th>Target Doc</th>
                <th>Anchor / Section</th>
                <th>Location</th>
                <th>Status</th>
                <th>Conf.</th>
                {runId && <th style={{ width: 64 }}></th>}
              </tr>
            </thead>
            <tbody>
              {localLinks.map((l, i) => {
                const clickable = !!onLinkClick || !!runId;
                const isEditing = editingIdx === i;

                if (isEditing) {
                  return (
                    <tr key={i} style={{ background: "var(--primary-bg, #f0f4ff)" }}>
                      <td style={{ fontWeight: 500, color: "var(--primary)", fontSize: 12 }}>
                        {l.link_text}
                      </td>
                      <td>
                        <input
                          value={editDraft.target_doc ?? l.target_doc ?? ""}
                          onChange={(e) => setEditDraft((d) => ({ ...d, target_doc: e.target.value }))}
                          placeholder="target_doc"
                          style={{
                            width: "100%", fontSize: 11, padding: "3px 6px",
                            border: "1px solid var(--primary)", borderRadius: 4,
                            fontFamily: "monospace",
                          }}
                        />
                      </td>
                      <td>
                        <input
                          value={editDraft.target_anchor ?? l.target_anchor ?? ""}
                          onChange={(e) => setEditDraft((d) => ({ ...d, target_anchor: e.target.value }))}
                          placeholder="anchor / section"
                          style={{
                            width: "100%", fontSize: 11, padding: "3px 6px",
                            border: "1px solid var(--primary)", borderRadius: 4,
                          }}
                        />
                      </td>
                      <td style={{ fontSize: 11, color: "var(--text-muted)" }}>
                        {l.link_location_descriptor || "—"}
                      </td>
                      <td>
                        <select
                          value={editDraft.status ?? l.status}
                          onChange={(e) => setEditDraft((d) => ({ ...d, status: e.target.value as Link["status"] }))}
                          style={{
                            fontSize: 11, padding: "3px 4px",
                            border: "1px solid var(--border)", borderRadius: 4,
                          }}
                        >
                          <option value="ok">OK</option>
                          <option value="broken">BROKEN</option>
                          <option value="unverified">UNVERIFIED</option>
                          <option value="suspicious">SUSPICIOUS</option>
                        </select>
                      </td>
                      <td style={{ fontSize: 12 }}>{Math.round(l.confidence * 100)}%</td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        <button
                          className="btn-primary btn-sm"
                          disabled={editSaving}
                          style={{ fontSize: 10, padding: "3px 7px", marginRight: 4 }}
                          onClick={async () => {
                            if (!runId) return;
                            setEditSaving(true);
                            try {
                              const updated = await api.pipeline.updateLink(
                                runId, l.source_doc, l.link_text, editDraft,
                              );
                              setLocalLinks((prev) => {
                                const next = [...prev];
                                next[i] = updated;
                                return next;
                              });
                              setEditingIdx(null);
                            } catch (err) {
                              alert(`Save failed: ${err instanceof Error ? err.message : String(err)}`);
                            } finally {
                              setEditSaving(false);
                            }
                          }}
                        >
                          {editSaving ? "…" : "Save"}
                        </button>
                        <button
                          className="btn-ghost"
                          style={{ fontSize: 10, padding: "3px 7px" }}
                          onClick={() => { setEditingIdx(null); setEditDraft({}); }}
                        >
                          Cancel
                        </button>
                      </td>
                    </tr>
                  );
                }

                return (
                  <tr
                    key={i}
                    style={{ cursor: clickable ? "pointer" : "default" }}
                    onClick={(e) => {
                      // Don't navigate when the edit button was clicked
                      if ((e.target as HTMLElement).closest("button")) return;
                      if (clickable) handleLink(l);
                    }}
                    title={clickable ? "Click to open this link" : undefined}
                  >
                    <td style={{ fontWeight: 500, color: "var(--primary)" }}>{l.link_text}</td>
                    <td
                      style={{
                        fontSize: 11, color: "var(--text-muted)",
                        maxWidth: 160, overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap",
                      }}
                      title={l.target_doc}
                    >
                      {l.target_doc || "—"}
                    </td>
                    <td
                      style={{
                        fontSize: 11, color: "var(--text-muted)",
                        maxWidth: 180, overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap",
                      }}
                      title={l.target_anchor}
                    >
                      {l.target_anchor || "—"}
                    </td>
                    <td style={{ fontSize: 11, color: "var(--text-muted)" }}>
                      {l.link_location_descriptor || "—"}
                    </td>
                    <td>
                      <span className={`link-status ${l.status}`}>
                        {l.status.toUpperCase()}
                      </span>
                    </td>
                    <td style={{ fontSize: 12 }}>{Math.round(l.confidence * 100)}%</td>
                    {runId && (
                      <td>
                        <button
                          className="btn-ghost"
                          style={{ fontSize: 11, padding: "2px 8px" }}
                          title="Edit this link's target"
                          onClick={(e) => {
                            e.stopPropagation();
                            setEditingIdx(i);
                            setEditDraft({
                              target_doc: l.target_doc,
                              target_anchor: l.target_anchor,
                              status: l.status,
                            });
                          }}
                        >
                          ✏️
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Floating tooltip */}
      {tooltip && (
        <div style={{
          position: "fixed", left: tooltip.x, top: tooltip.y,
          background: "#333", color: "#fff",
          padding: "5px 10px", borderRadius: 5, fontSize: 12,
          maxWidth: 380, wordBreak: "break-all",
          zIndex: 1000, boxShadow: "0 2px 8px rgba(0,0,0,0.3)",
          pointerEvents: "none",
        }}>
          {tooltip.text}
        </div>
      )}
    </>
  );
}
