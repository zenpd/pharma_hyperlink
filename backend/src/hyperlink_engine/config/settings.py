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
    ollama_model: str = Field(default="llama3.2:3b")
    # Per-request HTTP timeout for the Ollama /api/generate call. Larger models
    # on CPU-only hosts can exceed the old 30s default and time out mid-refine;
    # 90s is a safer ceiling. Tune down for fast GPUs / small models.
    ollama_timeout: float = Field(default=90.0, gt=0.0)
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=512, gt=0)
    llm_confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    # When True, the hybrid cascade sends EVERY detected reference to the LLM
    # for confirmation — not just spans below the confidence threshold. This
    # "de-prioritises" the fast regex/NER layers so the local LLM is always
    # exercised (useful for demos and for max-accuracy review passes).
    # Default False keeps the historical behavior (LLM only on low-confidence
    # spans) so the default pipeline path is unchanged.
    llm_force_refine: bool = Field(default=False)

    # When True, AND a cross-doc reference resolves to ≥2 candidate documents
    # that the deterministic _pick_sibling rule cannot separate (today it drops
    # the link), the local LLM is asked to pick one using the reference + its
    # surrounding context ("resolve_v1"). Strictly additive: it only acts where
    # deterministic resolution already gave up, and a low-confidence / failed
    # call falls back to the same "unresolved" outcome as before. Default False
    # keeps the pipeline byte-for-byte unchanged.
    llm_resolve_ambiguous: bool = Field(default=False)

    # ── LLM provider switch (POC only) ─────────────────────────────────
    # ONE toggle for where disambiguation inference runs:
    #   "ollama" (default) → local Ollama daemon — the GxP / on-prem path
    #                        (unchanged behaviour).
    #   "nvidia"           → remote NVIDIA API Catalog (OpenAI-compatible).
    # The "nvidia" path sends prompts OFF-MACHINE, so it is for POC /
    # synthetic-data demos ONLY — never real dossier content. Local stays
    # the production default.
    llm_provider: Literal["ollama", "nvidia"] = Field(default="ollama")
    nvidia_base_url: str = Field(default="https://integrate.api.nvidia.com/v1")
    nvidia_model: str = Field(default="meta/llama-3.1-8b-instruct")
    # API key for the cloud provider (set HYPERLINK_LLM_API_KEY in .env;
    # only used when llm_provider="nvidia").
    llm_api_key: str = Field(default="")

    # ── LangSmith tracing (DEV ONLY — must be self-hosted/local for GxP) ──
    # OFF by default. Only enable against a LOCAL/self-hosted LangSmith — the
    # tracing config refuses a non-local endpoint while enforce_local_llm_only
    # is True, so dossier data never leaves the machine.
    langsmith_tracing: bool = Field(default=False)
    langsmith_endpoint: str = Field(default="http://localhost:1984")
    langsmith_project: str = Field(default="hyperlink-engine")
    langsmith_api_key: str = Field(default="")
    # DEV ESCAPE HATCH: allow tracing to the LangSmith *cloud* even though it
    # sends data off-machine. Default False. Only set True for local debugging
    # when self-hosted LangSmith is unavailable — NEVER on the GxP product path.
    langsmith_allow_cloud: bool = Field(default=False)

    # ── Embeddings ─────────────────────────────────────────────────────
    embedding_model: str = Field(default="all-MiniLM-L6-v2")

    # ── Graph backend ──────────────────────────────────────────────────
    graph_backend: Literal["networkx", "neo4j"] = Field(default="neo4j")
    neo4j_uri: str = Field(default="bolt://localhost:7687")
    neo4j_user: str = Field(default="neo4j")
    neo4j_password: str = Field(default="changeme")
    # Dossier-graph schema version. "v2" (default) writes the enterprise layer
    # — Sponsor/Study/DocumentVersion/DetectionMethod/RefType nodes with clear
    # provenance edges — *in addition to* the core Run/Document/Reference nodes.
    # "v1" writes only the core nodes (legacy). The enterprise layer is purely
    # additive: hydration and existing queries keep working under either value.
    # "v3" (lifecycle) = v2 + Sequence/Approval/SUPERSEDES/INCLUDES so the
    # submission lifecycle (linked → compliance_approved → fda_ready) and eCTD
    # leaf operations are first-class. Each tier is additive over the previous,
    # so hydration and existing queries keep working under any value.
    graph_schema: Literal["v1", "v2", "v3"] = Field(default="v3")
    # Sponsor name attached to every Dossier in the enterprise graph layer.
    graph_sponsor_name: str = Field(default="Sun Pharma")
    # Default eCTD region/sequence tagged on the Sequence node (overridable
    # per advance-stage call). Kept simple — single sponsor, single region demo.
    graph_region: str = Field(default="US (FDA)")

    # ── Whole-reference linking ────────────────────────────────────────
    # When True (default), a highlight-aware pass guarantees that every
    # yellow-highlighted span in an authored .docx becomes one continuous link
    # (resolving via the normal resolver). It is ADDITIVE — it never removes a
    # detection-based link — and it is a strict NO-OP on documents with no
    # highlights, so plain (un-highlighted) uploads link purely by detection,
    # exactly as before. Set False to disable the safety net entirely.
    link_highlighted_spans: bool = Field(default=True)

    # ── Agent profile (Plan Three — selectable per-layer agents) ───────
    # Default preset applied when a run does not specify one. "balanced"
    # reproduces the historical fixed-cascade behavior (regex + NER).
    default_agent_profile: Literal["fast", "balanced", "max"] = Field(default="balanced")

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
    # Optional path to a TRAINED spaCy NER model (output of scripts/train_ner.py,
    # e.g. "models/ner_v1/model-best"). When set, SpacyNerExtractor loads it and the
    # cascade reports mode="trained:…"; unset (default) → the rule-fallback
    # EntityRuler, so the suite's default behavior is unchanged.
    ner_model_path: str | None = Field(default=None)

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

    # ── OCR (scanned PDFs & image documents) ───────────────────────────
    # Master switch — OFF by default; enable with HYPERLINK_OCR_ENABLED=true.
    ocr_enabled: bool = Field(
        default=False,
        description="Enable OCR for scanned PDFs and standalone image files.",
    )
    # Engine: "tesseract" requires Tesseract binary + pytesseract + Pillow;
    # "easyocr" requires easyocr (deep-learning, CPU-only, no system binary).
    ocr_engine: Literal["tesseract", "easyocr"] = Field(
        default="tesseract",
        description="OCR engine to use when text extraction fails.",
    )
    # Tesseract language code (e.g. "eng", "deu", "fra+eng").
    # For EasyOCR pass a comma-separated list of codes (e.g. "en,de").
    ocr_language: str = Field(
        default="eng",
        description="Tesseract lang code or comma-separated EasyOCR language list.",
    )
    # Higher DPI → better OCR quality but slower and larger memory footprint.
    # 300 is the industry standard for regulatory documents; 150 for quick passes.
    ocr_dpi: int = Field(
        default=300,
        gt=0,
        description="DPI used when rendering a PDF page to an image for OCR.",
    )
    # Per-word confidence gate — words below this threshold are discarded.
    ocr_min_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum per-word OCR confidence (0.0–1.0) to include in output.",
    )
    # When True (default), OCR fires automatically on any page that has no
    # extractable text (image-only/scanned PDF pages). When False, OCR is only
    # triggered explicitly (e.g., by the API upload endpoint with ocr=true).
    ocr_fallback_on_empty_page: bool = Field(
        default=True,
        description="Auto-OCR pages where PyMuPDF + pdfplumber both return no text.",
    )
    # File extensions treated as standalone image documents (fed through OCR).
    # These are ingested as single-page pseudo-PDFs and produce OcrPageResult text.
    ocr_image_extensions: list[str] = Field(
        default_factory=lambda: [".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"],
        description="File extensions recognised as scannable image documents.",
    )

    # ── Compliance ─────────────────────────────────────────────────────
    enforce_local_llm_only: bool = Field(
        default=True,
        description="If True, refuse any LLM call that targets a non-localhost host. "
        "Required for 21 CFR Part 11 compliance.",
    )

    # ── Auth (PLAN SEVEN — SuperTokens self-hosted) ────────────────────
    # Master switch for the authentication + document-classification gate.
    # Wired into the API in Phase 1; stays False (today's open behavior)
    # until deliberately enabled in Phase 2. Also runtime-togglable by an
    # admin via the "Security" button (POST /api/auth/mode).
    auth_enabled: bool = Field(default=False)
    supertokens_connection_uri: str = Field(default="http://localhost:3567")
    # Shared secret between the backend SDK and the core container.
    supertokens_api_key: str = Field(default="")
    # API + website origins SuperTokens uses for session/cookie config.
    api_domain: str = Field(default="http://localhost:8000")
    website_domain: str = Field(default="http://localhost:5174")
    # Mark session cookies Secure (set True when served over HTTPS).
    session_cookie_secure: bool = Field(default=False)
    # Sensitivity stamped on a new run when the uploader doesn't choose one.
    # "classified" = deny-by-default (secure); "unclassified" = open.
    default_classification: Literal["classified", "unclassified"] = Field(
        default="classified"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance.

    Use `get_settings.cache_clear()` in tests to force reload.
    """
    return Settings()
