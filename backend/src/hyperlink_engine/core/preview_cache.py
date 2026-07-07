"""Optional persistent cache for parsed preview blocks, with a pluggable backend.

Why this exists
---------------
The Reference View / BEFORE-AFTER preview parses each PDF into "blocks"
(``get_text("dict")`` + ``find_tables`` per page). On a big protocol that costs
~24s. The API memoizes the result in a process-local LRU (``_DOC_BLOCKS_CACHE``
in ``api/app.py``), but that dies on every process restart (``uvicorn --reload``)
and is not shared across processes (each Celery worker holds its own copy).

This module adds a **persistent, cross-process** layer *behind* that in-memory
LRU. It picks a backend automatically:

    redis present ─▶ use Redis        (fast, shared; RAM-resident)
    else diskcache ─▶ use disk cache  (SQLite-backed; spills to disk; no server)
    else            ─▶ no-op          (in-memory LRU only, today's behavior)

Neither backend needs Docker. Redis is only *used* if a server is already
reachable — it is never started here.

Backend selection (``HYPERLINK_CACHE_BACKEND``)
-----------------------------------------------
    auto  (default)  redis if reachable, else disk, else off
    redis            force Redis; falls back to disk if unreachable (fail-safe)
    disk             force diskcache
    off / none       disable entirely (in-memory LRU only)

Design guarantees (must never regress the default path)
-------------------------------------------------------
* **Optional.** ``redis`` and ``diskcache`` are both optional deps. Absent /
  unreachable → graceful no-op; callers fall back to in-memory-only behavior.
* **Fail-safe.** Every backend op swallows errors and degrades to "cache miss" —
  it never raises into the request path.
* **Env-configurable** (mirrors the existing ``HYPERLINK_DOC_BLOCKS_CACHE_MAX``
  env convention rather than routing infra knobs through Settings):
    - ``HYPERLINK_CACHE_BACKEND``        auto | redis | disk | off   (default auto)
    - ``HYPERLINK_DISK_CACHE_ENABLED``   global kill-switch          (default true)
    - ``HYPERLINK_DISK_CACHE_DIR``       disk cache dir     (default ~/.hyperlink_engine/cache)
    - ``HYPERLINK_DISK_CACHE_SIZE_GB``   disk LRU size cap           (default 2)
    - ``HYPERLINK_REDIS_URL``            redis url (default redis://localhost:6379/0)
    - ``HYPERLINK_CACHE_REDIS_TTL_SEC``  redis entry TTL, 0=no expiry (default 604800 = 7d)
    - ``HYPERLINK_CACHE_MAX_VALUE_MB``   skip caching values larger than this (default 64)
"""
from __future__ import annotations

import os
import pickle
import threading
from pathlib import Path
from typing import Any

from hyperlink_engine.config.logging_setup import get_logger

_log = get_logger("cache.preview")

_BACKEND_ENV = "HYPERLINK_CACHE_BACKEND"
_ENABLED_ENV = "HYPERLINK_DISK_CACHE_ENABLED"  # legacy global kill-switch
_DIR_ENV = "HYPERLINK_DISK_CACHE_DIR"
_SIZE_ENV = "HYPERLINK_DISK_CACHE_SIZE_GB"
_REDIS_URL_ENV = "HYPERLINK_REDIS_URL"
_REDIS_TTL_ENV = "HYPERLINK_CACHE_REDIS_TTL_SEC"
_MAX_VAL_MB_ENV = "HYPERLINK_CACHE_MAX_VALUE_MB"

_FALSEY = {"0", "false", "no", "off", ""}

# Lazily-initialized singleton backend. ``_init_done`` guards one-time setup so a
# missing/broken backend is diagnosed once, not on every call.
_backend: _Backend | None = None
_init_done = False
_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# Backends — each is best-effort: every method degrades to miss/no-op on error.
# ─────────────────────────────────────────────────────────────────────────────


class _Backend:
    name = "none"

    def get(self, key: str) -> Any:  # pragma: no cover - interface
        return None

    def set(self, key: str, value: Any) -> None:  # pragma: no cover - interface
        ...

    def close(self) -> None:  # pragma: no cover - interface
        ...


class _DiskBackend(_Backend):
    """diskcache.Cache — SQLite-backed, spills large values to disk, no server."""

    name = "disk"

    def __init__(self, cache: Any) -> None:
        self._c = cache

    def get(self, key: str) -> Any:
        try:
            return self._c.get(key)
        except Exception as exc:
            _log.warning("disk_cache_get_failed", error=str(exc))
            return None

    def set(self, key: str, value: Any) -> None:
        try:
            self._c.set(key, value)
        except Exception as exc:
            _log.warning("disk_cache_set_failed", error=str(exc))

    def close(self) -> None:
        try:
            self._c.close()
        except Exception:
            pass


class _RedisBackend(_Backend):
    """Redis — fast, shared, RAM-resident. Values are pickled; oversized values
    are skipped (crash-safety) and TTL-bounded to cap memory growth."""

    name = "redis"

    def __init__(self, client: Any, *, ttl: int, max_bytes: int) -> None:
        self._r = client
        self._ttl = ttl
        self._max = max_bytes

    def get(self, key: str) -> Any:
        try:
            raw = self._r.get(key)
            return pickle.loads(raw) if raw is not None else None
        except Exception as exc:
            _log.warning("redis_cache_get_failed", error=str(exc))
            return None

    def set(self, key: str, value: Any) -> None:
        try:
            data = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
            if self._max and len(data) > self._max:
                _log.info("redis_cache_skip_oversized", key=key, bytes=len(data))
                return
            self._r.set(key, data, ex=(self._ttl or None))
        except Exception as exc:
            _log.warning("redis_cache_set_failed", error=str(exc))

    def close(self) -> None:
        try:
            self._r.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Selection
