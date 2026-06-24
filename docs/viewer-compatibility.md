# Viewer Compatibility Matrix — Phase 3 W9.1

> Tested behaviour of injected hyperlinks across the viewers used by reviewers
> at health authorities and inside SunPharma / Celegence review tooling.

This document is the canonical reference for "will this link work for the
person who opens the published PDF?" The matrix is updated whenever the
W9.2 headless validation harness (`validation/viewer_compat.py`) gains a new
viewer adapter or when a quirk is discovered in production.

---

## 1. Viewer inventory

| ID                | Viewer                              | Engine     | Versions tested | Where it's used |
|-------------------|-------------------------------------|------------|-----------------|------------------|
| `adobe_reader_dc` | Adobe Acrobat Reader DC (free)       | Acrobat    | 2024.002        | Most external reviewers; default Windows handler |
| `adobe_acrobat_pro` | Adobe Acrobat Pro DC               | Acrobat    | 2024.002        | Internal QC team; preflight tooling |
| `foxit_reader`    | Foxit PDF Reader                    | Foxit      | 13.x            | Backup reviewer machines |
| `pdfjs_chrome`    | Chrome / Edge built-in PDF.js       | PDF.js     | 122 → 128       | Browser preview in Dossplorer™ |
| `pdfjs_firefox`   | Firefox built-in PDF.js             | PDF.js     | 122 → 130       | Some EU reviewer workstations |
| `dossplorer_preview` | Dossplorer™ in-app preview (Celegence) | Chromium  | n/a (vendored)  | Internal review workflow |
| `fda_esg`         | FDA Electronic Submissions Gateway   | proprietary | n/a (HA) | Gate at submission ingest |
| `ema_espre`       | EMA EU Submission Portal (ESPRE)     | proprietary | n/a (HA) | EMA gateway |
| `pmda_gateway`    | PMDA submission gateway              | proprietary | n/a (HA) | Japan submissions |

---

## 2. Compatibility matrix

Legend: ✅ works, ⚠️ works with caveats (see notes), ❌ broken, ➖ not applicable, 🧪 stubbed only (no real test access).

| Viewer / Link type                | Internal anchor (`#sec_x_y_z`) | Named destination | Cross-doc relative URI | Cross-module (eCTD `<leaf-xref>`) | External URL (https://) |
|------------------------------------|:------------------------------:|:-----------------:|:----------------------:|:----------------------------------:|:------------------------:|
| `adobe_reader_dc`                  | ✅                            | ✅                | ✅                     | ⚠️ (1)                            | ✅                       |
| `adobe_acrobat_pro`                | ✅                            | ✅                | ✅                     | ✅                                | ✅                       |
| `foxit_reader`                     | ✅                            | ⚠️ (2)            | ✅                     | ⚠️ (2)                            | ✅                       |
| `pdfjs_chrome`                     | ✅                            | ⚠️ (3)            | ⚠️ (4)                 | ❌ (4)                            | ✅                       |
| `pdfjs_firefox`                    | ✅                            | ⚠️ (3)            | ⚠️ (4)                 | ❌ (4)                            | ✅                       |
| `dossplorer_preview`               | ✅                            | ✅                | ✅                     | ✅                                | ⚠️ (5)                   |
| `fda_esg`                          | 🧪                            | 🧪                | 🧪                     | 🧪                                | 🧪                       |
| `ema_espre`                        | 🧪                            | 🧪                | 🧪                     | 🧪                                | 🧪                       |
| `pmda_gateway`                     | 🧪                            | 🧪                | 🧪                     | 🧪                                | 🧪                       |

**Word documents (.docx):** Internal bookmarks and external URLs are fully
supported in Microsoft Word 365 and LibreOffice Writer 7.6+. The engine
never generates Word-side cross-module links — those live in PDF renditions.

---

## 3. Notes & quirks

### (1) Adobe Reader DC — Cross-module `<leaf-xref>`
Reader DC follows ICH eCTD relative URIs correctly **provided** the target
leaf is present in the sequence directory tree. If the reader receives only
the leaf file in isolation (e.g., email attachment), the cross-module link
falls back to "file not found." Mitigation: the existence_checker raises
`UNVERIFIED` for cross-module links so reviewers know the link requires the
full backbone to resolve.

### (2) Foxit Reader — Named destinations
Foxit honours the `/Dest` array but ignores the `/StructTreeRoot` linkage
that Acrobat uses. Named destinations defined as compound names (e.g.,
`sec_2_5_3.subhead_4`) only work when written as `/D [ <page> /XYZ <x> <y> <z> ]`
explicit destinations. pikepdf writes both forms by default; no action needed
unless `HYPERLINK_PDF_DEST_FORMAT=compound_only` is set.

### (3) PDF.js — Named destinations
PDF.js resolves named destinations only when the URL fragment is the **exact
string** declared in the `/Names` tree. Some EMA reviewers configure their
Firefox profile to lowercase URL fragments, breaking case-sensitive names.
The engine emits all named destinations in lowercase + ASCII to side-step this.

### (4) PDF.js — Cross-doc / cross-module
Built-in PDF.js does not follow relative-path PDF→PDF links — it tries to
open the target as a new tab via HTTP, which the file:// scheme prevents.
Dossplorer™ preview wraps PDF.js in a custom URL handler that intercepts
these clicks and routes them through the dossier filesystem. For the public
PDF.js, cross-doc links are listed as `UNVERIFIED` in the validation report
with a "viewer limitation" rationale.

### (5) Dossplorer preview — External URLs
By design, Dossplorer™ strips external URLs (security policy: reviewers should
not be able to navigate away from the dossier). The link is rendered as plain
text. The engine flags this as an `INFO`-level anomaly rather than a failure.

---

## 4. Testing strategy

### Automated (W9.2 harness)
- **Structural pass:** `qpdf --check` on every linked PDF — catches malformed
  link annotations before any viewer-specific test.
- **PDF.js (Playwright):** loads each PDF in headless Chromium, enumerates the
  link annotations via the PDF.js JS API, and simulates a click on each.
- **Adobe (stub for POC):** real Acrobat SDK integration is gated to Phase 4.
  In POC, the harness emits an `UNVERIFIED` result with a note that an Acrobat
  Pro DC operator should run the regression suite manually before each
  acceptance gate.
- **HA simulators (stub):** the FDA ESG and EMA ESPRE adapters are stubs
  awaiting access credentials. Their `check()` methods raise `NotImplementedError`
  unless `HYPERLINK_HA_SIMULATOR_HOST` is configured.

### Manual
Before each phase tag, the publishing SME runs the regression corpus
(`tests/integration/test_viewer_compat.py`'s sample fixture) in Acrobat Pro
and records pass/fail in `output/viewer_qa/<date>.md`. This serves as the
GxP-traceable evidence that the matrix above is current.

---

## 5. Update policy

This matrix is **living documentation**:

1. Whenever a viewer is added to the harness, append a row.
2. Whenever a new quirk is found in production, add a note + bump the matrix
   cell from ✅ to ⚠️.
3. Whenever an HA publishes new guidance affecting link behaviour, log an
   ADR in `docs/adr/` and reflect the rule in `config/ha_rules.yaml`.

Last verified: see `output/viewer_qa/` for dated SME sign-offs.
