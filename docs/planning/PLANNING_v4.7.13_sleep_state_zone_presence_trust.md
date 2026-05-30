# PLANNING v4.7.13 — Sleep-State Zone Presence Trust Fallback

**Tier:** 1 (hotfix)
**Triggering incident:** 2026-05-30 overnight — master bedroom fan stopped/started 4× through the night because zone occupancy aggregator dropped Oji from `binary_sensor.zone_entertainment_master_suite_anyone` during sleep.
**Estimated size:** ~30-40 LoC across 3 files + ~5 cycle tests.

---

## 1. Problem statement

URA's zone occupancy aggregator (`binary_sensor.zone_<canonical>_anyone`) is computed from room-level occupancy sensors only. During `house_state == "sleep"`, all three configured room sensors in the master bedroom can fail simultaneously in predictable ways, leaving the zone aggregator falsely `off` for hours. The downstream consequences cascade through `_apply_house_state_presets` (zone preset oscillates `sleep ↔ away`) into the FanController vacancy hold (fan abruptly stops/starts at 35-50 min intervals).

### Sensor degeneration pattern (master bedroom, 2026-05-30 overnight)

| Sensor | Overnight behavior | Failure mode |
|---|---|---|
| `binary_sensor.master_bedroom_presence` (mmWave) | 16 flickers, drops every 10-15 min | mmWave loses motionless bodies |
| `binary_sensor.master_bedroom_motion` (PIR) | OFF 2h 18min straight | PIR can't fire on stationary body |
| `binary_sensor.master_bedroom_camera_person_detected` (Frigate) | OFF the entire night | Camera blind to covered body in dark room |

3-sensor redundancy structurally degenerates to 1-sensor coverage during sleep. Only mmWave can in principle detect a sleeping body, and it has well-known drop windows.

### Signal URA has but doesn't use

