# v4.5.13 — Observability Gap Fixes

**Date:** 2026-05-12
**Type:** Tier 2 cycle (per "full quality protocols" direction)
**Predecessor:** v4.5.12 (slice 2 of v4.5.11 cycle — live-validated, stable)

## Summary

Two surgical fixes deferred from v4.5.12's live validation. Both touch single sites; neither adds new entities, schema, or config keys. 26 new tests. Two independent staff-engineer reviews under the amended quality bar; APPROVED with all Review 1 fixes applied pre-deploy.

## What's fixed

### Fix 1: AC kWh Rate diagnostic sensor no longer stuck `unknown`

**Symptom (v4.5.12 live validation):** `sensor.ura_hvac_coordinator_ac_kwh_rate_<zone>` showed `unknown` on all 4 zones even when the source `sensor.span_panel_ac_*_power` reported live values (e.g., 2119 W). Master switch was OFF.

**Root cause:** `HVACACRampKwhRateSensor.native_value` read `zone.last_kwh_rate`, a ZoneState field that `OverrideArrester._read_kwh_rate` only populates while the master switch is ON. A diagnostic sensor was gated by the feature switch.

**Fix:** new helper `_read_source_kw` reads `hass.states.get(zone.ac_load_sensor)` directly, parses float, converts W→kW based on `unit_of_measurement`. Independent of the master switch.

**Hardening from Review 1:**
- Sanity bounds `[0.0, 50.0] kW` reject sensor glitches before they pollute long-term statistics (kW/W glitch class — historical Bug v4.3.4)
- Empty `unit_of_measurement` is now rejected, not silently treated as kW
- Source `state in ("unknown", "unavailable", "")` returns None
- Non-numeric source state returns None
- Missing source entity returns None

**New attributes on the sensor:**
- `source_unit` — reflects the live unit from the source entity (debugging aid for unit mismatches)
- existing `stale` / `age_seconds` / `kwh_threshold` retained

### Fix 2: Anomaly detectors transition from `learning` to `nominal` on partial coverage

**Symptom:** `sensor.ura_hvac_coordinator_hvac_anomaly`, presence anomaly, safety anomaly, security anomaly, and NM anomaly all showed `state: learning` for weeks. HVAC attrs showed 883 samples on 2 metrics, 0 samples on the other 2.

**Root cause:** `AnomalyDetector.get_learning_status` required ALL declared metrics to have `sample_count >= minimum_samples`. Two of four HVAC metrics (`short_cycle_rate`, `comfort_deviation_hours`) never received observations — either the record_observation call sites were never wired or the underlying events don't fire on this install.

**Fix:** transition to ACTIVE when at least `max(1, len(metric_names) // 2)` metrics are complete. Per-metric anomaly raising in `record_observation` is unchanged — anomalies still only fire when the specific metric's baseline is above minimum. Dead metrics still surface as `active=False` in the metric details, preserving visibility into the wiring gap.

**Why floor-half-min-1 and not strict majority:** for 2-metric detectors, true majority would require both (== old gate) and defeats the purpose. For 3-metric detectors, the math gives 1 — small-N degenerate case, but worse than the alternative (stuck-in-learning forever).

## What's NOT changed

- No new entities, sensors, switches, or buttons
- No DB schema changes
- No config keys
- No behavioral changes to AC ramp-down actions, anomaly raising, or coordinator decision cycles
- No dashboard breakage (entity_ids unchanged)

## Tier 2 Review

First Tier 2 cycle since the quality-bar amendment in v4.5.12. Both reviews mentally executed the full code path.

**Review 1 (Core A) — domain correctness, edge cases, type contracts:**
APPROVED-WITH-FIXES. All recommended fixes applied pre-deploy (sanity bounds, unit-rejection, docstring/code alignment, expanded test coverage).

