# v4.7.17.2 — DPM Simplified Operator Framing (rolling-median baseline)

**Tier 1.** ~120 LoC prod across 7 files + ~250 LoC tests (39 new + 4 M2 behavioral). Pre-deploy adversarial review found 0 CRITICAL + 2 HIGH + 3 MEDIUM + 3 LOW; H1 + M2 + M3 fixed before commit. H2 + M1 disposed in-place (kept-by-design + documented).

## Operator framing (verbatim, the reason for the redesign)

> *"The point of DPM is — on days that feel cooler outside, relax the Home and Sleep Preset ranges. If normally 70-75 on hot days, make it 70-76 on cooler feel days. On super hot days consider tightening to 70-74. That's it."*

The v4.7.x discrete-bucket mechanic (cool/mild/hot/extreme buckets with 16 per-zone CONFs and 4 delta-boundary CONFs) had drifted from this framing. v4.7.17.2 collapses it into ≤2 user-facing knobs against a self-tuning baseline.

## The new mechanic

`relative_delta = today_apparent_high − rolling_median_apparent_high_14d`

| relative_delta | day feels | adjustment to cool_high |
|---|---|---|
| ≤ −2.0°F | cooler than 14-day median | **+`dpm_cool_day_relax_f`** (default +1.0°F) |
| −2.0°F to +2.0°F | typical | **0.0°F** (deadzone, no override) |
| ≥ +2.0°F | hotter than median | **−`dpm_hot_day_tighten_f`** (default −1.0°F) |

`effective_home_high = PresetManager_seasonal_cool + zone_offset + cool_high_adjustment_f`
`effective_sleep_high = compute_sleep_high(seasonal_cool + adjustment, zone_offset)`

The bucket label (cool/mild/hot/extreme) persists on the sensor as a diagnostic — it no longer drives the override math.

## Why rolling 14-day median (not the rejected alternatives)

- **Self-tuning, no operator config.** Operator framing rule #2 ("reconsider stuff we don't need") forbids exposing per-season floats or installer "pick your climate" steps. Climate-norm CONFs fail this.
- **Adapts to climate shift without intervention.** 14 days smooths single-day forecast noise; short enough that seasonal transitions carry the baseline with them.
- **Existing "forecast − cool_target" frame (v4.7.16.4) rejected.** Using the operator's indoor target as the baseline is what produced "91°F is HOT" in Austin (operator intuition: 91°F is mild for Texas summer).
- **±2.0°F deadzone** prevents flickering "today is 0.3°F warmer" transitions. Hardcoded inside `_compute_cool_high_adjustment` — not exposed.

## Files changed

