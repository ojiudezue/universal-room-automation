# v4.3.4 — Battery power kW/W unit fix

**Date:** 2026-05-06
**Type:** Tier 1 hotfix (latent unit-mismatch bug, ~30 LoC change + 5 regression tests)
**Predecessor:** v4.3.3

## Summary

Fixes a latent unit-mismatch bug discovered immediately after v4.3.3 shipped. The EV battery-drain pause and smart-plug battery-drain pause both compared `battery_power_w` to `-100` (W threshold), but the value passed in was `self._battery.battery_power` — which is **whatever the underlying Envoy entity reports**. Newer Envoy installs (including the user's) report in **kW**, so the value passed was e.g. `-0.21` (kW). The check `-0.21 < -100` was always False → drain protection silently disabled. **Latent since v4.2.17** when the protection was added.

User-visible: with v4.3.3's slider set to 80, battery at 62%, EV charging at 7.4 kW, battery actively discharging at 210W → URA correctly evaluates the slider/SOC condition (`62 < 80` True) but incorrectly evaluates the discharge condition (`-0.21 < -100` False) → no pause.

## Root cause

`BatteryStrategy.battery_power` returns `-raw_state` from `sensor.envoy_*_current_battery_discharge`. That entity's `unit_of_measurement` is `"kW"` on the user's install. Two callsites in `energy.py` pass this kW value to:
- `EVChargerController.determine_battery_drain_actions(battery_power_w=...)`
- `SmartPlugController.determine_battery_drain_actions(battery_power_w=...)`

The parameter name says `_w` but the call passes whatever-units. Inside the callee the threshold `< -100` assumes W. Mismatch.

## Fix

Add a unit-normalizing accessor on `BatteryStrategy`:

```python
@property
def battery_power_w(self) -> float | None:
    """Battery power normalized to W (positive=charging, negative=discharging).
    Reads the entity's unit_of_measurement and multiplies by 1000 if kW.
    """
```

Update the 2 callsites in `energy.py:1869` and `:1894` to pass `self._battery.battery_power_w` instead of `self._battery.battery_power`.

The drain-rule code in `energy_pool.py` keeps the `< -100` (W) threshold — it's now correctly fed W regardless of which unit the Envoy reports.

`BatteryStrategy.battery_power` is left unchanged (still returns whatever the entity reports). It's still used in the strategy sensor display where users have come to recognize the value; changing units there would be a UI break. The unit-correctness lives in the new `battery_power_w` property.

## What changed

- `domain_coordinators/energy_battery.py`: new `battery_power_w` property (~25 LoC + docstring)
- `domain_coordinators/energy.py`: 2 callsites updated to pass `battery_power_w`
- `quality/tests/test_energy_battery.py`: 5 new regression tests (`TestBatteryPowerUnitNormalization`)

## Tier 1 Review

Per project memory `feedback_review_bug_visibility.md`:

| Severity | Finding | Status |
|---|---|---|
| (none CRITICAL) | — | — |
| (none HIGH) | — | — |
| (none MEDIUM) | — | — |
| LOW | `battery_power` (without `_w`) is left as-is — still kW on this install. Other callers might inadvertently use it for math expecting W. Currently the only other consumer is the strategy sensor display (no math). | **Accepted** — narrow change preserves UI; future caller adding math should use `battery_power_w`. Could add a docstring warning to `battery_power` (already done in this fix). |
| LOW | The user's existing `battery_power` shows `-0.21` on the strategy sensor; some users may have automations relying on this value being in kW. Unchanged in this fix — only the *internal* drain math is normalized. | **No action** — backward compat preserved deliberately. |

**Verdict: READY TO DEPLOY.** All 117 tests pass (5 new regression tests added). AST clean.

Full review at `docs/reviews/code-review/v4.3.4_battery_power_kw_unit_fix.md`.

## Tests

Five new tests in `TestBatteryPowerUnitNormalization`:
- `test_battery_power_w_kw_entity_normalizes_to_w` — kW reading × 1000 = W
- `test_battery_power_w_w_entity_passes_through` — W reading unchanged
- `test_battery_power_w_no_uom_assumes_w` — missing UoM defaults to W
- `test_battery_power_w_unavailable` — `unavailable` state → None
- `test_battery_power_w_kw_below_threshold` — small discharges (<100W) correctly don't trip the rule

The tests would have caught the bug from v4.2.17 if they had existed then. Filed as a permanent regression suite for this kind of unit-mismatch.

## Live validation (post-deploy)

After HACS download + HA restart:

1. Confirm `installed_version: v4.3.4` via HACS
2. With slider at 80, battery at 62%, battery discharging > 100W, EV charging:
   - Within ≤5 min on next decision tick: garage_a should pause
   - Log line: `EV battery drain: pausing garage_a (battery=-XXXW, SOC=62% < 80%)`
   - `sensor.ura_energy_coordinator_ev_charging_status.attributes.paused_by_battery_drain` should show `["garage_a"]`
3. If battery later refills above 85% (= 80 + 5% hysteresis), garage_a should resume

## Deploy notes

- No DB schema changes
- No breaking changes to public API or sensor displays
- Manifest stamped to v4.3.4 by deploy.sh
- HACS download required after deploy.sh per `feedback_verify_hacs_install.md`

## Next

Continuing the queue:
- **v4.3.5** — multi-day Solcast forecast lookback per `docs/planning/PLANNING_v4.3.3_multi_day_solcast_lookback.md` (will rename when work begins)
- **v4.4.x** — B5 Appliance Scheduler
- **v4.5.0** — Routine Awareness with reconciled AnomalyEvent foundation
