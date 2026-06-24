# ADR-0002 — Dossplorer Integration Contract

* **Status:** Proposed (Phase 1, finalized Phase 3 Week 11)
* **Date:** 2026-05-26
* **Deciders:** Engineering lead, Maikel Bouman (Celegence publishing), Dossplorer platform owner
* **Supersedes:** —
* **Related:** ADR-0001 (docx hyperlink approach)

## Context

The Hyperlink Engine generates per-document QC reports, readiness scores, and
anomaly flags for regulatory dossiers. Reviewers do not look at the engine's
own dashboard in isolation; they consume those results inside **Dossplorer™**,
Celegence's review UI. The engine must therefore push results to Dossplorer
and pull dossier metadata back.

Phase 1 cannot make live Dossplorer calls — credentials and a Celegence VPC
test environment will not be available until Phase 3. We need to define the
contract now so:

1. The Phase 1 mock client (`MockDossplorerClient`) matches the eventual live
   shape and tests run against a realistic surface.
2. The Phase 3 work to swap mock → live is purely substitution of one class,
   not redesign of downstream code.
3. The Dossplorer team can review the contract before they expose endpoints,
   avoiding rework on either side.

## Decision

The integration uses a small HTTPS+JSON REST surface, authenticated with
OAuth 2.0 client credentials, scoped per submission sponsor. The engine never
stores credentials in code; tokens are read from environment variables managed
by the on-prem secret store (Vault in production).

### Endpoints (v1)

| Verb | Path | Purpose | Auth scope |
|------|------|---------|------------|
| `GET`  | `/v1/dossiers/{dossier_id}`                | Pull dossier metadata (sponsor, type, sequence, study IDs) | `dossier:read` |
| `POST` | `/v1/dossiers/{dossier_id}/qc-reports`     | Push a readiness score + summary for one engine run         | `dossier:write` |
| `POST` | `/v1/dossiers/{dossier_id}/anomaly-flags`  | Push one anomaly flag (per-document)                        | `dossier:write` |
| `GET`  | `/v1/dossiers/{dossier_id}/sequences`      | List sequences (`0001`, `0002`, …)                          | `dossier:read` |
| `POST` | `/v1/dossiers/{dossier_id}/audit-events`   | Append an entry to the audit trail (21 CFR Part 11)         | `dossier:write` |

### Payload — `GET /v1/dossiers/{id}` (response)

```json
{
  "dossier_id": "DOS-2026-001",
  "sponsor": "SunPharma",
  "submission_type": "NDA",
  "region": "US",
  "sequence_number": "0001",
  "study_ids": ["MED-2020-026", "NCT46913810"],
  "submitted_at": null,
  "status": "draft"
}
```

This response is the on-the-wire shape of `DossierMetadata` in `models.py`.
Adding a field to the model is backwards-compatible; renaming or removing a
field is breaking and requires a contract version bump.

### Payload — `POST /v1/dossiers/{id}/qc-reports` (request)

```json
{
  "sequence_number": "0001",
  "score": 87.5,
  "broken_links": 4,
  "anomalies": {"blocker": 0, "warning": 7, "info": 12},
  "engine_version": "0.2.0",
  "generated_at": "2026-05-26T14:33:12Z",
  "report_artifact_uri": "file:///output/DOS-2026-001/0001/report.csv"
}
```

### Payload — `POST /v1/dossiers/{id}/anomaly-flags` (request)

```json
{
  "document": "m2/2-5-clin-overview/2-5-clin-overview.docx",
  "severity": "warning",
  "kind": "blue_text_no_link",
  "message": "Run colored blue but no hyperlink attached",
  "location": {"paragraph_index": 12, "run_index": 3, "char_start": 45, "char_end": 67},
  "suggested_fix": "Inject internal anchor to Section 2.7.3"
}
```

### Authentication

* **Phase 1 (mock):** no token; the mock client uses a local JSON fixture.
* **Phase 3 (live):** OAuth 2.0 client-credentials flow. Token obtained from
  Dossplorer's `/oauth/token` endpoint at engine start and refreshed via
  expiry-aware logic. Token + base URL come from:

  ```
  HYPERLINK_DOSSPLORER_MODE=live
  HYPERLINK_DOSSPLORER_BASE_URL=https://dossplorer.celegence.local
  HYPERLINK_DOSSPLORER_TOKEN=<short-lived access token>
  ```

  Per the on-prem mandate (ADR-0001 §Privacy), the token never leaves the
  customer VPC. The client refuses to operate over plain HTTP except against
  `127.0.0.1` (developer workstations).

### Error handling

| HTTP status | Engine behavior |
|-------------|-----------------|
| `2xx` | Treated as success; payload validated against schema |
| `401` / `403` | Refresh token once, retry once, then surface a `DossplorerError` |
| `404` | Surface `DossplorerError("dossier not found")` — never auto-create |
| `409` | Retry with exponential backoff (up to 3 attempts) |
| `5xx` | Retry with exponential backoff (up to 5 attempts), then surface error |
| Network error | Retry; preserve payload to retry queue (Redis) for next pipeline tick |

### Idempotency

`POST` endpoints require an `Idempotency-Key` header — the engine uses
`{dossier_id}:{sequence}:{sha256(payload)}`. Re-pushing identical results is
a no-op on the Dossplorer side and **must not** create duplicate records in
the review UI.

### Webhook (reverse direction, Phase 3+ optional)

Dossplorer **may** post back to `/api/dossplorer/webhook` on the engine's
FastAPI surface to notify of:

* SME approvals / rejections of anomaly flags
* New sequence published (triggers re-validation)
* Submission status changes (`draft` → `submitted` → `approved`)

The Phase 1 mock does not expose a webhook.

## Consequences

* **Positive:**
  * Downstream code (dashboard, reporting) targets one Protocol; mock and
    live clients are drop-in replacements.
  * Contract is reviewable by Dossplorer team before any wire bits exist.
  * Auth strategy is decoupled from business logic — easy to swap to SAML or
    mutual-TLS later without touching the engine.

* **Negative:**
  * Until Phase 3, every push silently succeeds against the in-memory buffer.
    Tests assert against `pushed_scores` / `pushed_anomalies`, but no
    end-to-end push has been validated yet.
  * Schema evolution requires coordination — the contract version header is
    `X-Hyperlink-Contract: v1` and must bump whenever a breaking change lands.

## Open Questions

1. Does Dossplorer prefer one anomaly per request, or batched arrays?
   *(Defer to Week 11 design call; mock supports both shapes already.)*
2. Should `audit-events` flow through Dossplorer or stay engine-local?
   GxP review will decide.
3. Retry-queue backing store — Redis (already in the stack) vs a SQLite
   spool? Phase 3 will benchmark.
