# v4.5.13.1.1 — number.py kWh Threshold Slider TypeError Fix

**Date:** 2026-05-12
**Type:** Tier 1 micro-hotfix (single 8-LoC change, 1 new regression test)
**Predecessor:** v4.5.13.1 (live-validated; this fix addresses one regression introduced by that cycle)

## Summary

v4.5.13.1's canonical-zone helper `iter_canonical_hvac_zones` returns 5-key dicts (`zone_id, zone_name, climate_entity, ac_load_sensor, ramp_zone_enabled`). Pre-v4.5.13.1's `_discover_ac_zones` helpers returned 3 keys. `number.py:71` was doing `cls = _hvac_zone_kwh_threshold_factory(**zone_spec)` against a fixed 3-parameter factory signature → TypeError at platform setup → all 3 per-zone kWh threshold sliders went `unavailable`.

This release filters the dict to the 3 keys the factory expects. Also adds an AST regression test (`test_no_kwarg_unpack_of_zone_spec_in_platforms`) that flags any future `**zone_spec` spread against a fixed-signature receiver. Adds Bug Class #37 to QUALITY_CONTEXT documenting the failure mode.

## What's fixed

### number.py:71 — kwarg unpack TypeError

**Before:**
```python
for zone_spec in _discover_ac_zones(hass):
    cls = _hvac_zone_kwh_threshold_factory(**zone_spec)
    entities.append(cls(hass, entry))
```

**After:**
```python
for zone_spec in _discover_ac_zones(hass):
    cls = _hvac_zone_kwh_threshold_factory(
        zone_id=zone_spec["zone_id"],
        zone_name=zone_spec["zone_name"],
        climate_entity=zone_spec["climate_entity"],
    )
    entities.append(cls(hass, entry))
```

Filter the dict to the 3 keys the factory accepts. Helper's extra fields (`ac_load_sensor`, `ramp_zone_enabled`) remain available for future per-zone entities that need them.

### Bug Class #37 added to QUALITY_CONTEXT

**Pattern:** API contract change without caller signature audit. Helper's return shape changes (3 keys → 5 keys); call sites doing `**returned_dict` against a fixed-signature receiver raise TypeError at runtime. The bug doesn't manifest until deploy; source-grep + AST tests on the helper alone don't catch it.

**Prevention:** AST regression test now flags any `**zone_spec` spread pattern in platform setup files; mandatory call-site signature audit when extending helpers.

## Tier 1 Review

Single staff-engineer review per CLAUDE.md hotfix protocol. Mental execution:
- The fix is a direct keyword-by-keyword pass — eliminates the `**` spread entirely
- Factory signature unchanged
- Helper return shape unchanged
- No new dependencies, no new imports
- No behavioral side effects beyond restoring the broken sliders

**Verdict:** APPROVED. 0 CRITICAL/HIGH/MEDIUM/LOW findings.

## Tests

**Before v4.5.13.1.1:** 367 tests
**After:** 368 tests (+1 regression test `test_no_kwarg_unpack_of_zone_spec_in_platforms`)

The new test does an AST walk of sensor.py, button.py, number.py looking for `func(**zone_spec)` patterns. Currently zero hits; future regressions caught.

## Live validation plan (post-restart)

1. **Per-zone kWh threshold sliders populate:**
   - `number.ura_hvac_coordinator_ac_kwh_rate_threshold_back_hallway` → state is a float (default 0.8 or saved value), not `unavailable`
   - Same for `_entertainment` and `_upstairs` siblings
   - (Note: entity_ids still reflect pre-v4.5.13.1 slugs — see v4.5.13.1 README for cleanup steps)

2. **No new URA errors in system log:**
   - `ha_get_logs source=system level=ERROR search=universal_room_automation` — no TypeError on `_hvac_zone_kwh_threshold_factory`

3. **All v4.5.13 + v4.5.13.1 fixes still working:**
   - kwh_rate sensors live (v4.5.13 fix)
   - HVAC anomaly state `nominal` / `advisory` / etc., not `learning` (v4.5.13 fix)
   - 3 canonical HVAC zones, not 4 (v4.5.13.1 fix)
   - merged-zone friendly name "Entertainment + Master Suite" preserved

4. **Envoy race watch (per session memory):**
   - Compare timestamps of bootstrap `Waiting for integrations to complete setup: enphase_envoy` and URA `envoy validation failed` (if it fires)
   - If race fires this restart → confirms v4.5.13.2 is the right next fix

## Deploy notes

- 1 file changed (number.py), 1 file added (regression test), 1 file extended (QUALITY_CONTEXT)
- HACS download required after deploy.sh
- HA restart required
- No new orphaned entities (the threshold sliders' unique_ids unchanged from v4.5.13.1)

## Documents

- Bug Class #37 in `docs/QUALITY_CONTEXT.md`
- Predecessor v4.5.13.1 review remains accurate; this micro-hotfix has no separate review doc (the change is too small to warrant one)

## Next

- **v4.5.13.2** — Envoy validation startup race fix. **Tier 2 (extra review)** per user direction — the race repro is intermittent and the fix touches startup ordering, so requires two independent staff-engineer reviews.
- v4.5.14, v4.5.15, v4.5.16 queue unchanged