**Review 2 (Core B) — concurrency, lifecycle, restart, cross-coordinator:**
APPROVED. No CRITICAL/HIGH. 2 MEDIUM accepted as documentation observations (dispatcher race window is vanishingly small under sync dispatch + 5-min cadence; double-read of `_read_source_kw` is O(1) and reads stable state). 2 LOW accepted as style nits.

| Severity | Found | Fixed | Accepted |
|---|---|---|---|
| CRITICAL | 0 | — | — |
| HIGH | 0 | — | — |
| MEDIUM | 4 | 2 | 2 documented |
| LOW | 6 | 2 | 4 documented |

Full review at `docs/reviews/code-review/v4.5.13_review.md`.

## Test count

- v4.5.12: 326 tests
- **v4.5.13: 352** (+26 from `test_v4513_gap_fixes.py`)

Breakdown of new tests:
- 5 AST/source-grep tests pinning Fix 1's read path (no regression to `zone.last_kwh_rate`, W→kW conversion present, unknown/unavailable handled, no Bug Class #34 datetime shadow)
- 11 behavior tests for `_read_source_kw` using a synthesized reader (AST-extracted method body + stubbed hass.states.get) — covering W→kW, kW pass-through, unknown/unavailable, non-numeric, missing unit, unknown unit, negative values, implausibly huge values, missing source, missing state
- 9 behavior tests for the gate relaxation (1/2/3/4/5-metric detectors, both ACTIVE and LEARNING paths, plus regression-guard that per-metric `active` flag survives)
- 1 source-grep regression guard against accidental revert of the threshold comparison

## Live validation plan (post-restart)

1. **AC kWh Rate sensors populate within 5 minutes (one HVAC decision cycle):**
   - `sensor.ura_hvac_coordinator_ac_kwh_rate_back_hallway` → live kW value (source: `sensor.span_panel_ac_3_power`)
   - `sensor.ura_hvac_coordinator_ac_kwh_rate_entertainment` → live kW value
   - `sensor.ura_hvac_coordinator_ac_kwh_rate_master_suite` → live kW value (same source as entertainment)
   - `sensor.ura_hvac_coordinator_ac_kwh_rate_upstairs` → live kW value (source emitted 2119 W in v4.5.12 live test → expect 2.119 kW)
   - All show `stale: false` and recent `age_seconds`

2. **Anomaly detectors transition from `learning`:**
   - `sensor.ura_hvac_coordinator_hvac_anomaly` → `nominal` (or `advisory/alert/critical` if metrics have anomalies)
   - `sensor.ura_presence_coordinator_presence_anomaly` → `nominal`
   - `sensor.ura_safety_coordinator_safety_anomaly` → `nominal`
   - `sensor.ura_security_coordinator_security_anomaly` → `nominal`
   - `sensor.ura_notification_manager_notification_anomaly` → `nominal`
   - All show per-metric `active=False` on dead metrics in attrs (visibility preserved)

3. **Zero new URA errors in system log** (`ha_get_logs source=system level=ERROR search=universal_room_automation`)

4. **No regression on existing entities:** `sensor.ura_hvac_coordinator_ac_nudge_false_positive_rate` still `unknown` (sample_size < 5 — R3 mitigation working).

## Deploy notes

- No DB schema changes
- No migration needed
- HACS download required after deploy.sh
- HA restart required (2 files touched: sensor.py, coordinator_diagnostics.py)
- After restart: confirm AC kWh Rate sensors populate within 5 min; confirm anomaly sensors transition out of `learning`

## Documents

- Review: `docs/reviews/code-review/v4.5.13_review.md`
- BACKLOG entries v4.5.15 + v4.5.16 (duplicate-timestamp + prediction-scoring investigations) remain unchanged; v4.5.14 closet/bathroom auto-off is next

## Next

- **v4.5.14** — closet + bathroom lazy auto-off (60-min default fail-safe)
- **v4.5.15** — duplicate-timestamp investigation → minor fix
- **v4.5.16** — Bayesian prediction-scoring pipeline investigation → minor fix
- **v4.6.0** — Routine Awareness Phase 1 (calibration window begins)
