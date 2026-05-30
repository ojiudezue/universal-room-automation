# URA v4.7.14 — Away-State Person-Tracker Trust Veto

**Tier:** 1 (hotfix)
**Sibling to:** v4.7.13 (sleep-state zone presence trust). Same architectural lesson, opposite end of the house-state arc: when transient signals (Frigate motion, camera Tier 2) disagree with reliable persistent signals (phone trackers), trust the persistent signal.

## Summary

URA's house-state inference now treats "every configured `person.*` tracker says away" as a positive veto signal that overrides camera Tier 2 motion. This stops empty-house oscillation when nobody is home but cameras keep firing on shadows, pets, or outdoor motion.

## Triggering incident — 2026-05-30

- All 4 `person.*` entities = `not_home`; all 4 Bermuda trackers = `not_home`.
- `binary_sensor.ura_presence_coordinator_house_occupied` was stuck `on`.
- `sensor.ura_coordinator_manager_house_state` was bouncing `away → arriving → home_day → away` every ~60-90 s.
- Bryant `studyB zone_1` thermostat had `preset_mode=away` at the device, URA was pushing `home`, compliance violations every cycle.
- AC actively cycling each preset flip.

User intervened by manually setting `select.ura_presence_coordinator_house_state_override → away`. This release removes the need for that manual intervention.

## Three deliverables

### D1 — Compute `all_tracked_persons_away` at the call site

**File:** `custom_components/universal_room_automation/domain_coordinators/presence.py`
**Lines:** 1896-1922 — new computation block at the top of `_run_inference`.

Reads `hass.data[DOMAIN]["person_coordinator"].data`, derives:
- `tracked_count` — how many person trackers are configured.
- `all_tracked_persons_away` — True iff `tracked_count > 0` AND every entry's `location` is in `("away", "")` (None location → ""). `"unknown"` is **conservatively excluded** — uncertainty is not confirmed-absence.

Defensive `try/except` so any future schema drift in `person_coordinator.data` fails safe (False) rather than raising.

Stored on the coordinator (`self._tracked_persons_count`, `self._all_tracked_persons_away`) so D3 sensor can surface them.

### D2 — Add kwarg + veto to `StateInferenceEngine.infer()`

**File:** same.
**Lines:**
- Signature: 367-376 — new kwarg `all_tracked_persons_away: bool = False`.
- Body: 403-414 — new early-return block inserted AFTER the existing `census_count==0 AND not any_zone_occupied → AWAY` gate (line 391) and BEFORE the `has_people` branch (line 416).
- Call site: 1992-1998 — `_run_inference` now passes `all_tracked_persons_away=all_tracked_persons_away`.

Veto semantics:
```
if all_tracked_persons_away and unidentified_count == 0:
    return AWAY (confidence 0.95) — or None if already AWAY
```

Key invariants:
- Veto does **not** fire when `unidentified_count > 0` — guest-at-the-door path preserved.
- Confidence `0.95` is higher than camera-driven `0.85` and the existing AWAY `0.9`.
- Default kwarg value `False` preserves back-compat for any caller that doesn't pass it.

`_LOGGER.info()` line at presence.py:2007 records every veto firing for diagnosability.

### D3 — Diagnostic attributes on the live house-state sensor

**File:** `custom_components/universal_room_automation/sensor.py`
**Lines:** 3624-3634 — inside `PresenceHouseStateSensor.extra_state_attributes`.

Adds two attributes to `sensor.ura_presence_house_state`:
- `tracked_persons_count` — int, how many person trackers `person_coordinator` is observing.
- `all_tracked_persons_away` — bool, the live veto signal.

Read pattern uses `getattr(presence, "_tracked_persons_count", 0)` so the sensor degrades cleanly if the coordinator isn't initialized yet.

## Acceptance criteria

- The `infer()` veto fires BEFORE the `has_people` branch so camera motion cannot pre-empt it.
- Veto does NOT fire when `unidentified_count > 0` — guest path preserved.
- Default `False` kwarg preserves existing behavior for callers that don't pass it.
- Empty `person_coordinator.data` → `all_tracked_persons_away = False` (fail-safe).
- `"unknown"` person state does NOT trigger the veto (conservative).
- Confidence `0.95` when veto fires.

## Tests

`quality/tests/test_v4714_away_state_person_tracker_trust.py` — 24 tests:

