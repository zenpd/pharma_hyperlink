# Hyperlink Engine — top-level monorepo task runner
#
# Python lives in backend/ (shared venv at ./.venv), React in frontend/, infra in infra/.
# Activate the venv first:  .venv\Scripts\Activate.ps1   (Windows)
#                           source .venv/bin/activate     (POSIX)
# On Windows without GNU Make, run the underlying commands from README.md directly.

.PHONY: help install test test-fast lint format typecheck backend frontend frontend-build \
        synthetic services-up services-down clean

help:
	@echo "Hyperlink Engine — make targets (activate ./.venv first)"
	@echo ""
	@echo "  install        editable install of backend[all] + pre-commit hooks"
	@echo "  test           backend pytest (full suite + coverage gate)"
	@echo "  test-fast      backend pytest (no slow/integration, no coverage)"
	@echo "  lint           ruff + black --check + mypy (backend)"
	@echo "  format         black + ruff --fix (backend)"
	@echo "  typecheck      mypy strict (backend)"
	@echo "  backend        run FastAPI on :8000"
	@echo "  frontend       run Vite dev server on :5174"
	@echo "  frontend-build build the React app (tsc + vite build)"
	@echo "  synthetic      generate a 20-doc synthetic dossier"
	@echo "  services-up    docker compose up (Ollama, Redis, Neo4j) via infra/docker"
	@echo "  services-down  docker compose down"
	@echo "  clean          remove caches + build artifacts"

install:
	cd backend && python -m pip install -e ".[all]"
	python -m pre_commit install

test:
	cd backend && python -m pytest

test-fast:
	cd backend && python -m pytest -m "not slow and not integration" --no-cov

lint:
	cd backend && python -m ruff check src tests scripts
	cd backend && python -m black --check src tests scripts
	cd backend && python -m mypy src/hyperlink_engine

format:
	cd backend && python -m black src tests scripts
	cd backend && python -m ruff check --fix src tests scripts

typecheck:
	cd backend && python -m mypy src/hyperlink_engine

backend:
	cd backend && python -m uvicorn hyperlink_engine.api.app:app --reload --port 8000 --host 0.0.0.0

frontend:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

synthetic:
	cd backend && python -m scripts.bootstrap_synthetic_data --out data/synthetic --docs 20

services-up:
	docker compose -f infra/docker/docker-compose.yml up -d

services-down:
	docker compose -f infra/docker/docker-compose.yml down

clean:
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache backend/.hypothesis \
	       backend/coverage_html backend/output