| # | File | What |
|---|---|---|
| 1 | `domain_coordinators/energy_const.py` | + `CONF_DPM_COOL_DAY_RELAX_F`, `CONF_DPM_HOT_DAY_TIGHTEN_F`, defaults = 1.0; + internal `DPM_ROLLING_WINDOW_DAYS=14`, `DPM_ROLLING_WINDOW_MIN_DAYS=7`, `DPM_RELATIVE_DELTA_DEADZONE_F=2.0`. |
| 2 | `domain_coordinators/weather_manager.py` | Rewrote `baseline_delta_for_zone` (semantic flip to rolling-median). Deleted `_get_zone_baseline_high`. Added `_rolling_median_apparent_high`, `_record_daily_apparent_high`, `_persist_ring`, `_hydrate_rolling_window_from_store`. `Store` key `ura_dpm_apparent_high_ring`. Hydrate runs BEFORE first probe in `async_setup`. |
| 3 | `domain_coordinators/dynamic_preset.py` | + module-level `_compute_cool_high_adjustment(delta, relax_f, tighten_f)`. Winter-gate short-circuit (`return [], "winter_season"` when PresetManager.current_season == SEASON_WINTER) using coordinator-resolved PM. `_build_overrides_with_reason` refactored: `home_high` now from `PresetManager.get_seasonal_setpoints("home")[0]` (Bug Class #49 tuple shape), bucket-cell reads stripped from runtime path. `resolved_pm` plumbed through from evaluate_with_reason (Tier 1 H1 — no fresh PM construction per tick). |
| 4 | `config_flow.py` | Stripped 3 bucket-boundary CONFs from visible Surface 1 schema. + 2 new Number knobs `vol.Range(min=0.0, max=3.0)`. Removed `cool_max < mild_max < hot_max` validation block + `dynamic_preset_bucket_boundary_disorder` error key. |
| 5 | `sensor.py` | Renamed `delta_f` → `relative_delta_f`, `baseline_high_f` → `rolling_median_apparent_high_f`. + new `cool_high_adjustment_f` attribute. |
| 6 | `strings.json` + `translations/en.json` | New visible labels for the 2 new knobs. Description language matches operator framing verbatim. Stale bucket-required error strings RETAINED (only surface when operator opts into Surface 2 customize_buckets — see H2 disposition below). |
| 7 | Tests | + `quality/tests/test_v4_7_17_2_dpm_simplified_frame.py` (39 tests). Updated 4 legacy v4.7.4 lockdown tests + 11 hotfix tests to v4.7.17.2 semantics. + 4 behavioral tests (`TestPMSeasonalLookupBehavioral`) covering Bug Class #49 + PM-seasonal lookup. |

## Pre-deploy review resolutions

| # | Sev | Issue | Resolution |
|---|---|---|---|
| H1 | HIGH | `_build_overrides_with_reason` constructed `PresetManager(self.hass)` per tick — two different PM instances vs the winter gate's coordinator-resolved PM | Resolved PM now captured once at `evaluate_with_reason` top, plumbed via new `resolved_pm` kwarg through to builder. Falls back to fresh construction only when resolved PM is unavailable (test paths). |
| H2 | HIGH | `dynamic_preset_bucket_required_*` translation strings reference the rejected "bucket cool_low/high" frame | **Kept by design.** These strings only surface when operator toggles `customize_buckets=True` on Surface 2 (the escape hatch for hand-tuning preserved bucket cells). In that opt-in context the language is contextually correct. Per "DO NOT throw away stuff that we need" — escape-hatch UX retained. |
| M1 | MED | Bucket label cycles HOT→EXTREME but override math is identical | Documented in this README: bucket label is diagnostic-only post-v4.7.17.2. Future enhancement (scaling adjustment by bucket distance) deferred to v5.0 architectural-debt sweep. |
| M2 | MED | Source-grep tests didn't exercise PM-seasonal lookup end-to-end | + 4 new `TestPMSeasonalLookupBehavioral` tests covering: (a) seasonal pair → home_high arithmetic, (b) Bug Class #49 tuple-shape contract, (c) None return → clean skip_reason, (d) negative adjustment tightens. |
| M3 | MED | `_persist_ring` / `_hydrate_rolling_window_from_store` swallowed all exceptions at DEBUG level → silent ring degradation | Bumped both to `_LOGGER.warning` with operator-actionable messages. |
| L1-L3 | LOW | Same-day rewrite on forecast updates, tz mix risk, `delta_f` signal-payload rename | Noted for cleanup; not deploy-blocking. |

## Migration

- **No DB migration.** Persistence via HA `Store` (HA-standard, not URA-internal DB).
- **No CONF migration.** Legacy bucket boundary CONFs + per-zone bucket cells stay dormant in `entry.options`. Runtime ignores them. Cleanup deferred to v5.0.
- **First 7 days post-deploy = natural no-op** while the ring fills. DPM emits `no_forecast_delta` until the rolling window has `>= 7` entries. No feature flag needed.

## Tier classification — Tier 1

- Single feature, ~120 LoC prod across 7 files
- No DB schema changes (Store ≠ URA DB)
- No DAO migration (Store is HA-native)
- Pre-deploy adversarial review run + resolved before commit (per the v4.7.16.3 procedural lesson)

## Live validation

```python
# After install + restart, verify entity surface:
ha_get_state("sensor.ura_energy_coordinator_dynamic_preset_bucket_<zone>",
             attribute_keys=["relative_delta_f", "rolling_median_apparent_high_f",
                             "cool_high_adjustment_f"])

# Verify Store ring is persisting (after a forecast tick):
# Check ~/ha-config/.storage/ura_dpm_apparent_high_ring exists
```

## Acceptance

```yaml
version: v4.7.17.2
hypotheses:
  - id: H1
    name: dpm_bucket_sensor_available_post_restart
    description: |
      v4.7.17.2 simplified-frame code must load and the DPM coordinator
      must complete its first 5-min cycle post-restart. Validated by
      the bucket sensor for a canonical zone (Upstairs) reaching a
      non-unavailable state. The ≤2 operator knobs themselves are
      CONFIG-FLOW options (CONF_DPM_COOL_DAY_RELAX_F / CONF_DPM_HOT_DAY_TIGHTEN_F,
      defaults 1.0°F each — see energy_const.py:220-223), NOT Number
      entities. Their behavioral effect is covered by H4.
    query:
      kind: ha_state
      entity: sensor.ura_energy_coordinator_dynamic_preset_bucket_upstairs
    expected:
      condition: "!="
      value: "unavailable"
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h

  - id: H2
    name: sensor_attrs_renamed
    description: |
      Bucket sensor must expose v4.7.17.2 attribute names:
      relative_delta_f (was delta_f), rolling_median_apparent_high_f
      (was baseline_high_f), and new cool_high_adjustment_f. Any legacy
      attribute name still present indicates an incomplete rename.
    query:
      kind: ha_state_attribute
      entity: sensor.ura_energy_coordinator_dynamic_preset_bucket_upstairs
      attribute: cool_high_adjustment_f
    expected:
      condition: "!="
      value: null
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h

  - id: H3
    name: cold_start_no_op_until_ring_fills
    description: |
      For the first ~7 days the rolling-median ring is < min_days; DPM
      must emit no override (skip_reason "no_forecast_delta"). This is
      the clean migration path — no feature flag, no operator action.
      Once the ring has ≥7 entries DPM begins emitting normally.
    query:
      kind: ha_state_attribute
      entity: sensor.ura_energy_coordinator_dynamic_preset_bucket_upstairs
      attribute: last_skip_reason
    expected:
      condition: "in"
      value: ["no_forecast_delta", "winter_season", null]
    window:
      first_check_after: 1h
      confirm_after: 168h   # 7 days — ring should be filling toward min_days threshold
      alert_if_violated_after: 336h

  - id: H4
    name: cool_high_adjustment_correctness
    description: |
      Once ring ≥ 7 days: on a day where relative_delta_f ≥ +2.0,
      cool_high_adjustment_f should equal -dpm_hot_day_tighten_f
      (default -1.0). On a day where relative_delta_f ≤ -2.0,
      it should equal +dpm_cool_day_relax_f (+1.0). In the deadzone
      (-2 < δ < +2) it should equal 0.0. Direct correctness check of
      the new mechanic.
    query:
      kind: ha_state_attribute
      entity: sensor.ura_energy_coordinator_dynamic_preset_bucket_upstairs
      attribute: cool_high_adjustment_f
    expected:
      condition: "in"
      value: [-1.0, 0.0, 1.0]
    window:
      first_check_after: 168h    # after ring fills
      confirm_after: 336h         # over 7 days post-ring-fill
      alert_if_violated_after: 504h

  - id: H5
    name: winter_gate_skips_emit
    description: |
      When HVAC PresetManager.current_season == winter, DPM short-circuits
      with skip_reason "winter_season" (no overrides emitted). DPM is a
      cooling-side feature; winter emissions are meaningless and would
      churn bucket transitions. Verify only during a winter month.
    query:
      kind: ha_state_attribute
      entity: sensor.ura_energy_coordinator_dynamic_preset_bucket_upstairs
      attribute: last_skip_reason
    expected:
      condition: "=="
      value: "winter_season"
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
      only_during: hvac_season=winter
```

## Rollback

HACS install v4.7.17.1 — old DPM bucket-driven mechanic restored. New CONFs `dpm_cool_day_relax_f` / `dpm_hot_day_tighten_f` persist in entry.options but become dormant (v4.7.17.1 ignores them). Bucket boundary CONFs become active again. Ring Store file (`.storage/ura_dpm_apparent_high_ring`) persists but is unread. No data loss either direction.

## Sibling cycles (deferred)

- **v5.0 bucket-cell removal sweep** — strip 16 per-zone CONFs + 3 boundary CONFs from `energy_const.py` after this redesign proves stable.
- **DPM adjustment-scaling by bucket distance** — future enhancement if operator wants EXTREME days tightened more than HOT days (per M1).
- **Boot warning room-coordinator noise suppression** — ~15 LoC Tier 1 backlog (operator: "track but ignore for now").
