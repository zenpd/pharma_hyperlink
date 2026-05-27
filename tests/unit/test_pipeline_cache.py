"""Unit tests for pipeline/cache.py (W7.2)."""

from __future__ import annotations

import pytest

from hyperlink_engine.pipeline.cache import (
    ExtractorConfig,
    LRUCache,
    get_existence_cache,
    get_extractor,
    reset_existence_cache,
    reset_extractor_cache,
)


# ── LRUCache ────────────────────────────────────────────────────────────


def test_lru_basic_get_put() -> None:
    cache: LRUCache[str, int] = LRUCache(capacity=2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    assert cache.get("b") == 2


def test_lru_evicts_least_recently_used() -> None:
    cache: LRUCache[str, int] = LRUCache(capacity=2)
    cache.put("a", 1)
    cache.put("b", 2)
    # Touch "a" so "b" becomes LRU.
    assert cache.get("a") == 1
    cache.put("c", 3)
    assert "b" not in cache
    assert "a" in cache
    assert "c" in cache


def test_lru_put_overwrites_existing() -> None:
    cache: LRUCache[str, int] = LRUCache(capacity=2)
    cache.put("a", 1)
    cache.put("a", 99)
    assert cache.get("a") == 99
    assert len(cache) == 1


def test_lru_zero_capacity_rejected() -> None:
    with pytest.raises(ValueError):
        LRUCache(capacity=0)


def test_lru_clear_empties_cache() -> None:
    cache: LRUCache[str, int] = LRUCache(capacity=4)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.clear()
    assert len(cache) == 0
    assert cache.get("a") is None


# ── ExtractorConfig ─────────────────────────────────────────────────────


def test_extractor_config_factory_methods() -> None:
    regex = ExtractorConfig.regex_only()
    assert regex.with_ner is False and regex.with_llm is False

    ner = ExtractorConfig.regex_plus_ner()
    assert ner.with_ner is True and ner.with_llm is False

    cascade = ExtractorConfig.full_cascade(prefer_stub=True)
    assert cascade.with_ner is True and cascade.with_llm is True


def test_extractor_config_is_hashable_for_cache_keys() -> None:
    a = ExtractorConfig.regex_only()
    b = ExtractorConfig.regex_only()
    assert hash(a) == hash(b)
    assert a == b


# ── get_extractor caching ───────────────────────────────────────────────


def test_get_extractor_returns_same_instance_for_same_config() -> None:
    reset_extractor_cache()
    cfg = ExtractorConfig.regex_only()
    a = get_extractor(cfg)
    b = get_extractor(cfg)
    assert a is b


def test_get_extractor_returns_different_instances_for_different_configs() -> None:
    reset_extractor_cache()
    regex = get_extractor(ExtractorConfig.regex_only())
    ner = get_extractor(ExtractorConfig.regex_plus_ner())
    assert regex is not ner


def test_reset_extractor_cache_clears_singletons() -> None:
    reset_extractor_cache()
    a = get_extractor(ExtractorConfig.regex_only())
    reset_extractor_cache()
    b = get_extractor(ExtractorConfig.regex_only())
    assert a is not b


# ── Existence cache (LRU singleton) ─────────────────────────────────────


def test_existence_cache_is_a_singleton() -> None:
    reset_existence_cache()
    a = get_existence_cache()
    b = get_existence_cache()
    assert a is b


def test_existence_cache_round_trips() -> None:
    reset_existence_cache()
    cache = get_existence_cache()
    cache.put(("target.docx", "anchor"), "ok")
    assert cache.get(("target.docx", "anchor")) == "ok"


def test_reset_existence_cache_clears_entries() -> None:
    cache = get_existence_cache()
    cache.put(("x", None), "ok")
    reset_existence_cache()
    assert cache.get(("x", None)) is None
