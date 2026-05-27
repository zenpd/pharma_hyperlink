# Hyperlink Engine — React Dashboard (Phase 3)

> Production-grade frontend for the AI-Powered Hyperlink Automation & Validation Engine.
> Ported pixel-for-pixel from the Claude Design handoff under `docs/design/`.

## Stack

- **React 18 + Vite + TypeScript** (strict mode)
- **Design tokens via CSS custom properties** (`src/styles/tokens.css`) — light + dark themes are first-class, switched via the `.theme-dark` class on the root.
- **Inline styles + CSS classes** (no Tailwind in the POC — the README mandates Tailwind for production but the token system is self-contained CSS so screens render immediately without the build step). Migration path to Tailwind is documented in `docs/design/`.

## Routes (hash-based)

| Hash | Screen |
|---|---|
| `#/canvas` | All 12 artboards scaled down (the "design canvas" view) |
| `#/overview` | Screen 1 — Executive Summary |
| `#/modules` | Screen 2 — Module Drill-down |
| `#/links` | Screen 3 — Link Inspector (data state) |
| `#/links/empty` | Screen 3 — Empty state |
| `#/links/loading` | Screen 3 — Loading skeleton |
| `#/links/error` | Screen 3 — Error state |
| `#/anomalies` | Screen 4 — Anomaly Browser |
| `#/export` | Screen 5 — Export & Gate Center |
| `#/pipeline` | Screen 6 — Pipeline Run Detail |

## Run

```bash
cd src/hyperlink_engine/dashboard/react_frontend
npm install
npm run dev    # localhost:5173 — proxies /api → FastAPI backend on :8000
npm run build  # tsc + vite build → dist/
```

The Vite dev server proxies `/api/**` to `http://127.0.0.1:8000`, where the
FastAPI backend (`hyperlink_engine.dashboard.api`) lives. Start the backend
with:

```bash
uvicorn hyperlink_engine.dashboard.api:app --reload --port 8000
```

## Project layout

```
src/
  styles/
    tokens.css            ← design tokens (light + dark CSS variables)
  components/
    shared.tsx            ← Icon, SevChip, RadialGauge, TopBar, DossierBar,
                            ConfidenceMeter, Sparkline, TreeRow, CodePath
  screens/
    ExecSummary.tsx       ← Screen 1
    ModuleDrilldown.tsx   ← Screen 2
    LinkInspector.tsx     ← Screen 3 (incl. empty / loading / error)
    AnomalyBrowser.tsx    ← Screen 4
    ExportGate.tsx        ← Screen 5
    PipelineRun.tsx       ← Screen 6
  canvas/
    DesignCanvas.tsx      ← All-screens-at-once view (production analogue
                            of the original handoff's draggable canvas)
  App.tsx                 ← Hash router + theme switch
  main.tsx                ← Vite entrypoint
```

## Production hardening (Phase 4 — not in this POC)

The Phase 3 deliverable is a runnable, visually-faithful port. The
following production-grade upgrades are documented in
`docs/design/README.md` and tracked separately:

1. **Tailwind CSS** with `tailwind.config.ts` pre-mapped to the same token names.
2. **TanStack Query** for data fetching (replace the hardcoded mock data in each screen).
3. **TanStack Table + @tanstack/react-virtual** for the document and link tables (currently plain `<table>` — they must virtualize from day one because they're designed for ≥ 2,000 rows).
4. **Recharts** for the trend line, sparklines, and confidence segments (currently custom SVG).
5. **lucide-react** for icons (currently inlined as an `IconName` dictionary in `shared.tsx`).
6. **Radix UI** primitives for `Dialog`, `Popover`, `DropdownMenu`, `Combobox`, `Toast`, `Tooltip`, `Checkbox`.
7. **`cmdk`** for the ⌘K command palette (currently a visual placeholder in the TopBar).

## Accessibility checklist (already in place)

- Every icon-only button has an `aria-label`.
- Severity is always paired with an icon (`SeverityIcon`) *and* a label (`SevChip`) — never colour alone.
- Focus rings: 2px brand-blue ring with 2px surface offset via `--focus-ring`.
- Heatmap and trend chart compute text colour from background so contrast holds across the sequential scale.
- `prefers-reduced-motion` honoured by every animation (skeleton + tail-mode pulse use a single `@keyframes` rule that can be disabled in CSS).
- Error state explicitly states *"No data has been transmitted off-network"* — this is a regulated reassurance per 21 CFR Part 11.

## Caveats

- The design canvas (`/canvas`) hosts screens at 0.55× scale so all 12 fit
  on most monitors. Use the per-screen routes for pixel-accurate review.
- Compliance-side wiring (PIV smartcard signing, real audit-log writes,
  SAML/OAuth login) is intentionally absent in this POC. The dashboard
  shows the *UI* of those flows; the Phase 4 milestone wires them to the
  GxP audit-trail backend documented in `docs/gxp-compliance.md`.
