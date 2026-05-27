"""Phase 2 W7.1 — Celery application factory.

Celery is an *optional* dep (declared under ``pipeline`` poetry extras).
We therefore defer the import and surface a clear ``CeleryUnavailable``
error if a caller tries to build the app without the package present.

The factory honors a few critical settings:

  * ``celery_eager``        — when True (default in tests), every task
                              runs synchronously in the caller's thread,
                              so unit tests don't need a Redis broker.
  * ``celery_broker_url``   — usually ``redis://...`` in production;
                              ``memory://`` in eager / dev mode.
  * ``celery_result_backend`` — same shape; ``cache+memory://`` works for
                                eager mode.

Task queues created on this app (one per pipeline stage):

    ingestion → detection → injection → validation → reporting

All five share the same broker but route to distinct queue names so an
operator can scale workers independently per stage (e.g. more detection
workers than reporting workers).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.config.settings import get_settings

if TYPE_CHECKING:  # pragma: no cover
    from celery import Celery

_log = get_logger("pipeline.celery_app")


# Canonical stage names — used as queue names *and* task name prefixes
# so an operator can grep audit logs by stage at a glance.
STAGE_INGESTION = "ingestion"
STAGE_DETECTION = "detection"
STAGE_INJECTION = "injection"
STAGE_VALIDATION = "validation"
STAGE_REPORTING = "reporting"

PIPELINE_STAGES: tuple[str, ...] = (
    STAGE_INGESTION,
    STAGE_DETECTION,
    STAGE_INJECTION,
    STAGE_VALIDATION,
    STAGE_REPORTING,
)


class CeleryUnavailable(RuntimeError):
    """Raised when the optional ``celery`` package isn't installed."""


def _import_celery() -> Any:
    try:
        import celery  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised via test
        raise CeleryUnavailable(
            "celery not installed — install with `poetry install --extras pipeline`"
        ) from exc
    return celery


_singleton: "Celery | None" = None


def make_celery_app(
    *,
    app_name: str = "hyperlink_engine",
    broker_url: str | None = None,
    result_backend: str | None = None,
    eager: bool | None = None,
) -> "Celery":
    """Build a configured Celery app. Idempotent — the singleton wins."""
    global _singleton
    if _singleton is not None:
        return _singleton

    settings = get_settings()
    celery_mod = _import_celery()

    app = celery_mod.Celery(
        app_name,
        broker=broker_url or settings.celery_broker_url,
        backend=result_backend or settings.celery_result_backend,
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_always_eager=bool(eager) if eager is not None else settings.celery_eager,
        task_eager_propagates=True,
        task_acks_late=True,  # don't lose tasks on worker crash
        task_reject_on_worker_lost=True,
        broker_connection_retry_on_startup=True,
        # One named queue per pipeline stage — operators scale them
        # independently.
        task_routes={
            f"{app_name}.{stage}.*": {"queue": stage}
            for stage in PIPELINE_STAGES
        },
        task_default_queue=STAGE_INGESTION,
        worker_concurrency=settings.celery_concurrency,
    )
    _singleton = app
    _log.info(
        "celery_app_created",
        name=app_name,
        broker=app.conf.broker_url,
        backend=app.conf.result_backend,
        eager=app.conf.task_always_eager,
        queues=list(PIPELINE_STAGES),
    )
    return app


def reset_app() -> None:
    """Drop the cached app — used by tests that toggle ``eager`` mode."""
    global _singleton
    _singleton = None


def get_app() -> "Celery":
    """Return the cached app, building it if needed."""
    return make_celery_app()


def stage_task_name(stage: str, action: str, *, app_name: str = "hyperlink_engine") -> str:
    """Compute the dotted Celery task name for a given pipeline stage + action."""
    if stage not in PIPELINE_STAGES:
        raise ValueError(f"unknown pipeline stage: {stage!r}")
    return f"{app_name}.{stage}.{action}"
