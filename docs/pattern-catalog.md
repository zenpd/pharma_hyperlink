# Reference Pattern Catalog

> **Purpose:** Authoritative inventory of every reference type the engine must detect, link, and validate. Drives the regex/NER pipeline (Layer 3) and the publishing-SME workshop (W1.3).
>
> **Owner:** Engineering + Publishing SME (joint sign-off)
> **Status:** Draft v1 (Week 1, Day 2) — refined after Maikel Bouman workshop
> **Spec:** ICH eCTD v3.2 / v4.0; SunPharma internal publishing SOPs

---

## How to read this document

Each pattern entry contains:

| Field | Meaning |
|---|---|
| **ID** | Stable identifier used in code (`PatternRegistry.get("STUDY_ID_V1")`) |
| **Label** | Human-readable name |
| **NER label** | spaCy entity label (Layer 3.2) |
| **Regex (draft)** | First-cut pattern using Python `regex` library syntax |
| **Examples** | At least 5 real-world strings the pattern should match |
| **Negative examples** | Strings that look similar but must NOT match |
| **Edge cases** | Known tricky variants |
| **False-positive risks** | Patterns that could falsely fire; mitigation noted |
| **Confidence weight** | 0.0–1.0; used by `entity_extractor.py` for conflict resolution |
| **Target resolution** | How the link target is derived from the matched text |
| **Cross-module?** | Whether matches commonly point to a different CTD module |

---

## Pattern Families (Index)

| ID prefix | Family | Count |
|---|---|---|
| `STUDY_ID_*` | Clinical study identifiers | 4 variants |
| `SECTION_REF_*` | Section number references | 5 variants |
| `APPENDIX_REF_*` | Appendix references | 3 variants |
| `TABLE_REF_*` | Table references | 3 variants |
| `FIGURE_REF_*` | Figure references | 2 variants |
| `LISTING_REF_*` | Listing references | 2 variants |
| `CTD_LEAF_*` | CTD module/leaf path references | 4 variants |
| `MODULE_PTR_*` | Cross-module narrative pointers | 3 variants |
| `EXT_REF_*` | External references (URLs, DOIs, guidelines) | 3 variants |

Total: **29 distinct patterns** in v1.

---

## 1. Study ID Patterns

### 1.1 — `STUDY_ID_SPONSOR_V1` — Standard sponsor-prefixed format

| Field | Value |
|---|---|
| **NER label** | `STUDY_ID` |
| **Regex** | `(?<![A-Z0-9])(?P<sponsor>[A-Z]{2,5})-(?P<year>\d{4})-(?P<seq>\d{3,4})(?![A-Z0-9])` |
| **Confidence** | 0.95 |
| **Examples** | `SP-2024-001`, `SUNP-2023-042`, `SPL-2025-1001`, `ABC-2022-007`, `XYZ-2024-9999` |
| **Negative** | `SP-24-1` (year too short), `sp-2024-001` (lowercase), `ZIP-12345-6789` (looks like ZIP code) |
| **Edge cases** | Sponsor prefix may be 2-5 chars; some legacy IDs use 3-digit year (deprecated — flag via `STUDY_ID_DEPRECATED_V1`) |
| **FP risks** | Could match arbitrary `XX-YYYY-NNN` strings (e.g., dates with sponsor-like prefixes). Mitigation: require word boundary AND validate sponsor against `data/known_sponsors.yaml` |
| **Target resolution** | Look up study in eCTD backbone Module 5.3.x; fallback to LLM disambiguation |
| **Cross-module?** | Yes — narrative mentions in Module 2 link to Module 5 CSR |

### 1.2 — `STUDY_ID_PROTOCOL_V1` — Protocol code variant

