# v3.12.2 — Dashboard v3 + Dashboard v2 Rebuild + Test Inbound Service

## Dashboard v3 ("URA Dashboard")
- New React dashboard built with @hakit/core, Recharts, and Lucide icons
- Registered as separate sidebar entry "URA Dashboard" (icon: `mdi:view-dashboard`)
- Original "URA" dashboard remains intact at `/ura-dashboard`
- v3 accessible at `/ura-dashboard-v3`
- WebComponent wrapper (`ura-panel-v3.js`) injects auth via postMessage
- Build outputs to `frontend-v3/` with locale cleanup (English-only)
- Manual chunks: vendor (react/react-dom), hakit (@hakit/core), charts (recharts)

## Dashboard v2 Rebuild
- **DiagnosticsTab**: Card-based layout, health tiles, detection layers
- **PresenceTab**: Card-based room/person layout, improved zone display
- **RoomsTab**: Room cards with occupancy, sensors, device controls
- **SecurityTab**: Lock/alarm control cards with confirmation dialogs
- **globals.css**: Expanded glass morphism styles, card layouts, responsive grid

## Test Inbound Service
- `universal_room_automation.test_inbound` service for simulating inbound text replies
- Fields: `text` (message), `channel` (companion/whatsapp/pushover/imessage)
- Tests response dictionary, safe word, and silence mechanisms

## Files Changed
- `__init__.py` — Second panel registration for `frontend-v3/`
- `services.yaml` — `test_inbound` service definition
- `frontend-v3/` — New directory with built v3 dashboard assets
- `frontend/` — Rebuilt v2 dashboard assets
- `dashboard-v3/` — Build config (package.json, tsconfig.json, vite.config.ts)
- `dashboard/` — Source changes (4 tabs + globals.css)
