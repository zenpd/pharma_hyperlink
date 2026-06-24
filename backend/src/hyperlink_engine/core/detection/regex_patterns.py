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

import os
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

URL_V1 = Pattern(
    id="URL_V1",
    label="URL",
    # Conservative http(s) URL; stops at whitespace and common trailing punctuation.
    regex=re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+[A-Za-z0-9/]"),
    confidence=0.98,
    description="External website hyperlink (http/https)",
)


# 2. Section reference patterns

# Cue words that legitimately introduce a bare dotted section number in prose
# ("as described in 2.3", "refer to 2.3.1", "see 2.5"). Broader than the bare
# "Section"/§ requirement so real cross-references aren't missed — paired with a
# statistical-context guard below so decimals are still rejected.
_SECTION_CUES: tuple[str, ...] = (
    "section", "§", "subsection", "see", "refer", "described in", "defined in",
    "specified in", "presented in", "provided in", "outlined in", "set forth in",
    "pursuant to", "in accordance with", "according to",
)

# A dotted number sitting in a STATISTICAL context is a value, not a section:
# "95% CI 0.36-1.37", "8.5 to 10.3 per 100,000", "3.9 years", "1.37 per 100 PY".
# When any of these markers is near the match we reject it even if a cue is present.
_STAT_CONTEXT = re.compile(
    r"%|\bCI\b|\bp\s*[=<>]|\bn\s*=|±|per\s+\d|/\s*\d|\d{1,3},\d{3}|"
    r"\b(?:years?|yrs?|months?|weeks?|days?|hours?|hrs?|PY|mg|mcg|kg|g|mL|L|"
    r"mmHg|bpm|score|fold|patients?|subjects?|cells?)\b",
    re.IGNORECASE,
)


def _section_dotted_validator(window: int = 28) -> Validator:
    """Accept a bare dotted number only when (a) a section cue is nearby AND
    (b) the surrounding context isn't statistical. Restores real prose section
    references while keeping p-values / CIs / rates / measurements out."""
    cue_check = _require_context_cue(window=window, cues=_SECTION_CUES)

    def _check(m: Match, source: str) -> bool:
        if not cue_check(m, source):
            return False
        left = max(0, m.start - window)
        right = min(len(source), m.end + window)
        return _STAT_CONTEXT.search(source[left:right]) is None

    return _check


