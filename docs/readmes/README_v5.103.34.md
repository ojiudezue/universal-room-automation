# URA v5.103.34 — Batch: humidity junk floor, attribute churn, anomaly baselines, music following, excursion ids, solar override

Five reviewed fixes from the overnight 10-01/10-02 queue, merged together. Each was reviewed separately (two framing-disjoint reviews each, mutation drills red-then-restored); this release adds one serial full-suite name-diff of the merged result against `pre-batch-1002`.

**Behaviour change to expect:** music following starts working again (silently off since May). Turn `switch.ura_music_following_coordinator_enabled` off if unwanted — that switch now really stops transfers.

## URA-ATTRIBUTE-CHURN-1 — stop re-publishing entities when only a ticking attribute changed

### Problem
Measured 2026-09-28: `binary_sensor.living_room_occupied` and `living_room_hvac_occupied` each wrote ~24 rows/min with state steady `on` (only `last_motion` changed); `sensor.ura_safety_coordinator_safety_active_cooldowns` did the same via `age_seconds` / `max_remaining_seconds`. Each write is a state_changed event plus a new attributes row.

### Fix
Occupancy attributes are now stable in every phase (sensor-active / countdown / held / vacant; producer `coordinator.py` ~3697-3757); HVAC `release_at` is stable; safety cooldowns expose fixed per-alert values instead of ticking ages. HA core drops identical writes (`core.py:2313-2350` fire only `state_reported`). No reader of the dropped/renamed keys found in URA, the PWA (Safety.tsx reads the state only), docs, automations or lovelace.

### Evidence
4 mutation drills red then restored; reviews A (correctness+consumers) SHIP, B (lifecycle/recorder) SHIP. LOWs not fixed: test helper sets phase by hand; no `release_at` test.

### Live acceptance (after deploy)
- Over 5 minutes with Living Room steadily occupied, `binary_sensor.living_room_occupied` writes far fewer than 119 recorder rows (discriminates: old code ~24/min with no state change).

## SAFETY-HUMIDITY-JUNK-READING-1 — junk 0% humidity no longer raises a safety alert

### SAFETY-HUMIDITY-JUNK-READING-1

### Problem
Some humidity sensors send a bogus reading of 0% (or 3%) for about one second while they reconnect. The safety coordinator raised a MEDIUM "Low humidity" hazard on it immediately. Three of the four low-humidity alerts since 09-12 were these junk readings (Study A 0.0% twice, Dining Room 3.0%). Humidity hazards never self-clear (carded separately: SAFETY-HAZARD-NEVER-CLEARS-1), so the 09-26 23:35 CDT blip kept `binary_sensor.ura_safety_coordinator_safety_alert` **on** and the safety status at `warning` for hours while the sensor read 46-49%.

### Fix (`domain_coordinators/safety.py`, `aggregation.py`)
- New rung-1 constant `HUMIDITY_PLAUSIBLE_MIN_PCT = 5.0` (review to change; 0 disables). Readings strictly below it are treated as absent at every humidity read site:
  - `_handle_humidity`: returns before any low-humidity / sustain / swing state, so a blip neither fires nor resets the 2-4 h high-humidity window.
  - `_process_sensor`: returns before the rate-of-change detector records the value (no poisoned rate history or persisted rate baseline).
  - `evaluate_zone_chip`: treated as None (no chip trip, no comfort-drift).
  - Whole-house `SafetyAlertBinarySensor._get_alerts`: treated as None (it had its own hard-coded `< 25` check).
- Debug log at the early returns.

### Review ledger
Build `bf134b4ec` → review A (correctness/edges/consumers) SHIP + M1 (missed house-level site) + L2 (boundary tests); review B (state/lifecycle/ripple) SHIP; four out-of-scope findings carded (SAFETY-HAZARD-NEVER-CLEARS-1, SAFETY-RATE-DETECTOR-DEAD-WINDOW-1, SAFETY-RECONNECT-ZERO-SIBLINGS-1; the observability LOW folded in). Fix-up `716ae5ce4`. 18 tests in `quality/tests/test_safety_humidity_junk_floor.py`; every guard site mutation-drilled red (builder: 6 drills; orchestrator independently re-drilled the `_handle_humidity` guard: 4 named tests red, restored green).

