# Authentication & Classified-Document Access — SuperTokens (Self-Hosted)

> **PLAN SEVEN** implementation guide. Everything in one place: architecture, boot
> sequence, login flow, cookies, roles, password storage, user management, the
> Security toggle, the classification gate, test accounts, and troubleshooting.
>
> Verified end-to-end on 2026-06-10: 24/24 live HTTP checks, 585 backend tests,
> clean frontend build.

---

## 1. What was built, in one paragraph

The engine previously had **zero authentication** — every request ran as a
hardcoded `system:hyperlink-engine` actor and the `reviewer` on sign-offs was an
unverified string from the request body. PLAN SEVEN adds three additive features:

| Feature | What it does |
|---|---|
| **A. Identity** | Email+password login, cookie sessions, `admin`/`user` roles, real identity bound into the audit trail and review/compliance sign-offs |
| **B. Classification gate** | Every pipeline run is `classified` or `unclassified`. Admins see everything; users see only unclassified. Enforced on every read, filtered out of every list |
| **C. Security toggle** | A runtime ON/OFF switch for the whole gate (admin button in the UI header), persisted across restarts, audit-logged |

**Crucial property:** with auth OFF (the default), the app is byte-for-byte the
pre-PLAN-SEVEN app. No login, no SuperTokens code runs, the test suite needs no
core. You opt in via `HYPERLINK_AUTH_ENABLED=true` or the Security button.

---

## 2. Why SuperTokens self-hosted (not Clerk)

This system enforces *"no data leaves the machine"* (GxP / 21 CFR Part 11
posture — `enforce_local_llm_only`, the On-Prem badge, the append-only audit
trail). Clerk ships every identity to its cloud. **SuperTokens self-hosted**
runs as a Docker container inside your network and stores users in **your own
Postgres** — nothing leaves the box. It also owns all session signing keys, so
there is **no JWT keypair for us to mint, store, or rotate**.

---

## 3. Architecture

```
Browser (SPA :5174)
  │  fetch("/api/...", credentials: "include")        ← httpOnly cookies ride along
  │  (Vite proxy makes /api same-origin in dev)
  ▼
FastAPI :8000  (backend/src/hyperlink_engine/api/)
  ├─ SuperTokens ASGI middleware  → mounts /api/auth/* (signin, signup, signout, refresh)
  ├─ auth_guard (GLOBAL dependency on every route)
  │     gate OFF → attach SYSTEM_PRINCIPAL (open, admin) and continue
  │     gate ON  → verify session cookie → attach real Principal, else 401
  ├─ require_classified_access (per-endpoint dependency on all run-scoped routes)
  │     classified run + caller not cleared → 403
  ▼
SuperTokens Core :3567 (Docker: hyperlink-supertokens)
  ▼
Postgres (Docker: hyperlink-supertokens-db, volume supertokens_db_data)
      users · password hashes · sessions · roles
```

Key files:

| File | Role |
|---|---|
| `backend/src/hyperlink_engine/api/middleware/__init__.py` | The entire auth core: `Principal`, `auth_guard`, `init_supertokens`, `require_classified_access`, Security-toggle helpers |
| `backend/src/hyperlink_engine/api/app.py` | Wires the guard globally, `/api/me`, `/api/security/mode`, upload classification rules, list filtering |
| `backend/src/hyperlink_engine/config/settings.py` | The `HYPERLINK_*` auth settings block |
| `backend/src/hyperlink_engine/orchestration/state.py` | `classification` + `owner` on every run |
| `backend/src/hyperlink_engine/core/graph/dossier_schema.py` | Persists/hydrates classification on Neo4j `Run` nodes |
| `frontend/src/contexts/Auth.tsx` | SPA auth state (probe, login, logout, toggle) |
| `frontend/src/screens/Login.tsx` | Login / signup screen |
| `infra/docker/docker-compose.yml` | `supertokens-core` + `supertokens-db` services |

---

## 4. Storage — where everything lives

