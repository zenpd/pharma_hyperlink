# Run Compare and link navigation

The 3-pane BEFORE | AFTER | Linked-Documents viewer with clickable injected links.

## How it works
- Compare shell + click routing: `frontend/src/screens/RunCompare.tsx`; rendering, real HTML tables, highlighting, snippet popover and inline edit: `frontend/src/components/BeforeAfter.tsx`.
- Link routing via the single source of truth `externalUrl` / `isExternalLink`: external → new tab; cross-doc → Reference View ([[Reports and review screens]]); internal → scroll-and-flash in place.
- Snippet endpoint `GET /api/pipeline/run/{id}/snippet` and inline edit `PATCH /api/pipeline/run/{id}/link`: `api/app.py`.

## Gotchas
- Per-paragraph highlighting is scoped by `para_index` — a preview-only concern; the injected docx output is always correct.

## Related
[[Injection layer]] · [[Pipeline run and live status]] · [[Reports and review screens]] · [[_Home]]