### Live Validation (prospective)
- **Verify (discriminating):** the deploy restart clears the current stale Study A hazard, but ANY restart would, so that is not the proof. The proof comes later: the next time `sensor.invisoutlet_b7d0_humidity` (or any humidity sensor) logs a sub-5 value in the recorder, NO new "Low humidity" row appears in `notification_log` and `sensor.ura_safety_coordinator_safety_active_hazards` does not count it. Under the old code the same recorder event produces a MEDIUM alert.
- **In-suite only:** real lows (5-25%) still fire; no real indoor RH that low is expected live.

## ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1 — anomaly baselines saved hourly and on stop

### What was wrong

Anomaly baselines for the `presence`, `security`, `safety`, `safety_rate`,
and `music_following` detectors are persisted ONLY from each coordinator's
`async_teardown()` and, for the CM setup detector, from
`CoordinatorManager.async_stop()`. Neither path runs on an HA restart —
HA fires `EVENT_HOMEASSISTANT_STOP` and exits without unloading the
config entry, so the only teardowns that ever execute are explicit
unloads (reload / disable). Learning accumulated between unloads is
discarded every restart.

Live DB confirmed the drift on 2026-10-01:

| coordinator_id    | last_updated |
|-------------------|--------------|
| presence          | 2026-09-14   |
| security          | 2026-09-04   |
| safety            | 2026-09-04   |
| safety_rate       | 2026-09-11   |
| music_following   | 2026-05-12   |
| energy / hvac / memory | current (per-rollover / per-cycle writers) |
| coordinator_manager    | current (saves each boot) |

### What changed (code)

`custom_components/universal_room_automation/domain_coordinators/manager.py`:

1. New module constant
   `ANOMALY_BASELINE_SAVE_INTERVAL_S = 3600` (named knob, numbers-get-knobs).
2. `CoordinatorManager._wire_anomaly_baseline_persistence()` wires two
   handles after `async_start` completes:
   - `async_track_time_interval(..., timedelta(seconds=ANOMALY_BASELINE_SAVE_INTERVAL_S))`
     — periodic save every hour.
   - `hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop)`
     — reuses the exact pattern from the house-state stop-hook at
     `manager.py` (previously `:617-633`) so there is one stop-listener style.
3. `_persist_coordinator_baselines()` iterates every coordinator with an
   `anomaly_detector`, awaits its `save_baselines()`, then invokes
   `safety._save_rate_baselines()` (safety_rate scope) and the CM setup
   detector. Each failure is isolated so one broken writer cannot block
   the others.
4. `async_stop()` cleans up both unsubs (listener hygiene).

Verified against HA source (`.venv-ha/lib/python3.13/site-packages/homeassistant/core.py:1112`):
`EVENT_HOMEASSISTANT_STOP` is fired inside `async_stop()` on both
graceful stop and restart, so this listener is reached on every restart.

### Write-volume

- Periodic timer: 1 call per `ANOMALY_BASELINE_SAVE_INTERVAL_S` = 24 calls/day.
- 5 detectors * 24 = 120 `save_baselines()` calls/day, plus 1 safety-rate
  save and 1 setup-detector save per period (total ≈ **168 helper calls/day**).
- Each `save_baselines()` issues an `INSERT OR REPLACE` per
  `(metric, scope)` tuple in that detector's baselines map — a handful
  of rows per call, bounded by the detectors' metric cardinality.
- **No per-decision-cycle amplification.** Behavioural test
  `TestWriteVolumeBounded.test_each_invocation_saves_once_per_detector`
  pins the one-save-per-invocation invariant; the interval constant is
  guarded `>= 1800s`.

### Listener cleanup

`async_stop()` calls both `_anomaly_baseline_periodic_unsub()` and
`_anomaly_baseline_stop_unsub()` and sets both back to `None`.
`TestListenerHygiene.test_async_stop_clears_both_unsubs` is the oracle.

### Falsifiable acceptance (live)

> After one restart and one `ANOMALY_BASELINE_SAVE_INTERVAL_S` period
> (~1h), `metric_baselines.last_updated` for `presence`, `security`,
> `safety`, `music_following` is within the current period.
> On restart (regardless of elapsed time since boot),
> `last_updated` for all four should refresh within seconds of
> `EVENT_HOMEASSISTANT_STOP` being fired at the subsequent restart.

Live check SQL (ura-sqlite or ssh ha):

