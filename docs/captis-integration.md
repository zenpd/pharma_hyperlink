# CAPTIS™ AI Integration — Phase 3 W11.3

> Lightweight interface for sharing NER models + training data between the
> hyperlink-engine and Celegence's CAPTIS™ regulatory-AI platform.

CAPTIS is Celegence's broader regulatory-AI portfolio.  This document
records the seams the hyperlink-engine exposes so that CAPTIS can:

1. Re-use the hyperlink-engine's pattern + NER training data.
2. Receive trained spaCy NER model artefacts.
3. Submit improved NER models back into the engine.

Both directions stay **on-prem** — no model artefact leaves the SunPharma
VPC / Celegence-managed infra.

---

## 1. What we share

### 1.1 — Training data

The engine collects two kinds of NER training inputs:

| Source                         | Path                                | Format         | Volume (POC) |
|---------------------------------|-------------------------------------|----------------|--------------|
| Manually-labeled gold set       | `data/training/gold/*.jsonl`        | spaCy v3 JSONL | 500 refs     |
| Synthetic generator output      | `data/training/synthetic/*.jsonl`   | spaCy v3 JSONL | 5 000 refs   |
| Auto-labelled high-confidence regex hits | `data/training/auto/*.jsonl` | spaCy v3 JSONL | grows per run |

Each JSONL line is a spaCy `Example` ready for `nlp.update()`.  The
schema is:

```json
{
  "text": "See Section 5.3.1 for the CSR",
  "ents": [
    {"start": 4, "end": 17, "label": "SECTION_REF"},
    {"start": 26, "end": 29, "label": "CTD_LEAF"}
  ]
}
```

CAPTIS consumes these files read-only.

### 1.2 — Model artefacts

The trained spaCy model lives under `models/ner_v<N>/` (gitignored;
tracked via Git LFS or DVC in Phase 4).  Each release ships a tag
`ner-v<N>` and a meta file describing:

```yaml
# models/ner_v1/meta.yaml
version: "1.0"
trained_on: "2026-05-27"
training_corpus_size: 5500
gold_corpus_size: 500
labels:
  - STUDY_ID
  - SECTION_REF
  - APPENDIX_REF
  - TABLE_REF
  - FIGURE_REF
  - CTD_LEAF
metrics:
  precision: 0.928
  recall: 0.901
  f1: 0.914
```

CAPTIS reads `meta.yaml` to decide whether to adopt the model into its
own pipeline.

---

## 2. What CAPTIS sends back

CAPTIS may publish an improved model that benefits the hyperlink-engine:

* New entity labels (e.g., `MEDICAL_TERM`, `ICH_GUIDELINE_REF`).
* Better recall on existing labels.
* Multilingual support.

The engine accepts CAPTIS-trained models via:

```bash
poetry run python -m scripts.adopt_captis_model \
    --model-dir /path/to/captis/ner_v<N> \
    --meta /path/to/captis/ner_v<N>/meta.yaml
```

The script:
1. Validates `meta.yaml` against the schema above.
2. Confirms F1 ≥ 0.85 (engine acceptance gate).
3. Copies the model directory under `models/ner_captis_v<N>/`.
4. Updates `config/settings.py::ner_model_path` to point at it.
5. Logs an `ADR-0010-captis-model-adoption.md` describing the swap.

---

## 3. Governance

| Topic                   | Policy                                                          |
|-------------------------|------------------------------------------------------------------|
| Data residency          | Training data + models never leave SunPharma VPC / Celegence infra. |
| Model provenance        | Every adopted model carries a `meta.yaml` recording its training set, metrics, and trainer name. |
| Rollback                | The previous model directory is kept until the next phase tag — operators can `cp models/ner_vN-1 models/ner_active`. |
| Audit trail             | Every model swap emits an `audit/trail.py::model_swapped` event. |
| Versioning              | `ner_v<N>` directories are append-only.  Never overwrite. |

---

## 4. Interfaces

### Read-side (engine → CAPTIS)
* File system: `data/training/`, `models/ner_v*/meta.yaml`
* Optional: `GET /api/training-data/manifest` exposed by `dashboard/api.py` lists available JSONL bundles for CAPTIS to pull.

### Write-side (CAPTIS → engine)
* File system: drop a directory under `/var/captis-drop/` watched by the
  adoption script.
* Optional: `POST /api/models/adopt` endpoint (Phase 4) that triggers the
  adoption script with the dropped directory.

Both directions are POSIX file operations in the POC; the Phase 4 milestone
introduces a thin REST contract for richer orchestration.

---

## 5. Future work (Phase 4+)

* Live training-data exchange via a CAPTIS-hosted feature store.
* Shared embeddings library so both projects use the same vectoriser.
* Federated-learning hook for cross-tenant model improvement.
* Model-card automation that emits regulatory-grade documentation per
  swap (per FDA's *Predetermined Change Control Plan* guidance).
