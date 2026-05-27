# eCTD Regional Variants — Phase 3 W10.2

> How the engine handles the four major eCTD regional sub-backbones
> and the associated sequence-numbering conventions.

The ICH eCTD spec defines a shared **Module 2–5** backbone, but **Module 1**
is region-specific. Each Health Authority publishes its own
`*-regional.xml` schema. The engine merges these into a single
:class:`models.BackboneSnapshot` (per W5.1) and applies region-aware
rules via the HA rule engine (W10.1).

---

## 1. Region map

| Region code | Authority         | Regional file               | Schema |
|-------------|-------------------|------------------------------|--------|
| `us`        | FDA (CDER / CBER) | `m1/us/us-regional.xml`      | FDA M1 v3.3 |
| `eu`        | EMA / CMDh        | `m1/eu/eu-regional.xml`      | EU M1 v3.0.4 / v3.1 |
| `jp`        | PMDA / MHLW       | `m1/jp/jp-regional.xml`      | JP M1 v1.2 |
| `ca`        | Health Canada     | `m1/ca/ca-regional.xml`      | CA M1 v2.4 |

The loader (`ingestion/ectd_loader.py::load_backbone_with_regional`) accepts a
list of regional roots via the `extra_regional` argument and merges them
into the canonical snapshot. Leaves with the same `leaf_id` from
different regional files are de-duplicated (last-write-wins, with a
`region_source` tag preserved for traceability).

---

## 2. Sequence numbering conventions

eCTD sequences are 4-digit zero-padded integers (`0000` … `9999`). The
**semantic meaning** of those numbers differs by region:

| Region | First sequence | Amendment convention | Reset on cycle change |
|--------|----------------|----------------------|------------------------|
| `us`   | `0000` (initial) | `0001`+ incremental | No (FDA mandates monotonic) |
| `eu`   | `0000` (initial) | Use `s-XXXX` for variations | Yes (per procedure type) |
| `jp`   | `0001` (initial) | Sequential, no gaps | No |
| `ca`   | `0000` (initial) | Same as FDA | No |

The :class:`graph.sequence_history.SequenceTimeline` is region-agnostic —
it tracks any path's history regardless of how the region numbers its
sequences. The `latest_for_study()` helper accepts a `region` filter for
EU dossiers where multiple procedure types may run in parallel.

---

## 3. Filename conventions

Each region imposes constraints on leaf filenames inside `m1`:

| Region | Case            | Separator | Allowed | Max length |
|--------|------------------|-----------|---------|------------|
| `us`   | lowercase        | hyphen `-`  | `[a-z0-9\-]` | 64 |
| `eu`   | lowercase        | hyphen `-`  | `[a-z0-9\-]` (no underscores at start) | 64 |
| `jp`   | lowercase + JP   | hyphen `-`  | `[a-z0-9\-]` + JIS-X-0208 (Shift-JIS round-trip required) | 128 |
| `ca`   | lowercase        | hyphen `-`  | `[a-z0-9\-]` | 64 |

The HA rule engine (`config/ha_rules.yaml`) encodes these as:
- `EMA_ESPRE_NAMING` — ESPRE filename rules
- `FDA_LEAF_TITLE_LENGTH`, `EMA_LEAF_TITLE_LENGTH`, `PMDA_LEAF_TITLE_LENGTH` — per-region title length caps
- `PMDA_SJIS_TITLE` — Shift-JIS round-trip check for JP

---

## 4. PDF/A conformance per region

| Region | Required PDF/A flavour                                    |
|--------|------------------------------------------------------------|
| `us`   | PDF/A-2b (FDA Guidance § 4.1)                              |
| `eu`   | PDF/A-1b OR PDF/A-2b (EMA accepts both)                    |
| `jp`   | PDF/A-1b preferred; PDF/A-2b acceptable                    |
| `ca`   | PDF/A-2b (Health Canada follows FDA)                       |

Enforced by `pdf_a_2b_compliance` / `pdf_a_1b_or_2b_compliance` validators
in `validation/ha_rule_engine.py`. PDF/A detection itself is delegated to
the PDF loader (`pdf_loader.py` reads the `/MarkInfo` and `/Metadata` XMP
sections via PyMuPDF; richer validation arrives in Phase 4 with a real
PDF/A verifier such as `verapdf`).

---

## 5. Bookmark-depth requirements

| Region | Minimum bookmark depth | Notes |
|--------|------------------------|-------|
| `us`   | 3 (FDA strict)         | Applies to all renditions in M2–M5 |
| `eu`   | 2                      | Less strict; warning only |
| `jp`   | 3 (for CSRs)           | PMDA requires this for clinical study reports |
| `ca`   | 3                      | Health Canada follows FDA |

Validated by the `fda_bookmark_depth_min_3`, `ema_bookmark_depth_min_2`,
`pmda_bookmark_depth_min_3`, and `hc_bookmark_depth_min_3` rules.

---

## 6. Cross-region edge cases

* **Mixed-region dossiers.** A single product file may carry FDA, EMA, and
  PMDA backbones simultaneously. The engine handles this by loading each
  regional file separately and tagging every leaf with its source. The
  HA rule engine then runs the appropriate rule set per region — a
  rule with `region: us` only fires on leaves whose `region_source` is
  `us-regional.xml`.
* **Mutual-recognition variations (EU).** When a single product is
  submitted via mutual-recognition or decentralised procedure, the EU
  backbone has multiple `s-XXXX` series. The :class:`SequenceTimeline`
  picks the highest series and within that the highest sequence.
* **Bridging studies (PMDA).** Japanese bridging-study submissions reuse
  CSR leaves from a prior FDA submission. The leaf resolver follows the
  cross-region link via `region_source` so the cross-module integrity
  check correctly identifies the original FDA leaf as the target.

---

## 7. Test fixtures

Synthetic multi-region dossiers live under `data/synthetic/multi_region/`
once generated by `scripts/bootstrap_synthetic_data.py --multi-region`.
The Phase 2 acceptance corpus is US-only; Phase 3 acceptance adds EU and
JP variants when the bootstrap is run with `--multi-region`.