| Field | Value |
|---|---|
| **NER label** | `STUDY_ID` |
| **Regex** | `(?<![A-Z0-9])PROT-(?P<sponsor>[A-Z]{2,5})-(?P<num>\d{4,6})(?![A-Z0-9])` |
| **Confidence** | 0.97 (very specific) |
| **Examples** | `PROT-ABC-1234`, `PROT-SUNP-12345`, `PROT-XY-001234`, `PROT-MED-99999`, `PROT-SP-4567` |
| **Negative** | `PROT-1234` (no sponsor), `Protocol-ABC-1234` (verbose prefix) |
| **Edge cases** | `Protocol number PROT-ABC-1234` — strip the leading "Protocol number" in display text |
| **FP risks** | Low; `PROT-` prefix is distinctive |
| **Target resolution** | Same as 1.1 |
| **Cross-module?** | Yes |

### 1.3 — `STUDY_ID_NCT_V1` — ClinicalTrials.gov identifier

| Field | Value |
|---|---|
| **NER label** | `STUDY_ID` |
| **Regex** | `\bNCT\d{8}\b` |
| **Confidence** | 0.99 |
| **Examples** | `NCT01234567`, `NCT00000001`, `NCT99999999`, `NCT04567890`, `NCT05123456` |
| **Negative** | `NCT-01234567` (hyphen), `NCT1234567` (7 digits) |
| **Edge cases** | Sometimes prefixed by "(NCT...)" parenthetical |
| **FP risks** | Very low — distinctive prefix + fixed length |
| **Target resolution** | External link to `https://clinicaltrials.gov/study/<NCT>` OR internal CSR if cross-referenced in backbone |
| **Cross-module?** | Yes (commonly cited in Module 2.7.x) |

### 1.4 — `STUDY_ID_EUDRACT_V1` — EU Clinical Trials Register

| Field | Value |
|---|---|
| **NER label** | `STUDY_ID` |
| **Regex** | `\b(?P<year>\d{4})-(?P<seq>\d{6})-(?P<country>\d{2})\b` |
| **Confidence** | 0.92 |
| **Examples** | `2024-001234-12`, `2023-999999-10`, `2025-000001-99`, `2022-555555-23`, `2024-987654-31` |
| **Negative** | `2024-1234-12` (seq too short), `24-001234-12` (year too short) |
| **Edge cases** | Country code maps to ISO 3166-1 numeric — validate via `data/country_codes.yaml` |
| **FP risks** | Generic `YYYY-NNNNNN-NN` could match arbitrary identifiers. Mitigation: context window check for "EudraCT" within ±50 chars OR placement in clinical-trial-list section |
| **Target resolution** | External link to EudraCT register; internal cross-ref if mapped in backbone |
| **Cross-module?** | Yes |

---

## 2. Section Reference Patterns

### 2.1 — `SECTION_REF_DOTTED_V1` — Dotted decimal section

| Field | Value |
|---|---|
| **NER label** | `SECTION_REF` |
| **Regex** | `(?<![\d.])(?P<num>\d+(?:\.\d+){1,4})(?![\d.])` |
| **Confidence** | 0.55 (low — needs context) |
| **Examples** | `2.5.3`, `5.3.1.1`, `2.7.4.2.1`, `1.0.0`, `14.2.1.1` |
| **Negative** | `2.5` (likely a version number unless context says "section"), `192.168.1.1` (IP address), `3.14` (math constant) |
| **Edge cases** | Trailing punctuation (`2.5.3.`); embedded in tables |
| **FP risks** | High — bare dotted numbers match many things. **Always require context window check**: presence of "Section", "§", "see", "refer to" within ±30 chars |
| **Target resolution** | Match against document heading map; if cross-module, resolve via CTD module-number mapping (e.g., `5.3.1` → Module 5.3 CSR) |
| **Cross-module?** | Often (Module 2 frequently refs Module 5) |

### 2.2 — `SECTION_REF_LABELED_V1` — Labeled section reference

