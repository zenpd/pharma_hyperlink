"""Tests for the optional persistent preview-block cache + backend switch.

The cache is OPTIONAL (`diskcache` / `redis` extras) and must degrade to a
graceful no-op when disabled or absent — these tests pin that no-regression
contract, the backend-selection logic (redis→disk→off), and the round-trip
(which runs only where `diskcache` is installed).
"""
from __future__ import annotations

import pytest

from hyperlink_engine.core import preview_cache as pc


@pytest.fixture(autouse=True)
def _clean_cache_env(monkeypatch):
    """Each test starts from a fresh, un-initialized backend and clean env."""
    for var in (
        "HYPERLINK_CACHE_BACKEND",
        "HYPERLINK_DISK_CACHE_ENABLED",
        "HYPERLINK_DISK_CACHE_DIR",
        "HYPERLINK_DISK_CACHE_SIZE_GB",
        "HYPERLINK_REDIS_URL",
        "HYPERLINK_CACHE_REDIS_TTL_SEC",
        "HYPERLINK_CACHE_MAX_VALUE_MB",
    ):
        monkeypatch.delenv(var, raising=False)
    pc._reset_for_tests()
    yield
    pc._reset_for_tests()


# ── disabled / no-op contract (no backend needed) ───────────────────────────

def test_kill_switch_disables_everything(monkeypatch):
    monkeypatch.setenv("HYPERLINK_DISK_CACHE_ENABLED", "false")
    pc._reset_for_tests()
    assert pc.get_cache() is None


def test_backend_off_disables(monkeypatch):
    monkeypatch.setenv("HYPERLINK_CACHE_BACKEND", "off")
    pc._reset_for_tests()
    assert pc.get_cache() is None


def test_get_is_miss_when_disabled(monkeypatch):
    monkeypatch.setenv("HYPERLINK_CACHE_BACKEND", "off")
    pc._reset_for_tests()
    assert pc.get_blocks(("x", 1, 2, True, True)) is None


def test_set_is_noop_and_never_raises_when_disabled(monkeypatch):
    monkeypatch.setenv("HYPERLINK_CACHE_BACKEND", "off")
    pc._reset_for_tests()
    pc.set_blocks(("x", 1, 2, True, True), [{"text": "hi"}])  # must not raise
    assert pc.get_blocks(("x", 1, 2, True, True)) is None


def test_key_stringify_is_stable_and_greppable():
    assert pc._stringify("blocks", ("/a/b.pdf", 10, 20, True, False)) == (
        "blocks::/a/b.pdf|10|20|True|False"
    )
    assert pc._stringify("blocks", "scalar") == "blocks::scalar"


# ── backend selection logic (redis → disk → off) ────────────────────────────

class _FakeBackend(pc._Backend):
    name = "fake"


def test_auto_prefers_redis_when_present(monkeypatch):
    monkeypatch.setenv("HYPERLINK_CACHE_BACKEND", "auto")
    redis_backend = _FakeBackend()
    monkeypatch.setattr(pc, "_try_redis", lambda: redis_backend)
    monkeypatch.setattr(pc, "_try_disk", lambda: _FakeBackend())
    pc._reset_for_tests()
    assert pc.get_cache() is redis_backend  # redis wins when reachable


def test_auto_falls_back_to_disk_when_redis_absent(monkeypatch):
    monkeypatch.setenv("HYPERLINK_CACHE_BACKEND", "auto")
    disk_backend = _FakeBackend()
    monkeypatch.setattr(pc, "_try_redis", lambda: None)  # no redis
    monkeypatch.setattr(pc, "_try_disk", lambda: disk_backend)
    pc._reset_for_tests()
    assert pc.get_cache() is disk_backend


def test_auto_off_when_nothing_available(monkeypatch):
    monkeypatch.setenv("HYPERLINK_CACHE_BACKEND", "auto")
    monkeypatch.setattr(pc, "_try_redis", lambda: None)
    monkeypatch.setattr(pc, "_try_disk", lambda: None)
    pc._reset_for_tests()
    assert pc.get_cache() is None


