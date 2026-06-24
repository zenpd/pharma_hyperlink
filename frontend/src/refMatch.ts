/**
 * Shared reference→block matcher for scroll-to-reference.
 *
 * The old logic reduced every link to a bare number and then tried a TABLE
 * caption and a TABLE ROW *before* the section heading. So a "Section 2.5"
 * link matched a "Table 14.2.5.1" caption (the substring "2.5") or any table
 * cell containing "2.5" — and landed on the wrong table. This matcher is:
 *
 *   • type-aware  — a Section/Appendix link never resolves to a table block;
 *     only Table/Figure/Listing links may land on a table caption/row.
 *   • boundary-safe — "2.5" matches "2.5"/"2.5 Title" but NOT inside "14.2.5.1".
 *
 * Returns the matching block's `index`, or -1.
 */

export interface RefBlock {
  index: number;
  text: string;
  type?: "paragraph" | "table" | string;
  rows?: string[][];
}

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\-]/g, "\\$&");

function isTableBlock(b: RefBlock): boolean {
  return b.type === "table" || (b.text || "").includes("|");
}

/**
 * A Table-of-Contents line/block — recognised by its dotted leader ("……25").
 * The TOC lists EVERY section/table number, so it falsely matches any "Section N"
 * reference and steals the scroll from the real heading. We never land on it.
 */
function isTocBlock(b: RefBlock): boolean {
  return /\.{4,}/.test(b.text || "");
}

