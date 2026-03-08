# v3.9.4 — URA Dashboard (HAKit React Panel)

## Summary
Ships a built-in React dashboard that appears in the HA sidebar. Uses HAKit
(@hakit/core + @hakit/components) for real-time WebSocket entity subscriptions.
Displays all coordinator data in one unified view.

## Dashboard Panels
- **Presence** — house state badge, zone occupancy chips, confidence/census
- **Energy** — TOU period/rate, battery strategy, SOC, solar class, HVAC
  constraint (mode/offset/forecast temps/max runtime), import/export/cost today,
  load shedding status, Envoy availability
- **HVAC** — coordinator mode, arrester state, per-zone cards (preset, setpoints,
  current temp, HVAC action, override counts)

## Architecture
- React source in `dashboard/` (not shipped to users)
- Vite builds to `custom_components/.../frontend/` (committed, shipped via HACS)
- `__init__.py` registers iframe panel via `async_register_built_in_panel`
- HAKit connects via same-origin WebSocket (no extra auth needed)
- Non-English locales stripped from build (1.2MB vs 9.1MB)

## Files Changed
- `__init__.py` — panel registration (static path + iframe)
- `manifest.json` — added `http`, `frontend` dependencies
- `frontend/` — new directory with built React SPA
- `scripts/deploy.sh` — stages `frontend/` and `brand/` directories
- `.gitignore` — excludes `dashboard/node_modules/`

## New: dashboard/ source tree
```
dashboard/
  package.json, vite.config.ts, tsconfig.json, index.html
  src/
    main.tsx — HassConnect bootstrap
    App.tsx — coordinator layout shell
    types/entities.ts — typed entity ID constants
    hooks/ — useEnergyData, useHVACData, usePresenceData
    components/
      energy/EnergyOverview.tsx
      hvac/HVACOverview.tsx
      presence/PresenceOverview.tsx
      layout/CoordinatorCard.tsx
      shared/StatusBadge.tsx, EntityValue.tsx
    styles/globals.css
```
