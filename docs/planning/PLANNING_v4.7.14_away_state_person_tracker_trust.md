# PLANNING v4.7.14 — Away-State Person-Tracker Trust Veto

**Tier:** 1 (hotfix)
**Triggering incident:** 2026-05-30 — empty-house oscillation. All 4 persons `not_home`; Bermuda healthy; URA bouncing `away ↔ arriving ↔ home_day ↔ away` every ~60-90 s because Frigate camera motion drives Tier 2 zone-occupancy and there is no person-tracker veto in the inference engine.
**Estimated size:** ~30-50 LoC + ~6 cycle tests.
**Sibling to:** v4.7.13 (sleep-state zone presence trust). Same architectural pattern, different gate.

---

## 1. Problem statement

URA's house-state inference has no person-tracker veto for the `away` path. When all configured `person.*` entities are `not_home` AND Bermuda confirms it, URA still treats camera Tier 2 motion as positive occupancy evidence and bounces house_state out of `away`.

**This is not a regression.** Git-blame:
- `presence.py:391` (the `census_count==0 AND not any_zone_occupied → AWAY` AND-gate) — original code from commit `b761cbe`, v3.6.0-c1 (2026-02-28)
- `presence.py:1502` (the `if location not in ("away", "unknown", "")` filter that discards person-coordinator "away" data) — same commit, same date
- `presence.py:1941` (the `infer()` call site) — last touched in v4.6.2.2 to add `guest_gate_armed`; the `any_zone_occupied` path is unchanged

The omission has always been there. It only manifests when phones are away **and** cameras fire — i.e., workdays / empty-house conditions. Recent environmental shifts (more outdoor camera triggers? lengthening daylight = more shadow motion? Frigate sensitivity drift?) have raised the camera-noise floor enough to expose it.

## 2. Triggering live evidence (2026-05-30)

- All 4 `person.*` entities = `not_home`
- All 4 Bermuda trackers = `not_home`, source_type=`bluetooth_le`, last reported ~75 min before symptom
- `binary_sensor.ura_presence_coordinator_house_occupied` = `on` (despite above)
- `sensor.ura_coordinator_manager_house_state` oscillating `away → arriving → home_day → away` at ~60-90 s cycle
- `sensor.universal_room_automation_census_confidence` = `none` (Frigate gives motion but no person-ID)
- Bryant studyB zone_1 thermostat: `preset_mode=away` at device, URA pushing `home`, compliance violations every cycle
- AC actively cycling each preset flip

## 3. Architecture (code-verified, not theorized)

### 3.1 The five files / lines involved

| File | Line | Function | Role |
|---|---|---|---|
| `domain_coordinators/presence.py` | 391 | `StateInferenceEngine.infer()` | AND-gate: returns AWAY only if `census_count == 0 AND not any_zone_occupied` |
| `domain_coordinators/presence.py` | 398-406 | `StateInferenceEngine.infer()` | `has_people` branch: any positive zone occupancy → ARRIVING from AWAY |
| `domain_coordinators/presence.py` | 1500-1506 | `_update_ble_zone_presence` | Iterates `person_coordinator.data`, **filters out** `"away"/"unknown"/""` |
| `domain_coordinators/presence.py` | 1874-1877 | `_run_inference` | Computes `any_zone_occupied = any(t.mode == OCCUPIED)` |
| `domain_coordinators/presence.py` | 1941-1947 | `_run_inference` | Calls `infer()` with `census_count`, `any_zone_occupied`, `unidentified_count`, `guest_gate_armed` |
| `person_coordinator.py` | 215-226 | `_async_update_data` | When Bermuda resolves to a room: stores `location: <room_name>, method: "bermuda"` |
| `person_coordinator.py` | 338-349 | `_async_update_data` | When person state == "not_home": stores `location: "away", method: "person_state", confidence: 0.9` |

### 3.2 Why phone-tracker "away" provides zero positive information today

