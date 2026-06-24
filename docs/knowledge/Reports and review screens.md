# Reports and review screens

Dashboards, the focused Reference View, the review queue and the compliance sign-off gate.

## How it works
- Reports screens: `frontend/src/screens/Dashboard.tsx`, `ModuleMatrix.tsx`, `LinksTable.tsx`, `Issues.tsx`, `ExportCenter.tsx`, `DetectionTrace.tsx`.
- Reference View — lands on the definition, not the first mention: `frontend/src/screens/ReferenceView.tsx`.
- Review queue + compliance sign-off gate: `frontend/src/screens/ReviewQueue.tsx`, `ComplianceGate.tsx` → `/api/review/*` and `/signoff`.

## Gotchas
- Reports/Analysis screens follow the run picked in the Run Selector bar, else fall back to the seeded demo dossier.

## Related
[[Validation layer]] · [[Reporting and scoring]] · [[Run Compare and link navigation]] · [[_Home]]