```sql
SELECT coordinator_id,
       MAX(last_updated) AS last_saved,
       CAST((julianday('now') - julianday(MAX(last_updated))) * 24 AS INT)
         AS hours_ago
  FROM metric_baselines
 WHERE coordinator_id IN ('presence','security','safety',
                          'safety_rate','music_following',
                          'coordinator_manager')
 GROUP BY coordinator_id
 ORDER BY last_saved DESC;
```

Expected after one hour of uptime post-deploy: `hours_ago <= 1` for all
five. Expected on the restart immediately after that: all five refresh
within ~5 seconds of the restart event (stop-flush path).

Discriminator vs failure: if `safety_rate.hours_ago` stays high while
the others refresh, the rate-detector has no samples (data gap), NOT a
save-path regression — the safety 30-min periodic save on
`safety.py:1214` was already live; this cycle re-covers it from the CM
loop for symmetry.

### Tests (behavioural)

`quality/tests/test_anomaly_baseline_periodic_save.py`:

- (a) stop event — `TestStopEventPersistsAllDetectors`
- (b) periodic path — `TestPeriodicTimerPersists`
- (c) simulated-restart sample round-trip — `TestRestartRoundTripSampleCount`
- (d) write-volume bound — `TestWriteVolumeBounded`
- lifecycle — `TestListenerHygiene`
- wire-in anchor drill — `TestWireInAnchor.test_neutering_the_call_site_breaks_the_oracle`
  (production source of `_persist_coordinator_baselines` is extracted
  via `inspect.getsource`, the `await detector.save_baselines()` line
  is removed in a monkeypatched copy, and the stop-callback oracle
  goes red — proving the oracle is bound to the real call site.)

All 59 tests pass in isolation and in combination with
`test_domain_coordinators`, `test_restart_safety_doctrine_1`,
`test_metric_baseline_integration`, `test_coordinator_diagnostics`
(the only remaining failures in that combined set are two pre-existing
failures unrelated to this change).

## MUSIC-FOLLOWING-NO-TRANSFERS-SINCE-MAY-1 — music following works again; its switch now really stops it

### What changed
- Music Following had made no transfers since May: the "is this person enabled?" check compared a display name ("Oji Udezue") against an entity id ("person.oji_udezue"), so it never matched. The check now compares a canonical key for both forms (`_person_key`, `music_following.py`).
- The Music Following coordinator on/off switch now really stops transfers (it used to gate only the wrapper while the engine kept running). Fail-safe: if the coordinator settings can't be read, transfers are off.
- Enabled-person storage and the boot-time auto-enable dedupe by the same canonical key, so one person can no longer appear twice and an "off" preference stored under the entity id blocks a display-name auto-enable.

### Behaviour change to expect
- **Music will start following people again** for everyone enabled (it has been silently off for ~5 months). If that is not wanted, turn the Music Following coordinator switch off before deploying.

### Evidence
- Tests: `-k music` 171 passed; drills RED then restored on the kill-switch gate and the canonical dedupe.
- Reviews: A + B on the core fix SHIP (with HIGH + 2 MEDIUM fixed in the fix-up); fix-up review A SHIP (switch key/default match `switch.py:258-266`, `:695-697`).

### Known residuals (recorded on the card, not in this cycle)
- BLE bleed: one person at 0.65-0.75 confidence can pull music into a room they did not enter.
- Anomaly baseline distortion from re-recording cumulative daily rates on every skip.
- CONF_MF_COOLDOWN_SECONDS / VERIFY_DELAY / UNJOIN_DELAY are read but unused.

### Live acceptance (after deploy)
- With an enabled person moving between two rooms that have players, `music_following` logs a transfer and the target player starts within the verify delay. Discriminates: before the fix no transfer row appears at all.

## HVAC-CLIMATE-WRITE-EXCURSION-ID-GAPS-1 — auto hand-backs record their borrow id

### What changed
- When a borrowed thermostat preset is handed back automatically (`_auto_return`, `hvac_excursion.py` ~717) or restored by the startup audit (~1187), the climate-write ledger row now carries the excursion's id. Before, every `auto_return:*` row had `excursion_id` NULL (live 9/9), so those writes could not be tied back to the borrow that caused them.
- Ledger-only change: no thermostat behaviour changes. No production code reads `climate_write.excursion_id` today.

