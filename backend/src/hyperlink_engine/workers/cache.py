"""W7.2 — Process-level warm-load caches.

Loading the spaCy model + initializing the EntityExtractor is the single
biggest cost per worker (multi-second cold start). The cache here keeps
one instance per process, reset at fork via Celery's worker_process_init
hook (wired in ``celery_app.py`` when running under Celery).

Caches:
  * ``get_extractor(config)`` — returns a shared ``EntityExtractor``
    instance per (regex_only, with_ner, with_llm) configuration tuple.
  * ``get_existence_checker_seen()`` — a per-process LRU of recent
    existence-check results, keyed by (target_doc, target_anchor).

The caches are intentionally simple — no eviction policy beyond LRU
because each worker only holds a handful of long-lived objects, and the
existence-check LRU caps at 1024 entries which is sufficient for the
500-doc batch acceptance gate.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Generic, TypeVar

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.core.detection.entity_extractor import (
    EntityExtractor,
    full_cascade,
    regex_only,
    regex_plus_ner,
)

_log = get_logger("pipeline.cache")

K = TypeVar("K")
V = TypeVar("V")


@dataclass(frozen=True)
class ExtractorConfig:
    """Identity key for a cached ``EntityExtractor`` instance."""

    with_ner: bool = True
    with_llm: bool = False
    prefer_llm_stub: bool = True
    # When True, the LLM disambiguator is consulted for *every* span regardless
    # of regex/NER confidence. Needed because the regex catalog emits high
    # (0.92–0.99) confidence, which otherwise keeps every span above the
    # llm_confidence_threshold and skips the LLM entirely.
    force_refine: bool = False

    @classmethod
    def regex_only(cls) -> "ExtractorConfig":
        return cls(with_ner=False, with_llm=False)

    @classmethod
    def regex_plus_ner(cls) -> "ExtractorConfig":
        return cls(with_ner=True, with_llm=False)

    @classmethod
    def full_cascade(
        cls, *, prefer_stub: bool = True, force_refine: bool = False
    ) -> "ExtractorConfig":
        return cls(
            with_ner=True,
            with_llm=True,
            prefer_llm_stub=prefer_stub,
            force_refine=force_refine,
        )


class LRUCache(Generic[K, V]):
    """Tiny thread-safe LRU. Built-in functools.lru_cache won't accept the
    unhashable types we sometimes hand to the cache, so a hand-rolled
    OrderedDict is the simplest correct path."""

    def __init__(self, capacity: int = 1024) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._lock = threading.Lock()
        self._data: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K) -> V | None:
        with self._lock:
            value = self._data.get(key)
            if value is not None:
                self._data.move_to_end(key)
            return value

    def put(self, key: K, value: V) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = value
            while len(self._data) > self._capacity:
                self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


# ─────────────────────────────────────────────────────────────────────────
# Singleton stores
# ─────────────────────────────────────────────────────────────────────────


_extractor_lock = threading.Lock()
_extractor_cache: dict[ExtractorConfig, EntityExtractor] = {}

_existence_cache: LRUCache[tuple[str, str | None], str] = LRUCache(capacity=1024)


def get_extractor(config: ExtractorConfig | None = None) -> EntityExtractor:
    """Return a warm ``EntityExtractor`` keyed by the requested config.

    Caching matters because each ``EntityExtractor`` loads the regex
    registry + the spaCy pipeline; the spaCy load alone is several
    hundred ms on cold start.
    """
    cfg = config or ExtractorConfig()
    with _extractor_lock:
        cached = _extractor_cache.get(cfg)
        if cached is not None:
            return cached
        if cfg.with_llm:
            extractor = full_cascade(
                prefer_stub=cfg.prefer_llm_stub, force_refine=cfg.force_refine
            )
        elif cfg.with_ner:
            extractor = regex_plus_ner()
        else:
            extractor = regex_only()
        _extractor_cache[cfg] = extractor
        _log.info("extractor_cache_miss", with_ner=cfg.with_ner, with_llm=cfg.with_llm)
        return extractor


def reset_extractor_cache() -> None:
    """Drop all cached extractors. Tests use this between configurations."""
    with _extractor_lock:
        _extractor_cache.clear()


def get_existence_cache() -> LRUCache[tuple[str, str | None], str]:
    """Return the process-wide LRU cache of existence-check results."""
    return _existence_cache


def reset_existence_cache() -> None:
    _existence_cache.clear()