| Data | Where | Notes |
|---|---|---|
| **User accounts & emails** | SuperTokens Postgres (`emailpassword_users`, `all_auth_recipe_users` tables) | Created via `/api/auth/signup` |
| **Passwords** | SuperTokens Postgres — **bcrypt hashes only** | Plaintext passwords are never stored anywhere; the core hashes on arrival. App code never sees or touches password hashes |
| **Sessions** | SuperTokens Postgres (`session_info`) + signed JWT access tokens in cookies | Access tokens verify *locally* in the backend (no core roundtrip per request) |
| **Session signing keys** | Inside the core + its Postgres | Rotated by the core automatically — not our problem |
| **Roles & permissions** | SuperTokens Postgres (`roles`, `user_roles`, `role_permissions`) | `admin` (with `read:classified` permission) and `user`, auto-created at backend boot by `bootstrap_roles()` |
| **Run `classification` + `owner`** | In-memory `run_store` **and** Neo4j `Run` node properties | Survives restarts via the existing Neo4j hydration. Legacy runs with no property = `unclassified` |
| **Security-toggle override** | `backend/output/.security_mode` (tiny JSON file) | Lets an admin's runtime choice survive a restart. Delete the file to fall back to the env default |
| **Audit lines** | Existing append-only `audit.jsonl` | `pipeline_upload`, `security_mode_changed`, `hitl_run_approved/rejected`, … now with real `actor` |

**The app's own database stores no credentials at all.** Everything credential-
shaped is inside the SuperTokens Postgres volume `supertokens_db_data`.

---

## 5. Keys, secrets & settings

All settings use the `HYPERLINK_` env prefix (pydantic-settings,
`config/settings.py`). From `.env.example`:

```dotenv
# Master switch — default OFF. Runtime-togglable via the Security button.
HYPERLINK_AUTH_ENABLED=false

# Where the backend finds the SuperTokens core
HYPERLINK_SUPERTOKENS_CONNECTION_URI=http://localhost:3567

# Shared secret between backend ↔ core. Empty in dev (core is localhost-bound).
# Set it in prod; the compose file forwards it to the core as API_KEYS.
HYPERLINK_SUPERTOKENS_API_KEY=

# Cookie/CORS domains
HYPERLINK_API_DOMAIN=http://localhost:8000
HYPERLINK_WEBSITE_DOMAIN=http://localhost:5174
HYPERLINK_SESSION_COOKIE_SECURE=false        # true behind HTTPS in prod

# Deny-by-default: new runs are classified unless the uploader downgrades
HYPERLINK_DEFAULT_CLASSIFICATION=classified

# Postgres for the core (docker-compose reads these)
POSTGRES_USER=supertokens
POSTGRES_PASSWORD=changeme
POSTGRES_DB=supertokens
```

**Net new secrets: just the core API key + the Postgres password.** No JWT
keypair, no JWKS endpoint, no key rotation runbook — SuperTokens owns signing.

The Python SDK is an **optional** dependency:
`poetry install -E auth` (pyproject pins `supertokens-python = "^0.31.0"`).
Without it installed the auth module no-ops and the app runs exactly as before.

---

## 6. Boot sequence (what happens in `create_app()`)

```
create_app()
 1. load_security_mode()          # restore persisted admin toggle from output/.security_mode
 2. init_supertokens(app)         # ONLY if supertokens-python is installed:
 │    ├─ init SDK once per process (app_name="hyperlink-engine",
 │    │     api_base_path="/api/auth", recipes: emailpassword, session, userroles)
 │    ├─ session recipe is PINNED to cookie mode  ← see §8, this matters
 │    ├─ app.add_middleware(get_middleware())   → mounts /api/auth/* routes
 │    └─ bootstrap_roles()        # best-effort: ensure admin/user roles +
 │                                #   read:classified permission exist in the core
 3. FastAPI(dependencies=[Depends(auth_guard)])   # the guard runs on EVERY route
 4. CORS expose_headers += front-token, st-access-token, st-refresh-token
```

Note: the SuperTokens middleware is mounted **whenever the SDK is installed**,
even if the gate is currently OFF. That's deliberate — it makes the runtime
Security toggle work in *both* directions without a restart (the `/api/auth/*`
routes are harmless while the gate is off; `auth_guard` decides per-request
whether sessions are actually *enforced*).

---

## 7. The request guard, step by step

Every request hits `auth_guard` (a global FastAPI dependency):

