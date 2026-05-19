# URA v4.6.12 — Dashboard Aggregator Sensors (Cycle B)

**Released:** 2026-05-19
**Tier:** Tier 2-DB (user-escalated)

## Summary
Three new aggregator sensors for the URA Dashboard v5.0:

- **`sensor.ura_zones_with_motion`** — count of distinct zones with motion in the last 5 minutes. Reads room coordinators' `_last_motion_time`, deduplicates by `CONF_ZONE`. Bug-class #21-safe (tolerates naive datetimes), #14-safe (options-first config read).

- **`sensor.ura_hvac_system_demand`** — % of zones actively heating or cooling, formula `round(active / total * 100)` using `zone.hvac_action` from the HVAC zone manager (mirrors `hvac.py:1514`). Returns None when HVAC coordinator is unavailable or zero zones configured. Includes `load_bucket` attribute (idle/light/moderate/heavy).

- **`sensor.ura_energy_grid_demand`** — current grid import as % of configured grid cap. Reads `EnergyCoordinator._battery.net_power_w` and `_grid_import_cap_kw`. No clamp at 100% (dashboard surfaces excess). Includes `exporting` boolean attribute.

## Review ceremony
3x parallel reviewers. 1 CRITICAL + 2 HIGH + 4 MEDIUM + 3 LOW. CRITICAL addressed via minimum-viable (6 AST-introspection smoke tests proving production classes exist with expected shape); full mock-patch refactor deferred as test-infra debt (same class as v4.6.11 C.H2). See `docs/reviews/code-review/v4.6.12_dashboard_aggregator_sensors.md`.

## Notable fixes from review
- **C.C2 — Motion sensor duplicated iteration.** Extracted `_compute_zones_with_motion()` shared by both `native_value` and `extra_state_attributes` — eliminates TOCTOU risk and maintenance hazard.
- **C.M3 — HouseSystemDemand double-fetch.** `extra_state_attributes` now computes pct locally from the already-fetched zones snapshot instead of re-invoking the value property.
- **B.B1 — manifest.json version bump.** Auto-handled by `deploy.sh`.

## Tests
- 43/43 v4.6.12 tests pass (37 original + 6 new smoke tests).
- Full suite 0-delta vs `pre-review-v4.6.12` baseline (57 failed, 3300 passed — same 57 pre-existing).

## Live-validation acceptance
Post-restart, via WebSocket (per user directive — no soak, basic checks only):
1. `sensor.ura_zones_with_motion` exists, returns int ≥ 0.
2. `sensor.ura_hvac_system_demand` exists, returns int 0-100 OR None.
3. `sensor.ura_energy_grid_demand` exists, returns float OR None.
4. Each sensor's attributes match the plan keys (`active_zones`, `active_count`, `total_zones`, `load_bucket`, `formula` for HVAC; `grid_import_kw`, `grid_import_cap_kw`, `grid_import_cap_enabled`, `exporting` for grid demand; `zones`, `window_minutes` for motion count).
5. No `RuntimeWarning` or `TypeError` in HA logs referencing the three new sensors.

## What's next
- **v4.6.13** — Cycle C coordinator telemetry sensors (override frequency via compliance_log, success rate via compliance_log).
- **Dashboard v5.0 D3-D7** — live wiring of all 10 tabs against Cycle A/B/C sensors once v4.6.13 ships.
