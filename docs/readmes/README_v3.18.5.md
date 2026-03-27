# v3.18.5 — Person-to-Zone Mapping in Zone Manager

**Date:** 2026-03-26
**Tests:** 1172 passing (54 pre-existing)
**Review:** 2-review adversarial. 1 HIGH found and fixed (snapshot overwriting config data).

---

## Summary

Moved person-to-zone mapping from a non-functional JSON text field in HVAC Coordinator config to a proper multi-select person entity dropdown in each zone's config. HVAC coordinator builds the reverse map automatically with a 3-tier fallback chain for restart resilience.

Also includes: sleep protection options flow `data_description` fix from earlier in the v3.18.x cycle.

## Changes

### Person-to-Zone Mapping
- **Zone config flow:** New "Primary Persons" step in Zone Manager → zone config menu. Multi-select `person.*` entity dropdown with clear labels: "Select people who primarily live in this zone. When they arrive home, HVAC will pre-condition this zone before they reach it."
- **HVAC reverse map:** `_build_person_zone_map()` builds `{person: [zone_ids]}` from zone configs automatically. No manual JSON entry needed.
- **3-tier resilience:** On startup: (1) build from zone configs → (2) fallback to in-memory cache → (3) fallback to DB-persisted `__person_zone_map`. Logged at each fallback level.
- **Periodic persistence:** Person-zone map included in existing zone state snapshot (saved every 25 min + shutdown).
- **Zone status sensor:** `zone_persons` attribute added to existing `sensor.ura_hvac_coordinator_zone_X_status`.
- **HVAC coordinator sensor:** `person_zone_map` attribute shows full reverse map.

### Removed
- JSON text field (`CONF_PERSON_PREFERRED_ZONES`) from HVAC Coordinator config flow
- JSON parsing block from `__init__.py`

### Sleep Protection Fix
- Added `data_description` block to options flow `sleep_protection` step in `strings.json` and `translations/en.json`

## Files Modified

| File | Changes |
|------|---------|
| `hvac_const.py` | Added `CONF_ZONE_PERSONS` |
| `hvac_zones.py` | `zone_persons` on ZoneState, read in discovery, status attrs, snapshot |
| `hvac.py` | `_build_person_zone_map()`, 3-tier fallback, snapshot persistence |
| `config_flow.py` | `async_step_zone_persons`, zone_config_menu updated, HVAC JSON field removed |
| `__init__.py` | Removed CONF_PERSON_PREFERRED_ZONES parsing |
| `strings.json` | Zone persons labels + sleep protection data_description |
| `translations/en.json` | Same |

## Review Findings

See `docs/reviews/code-review/v3.18.5_person_zone_mapping.md`.

1 HIGH fixed: `restore_state_snapshot()` was overwriting fresh config-sourced `zone_persons` with stale snapshot data. Fixed by removing the restore line — config entry is source of truth.

## Tests

6 new tests in `TestPersonZoneMap`:
- Reverse map: single person, multi-zone, multi-person, empty
- Fallback: cache used when config empty, DB used when cache empty

## Deferred Items

| Item | Why |
|------|-----|
| Remove dead `CONF_PERSON_PREFERRED_ZONES` constant | Harmless, future cleanup |
| Remove deprecated `person_zone_map` constructor param | Backward compat |
| Copy person_zone_map dict before sensor attr exposure | Low risk |
| Automatic zone assignment from occupancy history | v4.0.0 Bayesian scope |