/** Strip apostrophes/hyphens so a slug surname "obrien" matches body "O'Brien". */
const stripName = (s: string) => s.toLowerCase().replace(/['’\-]/g, "");

/**
 * The block that OPENS the References / Bibliography section. Accepts a bare
 * "References" / "Bibliography" heading AND the common clinical forms carrying a
 * leading section number — "6 References", "11. REFERENCES". Returns index or -1.
 */
function findRefsHeadingIndex(blocks: RefBlock[]): number {
  const hit = blocks.find((b) =>
    /^(?:\d+\.?\s+)?(?:references?|bibliography)\s*$/i.test((b.text || "").trim()),
  );
  return hit ? hit.index : -1;
}

/**
 * From the candidate blocks that all match a citation, pick the bibliography
 * ENTRY rather than an in-text mention. A citation by NAME ("Tankere et al.
 * (2022) …") starts with the surname too, so the first match is usually the
 * in-text mention, not the entry. Prefer a candidate AFTER the References
 * heading; else the last (entries sit at the end of the document). A single
 * candidate is returned as-is (no ambiguity).
 */
function pickEntryBlock(matches: RefBlock[], blocks: RefBlock[]): number {
  if (matches.length === 0) return -1;
  if (matches.length === 1) return matches[0].index;
  const refsIdx = findRefsHeadingIndex(blocks);
  if (refsIdx >= 0) {
    const inRefs = matches.find((m) => m.index > refsIdx);
    if (inRefs) return inRefs.index;
  }
  return matches[matches.length - 1].index;
}

/**
 * Locate a bibliography ENTRY block from a citation's `ref_*` anchor — so clicking
 * an in-text citation scrolls to its References entry, NOT to the first textual
 * occurrence of the citation (which is the citation itself, i.e. "the same line").
 *
 *   ref_helget_2024  → the entry line starting "Helget …" that contains "2024"
 *   ref_xu_2022      → short/compound surnames work (slug carries the surname)
 *   ref_7            → the numbered entry "7. …"
 *
 * Returns the block index, or -1 when the anchor isn't a reference key / no match.
 */
export function findRefEntryIndex(blocks: RefBlock[], anchor?: string): number {
  const a = (anchor || "").trim().toLowerCase();
  const ay = a.match(/^ref_([a-z][a-z'-]*)_((?:19|20)\d{2})$/);
  if (ay) {
    const surname = stripName(ay[1]);
    const year = ay[2];
    // Collect EVERY block starting with the surname + year (in-text mentions AND
    // the entry), then pick the entry. Word-boundary guard stops a short surname
    // "li" from matching a body word like "Likewise".
    const matches = blocks.filter((b) => {
      const t = stripName((b.text || "").trim());
      if (!t.startsWith(surname) || !t.includes(year)) return false;
      const after = t.charAt(surname.length);
      return after === "" || !/[a-z]/.test(after);
    });
    return pickEntryBlock(matches, blocks);
  }
  const num = a.match(/^ref_(\d{1,3})$/);
  if (num) {
    const re = new RegExp(`^\\(?${num[1]}[.)]\\s`);
    const matches = blocks.filter((b) => re.test((b.text || "").trim()));
    return pickEntryBlock(matches, blocks);
  }
  return -1;
}

export function findRefBlockIndex(blocks: RefBlock[], refText?: string): number {
  const text = (refText || "").trim();
  if (!text) return -1;
  const lower = text.toLowerCase();

  // Identify the reference type + number. Three accepted forms, most-specific first:
  //   • injected anchor slug   — "section_ref_6_1" / "table_ref_6_1_1"
  //   • a typed ref EMBEDDED anywhere — "Protocol TMX-67_301 Section 6.1" must key on
  //     "Section 6.1", NOT the doc-id digits "67"; this is the cross-doc compound case.
  //   • a leading keyword + number — "Table 14.2.1.1", "Section 2.5".
  const slug = text.match(/\b(table|figure|listing|appendix|section)_ref_([0-9]+(?:_[0-9]+)*|[a-z])\b/i);
  const typed = text.match(/\b(table|figure|listing|appendix|section)s?\.?\s+([0-9]+(?:[.\-][0-9]+)*|[A-Za-z])\b/i);
  let kw = "";
  let num = "";
  if (slug) {
    kw = slug[1].toLowerCase();
    num = slug[2].replace(/_/g, ".");
  } else if (typed) {
    kw = typed[1].toLowerCase();
    num = typed[2];
  } else {
    kw = (text.match(/^(table|figure|listing|appendix|section)\b/i)?.[1] ?? "").toLowerCase();
    num = text.match(/\d+(?:[.\-]\d+)+|\d+/)?.[0] ?? "";
  }
  const tableish = kw === "table" || kw === "figure" || kw === "listing";
  // Boundary-safe "this exact number" — 2.5 must not match inside 14.2.5.1.
  const numBound = num ? new RegExp(`(?<![\\d.])${esc(num)}(?![\\d.])`) : null;
  const norm = (b: RefBlock) => (b.text || "").trim().toLowerCase();

  // 1) A caption/heading that starts with the full typed reference
  //    ("section 2.5 …", "table 14.2.1.1 …", "appendix a …"). Only when there's
  //    a keyword prefix, so a bare "2.5" can't loosely match "2.50".
  if (kw) {
    const hit = blocks.find((b) => !isTocBlock(b) && norm(b).startsWith(lower));
    if (hit) return hit.index;
  }

  // 2) For non-table refs: a heading line that STARTS with the number at a
  //    boundary — "2.5 Study Objectives" AND "10. EFFICACY EVALUATION". The
  //    lookahead rejects a deeper number ("10" must not match "100" or the
  //    sub-section "10.5"), but a trailing "." before the title (the common
  //    "10. TITLE" heading style) must still match — so we forbid a following
  //    digit and a following ".<digit>", but allow ". TITLE". Never a table.
  if (!tableish && num) {
    const headStart = new RegExp(`^${esc(num)}(?!\\d)(?!\\.\\d)`);
    const hit = blocks.find(
      (b) => !isTableBlock(b) && !isTocBlock(b) && headStart.test(norm(b)),
    );
    if (hit) return hit.index;
  }

  // 3) Table refs: the typed caption, then the table ROW carrying the number.
  if (tableish && numBound) {
    const cap = blocks.find((b) => !isTocBlock(b) && norm(b).startsWith(`${kw} ${num}`));
    if (cap) return cap.index;
    const row = blocks.find((b) => isTableBlock(b) && numBound.test(b.text || ""));
    if (row) return row.index;
  }

  // 4) The full reference text appears somewhere (e.g. "section 2.5" mid-sentence).
  //    Never the TOC (it lists every number) — that stole the scroll for big PDFs.
  const textHit = blocks.find((b) => !isTocBlock(b) && (b.text || "").toLowerCase().includes(lower));
  if (textHit) return textHit.index;

  // 5) Last resort: a block containing the exact number — but NEVER a table for
  //    a non-table reference (this is the bug that sent sections to tables), and
  //    never the TOC.
  if (numBound) {
    const hit = blocks.find(
      (b) => !isTocBlock(b) && (tableish || !isTableBlock(b)) && numBound.test(b.text || ""),
    );
    if (hit) return hit.index;
  }
  return -1;
}
