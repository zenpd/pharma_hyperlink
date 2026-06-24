"""GLiNER author-name detection for literature citations (PLAN NINETEEN).

WHY: the ``_AUTHOR_YEAR`` regex is brittle to NAME DIVERSITY — measured, it MISSES
short surnames ("Xu, H 2022", "Ng, K", "Li, Q") and MANGLES compound names
("O'Brien" -> "Brien"). A new document with diverse authors silently loses those
citations. GLiNER recognises an author NAME by concept, so it generalises to any
new document (validated: it catches Xu/Ng/Li/McDonald/van der Berg that regex can't).

HOW (no conflict, high precision): GLiNER returns the NAME span only. The YEAR is
taken from an adjacent ``_YEAR`` regex — which is ALSO the citation-vs-co-author
discriminator: an in-text "See Xu, H 2022" has the year right after the name, while
a co-author buried in a References entry ("…; Boidot, R.; …") does NOT, so it is
dropped. The existing resolver then links ``(surname, year)`` -> the References
entry, so a name that matches no real entry never links (match-or-drop).

GLiNER is an OPTIONAL dependency (heavy: torch). When it is not installed this
module returns ``[]`` so the regex path keeps working untouched.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any

# First capitalised token of a GLiNER name span — the surname used as the resolver
# key. ``+`` (not ``{2,}``) so SHORT surnames ("Xu", "Ng", "Li") are kept — the
# whole point of using GLiNER over the regex.
_SURNAME = re.compile(r"[A-Z][A-Za-z'’\-]+")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_YEAR_WINDOW = 24  # chars after the name to look for the citation year

# Month names are NOT authors ("March 2020" is a date). Mirrors ref_index._MONTHS.
_MONTHS = {
    m.lower()
    for m in "January February March April May June July August September October "
    "November December Jan Feb Mar Apr Jun Jul Aug Sep Sept Oct Nov Dec".split()
}

_LABELS = ["author", "reference author", "cited author"]
_THRESHOLD = 0.45
_CHUNK = 1400  # ~ under GLiNER's token limit (matches the spike)


def available() -> bool:
    """True when the optional ``gliner`` package is importable."""
    try:
        import gliner  # noqa: F401
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def _model() -> Any:
    """Load the GLiNER model once (cached). Model id overridable via env."""
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from gliner import GLiNER

    name = os.environ.get("HYPERLINK_GLINER_MODEL", "urchade/gliner_medium-v2.1")
    return GLiNER.from_pretrained(name)


class CiteMatch:
    """Minimal ``re.Match``-compatible shim so GLiNER hits flow through the SAME
    consumers as ``author_year_cites()`` (which return ``re.Match``): they call
    ``.group("surname")``, ``.group("year")``, ``.group(0)``, ``.start()``, ``.end()``."""

    __slots__ = ("_groups", "_start", "_end", "_text")

    def __init__(self, surname: str, year: str, start: int, end: int, text: str) -> None:
        self._groups = {"surname": surname, "year": year}
        self._start, self._end, self._text = start, end, text

    def group(self, key: int | str = 0) -> str:
        if key == 0:
            return self._text
        return self._groups.get(str(key), "")

    def start(self) -> int:
        return self._start

    def end(self) -> int:
        return self._end


def _dedup(matches: list[CiteMatch]) -> list[CiteMatch]:
    """Drop a match whose span overlaps one already kept (GLiNER may return both
    'Xu' and 'Xu, H')."""
    kept: list[CiteMatch] = []
    for m in sorted(matches, key=lambda x: (x.start(), -(x.end() - x.start()))):
        if any(not (m.end() <= k.start() or m.start() >= k.end()) for k in kept):
            continue
        kept.append(m)
    return kept


def _cites_from_entities(text: str, entities: list[dict[str, Any]]) -> list[CiteMatch]:
    """Turn GLiNER author entities (offsets already absolute into ``text``) into
    citation matches: keep only those with a YEAR right after the name. Pure logic
    (no model) — unit-testable with fake entities."""
    out: list[CiteMatch] = []
    for e in entities:
        name = (e.get("text") or "").strip()
        sm = _SURNAME.match(name)
        if not sm:
            continue
        surname = sm.group(0)
        if surname.lower() in _MONTHS:
            continue
        start = int(e.get("start", 0))
        end = int(e.get("end", start + len(name)))
        # Search a window that starts a few chars BEFORE the span end too: GLiNER
        # sometimes includes the year in the name span ("Tankere, P 2022"), so a
        # strictly-after window would miss it (measured on the gold set, Phase C).
        ym = _YEAR.search(text[max(0, end - 6) : end + _YEAR_WINDOW])
        if not ym:  # no adjacent year -> a co-author/plain name, not a citation
            continue
        out.append(CiteMatch(surname, ym.group(0), start, end, name))
    return _dedup(out)


def gliner_ref_cites(text: str) -> list[CiteMatch]:
    """Author-name citations via GLiNER, each paired with an adjacent year.
    Returns ``[]`` when gliner is unavailable so the regex path stays the source
    of truth (never raises)."""
    if not text or not available():
        return []
    try:
        model = _model()
    except Exception:
        return []
    res: list[CiteMatch] = []
    for base in range(0, len(text), _CHUNK):
        chunk = text[base : base + _CHUNK]
        if not chunk.strip():
            continue
        try:
            ents = model.predict_entities(chunk, _LABELS, threshold=_THRESHOLD)
        except Exception:
            continue
        shifted = [
            {
                "text": e.get("text"),
                "start": base + int(e.get("start", 0)),
                "end": base + int(e.get("end", 0)),
            }
            for e in ents
        ]
        res.extend(_cites_from_entities(text, shifted))
    return _dedup(res)
