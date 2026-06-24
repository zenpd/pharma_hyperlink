# Key files

Concept → real source file map (paths under `backend/src/hyperlink_engine/` unless noted).

## Map
- Settings / config → `config/settings.py`
- Data models → `models.py`
- Regex catalog → `core/detection/regex_patterns.py`
- NER / GLiNER / LLM → `core/detection/ner_model.py`, `core/detection/gliner_refs.py`, `core/detection/llm_disambiguator.py`
- Detection orchestrator → `core/detection/entity_extractor.py`
- Cross-doc resolve → `orchestration/nodes.py` (`_resolve_one`, `_pick_sibling`)
- Anchor / citation index → `core/injection/anchor_index.py`, `core/injection/ref_index.py`
- Word / PDF writers → `core/injection/docx_linker.py`, `core/injection/pdf_linker.py`
- eCTD loader / leaf graph → `core/ingestion/ectd_loader.py`, `core/graph/leaf_resolver.py`, `core/graph/backbone_graph.py`
- Pipeline nodes / runner / state / graph → `orchestration/nodes.py`, `orchestration/runner.py`, `orchestration/state.py`, `orchestration/graph.py`
- Agents → `orchestration/agents/registry.py`
- Workers → `workers/celery_app.py`, `workers/tasks.py`, `workers/batch_runner.py`
- API → `api/app.py`; Audit → `audit/trail.py`
- Frontend shell / client → `frontend/src/App.tsx`, `frontend/src/api.ts`
- Infra / ops → `infra/docker/docker-compose.yml`, `Makefile`, `README.md`

## Related
[[_Home]] · [[Detection cascade]] · [[Resolution and anchoring]] · [[Orchestration and agents]]
