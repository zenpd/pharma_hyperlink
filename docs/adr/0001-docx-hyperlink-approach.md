# ADR-0001 — Word Hyperlink Injection via python-docx XML manipulation

| Field | Value |
|---|---|
| **Status** | Accepted |
| **Date** | Week 1 of POC |
| **Deciders** | Engineering Lead + Publishing SME |
| **Supersedes** | — |
| **Superseded by** | — |

---

## Context

The engine must inject thousands of hyperlinks into Dosscriber-authored Word documents (.docx) while:

1. **Preserving Dosscriber styles** — corporate templates carry custom paragraph/character styles. Any mutation outside the link text itself is a blocker (will fail publishing QC).
2. **Supporting both link types** — external URLs (e.g., `https://clinicaltrials.gov/...`) and internal bookmarks (e.g., `Section 2.5.3` → `#sec_2_5_3`).
3. **Round-tripping cleanly** — output must open in Word 2016+, Word 365, and Word for Mac without corruption warnings.
4. **Working at batch scale** — 500+ documents per run; cannot rely on UI-driven automation.
5. **Auditable** — every injection must be reproducible from input + reference list; no opaque library magic.

Three approaches were considered.

---

## Options Considered

### Option A — `python-docx` direct XML injection (CHOSEN)

Use `python-docx` to load the document model, then directly build `<w:hyperlink>` XML elements and inject them at exact run locations.

```python
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

doc = Document(input_path)
para = doc.paragraphs[12]
run = para.runs[3]

# Add relationship for external URL
rel_id = para.part.relate_to(
    target_url,
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
    is_external=True,
)

# Build the w:hyperlink wrapper
hyperlink = OxmlElement("w:hyperlink")
hyperlink.set(qn("r:id"), rel_id)
hyperlink.append(run._element)  # nest the run inside hyperlink

# Replace original run with the hyperlink in the paragraph
para._element.insert(para._element.index(run._element), hyperlink)
doc.save(output_path)
```

**Pros:**
- Library is mature, stable, single-purpose
- Full control over XML — preserves run styling exactly
- No round-trip through external tools (no Word, no LibreOffice, no Pandoc)
- Easy to unit-test: load .docx with `python-docx`, assert presence of `w:hyperlink` element
- Deterministic — same input always produces same output (audit-friendly)
- No external dependencies beyond the library itself

**Cons:**
- Verbose XML construction (mitigated by `injection/docx_linker.py` wrapper)
- Library only supports a subset of OOXML — exotic Dosscriber styles may need manual validation
- Internal bookmark targets must already exist in the document (or we create them via separate step)

### Option B — Round-trip through Word COM automation (REJECTED)

Use `pywin32` to drive Microsoft Word via COM; insert hyperlinks via the Word UI object model.

**Pros:**
- Word handles all OOXML edge cases natively

**Cons (deal-breakers):**
- Requires Word installed on the processing machine (license cost; not on Linux/on-prem)
- Single-process — cannot parallelize across 500-doc batch
- Brittle (any Word dialog box halts the pipeline)
- Cannot run in Docker / on-prem Linux production environment
- Not reproducible — Word version differences produce different XML
- Audit nightmare — opaque to inspection

### Option C — Pandoc / LibreOffice round-trip (REJECTED)

Convert .docx → Markdown/HTML → modify → convert back to .docx.

**Pros:**
- Pandoc handles many formats
- Cross-platform

**Cons (deal-breakers):**
- **Loses Dosscriber styles** — round-trip strips custom character/paragraph styles. This violates the #1 requirement.
- Lossy formatting (tables, embedded images, comments, tracked changes)
- Non-deterministic across Pandoc versions
- Adds a heavy external dependency

---

## Decision

**Adopt Option A — python-docx XML injection.**

The combination of style preservation, batch scalability, deterministic output, on-prem compatibility, and auditability makes this the only viable choice for the POC and production deployment.

---

## Consequences

### Positive

- We own the injection logic end-to-end (no external tool dependency)
- Style preservation tests (`tests/integration/test_style_preservation.py`) can compare pre/post XML diffs byte-level
- Easy to extend (new link types, custom anchors) without changing infrastructure
- Works identically on developer laptop (Windows) and on-prem (Linux Docker)

### Negative

- Engineering must understand OOXML well enough to construct correct `w:hyperlink` elements (mitigated by `docx_linker.py` wrapper and unit tests covering edge cases)
- Library version pinning critical — `python-docx >= 1.1` chosen for stable hyperlink support
- We must build our own bookmark-creation helper for internal links (separate concern; see `injection/style_preserver.py` Phase 2 extension)

### Mitigations

1. **OOXML reference** — link `docs/adr/0001-docx-hyperlink-approach.md` to the [ECMA-376 OOXML standard](https://www.ecma-international.org/publications-and-standards/standards/ecma-376/) in the appendix
2. **Style preservation regression suite** — every PR runs `tests/integration/test_style_preservation.py` against Dosscriber template fixtures
3. **Diff-check on every output** — `style_preserver.py::assert_no_unrelated_mutation()` raises if any run outside the link span has changed
4. **Manual SME sign-off** — Phase 1 acceptance gate (W4.6) requires publishing SME to visually inspect 50 sample links in Word

---

## Implementation Notes

The `injection/docx_linker.py` module will expose a high-level API:

```python
class DocxLinker:
    def __init__(self, source_path: Path, output_path: Path) -> None: ...

    def add_external_link(
        self,
        location: RunLocation,
        url: str,
        display_text: str | None = None,
    ) -> None: ...

    def add_internal_link(
        self,
        location: RunLocation,
        anchor: str,
        display_text: str | None = None,
    ) -> None: ...

    def save(self) -> None: ...  # validates + writes; raises on style mutation
```

Detailed implementation lives in `src/hyperlink_engine/injection/docx_linker.py` (W1.5 spike).

---

## Open Questions (resolved during W1.5 spike)

- [x] How do we handle hyperlinks that span multiple runs? → split the affected runs at link boundaries, then wrap.
- [x] Do we preserve existing hyperlinks if they're already correct? → yes, via `parser.has_link_at(location)` short-circuit.
- [x] What's the bookmark-creation strategy for internal links to headings that don't yet have bookmarks? → auto-create `bookmarkStart`/`bookmarkEnd` pair around target heading run; name = `sec_<dotted_num>` (e.g., `sec_2_5_3`).

---

## References

- ECMA-376 Part 1 §17.16.22 (Hyperlinks)
- python-docx documentation: https://python-docx.readthedocs.io/
- Dosscriber template style guide (internal — link in `docs/sop-mapping.md` after W1.3 workshop)