def test_explicit_disk_never_uses_redis(monkeypatch):
    monkeypatch.setenv("HYPERLINK_CACHE_BACKEND", "disk")
    monkeypatch.setattr(pc, "_try_redis", lambda: (_ for _ in ()).throw(AssertionError("redis probed!")))
    disk_backend = _FakeBackend()
    monkeypatch.setattr(pc, "_try_disk", lambda: disk_backend)
    pc._reset_for_tests()
    assert pc.get_cache() is disk_backend


def test_explicit_redis_falls_back_to_disk_when_unavailable(monkeypatch):
    monkeypatch.setenv("HYPERLINK_CACHE_BACKEND", "redis")
    disk_backend = _FakeBackend()
    monkeypatch.setattr(pc, "_try_redis", lambda: None)  # redis down
    monkeypatch.setattr(pc, "_try_disk", lambda: disk_backend)
    pc._reset_for_tests()
    assert pc.get_cache() is disk_backend  # fail-safe, not None


# ── disk round-trip (only where diskcache is installed) ─────────────────────

def test_disk_round_trip_persists_blocks(tmp_path, monkeypatch):
    pytest.importorskip("diskcache")
    monkeypatch.setenv("HYPERLINK_CACHE_BACKEND", "disk")  # deterministic
    monkeypatch.setenv("HYPERLINK_DISK_CACHE_DIR", str(tmp_path / "cache"))
    pc._reset_for_tests()

    key = ("/docs/protocol.pdf", 12345, 6789, True, True)
    blocks = [{"type": "text", "text": "Section 5.3"}, {"type": "image", "uri": "data:...="}]
    assert pc.get_blocks(key) is None  # cold
    pc.set_blocks(key, blocks)
    assert pc.get_blocks(key) == blocks  # warm


def test_disk_survives_a_fresh_handle(tmp_path, monkeypatch):
    """Persistence contract: a fresh handle (simulated restart) still sees a
    previously-written value."""
    pytest.importorskip("diskcache")
    monkeypatch.setenv("HYPERLINK_CACHE_BACKEND", "disk")
    monkeypatch.setenv("HYPERLINK_DISK_CACHE_DIR", str(tmp_path / "cache"))
    pc._reset_for_tests()

    key = ("/docs/a.pdf", 1, 2, True, True)
    pc.set_blocks(key, [{"text": "persisted"}])
    pc._reset_for_tests()  # drop the in-process handle (like a restart)
    assert pc.get_blocks(key) == [{"text": "persisted"}]


# ── redis backend value handling (no server needed — client is faked) ───────

class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.sets = 0

    def get(self, k):
        return self.store.get(k)

    def set(self, k, v, ex=None):
        self.sets += 1
        self.store[k] = v


def test_redis_backend_round_trips_via_pickle():
    r = _FakeRedis()
    be = pc._RedisBackend(r, ttl=0, max_bytes=64 * 1024 * 1024)
    be.set("blocks::k", [{"text": "hi"}, {"uri": "data:="}])
    assert be.get("blocks::k") == [{"text": "hi"}, {"uri": "data:="}]


def test_redis_backend_skips_oversized_values():
    r = _FakeRedis()
    be = pc._RedisBackend(r, ttl=0, max_bytes=8)  # tiny cap
    be.set("blocks::big", [{"text": "x" * 10_000}])
    assert r.sets == 0                 # oversized value never sent to redis
    assert be.get("blocks::big") is None


def test_redis_backend_get_is_miss_on_error():
    class _Boom:
        def get(self, k):
            raise RuntimeError("connection lost")
    be = pc._RedisBackend(_Boom(), ttl=0, max_bytes=1024)
    assert be.get("blocks::k") is None  # degrades to miss, does not raise