```
auth_guard(request):
  1. gate inactive OR path is public?
        → request.state.principal = SYSTEM_PRINCIPAL   (open, admin) → continue
  2. gate active, SDK not installed?
        → 503 "auth enabled but supertokens-python not installed"   (FAIL CLOSED)
  3. gate active → get_session(request)    # verifies the sAccessToken cookie locally
        session error (SDK uninitialised / core trouble) → 503      (FAIL CLOSED)
        no session                                       → 401 "authentication required"
        valid session → request.state.principal = Principal(user_id, email, roles)
```

**Public surface** (never requires a session):
`/api/auth/*`, `/auth/*`, `/api/health`, `/health`, `/docs`, `/redoc`,
`/openapi.json`, `/`, and **`GET /api/security/mode`** (GET only! — the SPA
must be able to read the gate status before login; the POST stays protected
because a public POST would inherit the open SYSTEM principal and let anonymous
callers disable security).

**The `Principal`** (frozen dataclass) is what handlers actually consume:

```python
Principal(user_id, email, roles)
  .is_admin             → "admin" in roles
  .can_read_classified  → is_admin or "read:classified" in roles

SYSTEM_PRINCIPAL = Principal("system:hyperlink-engine", "", ("admin", "read:classified"))
```

Handlers read it via `Depends(get_principal)` — uniformly, whether the gate is
on (real user) or off (SYSTEM_PRINCIPAL).

---

## 8. Login flow — every step, every cookie

The SPA does **not** use the `supertokens-auth-react` SDK. It calls the
backend-mounted SuperTokens REST routes with plain `fetch` + cookies
(`frontend/src/api.ts`). Same-origin via the Vite proxy, so cookies just work.

### 8.1 Sign-up / sign-in request

```http
POST /api/auth/signup        (or /api/auth/signin)
Content-Type: application/json

{
  "formFields": [
    { "id": "email",    "value": "admin@sunpharma.test" },
    { "id": "password", "value": "Passw0rd!123" }
  ]
}
```

Success response body: `{"status": "OK", "user": {"id": "<uuid>", ...}}`.
Failure statuses you'll see:

| Status | Meaning |
|---|---|
| `WRONG_CREDENTIALS_ERROR` | Bad email/password on signin |
| `FIELD_ERROR` | Validation failed — including "email already exists" on signup (newer cores report duplicates this way, not only as `EMAIL_ALREADY_EXISTS_ERROR`) |

### 8.2 What the response sets (cookie mode)

