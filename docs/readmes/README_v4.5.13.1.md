# v4.5.13.1 — HVAC Zone Dedup Hotfix

**Date:** 2026-05-12
**Type:** Tier 1 hotfix
**Predecessor:** v4.5.13 (live-validated; the duplication this hotfix addresses was discovered during that validation)

## Summary

v4.5.12 shipped per-zone D7 sensors that didn't deduplicate when two URA "home zones" shared a single physical thermostat (e.g., Entertainment + Master Suite both pointing at `climate.thermostat_bryant_wifi_studyb_zone_1`). The result was duplicate sensors reading the same source, plus a phantom `Zone 4` whose status sensor displayed `unknown`. This hotfix introduces a shared canonical-zone helper that all per-zone platform setup paths now use, eliminating the duplication and harmonizing cross-platform zone_id derivation.

15 new tests, including 2 lockstep equivalence tests that run the helper and `ZoneManager.async_discover_zones` against identical fixtures to guard against silent drift.

## What's fixed

### Per-zone entity duplication (sensor.py)

`sensor.py:280-313` (D7 + HVACZoneStatus + HVACZonePreset registration) was iterating Zone Manager config zones and creating one set of entities per **home zone**, not per **physical HVAC zone**. With 4 home zones sharing 3 physical thermostats, v4.5.12 created 4 entities where 3 should have existed — the 4th was a phantom referring to a ZoneManager zone that never existed.

**Fix:** replaced the inline loop with a call to `iter_canonical_hvac_zones(hass)`. The helper deduplicates by thermostat, mirrors ZoneManager's zone_id derivation, and produces merged names for shared-thermostat zones.

### Cross-platform zone_id drift (button.py, number.py)

`button.py:_discover_ac_zones` and `number.py:_discover_ac_zones` had local dedup helpers that worked correctly (no duplicates) but derived zone_ids differently than ZoneManager:
- Old: `thermostat.replace("climate.", "").replace(".", "_")` → `back_hallway_zone_3`
- ZoneManager: `_zone_id_from_thermostat` regex → `zone_3`

This drift meant the button/number unique_ids didn't align with sensor/ZoneManager — a latent cross-platform consistency hazard.

**Fix:** both `_discover_ac_zones` functions now delegate to `iter_canonical_hvac_zones`. All four code paths (sensor + button + number + ZoneManager runtime) now assign identical zone_ids.

## Architecture: Layer 3 prevention via shared helper

