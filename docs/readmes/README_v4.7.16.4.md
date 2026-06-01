# v4.7.16.4 — DPM baseline tuple-index fix-up (CRITICAL caught by retroactive Tier 1 review)

**Tier 1.** 1 LoC production change (`pair[1]` → `pair[0]`), 9 LoC of explanatory comment, expanded tests + new Bug Class #49 entry.

## Procedural breach disclosure

**v4.7.16.3 shipped without the Tier 1 review pass that CLAUDE.md mandates.** A retroactive review run at operator request immediately found a CRITICAL: the hotfix replaced broken `getattr` probes correctly but indexed the wrong field of the canonical accessor's tuple, biasing DPM **one bucket hotter than spec** on every summer day. v4.7.16.4 fixes the index and adds tests that lock the canonical contract in three places at once. The pre-deploy review IS being run for v4.7.16.4.

## What was wrong

`PresetManager.get_seasonal_setpoints(preset)` returns `(cool_setpoint, heat_setpoint)`. Authoritative at:

- `hvac_const.py:283` — `# Default seasonal ranges: {season: {preset: (cool, heat)}}`
- `hvac_preset.py:122` — docstring: `(cool_setpoint, heat_setpoint)`
- `hvac.py:1194` — canonical destructure: `baseline_cool, _baseline_heat = baseline`
- `hvac.py:1197` — comment: `cool is the high`

v4.7.16.3 returned `float(pair[1])` — the heat setpoint (70°F for summer home). Today's behavior:

- Intended: `91 − 77 = 14°F` → HOT bucket
- Shipped: `91 − 70 = 21°F` → **EXTREME bucket**

DPM was pushing for maximum cooling concessions on what the operator considered a cool day.

## Fix

```python
# weather_manager.py:560 (was pair[1])
return float(pair[0])
```

Plus a 9-line explanatory comment so future readers (and future Claude sessions) don't repeat the mistake.

## Tests

3 new tests in `TestTupleShapeAgreement` couple the caller (`weather_manager.py`) to the canonical consumer (`hvac.py`) to the source-of-truth comment (`hvac_const.py`). If any of the three drifts, all three tests fail in tandem — preventing the Bug Class #49 pattern from recurring silently.

Total: 11/11 tests pass on `test_hotfix_v4_7_16_3_dpm_baseline.py`.

## Bug Class #49 added

New entry at `docs/QUALITY_CONTEXT.md` under "Tuple shape assumption drift." Codifies the pattern (caller + tests built from same wrong mental model of upstream contract) and the prevention discipline (parallel test pinning canonical contract at the source-of-truth site, not just at the caller).

## What v4.7.16.4 does NOT fix (deferred to separate cycles)

Per CLAUDE.md "Plan Completion Tracking" — explicit accounting:

1. **DPM tuning frame is upside-down for the operator's mental model.** With `delta = forecast_high − zone_cool_target`, delta is always positive in summer (forecast > target). The operator-visible knob collapses to "how positive counts as hot" — not "today is cooler/hotter than typical Texas June." The intuitive frame requires comparing forecast to **climate norm for season/location** (e.g., Austin June median apparent_high ~97°F → today 91 = -6°F → COOL bucket → raise setpoint). This is a deeper redesign: new per-zone `expected_seasonal_apparent_high` config, switch baseline source in `weather_manager.baseline_delta_for_zone()`. Tier 1 ~80 LoC. **Operator recommended action until then: turn `switch.ura_energy_coordinator_dynamic_preset_overrides` OFF.**

2. **AC Nudge 30% false-positive rate (10 samples today).** Hypothesis: 10-min `AC_NUDGE_EVALUATION_DELAY_S` window catches compressor recoveries instead of ramp-downs on variable-speed Bryant systems. Needs per-nudge event-log review before deciding between (a) halving the eval window in code, (b) making it tunable as a Number entity, (c) rethinking the eval signal entirely. Separate Tier 1 investigation cycle.

## Live validation

```python
# Verify baseline_high_f now reads 77 in summer (not 70)
ha_get_state("sensor.ura_energy_coordinator_dynamic_preset_bucket_upstairs",
             attribute_keys=["baseline_high_f", "apparent_high_f", "delta_f"])
# Expect: baseline_high_f == 77 (summer home cool from SEASONAL_DEFAULTS)
#         delta_f == apparent_high_f - 77

# Verify bucket classification drops from EXTREME → HOT on the same forecast
# (or operator can disable DPM altogether per recommendation above)
```

## Rollback

HACS install v4.7.16.3 — re-introduces the bias. Or v4.7.16.2 — DPM returns to silently inert (probably the safest interim state).

## Tier

1. Single function body, single LoC, pre-deploy Tier 1 reviewed (this time).
