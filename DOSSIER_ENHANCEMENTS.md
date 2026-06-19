# Dossier Content Enhancements — Summary

## Overview
All three synthetic dossier datasets have been enhanced with **actual table content** and **detailed section text** replacing placeholder references. This improves the demo experience and makes the documents more realistic for testing the hyperlink detection and navigation features.

---

## 1. CSR Dossier (`data/synthetic/csr_dossier/`)

### Structure
- **4 study folders**: SP-2026-001 through SP-2026-004 (Phase 1 PK, Phase 2a, Phase 2b, Phase 3)
- **Per study**: CSR body document + Protocol + SAP + Listings documents
- **Total**: 16 documents across 4 studies

### Enhancements

#### CSR Body Documents
Each CSR now includes **4 real data tables**:

1. **Table 14.1.1.1 — Subject Demographics (Intent-to-Treat Population)**
   - Columns: Characteristic, Solzumab 200mg, Solzumab 100mg, Placebo, Total
   - Rows: N enrolled, Age, Gender distribution, Race
   - Shows realistic demographic distributions

2. **Table 14.2.1.1 — Primary Efficacy Summary (ITT Population)**
   - Columns: Treatment Arm, N, Responders (%), 95% CI, p-value
   - Rows: Each treatment arm with statistical results
   - Demonstrates efficacy comparisons

3. **Table 14.3.1.2 — Treatment-Emergent Adverse Events by System Organ Class**
   - Columns: System Organ Class, Solzumab (n=299), Placebo (n=148), Total (n=447)
   - Rows: Any TEAE, Gastrointestinal disorders, Infections, Nervous system, Serious AEs
   - Real safety incidence percentages

4. **Table 14.3.1.3 — Treatment-Related Adverse Events (Safety Population)**
   - Columns: Event, Solzumab (n=299), Placebo (n=148)
   - Rows: Related TEAE, Mild-Moderate, Severe, Leading to discontinuation
   - Severity distribution data

#### Protocol Documents
New detailed sections and table:
- **Section 6.1.1 — Study Design Parameters** (Table 6.1.1)
  - Type, Duration, Primary/Secondary Endpoints, Target N
- **Section 9.5.1 — Safety Assessment Schedule** (Table 9.5.1)
  - Shows assessment timing: Screening, Baseline, Weekly, End of Study

#### SAP Documents
New analysis methods with table:
- **Section 4.2.1 — Definition of Analysis Populations** (Table 4.2.1)
  - ITT, Per-Protocol, Safety, PK-evaluable populations
- **Section 5.1.1 — Statistical Analysis Methods** (Table 5.1.1)
  - Endpoint, Population, Method, Significance Level for each analysis

#### Listings Documents
Enhanced structure:
- **Section 16.1**: Baseline and Demographics Listings
- **Section 16.2**: Subject Efficacy Listings with sample data table
- **Section 16.3**: Subject Safety Listings

---

## 2. NER Dossier (`data/synthetic/ner_dossier/`)

### Structure
- **3 documents**: Protocol, CSR, SAP for study AMD-2025 series
- **Location**: `m5/53-clin-stud-rep/` (eCTD Module 5 Clinical Study Reports)

### Enhancements

#### Protocol Document (`protocol-amd-2025-001.docx`)
New table:
- **Table 5.1 — Planned Dose Regimens and Cohorts**
  - Columns: Cohort, Dose (mg), Formulation, N Subjects, Duration (days)
  - Rows: 3 cohorts (50mg, 100mg, Placebo)
  - Sample sizes and treatment durations

#### CSR Document (`csr-amd-2025-002.docx`)
Two data tables:
1. **Table 6.3 — Demographics and Baseline Characteristics (Safety Population)**
   - Columns: Characteristic, Amidazetil 50mg, Amidazetil 100mg, Placebo
   - Rows: Age, Gender, Weight, Child-Pugh classification
   - Shows baseline comparability across arms

2. **Table 7.2 — Summary of Treatment-Emergent Adverse Events**
   - Columns: System Organ Class, Amidazetil (N=64), Placebo (N=12), Total (N=76)
   - Rows: TEAE incidence, Gastrointestinal, Nervous system, Serious AEs
   - Safety summary with percentages

#### SAP Document (`sap-amd-2025-003.docx`)
Analysis framework table:
- **Table 7.2 — Statistical Analysis Methods and Model Parameters**
  - Columns: Analysis, Method, Population, Primary Endpoint
  - Rows: Primary PK, Secondary PK, Safety, Efficacy analyses
  - Shows statistical approaches for each analysis type

### NER Pattern Visibility
Documents continue to embed NER-exclusive patterns alongside standard regex patterns:
- **NER-only**: Form FDA 1572, Site US-001/007/US-014, Batch No./Lot, MedDRA codes, Sequence refs
- **Regex-detected**: Study IDs, Section numbers, Table/Figure/Listing/Appendix refs
- **Result**: Detection Trace shows both regex and NER hits for comprehensive coverage testing

