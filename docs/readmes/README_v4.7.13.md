# URA v4.7.13 — Sleep-State Zone Presence Trust Fallback

**Release date:** 2026-05-30
**Tier:** Tier 1 (single hotfix review)
**Scope:** Three short-circuits that mirror the existing `house_state == "sleep"` skip pattern (`hvac.py:1502`) into the zone occupancy aggregator, the zone preset transition logic, and the FanController vacancy hold.

---

## Triggering incident — 2026-05-30 overnight

Master bedroom fan stopped/started 4× through the night because the zone occupancy aggregator dropped Oji from `binary_sensor.zone_entertainment_master_suite_anyone` whenever mmWave lost his motionless body.

Sensor degeneration pattern during sleep:

| Sensor | Behavior | Failure mode |
|---|---|---|
| `binary_sensor.master_bedroom_presence` (mmWave) | 16 flickers, 10–15 min drops | mmWave loses motionless bodies |
| `binary_sensor.master_bedroom_motion` (PIR) | OFF 2h 18min straight | PIR can't fire on stationary body |
| `binary_sensor.master_bedroom_camera_person_detected` (Frigate) | OFF entire night | Camera blind to covered body in dark room |

3-sensor redundancy structurally degenerates to 1-sensor coverage during sleep. URA had `person.oji_udezue == home` data it never used as a fallback.

Cascade: mmWave drop → zone aggregator off → preset `sleep → away` → setpoint deadband widens → fan re-speed → power oscillation 100W↔270W → user wakes. Activity stream confirmed 6 sleep↔away transitions between 03:24 and 06:14 CDT.

---

## Deliverables

### D1 — Zone occupancy aggregator fallback

**File:** `custom_components/universal_room_automation/aggregation.py`
- `ZoneAnyoneBinarySensor.is_on` (around line 3178) — Layer 1 unchanged; falls through to new Layer 2.
- New helper `ZoneAnyoneBinarySensor._sleep_person_fallback_occupied` (around line 3192) — reads `coordinator_manager.house_state` and `hvac._zone_manager.zones[self.zone].zone_persons`; returns True if any tracker `state == "home"` during sleep. Try/except guarded.

**Acceptance criteria (from plan):**
- Layer 2 only triggers when `house_state == "sleep"` AND `zone_persons` non-empty AND at least one tracker `"home"`.
- `binary_sensor.zone_entertainment_master_suite_anyone` stays `on` while `person.oji_udezue == home` AND `house_state == sleep`, regardless of mmWave flicker.

### D2 — Zone preset transition guard

**File:** `custom_components/universal_room_automation/domain_coordinators/hvac.py`
- `_apply_house_state_presets` — guard inserted at around line 915 (immediately BEFORE the preset write decision branch). Mirrors `hvac.py:1502` `if self._house_state == "sleep": continue` precedent.
- When `effective_preset == "away" AND self._house_state == "sleep"` AND any `zone.zone_persons` entity is `"home"`, the guard logs at INFO and `continue`s the loop — no `climate.set_preset_mode` call, no setpoint recomputation.

**Acceptance criteria (from plan):**
- Guard placed BEFORE the preset write — no setpoint recomputation.
- Zero `sleep → away` transitions logged for Entertainment + Master Suite zone overnight while Oji is home.

### D3 — FanController vacancy hold mirror

**File:** `custom_components/universal_room_automation/domain_coordinators/hvac_fans.py`
- `_evaluate_temp_fan` — guard inserted into the existing "fan on + room unoccupied" branch (around line 342, immediately BEFORE the `if vacancy_seconds >= DEFAULT_FAN_VACANCY_HOLD` expiry check).
- When `self._house_state == "sleep"` AND any `zone.zone_persons` entity is `"home"`, returns `(True, room_fan.trigger, room_fan.speed_pct)` — fan stays at last commanded speed.
- Vacancy timer (`room_fan.vacancy_detected_time`) is NOT cleared, so if the person tracker subsequently goes not-home during sleep, the next tick falls through to normal vacancy expiry on the next evaluation.

