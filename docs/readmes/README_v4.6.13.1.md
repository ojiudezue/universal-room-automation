# URA v4.6.13.1 — Dashboard v5.0 Live Wiring (8/10 tabs)

**Released:** 2026-05-19
**Tier:** Patch (frontend-only update; no Python code changes vs v4.6.13)

## Summary
First substantive port of the URA Dashboard v5.0 React app from static HTML stubs to live HA-entity components via `@hakit/core`'s `useEntity` hook. 8 of 10 tabs now render real data from the URA sensor surface that shipped in v4.6.10–v4.6.13.

## Tabs now LIVE (8)
- **Diagnostics** — per-coordinator decisions/override/compliance/last-decision cards backed by the 21 v4.6.13 sensors; decision stream timeline
- **Energy** — TOU period, grid demand %, battery SoC/power, solar production (current + today), URA energy cost
- **Home** — house state, zone motion count, coordinator overview, latest decision per coordinator
- **HVAC** — system demand %, per-zone iteration (status + setpoints from zone_manager)
- **Zones** — house-level zone breakdown card
- **Rooms** — per-room cards (19 rooms in this install)
- **Presence** — house state pill, transit signals, room occupancy
- **Safety** — hazards, safety_events_summary, anomaly status

## Tabs still on HTML stubs (2)
- **Security** — full port in next cycle
- **House** — house-level overview; smallest static fragment, fast to port next

## Shared helpers (architecture)
- `dashboard-v3/src/data/useUraSensor.ts` — base hook utilities (`useUraSensorState`, `useUraSensorInt`, `useUraSensorFloat`, `useUraSensorAttrs<T>`, `formatRelativeTime`, `formatClockTime`)
- `dashboard-v3/src/data/statusColors.ts` — `statusToCardClass`, `statusToBadge`, `num`
- `dashboard-v3/src/data/useCoordinatorSummary.ts` — typed access to `sensor.ura_coordinator_manager_coordinator_summary` attributes
- `dashboard-v3/src/components/tabs-shell/TabShell.tsx` — routes 8 tabs to React components, 2 still HTML

## Verified entity IDs (today, against live HA)
- `sensor.universal_room_automation_house_state`
- `sensor.universal_room_automation_whole_house_power` + `_cost_today`
- `sensor.universal_room_automation_zones_with_motion`
- `sensor.universal_room_automation_hvac_system_demand`
- `sensor.universal_room_automation_energy_grid_demand`
- `sensor.ura_energy_coordinator_tou_period`
- `sensor.envoy_482543015950_battery` (single-install — hardcoded per memory rule)
- `sensor.envoy_482543015950_current_battery_discharge`
- `sensor.envoy_482543015950_current_power_production`
- `sensor.envoy_482543015950_energy_production_today`
- `sensor.ura_coordinator_manager_coordinator_summary` (attrs: status_per_coordinator, house_state, decisions_today, etc.)
- v4.6.13 telemetry sensors (5x each of decisions_today, override_frequency, compliance_rate, last_decision)

## Known limitations (next cycle)
- 2 tabs (Security, House) still served as HTML
- Controls bar knobs all read-only across all tabs — backing entities for runtime control don't exist yet
- Automation health card (Diagnostics) renders placeholders — no HA-side automation success-rate sensor exists
- DB size sensor reports "unknown" (filed as backlog in `docs/TELEMETRY_LAYER.md` section 6)
- Some entity IDs in Rooms/Zones/Presence/Safety marked `TODO(entity-id):` in source — will need live-load verification

## Backing telemetry layer
See `docs/TELEMETRY_LAYER.md` for the full map of sensor surfaces, signal flows, and the "synthesis" sections on composition model + seams + anti-patterns.

## Live-validation acceptance
After HACS install + restart:
1. URA Dashboard panel loads without console errors
2. Navigate to each of the 8 live tabs — every card renders either a value, a `"—"` placeholder, or `"unavailable"` text (no crashes)
3. Values match the corresponding `sensor.*` entity state in HA Developer Tools
4. The 2 remaining HTML tabs (Security, House) still render their static design
