# v5.103.86 — Release batch: OC write dedup, restart-pending repair, coverage uses total consumption

Three independently reviewed fixes. Full suite on the merged batch (`integ/batch-1023` 2f6c21300): 0 new failures vs the develop baseline (`docs/planning/suite_baseline_develop_2026_10_23.txt`); 11 known failures unchanged (census switches, humidity fan behavioral; being fixed on the test-harness slice), passed +39. Deploy risk: LOW (fewer DB writes, a read-only repair check, a display/audit input swap).

## 1. Optimization Coordinator stops re-writing unchanged rows
Card: OC-REEMIT-DEDUP (Tier 2, reviews A correctness + B lifecycle, both FIX-REQUIRED → fixed and drilled).

### Problem
The Optimization Coordinator wrote the same rows to the database over and over. The never-fires dedup stamp lived only in memory, so every restart re-wrote every never-fires finding. The `cycle_ok` heartbeat and the next-room `prediction_accuracy` finding were written every 5-minute cycle even when nothing changed.

### Change
- The never-fires `last_persisted` stamp is saved in the existing never-fires Store, so it survives a restart.
- `_filter_unchanged_repeats` + `OPTIMIZER_PERSIST_ON_CHANGE_DIMENSIONS` (const.py; empty tuple = off): `cycle_ok` and `prediction_accuracy` rows are written when the description changes, on the first cycle of each boot, and at least once per `OPTIMIZER_SENSOR_HEALTH_REPERSIST_INTERVAL_S` (24 h, reused) so the 7-day prune never removes the last copy (review A1/B2).
- A cached entry is dropped when its finding is absent from a cycle, so a cleared-then-recurring finding is written again (A2).
- Stamps are committed only after `log_findings_batch` returns a non-zero count; tripwire drops, a missing DB, an exception or a silent 0 leave no stamp (A3/B1).
- Notifications, the scoreboard and the in-memory findings still see every cycle; only DB rows change. Writes only go down.

### Tests
`test_ocr_*` in `test_optimization_coordinator.py` (12), 8 per-site mutation drills all RED. Review docs `docs/reviews/code-review/oc_reemit_dedup_review_A.md` / `_B.md`.

### Live acceptance (prospective)
- **Live:** `optimization_findings` `cycle_ok` rows: one after restart, then none until the description changes or 24 h passes (was 1 per 5 min).
- **Live:** `prediction_accuracy` rows only when the text changes; no write-tripwire warnings.
- **Discriminator:** broken filter → `cycle_ok` keeps landing every 5 min; broken stamp-after-write → a boot with no `cycle_ok` row at all.

## 2. Restart-pending repair when loaded ≠ installed
Card: EC-LOADED-VS-INSTALLED-VERSION-1 (Tier 1).

### Problem
After a deploy installs new files (HACS / deploy.sh) but before HA restarts, the running URA is older than the installed one, and nothing showed it. On 2026-10-19 the device registry reported sw_version v5.103.72 (loaded) while manifest.json on disk said 5.103.74. Live checks in that window read old code without any warning.

### Change
- New `version_check.py`. Loaded = `const.VERSION`, installed = `manifest.json` `version` read in the executor. A leading `v` is stripped before comparing.
- Runs once at integration-entry setup and then every `VERSION_CHECK_INTERVAL_S` (const.py, 3600 s, rung 1). The timer is released when the entry unloads.
- When the versions differ, one Repairs issue `restart_pending_version_mismatch` is raised (WARNING, not fixable, placeholders loaded/installed). It is deleted when they match again. If the manifest is missing or unreadable, installed = None and nothing changes.
- `sensor.ura_coordinator_manager` gains the attributes `loaded_version`, `installed_version` and `restart_pending`.
- Deploys deliberately separate install from restart (no restart while the house sleeps), so this state is normal. The issue is informational only.

### Tests
`quality/tests/test_loaded_vs_installed_version.py`. Mutation drills went RED for the comparison, issue create, issue delete, the setup wire-in call, the timer arm, and the sensor attrs.