| Field | Value |
|---|---|
| **NER label** | `SECTION_REF` |
| **Regex** | `(?:Section|Sect\.?|sec\.?)\s+(?P<num>\d+(?:\.\d+){0,4})` |
| **Confidence** | 0.92 |
| **Examples** | `Section 2.5.3`, `Section 5`, `Sect. 11.4`, `sec 14.2.1`, `Section 2.7.4.2.1` |
| **Negative** | `Section A` (alpha — different pattern), `Section 5 of the FDA guidance` (external) |
| **Edge cases** | Pluralized "Sections 2.5 and 2.6" — current pattern matches first only; v2 enhancement |
| **FP risks** | Low |
| **Target resolution** | Same as 2.1 |
| **Cross-module?** | Often |

### 2.3 — `SECTION_REF_SIGIL_V1` — Section sign (§) reference

| Field | Value |
|---|---|
| **NER label** | `SECTION_REF` |
| **Regex** | `§\s*(?P<num>\d+(?:\.\d+){0,4})` |
| **Confidence** | 0.97 |
| **Examples** | `§2.5`, `§ 5.3.1`, `§11`, `§14.2.1.1`, `§2.7` |
| **Negative** | `§A`, `§§` (multi-section, future v2) |
| **Edge cases** | Sometimes encoded as `&sect;` HTML entity in copy-pasted content — pre-normalize |
| **FP risks** | Very low; § is distinctive |
| **Target resolution** | Same as 2.1 |
| **Cross-module?** | Often |

### 2.4 — `SECTION_REF_INLINE_V1` — "see section X" pointer

| Field | Value |
|---|---|
| **NER label** | `SECTION_REF` |
| **Regex** | `\b(?:see|refer to|as (?:described|shown|noted) in|per)\s+(?:Section\s+)?(?P<num>\d+(?:\.\d+){1,4})` |
| **Confidence** | 0.88 |
| **Examples** | `see Section 2.5.3`, `refer to 5.3.1`, `as described in Section 2.7.4`, `per 14.2.1`, `as noted in Section 11` |
| **Negative** | `see Figure 2.5.3` (figure, not section) |
| **Edge cases** | Inline references vs. start-of-sentence references — both supported |
| **FP risks** | Medium — must distinguish from Table/Figure/Appendix pointers in same vocabulary. Resolve via overlapping-span priority in `entity_extractor.py` |
| **Target resolution** | Same as 2.1 |
| **Cross-module?** | Often |

### 2.5 — `SECTION_REF_ALPHA_V1` — Alpha section (Module 1)

| Field | Value |
|---|---|
| **NER label** | `SECTION_REF` |
| **Regex** | `(?:Section|Sect\.?)\s+(?P<num>[A-Z](?:\.\d+){0,3})` |
| **Confidence** | 0.85 |
| **Examples** | `Section A`, `Section B.1`, `Section C.2.1`, `Section D`, `Section A.3.2` |
| **Negative** | `Section ABC` (acronym), `Section AA` (double-letter) |
| **Edge cases** | Module 1 regional sections use letter prefixes per FDA convention |
| **FP risks** | Medium — restrict to Module 1 documents via filename/path heuristic |
| **Target resolution** | Module 1 region-specific lookup |
| **Cross-module?** | Rare (Module 1 internal) |

---

## 3. Appendix Reference Patterns

### 3.1 — `APPENDIX_REF_NUMBERED_V1` — Numbered appendix

| Field | Value |
|---|---|
| **NER label** | `APPENDIX_REF` |
| **Regex** | `\bAppendix\s+(?P<num>\d+(?:\.\d+){0,3})\b` |
| **Confidence** | 0.96 |
| **Examples** | `Appendix 16.1.1`, `Appendix 1`, `Appendix 16.2.5`, `Appendix 16`, `Appendix 11.4.3` |
| **Negative** | `Appendix A`, `Appendices 16.1.1 and 16.1.2` (multiple — v2) |
| **Edge cases** | "Clinical Study Report Appendix 16.1.1" — full referenced phrase |
| **FP risks** | Low |
| **Target resolution** | CSR appendix structure mapping; typically intra-document |
| **Cross-module?** | Rare |

