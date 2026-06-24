# Ingestion layer

Layer 1 — load source documents and the eCTD backbone into normalized records.

## How it works
- Word loader `backend/src/hyperlink_engine/core/ingestion/docx_loader.py`; PDF loader `core/ingestion/pdf_loader.py`.
- eCTD `index.xml` → `BackboneSnapshot` of leaves: `core/ingestion/ectd_loader.py` (see [[eCTD backbone and graph]]).
- Dossplorer metadata/sequence (mock + live client): `core/ingestion/dossplorer_client.py`.
- Pipeline entry `node_load_dossier` in `orchestration/nodes.py` hashes each file (sha256) and records size/suffix into `ingest_records`.

## Gotchas
- Image-only / scanned PDFs have no extractable text → 0 detections (the engine does not OCR).

## Related
[[Parsing layer]] · [[eCTD backbone and graph]] · [[Orchestration and agents]] · [[_Home]]
