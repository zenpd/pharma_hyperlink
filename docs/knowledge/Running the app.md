# Running the app

Ops — how to run the backend, dashboard, optional services, and tests. Source: `README.md`.

## How it works
- Backend (FastAPI, :8000): `python -m uvicorn hyperlink_engine.api.app:app --reload --port 8000` from `backend/`.
- Frontend (React/Vite, :5174): `npm run dev` from `frontend/`.
- Optional services: `docker compose -f infra/docker/docker-compose.yml up -d redis neo4j ollama` (then `ollama pull llama3.2:3b`).
- Headless batch: `python -m hyperlink_engine.workers.batch_runner --input … --output …`; tests: `python -m pytest`.

## Gotchas
- None of Redis / Neo4j / Ollama are required for a basic run. Config is via `HYPERLINK_*` env vars or `backend/.env`; auth is OFF by default.

## Related
[[Workers and queue]] · [[Auth and compliance]] · [[Orchestration and agents]] · [[_Home]]