When `person.oji_udezue == "not_home"`:
1. `person_coordinator.data["oji_udezue"] = {"location": "away", "method": "person_state", "confidence": 0.9}`
2. `presence.py:1502` filters: `if location not in ("away", "unknown", "")` → False → skip
3. `zone_has_person` stays False for that person
4. After looping all persons, `tracker.update_ble_presence(False)` → `_ble_occupied = False`
5. `_derived_mode` Tier 3 (BLE) returns nothing (line 160-161 fails)
6. Falls through to Tier 1 (mmWave/PIR) — quiet
7. Falls through to Tier 2 (camera) — Frigate motion → `_any_camera_occupied()` True for 300 s post-detection (line 188 `_CAMERA_OCCUPANCY_TIMEOUT_SECONDS`)
8. Zone → `OCCUPIED`, `any_zone_occupied → True`
9. `infer()` line 391 AND-gate fails, line 398-406 → returns ARRIVING from AWAY

There is no path where "all four phones away" reaches `infer()` as a signal.

## 4. Design — three-deliverable Tier 1 hotfix

All three changes mirror v4.7.13's pattern: **use already-available reliable boolean signals as a fallback / veto where transient signals dominate.**

### D1 — Compute `all_tracked_persons_away` at the call site

**File:** `domain_coordinators/presence.py`
**Site:** `_run_inference`, just before the existing `any_zone_occupied` computation at line 1874

```python
# v4.7.14: Compute all-persons-away veto signal from person_coordinator
person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
all_tracked_persons_away = False
tracked_count = 0
if person_coordinator and getattr(person_coordinator, "data", None):
    person_data = person_coordinator.data or {}
    tracked_count = len(person_data)
    if tracked_count > 0:
        all_tracked_persons_away = all(
            (info.get("location") or "") in ("away", "")
            for info in person_data.values()
        )
```

**Notes:**
- `tracked_count > 0` guard prevents an empty config from vetoing — if no persons are tracked, behave exactly like today.
- `"unknown"` is intentionally NOT treated as "away" — unknown is genuine uncertainty and shouldn't trigger the veto. Conservative bias.
- Use `or ""` to handle None.

### Acceptance Criteria

- **Verify:** Computation happens BEFORE the `infer()` call so the value is available to pass.
- **Verify:** Empty `person_coordinator.data` results in `all_tracked_persons_away = False` (not True) — fail-safe toward current behavior.
- **Verify:** No new imports beyond what's already in the file.
- **Test:** `test_all_tracked_persons_away_true_when_all_away`
- **Test:** `test_all_tracked_persons_away_false_when_any_unknown`
- **Test:** `test_all_tracked_persons_away_false_when_no_persons_tracked`
- **Test:** `test_all_tracked_persons_away_false_when_person_coordinator_missing`

---

### D2 — Pass `all_tracked_persons_away` to `infer()` and apply the veto

**File:** `domain_coordinators/presence.py`
**Site 1:** `StateInferenceEngine.infer()` signature (line 367), add new kwarg
**Site 2:** `infer()` body, inserted BEFORE the existing `has_people` branch (line 398), AFTER the existing AND-gate (line 391-395)
**Site 3:** `_run_inference` call site at line 1941, pass new kwarg

```python
# Signature change at line 367
def infer(
    self,
    census_count: int,
    current_state: HouseState,
    any_zone_occupied: bool,
    now: Optional[datetime] = None,
    unidentified_count: int = 0,
    guest_gate_armed: bool = False,
    all_tracked_persons_away: bool = False,  # NEW
) -> Optional[HouseState]:
```

```python
# Body, inserted after line 395, before line 398
# v4.7.14: Person-tracker veto — if all configured phone trackers say away
# AND no unidentified person is in the house, return AWAY regardless of
# camera Tier 2 motion. Defends against camera ghost-presence.
# Note: unidentified_count > 0 preserves guest detection — a guest at the
# door triggering camera motion legitimately means someone IS here even
# if all tracked persons are away.
if all_tracked_persons_away and unidentified_count == 0:
    if current_state == HouseState.AWAY:
        return None  # already away
    self._confidence = 0.95  # higher than the camera-driven 0.85
    return HouseState.AWAY
```