---

## 3. Demo Dossier (`data/synthetic/demo_dossier/`)

### Structure
- **4 CSR documents**: Phase 1, 2a, 2b, and 3 studies (SP-2026-001 through SP-2026-004)
- **12 cross-document references**: 3 per document linking across all studies
- **Comprehensive tables**: Multiple data tables per document

### Enhancements Already Present (Regenerated)
Each Phase CSR contains:
- **Demographics table**: Subject characteristics at baseline
- **PK table** (Phase 1): Pharmacokinetic parameters (Cmax, AUC, half-life, Clearance)
- **Efficacy table**: Primary endpoint response rates with 95% CI and p-values
- **Safety table**: Treatment-emergent adverse event incidence by system organ class
- **ADA incidence** (Phase 1): Anti-drug antibody development rates

### Cross-Document Links
12 realistic cross-reference examples:
1. **SP-2026-001 → SP-2026-002 Section 2.5**: Safety comparison between healthy volunteers and patients
2. **SP-2026-001 → SP-2026-003 Appendix 16.1.1**: PK listings reused in dose-finding
3. **SP-2026-001 → SP-2026-004 Table 14.2.1.1**: Integrated demographics across all studies
4. **SP-2026-002 → SP-2026-001 Section 5.3.1**: PK profile reference
5. **SP-2026-002 → SP-2026-003 Listing 16.2.5**: AE reconciliation
6. **SP-2026-002 → SP-2026-004 Section 5.3.5**: Pivotal efficacy results
7-12. Similar patterns for SP-2026-003 and SP-2026-004 cross-references

---

## Table Statistics

| Dossier | Documents | Total Tables | Avg Tables/Doc |
|---------|-----------|--------------|-----------------|
| CSR     | 16        | 64+          | 4               |
| NER     | 3         | 6            | 2               |
| Demo    | 4         | 12+          | 3               |

---

## Implementation Details

### Generator Script Enhancements

#### `generate_csr_dossier.py`
- **Enhanced functions**: `_csr_body()`, `_protocol()`, `_sap()`, `_listings()`
- **Table helper**: Existing `_table()` function used for table generation
- **Content builders**: Each section now includes full narrative + embedded tables
- **Cross-references**: Intra-doc and cross-doc references with section/table numbers

#### `generate_ner_dossier.py`
- **Helper added**: `_table()` function to support table generation (was text-only before)
- **Document generator modified**: `_make_doc()` now handles both text sections and table blocks
- **Content renamed**: `PROTOCOL_SECTIONS` → `PROTOCOL_CONTENT`, etc. (now list of mixed types)
- **NER patterns**: Embedded throughout sections alongside standard regex patterns

#### `generate_demo_dossier.py`
- **No changes required**: Already had comprehensive table support and detailed content
- **Regenerated**: To ensure consistency and verify table content is present

---

## Benefits for Demo/Testing

✅ **Hyperlink Resolution**: Tables are now real targets for hyperlinks to point to, not just references
✅ **Section Depth**: Subsections (e.g., 2.5 vs 2.5.3) can be tested with full content
✅ **Realistic Documents**: Industry-standard format for regulatory CSRs and SAPs
✅ **NER Coverage**: NER-exclusive patterns appear in context within document sections
✅ **Cross-Document Navigation**: Links navigate to actual table rows/sections with content
✅ **Snippet Preview**: Hyperlink snippets show real table captions and section headings
✅ **Real-Grid Rendering**: tables now render as bordered HTML grids in the Run Compare panels **and** the Reference View (backend `_read_docx_blocks` emits structured table blocks), instead of flattened `Cell | Cell | Cell` text

---

## How to Regenerate

If you need to regenerate any dossier:

```bash
# CSR Dossier (4 studies × 4 documents = 16 docs)
cd backend
python scripts/generate_csr_dossier.py --out ../data/synthetic/csr_dossier

# NER Dossier (3 documents with NER-exclusive patterns)
python scripts/generate_ner_dossier.py --out ../data/synthetic/ner_dossier

# Demo Dossier (4 Phase studies with 12 cross-refs)
python scripts/generate_demo_dossier.py --out ../data/synthetic/demo_dossier
```

All scripts require `python-docx` to be installed (included in `pyproject.toml` dependencies).

---

## Next Steps

1. **Upload enhanced dossiers** via Pipeline screen to test hyperlink detection
2. **Verify Detection Trace** shows tables are detected and resolved correctly
3. **Test Cross-Document Navigation**: Click links and verify scroll-to-table behavior
4. **Run Inline Editing**: Edit link targets in Run Compare and verify persistence
5. **Check NER Triggers**: Verify NER detection layer is reached for NER-exclusive patterns
