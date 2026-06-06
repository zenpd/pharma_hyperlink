"""Unit tests for pipeline/celery_app.py (W7.1)."""

from __future__ import annotations

import pytest

# celery is an optional dep — skip the whole module when not installed.
pytest.importorskip("celery")

from hyperlink_engine.pipeline import celery_app as celery_app_module  # noqa: E402
from hyperlink_engine.pipeline.celery_app import (
    PIPELINE_STAGES,
    STAGE_DETECTION,
    STAGE_INGESTION,
    CeleryUnavailable,
    _import_celery,
    get_app,
    make_celery_app,
    reset_app,
    stage_task_name,
)


@pytest.fixture(autouse=True)
def _reset_app_between_tests() -> None:
    reset_app()
    yield
    reset_app()


def test_pipeline_stage_constants_are_consistent() -> None:
    assert STAGE_INGESTION == "ingestion"
    assert STAGE_DETECTION == "detection"
    assert STAGE_INGESTION in PIPELINE_STAGES
    assert len(PIPELINE_STAGES) == 5


def test_make_celery_app_returns_singleton() -> None:
    app1 = make_celery_app()
    app2 = make_celery_app()
    assert app1 is app2


def test_make_celery_app_honors_eager_override() -> None:
    app = make_celery_app(eager=True)
    assert app.conf.task_always_eager is True


def test_make_celery_app_eager_false_override() -> None:
    app = make_celery_app(eager=False)
    assert app.conf.task_always_eager is False


def test_get_app_builds_on_demand() -> None:
    reset_app()
    app = get_app()
    assert app is not None
    # Second call returns same instance.
    assert get_app() is app


def test_stage_task_name_format() -> None:
    name = stage_task_name(STAGE_DETECTION, "detect_references")
    assert name == "hyperlink_engine.detection.detect_references"


def test_stage_task_name_rejects_unknown_stage() -> None:
    with pytest.raises(ValueError, match="unknown pipeline stage"):
        stage_task_name("not_a_stage", "x")


def test_queue_routes_include_every_stage() -> None:
    app = make_celery_app()
    routes = app.conf.task_routes
    for stage in PIPELINE_STAGES:
        # task_routes is a glob pattern → queue mapping
        key = next(k for k in routes if k.startswith(f"hyperlink_engine.{stage}"))
        assert routes[key]["queue"] == stage


def test_import_celery_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    original_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):
        if name == "celery":
            raise ImportError("no celery")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(CeleryUnavailable):
        _import_celery()


def test_app_has_json_serializer_only() -> None:
    app = make_celery_app()
    assert app.conf.task_serializer == "json"
    assert "json" in app.conf.accept_content
    assert app.conf.result_serializer == "json"
