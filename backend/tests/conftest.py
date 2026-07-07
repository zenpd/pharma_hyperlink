"""Shared pytest fixtures. PLAN SEVEN — auth test helpers.

Auth is OFF by default (``settings.auth_enabled=False``), so the existing
suite runs unchanged: the global :func:`auth_guard` attaches the open
``SYSTEM_PRINCIPAL`` and never raises. These helpers let Phase 2/3 tests
simulate a logged-in user *without* a live SuperTokens core by overriding the
two auth dependencies on a ``create_app()`` instance.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolate_preview_cache() -> Iterable[None]:
    """Force the persistent preview cache OFF for the whole test suite.

    Without this, tests that render a document preview would read/write the
    developer's *real* Redis (or the machine-global disk cache) — causing
    cross-run pollution and flakiness. The dedicated cache tests
    (``test_preview_cache.py``) override ``HYPERLINK_CACHE_BACKEND`` per-test, so
    they still exercise the disk/redis paths in isolated temp dirs / fakes.
    """
    prev = os.environ.get("HYPERLINK_CACHE_BACKEND")
    os.environ["HYPERLINK_CACHE_BACKEND"] = "off"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("HYPERLINK_CACHE_BACKEND", None)
        else:
            os.environ["HYPERLINK_CACHE_BACKEND"] = prev


@pytest.fixture
def make_principal() -> Callable[..., object]:
    """Factory for a :class:`Principal` with the given roles (default: admin)."""
    from hyperlink_engine.api.middleware import Principal

    def _make(
        user_id: str = "u-test",
        email: str = "tester@example.com",
        roles: Iterable[str] = ("admin", "read:classified"),
    ) -> Principal:
        return Principal(user_id=user_id, email=email, roles=tuple(roles))

    return _make


def login_as(app: object, principal: object) -> None:
    """Override the auth gate + identity on a ``create_app()`` app for tests.

    Bypasses session enforcement (so no SuperTokens core is needed) and pins
    the resolved principal that route handlers read via ``Depends(get_principal)``.
    """
    from hyperlink_engine.api import middleware as mw

    async def _noop_guard() -> None:  # replaces auth_guard
        return None

    app.dependency_overrides[mw.auth_guard] = _noop_guard  # type: ignore[attr-defined]
    app.dependency_overrides[mw.get_principal] = lambda: principal  # type: ignore[attr-defined]


@pytest.fixture
def login_as_fixture() -> Callable[[object, object], None]:
    """Fixture form of :func:`login_as` for tests that prefer injection."""
    return login_as


@pytest.fixture(autouse=True)
def _reset_security_mode():
    """Stop the process-global security-toggle override leaking across tests."""
    from hyperlink_engine.api import middleware as mw

    mw.clear_security_mode()
    yield
    mw.clear_security_mode()
