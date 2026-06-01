# v4.7.16.3 — DPM baseline derivation hotfix

**Tier 1.** Single function body, no DB / config-flow / migration surface. 8 source-grep tests + 351 weather/DPM regression tests pass.

## What broke

`WeatherProviderManager._get_zone_baseline_high()` at `domain_coordinators/weather_manager.py:522` was probing two attributes that `PresetManager` does not expose:

1. `getattr(preset_mgr, "SEASONAL_DEFAULTS", None)` — `SEASONAL_DEFAULTS` is a module constant in `hvac_const.py:284`, never bound to the instance.
2. `getattr(preset_mgr, "zone_presets", {})` — does not exist at all.

Both `getattr` calls returned `None` → `baseline_delta_for_zone()` returned `None` → DPM emitted `skipped_zones_with_reason: "no_forecast_delta"` on every tick for every zone. Silently broken since the v4.7.3 baseline-editor refactor (moved zone overrides to CM `entry.options` without updating WPM's probe).

## Evidence

Pre-deploy state of `sensor.ura_energy_coordinator_dynamic_preset_bucket_*` for all 3 zones:
```
state: unknown
delta_f: null
apparent_high_f: 91          ← forecast IS present
baseline_high_f: null        ← THE BUG
dwell_remaining_min: null
```

`sensor.ura_energy_coordinator_dynamic_preset_overrides_applied`:
```
state: 0
skipped_zones_with_reason:
  - zone_id: zone_3, reason: no_forecast_delta
  - zone_id: zone_1, reason: no_forecast_delta
  - zone_id: zone_2, reason: no_forecast_delta
```

## Fix

Route through the canonical accessor `PresetManager.get_seasonal_setpoints(preset)` at `hvac_preset.py:118`. It already merges `SEASONAL_DEFAULTS` with CM `entry.options` per-CONF overrides per the v4.7.3 D2 contract.

```python
pair = preset_mgr.get_seasonal_setpoints(preset)  # (cool_low, cool_high)
if pair is None:
    return None
return float(pair[1])
```

## What today would have looked like

With the fix live:
- Summer home cool baseline = 77°F (from SEASONAL_DEFAULTS or your CM override)
- Today's apparent_high = 91°F
- `delta = 91 - 77 = +14°F`
- Bucket classification (defaults: `COOL ≤ -2`, `MILD ≤ 8`, `HOT ≤ 18`, `EXTREME > 18`) → **HOT**
- DPM would push for **more aggressive cooling**, not less

The operator's instinct was the opposite ("today is cool for Texas, raise the setpoint by 1°F"). This points at a deeper issue the hotfix does NOT address.

## What the hotfix does NOT fix

**The tuning frame is upside-down.** With `delta = forecast_high − zone_cool_target`, the delta is always positive in summer (forecast always > indoor target), so the operator-visible knob is "how positive counts as hot" — not "today is cooler/hotter than typical." The intuitive frame requires `delta = forecast_high − climate_norm_for_season_and_location`, where Austin June median apparent_high (~97°F) becomes the anchor and today (91°F) lands at `delta = -6°F` → COOL bucket → raise setpoint.

**Recommended operator action post-deploy:** turn `switch.ura_energy_coordinator_dynamic_preset_overrides` **OFF** until a climate-norm-baseline follow-on cycle lands. Otherwise DPM will push for more cooling than wanted on most summer days at default thresholds.

## Live validation

```python
# Verify bucket sensor attrs populate
ha_get_state("sensor.ura_energy_coordinator_dynamic_preset_bucket_upstairs",
             attribute_keys=["delta_f", "baseline_high_f", "apparent_high_f"])
# Expect: baseline_high_f != null, delta_f = apparent_high_f - baseline_high_f

# Verify skip reason changes
ha_get_state("sensor.ura_energy_coordinator_dynamic_preset_overrides_applied",
             attribute_keys=["skipped_zones_with_reason"])
# Expect: no "no_forecast_delta" entries
```

## Follow-on cycles (filed, not in this hotfix)

1. **DPM climate-norm baseline source** — switch from `forecast - zone_cool_target` to `forecast - climate_norm`. New per-zone `expected_seasonal_apparent_high` config. Operator-intuitive tuning frame. Tier 1, ~80 LoC.
2. **AC Nudge FP-rate investigation** — 30% FP over 10 samples today. Hypothesis: 10-min eval window catches recoveries instead of ramp-downs. Needs per-nudge event-log review before deciding whether to halve eval window or rethink the signal.

## Rollback

HACS install v4.7.16.2 — DPM returns to silently inert state, no functional change for users (it was already not doing anything).

## Tier

1. Single function body, single call-site contract change, no DB / config-flow / migration surface. Tier 1 review: this README + the inline comment block at the fix site.