### Known residual (not fixed, recorded on the card)
- The boot ramp-audit nudge restore (`hvac_override.py` ~7739/7762) still writes NULL: the nudge registry has no id column, so fixing it needs a schema addition.

### Evidence
- Wire-in test `test_auto_return_forwards_excursion_id_to_emit_set_preset_mode` (test_hvac_excursion_d1_auto_release.py); call-neuter drill RED then restored (10-01).
- Full-suite name-diff vs develop 2b6f94bdc: identical failing-name sets (152 failed / 3 errors pre-existing), +1 passing.
- Reviews: A (local correctness) SHIP, B (consumers/completeness) SHIP.

### Live acceptance (after deploy)
- `SELECT reason, excursion_id FROM climate_write WHERE reason LIKE 'auto_return:%' AND ts > '<deploy time>';` — every row has a non-NULL `excursion_id`. Discriminates: under the old code the same query returns NULLs.

## EC-SOLAR-OVERRIDE — optional solar power sensor for the energy coordinator

Plan: `docs/planning/PLANNING_ec_solar_entity_override.md` (Tier 2, PATCH).

### Problem

The Envoy's own production total broke at 23:05 on Oct 1. `/api/v1/production` reports
`wattsNow` 0 and the lifetime counter reset to 45,505 Wh. A reboot did not fix it.
`sensor.envoy_482543015950_current_power_production` is stuck at 0.0, while
`sensor.envoy_482543015950_production_ct_power` (also kW) still shows real solar.
The Energy Coordinator gets its solar input from the Envoy serial (`derive_envoy_config`).
At setup, an explicit `energy_solar_entity` already wins through the `setdefault` merge
(`__init__.py`), but no options-flow field set that key. The operator therefore had no
way to point EC at the healthy sensor.

### Fix

- **Energy Coordinator options:** new optional field **"Solar power sensor (override)"**
  (`energy_solar_entity`), placed right after the Envoy picker. Helper text: *"Leave blank
  to use the Envoy's solar reading. Pick a sensor here only if that reading is wrong."*
  Labels are in `strings.json` and `translations/en.json`.
- **Clearable:** the field uses `suggested_value`. When the field is omitted or saved as
  `""`, the key is removed from the saved options. Without this, the
  `{**options, **user_input}` merge would bring back the old value. `""` is never saved: at
  runtime `setdefault` would keep it and solar would silently read as nothing. The removal
  runs before the Envoy validation merge, so validation sees the cleared state.
- **No other production change.** Precedence (explicit beats derived) already exists at
  setup, in `validate_envoy_config`, and in repairs. A bad pick is rejected inline on the
  field with `derived_entity_missing`.
- Saving this field reloads the CM entry, which rebuilds the entity map. The key is
  deliberately **not** in `OPTIONS_RELOAD_SUPPRESS_KEYS`. Save it while the house is awake.

### Tests (`quality/tests/test_ec_solar_entity_override.py`)

| Test | Proves |
|---|---|
| `test_ec_solar_override_reaches_battery_strategy` | Real `__init__.py` merge + real `_build_entity_map` (both source-extracted) → real `BatteryStrategy`: derived=0.0 kW, CT=4.2 kW → `solar_production`=4.2, `solar_production_w`=4200 |
| `test_ec_solar_override_blank_uses_derived` | Override absent → derived entity, `energy_entity_config` dict-equal to options + `derive_envoy_config` (unchanged default); reads 0.0 |
| `test_ec_solar_override_validation_resolves_override` | `validate_envoy_config(...)["resolved"]["energy_solar_entity"]` == override |
| `test_ec_solar_override_options_roundtrip_set_and_clear` | Real options step: set → present; field omitted → absent (old value not kept); `""` → absent |
| `test_ec_solar_override_schema_exposes_field` | Form schema contains `energy_solar_entity` |
| `test_ec_solar_override_invalid_entity_rejected` | Envoy + non-existent override → form error `derived_entity_missing` on `energy_solar_entity` |
| `test_ec_solar_override_valid_with_envoy_passes_validation` | (plan-review extra) Envoy + valid override → save passes; validator resolved key = override |

### Mutation drills (source edited, suite run, restored by Python rewrite, `__pycache__` cleared, `PYTHONDONTWRITEBYTECODE=1`)