```python
# Call site update at line 1941
new_state = self._inference_engine.infer(
    census_count=self._census_count,
    current_state=current_state,
    any_zone_occupied=any_zone_occupied,
    unidentified_count=self._unidentified_count,
    guest_gate_armed=guest_armed,
    all_tracked_persons_away=all_tracked_persons_away,  # NEW
)
```

### Acceptance Criteria

- **Verify:** Veto fires BEFORE the `has_people` branch so camera motion can't pre-empt it.
- **Verify:** Veto does NOT fire when `unidentified_count > 0` (guest path preserved).
- **Verify:** Default value `False` preserves existing behavior for any caller that doesn't pass the kwarg.
- **Verify:** Confidence 0.95 > existing 0.9 AWAY confidence and 0.85 ARRIVING confidence so downstream code that ranks by confidence prefers the veto.
- **Test:** `test_veto_fires_when_all_persons_away_and_no_unidentified`
- **Test:** `test_veto_does_not_fire_when_unidentified_count_positive` (guest path)
- **Test:** `test_veto_does_not_fire_when_any_person_home`
- **Test:** `test_veto_returns_none_if_already_away` (no duplicate transition)
- **Test:** `test_default_kwarg_preserves_existing_behavior` — call `infer()` without `all_tracked_persons_away` and verify identical output to pre-v4.7.14 behavior on the same inputs
- **Live:** `binary_sensor.ura_presence_coordinator_house_occupied` goes `off` within one inference cycle of all 4 persons reaching `not_home`, regardless of Frigate motion firing
- **Live:** zero `away → arriving → home_day → away` bounces in `sensor.ura_coordinator_manager_last_activity` while all persons away

---

### D3 — Defensive: expose `tracked_count` + `all_tracked_persons_away` as state attributes on the existing house-state sensor for diagnostics

**File:** `domain_coordinators/presence.py` (where the existing `house_state` sensor builds its attributes — verify exact location during build)

Add to the existing house-state sensor's `extra_state_attributes`:
```python
"tracked_persons_count": tracked_count,
"all_tracked_persons_away": all_tracked_persons_away,
```

Purpose: next time URA seems "fragile," the diagnostic is one MCP probe — read the attributes and see whether the veto was active, instead of having to read code or replay logs.

### Acceptance Criteria

- **Verify:** Attribute names follow the existing snake_case + lowercase convention used by other URA sensors.
- **Verify:** Builder confirms the EXACT sensor entity that should carry these attributes before adding (don't fabricate — find the existing house-state sensor's attribute build site).
- **Test:** `test_house_state_sensor_exposes_tracked_persons_count`
- **Test:** `test_house_state_sensor_exposes_all_tracked_persons_away`
- **Live:** `ha_get_state("<the sensor>", attribute_keys=["tracked_persons_count", "all_tracked_persons_away"])` returns truthy values matching live person.* state.

---

## 5. What's intentionally OUT of scope

- **Not changing `_update_ble_zone_presence` at line 1502.** The "away" filter for the per-zone BLE Tier-3 signal is correct as-is — that signal is about "is THIS zone occupied by a person known to be in THIS zone's rooms." Per-zone BLE is the wrong layer for an all-house-away veto.
- **Not changing the camera Tier-2 timeout** (`_CAMERA_OCCUPANCY_TIMEOUT_SECONDS = 300`). The timeout is correct for short-term camera occlusion; the fix here is structural, not parametric.
- **Not changing Frigate sensitivity / Frigate config.** That's an upstream tuning question; this cycle just makes URA robust to upstream noise.
- **Not changing `census_count` logic.** Census + Frigate person-ID could be a future independent improvement.
- **Not adding `"unknown"` to the veto.** Conservative: only literal `away` triggers it. Unknown stays risky.
- **No house-level BLE positive signal** ("BLE confirms Oji is in the house but not pinned to a room") — would require additional code path; defer to a follow-up if needed.

## 6. Bug class watch

