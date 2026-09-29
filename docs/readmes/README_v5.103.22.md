# v5.103.22: plain names for HVAC settings, exit and arrester countdown times, and pre-cool restore uses your Heat Low

**Cards:** `HVAC-PUBLISH-ZONE-AWAY-DUE-AND-ARRESTER-TIMERS-1`, `HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1`, plus label renames requested by the operator on 2026-09-28 (Tier 1).

**Branches:** `feature/hvac-labels-and-timer-attrs` (renames, new attributes, C26 correction) and `feature/hvac-precool-restore-heat-low` (heat setpoint fix).

## 1. Renames (labels only, no behaviour change)

Entity ids and unique_ids do not change. Only the names shown in HA change.

| Where | Old name | New name |
|---|---|---|
| Switch `switch.ura_hvac_coordinator_hvac_consensus_defer_gate` | HVAC Consensus Defer Gate | **Wait for Presence** |
| Switch `switch.ura_coordinator_manager_compliance_consensus_defer_gate` | Compliance Consensus Defer Gate | **Compliance Presence Wait** |
| HVAC settings form, `dynamic_preset_dwell_minutes` | Settle Time (minutes) | **Weather adjust delay (min)** |
| HVAC settings form, `dynamic_preset_hysteresis_f` | Temperature Margin (°F) | **Weather adjust margin (°F)** |
| Number `number.ura_energy_coordinator_dynamic_preset_dwell_minutes` | 03 · Settle Time (min) | **03 · Weather Adjust Delay** |
| Number `number.ura_energy_coordinator_dynamic_preset_hysteresis_f` | 04 · Preset Margin (°F) | **04 · Weather Adjust Margin** |

New helper text on the settings form:
- **Weather adjust delay:** "How long a cooler- or hotter-than-usual forecast must last before the cooling range shifts. 15-240 min. Default 60."
- **Weather adjust margin:** "How far past the usual the forecast must be before it counts as a cooler or hotter day. 0.5-5 °F. Default 2."

The HVAC switch keeps a plain name with no number prefix, because it is not one of the numbered HVAC Coordinator entities. The two Numbers keep their `03 ·` / `04 ·` prefixes.

`strings.json` and `translations/en.json` were updated identically. Stale entity ids in the code comments for both switches were also corrected.

## 2. New display attributes (display only; no decision reads them)

**Zone exit time.** New attribute `away_due_at` on `sensor.ura_hvac_coordinator_zone_{n}_status`:
- It is when the zone is due to switch to Away: the zone's release time (from `zone_away_due_at`, `hvac_zones.py`) plus the vacancy grace HVAC uses right now (knob 48, or knob 49 under coast/shed).
- ISO local time. It matches the exit timer's due time minus the timer's 2 s slack.
- It is **None** while the zone is HVAC-occupied (including a room still in its hold time), once the due time has passed, or when the release time is unknown.

**Arrester end times.** New per-zone attributes on the arrester sensor (`get_arrester_detail()["zones"][<zone name>]`):
- `grace_until`: when the current grace period ends (normal or severe override, or the startup audit). ISO local, or None.
- `compromise_until`: when the current compromise ends and the zone is put back. ISO local, or None.
- The times are recorded when a timer starts. They are shown only while that timer is still running, so a cancel, a fire, disabling the arrester, or handing the zone to a borrow all clear them.
- Known limit: after a restart, `compromise_until` reads None even while a restored COMPROMISE borrow is still live, because the arrester has no timer for it then. The borrow is closed by the lease-expiry sweep.

## 3. Pre-cool (banking) restore uses your Heat Low (`HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1`)

**Problem.** When a solar pre-cool (banking) borrow returns a zone and URA has no remembered range for that zone (e.g. no preset cycle since boot), it rebuilds the range from the preset. The low side was computed as `cool − 7 °F` and ignored the configured Heat Low. On a winter Away profile of 80/65, an empty zone would be restored with heat at 73 °F instead of 65 °F.

**Fix.** `hvac_predict.py` `_resolve_baseline_range` now uses the configured heat setpoint from `PresetManager.get_seasonal_setpoints` (per-preset values from the options, with the seasonal defaults as fallback, so a Heat Low always exists). On this Carrier, `target_temp_low` is the heat setpoint.

**Effect today (summer):** sleep low goes 69 → 70 and away low 75 → 60. Both are harmless while cooling. The arrester already compares against the configured heat, so this also removes a false +15 °F override delta after a summer-away raw release.

**Not changed:** the same `cool − 7` shape remains at the Dynamic Preset apply site (`hvac.py` ~3541), the display (`sensor.py`) and `dynamic_preset.py`. These only matter once Custom Preset Ranges (D9) is on, which is off today. That plan deletes the `hvac.py` site.

Review: `docs/reviews/code-review/hvac_precool_restore_heat_low.md` (SHIP, 2 LOW, 1 fixed, 1 covered by the Custom Preset Ranges plan).

## 4. C26: the excursion "manual skip" stays

The W1-B plan said to delete the `hvac_excursion.py` HIGH-1 skip once live validation passed. The skip is in `_auto_return`: when the saved preset is `manual`, empty or None, it writes no preset. That deletion was refuted, so the skip was **not** deleted:
- COMPROMISE borrows start while the zone is held in `manual`.
- After a restart the borrow row is restored but the arrester's compromise timer is gone.
- The lease-expiry sweep then returns the borrow through this skip.
- Without the skip, URA would write preset `manual` (or None) to the thermostat.

