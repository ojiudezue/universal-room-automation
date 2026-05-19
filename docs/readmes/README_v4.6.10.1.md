# v4.6.10.1 — Dashboard v5.0 Mount Preview

**Date:** 2026-05-19 CDT
**Tier:** Tier 1 (hotfix — frontend payload only, no Python code changes)
**Predecessor:** v4.6.10 (Setup Telemetry + Anomaly Wiring Scaffold)

## Why

Mounts the in-progress Dashboard v5.0 (P6 fulcrum, light Navet-styled) as the URA Dashboard panel in HA so the user can validate aesthetics in the actual HA frontend instead of a local Vite folder. Exercises the full integration path (panel_custom + iframe + hakit) that v5.0.0's eventual ship will go through.

**This is a preview ship, not a feature ship.** Tab content is mock data extracted from the P6 prototype (no live entity wiring yet). The Python sensor cycles required for live wiring (A: attribute adds, B: aggregator sensors, C: coordinator telemetry against `ura_activity_log`) are filed in `docs/planning/DASHBOARD_BACKLOG.md` and queued for v4.6.11+.

## What you'll see

Open Home Assistant → sidebar → **URA Dashboard** (mdi:view-dashboard icon). The dashboard renders with:
- Left rail: 10 tabs across Overview / Systems / URA sections
- P6 light theme: off-white surface, pastel mood gradient keyed per tab
- Navet styling: leading-icon containers, top-edge highlights, pill action buttons, rail active indicator
- All 10 tab contents populated with realistic mock data (energy flow, person cards, coordinator health, safety detectors, etc.)
- Mobile-responsive: rail collapses to horizontal top-strip at ≤768px

## What's NOT live yet

Static mock data via `dangerouslySetInnerHTML` from extracted P6 HTML fragments. Controls don't fire service calls. Counts and statuses are illustrative.

This is deliberate — the shell-out establishes aesthetic confidence ahead of the Python sensor work. When `useEntity` wiring lands in v5.0.0, each tab's HTML fragment is incrementally replaced by proper JSX with hakit data subscriptions.

## Changes

### Frontend payload
- `frontend-v3/index.html` + `frontend-v3/assets/*` rebuilt from `dashboard-v3/` with `@hakit/core@6.0.2`
- `frontend-v3/ura-panel-v3.js` — panel bootstrap web component, simplified per @hakit v6 auth model (no postMessage token bridge needed; hakit auto-inherits from `window.top.hassConnection`)
- Vite base path corrected to `/universal_room_automation_panel_v3/` matching the static-path mapping in `__init__.py:2171`

### Python — unchanged
The panel registration in `__init__.py:2166-2189` (added in v3.12.0) already does the right thing. No Python diff in this release. The reason v3-era dashboard was broken (and is now fixed) was purely a build-output path mismatch + missing bootstrap file, both addressed in the frontend payload.

### Source repo additions (under `dashboard-v3/`)
- `src/components/layout/{Shell,Rail,MobileTabs}.tsx` — React shell
- `src/components/tabs-shell/{home,house,zones,rooms,energy,hvac,presence,security,safety,diagnostics}.html` — P6 content fragments
- `src/components/tabs-shell/TabShell.tsx` — single renderer via dangerouslySetInnerHTML
- `src/design/p6-shared.css` — verbatim copy of P6 prototype stylesheet (1607 LoC)
- `public/ura-panel-v3.js` — panel bootstrap source
- `playwright-shot.mjs` — visual diff tool (not deployed)

### Docs
- `docs/planning/PLANNING_v5.x_dashboard_v4_react_port.md` — full implementation plan (committed prior)
- `docs/planning/DASHBOARD_BACKLOG.md` — dashboard-specific tracking
- `docs/planning/DASHBOARD_v5_sensor_audit.md` — gap categorization (a/b/c/d) for every value in P6, sized in LoC per cycle

## Known limitations

1. **Tab content is mock.** Don't interpret values shown (anomaly counts, energy figures, person locations) as reflecting current URA state — they're from the P6 design mockup. Live wiring lands in v5.0.0.

2. **hakit issue #304 — iframe-recreation after tab hide.** `panel_custom` + iframe means HA may destroy and recreate the iframe when you return to the URA Dashboard panel after backgrounding the tab for >5 min. The SPA re-mounts but the WebSocket may be mid-reconnect. **Workaround:** hard-refresh (Cmd+R). **Fix:** v5.0.1 — cache the iframe DOM node across the panel's disconnectedCallback so the SPA isn't torn down. Tracked in DASHBOARD_BACKLOG.md.

3. **Controls do not yet fire services.** Sliders, toggles, buttons render but don't currently wire to HA service calls. That's D3-D7 work post-Python-cycle.

## Tests

No new tests this release (frontend-only payload; Python tests unchanged).

Build verification: `npm run build` from `dashboard-v3/` produces clean output to `custom_components/universal_room_automation/frontend-v3/`. Vite asset paths resolve to the same URL pattern that the panel's StaticPathConfig serves.

Visual fidelity verification: Playwright screenshot diff against the source `p6-light-styled.html` prototype at 1400×900 (desktop) and 480×900 (mobile) — both passing within the 3-round iteration cap.

## Commits

```
e578dcc Dashboard v5.0: upgrade @hakit/core 4.0.4 → 6.0.2 + simplify auth bridge
84b4de0 Dashboard v5.0: restore panel bootstrap + fix Vite base path to match HA panel URL
a136483 Dashboard v5.0 D3-D7 shell-out: all 10 tabs P6-pixel-perfect via static HTML
4e01fc9 Dashboard v5.0 D1: Foundation (P6 light Navet-styled shell)
```