### Live acceptance (one-shot, discriminating)
- **Live:** right after this deploy is installed but not yet restarted, the running code is the OLD build, which lacks this check, so it cannot report on itself. Validate on the NEXT deploy: once it is installed and before the restart, Repairs shows "Restart pending to load URA Y" with loaded=X installed=Y, and `sensor.ura_coordinator_manager` shows `restart_pending: true`.
- **Live:** after the restart the issue is gone and `loaded_version == installed_version`, `restart_pending: false`.
- Discrimination: if the check were broken, the issue would be absent while installed != loaded (a false negative), or present after the restart (a false positive). Each of those observations differs from the correct-behaviour one.

## 3. Energy coverage audit reads total house consumption
Card: COVERAGE-EVENING-ATTRIBUTION-DRIFT-1 (Tier 1-2, display/audit only).

### Problem
`sensor.universal_room_automation_energy_coverage_delta` computes
unattributed = whole house - sum(rooms, zones, house devices). Its whole-house
input came from `whole_house_energy_sensors`, which is live-configured to
`sensor.envoy_482543015950_lifetime_net_energy_consumption`. That is Envoy NET
consumption: grid import, net of the solar the house used itself. Coverage needs
TOTAL consumption. On sunny afternoons the net figure flattens while rooms keep
accumulating, so the parts exceed the whole and `delta_percent` walks steadily
negative from about 14:00 to midnight. The 2026-09-23 measurement confirmed it:
total minus net = production minus export, to five decimal places.

### Change
- The coverage sensor now prefers the Energy Coordinator's existing total entity
  (`CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY`, an explicit setting or the
  serial-derived default `sensor.envoy_<serial>_lifetime_energy_consumption`),
  already resolved on `EnergyCoordinator._entity_lifetime_consumption`. New helper:
  `EnergyCoverageDeltaSensor._resolve_whole_house_sources` (aggregation.py).
- Fallback: if there is no EC, no total entity, or the entity is not in the state
  machine, the sensor uses `whole_house_energy_sensors` as before. A total entity
  that exists but is unavailable stays selected and shows "No data". It is not
  swapped to NET mid-day.
- New attribute `whole_house_source`: `ec_total` | `whole_house_energy_sensors`.
- Unchanged: the shared field, `WholeHouseEnergySensor`, `WholeHouseCostTodaySensor`
  (still NET), unit normalization, no-data handling, and the 120-min midnight
  re-anchor window.
- Anchor at the switch: baselines are keyed per sensor id and held in memory. The
  first read after the upgrade anchors the total counter fresh, which matches
  normal post-restart behaviour (`post_restart_window` already covers the gap).
- Comment-only: energy.py comments that said lifetime_energy_consumption = net
  import now say it is TOTAL on this Envoy.

No new config field and no new knob.

### Tests
`quality/tests/test_coverage_whole_house_total_source.py` (6 tests) drives the
real sensor with separate NET (+3 kWh) and TOTAL (+10 kWh) counters: EC total is
used (delta 6, not -1); fallback when EC is absent, has no entity, or the entity
is missing; unavailable total stays on `ec_total`; the cost sensor still reads NET.
Mutation drills: neutering the EC branch, reverting the call site, or dropping the
states guard each turns specific tests RED.

### Live acceptance (prospective)
- `sensor.universal_room_automation_energy_coverage_delta` attribute
  `whole_house_source` = `ec_total`.
- On a sunny afternoon, `delta_percent` does not walk steadily negative from
  14:00 to 23:00. Under the old bug it fell from about -10% to -59% (2026-09-21).
- The attribute `whole_house` tracks the daily rise of
  `sensor.envoy_482543015950_lifetime_energy_consumption`, not of the net sensor.
- `sensor.universal_room_automation_whole_house_cost_today` is unchanged (still NET-based).
- After a CM reload, `whole_house_source` returns to `ec_total` and coverage does not
  publish a NET-based value. A source switch yields one no-data cycle (debug log
  "whole-house source switched"), then TOTAL reads against a baseline anchored at
  the switch.
