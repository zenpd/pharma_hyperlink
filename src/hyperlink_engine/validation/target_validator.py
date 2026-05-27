"""Layer 5 — Target correctness validator.

Existence (W4.4) says "the link resolves to *something*". This module asks
a different question: "does the link resolve to the *right* something?"

For each link:

* The visible text (e.g. ``Section 2.5.3``) is normalized
* The target heading / leaf title is normalized
* A similarity score is computed
* Below the configured threshold → ``SUSPICIOUS`` (not ``BROKEN``);
  publishing reviewers triage suspicious links in the dashboard.

Embeddings (sentence-transformers) are the preferred similarity engine
but are large; a deterministic token-Jaccard fallback runs when
embeddings are disabled or unavailable. That keeps the engine usable on
machines without the ML extras installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.config.settings import get_settings
from hyperlink_engine.models import LinkRecord, LinkStatus

_log = get_logger("validation.target")

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text)}


def jaccard_similarity(a: str, b: str) -> float:
    """Token-Jaccard similarity — deterministic, no ML deps."""
    set_a = _tokens(a)
    set_b = _tokens(b)
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _try_load_embeddings() -> object | None:
    """Lazily import sentence-transformers; return the model or None on failure."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return SentenceTransformer("all-MiniLM-L6-v2")
    except Exception as exc:  # noqa: BLE001 — model load can fail offline
        _log.warning("embedding_load_failed", error=str(exc))
        return None


@dataclass(frozen=True)
class TargetCheck:
    """Result of one target-correctness comparison."""

    link_text: str
    target_text: str
    score: float
    threshold: float
    passed: bool


class TargetValidator:
    """Compare link text against the target heading / title."""

    def __init__(
        self,
        *,
        threshold: float | None = None,
        use_embeddings: bool | None = None,
    ) -> None:
        settings = get_settings()
        self._threshold = threshold if threshold is not None else settings.target_similarity_threshold
        self._embedder = None
        wanted_embeddings = use_embeddings if use_embeddings is not None else False
        if wanted_embeddings:
            self._embedder = _try_load_embeddings()
        self._mode = "embeddings" if self._embedder is not None else "jaccard"
        _log.info("target_validator_init", mode=self._mode, threshold=self._threshold)

    @property
    def mode(self) -> str:
        return self._mode

    def score(self, link_text: str, target_text: str) -> float:
        if self._embedder is None:
            return jaccard_similarity(link_text, target_text)
        try:
            import numpy as np  # noqa: F401  (only required when embedder is live)

            vectors = self._embedder.encode(  # type: ignore[attr-defined]
                [link_text, target_text], normalize_embeddings=True
            )
            return float((vectors[0] * vectors[1]).sum())
        except Exception as exc:  # noqa: BLE001
            _log.warning("embedding_score_failed", error=str(exc))
            return jaccard_similarity(link_text, target_text)

    def check(self, link_text: str, target_text: str) -> TargetCheck:
        s = self.score(link_text, target_text)
        return TargetCheck(
            link_text=link_text,
            target_text=target_text,
            score=s,
            threshold=self._threshold,
            passed=s >= self._threshold,
        )

    def annotate(
        self,
        records: Iterable[LinkRecord],
        target_text_provider,  # type: ignore[no-untyped-def]
    ) -> list[LinkRecord]:
        """Add SUSPICIOUS status to existence-OK links whose target text mismatches.

        ``target_text_provider`` is a callable ``(LinkRecord) -> str | None``
        that returns the heading / title to compare against.
        """
        annotated: list[LinkRecord] = []
        suspicious = 0
        for record in records:
            if record.status != LinkStatus.OK:
                annotated.append(record)
                continue
            target_text = target_text_provider(record)
            if not target_text:
                annotated.append(record)
                continue
            result = self.check(record.link_text, target_text)
            if result.passed:
                annotated.append(record)
                continue
            suspicious += 1
            annotated.append(
                LinkRecord(
                    source_doc=record.source_doc,
                    link_text=record.link_text,
                    link_location_descriptor=record.link_location_descriptor,
                    target_doc=record.target_doc,
                    target_anchor=record.target_anchor,
                    status=LinkStatus.SUSPICIOUS,
                    confidence=result.score,
                    error_msg=f"target mismatch: score={result.score:.2f} < {result.threshold:.2f}",
                )
            )
        _log.info("target_validator_annotate", total=len(annotated), suspicious=suspicious)
        return annotated