| Cookie / header | Type | Purpose |
|---|---|---|
| `sAccessToken` | httpOnly cookie | The session JWT. Sent automatically on every request; verified **locally** by the backend (no core call) |
| `sRefreshToken` | httpOnly cookie, path-limited to `/api/auth/session/refresh` | Used to mint a new access token when the old one expires |
| `front-token` | response **header** | Base64 session metadata readable by JS (we don't use it — we call `/api/me` instead) |
| `st-anti-csrf` | header (only if anti-CSRF enabled) | CSRF protection token |

> ⚠️ **Pinned to cookies on purpose.** SuperTokens ≥0.30 defaults to *header*
> tokens when the client doesn't send an `st-auth-mode` header — which plain
> `fetch` doesn't. We discovered this live: logins "succeeded" but no session
> stuck. The fix is server-side in `_init_sdk()`:
>
> ```python
> session.init(
>     cookie_secure=s.session_cookie_secure,
>     get_token_transfer_method=lambda _req, _new, _ctx: "cookie",
> )
> ```
>
> Cookies are non-negotiable here anyway: the SSE stream (`EventSource`) and
> `window.open` downloads **cannot attach Authorization headers** — the cookie
> riding along is what keeps them working behind the gate.

### 8.3 Session probe — `GET /api/me`

After login (or on every app load) the SPA calls:

```json
GET /api/me     →
{
  "user_id": "10af9536-5674-42e5-9d63-68f7b5fb3080",
  "email": "admin@sunpharma.test",
  "roles": ["admin"],
  "is_admin": true,
  "can_read_classified": true,
  "security_enabled": true
}
```

- Gate ON + no cookie → **401** → the SPA shows the Login screen.
- Gate OFF → returns the open `system:hyperlink-engine` principal (admin) — the
  UI renders the full single-user experience unchanged.

The email comes from a per-process `user_id → email` cache (`_email_of()` in
the middleware) — resolved from the core once per user, so per-request session
verification stays a pure local JWT check.

### 8.4 Sign-out

```http
POST /api/auth/signout      → clears both cookies, revokes the session in the core
```

### 8.5 Full sequence diagram

```
Browser                FastAPI :8000                 Core :3567        Postgres
  │ GET /api/security/mode (public)                                        │
  │──────────────────────►│ {"enabled": true, ...}                         │
  │ GET /api/me           │                                                │
  │──────────────────────►│ 401 (no cookie)        → SPA renders Login     │
  │ POST /api/auth/signin {formFields...}                                  │
  │──────────────────────►│── verify credentials ──►│── bcrypt check ─────►│
  │   Set-Cookie: sAccessToken, sRefreshToken  ◄────│   create session     │
  │◄──────────────────────│                                                │
  │ GET /api/me  (cookie) │ auth_guard: verify JWT locally ✓               │
  │──────────────────────►│ {user_id, email, roles:["admin"], ...}         │
  │ ... all /api/* calls now carry the cookie automatically ...            │
  │ POST /api/auth/signout│── revoke session ──────►│                      │
```

---

## 9. Roles, permissions & how an admin is made

Two roles, one permission — created automatically at boot by `bootstrap_roles()`:

| Role | Permissions | Sees |
|---|---|---|
| `admin` | `read:classified` | Everything; may mark uploads classified; may flip the Security toggle while it's ON |
| `user` | (none) | Unclassified only |
| *(no role — fresh signup)* | (none) | Same as `user`: unclassified only |

Roles travel inside the access token as the `st-role` claim, e.g.
`{"st-role": {"v": ["admin"], "t": ...}}`. The middleware reads
`payload["st-role"]["v"]` into `Principal.roles`.

> **Important:** the claim is computed **when the session is created**. Granting
> a role to a logged-in user does nothing until they **sign out and back in**
> (fresh session → fresh claim).

### Granting the admin role (core CDI API)

There is no app endpoint for this (POC) — you talk to the core directly. The
core is bound to `127.0.0.1:3567`, so this can only be done from the host:

```powershell
# 1. Find the user's id (by email)
Invoke-RestMethod -Uri "http://127.0.0.1:3567/users?limit=20" -Headers @{ rid = "" } |
  ConvertTo-Json -Depth 6

# 2. Grant the role
Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:3567/recipe/user/role" `
  -Headers @{ rid = "userroles"; "Content-Type" = "application/json" } `
  -Body '{"userId": "<the-uuid>", "role": "admin"}'
# → {"status":"OK", ...}

# 3. Revoke it again
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:3567/recipe/user/role/remove" `
  -Headers @{ rid = "userroles"; "Content-Type" = "application/json" } `
  -Body '{"userId": "<the-uuid>", "role": "admin"}'
```

curl equivalents:

```bash
curl -X PUT http://127.0.0.1:3567/recipe/user/role \
  -H "rid: userroles" -H "Content-Type: application/json" \
  -d '{"userId": "<uuid>", "role": "admin"}'
```

If you set `HYPERLINK_SUPERTOKENS_API_KEY`, add `-H "api-key: <key>"` to every
core call.

---

## 10. Classification gate (Feature B) — the rules

### At upload (`POST /api/pipeline/upload`, form field `classification`)

| Caller | Sends `classified` | Sends `unclassified` | Sends nothing |
|---|---|---|---|
| Gate OFF (anyone) | classified | unclassified | `HYPERLINK_DEFAULT_CLASSIFICATION` (= classified) |
| Gate ON, **admin** | classified | unclassified | settings default |
| Gate ON, **user** | **403** | unclassified | **forced unclassified** — never the classified default, so users can't lock themselves out of their own runs |
| Bogus value | **400** | | |

Every upload stamps `owner = principal.user_id` and writes a `pipeline_upload`
audit line with the classification.

### At read — `require_classified_access`

Attached to **all 22 run-scoped endpoints** (`status`, `results`, `links`,
`anomalies`, `score`, `detection-trace`, `document-preview`, `stage-preview`,
`snippet`, `stages`, `advance-stage`, both exports, both downloads, the SSE
`stream`, the `PATCH link` editor, run start, review `approve`/`reject`, and
the Compliance Gate `GET /api/compliance/{run_id}` + `…/submit` — the last
four were added 2026-06-10 after a live finding that the Compliance Gate
answered a non-cleared user with the full checklist for a classified run):

```
gate ON  +  run.classification == "classified"  +  caller lacks read:classified  →  403
run not found → falls through, the endpoint's own 404 stays authoritative
gate OFF → no-op
```

### At list

`GET /api/pipeline/runs` and `GET /api/review/queue` silently drop classified
runs for non-cleared callers (filtered *before* the previewable-fallback logic
so a sparse list can never resurrect a hidden run). `/api/dossiers` (the seeded
demo store) has no classification concept — legacy data is unclassified by
definition and stays visible.

### Persistence

`classification`/`owner` are written to the Neo4j `Run` node by `persist_run()`
and restored by `fetch_runs()` hydration. **Legacy Run nodes without the
property hydrate as `unclassified`** — a deliberate backward-compat tradeoff so
existing demo data stays visible.

---

## 11. Security toggle (Feature C)

| Call | Who may call | Effect |
|---|---|---|
| `GET /api/security/mode` | **everyone** (public, GET only) | `{"enabled": bool, "source": "settings"\|"override", "supertokens_available": bool}` |
| `POST /api/security/mode {"enabled": true/false}` | gate OFF → anyone; gate ON → **admin only** (403 otherwise; 401 anonymous) | Flips the gate live, persists to `output/.security_mode`, writes a `security_mode_changed` audit line |

Resolution order for the effective flag:
**runtime override (the persisted file / button) → else `HYPERLINK_AUTH_ENABLED` env.**

UI behavior (`App.tsx` header): green `🔐 Security ON` / amber `🔓 Security OFF`
chip; admins see the Disable/Enable button; a warning banner appears when the
gate is OFF **via an explicit admin override** (not when it's merely off by
default). The Enable button is hidden if the backend reports
`supertokens_available: false` — enabling then would fail closed and 503 every
request.

---

## 12. Identity binding (audit trail)

With the gate active, the logged-in identity wins over anything in the request
body:

- `POST /api/review/{run}/approve|reject` → `reviewer = principal.email or user_id`
  (body `reviewer` is demo-only fallback when the gate is off)
- Compliance submit → same binding
- Audit lines (`audit.jsonl`) → `actor = principal.user_id`

Verified live: an approval by `admin@sunpharma.test` records
`"reviewer": "admin@sunpharma.test"`.

---

## 13. Frontend flow (SPA)

```
main.tsx → App → <AuthProvider>
                    │ on mount:
                    │  GET /api/security/mode   (public — works pre-login)
                    │  GET /api/me              (401 → user = null)
                    ▼
                 <AppGate>
                    ├─ loading        → render nothing (no login flash)
                    ├─ enabled && !user → <Login />        (email+password form)
                    └─ otherwise      → <AppShell />       (the normal app)
```

- Every `fetch` in `api.ts` uses `credentials: "include"`.
- Any 401 anywhere dispatches a `hyperlink:unauthorized` window event → the
  Auth context re-probes → expired sessions land back on Login.
- `api.auth.login/signup/logout`, `api.security.mode/setMode` wrap the REST
  calls from §8.
- Pipeline upload card shows a **Classification** select (only when gate ON and
  the user is admin). RunSelector prefixes classified runs with 🔒 (admins only
  ever see them anyway).
- POC gap: no automatic token refresh — when the access token expires the next
  call 401s and you log in again.

---

## 14. Running it — step by step

### A. Default mode (no auth — exactly the old app)

```powershell
# nothing to do. HYPERLINK_AUTH_ENABLED defaults to false.
# No SuperTokens containers or SDK needed. Suite green as-is.
```

### B. Full auth mode

```powershell
# 1. Start the identity infrastructure (core + its Postgres)
cd "C:\Zensar\Hyperlink automation\hyperlink-engine\infra\docker"
docker compose up -d supertokens-db supertokens-core
# health check → returns "Hello"
Invoke-WebRequest http://127.0.0.1:3567/hello -UseBasicParsing

# 2. Install the optional auth extra (once)
cd ..\..\backend
poetry install -E auth          # or: .venv\Scripts\pip install "supertokens-python>=0.31,<0.32"

# 3. Run the backend with the gate ON
$env:HYPERLINK_AUTH_ENABLED = "true"
$env:PYTHONPATH = "C:\Zensar\Hyperlink automation\hyperlink-engine\backend\src"
..\.venv\Scripts\python.exe -m uvicorn hyperlink_engine.api.app:app --port 8000

# 4. Frontend
cd ..\frontend
npm run dev                     # http://localhost:5174 → Login screen appears
```

### C. Test accounts (already in the local core's Postgres volume)

| Email | Password | Role | Sees |
|---|---|---|---|
| `admin@sunpharma.test` | `Passw0rd!123` | `admin` | everything; can classify uploads; can flip the Security toggle |
| `officer@sunpharma.test` | `Passw0rd!123` | *(none)* | unclassified only |

> These are **local dev accounts** living in the `supertokens_db_data` Docker
> volume on this machine only. `docker volume rm` wipes them. Never reuse these
> credentials anywhere real.

New users: click **Sign up** on the login screen (POC convenience). Fresh
accounts have no roles → unclassified-only until granted a role per §9.

---

## 15. Endpoint reference

| Endpoint | Auth (gate ON) | Notes |
|---|---|---|
| `POST /api/auth/signup` / `signin` / `signout`, `POST /api/auth/session/refresh` | public | Mounted by the SuperTokens middleware |
| `GET /api/health`, `/docs`, `/openapi.json`, `/` | public | |
| `GET /api/security/mode` | public | Gate status for the SPA |
| `POST /api/security/mode` | session; **admin** to disable while ON | Audit-logged |
| `GET /api/me` | session | The SPA's probe; 401 = show login |
| `POST /api/pipeline/upload` | session; **admin** to mark classified | Stamps owner + audits |
| `GET /api/pipeline/runs`, `GET /api/review/queue` | session | Classified filtered for non-cleared |
| All `/api/pipeline/run/{id}/**`, `/api/pipeline/status|stream/{id}` | session **+ classification gate** | 403 on classified runs for non-cleared |
| Everything else (`/api/dossiers/**`, review approve/reject, compliance) | session | Identity-bound where it signs anything |

Status-code cheat sheet: **401** no/expired session · **403** logged in but not
allowed (non-admin flip, classified access, classified upload) · **503** gate is
ON but the session layer is unavailable (SDK missing/uninitialised — fail
closed, never fail open) · **400** bogus classification value.

---

## 16. How the test suite works without a core

`tests/conftest.py` provides:

- `make_principal(roles=...)` — builds a `Principal` (default admin).
- `login_as(app, principal)` — overrides the two dependencies on a
  `create_app()` instance via `app.dependency_overrides`:
  `auth_guard` → no-op, `get_principal` → returns the pinned principal.
  Because `require_classified_access` consumes `Depends(get_principal)` as a
  sub-dependency, the override reaches the classification gate too.
- autouse `_reset_security_mode` — clears the runtime override + persisted file
  around every test.
- `mw.set_auth_override(True)` inside a test activates enforcement without env.

So role/classification behavior is fully testable offline:
`tests/unit/api/test_auth_security.py` (toggle, fail-closed, `/api/me`,
identity binding, GET-public/POST-protected) and
`tests/unit/api/test_classification.py` (upload rules, list filtering, 403s).

---

## 17. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Login "succeeds" but `/api/me` is still 401 | Header-vs-cookie pitfall (§8.2). The server pins cookie mode — if you removed `get_token_transfer_method`, put it back |
| Granted `admin` but `/api/me` shows no roles | Roles are baked into the session at creation. **Sign out and back in** |
| Every request 503s after enabling the gate | `supertokens-python` not installed (`poetry install -E auth`) or the core is down (`docker compose up -d supertokens-core supertokens-db`). This is fail-closed by design |
| Gate is ON even though `HYPERLINK_AUTH_ENABLED=false` | A persisted admin override: delete `backend/output/.security_mode` |
| Anonymous user can read the gate status — bug? | No: `GET /api/security/mode` is deliberately public (GET only) so the SPA can decide to show Login. POST is protected |
| Signup returns `FIELD_ERROR` for an existing email | Newer cores report duplicates as a field error, not only `EMAIL_ALREADY_EXISTS_ERROR`. Treat any non-OK as "try signin" |
| Old demo runs disappeared for a user | They didn't — they hydrate as `unclassified` and stay visible. If a run is hidden, it's a real `classified` run and the caller lacks clearance |
| SSE stream or CSV download breaks behind the gate | They rely on the session **cookie** (can't set headers). Check the request carries `sAccessToken`; check `credentials: "include"` in `api.ts` |

---

## 18. POC → production gaps (deferred, by decision)

- SSO / SAML to the corporate directory (SuperTokens third-party recipe)
- E-signature into the reserved `signature_id` audit slot (21 CFR Part 11 e-sig)
- Password policy, account lockout, email verification, password reset flows
- Automatic session refresh in the SPA (currently: expired token → re-login)
- Locking the Security toggle behind ops/break-glass in production
- Per-user clearance tiers (currently binary classified/unclassified)
- Disabling public self-service signup
- Pinning the core image to a concrete tag + setting a real `API_KEYS` value
- IQ/OQ/PQ validation documentation
- Self-hosting the Admin Dashboard's static assets (§19 — currently loaded from the jsDelivr CDN, which a strict air-gapped deployment can't reach)

---

## 19. Admin Dashboard — built-in web UI for users, sessions & roles

SuperTokens ships an optional **Dashboard recipe** — a ready-made admin UI. It is now
**enabled** in this project (`dashboard.init()` in the recipe list in
`api/middleware/__init__.py::_init_sdk`).

**Open it:** <http://localhost:8000/api/auth/dashboard> (or through the Vite proxy at
`http://localhost:5174/api/auth/dashboard`). It is served by the SuperTokens ASGI
middleware, which runs *before* FastAPI routing — so `auth_guard` never blocks it and
it works whether the Security gate is ON or OFF. It has its **own login**, separate
from app users.

