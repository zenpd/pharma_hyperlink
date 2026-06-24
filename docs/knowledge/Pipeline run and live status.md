# Pipeline run and live status

Upload documents, pick an agent profile, and watch the LangGraph nodes advance live.

## How it works
- Upload + run + live SSE status screen: `frontend/src/screens/Pipeline.tsx` → `POST /api/pipeline/upload`, `POST /api/pipeline/run/{id}`, `GET /api/pipeline/stream/{id}`.
- API client `frontend/src/api.ts`; backend routes in `backend/src/hyperlink_engine/api/app.py`.
- The Fast / Balanced / Max agent profile chosen here drives [[Orchestration and agents]].

## Gotchas
- The SSE stream drives the live node stepper; a completed run then feeds Run Compare and the Reports screens.

## Related
[[Orchestration and agents]] · [[Run Compare and link navigation]] · [[Reports and review screens]] · [[_Home]]