### 3.2 — `APPENDIX_REF_ALPHA_V1` — Alpha appendix

| Field | Value |
|---|---|
| **NER label** | `APPENDIX_REF` |
| **Regex** | `\bAppendix\s+(?P<id>[A-Z](?:\.\d+){0,2})\b` |
| **Confidence** | 0.94 |
| **Examples** | `Appendix A`, `Appendix B.1`, `Appendix C.2.1`, `Appendix D`, `Appendix E.3` |
| **Negative** | `Appendix ABC`, `Appendix AB` |
| **Edge cases** | Some sponsors use `Annex` interchangeably (covered by 3.3) |
| **FP risks** | Low |
| **Target resolution** | Same as 3.1 |
| **Cross-module?** | Rare |

### 3.3 — `APPENDIX_REF_ANNEX_V1` — "Annex" variant (EU style)

| Field | Value |
|---|---|
| **NER label** | `APPENDIX_REF` |
| **Regex** | `\bAnnex\s+(?P<id>(?:\d+(?:\.\d+){0,3}\|[A-Z](?:\.\d+){0,2}))\b` |
| **Confidence** | 0.93 |
| **Examples** | `Annex I`, `Annex 1`, `Annex II.A`, `Annex 16.1.1`, `Annex B.2` |
| **Negative** | `Annex of the Treaty` |
| **Edge cases** | Roman numerals (`Annex I`, `Annex IV`) common in EMA dossiers — separate sub-pattern needed (v2) |
| **FP risks** | Medium — needs context check that we're in a regulatory document |
| **Target resolution** | Same as 3.1 |
| **Cross-module?** | Sometimes (EMA-specific) |

---

## 4. Table / Figure / Listing References

### 4.1 — `TABLE_REF_NUMBERED_V1` — Standard table reference

| Field | Value |
|---|---|
| **NER label** | `TABLE_REF` |
| **Regex** | `\bTable\s+(?P<num>\d+(?:[\.\-]\d+){0,4})\b` |
| **Confidence** | 0.96 |
| **Examples** | `Table 1`, `Table 14.2.1.1`, `Table 11-4`, `Table 2.7.3-1`, `Table 5.3.5.2-2` |
| **Negative** | `Table of Contents`, `Table A` (alpha — see 4.2) |
| **Edge cases** | Mixed hyphen/dot separators in same document; normalize during match |
| **FP risks** | Low |
| **Target resolution** | In-document tables map; cross-ref to source CSR if footnoted |
| **Cross-module?** | Sometimes |

### 4.2 — `TABLE_REF_ALPHA_V1` — Alpha-prefixed table

| Field | Value |
|---|---|
| **NER label** | `TABLE_REF` |
| **Regex** | `\bTable\s+(?P<id>[A-Z](?:[\.\-]\d+){0,3})\b` |
| **Confidence** | 0.94 |
| **Examples** | `Table A.1`, `Table B-2`, `Table C.3.1`, `Table D`, `Table E.4.2` |
| **Negative** | `Table ABC` |
| **Edge cases** | Some sponsors use `Table 14.A` (mixed) — sub-pattern v2 |
| **FP risks** | Low |
| **Target resolution** | Same as 4.1 |
| **Cross-module?** | Rare |

### 4.3 — `TABLE_REF_INLINE_V1` — "as shown in Table X"

| Field | Value |
|---|---|
| **NER label** | `TABLE_REF` |
| **Regex** | `(?:see|shown in|presented in|listed in)\s+Table\s+(?P<num>\d+(?:[\.\-]\d+){0,4})` |
| **Confidence** | 0.97 |
| **Examples** | `see Table 14.2.1`, `as shown in Table 11-4`, `presented in Table 2.7.3-1`, `listed in Table 5`, `see Table 16.1.1` |
| **Negative** | `see Figure 14.2.1` |
| **Edge cases** | Combine with 4.1 in dedup phase |
| **FP risks** | Low |
| **Target resolution** | Same as 4.1 |
| **Cross-module?** | Sometimes |