**Login (local dev only — never reuse):** `admin@sunpharma.test` / `Passw0rd!123`.
Dashboard users are a distinct account type stored in the core's Postgres; this one was
created via the core CDI:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:3567/recipe/dashboard/user" `
  -Headers @{ "rid" = "dashboard"; "Content-Type" = "application/json" } `
  -Body '{"email": "admin@sunpharma.test", "password": "Passw0rd!123"}'
```

**What you can do in it:** list and search all signed-up users, inspect a user's
sessions and metadata, revoke sessions, delete users, and manage roles (the
`userroles` recipe is active, so `admin` grants/revokes can be done here instead of
the raw CDI calls in §9). Note that role changes still only take effect at the user's
**next login** (claims are baked into the access token at session creation).

> ⚠️ **On-prem caveat:** the dashboard's HTML shell pulls its JavaScript/CSS bundle
> from `cdn.jsdelivr.net`, so the *browser* needs internet access to render it. Your
> user data never goes to the CDN — it flows only browser ↔ backend ↔ core — but for a
> strictly air-gapped deployment the recipe must be disabled or its static bundle
> self-hosted (listed as a production gap in §18).

Verified on 2026-06-10: `GET /api/auth/dashboard` → 200 HTML; dashboard signin → OK;
the dashboard users API returned both test accounts.

