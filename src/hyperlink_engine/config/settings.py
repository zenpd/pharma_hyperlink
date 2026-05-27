"""Centralized configuration via Pydantic Settings.

Settings are loaded once at process start from environment variables (with
optional `.env` file). Access via `get_settings()` — never instantiate
`Settings()` directly in production code (so tests can override).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="HYPERLINK_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Paths ──────────────────────────────────────────────────────────
    project_root: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[3],
        description="Repository root (auto-detected).",
    )
    data_dir: Path = Field(default=Path("data"))
    output_dir: Path = Field(default=Path("output"))
    audit_log_path: Path = Field(default=Path("audit.jsonl"))

    # ── LLM (local-only; no external APIs) ─────────────────────────────
    ollama_host: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="llama3.1:8b")
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=512, gt=0)
    llm_confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)

    # ── Embeddings ─────────────────────────────────────────────────────
    embedding_model: str = Field(default="all-MiniLM-L6-v2")

    # ── Graph backend ──────────────────────────────────────────────────
    graph_backend: Literal["networkx", "neo4j"] = Field(default="networkx")
    neo4j_uri: str = Field(default="bolt://localhost:7687")
    neo4j_user: str = Field(default="neo4j")
    neo4j_password: str = Field(default="changeme")

    # ── Pipeline ───────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")
    celery_concurrency: int = Field(default=4, gt=0)
    # Celery eager mode runs every task synchronously in the calling thread.
    # Default True so unit tests don't need a Redis broker; production CLI
    # flips it off via HYPERLINK_CELERY_EAGER=false.
    celery_eager: bool = Field(default=True)
    celery_broker_url: str = Field(default="memory://")
    celery_result_backend: str = Field(default="cache+memory://")
    # Throughput knobs.
    pipeline_max_retries: int = Field(default=3, ge=0)
    pipeline_retry_backoff_seconds: float = Field(default=2.0, gt=0.0)
    pipeline_doc_workers: int = Field(default=4, gt=0)
    pipeline_ner_warm_load: bool = Field(default=True)

    # ── Dossplorer integration (mocked in Phase 1) ─────────────────────
    dossplorer_base_url: str = Field(default="http://localhost:8080/mock-dossplorer")
    dossplorer_oauth_token: str = Field(default="")
    dossplorer_mock_mode: bool = Field(default=True)

    # ── Validation thresholds ──────────────────────────────────────────
    detection_min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    target_similarity_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    blue_text_rgb_tolerance: int = Field(default=40, ge=0, le=255)

    # ── Logging ────────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    log_format: Literal["json", "console"] = Field(default="json")

    # ── Compliance ─────────────────────────────────────────────────────
    enforce_local_llm_only: bool = Field(
        default=True,
        description="If True, refuse any LLM call that targets a non-localhost host. "
        "Required for 21 CFR Part 11 compliance.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance.

    Use `get_settings.cache_clear()` in tests to force reload.
    """
    return Settings()
