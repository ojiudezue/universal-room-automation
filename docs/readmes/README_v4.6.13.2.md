# URA v4.6.13.2 — Dashboard v5.0 complete (10/10 tabs) + lazy-load perf

**Released:** 2026-05-20
**Tier:** Patch (frontend-only update; no Python code changes vs v4.6.13.1)

## Summary
Closes the dashboard React port. **All 10 tabs are now live-wired** to URA sensors via `@hakit/core`'s `useEntity` hook. Plus a real first-paint perf win via `React.lazy` per tab.

## Tabs now LIVE — 10/10
v4.6.13.1 shipped 8 of these; v4.6.13.2 adds the last two.

- Diagnostics, Energy, Home, HVAC, Zones, Rooms, Presence, Safety (from v4.6.13.1)
- **House** (NEW) — whole-house roll-up: house state, power, cost today, motion zones, HVAC system demand card
- **Security** (NEW) — armed state, open entries, authorized guests, last lock sweep, security anomaly + alert + compliance; cameras + per-lock UI left as scaffolding (live MJPEG and install-specific lock entity-ids are deferred)

## Performance changes
1. **React.lazy per tab** — Each tab is now its own dynamic-import chunk. First paint only downloads the active tab's code (`Home-*.js`, ~5-15 KB gzip per tab), not all 10 eagerly. Tab switches lazy-load on first visit, then are cached for subsequent visits.
2. **Shared data hooks chunked** — `useUraSensor.ts` and `useCoordinatorSummary.ts` are now their own chunks shared across tabs. No duplication.
3. **Locale shards** — kept as the existing lazy-loaded per-locale chunks. Bundle on disk is large (~18 MB total across ~60 locales), but the dashboard only downloads ONE locale chunk on first paint (en-US). Attempted to fold them into a single chunk via manualChunks — abandoned because it bloated the hakit chunk to 18 MB which would have been eagerly loaded.

## What's still deferred (carry-over backlog)
- Controls-bar knobs across all tabs remain read-only (no service-wiring; needs Number/Switch entities)
- Camera live MJPEG tiles on Security tab
- Per-lock entity wiring on Security tab
- DB size sensor still reports "unknown" upstream (filed in `docs/TELEMETRY_LAYER.md` section 6)
- hakit issue #304 mitigation (panel_custom iframe destroy/recreate)
- Automation health card placeholders (Diagnostics) — needs an HA-side automation success-rate sensor

## Verified entity IDs for the new tabs

**House:**
- `sensor.ura_coordinator_manager_coordinator_summary` (house_state, coordinator counts)
- `sensor.universal_room_automation_zones_with_motion`
- `sensor.universal_room_automation_whole_house_power`
- `sensor.universal_room_automation_whole_house_cost_today`
- `sensor.universal_room_automation_hvac_system_demand`

**Security:** (all verified 2026-05-19/20 against live HA)
- `sensor.ura_security_coordinator_security_armed_state` = "disarmed"
- `sensor.ura_security_coordinator_security_open_entries` = 0
- `sensor.ura_security_coordinator_security_authorized_guests` = "none"
- `sensor.ura_security_coordinator_security_expected_arrivals` = 0
- `sensor.ura_security_coordinator_security_anomaly` = "nominal"
- `sensor.ura_security_coordinator_security_compliance` = 50.0
- `sensor.ura_security_coordinator_security_last_lock_sweep` = ISO timestamp
- `binary_sensor.ura_security_coordinator_security_alert` = off

## Acceptance
- Build green (vite 2.68s, 0 TS errors, lazy-loading working — each tab gets its own chunk)
- HACS install + restart proceeds normally
- Navigate to the URA Dashboard panel and click through all 10 tabs — every tab renders without console errors; values either show real data or `"—"` placeholders
- First-paint network tab in browser shows ~6-8 chunks downloading (vs ~12+ in v4.6.13.1)