---

## 20. FAQ — where users live, how classification flows, Neo4j ↔ SuperTokens

### Q1. Is Postgres *inside* SuperTokens? How do I view signed-up / logged-in users?

Postgres is **not inside** SuperTokens — they are two separate containers:
`hyperlink-supertokens` (the core, the brain) and `hyperlink-supertokens-db`
(`postgres:16-alpine`, the storage). The core holds no data itself; everything lives
in that dedicated Postgres (volume `supertokens_db_data`), which is why users survive
restarts. The app's own database (Neo4j) is completely separate.

Three ways to view users:

1. **Admin Dashboard (easiest)** — see §19.
2. **Direct SQL** into the core's Postgres:
   ```powershell
   # Signed-up users (passwords exist only as bcrypt hashes — never viewable)
   docker exec hyperlink-supertokens-db psql -U supertokens -d supertokens `
     -c "SELECT user_id, email, to_timestamp(time_joined/1000) AS signed_up FROM emailpassword_users;"

   # Role assignments
   docker exec hyperlink-supertokens-db psql -U supertokens -d supertokens `
     -c "SELECT user_id, role FROM user_roles;"

   # Logged-in users = unexpired rows in session_info
   docker exec hyperlink-supertokens-db psql -U supertokens -d supertokens `
     -c "SELECT user_id, to_timestamp(created_at_time/1000) AS started, to_timestamp(expires_at/1000) AS expires FROM session_info;"
   ```
3. **Core CDI API** — `GET http://localhost:3567/users` (add the `api-key` header once
   one is configured).