# ─────────────────────────────────────────────────────────────────────────────


def _default_dir() -> Path:
    override = os.environ.get(_DIR_ENV)
    if override:
        return Path(override)
    # Home-anchored so the cache is machine-global and survives the repo being
    # moved, re-zipped, or checked out in a new folder.
    return Path.home() / ".hyperlink_engine" / "cache"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def _try_redis() -> _Backend | None:
    """Return a Redis backend iff a server is reachable, else None. Never raises."""
    url = os.environ.get(_REDIS_URL_ENV, "redis://localhost:6379/0")
    try:
        import redis  # optional dependency (already used as the Celery broker)
    except Exception:
        return None
    try:
        client = redis.Redis.from_url(
            url, socket_connect_timeout=0.5, socket_timeout=1.0
        )
        client.ping()  # the actual "is Redis present?" probe (one time, at init)
    except Exception:
        return None
    ttl = _env_int(_REDIS_TTL_ENV, 604800)  # 7 days; 0 disables expiry
    max_bytes = _env_int(_MAX_VAL_MB_ENV, 64) * 1024 * 1024
    _log.info("cache_backend_ready", backend="redis", url=url, ttl_sec=ttl)
    return _RedisBackend(client, ttl=ttl, max_bytes=max_bytes)


def _try_disk() -> _Backend | None:
    """Return a diskcache backend, or None if diskcache is absent / init fails."""
    try:
        import diskcache  # optional dependency
    except Exception:
        _log.info("disk_cache_unavailable", hint="pip install diskcache")
        return None
    try:
        size_gb = float(os.environ.get(_SIZE_ENV, "2") or "2")
    except (TypeError, ValueError):
        size_gb = 2.0
    try:
        root = _default_dir()
        root.mkdir(parents=True, exist_ok=True)
        cache = diskcache.Cache(
            str(root / "preview_blocks"),
            size_limit=int(max(0.1, size_gb) * (1024 ** 3)),
            eviction_policy="least-recently-used",
        )
        _log.info("cache_backend_ready", backend="disk", dir=str(root), size_gb=size_gb)
        return _DiskBackend(cache)
    except Exception as exc:
        _log.warning("disk_cache_init_failed", error=str(exc))
        return None


def _select_backend() -> _Backend | None:
    """Pick a backend from ``HYPERLINK_CACHE_BACKEND`` + availability. Never raises."""
    # Global kill-switch (kept for back-compat): overrides everything.
    if os.environ.get(_ENABLED_ENV, "true").strip().lower() in _FALSEY:
        _log.info("cache_disabled", reason=_ENABLED_ENV)
        return None
    mode = os.environ.get(_BACKEND_ENV, "auto").strip().lower()
    if mode in ("off", "none", "memory", "disabled"):
        _log.info("cache_disabled", reason=f"{_BACKEND_ENV}={mode}")
        return None
    if mode == "disk":
        return _try_disk()
    if mode == "redis":
        # Explicit preference, but fail-safe: fall back to disk if Redis is down
        # so a misconfigured URL degrades to a working cache, not to nothing.
        backend = _try_redis()
        if backend is None:
            _log.warning("redis_requested_but_unavailable_falling_back_to_disk")
            backend = _try_disk()
        return backend
    # auto (default): Redis if reachable, else disk, else nothing.
    return _try_redis() or _try_disk()


def get_cache() -> _Backend | None:
    """Return the lazily-selected cache backend, or None.

    None means "no persistent cache available" (disabled, nothing installed, or
    unreachable) — callers must treat that as a cache miss and use their
    in-memory path unchanged.
    """
    global _backend, _init_done
    if _init_done:
        return _backend
    with _lock:
        if _init_done:  # another thread won the race
            return _backend
        # Assign the backend BEFORE flipping the flag: the lock-free fast path
        # reads _init_done then _backend, so if it ever observes the flag True the
        # backend must already be set (never None mid-init, e.g. while a slow
        # redis ping runs). Under CPython each assignment is atomic, so this
        # ordering is sufficient without an explicit memory barrier.
        _backend = _select_backend()
        _init_done = True
        return _backend


def _reset_for_tests() -> None:
    """Drop the cached backend so a test can re-init under new env vars."""
    global _backend, _init_done
    with _lock:
        try:
            if _backend is not None:
                _backend.close()
        except Exception:
            pass
        _backend = None
        _init_done = False


def _stringify(namespace: str, key: Any) -> str:
    """Stable string key. Tuples become ``a|b|c`` so the key is human-greppable
    and independent of tuple-pickling details across versions."""
    if isinstance(key, (tuple, list)):
        body = "|".join(str(part) for part in key)
    else:
        body = str(key)
    return f"{namespace}::{body}"


def get_blocks(key: Any) -> Any:
    """Return cached parsed blocks for ``key`` (any hashable identity), or None."""
    backend = get_cache()
    if backend is None:
        return None
    return backend.get(_stringify("blocks", key))


def set_blocks(key: Any, value: Any) -> None:
    """Persist parsed blocks for ``key``. Best-effort; swallows all errors."""
    backend = get_cache()
    if backend is None:
        return
    backend.set(_stringify("blocks", key), value)