### 4.4 — `FIGURE_REF_NUMBERED_V1` — Standard figure reference

| Field | Value |
|---|---|
| **NER label** | `FIGURE_REF` |
| **Regex** | `\bFigure\s+(?P<num>\d+(?:[\.\-]\d+){0,4})\b` |
| **Confidence** | 0.96 |
| **Examples** | `Figure 1`, `Figure 11`, `Figure 14.2.1`, `Figure 2.7.3-1`, `Figure 5.3-2` |
| **Negative** | `Figure of speech` (false positive — mitigated by `\b` and number requirement) |
| **Edge cases** | "Fig. 1", "Fig 1" abbreviations — covered by 4.5 |
| **FP risks** | Low |
| **Target resolution** | In-document figures map |
| **Cross-module?** | Rare |

### 4.5 — `FIGURE_REF_ABBREV_V1` — Abbreviated "Fig."

| Field | Value |
|---|---|
| **NER label** | `FIGURE_REF` |
| **Regex** | `\bFig\.?\s+(?P<num>\d+(?:[\.\-]\d+){0,4})\b` |
| **Confidence** | 0.93 |
| **Examples** | `Fig. 1`, `Fig 11`, `Fig. 14.2.1`, `Fig 2.7-1`, `Fig. 5.3.2` |
| **Negative** | `Fig leaf`, `figs` (no number) |
| **Edge cases** | Sentence-initial capitalization |
| **FP risks** | Low |
| **Target resolution** | Same as 4.4 |
| **Cross-module?** | Rare |

### 4.6 — `LISTING_REF_NUMBERED_V1` — Numbered listing

| Field | Value |
|---|---|
| **NER label** | `LISTING_REF` |
| **Regex** | `\bListing\s+(?P<num>\d+(?:[\.\-]\d+){0,4})\b` |
| **Confidence** | 0.96 |
| **Examples** | `Listing 16.2.5`, `Listing 1`, `Listing 16.1.1`, `Listing 14-1`, `Listing 16.2.5.1` |
| **Negative** | `Listing of products` |
| **Edge cases** | CSR Appendix 16.2 typically organized as Listings |
| **FP risks** | Low |
| **Target resolution** | CSR data listings (Appendix 16.2.x) |
| **Cross-module?** | Yes (Module 5 CSR appendix) |

### 4.7 — `LISTING_REF_INLINE_V1` — "see Listing X"

| Field | Value |
|---|---|
| **NER label** | `LISTING_REF` |
| **Regex** | `(?:see|shown in|presented in|listed in)\s+Listing\s+(?P<num>\d+(?:[\.\-]\d+){0,4})` |
| **Confidence** | 0.97 |
| **Examples** | `see Listing 16.2.5`, `shown in Listing 16.1.1`, `presented in Listing 14-1`, `listed in Listing 16.2.7`, `see Listing 16.2.5.1` |
| **Negative** | `see Table 16.2.5` |
| **Edge cases** | Dedupe with 4.6 |
| **FP risks** | Low |
| **Target resolution** | Same as 4.6 |
| **Cross-module?** | Yes |

---

## 5. CTD Leaf Path References

### 5.1 — `CTD_LEAF_PATH_V1` — Standard eCTD leaf path

| Field | Value |
|---|---|
| **NER label** | `CTD_LEAF` |
| **Regex** | `\bm(?P<mod>[1-5])(?:/(?P<subpath>[a-z0-9\-]+(?:/[a-z0-9\-]+)*))?\b` |
| **Confidence** | 0.94 |
| **Examples** | `m5/53-clin-stud-rep/5331/study-001`, `m2/27-clin-summary/2731-bio`, `m3/32-body-data/32p-drug-prod`, `m4/42-stud-rep`, `m1/us/cover` |
| **Negative** | `M5` (no module path), `m6` (no such module), `M5/Section/X` (uppercase + wrong format) |
| **Edge cases** | Trailing slash; URL-encoded chars; mixed case (some tools emit `M5/53-...`) — normalize to lowercase |
| **FP risks** | Medium — could match arbitrary path-like strings. Mitigation: leading `\bm[1-5]/` is distinctive |
| **Target resolution** | Direct lookup in eCTD backbone graph (Module 5+) |
| **Cross-module?** | Always (explicit module path) |