The app itself only exposes `GET /api/me` — the *current* caller's identity, not a
user list. "Signed up" = a row in `emailpassword_users`; "logged in" = an unexpired,
unrevoked row in `session_info`.

### Q2. How is classified/unclassified set on a document, and how is it retrieved?

**Set — exactly once, at upload (write path):**

1. The *Classification* dropdown on the Pipeline upload card only renders for an
   **admin while security is ON** (`canClassify = mode.enabled && user.is_admin`).
   It is sent as a `classification` form field with the upload.
2. The upload endpoint applies the rules (§10): bogus value → 400; non-admin
   requesting "classified" → 403; non-admin uploads are **forced to unclassified**
   (anti-lockout); empty → server default `HYPERLINK_DEFAULT_CLASSIFICATION=classified`
   (deny-by-default).
3. The resolved value is stamped onto the run state
   (`PipelineState.new(classification=…, owner=…)`) and **persisted to Neo4j**
   (`persist_run` writes `r.classification` / `r.owner` on the Run node).

In the POC, classification is **immutable after upload** — there is no edit endpoint;
re-upload to change it.

**Retrieved (read path):**

1. On backend restart `run_store` rehydrates from Neo4j (`fetch_runs` returns
   `classification`/`owner`; legacy runs without the property default to
   `unclassified`).