The proper fix for "per-zone entity registration bypasses dedup" (Bug Class #36) is to eliminate the bug by construction: there must be one canonical zone-iteration path that all per-zone platform setup paths use. `iter_canonical_hvac_zones(hass)` is that path. Adding a new per-zone entity surface (future v4.6.x features) now means calling the helper, not rolling another loop. The helper itself lives in `domain_coordinators/hvac_zones.py` next to the ZoneManager so the dedup semantics stay in lockstep.

Three prevention layers per `docs/QUALITY_CONTEXT.md` Bug Class #36:
- **Layer 1 (review):** any new per-zone entity surface routes through the helper and adds a coverage test
- **Layer 2 (tests):** AST regression tests block direct iteration over `<zm_data_var>.get("zones", {})`; source-grep blocks orphaned `seen.add(thermostat)` patterns
- **Layer 3 (helper):** single source of truth, makes the bug structurally impossible

## Entity unique_id changes

**This release changes entity unique_ids. Some entity_ids will be remapped or orphaned in HA's entity registry.** Per single-user policy, no migration shim is included. List below covers the user's canonical 4-home-zone install.

### Removed (phantom zone_4 entities)

These were duplicates with no real backing zone. Will appear as orphaned in `Settings → Devices & Services → Entities → "Universal Room Automation"`:
- `sensor.ura_hvac_coordinator_zone_4_status`
- `sensor.ura_hvac_coordinator_zone_4_preset`
- `sensor.ura_hvac_coordinator_ac_ramp_state_<old_phantom>`
- `sensor.ura_hvac_coordinator_ac_ramp_last_action_<old_phantom>`
- `sensor.ura_hvac_coordinator_ac_kwh_rate_<old_phantom>`

The "phantom" suffix corresponds to whichever of Entertainment/Master Suite was the second one iterated when v4.5.12 created duplicate entities. Clean up via HA's entity registry UI (Delete on the orphaned entries).

### Renamed (button.py — 9 buttons)

For each AC zone, 3 buttons existed: force_nudge, cancel_nudge, clear_lockout. unique_id pattern changes:

| Old unique_id stem | New unique_id stem |
|---|---|
| `universal_room_automation_hvac_ac_ramp_force_nudge_back_hallway_zone_3` | `universal_room_automation_hvac_ac_ramp_force_nudge_zone_3` |
| `..._cancel_nudge_back_hallway_zone_3` | `..._cancel_nudge_zone_3` |
| `..._clear_lockout_back_hallway_zone_3` | `..._clear_lockout_zone_3` |
| (same pattern for `thermostat_bryant_wifi_studyb_zone_1` → `zone_1`) | (same → `zone_1`) |
| (same for `up_hallway_zone_2` → `zone_2`) | (same → `zone_2`) |

HA's entity registry will create new entries with the new unique_ids and orphan the old ones. The user-visible entity_ids (`button.ura_hvac_coordinator_clear_ac_ramp_lockout_back_hallway`) may auto-rename to suffix-match the new zone_name. **Lockout buttons were added in v4.5.11 with no production dashboards referencing them**, so cleanup risk is low.

### Renamed (number.py — 3 sliders)

| Old | New |
|---|---|
| `universal_room_automation_hvac_ac_kwh_threshold_back_hallway_zone_3` | `..._zone_3` |
| `..._thermostat_bryant_wifi_studyb_zone_1` | `..._zone_1` |
| `..._up_hallway_zone_2` | `..._zone_2` |

Per-zone kwh threshold sliders shipped in v4.5.11.

### Unchanged

- All D8 house-wide sensors (`ac_nudges_today`, `ac_hard_resets_today`, etc.)
- All EC entities
- All non-HVAC coordinator entities
- All room entities
- The diagnostic dump button (`button.ura_hvac_coordinator_ac_ramp_diagnostic_dump`) — house-wide, no zone scope

## What's NOT changed

- No DB schema changes
- No config keys added/removed/renamed
- No behavioral changes to AC ramp-down actions or HVAC decisions
- No anomaly detector logic changes (v4.5.13's gate relaxation stands)

## Tier 1 Review

One independent staff-engineer review per CLAUDE.md hotfix protocol. Mental execution of:
- Helper dedup logic for the user's canonical 4-home-zone install
- Zone_id alignment across all 4 code paths (sensor, button, number, ZoneManager runtime)
- Edge cases: empty config, no thermostat, 5+ shared zones, suffix collisions
- Platform setup ordering safety

**Findings:** 0 CRITICAL/HIGH. 1 MEDIUM addressed via README documentation (entity unique_id changes). 6 LOW: 3 fixed in code, 3 documented as accepted design trade-offs.

Full review at `docs/reviews/code-review/v4.5.13.1_review.md`.

## Test count

- v4.5.13: 352 tests
- **v4.5.13.1: 367** (+15 from `test_v4513_1_zone_dedup.py`)

Includes 2 lockstep equivalence tests that run the helper AND `ZoneManager.async_discover_zones` against identical fixtures, asserting the (zone_id → climate_entity, zone_name) mapping agrees. These tests fail if either code path drifts from the other.

## Live validation plan (post-restart)

1. **Sensor count check (~immediately post-restart):**
   - `sensor.ura_hvac_coordinator_ac_kwh_rate_*` count == 3 (was 4 in v4.5.13 — phantom removed)
   - `sensor.ura_hvac_coordinator_zone_*_status` count == 3 (was 4)
   - One zone has friendly_name including " + " (the Entertainment + Master Suite merge)

2. **Zone_id consistency (within 5 min):**
   - Pick the shared-thermostat zone (Entertainment + Master Suite). Its sensors, buttons, and slider all have unique_ids containing `zone_1` (or whichever ZoneManager assigns).
   - Pre-v4.5.13.1 button entities (with `back_hallway_zone_3`-style unique_ids) appear as orphaned in Settings → Devices & Services → Entities. Delete them.

3. **No new URA errors in system log:**
   - `ha_get_logs source=system level=ERROR search=universal_room_automation` returns empty

4. **Behavior preserved:**
   - AC ramp master switch toggle still works
   - kwh_rate sensors still populate live values (v4.5.13 fix unaffected)
   - Anomaly detectors still in `active`/`advisory`/etc. state (v4.5.13 fix unaffected)

5. **Envoy race repro watch (per session memory):**
   - Inspect bootstrap log immediately after restart: timestamp of `Waiting for integrations to complete setup: enphase_envoy` vs URA's `envoy validation failed` error.
   - If both timestamps within 30 sec of each other AND URA error fires → race confirmed and v4.5.13.2 is the right next fix.
   - If URA error fires WITHOUT a paired enphase_envoy bootstrap warning → race theory wrong; need deeper investigation.

## Deploy notes

- HACS download required after deploy.sh
- HA restart required (4 files touched: sensor.py, button.py, number.py, hvac_zones.py, plus QUALITY_CONTEXT.md)
- **Post-restart cleanup needed:** orphaned button/number entities + phantom zone_4 sensors. Use Settings → Devices & Services → Entities → search "Universal Room Automation" → filter Orphaned → Delete.

## Documents

- Review: `docs/reviews/code-review/v4.5.13.1_review.md`
- Quality context: `docs/QUALITY_CONTEXT.md` Bug Class #36
- BACKLOG: v4.5.13.2 (envoy startup race) remains the next item

## Next

- **v4.5.13.2** — Envoy validation startup race fix (state-added subscription)
- **v4.5.14** — Anomaly visibility (`extra_state_attributes` on all anomaly sensors) + closet/bathroom lazy auto-off
- **v4.5.15** — Duplicate-timestamp investigation
- **v4.5.16** — Bayesian prediction-scoring pipeline investigation
- **v4.6.0** — Routine Awareness Phase 1
