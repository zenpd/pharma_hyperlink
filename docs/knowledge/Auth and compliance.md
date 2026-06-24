# Auth and compliance

Self-hosted auth, the classified-document gate, and the GxP compliance posture.

## How it works
- SuperTokens cookie sessions + admin/user roles, with a classified gate (`_CLASSIFIED_GATE`) on run-scoped endpoints: `api/app.py`. Master switch `HYPERLINK_AUTH_ENABLED` (default `false`).
- Local-only LLM enforcement (`enforce_local_llm_only`): `config/settings.py`, `core/detection/llm_disambiguator.py`.
- Never mutate originals — every output is a new `_linked` file ([[Injection layer]]); immutable audit trail to `audit.jsonl`: `audit/trail.py`.

## Gotchas
- `enforce_local_llm_only` is enforced only on the Ollama transport; the remote (Nvidia / LiteLLM) provider paths bypass it — keep `llm_provider=ollama` for real dossier data.

## Related
[[Detection cascade]] · [[Reports and review screens]] · [[Running the app]] · [[_Home]]