D1 source/AST invariants:
- `test_computation_block_exists`
- `test_tracked_count_computed`
- `test_empty_config_failsafe_present`
- `test_unknown_not_treated_as_away`
- `test_uses_person_coordinator_key`
- `test_diagnostic_attributes_stored_on_self`
- `test_run_inference_passes_kwarg_to_infer`

D1 behavioral (logic equivalent to production):
- `test_all_tracked_persons_away_true_when_all_away`
- `test_all_tracked_persons_away_false_when_any_unknown`
- `test_all_tracked_persons_away_false_when_no_persons_tracked`
- `test_all_tracked_persons_away_false_when_person_coordinator_missing`
- `test_all_tracked_persons_away_handles_none_location`
- `test_all_tracked_persons_away_false_when_one_home`

D2 behavioral (drive real `StateInferenceEngine.infer()`):
- `test_veto_fires_when_all_persons_away_and_no_unidentified`
- `test_veto_does_not_fire_when_unidentified_count_positive`
- `test_veto_does_not_fire_when_any_person_home`
- `test_veto_returns_none_if_already_away`
- `test_default_kwarg_preserves_existing_behavior`
- `test_veto_fires_from_arriving_state`
- `test_veto_kwarg_signature_has_default_false`

D3 sensor (AST against real `sensor.py`):
- `test_house_state_sensor_exposes_tracked_persons_count`
- `test_house_state_sensor_exposes_all_tracked_persons_away`
- `test_attributes_land_on_presence_house_state_sensor`
- `test_attributes_read_from_presence_coordinator`

Also widens `test_v472_feature_b_guest_signal.py` confidence-marker grep window 5000 → 7000 chars — the new computation block pushed the existing D5 markers past the original horizon; production semantics unchanged.

Run: `PYTHONPATH=quality python3 -m pytest quality/tests/test_v4714_*.py -v` → 24 passed.
Full suite delta vs `pre-review-v4.7.13` baseline: +18 net passes (24 new minus 6 brittle-window fixes), 0 new failures.

## Out of scope

- **No change to `_update_ble_zone_presence` at line 1518.** The "away" filter for per-zone BLE Tier-3 is correct as-is — that signal is about "is THIS zone occupied by a person known to be here," not a house-level veto.
- **No change to `_CAMERA_OCCUPANCY_TIMEOUT_SECONDS = 300`.** Timeout is fine; the fix is structural, not parametric.
- **No Frigate tuning.** Upstream noise is now defended against in URA, not at the upstream source.
- **`"unknown"` not added to the veto.** Conservative — only literal `away` triggers it.
- **No house-level BLE positive signal.** ("BLE confirms Oji is in the house but not pinned to a room.") Deferred — would require additional code path.

## Live validation checklist

Run on the next workday when everyone leaves:

1. Within one inference cycle of all 4 persons reaching `not_home`:
   - `binary_sensor.ura_presence_coordinator_house_occupied` = `off`
   - `sensor.ura_presence_house_state` = `away`
   - `sensor.ura_presence_house_state` attribute `all_tracked_persons_away` = `true`
   - `sensor.ura_presence_house_state` attribute `tracked_persons_count` = `4` (or whatever the configured count is)
   - `sensor.ura_presence_house_state` attribute `confidence` ≥ `0.95`

2. Zero `away → arriving → home_day → away` bounces in `sensor.ura_coordinator_manager_last_activity` across the empty-house window.

3. HVAC zone preset `away` holds; no Bryant compliance violations from URA driving `home`.

4. When even one person returns home: house state transitions to `arriving` within one inference cycle; `all_tracked_persons_away` flips back to `false`.

5. When a guest arrives (`unidentified_count > 0`) while all configured persons are away: house state does NOT veto to `away` — guest path preserved.

6. Search `home-assistant.log` for `v4.7.14: Person-tracker veto fired` — should appear at least once when transitioning AWAY due to the veto.

## Sibling cycle context

| Cycle | Symptom | Fix |
|---|---|---|
| v4.7.13 | Zone aggregator drops motionless sleeper → fan vacancy cycles overnight | `ZoneAnyoneBinarySensor` Layer-2 fallback during `house_state == "sleep"` |
| v4.7.14 | House inference drops away-confirmed persons → empty-house oscillation | `StateInferenceEngine.infer()` veto when `all_tracked_persons_away` |

Both cycles follow the same lesson: when transient signals (mmWave / camera) disagree with reliable persistent signals (phone trackers), trust persistent. Candidate for a new QUALITY_CONTEXT bug class — "Transient sensor over-trust during reliable-truth-says-otherwise periods."