SECTION_REF_DOTTED_V1 = Pattern(
    id="SECTION_REF_DOTTED_V1",
    label="SECTION_REF",
    # Leading digit [1-9]: section numbers never start at 0, so "0.74" / "0.36"
    # (p-values, CIs, proportions) can't match.
    regex=re.compile(r"(?<![\d.])(?P<num>[1-9]\d*(?:\.\d+){1,4})(?![\d.])"),
    confidence=0.55,
    # Cue-gated AND statistical-context-guarded (see _section_dotted_validator).
    # The previous version required the literal word "Section"/§ within 30 chars,
    # which also dropped legitimate bare references ("as described in 2.3",
    # "refer to 2.3.1"). This restores them without re-admitting decimals.
    validator=_section_dotted_validator(window=28),
    description="Bare dotted-decimal section number in a section-cue, non-statistical context (no leading 0)",
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

FIGURE_REF_LETTER_V1 = Pattern(
    id="FIGURE_REF_LETTER_V1",
    label="FIGURE_REF",
    regex=re.compile(r"\bFigure\s+(?P<num>[A-Z])\b"),
    confidence=0.93,
    description="Letter-suffixed figure reference, e.g., 'Figure A' (mirrors APPENDIX_REF_LETTER_V1)",
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

APPENDIX_REF_LETTER_V1 = Pattern(
    id="APPENDIX_REF_LETTER_V1",
    label="APPENDIX_REF",
    regex=re.compile(r"\bAppendix\s+(?P<num>[A-Z])\b"),
    confidence=0.93,
    description="Letter-suffixed appendix reference, e.g., 'Appendix A' (common in protocols)",
)


# 3b. Document-type cross-references (DOC_REF) — guarded BARE-word
# Real Protocol/SAP/CSR sets reference each other by the BARE document-type word
# ("SAP", "CSR", "Protocol") and the publishing team wants the bare word itself
# hyperlinked — explicitly NOT "the CSR"/"the Protocol", just "CSR"/"Protocol".
# So we match the bare word and use a negative-guard validator to reject the
# common non-reference noun-phrases ("protocol deviation", "per protocol set").
# The acronyms (SAP/CSR) are matched case-sensitively so lowercase "sap"/"csr"
# can't false-fire; the spelled-out forms are case-insensitive. The resolver
# (orchestration/nodes.py) routes a DOC_REF to the same study's sibling document;
# a self-reference (e.g. "SAP" inside the SAP) resolves to None and is dropped,
# so a document never links to itself.

# Words that, immediately AFTER "protocol", mean it is NOT a document reference.
_PROTOCOL_FP_NEXT: tuple[str, ...] = (
    "deviation", "deviations", "deviate", "set", "sets", "violation", "violations",
    "waiver", "waivers", "amendment", "amendments", "amend", "amended",
    "number", "no", "synopsis", "compliance", "adherence", "specified",
    "defined", "mandated", "required", "population", "eligible",
)


def _doc_ref_guard(
    fp_next: tuple[str, ...] = (), fp_prev: tuple[str, ...] = ()
) -> Validator:
    """Reject a bare doc-type match whose neighbouring word shows it is NOT a
    document reference (e.g. 'protocol deviation', 'per protocol set')."""
    nset = frozenset(w.lower() for w in fp_next)
    pset = frozenset(w.lower() for w in fp_prev)
    _after = re.compile(r"[\s\-,.:;()]*([A-Za-z']+)")
    _before = re.compile(r"([A-Za-z']+)[\s\-]*$")

    def _check(m: Match, source: str) -> bool:
        if nset:
            am = _after.match(source, m.end)
            if am and am.group(1).lower() in nset:
                return False
        if pset:
            bm = _before.search(source[max(0, m.start - 12) : m.start])
            if bm and bm.group(1).lower() in pset:
                return False
        return True

    return _check


DOC_REF_PROTOCOL_V1 = Pattern(
    id="DOC_REF_PROTOCOL_V1",
    label="DOC_REF",
    regex=re.compile(r"(?<![A-Za-z])protocol(?![A-Za-z])", re.IGNORECASE),
    confidence=0.70,
    validator=_doc_ref_guard(fp_next=_PROTOCOL_FP_NEXT, fp_prev=("per",)),
    description="Bare reference to the study Protocol document (guards 'protocol deviation/set', 'per protocol')",
)

def _dedupe_parenthetical_acronym(spelled: str, acronym: str) -> Validator:
    """'Statistical Analysis Plan (SAP)' / 'Clinical Study Report (CSR)' should produce
    ONE link, on the ACRONYM in parens — the publishing team wants the short tag
    linked, not the spelled-out phrase. So reject the SPELLED-OUT form when its
    acronym immediately follows it in parentheses; keep the acronym. A standalone
    spelled-out form (no '(ACR)' after) and a standalone acronym are both unaffected.
    (Cross-run cases — Word split the phrase and the '(SAP)' into separate runs — are
    handled paragraph-level in workers/tasks._dedupe_fullname_acronym_docx.)"""
    sp = spelled.lower()
    ac = acronym.lower()

    def _check(m: Match, source: str) -> bool:
        if m.text.lower() != sp:
            return True  # the acronym branch (or other case) — keep it
        after = source[m.end : m.end + len(acronym) + 4].lstrip().lower()
        if after.startswith("("):
            after = after[1:].lstrip()
        return not after.startswith(ac)  # drop the spelled-out form, keep '(ACR)'

    return _check


DOC_REF_SAP_V1 = Pattern(
    id="DOC_REF_SAP_V1",
    label="DOC_REF",
    regex=re.compile(r"(?<![A-Za-z])(?:(?i:statistical\s+analysis\s+plan)|SAP)(?![A-Za-z])"),
    confidence=0.68,
    validator=_dedupe_parenthetical_acronym("Statistical Analysis Plan", "SAP"),
    description="Bare reference to the Statistical Analysis Plan document (SAP); de-dupes 'Statistical Analysis Plan (SAP)'",
)

DOC_REF_CSR_V1 = Pattern(
    id="DOC_REF_CSR_V1",
    label="DOC_REF",
    regex=re.compile(r"(?<![A-Za-z])(?:(?i:clinical\s+study\s+report)|CSR)(?![A-Za-z])"),
    confidence=0.68,
    validator=_dedupe_parenthetical_acronym("Clinical Study Report", "CSR"),
    description="Bare reference to the Clinical Study Report document (CSR); de-dupes 'Clinical Study Report (CSR)'",
)

DOC_REF_ISS_V1 = Pattern(
    id="DOC_REF_ISS_V1",
    label="DOC_REF",
    regex=re.compile(
        r"(?<![A-Za-z])(?:(?i:integrated\s+summary\s+of\s+safety)|ISS)(?![A-Za-z])"
    ),
    confidence=0.68,
    validator=_dedupe_parenthetical_acronym("Integrated Summary of Safety", "ISS"),
    description="Bare reference to the Integrated Summary of Safety (ISS); de-dupes 'Integrated Summary of Safety (ISS)'",
)

DOC_REF_ISE_V1 = Pattern(
    id="DOC_REF_ISE_V1",
    label="DOC_REF",
    regex=re.compile(
        r"(?<![A-Za-z])(?:(?i:integrated\s+summary\s+of\s+efficacy)|ISE)(?![A-Za-z])"
    ),
    confidence=0.68,
    validator=_dedupe_parenthetical_acronym("Integrated Summary of Efficacy", "ISE"),
    description="Bare reference to the Integrated Summary of Efficacy (ISE); de-dupes 'Integrated Summary of Efficacy (ISE)'",
)

# 3c. Document identifier cross-reference (DOC_ID)
# A protocol/compound code like "TMX-67_301" names a *document* by its id. We
# detect the distinctive letters-digits_digits shape; the resolver links it ONLY
# when a matching file is in the upload batch (token overlap on the filename),
# and an unmatched id is skipped before injection — so this cannot produce a
# false link in prose. The underscore-joined double number is distinctive enough
# that it neither fires on ordinary text nor collides with the STUDY_ID patterns
# (which require a 4-digit year and hyphen separators).
DOC_ID_V1 = Pattern(
    id="DOC_ID_V1",
    label="DOC_ID",
    regex=re.compile(r"(?<![A-Za-z0-9])[A-Z]{2,5}-\d{1,3}_\d{1,4}(?![A-Za-z0-9])"),
    confidence=0.72,
    description="Document identifier, e.g. 'TMX-67_301' (links to the matching uploaded file)",
)


# 4. CTD leaf / module
CTD_LEAF_PATH_V1 = Pattern(
    id="CTD_LEAF_PATH_V1",
    label="CTD_LEAF",
    # The path segment after the module digit is MANDATORY: a real eCTD leaf path
    # always has the "/53-clin-stud-rep/…" structure. Without this, a bare "m2"
    # matched inside unit strings like "kg/m2" (BMI) — a false positive seen on
    # real ClinicalTrials SAPs. Narrative "Module 2" mentions are handled by
    # CTD_LEAF_MODULE_V1, so requiring the slash here loses no real references.
    # The first subpath segment must be DIGIT-LED (CTD section codes are numbered:
    # "53-clin-stud-rep", "2-5-clin-overview"); this rejects dosing units like
    # "m2/day" / "mg/m2/day" where the trailing slash used to let "m2/day" through.
    regex=re.compile(r"\bm(?P<mod>[1-5])/(?P<subpath>\d[a-z0-9\-]*(?:/[a-z0-9\-]+)*)\b"),
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


# 4b. External / regulatory references (EXT_REF)
# Real protocols and SAPs cite external standards by name ("ICH E6(R2)",
# "21 CFR Part 312", "Declaration of Helsinki") and literature by DOI. These
# are high-precision (distinctive tokens, near-zero false positives) and resolve
# to stable public URLs in tasks._resolve_target — mirroring the NCT →
# clinicaltrials.gov mapping — so they become working external hyperlinks rather
# than dead text. Confirmed present in the NCT01101035 Protocol/SAP analysis.
EXT_REF_ICH_V1 = Pattern(
    id="EXT_REF_ICH_V1",
    label="EXT_REF",
    regex=re.compile(r"\bICH\s+(?P<code>[EMQS]\d+[A-Z]?)(?:\s*\((?P<rev>R\d+)\))?"),
    confidence=0.90,
    description="ICH guideline citation, e.g., 'ICH E6(R2)', 'ICH M4', 'ICH E2A'",
)

EXT_REF_CFR_V1 = Pattern(
    id="EXT_REF_CFR_V1",
    label="EXT_REF",
    # Handles both the abbreviated form ("21 CFR 312", "21 CFR Part 50") and the
    # spelled-out form seen in real protocols ("21 Code of Federal Regulations
    # (CFR) Part 56"). A trailing part/section number is required, so a bare
    # "(CFR)" definitional mention is not matched.
    regex=re.compile(
        r"\b(?:(?P<title>\d{1,2})\s+(?:Code of Federal Regulations\s*)?)?"
        r"\(?CFR\)?\s+(?:Part\s+)?(?P<part>\d+)(?:\.(?P<sec>\d+))?\b"
    ),
    confidence=0.92,
    description="US CFR citation, e.g., '21 CFR 312', '21 CFR Part 50', '21 Code of Federal Regulations (CFR) Part 56'",
)

EXT_REF_HELSINKI_V1 = Pattern(
    id="EXT_REF_HELSINKI_V1",
    label="EXT_REF",
    regex=re.compile(r"\bDeclaration of Helsinki\b", re.IGNORECASE),
    confidence=0.95,
    description="WMA Declaration of Helsinki reference",
)

EXT_REF_DOI_V1 = Pattern(
    id="EXT_REF_DOI_V1",
    label="EXT_REF",
    regex=re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+"),
    confidence=0.95,
    description="DOI citation → resolves via https://doi.org/",
)


# 4c. Visit / timepoint references (VISIT_REF)
# Clinical protocols cross-reference scheduled visits by timepoint name ("Week 2
# Visit", "Day 1/Randomization Visit", "Month 3 visit"). The literal word "Visit"
# is REQUIRED: the bare timepoint ("at Week 2", "the Week 2 sUA level") is
# descriptive prose, not a cross-reference — matching it would flood the document
# (188 raw "Week/Day/Month N" mentions in NCT01101035, only ~35 real visit refs).
# Resolves to the matching visit section ("9.3.3.1 Week 2") via the anchor index.
VISIT_REF_V1 = Pattern(
    id="VISIT_REF_V1",
    label="VISIT_REF",
    regex=re.compile(
        r"\b(?P<unit>Week|Day|Month)\s+(?P<n>\d+)(?:/[A-Za-z]+)?\s+[Vv]isit\b"
    ),
    confidence=0.85,
    description="Scheduled-visit cross-reference, e.g., 'Week 2 Visit', 'Day 1/Randomization Visit'",
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


# VISIT_REF ("Week 2 visit") links are DISABLED by default (2026-06-23): on real
# protocols most visits have NO indexed definition (the Schedule-of-Assessments rows
# aren't captured), so the links fall back to the citation's own page and read as
# stale clutter. The pattern is RETAINED (not removed) — set HYPERLINK_LINK_VISIT_REFS=1
# to re-enable once visit-definition indexing improves.
_LINK_VISIT_REFS = os.environ.get("HYPERLINK_LINK_VISIT_REFS", "").strip().lower() in ("1", "true", "yes")


def default_registry() -> PatternRegistry:
    """Return a registry pre-populated with the Phase 1 pattern set."""
    patterns = [
        STUDY_ID_SPONSOR_V1,
        STUDY_ID_PROTOCOL_V1,
        STUDY_ID_NCT_V1,
        URL_V1,
        SECTION_REF_DOTTED_V1,
        SECTION_REF_LABELED_V1,
        SECTION_REF_SIGIL_V1,
        TABLE_REF_NUMBERED_V1,
        FIGURE_REF_NUMBERED_V1,
        FIGURE_REF_LETTER_V1,
        LISTING_REF_NUMBERED_V1,
        APPENDIX_REF_NUMBERED_V1,
        APPENDIX_REF_LETTER_V1,
        DOC_REF_PROTOCOL_V1,
        DOC_REF_SAP_V1,
        DOC_REF_CSR_V1,
        DOC_REF_ISS_V1,
        DOC_REF_ISE_V1,
        DOC_ID_V1,
        CTD_LEAF_PATH_V1,
        CTD_LEAF_MODULE_V1,
        EXT_REF_ICH_V1,
        EXT_REF_CFR_V1,
        EXT_REF_HELSINKI_V1,
        EXT_REF_DOI_V1,
        VISIT_REF_V1,
    ]
    if not _LINK_VISIT_REFS:
        patterns = [p for p in patterns if p.id != "VISIT_REF_V1"]
    return PatternRegistry(patterns=patterns)


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