**Acceptance criteria (from plan):**
- Hold branch returns `(True, trigger, speed_pct)`.
- Existing vacancy timer not cleared.
- `sensor.master_bedroom_power` does NOT show 100W↔270W oscillation overnight.

---

## Out of scope (from plan §3)

- **Room-level occupancy aggregator unchanged.** mmWave still drives `master_bedroom_occupied` — only the ZONE aggregator gets the person-tracker fallback. Preserves accurate room-level signals for other consumers (light automations still go off when no motion).
- **No mmWave debounce / hold-timer tuning.** Separate cycle if wanted.
- **No manual "force occupied" override UX.** Separate cycle.
- **`person.state == "unknown"` treated as not-home.** Only `"home"` triggers fallback (safety bias).
- **No backfill of `zone_persons` defaults.** Existing config respected. If a zone has no `zone_persons` configured, the fallback never engages — behavior identical to v4.7.12.

---

## Test changes

`quality/tests/test_v4713_sleep_state_zone_presence_trust.py` — 23 tests across:
- `TestD1ZoneAggregatorSleepFallback` (4) — source-shape assertions (helper exists, called from `is_on`, gated on sleep, guarded with try/except).
- `TestD1FallbackBehavior` (5) — exec'd-helper behavior across the three fallback branches + empty zone_persons + missing manager.
- `TestD2PresetGuardSourceShape` (3) — guard present, logs suppression, uses `continue`.
- `TestD2GuardBehavior` (4) — guard suppresses iff (away + sleep + person home), else proceeds.
- `TestD3FanVacancyHoldDuringSleep` (5) — drives real `FanController._evaluate_temp_fan` through the matrix.
- `TestD3SourceShape` (2) — guard tagged with version marker, does NOT clear vacancy timer.

Suite delta vs v4.7.12 baseline: **+23 passed**, failures and errors unchanged.

---

## Live validation checklist (overnight observation)

After restart on the next sleep window:

- [ ] **D1:** `binary_sensor.zone_entertainment_master_suite_anyone` stays `on` from sleep onset through morning wake while `person.oji_udezue == home`. Check Logbook for absence of off transitions.
- [ ] **D1 log:** Grep HA core log for `Zone 'entertainment_master_suite': sleep-state person fallback engaged` — confirms the helper engaged at least once when mmWave dropped.
- [ ] **D2:** Activity log for HVAC coordinator shows zero `preset_change` rows with `old_preset=sleep new_preset=away` for Entertainment + Master Suite zone overnight. (Compare against pre-deploy night which had 3 such entries.)
- [ ] **D2 log:** Grep HA core log for `Suppressing Entertainment + Master Suite preset flip -> away during sleep` — confirms the guard fired and `zone_persons` was non-empty.
- [ ] **D3:** `sensor.master_bedroom_power` shows a flat 100W (or whatever speed was last commanded) trace overnight rather than 100W↔270W oscillation. Compare to 2026-05-30 baseline night.
- [ ] **D3 log (debug):** If debug logging on `hvac_fans` is enabled, grep for `vacancy hold extended during sleep (person person.oji_udezue home)` to confirm the indefinite-hold branch took effect.

Negative checks:
- [ ] Pre-sleep behavior unchanged: when Oji is downstairs (mmWave off + `person.oji_udezue == home` BUT `house_state != "sleep"`), the zone correctly reports `off` (Layer 2 gated by sleep).
- [ ] Away behavior unchanged: when Oji leaves house during sleep (extreme: night drive), zone_persons all `not_home` → fallback dormant, normal vacancy expiry takes the fan off after `DEFAULT_FAN_VACANCY_HOLD` (300s).

---

## References

- Plan: `docs/planning/PLANNING_v4.7.13_sleep_state_zone_presence_trust.md`
- Precedent: `hvac.py:1502` `if self._house_state == "sleep": continue` (D5 duty-cycle skip)
- Backlog memo: `project_sleep_state_zone_presence_trust_backlog.md`