"Parked D3" has no code, only log text. Only the docstring changed: S1 now reclaims `manual` zones. Recorded as C26 in `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §10.

**Related finding (check only, no change):** a NUDGE can also start while a zone reads `manual`. `check_ac_reset` does not check the preset, only `_override_active`, which is set only for ≥1 °F arrested overrides. `begin_excursion` records the raw preset. So the boot audit's NUDGE preset restore (`hvac_excursion.py` ~1144, `if pre_preset and ...`) can write `manual` back after a restart mid-nudge. See the final report of this branch.

## Tests

- New `quality/tests/test_hvac_publish_zone_away_due_and_arrester_timers.py` (9 tests). It drives the real `HVACZoneStatusSensor.extra_state_attributes`, `HVACCoordinator`, `ZoneManager` and `OverrideArrester` paths:
  - `away_due_at` is set on an empty zone past its release.
  - It follows the energy-constrained grace.
  - It is None while occupied, None during a room's hold time, and None once the due time has passed.
  - `grace_until` is set by the normal and severe overrides and by the startup audit, and cleared on cancel and on disable.
  - `compromise_until` is set when a compromise applies and cleared on revert.
- Mutation drill: each new assignment or check was disabled in turn with `PYTHONDONTWRITEBYTECODE=1` and `__pycache__` cleared. Each turned a named test red, and `git status` was clean after restore.
- Heat-low fix: new tests in `quality/tests/test_v5_7_1_energy_precool.py`. Reverting to `cool − 7` turned 2 of 3 red. That branch also fixes the file's stub loader, which made 27 tests error when the file was run alone.
- `--isolate` name-diff against develop over every test file importing `hvac_override` / `hvac_zones` / `hvac_excursion` / `switch` / `number` / strings / translations: 0 NEW, 0 GONE.

## Live validation (prospective)

- **L1 names:** the HVAC Coordinator device shows "Wait for Presence", "03 · Weather Adjust Delay" and "04 · Weather Adjust Margin". The Coordinator Manager device shows "Compliance Presence Wait". The HVAC settings form shows "Weather adjust delay (min)" and "Weather adjust margin (°F)" with the new helper text. The entity ids are unchanged.
- **L2 away_due_at:** on a zone whose rooms are HVAC-empty with the exit still ahead, `sensor.ura_hvac_coordinator_zone_{n}_status` has `away_due_at` = `hvac_release_at` + vacancy grace (5 min live). On an occupied zone it is `null`. After the zone writes Away it returns to `null`.
- **L3 grace_until:** during the next arrester grace (the "25 · Override Arrester State" sensor, unique_id `universal_room_automation_hvac_arrester_state`, reads `grace_period`), that zone's entry in the `zones` attribute has `grace_until` about the grace length after the override. It returns to `null` when the grace fires or is cancelled.
- **L4 heat low:** the next banking restore that takes the preset fallback writes `target_temp_low` = the configured Heat Low for the preset, not cool − 7. Look for a `hvac_excursion_events` row or a `climate_write` row with site `S11…`. This only applies when the zone has no remembered range. A named-preset release writes no setpoints, so for this check look for a raw (human-manual) release.
- **Discriminator:** a `grace_until` still showing after the arrester state returns to `idle`, or an `away_due_at` earlier than the current time, would mean the fix is not working.

## Rollback

Revert the merge commits. There is no schema, options or entity-id change.

## Validated 2026-09-28 23:42 CDT (HACS v5.103.22, HA restarted 23:36)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Renamed friendly names show; entity ids unchanged | **PASS** | `switch.ura_hvac_coordinator_hvac_consensus_defer_gate` = "URA: HVAC Coordinator Wait for Presence"; `switch.ura_coordinator_manager_compliance_consensus_defer_gate` = "... Compliance Presence Wait"; `number.ura_energy_coordinator_dynamic_preset_dwell_minutes` = "03 · Weather Adjust Delay"; `..._hysteresis` = "04 · Weather Adjust Margin" |
| L2a | `away_due_at` None while the zone is HVAC-occupied | **PASS** | zone_1 (sleep, occupied) and zone_2 (occupied) both `away_due_at: null` |
| L2b | `away_due_at` set on an empty zone with a bounded release | **PENDING** | only zone_3 was empty (since 23:25), in house sleep/night, where the release is unbounded by design, so `hvac_release_at` and `away_due_at` are null. Check on the first daytime empty-zone release |
| L3 | `grace_until` during an arrester grace | **PENDING** | no arrester grace armed since the restart |
| L4 | Banking/pre-heat restore writes the configured Heat Low | **PENDING (rare path)** | only fires on a raw (human-manual) banking release via the preset fallback |

Boot observation (not caused by this release; evidence for Batch B `PLANNING_hvac_w1_w2_finish.md`): at 23:03:51 a human set zone_2 76→71 during a live pre-arrival banking borrow (`override_detected` gated `borrow_active`). At the 23:40 restart, the boot audit's stale-boot release restored the borrow's snapshot preset `away`, erasing the human's 71. S1 then set `home` at 23:41:21 (house `home_night`). Batch B's "person interrupts ends the borrow" would have closed the row at 23:03, so the restart would have had nothing to restore.