- `person.oji_udezue == home` (phone-based, stable all night)
- `zone_persons` config for Entertainment + Master Suite = `[person.oji_udezue]`
- `house_state == "sleep"` (URA's own state, stable)

These three together definitionally state "Oji is in his bedroom asleep" — but the zone aggregator ignores them.

### Cascade

1. mmWave loses motionless Oji → `master_bedroom_occupied → off`
2. Zone-preset evaluator runs → "no rooms occupied" → flips zone preset `sleep → away`
3. `_apply_house_state_presets` recomputes setpoint_high (away preset wider deadband)
4. FanController re-evaluates: delta changed → speed recomputed via `_compute_speed(delta)` → RF send
5. Fan abruptly changes (visible as 100W↔270W in `sensor.master_bedroom_power`)
6. Oji shifts in his sleep → mmWave catches → `master_bedroom_occupied → on`
7. Zone preset flips back `away → sleep` within ~60s → setpoint tightens → fan re-adjusts
8. GOTO 1, repeating 4-8× per night.

Activity stream from 2026-05-30 night confirms 1:1 correlation:
- 03:24 CDT — sleep → away
- 03:39 CDT — home → sleep
- 04:04 CDT — sleep → away
- 04:14 CDT — home → sleep
- 05:04 CDT — sleep → away
- 05:14 CDT — home → sleep
- 06:14 CDT — sleep → home (legitimate wake-up)

---

## 2. Design — three-location short-circuit

All three additions mirror the existing `house_state == "sleep"` skip pattern at `hvac.py:1502` (duty-cycle enforcement skip during sleep). Rationale precedent already lives in the codebase — this extends it to occupancy aggregation, preset transitions, and fan vacancy.

### D1 — Zone occupancy aggregator fallback

**File:** `custom_components/universal_room_automation/domain_coordinators/aggregation.py` (or wherever `zone_<canonical>_anyone` binary_sensor compute lives — builder agent confirms during scoping).

**Change:** Add Layer 2 fallback after the existing Layer 1 (any-room-occupied) check.

```python
def zone_is_occupied(zone, house_state: str | None) -> bool:
    # Layer 1 (existing): any room reports occupied
    if any(room.is_occupied for room in zone.rooms):
        return True

    # Layer 2 (NEW v4.7.13): during sleep, trust person tracker + zone_persons
    if house_state == "sleep" and zone.zone_persons:
        for person_entity in zone.zone_persons:
            person_state = hass.states.get(person_entity)
            if person_state and person_state.state == "home":
                return True

    return False
```

### Acceptance Criteria

- **Verify:** Builder confirms exact aggregator file/function before edit (no fabrication).
- **Verify:** Layer 2 only triggers when `house_state == "sleep"` AND `zone.zone_persons` non-empty AND at least one person `state == "home"`.
- **Sensor:** `binary_sensor.zone_entertainment_master_suite_anyone` = `on` while `person.oji_udezue == home` AND `house_state == sleep`, regardless of mmWave flicker.
- **Test:** `test_v4713_zone_occupied_fallback_to_person_tracker_during_sleep`
- **Test:** `test_v4713_when_all_persons_not_home_during_sleep_no_fallback` (don't lock occupied when actual reason for empty is person-away)
- **Test:** `test_v4713_when_house_state_not_sleep_no_fallback_applies`
- **Live:** Overnight monitoring shows zone aggregator stays `on` from sleep onset through morning wake.

---

### D2 — Zone preset transition guard

**File:** `custom_components/universal_room_automation/domain_coordinators/hvac.py` — `_apply_house_state_presets` (or wherever zone preset transitions on occupancy).

**Change:** Defensive guard before flipping a zone preset to `away` during sleep.

```python
# v4.7.13: suppress sleep -> away preset flip when zone_persons home
if new_preset == "away" and self._house_state == "sleep":
    home_persons = [
        p for p in zone.zone_persons
        if (s := self.hass.states.get(p)) and s.state == "home"
    ]
    if home_persons:
        _LOGGER.debug(
            "Suppressing %s preset flip -> away during sleep: %s home in zone_persons",
            zone.zone_name, home_persons,
        )
        return  # keep current preset
```

### Acceptance Criteria

- **Verify:** Guard placed BEFORE the preset write — no setpoint recomputation triggered.
- **Test:** `test_v4713_zone_preset_does_not_flip_to_away_during_sleep_when_person_home`
- **Test:** `test_v4713_zone_preset_flips_normally_to_away_during_sleep_when_zone_persons_all_not_home`
- **Live:** Zero `sleep → away` transitions logged for Entertainment + Master Suite zone overnight while Oji is home.

---

### D3 — FanController vacancy hold mirror

**File:** `custom_components/universal_room_automation/domain_coordinators/hvac_fans.py` at `_evaluate_temp_fan` (lines 304-377 from earlier diagnostic, specifically the vacancy hold branch around line 337-345).

**Change:** When fan is on and room becomes unoccupied during sleep, hold indefinitely if a zone_persons member is home (covers motionless sleepers whose mmWave dropped them).

```python
# Existing logic at line 332-345 (vacancy hold start)
if not occupied and room_fan.is_on:
    # v4.7.13 sleep-trust: indefinite hold during sleep when person home
    if self._house_state == "sleep":
        zone = self._zone_manager.get_zone_for_room(room_fan.room_id)
        if zone and any(
            (s := self.hass.states.get(p)) and s.state == "home"
            for p in (zone.zone_persons or [])
        ):
            return True, room_fan.trigger, room_fan.speed_pct  # hold during sleep

    # ... existing vacancy hold timer logic continues ...
```

### Acceptance Criteria

- **Verify:** Hold branch returns `(True, trigger, speed_pct)` — fan stays at last commanded speed.
- **Verify:** Existing vacancy timer NOT cleared (so if person tracker subsequently goes not-home during sleep, normal vacancy timer takes over).
- **Test:** `test_v4713_fan_vacancy_hold_does_not_expire_during_sleep_when_person_home`
- **Test:** `test_v4713_fan_vacancy_normal_expiry_when_house_state_not_sleep`
- **Live:** `sensor.master_bedroom_power` does NOT show 100W↔270W oscillation pattern overnight.

---

## 3. What's intentionally OUT of scope

- **Room-level occupancy aggregator unchanged.** mmWave still drives `master_bedroom_occupied` — only the ZONE aggregator gets the person-tracker fallback. This preserves accurate room-level signals for other consumers (e.g., light automations should still go off when no motion).
- **No mmWave debounce / hold-timer tuning.** Separate cycle if wanted.
- **No manual "force occupied" override UX.** Separate cycle.
- **`person.state == "unknown"` treated as not-home.** Only `"home"` triggers fallback (safety bias).
- **No backfill of zone_persons defaults.** Existing config respected as-is. If a zone has no `zone_persons` configured, the fallback never engages and behavior is unchanged from v4.7.12.

---

## 4. Bug class watch

| Bug class | Risk in this cycle | Notes |
|---|---|---|
| #11 (UTC vs local TZ) | None | No timestamp logic. |
| #14 (config snapshot staleness) | Minimal | `_house_state` already snapshotted per tick. |
| #20 (concurrent reload race) | None | No registry mutations. |
| #42 (lambda + async_create_task) | None | No new scheduling. |
| #44 (test fixture authority) | Watch | New tests should use existing zone_persons fixture, not hand-craft. |
| #46 (async_update_entry re-entrancy) | None | No config-entry mutations. |
| #47 (lazy canonical UI surface violation) | None | No new entities. |

---

## 5. Plan completion tracking

After implementation, document explicitly:
- D1/D2/D3 status (shipped, partial, deferred)
- Any deviations from the planned signature/placement
- Live overnight evidence

---

## 6. Recall

- "Plan v4.7.13 sleep-state zone trust"
- "Resume sleep occupancy fallback"
- "Why did the fan keep stopping overnight"

## 7. References

- Memory backlog: `project_sleep_state_zone_presence_trust_backlog.md`
- Diagnostic conversation: prior session ending 2026-05-30, master bedroom fan investigation
- Precedent: `hvac.py:1502` `if self._house_state == "sleep": continue` (existing pattern)
- FanController vacancy hold: `hvac_fans.py:304-377` `_evaluate_temp_fan`
- FanController constant: `hvac_const.py:257` `DEFAULT_FAN_VACANCY_HOLD = 300`