### 5.2 — `CTD_LEAF_MODULE_V1` — Module-number reference

| Field | Value |
|---|---|
| **NER label** | `CTD_LEAF` |
| **Regex** | `\bModule\s+(?P<mod>[1-5])(?:\.(?P<sub>\d+(?:\.\d+){0,3}))?\b` |
| **Confidence** | 0.95 |
| **Examples** | `Module 5`, `Module 2.5.3`, `Module 5.3.1`, `Module 3.2.P.5`, `Module 1.3.1` |
| **Negative** | `Module 6` (invalid), `Modules 2 and 3` (multi — v2) |
| **Edge cases** | Capitalization variants ("module 5", "MODULE 5") — normalize |
| **FP risks** | Low |
| **Target resolution** | Map module-number → backbone leaf via SOP rules |
| **Cross-module?** | Always (explicit) |

### 5.3 — `CTD_LEAF_M_DOT_V1` — "M5.3.1" shorthand

| Field | Value |
|---|---|
| **NER label** | `CTD_LEAF` |
| **Regex** | `\bM(?P<mod>[1-5])\.(?P<sub>\d+(?:\.\d+){0,3})\b` |
| **Confidence** | 0.93 |
| **Examples** | `M2.5.3`, `M5.3.1`, `M3.2.P.5`, `M5.3.5.2`, `M2.7.4` |
| **Negative** | `M6.1` (invalid), `M5` (no sub) |
| **Edge cases** | Mixed with parenthesized variants `(M5.3.1)` |
| **FP risks** | Medium — could match e.g. weapon designations (M1.1), military equipment refs in toxicology refs |
| **Target resolution** | Same as 5.2 |
| **Cross-module?** | Always |

### 5.4 — `CTD_LEAF_CTD_PREFIX_V1` — "CTD Section X" reference

| Field | Value |
|---|---|
| **NER label** | `CTD_LEAF` |
| **Regex** | `\b(?:CTD\s+)?Section\s+(?P<mod>[1-5])\.(?P<sub>\d+(?:\.\d+){0,3})\b` |
| **Confidence** | 0.90 |
| **Examples** | `CTD Section 2.5.3`, `CTD Section 5.3.1`, `Section 3.2.P.5` (with CTD context), `CTD Section 2.7.4`, `CTD Section 1.3.1` |
| **Negative** | `Section 2.5` (insufficient depth — falls to SECTION_REF) |
| **Edge cases** | Disambiguate vs SECTION_REF_LABELED via leading "CTD" or full 3+ level depth |
| **FP risks** | Medium — high overlap with SECTION_REF; resolve via highest-confidence wins |
| **Target resolution** | Same as 5.2 |
| **Cross-module?** | Often |

---

## 6. Cross-Module Narrative Pointers

### 6.1 — `MODULE_PTR_REFER_V1` — "refer to Module X"

| Field | Value |
|---|---|
| **NER label** | `CTD_LEAF` |
| **Regex** | `(?:refer to|see|presented in|discussed in)\s+Module\s+(?P<mod>[1-5])(?:\.(?P<sub>\d+(?:\.\d+){0,3}))?` |
| **Confidence** | 0.97 |
| **Examples** | `refer to Module 5.3.1`, `see Module 2.7.4`, `presented in Module 3.2.P.5`, `discussed in Module 5`, `see Module 1.3.1` |
| **Negative** | `refer to the protocol` |
| **Edge cases** | Dedup with 5.2 |
| **FP risks** | Low |
| **Target resolution** | Same as 5.2 |
| **Cross-module?** | Always |

