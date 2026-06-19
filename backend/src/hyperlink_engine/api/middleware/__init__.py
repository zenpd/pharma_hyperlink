"""API auth middleware — SuperTokens (self-hosted) session gate. PLAN SEVEN.

Designed to be **inert** until ``settings.auth_enabled`` is True:

* **Auth disabled (the default):** every request resolves to the open
  :data:`SYSTEM_PRINCIPAL` and no SuperTokens code runs — behaviour is
  byte-for-byte identical to the pre-PLAN-SEVEN app.
* **Auth enabled:** :func:`init_supertokens` boots the SuperTokens SDK
  (mounting ``/api/auth/*`` + session refresh) and :func:`auth_guard`
  enforces a valid session on every non-public route.

The SuperTokens Python SDK is an **optional** dependency (``poetry install -E
auth``); all SuperTokens imports are lazy/guarded so this module loads even
when it is not installed. The *enforced* path is first exercised in Phase 2
(when the flag is flipped on); Phase 1 only wires it behind the flag.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.config.settings import get_settings

_log = get_logger("api.auth")

# ── Optional FastAPI import (guarded: conftest imports this module for the
#    whole suite, including environments without FastAPI) ────────────────────
try:
    from fastapi import Depends as _Depends
    from fastapi import HTTPException as _HTTPException
    from fastapi import Request as _Request
except Exception:  # pragma: no cover - FastAPI is optional for the core engine
    _Request = object  # type: ignore[assignment, misc]

    def _Depends(dependency: object = None) -> None:  # type: ignore[no-redef] # noqa: N802
        return None

    class _HTTPException(Exception):  # type: ignore[no-redef]
        def __init__(self, status_code: int = 500, detail: str = "") -> None:
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail


# ── Optional SuperTokens import ────────────────────────────────────────────
try:
    import supertokens_python  # noqa: F401

    _SUPERTOKENS_AVAILABLE = True
except Exception:  # pragma: no cover - optional dep, installed via -E auth
    _SUPERTOKENS_AVAILABLE = False


# ── Principal ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Principal:
    """The authenticated caller (or the open system principal when auth off)."""

    user_id: str
    email: str = ""
    roles: tuple[str, ...] = ()

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    @property
    def can_read_classified(self) -> bool:
        # Admins always can; the explicit permission is honoured too (Phase 3).
        return self.is_admin or "read:classified" in self.roles


# Open principal used whenever the gate is inactive. Treated as fully
# privileged so the existing single-user behaviour is preserved when auth is
# off (mirrors today's hardcoded ``system:hyperlink-engine`` actor).
SYSTEM_PRINCIPAL = Principal(
    user_id="system:hyperlink-engine",
    email="",
    roles=("admin", "read:classified"),
)


# ── Effective on/off (Feature C hook) ──────────────────────────────────────
# Phase 2 adds a persisted runtime override toggled via POST /api/auth/mode.
# Phase 1 keeps it simple: the effective flag is just settings.auth_enabled,
# with an in-memory override slot pre-wired so Phase 2 only adds persistence.
_runtime_override: bool | None = None


def set_auth_override(value: bool | None) -> None:
    """Set (or clear with ``None``) the runtime security-toggle override."""
    global _runtime_override
    _runtime_override = value


def auth_active() -> bool:
    """True when the auth + classification gate should be enforced."""
    if _runtime_override is not None:
        return _runtime_override
    return bool(get_settings().auth_enabled)


# ── Security toggle persistence (Feature C) ────────────────────────────────
_SECURITY_MODE_FILE = Path("output") / ".security_mode"


def load_security_mode() -> None:
    """Restore a persisted admin security-toggle choice on startup.

    If an admin previously flipped the gate via ``POST /api/security/mode``,
    that choice (in ``output/.security_mode``) overrides the env default so it
    survives a restart. No file → effective flag is ``settings.auth_enabled``.
    """
    try:
        if _SECURITY_MODE_FILE.is_file():
            data = json.loads(_SECURITY_MODE_FILE.read_text(encoding="utf-8"))
            set_auth_override(bool(data.get("enabled")))
    except Exception:  # pragma: no cover - never fail startup on a bad file
        _log.warning("security_mode_load_failed")


def persist_security_mode(enabled: bool) -> None:
    """Apply + persist a security-toggle change (admin Security button)."""
    set_auth_override(bool(enabled))
    try:
        _SECURITY_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SECURITY_MODE_FILE.write_text(json.dumps({"enabled": bool(enabled)}), encoding="utf-8")
    except Exception:  # pragma: no cover
        _log.warning("security_mode_persist_failed")


def clear_security_mode() -> None:
    """Drop any persisted/override security-toggle choice (tests + reset)."""
    set_auth_override(None)
    try:
        _SECURITY_MODE_FILE.unlink(missing_ok=True)
    except Exception:  # pragma: no cover
        pass


def security_mode_state() -> dict[str, object]:
    """Current gate status for the UI Security button + OFF banner."""
    return {
        "enabled": auth_active(),
        "source": "override" if _runtime_override is not None else "settings",
        "supertokens_available": _SUPERTOKENS_AVAILABLE,
    }


def bootstrap_roles() -> None:
    """Best-effort: ensure ``admin``/``user`` roles + ``read:classified`` exist.

    Runs only when the SDK is installed; a logged no-op when the SuperTokens
    core is unreachable at boot.
    """
    if not _SUPERTOKENS_AVAILABLE:
        return
    try:
        from supertokens_python.recipe.userroles.syncio import (
            create_new_role_or_add_permissions,
        )

        create_new_role_or_add_permissions("admin", ["read:classified"])
        create_new_role_or_add_permissions("user", [])
        _log.info("auth_roles_bootstrapped")
    except Exception:  # pragma: no cover - core may be down at boot
        _log.warning("auth_roles_bootstrap_failed")


# ── Init ───────────────────────────────────────────────────────────────────
_ST_INITED = False


def init_supertokens(app: object) -> None:
    """Boot the SuperTokens SDK + middleware whenever the SDK is installed.

    Mounting is deliberately independent of the gate state so the runtime
    Security toggle (Feature C) works in *both* directions without a restart:
    the ``/api/auth/*`` routes are always available (harmless while the gate
    is off — they just manage cookies), and :func:`auth_guard` decides whether
    sessions are actually *enforced* via :func:`auth_active`. Without the SDK
    installed this is a no-op and the app is byte-for-byte the pre-PLAN-SEVEN
    app.

    Safe to call repeatedly: the SDK ``init`` runs at most once per process
    (so repeated ``create_app()`` calls in tests do not re-init).
    """
    global _ST_INITED
    if not _SUPERTOKENS_AVAILABLE:
        if auth_active() or get_settings().auth_enabled:
            _log.warning("auth_enabled_but_supertokens_missing")
        return
    if not _ST_INITED:
        _init_sdk()
        _ST_INITED = True
    from supertokens_python.framework.fastapi import get_middleware

    app.add_middleware(get_middleware())  # type: ignore[attr-defined]
    bootstrap_roles()
    _log.info("supertokens_initialised", enforced=auth_active())


def _init_sdk() -> None:
    s = get_settings()
    from supertokens_python import InputAppInfo, SupertokensConfig, init
    from supertokens_python.recipe import dashboard, emailpassword, session, userroles

    init(
        app_info=InputAppInfo(
            app_name="hyperlink-engine",
            api_domain=s.api_domain,
            website_domain=s.website_domain,
            api_base_path="/api/auth",
            website_base_path="/auth",
        ),
        supertokens_config=SupertokensConfig(
            connection_uri=s.supertokens_connection_uri,
            api_key=s.supertokens_api_key or None,
        ),
        framework="fastapi",
        recipe_list=[
            emailpassword.init(),
            session.init(
                cookie_secure=s.session_cookie_secure,
                # Force cookie-based sessions: SSE (EventSource) and
                # window.open downloads cannot attach Authorization headers,
                # and the SDK's default switches to header tokens when the
                # client omits the st-auth-mode header (plain fetch does).
                get_token_transfer_method=lambda _req, _new, _ctx: "cookie",
            ),
            userroles.init(),
            # Built-in admin web UI at {api_domain}/api/auth/dashboard — view
            # users, sessions and roles. Served by the SuperTokens middleware
            # (runs before FastAPI routing), so auth_guard never blocks it;
            # access requires a dashboard user created via the core CDI.
            dashboard.init(),
        ],
        mode="asgi",
    )


def cors_expose_headers() -> list[str]:
    """Headers the browser must be allowed to read for SuperTokens sessions.

    Empty (no CORS change) unless the SDK is installed — exposing them is
    harmless while the gate is off, and required the moment it flips on.
    """
    if not _SUPERTOKENS_AVAILABLE:
        return []
    try:
        from supertokens_python import get_all_cors_headers

        return ["front-token", "st-access-token", "st-refresh-token", *get_all_cors_headers()]
    except Exception:  # pragma: no cover
        return []


# ── Request guard + principal dependencies ─────────────────────────────────
_PUBLIC_PREFIXES = ("/api/auth", "/auth")
_PUBLIC_PATHS = {"/api/health", "/health", "/docs", "/redoc", "/openapi.json", "/"}


def _is_public(path: str, method: str = "GET") -> bool:
    if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return True
    # The SPA must read the gate status BEFORE login to know whether to show
    # the login screen. GET only — making POST public would hand the handler
    # the open SYSTEM principal and let anonymous callers flip the gate.
    return method.upper() == "GET" and path == "/api/security/mode"


async def auth_guard(request: _Request) -> None:  # type: ignore[valid-type]
    """Global FastAPI dependency: enforce a session on protected routes.

    * Inactive gate or public path → attach :data:`SYSTEM_PRINCIPAL`, return.
    * Active gate → require a valid SuperTokens session (401 if absent).

    Tests override this (and :func:`get_principal`) via
    ``app.dependency_overrides`` to simulate a logged-in user.
    """
    if not auth_active() or _is_public(request.url.path, request.method):
        request.state.principal = SYSTEM_PRINCIPAL
        return
    if not _SUPERTOKENS_AVAILABLE:
        raise _HTTPException(
            status_code=503, detail="auth enabled but supertokens-python not installed"
        )
    from supertokens_python.recipe.session.asyncio import get_session

    try:
        st_session = await get_session(request, session_required=False)
    except _HTTPException:
        raise
    except Exception as exc:  # SDK not initialised / core unreachable → fail closed
        _log.warning("auth_session_check_failed", error=str(exc))
        raise _HTTPException(
            status_code=503, detail="auth gate active but session layer unavailable"
        ) from exc
    if st_session is None:
        raise _HTTPException(status_code=401, detail="authentication required")
    request.state.principal = await _principal_from_session(st_session)


# user_id → email, resolved once per user per process. Sessions verify locally
# (JWT); without this cache every request would add a core HTTP roundtrip.
_EMAIL_CACHE: dict[str, str] = {}


async def _email_of(user_id: str) -> str:
    if user_id in _EMAIL_CACHE:
        return _EMAIL_CACHE[user_id]
    email = ""
    try:
        from supertokens_python.asyncio import get_user

        u = await get_user(user_id)
        if u and getattr(u, "emails", None):
            email = u.emails[0] or ""
    except Exception:  # pragma: no cover - core unreachable → id-only principal
        pass
    _EMAIL_CACHE[user_id] = email
    return email


async def _principal_from_session(st_session: object) -> Principal:
    user_id = st_session.get_user_id()  # type: ignore[attr-defined]
    roles: tuple[str, ...] = ()
    try:
        payload = st_session.get_access_token_payload() or {}  # type: ignore[attr-defined]
        claim = payload.get("st-role", {}) or {}
        roles = tuple(claim.get("v", []) or [])
    except Exception:  # pragma: no cover - role claim wired fully in Phase 2
        roles = ()
    return Principal(user_id=user_id, email=await _email_of(user_id), roles=roles)


def get_principal(request: _Request) -> Principal:  # type: ignore[valid-type]
    """Return the resolved :class:`Principal` for the current request.

    Route handlers use ``Depends(get_principal)`` to read the caller's identity
    + roles uniformly whether or not the gate is active. The global
    :func:`auth_guard` runs first and populates ``request.state.principal``.
    """
    return getattr(request.state, "principal", SYSTEM_PRINCIPAL)


def require_classified_access(  # type: ignore[no-untyped-def]
    run_id: str, principal: Principal = _Depends(get_principal)
) -> None:
    """403 when a non-cleared caller reads a classified run's content (Feature B).

    Attached via ``dependencies=[Depends(require_classified_access)]`` on
    run-scoped endpoints, so ``run_id`` resolves from the path. A missing run
    is *not* rejected here — the endpoint's own 404 stays authoritative.
    Runs without a ``classification`` value count as unclassified (legacy
    compat), and the whole check no-ops while the gate is inactive.
    """
    if not auth_active():
        return
    if getattr(principal, "can_read_classified", False):
        return
    try:
        from hyperlink_engine.orchestration.state import run_store

        state = run_store.get(run_id)
    except Exception:  # pragma: no cover - store unavailable → endpoint decides
        return
    if state is None:
        return
    if str(state.get("classification") or "unclassified") == "classified":
        raise _HTTPException(status_code=403, detail="classified document: access denied")