| Drill | Site | Result |
|---|---|---|
| `setdefault(k, v)` → `energy_entity_config[k] = v` | `__init__.py` Envoy derive merge | `test_ec_solar_override_reaches_battery_strategy` FAILED (1 failed, 6 passed); restored |
| Removal `saved_options.pop(CONF_ENERGY_SOLAR_ENTITY, None)` → `pass` | `config_flow.py` energy step | `test_ec_solar_override_options_roundtrip_set_and_clear` FAILED (1 failed, 6 passed); restored |

Targeted regression: the new file plus baec / solar-follow / arbitrage-guard / energy-ladder /
cycle-b config-flow / shared-power-staleness gave 150 passed.
`test_envoy_auto_derive.py` and `test_envoy_boot_decoupling.py` fail at collection with the
same error on develop with this change absent: dataclass `sys.modules.get(cls.__module__)` is
None under the py3.13 venv. This is an existing problem in the test harness, not part of this
change.

### Live acceptance (D3) — to fill after deploy (`Validated <date>` table)

- After setting the override (house awake), the log shows `CM options changed ... falling
  through to reload (changed_keys=['energy_solar_entity'])`. There is no watchdog trip or
  stall, and the CM comes back within its normal setup time.
- The `solar_production` attribute on `sensor.ura_energy_coordinator_battery_strategy`
  matches live `sensor.envoy_482543015950_production_ct_power` (allowing for rounding) while
  that sensor is above 0 in daylight. It is **not** 0.0. A 0.0 reading means the override had
  no effect.
- The `solar_age_s` attribute on the Envoy freshness sensor stays small (seconds) and does not
  climb.
- An EC DB snapshot row written after the reload has a non-zero `solar_production` in daylight.
- No new `envoy` repair issue appears.

### Not done / follow-ups

- PWA "Solar now" card (`dashboard-v3/.../Energy.tsx`) still reads the derived entity by name.
  It is display-only and needs a card (PWA-SOLAR-NOW-ENTITY-1).
- Lifetime-production reset affects `energy_lifetime_production_entity` and daily
  `solar_produced_kwh`. Needs a card (EC-LIFETIME-PRODUCTION-RESET-1).
- Overrides for all 13 derived Envoy entities, and hot-apply without a CM reload: parked
  according to the plan.
- EC manual config-surface row: not edited in this build. Add it with the release README.

**Fail-closed note (review B MEDIUM):** if the override sensor is later deleted or renamed, the energy coordinator will not start and a repair is raised — clear or re-pick the override to recover.

## Test-only: lighting untested sites
`quality/tests/test_lighting_untested_sites.py` adds behavioural tests + red drills for review-C sites R4/E8/E9/E10 (no production change).

## Suite
Serial full-suite name-diff vs `pre-batch-1002`: 151 failed / 3 errors identical name sets on both sides, +110 passing — CLEAN.

## Live validation
### Validated 2026-10-03 (restart 00:37 CDT onto v5.103.36; checked ~01:15)

| Criterion | Status | Evidence |
|---|---|---|
| Attribute churn: <119 rows/5 min while Living Room occupied | pending organic | Room off since restart. Dispose: count `binary_sensor.living_room_occupied` rows over a 5-min occupied window; PASS if <119. |
| `safety_active_cooldowns` not ticking | PASS (partial) | 1 row since restart. |
| Junk humidity floor | pending organic | No sub-5% reading yet. Dispose: no `low_humidity` row in `ura_activity_log` after the next blip. |
| Anomaly baselines saved hourly/on stop | pending (uptime <1h at check) | coordinator_manager fresh; others pre-fix ages. Dispose: re-check after 1h uptime — all 5 refresh. |
| Music following works again | PASS (mechanism) | 01:14 evaluation for "Oji Udezue" Master Bathroom→AV Closet = `sleep_suppressed` (name match now works); 23 low_confidence / 14 ping_pong in 37 min. Completed transfer pending (waking hours). |
| Auto-return writes carry excursion_id | pending organic | No auto_return since restart. Ledger is `ura_activity_log` (action='climate_write'), not a `climate_write` table. |
| Solar override | pending operator/daylight | Override not set; Envoy production path itself faulty (production.json hangs). |

No new URA errors since restart; boot-only noise: fan-oracle fallback burst (fixed on develop), Envoy setup hang (Envoy firmware fault), Leviton 12 s stall.