### 6.2 — `MODULE_PTR_CSR_V1` — CSR (Clinical Study Report) reference

| Field | Value |
|---|---|
| **NER label** | `CTD_LEAF` |
| **Regex** | `\b(?:CSR|Clinical Study Report)\s+(?:for\s+)?(?P<study>[A-Z]{2,5}-\d{4}-\d{3,4})` |
| **Confidence** | 0.96 |
| **Examples** | `CSR for SP-2024-001`, `Clinical Study Report SUNP-2023-042`, `CSR SP-2024-001`, `Clinical Study Report for ABC-2022-007`, `CSR XYZ-2024-9999` |
| **Negative** | `CSR system`, `Clinical Study Report template` |
| **Edge cases** | Combine with STUDY_ID match; emit single Reference with both labels |
| **FP risks** | Low |
| **Target resolution** | Resolve to Module 5.3.x CSR leaf for the given study |
| **Cross-module?** | Always (points to M5) |

### 6.3 — `MODULE_PTR_BACKBONE_V1` — Backbone file mention

| Field | Value |
|---|---|
| **NER label** | `CTD_LEAF` |
| **Regex** | `\b(?:index\.xml|backbone|leaf-id)\s*[=:]\s*[\"\']?(?P<value>[a-z0-9\-]+)[\"\']?` |
| **Confidence** | 0.88 |
| **Examples** | `leaf-id="leaf-12345"`, `index.xml: m5/53-clin-stud-rep`, `backbone: m2/27`, `leaf-id=stud-001`, `index.xml = m1/us/cover` |
| **Negative** | `backbone of the study` |
| **Edge cases** | Rare in narrative; usually in technical appendices or QC docs |
| **FP risks** | Low |
| **Target resolution** | Direct backbone lookup |
| **Cross-module?** | Yes |

---

## 7. External References

### 7.1 — `EXT_REF_URL_V1` — Full URL

| Field | Value |
|---|---|
| **NER label** | `EXT_URL` |
| **Regex** | `https?://[^\s\)\]\>]+` |
| **Confidence** | 0.99 |
| **Examples** | `https://www.fda.gov/...`, `https://clinicaltrials.gov/study/NCT01234567`, `https://ema.europa.eu/...`, `http://example.com/doc.pdf`, `https://doi.org/10.1234/abc` |
| **Negative** | `www.fda.gov` (no scheme — covered by 7.2) |
| **Edge cases** | Trailing punctuation (`.`, `,`, `)`); URL-encoded characters; very long URLs that wrap |
| **FP risks** | Very low |
| **Target resolution** | External hyperlink; no internal resolution |
| **Cross-module?** | N/A |

### 7.2 — `EXT_REF_DOI_V1` — DOI reference

| Field | Value |
|---|---|
| **NER label** | `EXT_URL` |
| **Regex** | `\b10\.\d{4,9}/[\-._;()/:A-Za-z0-9]+\b` |
| **Confidence** | 0.95 |
| **Examples** | `10.1234/abc.5678`, `10.1038/nature12373`, `10.1056/NEJMoa1234567`, `10.1016/S0140-6736(20)30183-5`, `10.1001/jama.2023.12345` |
| **Negative** | `10.5` (insufficient structure) |
| **Edge cases** | DOIs containing parentheses, slashes; URL-prefixed (`https://doi.org/10....`) — capture without prefix |
| **FP risks** | Low |
| **Target resolution** | Prepend `https://doi.org/` to form external link |
| **Cross-module?** | N/A |

### 7.3 — `EXT_REF_GUIDELINE_V1` — Regulatory guideline reference

