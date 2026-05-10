# v4.5.9.1 — Surface v4.5.9 cover diagnostic attrs on HVAC mode sensor

**Date:** 2026-05-10
**Type:** Tier 1 hotfix (~10 LoC + 1 regression test)
**Predecessor:** v4.5.9
**Reproducer:** v4.5.9 live validation post-restart — `sensor.ura_hvac_coordinator_mode` had `covers_closed` and `managed_covers` but NOT the new v4.5.9 D6 diagnostic attrs (`hvac_closed_set`, `hvac_closed_count`, `managed_tilt_covers`, `managed_shade_covers`).

## Summary

v4.5.9 added the new diagnostic keys to `CoverController.get_cover_status()`, but `hvac.py:1453-1455` has a manual attribute picker that explicitly lists only the two pre-v4.5.9 keys (`covers_closed`, `managed_covers`). The new keys lived in the dict, but the mode sensor's attribute builder didn't pick them up. Caught during the v4.5.9 live validation step.

This is a half-shipped D6 — the data was there, the surfacing wasn't. v4.5.9.1 is the four-line completion + a source-contract test that asserts the mode sensor's pick block includes the v4.5.9 keys (so a future cleanup can't silently regress them).

## What changed

`domain_coordinators/hvac.py:1453-1462`:

```python
cover_status = self._cover_controller.get_cover_status()
attrs["covers_closed"] = cover_status.get("covers_closed", False)
attrs["managed_covers"] = cover_status.get("managed_covers", 0)
# v4.5.9.1: surface v4.5.9 D6 diagnostic attrs
attrs["managed_tilt_covers"] = cover_status.get("managed_tilt_covers", 0)
attrs["managed_shade_covers"] = cover_status.get("managed_shade_covers", 0)
attrs["hvac_closed_set"] = cover_status.get("hvac_closed_set", [])
attrs["hvac_closed_count"] = cover_status.get("hvac_closed_count", 0)
```

## Tests

1 new regression test added to `test_v459_hvac_cover_intent.py::TestSourceContract::test_hvac_mode_sensor_picks_up_v459_attrs`. Source-grep test that asserts the mode sensor's `cover_status` pick block includes all 4 v4.5.9 D6 keys.

**Test count progression:**
- v4.5.9: 2054, 0 isolated failures across 57 files
- **v4.5.9.1: 2055** (+1)

## Live validation (post next-restart)

After HACS download + HA restart, `sensor.ura_hvac_coordinator_mode` extra_state_attributes should include:
- `managed_tilt_covers: <int>`
- `managed_shade_covers: <int>`
- `hvac_closed_set: []` (likely empty post-restart; populates during a solar window when HVAC closes covers)
- `hvac_closed_count: 0`

Plus the existing `covers_closed`, `managed_covers`, `solar_banking_zones` etc.

## Lesson learned

This is the same shape as Bug Class #33 (sibling helpers skipped) but in a smaller form: the producer (`get_cover_status`) was updated; the consumer (mode sensor pick block) wasn't audited. **When a controller's status dict gets new keys, every consumer that selectively reads from it must be checked for an updated pick list.** The Tier 2 review process for v4.5.9 didn't catch this because both reviews focused on the controller's own logic, not the cross-coordinator surfacing path. Worth adding to the review checklist: "data shape changes → grep for every consumer's selective key extraction."

## Deploy notes

- No DB schema changes
- No migration needed
- HACS download required after deploy.sh
- HA restart required (hvac.py touched)
