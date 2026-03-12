# v3.12.3 — Dashboard v3 Panel Hotfix

## Fix
- `ura-panel-v3.js` was deleted by Vite's `emptyOutDir: true` during locale cleanup rebuild
- Changed v3 build config to `emptyOutDir: false` with pre-clean of assets directory only (matching v2 pattern)
- Panel wrapper JS file now survives rebuilds

## Files Changed
- `frontend-v3/ura-panel-v3.js` — Recreated (WebComponent wrapper for v3 dashboard)
- `dashboard-v3/vite.config.ts` — `emptyOutDir: false`
- `dashboard-v3/package.json` — Pre-clean assets dir before build
