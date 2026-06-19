"""References-section index + in-text citation matchers (PLAN — citation linking).

Problem it solves
-----------------
Clinical documents cite literature in two styles and list it in a *References*
section at the end:

* **Author-year** (the team's CSR): in-text ``"see Helget LN, 2024"`` → a
  References entry ``"Helget LN et al. … Am J Kidney Dis. 2024"``.
* **Numbered** (the protocol PDFs): in-text ``"[7]"`` → a numbered entry
  ``"7. Marcus R, … Biometrika 1976"``.

Neither was linked before — there was no pattern for an author-year citation and
no machinery that parsed the References list into per-entry anchors. This module
supplies both halves so a citation hyperlinks to its bibliography entry:

* **Citation matchers** (``author_year_cites`` / ``numbered_cites``) used by the
  detection stage to find the in-text citations.
* **Index helpers** (``is_references_heading`` / ``parse_ref_entry_key``) used by
  the anchor index to turn each References entry into a bookmark keyed the *same*
  way the citation resolves, so citation ⇆ entry meet on one key.

Matching rule (verified on the real CSR)
----------------------------------------
* Citation key = ``(first-author surname, year)`` — **surname alone is
  ambiguous**: "Schumacher" is the first author of the 2010 entry *and* a
  co-author of the 2005 entry, so the year is required to disambiguate.
* The in-text matcher requires a **comma/space** (never a period) between the
  name and the year, so a References entry's own ``"… Med. 2005"`` /
  ``"… Dis. 2024"`` journal-then-year tail is *not* mistaken for a citation —
  the period guard removes the need to special-case the References section.
* Month names are rejected so date noise ("February 2017") never matches.
"""

from __future__ import annotations

import re

# A citation whose specific bibliography entry can't be found still links here
# (the "REFERENCES" heading) rather than being dropped — the team's explicit
# "by not skipping" requirement.
REF_HEADING_KEY = "ref_heading"


# ─────────────────────────────────────────────────────────────────────────
# Canonical keys — the citation side and the index side MUST agree byte-for-byte
# ─────────────────────────────────────────────────────────────────────────


def canonical_ref_key_author(surname: str, year: str) -> str:
    """('Helget','2024') -> 'ref_helget_2024'. Surname is lower-cased and stripped
    of non-letters so 'O'Brien' / 'van-Dijk' key cleanly."""
    s = re.sub(r"[^a-z]", "", (surname or "").lower())
    return f"ref_{s}_{year}"


def canonical_ref_key_num(n: str | int) -> str:
    """('7' | 7) -> 'ref_7'. Leading zeros normalised ('07' -> 'ref_7')."""
    return f"ref_{int(n)}"


# ─────────────────────────────────────────────────────────────────────────
# In-text citation matchers (detection side)
# ─────────────────────────────────────────────────────────────────────────

_MONTHS = {
    m.lower()
    for m in (
        "January February March April May June July August September October "
        "November December Jan Feb Mar Apr Jun Jul Aug Sep Sept Oct Nov Dec"
    ).split()
}

# Author-year in-text citation: a Capitalised surname, optional initials, then a
# year — separated by comma/whitespace only (NOT a period, which would admit a
# References entry's "Journal. 2005" tail). "Helget LN, 2024" / "Becker MA, 2005".
_AUTHOR_YEAR = re.compile(
    r"\b(?P<surname>[A-Z][a-z]{2,})"
    r"(?:\s+(?P<initials>[A-Z]{1,3}))?"
    r",?\s+(?P<year>(?:19|20)\d{2})\b"
)

# Numbered in-text citation marker: "[7]", "[12]" (the protocol PDFs). Brackets
# are required so a numbered References *entry* ("7. …") is never matched here.
_NUM_CITE = re.compile(r"\[(?P<num>\d{1,3})\]")


def author_year_cites(text: str) -> list[re.Match[str]]:
    """In-text author-year citations in *text* (month-name false positives dropped)."""
    return [
        m
        for m in _AUTHOR_YEAR.finditer(text or "")
        if m.group("surname").lower() not in _MONTHS
    ]


def numbered_cites(text: str) -> list[re.Match[str]]:
    """In-text numbered citation markers ("[7]") in *text*."""
    return list(_NUM_CITE.finditer(text or ""))


# ─────────────────────────────────────────────────────────────────────────
# References-section parsing (index side)
# ─────────────────────────────────────────────────────────────────────────

# "15. REFERENCES", "References", "11 REFERENCES" — a short standalone heading.
_REF_HEADING = re.compile(r"^\s*(?:\d{1,2}[.)]?\s+)?references\b", re.IGNORECASE)

# A heading that ENDS the References list (the next CTD/CSR section). It must NOT
# fire on a numbered reference *entry* ("1. Marcus R, …") — those look exactly like
# a numbered heading. So we match either a named next-section word (case-insensitive)
# OR a numbered heading whose title is ALL-CAPS ("16. APPENDICES") — a reference
# entry's mixed-case author text ("1. Marcus R…") fails the all-caps shape.
_NEXT_SECTION = re.compile(
    r"^\s*(?:"
    r"(?i:appendix|appendices|annex|annexes|glossary|abbreviations?|"
    r"acknowledge?ments?|bibliography|list of|tables?|figures?|listings?)\b"
    r"|\d{1,2}[.)]\s+[A-Z][A-Z0-9 &/()_'-]{2,}$"  # "16. APPENDICES" (ALL-CAPS title)
    r")"
)

_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_LEAD_NUM = re.compile(r"^\s*(\d{1,3})[.)]\s+")  # "7. Marcus R…", "12) …"
_LEAD_SURNAME = re.compile(r"^\s*([A-Z][A-Za-z'\-]{2,})")  # "Helget LN et al."


def is_references_heading(text: str) -> bool:
    """True when *text* is the standalone 'REFERENCES' heading (not prose mentioning
    references)."""
    s = (text or "").strip()
    return len(s) <= 40 and bool(_REF_HEADING.match(s))


def is_next_section_after_refs(text: str) -> bool:
    """True when *text* is the heading that terminates the References list."""
    s = (text or "").strip()
    return len(s) <= 60 and bool(_NEXT_SECTION.match(s))


def references_span(texts: list[str]) -> tuple[int | None, int | None]:
    """``[start, end)`` paragraph/line range of the References section, or
    ``(None, None)``. ``start`` is the 'REFERENCES' heading; ``end`` is the next
    terminating section (or the document end). Used to suppress in-text citation
    detection *inside* the bibliography (an entry's "Journal 1976" tail would
    otherwise self-match as a citation)."""
    start = next((i for i, t in enumerate(texts) if is_references_heading(t)), None)
    if start is None:
        return None, None
    end = len(texts)
    for i in range(start + 1, len(texts)):
        if is_next_section_after_refs(texts[i]):
            end = i
            break
    return start, end


def parse_ref_entry_key(text: str) -> str | None:
    """Canonical anchor key for a single References entry line, or None.

    Numbered entry ('7. Marcus R …') -> 'ref_7'; author-led entry
    ('Helget LN et al. … 2024') -> 'ref_helget_2024' (first surname + the entry's
    year). Returns None for a line that is neither (blank, a stray note, …).
    """
    s = (text or "").strip()
    if not s:
        return None
    m = _LEAD_NUM.match(s)
    if m:
        return canonical_ref_key_num(m.group(1))
    sm = _LEAD_SURNAME.match(s)
    ym = _YEAR.search(s)
    if sm and ym:
        return canonical_ref_key_author(sm.group(1), ym.group(0))
    return None