| Field | Value |
|---|---|
| **NER label** | `EXT_URL` |
| **Regex** | `\b(?:ICH|FDA|EMA|CHMP|CPMP)\s+(?P<code>[A-Z]\d+(?:\([A-Z0-9]+\))?(?:\s*R\d+)?)` |
| **Confidence** | 0.91 |
| **Examples** | `ICH E6(R2)`, `ICH M4`, `FDA 21 CFR 314.50`, `EMA CHMP/QWP/12345/2023`, `CHMP/EWP/9147/2008` |
| **Negative** | `ICH meeting`, `FDA staff` |
| **Edge cases** | Many guideline citation formats; build a lookup table `data/guidelines.yaml` mapping code → official URL |
| **FP risks** | Medium — restrict to documents with `ICH/FDA/EMA` prefix |
| **Target resolution** | Lookup in `data/guidelines.yaml`; fallback to web search (Phase 3) |
| **Cross-module?** | N/A |

---

## 8. Conflict Resolution Rules

When two patterns match overlapping spans, `detection/entity_extractor.py` applies these rules in order:

1. **Higher confidence wins** — `STUDY_ID_NCT_V1` (0.99) beats `STUDY_ID_SPONSOR_V1` (0.95) if both fire.
2. **More specific pattern wins ties** — `MODULE_PTR_REFER_V1` ("refer to Module 5.3.1") beats `SECTION_REF_DOTTED_V1` ("5.3.1") even though both match the number.
3. **Labeled patterns beat unlabeled** — `SECTION_REF_LABELED_V1` ("Section 2.5") beats `SECTION_REF_DOTTED_V1` ("2.5") for the same span.
4. **CTD_LEAF beats SECTION_REF** when 3+ levels of depth and module-1 prefix.
5. **Reject low-confidence orphans** — `SECTION_REF_DOTTED_V1` requires context cue within ±30 chars OR drops to "candidate, needs LLM" queue.

---

## 9. False-Positive Mitigation Strategy

| Risk class | Mitigation |
|---|---|
| **Number-looking-like-section** | Context window scan (±30 chars) for cue words ("Section", "see", "§"); reject if no cue and pattern confidence < 0.7 |
| **Date matched as Study ID** | Validate sponsor prefix against `data/known_sponsors.yaml` (built from W1.3 workshop) |
| **Version number matched as section** | Reject if pattern is on a heading/title (file metadata) or appears next to "v" / "version" / "rev" |
| **Hyperlink already exists** | Skip injection if `parser.has_link_at(location)` returns True |
| **Cross-pattern overlap** | Conflict resolution (§8) |

---

## 10. Open Questions for Stakeholder Workshop (Day 3)

To finalize this catalog with Maikel Bouman's publishing team:

1. **Sponsor prefix list** — what's the authoritative list for SunPharma? (Drives `data/known_sponsors.yaml`)
2. **Legacy ID formats** — are there pre-2020 IDs that follow different conventions? (Add as `*_DEPRECATED_V1` patterns; flag in anomaly detector)
3. **Cross-reference style guide** — does the SOP mandate `Section 2.5.3` over `§2.5.3` or are both equivalent?
4. **Annex vs Appendix** — are these synonymous in SunPharma's vocabulary, or do they denote different document classes?
5. **Module 1 regional variants** — which regions (FDA, EMA, PMDA, Health Canada, ANVISA) does the POC need to cover in Phase 1?
6. **Listing numbering** — confirm `16.2.x` is the only valid Listing path or whether other CSR appendices contain listings?
7. **External link policy** — should DOIs/URLs always be linked, never linked (per HA submission rules), or configurable per region?
8. **Color convention** — what RGB range constitutes "blue text" indicating a missing link? (Drives anomaly detection threshold)

---

## 11. Versioning & Change Control

- This catalog is **versioned in git**; every change requires:
  - PR review by 1 engineer + 1 publishing SME
  - Updated unit tests in `tests/unit/detection/test_regex_patterns.py`
  - Updated benchmark scores in `scripts/benchmark.py` output
- Pattern IDs are **stable** — never rename; deprecate via `_DEPRECATED_V1` suffix and add successor.
- The catalog feeds `detection/regex_patterns.py::default_registry()` directly; engineer keeps them in sync.
