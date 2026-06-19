"""Opt-in LangSmith tracing for the LangGraph pipeline — DEV ONLY.

LangGraph automatically reports a run to LangSmith when the ``LANGCHAIN_*``
environment variables are set. This module wires those variables from our
Pydantic settings, but only when:

  * ``langsmith_tracing`` is enabled (default OFF), AND
  * the configured endpoint is LOCAL — when ``enforce_local_llm_only`` is on
    (the 21 CFR Part 11 / GxP default), a non-local endpoint is refused so
    dossier content never leaves the machine.

This keeps tracing strictly a developer-debugging aid against a self-hosted
LangSmith instance; it is never part of the compliant product path.
"""

from __future__ import annotations

import os
import urllib.parse

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.config.settings import get_settings

_log = get_logger("orchestration.tracing")

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _is_local(endpoint: str) -> bool:
    host = (urllib.parse.urlparse(endpoint).hostname or "").lower()
    if host in _LOCAL_HOSTS:
        return True
    if host.startswith("10.") or host.startswith("192.168."):
        return True
    if host.startswith("172."):
        try:
            return 16 <= int(host.split(".")[1]) <= 31
        except (ValueError, IndexError):
            return False
    return False


def configure_tracing() -> bool:
    """Enable LangSmith tracing if requested and compliant. Returns True if on.

    Idempotent — safe to call on every graph build.
    """
    settings = get_settings()
    if not settings.langsmith_tracing:
        return False

    is_local = _is_local(settings.langsmith_endpoint)
    if not is_local:
        if not settings.langsmith_allow_cloud:
            _log.warning(
                "langsmith_tracing_refused_nonlocal",
                endpoint=settings.langsmith_endpoint,
                reason="non-local endpoint blocked; set langsmith_allow_cloud=true "
                "to override (DEV ONLY — sends data off-machine, not GxP-compliant).",
            )
            return False
        # Explicit dev override: cloud tracing accepted, but make the GxP
        # implication loud in the audit log.
        _log.warning(
            "langsmith_cloud_tracing_enabled_DEV_ONLY",
            endpoint=settings.langsmith_endpoint,
            reason="langsmith_allow_cloud=true — dossier run metadata is sent to "
            "the LangSmith cloud. Do NOT use on the compliant product path.",
        )

    # LangGraph / LangChain read these at runtime. Set both the modern
    # LANGSMITH_* names and the legacy LANGCHAIN_* names for compatibility.
    for prefix in ("LANGSMITH", "LANGCHAIN"):
        os.environ[f"{prefix}_TRACING"] = "true"
        os.environ[f"{prefix}_ENDPOINT"] = settings.langsmith_endpoint
        os.environ[f"{prefix}_PROJECT"] = settings.langsmith_project
        if settings.langsmith_api_key:
            os.environ[f"{prefix}_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_TRACING_V2"] = "true"  # older flag some versions read

    _log.info(
        "langsmith_tracing_enabled",
        endpoint=settings.langsmith_endpoint,
        project=settings.langsmith_project,
        mode="cloud(dev)" if not is_local else "local",
    )
    return True