2. **Lists** (`/api/pipeline/runs`, `/api/review/queue`) filter classified runs out of
   the response for non-admins — a plain user never even sees they exist.
3. **Direct reads** — 22 run-scoped endpoints (previews, links, snippet, exports,
   downloads, the SSE stream, …) carry `Depends(require_classified_access)`: load the
   run's classification, return **403** unless the principal has
   `can_read_classified`. A nonexistent run still returns the endpoint's own 404.
4. With the Security toggle OFF, every request runs as the SYSTEM principal
   (admin-equivalent): the label is still *stored* but not *enforced*.

### Q3. Is there a connection between Neo4j and SuperTokens for classification?

**No direct connection — deliberately.** Neither system knows the other exists. They
answer different questions and only "meet" inside FastAPI middleware on each request:

```
Request → auth_guard:                 SuperTokens cookie → "WHO are you?"  → Principal(roles)
        → require_classified_access:  Neo4j-hydrated run → "WHAT is this?" → classification
        → compare the two            → allow (200) or deny (403)
```

Why this separation is correct:

- **Identity stays out of business data; business data stays out of identity.**
  SuperTokens' Postgres holds credentials/sessions/roles and nothing about documents;
  Neo4j holds documents and nothing about passwords. Linking them would couple two
  stores with very different security, backup, and audit requirements.
- **Roles are generic, labels are specific.** SuperTokens only says "this person is an
  admin"; Neo4j only says "this run is classified". Either side can change
  independently without touching the other.
- **Fail-closed stays simple.** If SuperTokens is unreachable while the gate is ON,
  everything 503s regardless of what Neo4j says — classification alone can never grant
  access.

The only identity that ever flows into the document side is plain text for
traceability: the uploader's id in the run's `owner` field and the user's email as
`actor`/`reviewer` in the audit trail (§12) — strings for the GxP record, never
credentials.

Request → auth_guard:  SuperTokens cookie  → "WHO are you?"  → Principal(roles)
        → require_classified_access:  Neo4j-hydrated run state → "WHAT is this doc?" → classification
        → compare the two → allow (200) or deny (403)
