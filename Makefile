# Hyperlink Engine — developer convenience targets
#
# Use `make help` to see available commands.
# On Windows: install GNU Make (https://gnuwin32.sourceforge.net/packages/make.htm)
# or run the equivalent commands manually from README.md.

.PHONY: help install test test-fast lint format synthetic spike spike-inspect \
        services-up services-down clean coverage typecheck

help:
	@echo "Hyperlink Engine — make targets"
	@echo ""
	@echo "  install        poetry install + pre-commit install"
	@echo "  test           run full pytest suite with coverage gate"
	@echo "  test-fast      run pytest excluding slow + integration tests"
	@echo "  lint           ruff + black --check + mypy"
	@echo "  format         black + ruff --fix"
	@echo "  typecheck      mypy strict"
	@echo "  coverage       open coverage_html/index.html (after make test)"
	@echo "  synthetic      generate 20-doc synthetic dossier under data/synthetic/"
	@echo "  spike          run W1.5 spike on first synthetic Module 2 doc"
	@echo "  spike-inspect  show all detected references (no injection)"
	@echo "  services-up    docker compose up -d (Ollama, Redis, Neo4j)"
	@echo "  services-down  docker compose down"
	@echo "  clean          remove caches, build artifacts, output/"

install:
	poetry install
	poetry run pre-commit install

test:
	poetry run pytest

test-fast:
	poetry run pytest -m "not slow and not integration"

lint:
	poetry run ruff check .
	poetry run black --check .
	poetry run mypy src

format:
	poetry run black .
	poetry run ruff check --fix .

typecheck:
	poetry run mypy src

coverage:
	@echo "Open coverage_html/index.html in a browser"

synthetic:
	poetry run python -m scripts.bootstrap_synthetic_data --out data/synthetic --docs 20

spike:
	poetry run hyperlink-engine spike \
		--input data/synthetic/m2/2-5-clin-overview/2-5-clin-overview.docx \
		--output output/2-5-clin-overview_linked.docx \
		--report output/2-5-clin-overview_report.csv

spike-inspect:
	poetry run hyperlink-engine inspect \
		--input data/synthetic/m2/2-5-clin-overview/2-5-clin-overview.docx

services-up:
	docker compose up -d

services-down:
	docker compose down

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis coverage_html \
	       output __pycache__ src/**/__pycache__ tests/**/__pycache__
