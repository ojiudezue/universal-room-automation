# PLANNING — Part 2: EC + HVAC Options-Writeback Retrofit

**Status:** Build-ready plan. Depends on the reload-suppression cycle landing first. Tier elevated to operator-elevated Tier 2-DB (see Tier classification).
**Version:** unassigned (operator assigns at deploy time, per `feedback_versioning_convention`).
**Cycle scope:** Retrofit the v4.7.25 "options = sole source of truth + live-attr push" pattern onto the Energy Coordinator (EC) Numbers, the remaining HVAC RestoreEntity Numbers (DPM hysteresis, egress threshold/resume, fan-interference hold), and the two HVAC tunable factories (`_HVACTunableNumber` 60-66 + 70-76 cluster, `_HVACZoneKwhThresholdNumber` per-zone kWh thresholds). For each retrofitted Number: drop `RestoreEntity`, seed `self._value` from `{**entry.data, **entry.options}`, push the live coordinator attr + `async_update_entry` in the setter, fix any stale docstring, and ADD its CONF_* key to the `OPTIONS_RELOAD_SUPPRESS_KEYS` allowlist introduced by the reload-suppression cycle so form-path and device-card edits APPLY-IN-PLACE rather than full-reloading the CM.

**Hard dependency.** This cycle BUILDS ON TOP of `PLANNING_cm_option_writeback_reload_suppression.md`. Part 2 MUST ship AFTER the suppression cycle is live and validated. If `OPTIONS_RELOAD_SUPPRESS_KEYS` and `apply_in_place(...)` are not already in `__init__.py`, every key added by this cycle would trigger a full CM reload (the bug we're trying to retire wholesale), defeating the point. The two cycles cannot be merged because (a) the suppression cycle needs to harden the dispatcher contract before it grows to ~20 keys; (b) Tier 2-DB review surface on a combined cycle would balloon.

**Explicit out-of-scope.** Per-room `ComfortTempMinNumber` / `ComfortTempMaxNumber` persistence is OUT of scope for this cycle and tracked as its own follow-up. See "Plan completion tracking — explicit deferral list" below for the rationale.

---

## Institutional context verified

### Greps run + results (REUSED / NEW)

**Class enumeration — every `NumberEntity` subclass in `number.py` (verified this session via `grep -n '^class' custom_components/universal_room_automation/number.py`):**

| Class | Line | `RestoreEntity`? | `async_update_entry`? | CONF_* key | unique_id | In-scope for Part 2? |
|---|---|---|---|---|---|---|
| `TimeoutOverrideNumber` | 141 | NO | NO | (ROOM `occupancy_timeout`) | `<room>_timeout_override` | OPEN Q (ROOM-entry) |
| `ComfortTempMinNumber` | 177 | NO | NO | (`COMFORT_TEMP_MIN` const, NO persistence) | `<room>_comfort_temp_min` | OUT OF SCOPE (separate follow-up cycle — see deferral list; ROOM-entry reload path + data hazard) |
| `ComfortTempMaxNumber` | 213 | NO | NO | (`COMFORT_TEMP_MAX` const, NO persistence) | `<room>_comfort_temp_max` | OUT OF SCOPE (separate follow-up cycle — see deferral list; ROOM-entry reload path + data hazard) |
| `ComfortHumidityMaxNumber` | 249 | NO | NO | (per-room) | `<room>_comfort_humidity_max` | OPEN Q (ROOM-entry) |
| `ZoneEntryDwellNumber` | 285 | NO | YES (`:368`) | `CONF_HVAC_ZONE_ENTRY_DWELL` | `<DOMAIN>_hvac_zone_entry_dwell` | DONE in prior cycle (excluded) |
| `VacancyGraceMinutesNumber` | 376 | NO | YES (`:462`) | `CONF_HVAC_VACANCY_GRACE_MINUTES` | `<DOMAIN>_hvac_vacancy_grace_minutes` | DONE in prior cycle (excluded) |
| `VacancyGraceConstrainedNumber` | 467 | NO | YES (`:551`) | `CONF_HVAC_VACANCY_GRACE_CONSTRAINED` | `<DOMAIN>_hvac_vacancy_grace_constrained` | DONE in prior cycle (excluded) |
| `MaxOccupancyHoursNumber` | 561 | NO | YES (`:625`) | `CONF_HVAC_MAX_OCCUPANCY_HOURS` | `<DOMAIN>_hvac_max_occupancy_hours` | DONE in prior cycle (excluded) |
| `OffPeakDrainNumber` | 633 | YES | NO | `CONF_ENERGY_OFFPEAK_DRAIN_{EXCELLENT,GOOD,MODERATE,POOR}` (×4 instances) | `<DOMAIN>_energy_offpeak_drain_<quality>` | **YES** (D1) |
| `PeakBufferTargetNumber` | 720 | YES | NO | `CONF_ENERGY_PEAK_BUFFER_TARGET` | `<DOMAIN>_energy_peak_buffer_target` | **YES** (D1) |
| `ArbitrageChargeLeadTimeNumber` | 845 | YES | NO | `CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN` (verify exact const name in build pass) | `<DOMAIN>_energy_arbitrage_charge_lead_time_min` | **YES** (D1) |
| `EVBatteryDrainSOCNumber` | 968 | YES | NO | `CONF_ENERGY_EV_BATTERY_DRAIN_SOC` (verify in build pass) | `<DOMAIN>_energy_ev_battery_drain_soc` | **YES** (D1) |
| `FillPrioritySOCNumber` | 1095 | YES | NO | `CONF_ENERGY_FILL_PRIORITY_SOC` (verify in build pass) | `<DOMAIN>_energy_fill_priority_soc` | **YES** (D1) |
| `ExcessSolarSOCNumber` | 1211 | YES | NO | `CONF_ENERGY_EXCESS_SOLAR_SOC` (verify in build pass) | `<DOMAIN>_energy_excess_solar_soc` | **YES** (D1) |
| `BayesianCellStalenessNumber` | 1330 | YES | NO | `CONF_BAYESIAN_CELL_STALENESS_DAYS` (verify in build pass) | `<DOMAIN>_bayesian_cell_staleness_days` | **YES** (D1) — not EC, but same Pattern A |
| `_RoutineNumberBase` subclasses (`RoutineEventCooldownDaysNumber`, `RoutineEventMinSeverityNumber`, `RoutineRegimeBaselineWindowNumber`, `RoutineRegimeRecentWindowNumber`) | 1408-1594 | YES (via base) | YES (only `RoutineEventMinSeverityNumber` at `:1528`) | `CONF_ROUTINE_*` family | `<DOMAIN>_routine_*` | **YES** (D2) — base class retrofit + per-class verification |
| `_HVACTunableNumber` factory output (cover/fan cluster 60-66 + AC ramp-down 70-76) | 1634 | YES | NO | 14 distinct CONF keys (see "Factory enumeration" below) | `<DOMAIN>_hvac_<suffix>` ×14 | **YES** (D3) — factory retrofit, single surgery covers 14 entities |
| `_HVACZoneKwhThresholdNumber` factory output (per AC zone, 3 typical) | 1972 | YES | NO | (`kwh_rate_threshold` per-zone on `ZoneState`; CONF key TBD — verify in build pass) | `<DOMAIN>_hvac_ac_kwh_threshold_<zone_id>` | **YES** (D4) — factory retrofit; per-zone target |
| `DynamicPresetDwellMinutesNumber` | 2115 | YES (prior to D2) | YES (`:2187`) | `CONF_DYNAMIC_PRESET_DWELL_MINUTES` | `<DOMAIN>_energy_dynamic_preset_dwell_minutes` | DONE in prior cycle's D2 (excluded) |
| `DynamicPresetHysteresisFNumber` | 2197 | YES | YES (`:2266`) | `CONF_DYNAMIC_PRESET_HYSTERESIS_F` | `<DOMAIN>_energy_dynamic_preset_hysteresis_f` | **YES** (D5) |
| `HVACEgressPauseThresholdNumber` | 2290 | YES | YES (verify) | `CONF_HVAC_EGRESS_PAUSE_THRESHOLD_MIN` (verify in build pass) | `<DOMAIN>_hvac_egress_threshold_min` | **YES** (D5) |
| `HVACEgressResumeDelayNumber` | 2389 | YES | YES (verify) | `CONF_HVAC_EGRESS_RESUOR_DELAY_MIN` (verify in build pass) | `<DOMAIN>_hvac_egress_resume_delay_min` | **YES** (D5) |
| `FanInterferenceHoldNumber` | 2487 | YES | YES (`:2591`) | `CONF_FAN_INTERFERENCE_HOLD_S` | `<DOMAIN>_fan_interference_hold_s` | **YES** (D5) |

**Excluded from this cycle (per task):** The 4 HVAC presence timers (`ZoneEntryDwellNumber`, `VacancyGraceMinutesNumber`, `VacancyGraceConstrainedNumber`, `MaxOccupancyHoursNumber`) and `DynamicPresetDwellMinutesNumber` — all shipped in the v4.7.25 cycle and/or its sibling reload-suppression cycle. `ComfortTempMinNumber` and `ComfortTempMaxNumber` per-room persistence is also explicitly out-of-scope and tracked as a separate follow-up cycle (see deferral list).

**Factory enumeration — `_HVACTunableNumber` outputs (call sites `:1772-1841` cover cluster + `:1871-1949` AC ramp-down cluster), verified this session:**

| Suffix | Display name | CONF key | runtime_field | sub_controller_attr |
|---|---|---|---|---|
| `cover_close_threshold` | 60 · Cover Close Threshold | `CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA` | `_occupied_close_delta` | `_cover_controller` |
| `cover_close_temp` | 61 · Cover Close Temp | `CONF_HVAC_COVER_CLOSE_TEMP` | `_cover_close_temp` | `_cover_controller` |
| `cover_open_temp` | 62 · Cover Open Temp | `CONF_HVAC_COVER_OPEN_TEMP` | `_cover_open_temp` | `_cover_controller` |
| `cover_override_duration` | 63 · Cover Override Duration | `CONF_HVAC_COVER_OVERRIDE_HOURS` | `_cover_override_hours` | `_cover_controller` |
| `solar_bank_floor` | 64 · Solar Banking Cool Floor | `CONF_HVAC_SOLAR_BANK_FLOOR` | `_solar_bank_floor` | `_predictor` |
| `fan_on_threshold` | 65 · Fan On Threshold | `CONF_HVAC_FAN_ACTIVATION_DELTA` | `_activation_delta` | `_fan_controller` |
| `fan_off_hysteresis` | 66 · Fan Off Hysteresis | `CONF_HVAC_FAN_HYSTERESIS` | `_deactivation_delta` | `_fan_controller` |
| `ac_nudge_size` | 70 · AC Nudge Size | `CONF_HVAC_AC_NUDGE_SIZE` | `_nudge_size_f` | `_override_arrester` |
| `ac_nudge_duration` | 71 · AC Nudge Duration | `CONF_HVAC_AC_NUDGE_DURATION` | `_nudge_duration_min` | `_override_arrester` |
| `ac_sustained_samples` | 72 · AC Sustained Samples | `CONF_HVAC_AC_SUSTAINED_SAMPLES` | `_sustained_samples` | `_override_arrester` |
| `ac_detection_time_gate` | 73 · AC Detection Time Gate | `CONF_HVAC_AC_DETECTION_TIME_GATE` | `_detection_time_gate_min` | `_override_arrester` |
| `ac_hard_reset_daily_limit` | 74 · AC Hard Reset Daily Limit | `CONF_HVAC_AC_HARD_RESET_DAILY_LIMIT` | `_hard_reset_daily_limit` | `_override_arrester` |
| `ac_hard_reset_min_interval` | 75 · AC Hard Reset Min Interval | `CONF_HVAC_AC_HARD_RESET_MIN_INTERVAL` | `_hard_reset_min_interval_min` | `_override_arrester` |
| `ac_nudge_eval_delay` | 76 · AC Nudge Eval Delay | `CONF_HVAC_AC_NUDGE_EVAL_DELAY` | `_nudge_eval_delay_s` | `_override_arrester` |

14 entities, all sharing the same factory body at `number.py:1634-1748` — a single factory edit retrofits all 14.

**Watch-list — entities whose live target is NOT a simple scalar attr.** The factory's push contract today is `setattr(sub_controller, runtime_field, value)` (`number.py:1694`). These look scalar. NONE of the 14 above clearly feeds a derived/recomputed value based on a name scan — BUT the build pass MUST verify by reading each `sub_controller.runtime_field` site for any precomputed cache (e.g. `timedelta(minutes=self._nudge_duration_min)` stashed somewhere). Specifically flagged for closer look (because of their "duration/delay/interval" names): `ac_nudge_duration` (71), `ac_nudge_eval_delay` (76), `ac_detection_time_gate` (73), `ac_hard_reset_min_interval` (75), `cover_override_duration` (63). If any of these stashes a `timedelta`, `apply_in_place` MUST trigger a recompute, not just an attr poke.

For the EC family (D1), `OffPeakDrainNumber` is unique in that it calls `energy.set_offpeak_drain(quality, value)` (`number.py:419-420`) — NOT a direct attr write. The retrofit MUST call the same setter from `apply_in_place` (not poke a private attr), and the setter must remain idempotent. Build pass MUST read `EnergyCoordinator.set_offpeak_drain` to confirm.

**Existing clamp/validation invariants (must mirror the A-HIGH-1 pattern if cross-field constraints exist):**
- EC has cross-field invariants between `CONF_ENERGY_EXCESS_SOLAR_SOC` and `CONF_ENERGY_FILL_PRIORITY_SOC` (verify in build pass — operator may have wired a sanity check elsewhere). If verified, mirror the A-HIGH-1 bidirectional clamp pattern from `VacancyGraceMinutesNumber.async_set_native_value`.
- DPM hysteresis (`CONF_DYNAMIC_PRESET_HYSTERESIS_F`) — no known cross-field constraint; verify.
- HVAC egress pause/resume — likely cross-field (pause-threshold vs resume-delay). Verify and mirror A-HIGH-1 if found.

### Prior planning docs consulted

- `docs/planning/PLANNING_hvac_presence_timer_knobs_and_options_writeback_retrofit.md` §347-428 — original Part-2 deferral inventory. This plan converts that inventory from a backlog narrative into a concrete deliverable list. The inventory's Part-2 line items map 1-to-1 to D1, D2, D3, D4, D5 below.
- `docs/planning/PLANNING_cm_option_writeback_reload_suppression.md` — the hard dependency. Read end-to-end. Its `OPTIONS_RELOAD_SUPPRESS_KEYS` constant + `apply_in_place(...)` dispatcher are the surfaces this cycle extends. Specifically: D1-D5 each ADD their CONF_* keys to the allowlist and ADD a dispatch branch to `apply_in_place`.
- `docs/planning/PLANNING_v4.7.6.1_labels_helpers_excess_solar_number.md` — skim. Precedent for the `ExcessSolarSOCNumber` Number entity being promoted from a form field. Confirms current persistence shape.

### Memory bodies pulled

- `feedback_ura_mirror_pattern` — the v4.3.2 "RestoreEntity = runtime store; entry.options = seed only" pattern is the doctrine being RETIRED by this cycle. Every EC docstring that cites this pattern as canonical is OUT OF DATE; update each as the class is retrofitted (D1, D2, D5).
- `project_v4_7_25_hvac_presence_timer_knobs_live` — the reference implementation. The four HVAC presence-timer Numbers shipped in v4.7.25 are the template every retrofitted Number imitates.
- `feedback_parsimonious_room_config` — no new CONFs; no new form fields; no new Number entities. Only behavior changes on existing entities.
- `feedback_pre_deploy_zero_bugs_gate` — applies.
- `feedback_no_fabrication` — applies. Every CONF_* and live-attr citation in this plan was verified this session by grep against `number.py`; where the brief used a guessed CONF name, this plan flags it as "verify in build pass" rather than assert.

### Design docs read

- `docs/Coordinator/HVAC.md` (if present) — for the HVAC tunable factory targets (`_cover_controller._occupied_close_delta` etc.). Must be re-read in build pass to confirm each `runtime_field` is a scalar attr and not a cached/derived value.
- `docs/Coordinator/Energy.md` (if present) — for the EC scalar attrs that the EC Numbers push to. Specifically the `OffPeakDrainNumber.set_offpeak_drain` setter contract.

### Code locations surveyed (end-to-end during scoping)

- `custom_components/universal_room_automation/number.py:633-1402` — full EC Number family.
- `custom_components/universal_room_automation/number.py:1408-1604` — `_RoutineNumberBase` + 4 subclasses.
- `custom_components/universal_room_automation/number.py:1608-1842` — `_hvac_tunable_number_factory` + cover/fan cluster call sites.
- `custom_components/universal_room_automation/number.py:1845-1950` — AC ramp-down cluster call sites.
- `custom_components/universal_room_automation/number.py:1961-2096` — `_hvac_zone_kwh_threshold_factory` + per-zone setup loop at `:106-116`.
- `custom_components/universal_room_automation/number.py:2197-2596` — DPM hysteresis + HVAC egress + fan-interference hold.
- `docs/planning/PLANNING_cm_option_writeback_reload_suppression.md` — entire doc (the hard dependency).

---

## Verified HA best-practice facts (carried forward from sibling plan)

All four facts from `PLANNING_cm_option_writeback_reload_suppression.md` apply here. Re-verify in build pass against pinned HA-core source:
1. `async_update_entry` short-circuits on no-change.
2. Combining update listener with `async_update_reload_and_abort` is deprecated. URA does not currently trip it.
3. `ConfigEntry.data` / `ConfigEntry.options` must never be mutated directly — go through `async_update_entry`.
4. HA data-entry-flow `errors` dict supports multiple simultaneous keys. (Not directly relevant here — no new form validation.)

---

## Restart-restore — same coverage as v4.7.25

For every retrofitted Number, restart-restore is preserved without any RestoreEntity:
- Options live in `.storage/core.config_entries` and survive process restart by definition.
- Each Number's `__init__` MUST re-seed `self._value = cast({**entry.data, **entry.options}.get(CONF, DEFAULT))`. Mirror the existing v4.7.25 pattern (`number.py:600-603`, `:414-417`).
- The factory `_HVACTunableNumber.__init__` already does this at `number.py:1659-1665` (it reads `cm_config = {**cm_entry.data, **cm_entry.options}`). No structural change there — just drop RestoreEntity and the restore branch.

---

## Design approach

Mechanical retrofit. The pattern is identical to v4.7.25 / the reload-suppression cycle. For each in-scope class:

1. **Drop `RestoreEntity`** from the class bases. Drop the `from homeassistant.helpers.restore_state import RestoreEntity` import if no other class in the file still uses it (verify in build pass — `_RoutineNumberBase` and many other classes do, so the import almost certainly stays).
2. **Drop `async_added_to_hass`** restore branches that read `async_get_last_state`. If `async_added_to_hass` is doing anything else important (e.g. registering a dispatcher listener for `SIGNAL_HVAC_ENTITIES_UPDATE` — the factory does this at `:1721-1735`), KEEP that part and only drop the restore step.
3. **Seed `self._value`** in `__init__` from `{**entry.data, **entry.options}.get(CONF, DEFAULT)`. For the per-room comfort entities (if scope is approved), seed from `coordinator.entry.data | coordinator.entry.options`.
4. **In `async_set_native_value`**:
   - Set `self._value = cast(value)`.
   - Push to the live coordinator attr (or call the controller setter, e.g. `energy.set_offpeak_drain(quality, value)`).
   - Call `self.hass.config_entries.async_update_entry(entry, options={**entry.options, CONF: value})`.
   - `self.async_write_ha_state()`.
   - In that order. (Live-attr push BEFORE writeback so the next decision cycle picks up the new value even if the reload settles later.)
5. **Fix docstrings.** Every class touched whose docstring cites the v4.3.2 "RestoreEntity = canonical runtime store" pattern MUST be rewritten to "entry.options is the SOLE source of truth. No RestoreEntity."
6. **Add CONF key to `OPTIONS_RELOAD_SUPPRESS_KEYS`** in `__init__.py`. ONE atomic edit per deliverable — list its keys at the top of the deliverable.
7. **Add dispatch branch to `apply_in_place(...)`** in `__init__.py`. Each branch is idempotent. For non-scalar targets (controller setters, derived caches), call the same setter the Number setter calls.
8. **Mirror A-HIGH-1 clamp** if a verified cross-field invariant exists (build pass to verify).

The suppression cycle's snapshot machinery (`hass.data[DOMAIN]["cm_last_applied_options"]`) is REUSED unchanged. Adding ~20 more keys to the allowlist does not change the diff algorithm.

---

## Deliverables

### D1: EC Number family retrofit

**Files:** `custom_components/universal_room_automation/number.py`, `custom_components/universal_room_automation/__init__.py`.

**Classes retrofitted** (drop RestoreEntity + add writeback + update docstring):
- `OffPeakDrainNumber` (×4 instances by quality) — `number.py:633`. Setter calls `energy.set_offpeak_drain(quality, value)`.
- `PeakBufferTargetNumber` — `number.py:720`.
- `ArbitrageChargeLeadTimeNumber` — `number.py:845`.
- `EVBatteryDrainSOCNumber` — `number.py:968`.
- `FillPrioritySOCNumber` — `number.py:1095`.
- `ExcessSolarSOCNumber` — `number.py:1211`.
- `BayesianCellStalenessNumber` — `number.py:1330` (not strictly EC; same Pattern A retrofit).

**`__init__.py` edits:**
- Append the 7+ CONF keys (`CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT/GOOD/MODERATE/POOR`, `CONF_ENERGY_PEAK_BUFFER_TARGET`, `CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN`, `CONF_ENERGY_EV_BATTERY_DRAIN_SOC`, `CONF_ENERGY_FILL_PRIORITY_SOC`, `CONF_ENERGY_EXCESS_SOLAR_SOC`, `CONF_BAYESIAN_CELL_STALENESS_DAYS`) to `OPTIONS_RELOAD_SUPPRESS_KEYS`.
- Add dispatch branches to `apply_in_place(...)`. For `OffPeakDrain*`, dispatch calls `energy.set_offpeak_drain(<quality>, value)` (NOT a direct attr write). For the rest, push to the corresponding scalar attr (verify each in build pass).

**Cross-field verification:** Check whether any EC pair (e.g. `EXCESS_SOLAR_SOC` vs `FILL_PRIORITY_SOC`) has an invariant; if so, mirror A-HIGH-1 clamp in BOTH the setter and the form path. **Open question for operator** if verification finds a constraint that isn't already enforced.

#### D1 Acceptance Criteria
- **Verify:** None of the listed EC classes inherits from `RestoreEntity`. All call `async_update_entry` in their setter. All docstrings reflect the options-sole-source pattern.
- **Verify:** Every listed CONF key is a member of `OPTIONS_RELOAD_SUPPRESS_KEYS`.
- **Verify:** `apply_in_place(hass, entry, {CONF_X}, new_options)` routes correctly for each key — for OffPeakDrain, the EC setter `energy.set_offpeak_drain(quality, value)` is invoked; for the rest, the matching scalar attr is set.
- **Sensor:** All 10+ EC Number entities retain their `unique_id` and `entity_id` post-retrofit (entity-identity stability bar). Their displayed `native_value` matches `entry.options` post-restart.
- **Test:** `test_ec_no_restoreentity` (AST scan), `test_ec_setter_calls_async_update_entry` (mocked, per class), `test_ec_keys_in_suppress_allowlist`, `test_apply_in_place_routes_ec_keys` (one assertion per key), `test_offpeak_drain_dispatch_uses_set_offpeak_drain_setter`.
- **Live:** For each EC Number: edit the value, observe sibling EC Numbers' `last_changed` does NOT advance (reload suppressed). Restart HA; value persists. For OffPeakDrain quality=excellent: edit → confirm `energy.set_offpeak_drain('excellent', N)` was invoked (log line or coordinator attr inspection).

### D2: Routine Number base-class retrofit

**Files:** `custom_components/universal_room_automation/number.py`, `custom_components/universal_room_automation/__init__.py`.

**Classes retrofitted:**
- `_RoutineNumberBase` — `number.py:1408`. Drop `RestoreEntity` from base. Update the `async_added_to_hass` restore branch at `:1447`.
- `RoutineEventCooldownDaysNumber` — `number.py:1465`. Confirm setter writes back (build pass: only `RoutineEventMinSeverityNumber` has a verified `async_update_entry` at `:1528`; the others may need NEW writeback bodies).
- `RoutineEventMinSeverityNumber` — `number.py:1491`. Already does writeback at `:1528`. Just drop RestoreEntity from base.
- `RoutineRegimeBaselineWindowNumber` — `number.py:1543`. Add writeback if missing.
- `RoutineRegimeRecentWindowNumber` — `number.py:1571`. Add writeback if missing.

**`__init__.py` edits:** Append the 4 `CONF_ROUTINE_*` keys to `OPTIONS_RELOAD_SUPPRESS_KEYS`. Add 4 dispatch branches to `apply_in_place(...)`. The Routine target attrs need to be identified (build pass against `domain_coordinators/routine*.py` or whichever coordinator hosts these).

**Watch:** the base class drop must not strand a sibling that legitimately needs RestoreEntity. Build pass MUST confirm no other Number outside `_RoutineNumberBase` users still relies on the base's restore semantics.

#### D2 Acceptance Criteria
- **Verify:** `_RoutineNumberBase` no longer inherits from `RestoreEntity`. All 4 subclasses' setters call `async_update_entry`.
- **Verify:** All 4 `CONF_ROUTINE_*` keys are in `OPTIONS_RELOAD_SUPPRESS_KEYS`.
- **Sensor:** The 4 Routine Number entities retain `unique_id` + `entity_id`.
- **Test:** `test_routine_base_no_restoreentity`, `test_routine_setters_writeback` (×4), `test_routine_keys_in_suppress_allowlist`.
- **Live:** Edit `RoutineEventCooldownDaysNumber` → reload suppressed, value persists across restart.

### D3: `_HVACTunableNumber` factory retrofit (14 entities)

**Files:** `custom_components/universal_room_automation/number.py`, `custom_components/universal_room_automation/__init__.py`.

**Change.** Single edit to the factory at `number.py:1634-1748`:
- Drop `RestoreEntity` from the class bases.
- Drop the `last_state` read at `:1704-1712` from `async_added_to_hass`. KEEP the `SIGNAL_HVAC_ENTITIES_UPDATE` dispatcher hookup at `:1721-1735` (still needed for cross-coordinator init race).
- In `async_set_native_value` (build pass to locate exact line — likely around `:1737-1745`): keep the existing push-to-controller; ADD `self.hass.config_entries.async_update_entry(self._entry, options={**self._entry.options, conf_key: cast(value)})` after the controller push, before `self.async_write_ha_state()`. Today, the factory does NOT write back at all (verified — searching the factory body found no `async_update_entry`).
- Update the docstring at `:1623-1631` ("RestoreEntity-backed (slider survives restart)" → "entry.options is the sole source of truth; restart re-seeds via the factory `__init__`").

**`__init__.py` edits:**
- Append the 14 `CONF_HVAC_*` keys from the factory enumeration table to `OPTIONS_RELOAD_SUPPRESS_KEYS`.
- Add 14 dispatch branches to `apply_in_place(...)` — each setting `getattr(hvac.<sub_controller_attr>, runtime_field, ...) = value` (cast appropriately). The dispatcher needs the same `cast` (int vs float) the factory uses; since the factory knows this per-instance, the cleanest path is to expose a small adapter: for these 14 keys, the dispatcher delegates back to the Number entity's setter rather than re-implementing the cast/push. Build pass to choose: (a) duplicate the controller-push logic in `apply_in_place`, or (b) look up the entity by unique_id and call its setter. Option (b) is DRYer but has lifecycle gotchas (entity not yet registered during boot). **Recommend option (a)** with explicit per-key dispatch entries; the 14 entries are mechanical.

**Watch-list recompute triggers.** As called out in Institutional Context, verify each of `ac_nudge_duration`, `ac_nudge_eval_delay`, `ac_detection_time_gate`, `ac_hard_reset_min_interval`, `cover_override_duration` to see if their `runtime_field` is consumed as a `timedelta` cache. If yes, `apply_in_place` MUST call a recompute helper on the controller (e.g. `controller.invalidate_cached_durations()`), not just `setattr`.

#### D3 Acceptance Criteria
- **Verify:** Factory no longer inherits from `RestoreEntity`. Setter calls `async_update_entry`.
- **Verify:** All 14 CONF keys in `OPTIONS_RELOAD_SUPPRESS_KEYS`. All 14 dispatch branches present in `apply_in_place`.
- **Verify:** Watch-list classes either (a) have scalar targets (confirmed in build pass), or (b) trigger a recompute helper.
- **Sensor:** All 14 entities retain `unique_id` + `entity_id`. Display values match `entry.options` post-restart.
- **Test:** `test_hvac_tunable_factory_no_restoreentity`, `test_hvac_tunable_factory_writeback` (parameterised across the 14 keys), `test_hvac_tunable_keys_in_suppress_allowlist` (asserts all 14), `test_apply_in_place_routes_hvac_tunable_keys` (parameterised), `test_watchlist_keys_trigger_recompute_if_required`.
- **Live:** Edit 60 (Cover Close Threshold), 71 (AC Nudge Duration), 76 (AC Nudge Eval Delay). For each: sibling tunables' `last_changed` does NOT advance; the corresponding `hvac._cover_controller._occupied_close_delta` (etc.) reads the new value. Restart HA; values persist.

### D4: `_HVACZoneKwhThresholdNumber` factory retrofit (per-zone)

**Files:** `custom_components/universal_room_automation/number.py`, `custom_components/universal_room_automation/__init__.py`.

**Change.** Factory at `number.py:1972-2096`. Drop RestoreEntity; add writeback in `async_set_native_value`. The push target is `ZoneState.kwh_rate_threshold` (per-zone, looked up via `coordinator_manager → hvac → _zone_manager → zones[zone_id]` per the factory's lookup chain at `number.py:1966-1969`).

**The per-zone CONF key shape** is NOT a fixed list of constants — `kwh_rate_threshold` lives on `ZoneState`, not in `entry.options`, today. Build pass MUST verify: is there a per-zone CONF key (`CONF_HVAC_AC_KWH_THRESHOLD_<zone_id>` or similar) in `hvac_const.py`, OR is the threshold not currently persisted into `entry.options` at all? If NOT persisted, this deliverable EITHER:
- (a) introduces a per-zone CONF key family (NEW constants — requires institutional verification that no equivalent exists), OR
- (b) is dropped from Part 2 and re-scoped as a standalone cycle (since adding new CONFs is itself a substantive change deserving its own review).

**Recommendation: split D4 out as a standalone follow-up cycle** if the build-pass verification confirms there's no existing per-zone CONF persistence. This keeps Part 2 mechanical (drop RestoreEntity + add writeback for existing CONFs) and pushes the new-CONF-design question to its own scoped cycle.

**`__init__.py` edits:** IF D4 proceeds in this cycle, the per-zone CONF keys are added to `OPTIONS_RELOAD_SUPPRESS_KEYS` and `apply_in_place(...)` gets a per-zone dispatch branch.

#### D4 Acceptance Criteria
- **Verify:** EITHER the factory is retrofitted with writeback against an existing per-zone CONF key, OR D4 is split out as a separate cycle (with a backlog memo filed).
- **Sensor:** Per-zone kWh threshold Numbers retain `unique_id` + `entity_id`.
- **Test:** Conditional on path chosen.
- **Live:** Edit one zone's kWh threshold; reload suppressed; restart HA; value persists.

### D5: Remaining HVAC/DPM RestoreEntity Numbers retrofit

**Files:** `custom_components/universal_room_automation/number.py`, `custom_components/universal_room_automation/__init__.py`.

**Classes retrofitted:**
- `DynamicPresetHysteresisFNumber` — `number.py:2197`. Already writes back at `:2266`. Drop RestoreEntity + restore branch.
- `HVACEgressPauseThresholdNumber` — `number.py:2290`. Verify setter writes back; add if missing.
- `HVACEgressResumeDelayNumber` — `number.py:2389`. Verify setter writes back; add if missing.
- `FanInterferenceHoldNumber` — `number.py:2487`. Already writes back at `:2591`. Drop RestoreEntity + restore branch.

**Cross-field check:** `HVAC_EGRESS_PAUSE_THRESHOLD_MIN` vs `HVAC_EGRESS_RESUME_DELAY_MIN` — likely cross-field (you can't resume before pausing). Verify and mirror A-HIGH-1 clamp if applicable.

**`__init__.py` edits:**
- Append `CONF_DYNAMIC_PRESET_HYSTERESIS_F`, `CONF_HVAC_EGRESS_PAUSE_THRESHOLD_MIN` (verify name), `CONF_HVAC_EGRESS_RESUME_DELAY_MIN` (verify name), `CONF_FAN_INTERFERENCE_HOLD_S` to `OPTIONS_RELOAD_SUPPRESS_KEYS`.
- Add 4 dispatch branches to `apply_in_place(...)`.

**Watch:** `FanInterferenceHoldNumber` is consumed by the fan-interference holds in `presence.py` (see v4.7.20 cycle). The hold duration may be cached as a `timedelta`. Build pass to verify; if cached, recompute trigger required.

#### D5 Acceptance Criteria
- **Verify:** All 4 classes no longer inherit from `RestoreEntity`. All 4 setters call `async_update_entry`.
- **Verify:** All 4 CONF keys are in `OPTIONS_RELOAD_SUPPRESS_KEYS`. Dispatch branches in `apply_in_place(...)`.
- **Verify:** Egress pause/resume cross-field invariant (if confirmed) is enforced via A-HIGH-1-style clamp.
- **Sensor:** The 4 Number entities retain `unique_id` + `entity_id`.
- **Test:** `test_remaining_hvac_no_restoreentity` (AST scan), `test_remaining_hvac_writeback` (×4), `test_remaining_hvac_keys_in_suppress_allowlist`, `test_egress_clamp_invariant` (if applicable).
- **Live:** Edit each Number; sibling Numbers' `last_changed` does NOT advance; restart HA; value persists. For egress: try to set resume-delay > pause-threshold → rejected (clamp).

### D6: Tests

**Files:** `quality/tests/`.

Beyond the per-D tests called out above, add suite-level tests:
1. `test_no_restoreentity_left_in_number_py` — AST scan asserting NO class in `number.py` still inherits from `RestoreEntity` (post-D1-D5; per-room Numbers excluded if they remain out-of-scope).
2. `test_options_reload_suppress_keys_membership` — asserts the allowlist contains exactly the set of CONFs documented in the planning doc (cycle's suppress-keys + prior cycle's + this cycle's additions).
3. `test_apply_in_place_dispatch_coverage` — asserts EVERY key in `OPTIONS_RELOAD_SUPPRESS_KEYS` has a corresponding dispatch branch in `apply_in_place`.
4. `test_part2_retrofit_does_not_break_v4_7_25_keys` — regression: the 4 HVAC presence timers + DPM dwell still behave identically.

#### D6 Acceptance Criteria
- **Verify:** All 4 suite tests pass.
- **Test:** `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` baseline-diffs CLEAN against `pre-review-v<assigned>`.
- **Live:** N/A.

### D7: Documentation + backlog cleanup

- Update `docs/Coordinator/HVAC.md` and `docs/Coordinator/Energy.md` (if present) with the expanded "Runtime-tunable option keys" sections.
- Close the "Options-writeback retrofit — EC Numbers + DPM/HVAC RestoreEntity Numbers" backlog memo (filed at the end of the prior cycle).
- File a new backlog memo IF the per-room Numbers (OPEN QUESTION below) remain out-of-scope after this cycle.
- File the dedicated ComfortTempMin/Max per-room persistence follow-up cycle memo (see deferral list).

#### D7 Acceptance Criteria
- **Verify:** Docs updated, backlog memo closed, ComfortTempMin/Max follow-up memo filed.

---

## Critical edge cases (each MUST be covered by a test)

1. **Factory class retrofit doesn't strand a non-factory user.** D3's drop of RestoreEntity from `_HVACTunableNumber` only affects the 14 factory outputs. Confirm via AST scan that no other class inherits from `_HVACTunableNumber` (the factory is `def _hvac_tunable_number_factory(...) -> type`, so direct inheritance is unlikely, but verify).
2. **OffPeakDrain setter-vs-attr dispatch.** `apply_in_place` for `CONF_ENERGY_OFFPEAK_DRAIN_<quality>` MUST call `energy.set_offpeak_drain(quality, value)` not a direct attr write. Test asserts the setter is invoked.
3. **Watch-list recompute triggers.** For any tunable verified to cache a `timedelta` (or any derived value), `apply_in_place` MUST trigger the recompute. Failure mode: silent stale-cache where the Number entity shows the new value but the controller keeps using the old derived form.
4. **Cross-field clamps under form path.** Any cross-field invariant verified in this cycle (EC, egress) MUST be enforced both in the setter (entity path) AND in the form save path (config_flow). Mirror the A-HIGH-1 layered approach from v4.7.25.
5. **Boot-time race on factory-output entities.** The factory's `SIGNAL_HVAC_ENTITIES_UPDATE` dispatcher hookup at `number.py:1721-1735` handles the case where the sub-controller isn't ready at entity-add time. Retrofit preserves this (only the `last_state` block is dropped). Test that the dispatcher-handler still fires correctly after retrofit.
6. **Apply-in-place lookup of `coordinator_manager`.** `apply_in_place` runs from `_async_update_listener`, which can fire any time after CM setup. The lookup `hass.data[DOMAIN].get("coordinator_manager")` must be defensive — if absent or mid-teardown, dispatch must early-return. Existing v4.7.25 dispatch branches already do this; mirror it.
7. **Existing RestoreEntity state.** Some retrofitted Numbers may have stored a value in HA's recorder (Restore framework) that is more recent than `entry.options` (e.g. user edited an EC value, system crashed before `async_update_entry` returned — though it's `await`ed so this is narrow). On first post-deploy boot, the entity will read `entry.options` and ignore any stale recorder state. **This is correct behavior post-retrofit** but is a one-time UX surprise if anyone had pending un-persisted edits. Acceptable per the v4.7.25 doctrine flip.

---

## Tier classification

**Decision: operator-elevated Tier 2-DB (three parallel reviews, framing-disjoint).**

Per the URA CLAUDE.md "Operator-elevated Tier 2-DB" clause, the operator may elevate any cycle to Tier 2-DB even when the standard structural triggers (DB schema change, ≥3 DAO migration, payload-shape change, behavioral fixture against real schemas, planned migration follow-up) do not fire. The standard justification is **trust-hierarchy ripple** — situations where a small surgical fix risks regressions across multiple coordinators.

**Operator elevation rationale (recorded here for reviewers):**
- The CM reload path's blast radius spans EVERY coordinator on the CM entry: presence, HVAC, energy, safety, diagnostics, house_state, signals, routine. This cycle extends the in-place apply path to ~20 more CONF keys touching HVAC sub-controllers (cover/fan/predictor/override_arrester), EC (offpeak-drain setter, peak-buffer, arbitrage, EV/fill/excess SOC, Bayesian staleness), DPM (hysteresis), egress (pause/resume), and fan-interference. Every dispatch branch is a chance to silently desync a Number's displayed value from the live controller attr that the next decision cycle reads. A wrong dispatch silently runs the controller against stale tuning.
- The operator has set a high robustness bar — verbatim: *"must be robust, no bugs in this very basic high traffic system."* The listener fires on every knob edit, every form submit, every reset path, and during restart-path completion. With ~25 keys total on the allowlist after this cycle, the dispatch table itself becomes a high-traffic surface.
- The `OffPeakDrainNumber` dispatch goes through `energy.set_offpeak_drain(quality, value)` — a controller setter, not a scalar attr write. If `apply_in_place` poked an attr instead, the setter's side-effects (e.g. internal recompute, schedule update) would silently skip. Cross-coordinator side-effects are exactly the trust-hierarchy ripple the operator-elevation clause exists for.
- D3 retrofits a FACTORY (`_HVACTunableNumber`) that produces 14 entities in one stroke. The watch-list (`ac_nudge_duration`, `ac_nudge_eval_delay`, `ac_detection_time_gate`, `ac_hard_reset_min_interval`, `cover_override_duration`) flags candidates where a `timedelta` cache may shadow the raw attr; failing to invalidate the cache leaves the override-arrester running against the old duration with the new display value — a silent correctness regression in the AC nudge state machine.
- D2 drops `RestoreEntity` from a BASE CLASS (`_RoutineNumberBase`) with 4 subclasses, only one of which has a verified `async_update_entry` writeback today. The other three subclasses may need NEW writeback bodies — behavioral change to the routine-coordinator surface.

**Three-reviewer framing-disjoint protocol applies.** Run reviews in PARALLEL; framings must NOT overlap, per the Tier 2-DB rule that "different framings can't share blind spots."

**Review A — Correctness + entity-identity stability + dispatch coverage + cross-field clamps + dispatch-vs-direct-attr distinction.**
Focus: every retrofitted class drops RestoreEntity AND adds writeback; every CONF is in the allowlist AND has a dispatch branch (1:1 coverage); `unique_id` is unchanged for every entity (entity-identity bar — critical because RestoreEntity removal would otherwise reset the entity if unique_id changed); cross-field invariants are mirrored at BOTH entity and form paths (EC, egress); **OffPeakDrain dispatch uses the EC setter `energy.set_offpeak_drain(quality, value)`, NOT a direct attr write — explicit assertion**; D3 factory keys with non-scalar targets (controller setters) follow the same dispatch-via-setter pattern; D2 subclass writeback bodies are added where missing; the suite-level `test_apply_in_place_dispatch_coverage` test asserts EVERY allowlist key has a branch.

**Review B — Async + lifecycle + race conditions + watch-list `timedelta`-cache invalidation + factory-output safety + factory writeback behavioral change.**
Focus: D3 factory retrofit's behavioral writeback addition (the factory does NOT write back today — adding `async_update_entry` to its setter is a behavioral change worth its own scrutiny); `SIGNAL_HVAC_ENTITIES_UPDATE` dispatcher hookup at `number.py:1721-1735` is preserved (cross-coordinator init race coverage); the watch-list keys (`ac_nudge_duration`, `ac_nudge_eval_delay`, `ac_detection_time_gate`, `ac_hard_reset_min_interval`, `cover_override_duration`) — verify each `sub_controller.runtime_field` site for any `timedelta` or derived cache; if present, `apply_in_place` MUST invoke a recompute helper, not just `setattr`; defensive lookups in `apply_in_place` for missing or mid-teardown coordinators (HVAC, EC, Routine) — early-return mandatory; concurrent edits across entity+form paths do not corrupt the cached snapshot; D2 base-class drop does not strand a sibling Number that legitimately needs RestoreEntity (AST scan).

**Review C — New surfaces + restart/seed round-trip + test-fixture authority + per-zone (D4) handling + ComfortTempMin/Max deferral verification.**
Focus: per-zone factory (D4) handles a not-yet-existing per-zone CONF correctly — EITHER retrofits an existing one (build pass verified) OR is split out as its own cycle with a backlog memo; NO new CONFs are silently introduced in this cycle (institutional-context discipline); restart round-trip is end-to-end clean for each retrofitted Number (cold boot → seed from options → operator edit → listener applies in place → restart → reseed from options → entity reads edited value); test fixtures DRIVE the real factory bodies and real `apply_in_place` (no hand-copied dispatch logic in tests); D3 watch-list tests assert recompute is invoked where required; suite-level tests have 1:1 mapping with allowlist keys; **verify the ComfortTempMin/Max per-room follow-up memo is filed (D7) and the deferral list explicitly documents the data-loss hazard** so the follow-up cycle is not silently dropped.

Run the three reviews in PARALLEL. Fix every CRITICAL and HIGH finding before deploy. If fix-up substantially mutates the new surfaces (factory writeback contract, OffPeakDrain dispatch shape, watch-list recompute helper), run a focused fourth review on those surfaces.

**Live Validation (Review D)** per the Tier 2-DB protocol: post-restart, for at least ONE entity from each deliverable (D1, D2, D3, D5), prove end-to-end that (a) the edit landed in `entry.options`, (b) the live controller attr (or controller setter) received the value, (c) NO `async_reload` was scheduled on the CM entry (log scan), (d) sibling `last_changed` did not advance, (e) the value persists across restart. Sentinels-only validation (form persisted) is INSUFFICIENT — the reload-suppression proof and the controller-attr proof are both required.

---

## Plan completion tracking — explicit deferral list

| Item | Why deferred | Where tracked |
|---|---|---|
| **ComfortTempMinNumber / ComfortTempMaxNumber per-room persistence (SEPARATE FOLLOW-UP CYCLE — DO NOT DROP)** | **OUT of scope for Part 2.** These are per-room Numbers on ROOM config entries, which fire a DIFFERENT listener path than the CM entry that Part 2 targets — ROOM-entry reload behavior is intentionally untouched this cycle. They also live in a larger per-room config surface that the operator has explicitly bounded as "the most precious surface" (`feedback_parsimonious_room_config`); per-room retrofit deserves its own institutional-context pass against the ROOM-entry options/data shape. Critically: **ComfortTempMin/Max have ZERO persistence today** (no RestoreEntity, no async_update_entry — `number.py:177` and `:213` confirmed) — this is a real data-loss hazard (operator-set comfort bounds disappear on the next room reload), not a cosmetic gap. Must NOT be silently dropped; explicit follow-up cycle with its own planning doc covering the ROOM-entry listener surgery, the new CONF persistence shape, and migration from any prior in-memory defaults. | NEW dedicated follow-up cycle — file a planning doc + backlog memo at D7 (`docs/planning/PLANNING_per_room_comfort_temp_persistence.md` + memo titled "Per-room ComfortTempMin/Max persistence — data-loss hazard, separate from Part 2"). |
| Other per-room Numbers (`TimeoutOverrideNumber`, `ComfortHumidityMaxNumber`) | These also live on ROOM entries with the same separate-listener-path argument. Less acute than ComfortTempMin/Max because their default-only behavior is less semantically loaded, but still merits a Tier 2 retrofit cycle. Bundle with the ComfortTempMin/Max follow-up OR scope as its own cycle. | Open question O1; backlog memo filed at D7 if remains deferred. |
| `_HVACZoneKwhThresholdNumber` factory if no existing per-zone CONF | D4 may split out — depends on build-pass verification. | D4 itself, or new backlog memo if split. |
| Any factory-output that turns out to need a recompute trigger (watch-list) | Build-pass verification per D3. If found, recompute helper added in the same cycle. If a deeper refactor is needed, defer that one entity. | D3 watch-list. |
| QUALITY_CONTEXT.md updates | Post-review documentation step per CLAUDE.md. | Post-review. |
| Version assignment | Per operator convention. | Deploy step. |

**Items NOT deferred but explicitly considered and rejected:**
- Bundling Part 2 into the reload-suppression cycle. Operator framing: "We will do EC/HC after the HVAC reference ships." Part 2 builds on top, doesn't merge with.
- Introducing new CONFs for per-zone kWh thresholds in this cycle (D4). If that ends up necessary, D4 is split out — a new CONF family deserves its own institutional-context pass.
- Bundling ComfortTempMin/Max per-room persistence into Part 2. Three reasons: (1) different listener path (ROOM vs CM), (2) the per-room config surface is operator-bounded as parsimonious-critical, (3) it is a genuine data hazard that deserves a focused review pass, not a footnote in a ~20-entity retrofit.

---

## Open questions for operator (must be resolved before build)

- **O1.** ROOM-entry scope. The 4 per-room Numbers are out-of-scope by default this cycle. `ComfortTempMinNumber` and `ComfortTempMaxNumber` in particular have NO persistence today — operator decision is RESOLVED for this cycle: separate follow-up cycle (see deferral list). For `TimeoutOverrideNumber` and `ComfortHumidityMaxNumber`: bundle into the ComfortTempMin/Max follow-up or scope a third cycle? Recommendation: bundle.
- **O2.** D4 path. If build-pass verifies no per-zone kWh CONF exists today, split D4 out as a separate cycle introducing the new CONF family? Recommendation: split.
- **O3.** EC cross-field invariants. Build-pass verification will surface whether EC has any cross-field pair (e.g. `EXCESS_SOLAR_SOC` vs `FILL_PRIORITY_SOC`). If yes, mirror A-HIGH-1; confirm operator wants the same UX shape (entity setter clamps; form rejects).
- **O4.** Egress pause-vs-resume invariant. Same shape. Confirm.
- **O5.** Tier elevation. **RESOLVED** — operator elevated to Tier 2-DB. See "Tier classification" section above.
- **O6.** Dispatch implementation choice for D3 (option (a) duplicate per-key, option (b) entity-by-unique_id lookup). Recommend (a). Confirm.

---

## Pre-deploy zero-bugs gate (per `feedback_pre_deploy_zero_bugs_gate`)

Before running `./scripts/deploy.sh <assigned-version> <summary> <release-notes>`:
1. `git grep -nE '<<<<<<< |>>>>>>> '` — no merge conflict markers.
2. `python3 -m py_compile` on `__init__.py`, `number.py`, and any test files.
3. `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` — D1-D6 tests pass + baseline diff CLEAN against `pre-review-v<assigned>`.
4. Re-verify HA best-practice facts 1-3 from the sibling plan against pinned HA-core source.
5. Confirm the reload-suppression cycle (`PLANNING_cm_option_writeback_reload_suppression.md`) is LIVE in production AND validated (its post-deploy README validation table is filled in). If not, DO NOT deploy this cycle.
6. Verify HACS installed_version matches assigned version post-deploy; restart HA; run D1, D2, D3, D5 live acceptance criteria.

---

## Post-deploy README validation table

Per the URA "Record Live Validation Back Into the README" rule, `README_v<assigned>.md` MUST be updated after live validation with an observed-results table:
- One row per Live acceptance criterion in D1-D5.
- PASS / FAIL + concrete evidence per entity_id: `last_changed` not advancing on siblings (reload suppressed); live coordinator attr value matches edit; restart-persists check; cross-field clamp check (where applicable).
- Cite the authoritative signal actually used.

A cycle is not closed until its README carries the post-restart validation table.