| Class | Risk | Notes |
|---|---|---|
| #11 (UTC vs local TZ) | None | No timestamp logic. |
| #14 (config snapshot staleness) | Minimal | `tracked_persons` list read fresh each call. |
| #20 (concurrent reload race) | None | No new listeners / no entity registry mutation. |
| #22 (enum mismatch) | Low | Compare to string literal `"away"` matching existing convention at line 1502. |
| #26 (in-memory reads only) | None | Reads via `hass.data.get(...).data` — same pattern as existing line 1494. |
| #33 (sibling helper skipped) | Watch | Was there a sibling place (e.g., a separate "house occupied" computation) that should ALSO get the veto? Builder verifies during scoping. |
| #38 (untracked unsub) | None | No new listeners. |
| #42 (lambda + async_create_task) | None | No new scheduling. |
| #43 (silent room drop) | None | New code is house-level, not room-level. |
| #44 (test fixture authority) | Watch | Cycle tests should drive the real `StateInferenceEngine.infer()` with kwargs, not stub. |
| #45 (lambda closure stale) | None | No new closures. |
| #46 (async_update_entry re-entrancy) | None | No config-entry mutations. |
| #47 (lazy canonical UI surface violation) | None | No new entities. |

## 7. Tests required (summary)

- `test_all_tracked_persons_away_true_when_all_away`
- `test_all_tracked_persons_away_false_when_any_unknown`
- `test_all_tracked_persons_away_false_when_no_persons_tracked`
- `test_all_tracked_persons_away_false_when_person_coordinator_missing`
- `test_veto_fires_when_all_persons_away_and_no_unidentified`
- `test_veto_does_not_fire_when_unidentified_count_positive`
- `test_veto_does_not_fire_when_any_person_home`
- `test_veto_returns_none_if_already_away`
- `test_default_kwarg_preserves_existing_behavior`
- `test_house_state_sensor_exposes_tracked_persons_count`
- `test_house_state_sensor_exposes_all_tracked_persons_away`

## 8. Acceptance criteria — live overnight + next-day workday

Within one inference cycle of all 4 persons leaving:
- `binary_sensor.ura_presence_coordinator_house_occupied` = `off`
- `sensor.ura_presence_coordinator_house_state` = `away`
- No `away → arriving → home_day → away` bounces in `sensor.ura_coordinator_manager_last_activity` for the entire away window
- HVAC zone preset `away` holds; no Bryant compliance violations from URA driving `home` preset
- `sensor.ura_presence_coordinator_house_state_confidence` ≥ 0.95 when the veto fires

When even one person returns home:
- House state transitions to `arriving` within one inference cycle
- All-tracked-persons-away attribute on house state sensor reads `false`

When a guest arrives (`unidentified_count > 0`) while all configured persons are away:
- House state does NOT veto to `away` — guest path preserved
- Existing guest detection logic continues to fire

## 9. Plan completion tracking

After implementation, document:
- D1/D2/D3 status (shipped, partial, deferred)
- Any deviations from planned line numbers / signatures
- Live evidence: workday observation showing zero bounces

## 10. Sibling to v4.7.13 — paired learning

| Bug shape | Fix | Cycle |
|---|---|---|
| Zone aggregator drops motionless sleeper → fan vacancy cycles | `ZoneAnyoneBinarySensor` Layer-2 fallback during `house_state == "sleep"` | v4.7.13 |
| House inference drops away-confirmed persons → empty-house cycles | `StateInferenceEngine.infer()` veto when `all_tracked_persons_away` | v4.7.14 |

Both fixes follow the same lesson: **when transient signals (mmWave/camera) disagree with reliable persistent signals (phone trackers), trust persistent.** Worth promoting to a QUALITY_CONTEXT bug class: "Transient sensor over-trust during reliable-truth-says-otherwise periods." Defer naming to QUALITY_CONTEXT update post-ship.

## 11. References

- v4.7.13 planning doc: `docs/planning/PLANNING_v4.7.13_sleep_state_zone_presence_trust.md`
- Memory: `project_nm_bb_wa_audit_2026_05_30.md` (unrelated, but same auditing session)
- Memory: `project_sleep_state_zone_presence_trust_backlog.md` (precedent reasoning)
- Git-blame evidence: commit `b761cbe` (v3.6.0-c1, 2026-02-28) — original Presence Coordinator; lines 391 + 1502 unchanged since
- Last `infer()` signature change: commit `b059fdc` (v4.6.2.2, 2026-05-14) — added `guest_gate_armed`
