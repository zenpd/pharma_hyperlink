"""Regex-based reference pattern engine.

Implements the patterns defined in `docs/pattern-catalog.md`. Phase 1 ships
the three foundational pattern families needed by the W1.5 spike (Study ID,
Section ref, Table ref) plus a handful of high-confidence neighbors so the
demo can show breadth.

The full 29-pattern catalog rolls in over Week 3 alongside the NER model.

Conflict resolution between overlapping matches is handled in
`entity_extractor.py` per catalog §8.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator

import regex as re


@dataclass(frozen=True)
class Match:
    """A single regex hit.

    `pattern_id` matches an entry in `docs/pattern-catalog.md`. `groups`
    holds named regex captures (e.g., `{"sponsor": "SP", "year": "2024"}`).
    """

    pattern_id: str
    text: str
    start: int
    end: int
    confidence: float
    groups: dict[str, str] = field(default_factory=dict)

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "Match") -> bool:
        return not (self.end <= other.start or other.end <= self.start)


# A validator narrows false positives that survive the regex itself.
Validator = Callable[[Match, str], bool]


def _always_true(_: Match, __: str) -> bool:
    return True


def _require_context_cue(window: int = 30, cues: tuple[str, ...] = ()) -> Validator:
    """Return a validator that demands at least one cue word near the match."""
    lowered = tuple(c.lower() for c in cues)

    def _check(m: Match, source: str) -> bool:
        left = max(0, m.start - window)
        right = min(len(source), m.end + window)
        haystack = source[left:right].lower()
        return any(cue in haystack for cue in lowered)

    return _check


@dataclass(frozen=True)
class Pattern:
    """A compiled regex with metadata for the engine."""

    id: str
    label: str  # NER label
    regex: re.Pattern[str]
    confidence: float
    validator: Validator = _always_true
    description: str = ""

    def finditer(self, text: str) -> Iterator[Match]:
        for raw in self.regex.finditer(text):
            m = Match(
                pattern_id=self.id,
                text=raw.group(0),
                start=raw.start(),
                end=raw.end(),
                confidence=self.confidence,
                groups={k: v for k, v in raw.groupdict().items() if v is not None},
            )
            if self.validator(m, text):
                yield m


# ─────────────────────────────────────────────────────────────────────────
# Pattern library — Phase 1 subset (W1.5 spike)
# ─────────────────────────────────────────────────────────────────────────

# 1. Study ID patterns
STUDY_ID_SPONSOR_V1 = Pattern(
    id="STUDY_ID_SPONSOR_V1",
    label="STUDY_ID",
    regex=re.compile(r"(?<![A-Z0-9])(?P<sponsor>[A-Z]{2,5})-(?P<year>\d{4})-(?P<seq>\d{3,4})(?![A-Z0-9])"),
    confidence=0.95,
    description="Standard sponsor-prefixed clinical study ID, e.g., SP-2024-001",
)

STUDY_ID_PROTOCOL_V1 = Pattern(
    id="STUDY_ID_PROTOCOL_V1",
    label="STUDY_ID",
    regex=re.compile(r"(?<![A-Z0-9])PROT-(?P<sponsor>[A-Z]{2,5})-(?P<num>\d{4,6})(?![A-Z0-9])"),
    confidence=0.97,
    description="Protocol-prefixed identifier, e.g., PROT-ABC-1234",
)

STUDY_ID_NCT_V1 = Pattern(
    id="STUDY_ID_NCT_V1",
    label="STUDY_ID",
    regex=re.compile(r"\bNCT\d{8}\b"),
    confidence=0.99,
    description="ClinicalTrials.gov registry identifier",
)


# 2. Section reference patterns
SECTION_REF_DOTTED_V1 = Pattern(
    id="SECTION_REF_DOTTED_V1",
    label="SECTION_REF",
    regex=re.compile(r"(?<![\d.])(?P<num>\d+(?:\.\d+){1,4})(?![\d.])"),
    confidence=0.55,
    validator=_require_context_cue(
        window=30,
        cues=("section", "see ", "refer to", "§", "per ", "described in", "noted in"),
    ),
    description="Bare dotted-decimal section number, requires nearby context cue",
)

SECTION_REF_LABELED_V1 = Pattern(
    id="SECTION_REF_LABELED_V1",
    label="SECTION_REF",
    regex=re.compile(r"(?:Section|Sect\.?|sec\.?)\s+(?P<num>\d+(?:\.\d+){0,4})", re.IGNORECASE),
    confidence=0.92,
    description="Explicit 'Section X.Y.Z' label",
)

SECTION_REF_SIGIL_V1 = Pattern(
    id="SECTION_REF_SIGIL_V1",
    label="SECTION_REF",
    regex=re.compile(r"§\s*(?P<num>\d+(?:\.\d+){0,4})"),
    confidence=0.97,
    description="Section sign (§) reference",
)


# 3. Table / figure / listing
TABLE_REF_NUMBERED_V1 = Pattern(
    id="TABLE_REF_NUMBERED_V1",
    label="TABLE_REF",
    regex=re.compile(r"\bTable\s+(?P<num>\d+(?:[\.\-]\d+){0,4})\b"),
    confidence=0.96,
    description="Standard table reference, e.g., 'Table 14.2.1.1'",
)

FIGURE_REF_NUMBERED_V1 = Pattern(
    id="FIGURE_REF_NUMBERED_V1",
    label="FIGURE_REF",
    regex=re.compile(r"\bFigure\s+(?P<num>\d+(?:[\.\-]\d+){0,4})\b"),
    confidence=0.96,
    description="Standard figure reference",
)

LISTING_REF_NUMBERED_V1 = Pattern(
    id="LISTING_REF_NUMBERED_V1",
    label="LISTING_REF",
    regex=re.compile(r"\bListing\s+(?P<num>\d+(?:[\.\-]\d+){0,4})\b"),
    confidence=0.96,
    description="CSR Appendix 16.2 listing reference",
)

APPENDIX_REF_NUMBERED_V1 = Pattern(
    id="APPENDIX_REF_NUMBERED_V1",
    label="APPENDIX_REF",
    regex=re.compile(r"\bAppendix\s+(?P<num>\d+(?:\.\d+){0,3})\b"),
    confidence=0.96,
    description="Numbered appendix reference",
)


# 4. CTD leaf / module
CTD_LEAF_PATH_V1 = Pattern(
    id="CTD_LEAF_PATH_V1",
    label="CTD_LEAF",
    regex=re.compile(r"\bm(?P<mod>[1-5])(?:/(?P<subpath>[a-z0-9\-]+(?:/[a-z0-9\-]+)*))?\b"),
    confidence=0.94,
    description="Direct eCTD leaf path, e.g., 'm5/53-clin-stud-rep/5331/study-001'",
)

CTD_LEAF_MODULE_V1 = Pattern(
    id="CTD_LEAF_MODULE_V1",
    label="CTD_LEAF",
    regex=re.compile(r"\bModule\s+(?P<mod>[1-5])(?:\.(?P<sub>\d+(?:\.\d+){0,3}))?\b"),
    confidence=0.95,
    description="Narrative module reference, e.g., 'Module 2.5.3'",
)


# ─────────────────────────────────────────────────────────────────────────
# Registry — central access point used by the detection pipeline
# ─────────────────────────────────────────────────────────────────────────


class PatternRegistry:
    """Holds the active set of patterns and runs them against text."""

    def __init__(self, patterns: Iterable[Pattern] | None = None) -> None:
        self._patterns: dict[str, Pattern] = {}
        for p in patterns or ():
            self.register(p)

    def register(self, pattern: Pattern) -> None:
        if pattern.id in self._patterns:
            raise ValueError(f"Pattern {pattern.id!r} already registered")
        self._patterns[pattern.id] = pattern

    def get(self, pattern_id: str) -> Pattern:
        return self._patterns[pattern_id]

    def __len__(self) -> int:
        return len(self._patterns)

    def __iter__(self) -> Iterator[Pattern]:
        return iter(self._patterns.values())

    def find_all(self, text: str) -> list[Match]:
        """Run every pattern against `text` and return all matches (unsorted)."""
        matches: list[Match] = []
        for pattern in self._patterns.values():
            matches.extend(pattern.finditer(text))
        return matches

    def find_all_sorted(self, text: str) -> list[Match]:
        """Same as `find_all` but sorted by start position then descending confidence."""
        return sorted(self.find_all(text), key=lambda m: (m.start, -m.confidence))


def default_registry() -> PatternRegistry:
    """Return a registry pre-populated with the Phase 1 pattern set."""
    return PatternRegistry(
        patterns=[
            STUDY_ID_SPONSOR_V1,
            STUDY_ID_PROTOCOL_V1,
            STUDY_ID_NCT_V1,
            SECTION_REF_DOTTED_V1,
            SECTION_REF_LABELED_V1,
            SECTION_REF_SIGIL_V1,
            TABLE_REF_NUMBERED_V1,
            FIGURE_REF_NUMBERED_V1,
            LISTING_REF_NUMBERED_V1,
            APPENDIX_REF_NUMBERED_V1,
            CTD_LEAF_PATH_V1,
            CTD_LEAF_MODULE_V1,
        ]
    )


def resolve_overlaps(matches: list[Match]) -> list[Match]:
    """Apply catalog §8 conflict resolution: highest confidence wins.

    For matches with identical confidence, the longer one wins (more specific
    pattern). Returns a new list of non-overlapping matches sorted by start.
    """
    if not matches:
        return []

    # Process candidates in priority order: highest confidence first, then
    # longest span (more specific pattern), then earliest position. Each
    # winner blocks anything it overlaps.
    priority = sorted(matches, key=lambda m: (-m.confidence, -m.length, m.start))
    kept: list[Match] = []
    for m in priority:
        if any(m.overlaps(k) for k in kept):
            continue
        kept.append(m)
    return sorted(kept, key=lambda m: m.start)
