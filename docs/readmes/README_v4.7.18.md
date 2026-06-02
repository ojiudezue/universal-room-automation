# v4.7.18 — DPM Drift Guard + Cleanup (heat-wave absolute-ceiling gate)

**Tier 2-DB (operator-elevated).** ~185 LoC prod across 5 files + ~250 LoC tests. Pre-deploy adversarial review (3 parallel framings: A=data integrity, B=migration/signal-chain, C=new-surfaces/test-authority) found 0 CRITICAL + 0 HIGH + 3 MEDIUM (all C-side) + 14 LOW. All 3 MEDIUMs fixed (C-M1 = this README; C-M2 = deferral logged in planning §14 #6; C-M3 = `dynamic_preset.py` pair-restore guard). 14 LOWs justified for v4.7.19 deferral (see `docs/reviews/code-review/v4.7.18_LOW_deferrals.md`).

## Operator framing (the three audit gaps closed in one cycle)

v4.7.17.2 shipped the simplified rolling-median frame ("on cooler-feeling days relax Home/Sleep ranges; on super-hot days tighten") but operator audit surfaced three drift surfaces:

1. **Surface 2 (per-zone DPM) still rendered 16 dead bucket cells + a `customize_buckets` toggle** — vestige of v4.7.4. Schema noise; not read at runtime. (Closed by D1.)
2. **Dead validator `_validate_dynamic_preset_input`** still defined post-v4.7.17.2; no production callers. (Closed by D2.)
3. **Heat-wave drift risk**: on sustained ≥90°F days the rolling median ratchets upward, narrowing relative_delta and producing residual relax adjustments precisely when comfort should tighten, not loosen. (Closed by D3+D4+D5+D6.)

## The new mechanic — absolute-ceiling-gated relax

`_resolve_relax_ceiling(today_apparent_high, p25_apparent_high, mode) → (ceiling_f, source_label)`

| mode | resolved ceiling | source label |
|---|---|---|
| `auto` (default) | p25 of 90-day forecast ring if ≥30 days; else **90.0°F fallback** | `auto` |
| `conservative_85` | 85.0°F | `manual_conservative` |
| `moderate_90` | 90.0°F | `manual_moderate` |
| `aggressive_95` | 95.0°F | `manual_aggressive` |
| `off` | None (gate disabled) | `off` |

**Gate firing rule:** when `mode != off` AND `today_apparent_high >= ceiling_f` AND the computed `cool_high_adjustment_f > 0` (relax direction), the gate suppresses the relax (sets `cool_high_adjustment_f = 0.0`) and increments `_relax_ceiling_blocked_count[zone_id]`. Tighten direction is NEVER gated.

The internal v4.7.17.2 rolling-median mechanic (`relative_delta = today_apparent_high − rolling_median_14d`, ±2°F deadzone) is preserved exactly. The gate sits AFTER `_compute_cool_high_adjustment` and only intervenes on the relax side.

## Files changed

| # | File | What |
|---|---|---|
| 1 | `domain_coordinators/energy_const.py` | + `CONF_DPM_RELAX_CEILING_MODE` (default `auto`), `DPM_RELAX_CEILING_MODES` tuple, 4 fixed-ceiling constants (`85/90/95`), `DPM_RELAX_CEILING_AUTO_FALLBACK_F=90.0`, `DPM_ROLLING_WINDOW_MAX_DAYS=90`, `DPM_P25_MIN_DAYS=30`. |
| 2 | `domain_coordinators/weather_manager.py` | Ring widen 14→90 entries. New `_p25_apparent_high()` accessor (returns None when ring <30 entries). `_rolling_median_apparent_high()` SLICE preserved (`ring[-DPM_ROLLING_WINDOW_DAYS:]` — load-bearing). Staleness margin widened 21→97 days. Hydrate cap = `cleaned[-MAX_DAYS:]`. |
| 3 | `domain_coordinators/dynamic_preset.py` | + module-level `_resolve_relax_ceiling()`. Heat-wave gate in `_build_overrides_with_reason`. + `restore_blocked_counter()` (Bug #11 UTC-aware, C-M3 pair-restore). + `_relax_ceiling_blocked_count`, `_relax_ceiling_last_blocked_at`, `_relax_ceiling_last_value`, `_relax_ceiling_last_source` dicts. `get_zone_state()` surfaces all 4 new attrs. |
| 4 | `config_flow.py` | **D1:** stripped 16 bucket cells + `customize_buckets` toggle from Surface 2 schema (`_build_dynamic_preset_schema`). **D2:** deleted `_validate_dynamic_preset_input` (zero production callers). **D4:** + `relax_ceiling_mode` 5-option `SelectSelector` dropdown on Surface 1. |
| 5 | `sensor.py` | + 4 new attrs on `DynamicPresetActiveBucketSensor`: `relax_ceiling_f`, `relax_ceiling_source`, `relax_ceiling_blocked_count`, `relax_ceiling_last_blocked_at`. + `_try_restore_blocked_counter()` via RestoreEntity. |
| 6 | `strings.json` + `translations/en.json` | + `dpm_relax_ceiling_mode` label "Skip relax on hot days" + helper text. Removed `dynamic_preset_bucket_required_*` error keys (D2 cascade). |
| 7 | Tests | + `quality/tests/test_v4_7_18_dpm_drift_guard.py` (14 tests covering 6 load-bearing decisions incl. C-M3 pair-restore lock). Retired 25 tests pinning surfaces removed by D1+D2 via `pytest.mark.skip` (preserves archaeology). |

## Tier 2-DB pre-deploy review resolutions

| ID | Sev | Issue | Resolution |
|---|---|---|---|
| C-M1 | MED | `README_v4.7.18.md` + acceptance YAML absent | **Fixed** — this file. Acceptance YAML transcribed verbatim from planning §12. |
| C-M2 | MED | Per-option dropdown DESCRIPTIONS (planning §3) absent in code + strings | **Deferred** to v4.7.19 alongside broader Surface 2 string audit. Logged in planning §14 #6. Labels themselves are operator-approved verbatim and self-explanatory. |
| C-M3 | MED | `restore_blocked_counter` set `last_blocked_at` independently of count → inconsistent shape `count=0, ts=<iso>` | **Fixed** — paired restore under same `if c > 0:` block. Test `test_restore_rejects_timestamp_when_count_is_zero` locks the contract. |
| A-L1..L4, B-L1..L4, C-L1..L6 | LOW (14 total) | hygiene / coherence / coverage gaps | **All deferred to v4.7.19+** with per-finding justification in `docs/reviews/code-review/v4.7.18_LOW_deferrals.md`. None are regressions; all pre-existing or telemetry-only. |

## Migration

- **No DB migration.** Persistence via HA `Store` (unchanged shape, widened cap 14→90).
- **No CONF migration.** v4.7.17.2 CONFs untouched; v4.7.18 ADDS `CONF_DPM_RELAX_CEILING_MODE` default `auto`. v4.7.4-era bucket cells stay dormant in `entry.options` (already the v4.7.17.2 contract).
- **First restart after deploy:** byte-identical 14-day median. Ring loads existing ≤14 entries from Store; `cleaned[-90:]` of a ≤14-entry list = same list; median computed over the most-recent 14.
- **First 30 days post-deploy:** auto ceiling pinned at 90.0°F fallback (ring has <30 entries → p25 unavailable).
- **After day 30:** ceiling = climate's p25 (typically 75–90°F depending on region).
- **Rollback to v4.7.17.2:** new CONF stays dormant. Oversized ring Store payload (potentially >14 entries) gracefully truncates via v4.7.17.2's `cleaned[-14:]` slice. No data loss either direction.

## Tier classification — Tier 2-DB (operator-elevated)

The standard CLAUDE.md Tier 2-DB triggers are not strictly fired (no `database.py` DAO changes, no SQL schema migration). Operator elevation invokes the higher bar because the trust-hierarchy ripple risk is real: DPM ↔ WPM ↔ PM coupling + RestoreEntity counter ownership + UI schema strip. Three parallel review framings (A/B/C) deliver disjoint findings — empirically validated (A and B converged on 0 MED; C surfaced 3 distinct MEDs no other framing would have caught).

## Pre-deploy snapshot (Tier 2-DB requirement)

Before `./scripts/deploy.sh 4.7.18`:

```bash
# Ring file size
wc -l ~/ha-config/.storage/ura_dpm_apparent_high_ring

# Per-zone median baseline (for byte-identity comparison post-restart)
# Replace <zone> with each DPM-enabled zone canonical id (e.g., upstairs, master)
ha_get_state(
    "sensor.ura_energy_coordinator_dynamic_preset_bucket_<zone>",
    attribute_keys=["rolling_median_apparent_high_f","relative_delta_f","cool_high_adjustment_f"],
)

# Tag
git tag pre-review-v4.7.18  # (already exists at 1b3d491)
```

## Live validation (Reviewer D, post-restart)

```python
# Per-zone bucket sensor — verify new attrs present + v4.7.17.2 attrs preserved:
ha_get_state(
    "sensor.ura_energy_coordinator_dynamic_preset_bucket_<zone>",
    attribute_keys=[
        # v4.7.17.2 (must still be present + populated)
        "relative_delta_f",
        "apparent_high_f",
        "rolling_median_apparent_high_f",
        "cool_high_adjustment_f",
        # v4.7.18 NEW
        "relax_ceiling_f",
        "relax_ceiling_source",
        "relax_ceiling_blocked_count",
        "relax_ceiling_last_blocked_at",
    ],
)

# Surface 2 regression check (D1): open URA → Zone Manager → Configure
# DPM-enabled zone. Form must show exactly 4 fields:
#   enabled, offset, reset_guest, sleep_enabled.

# Heat-wave defense smoke (only firable on hot day post-deploy + ring 14+ days):
# When today_apparent_high >= 90F, cool_high_adjustment_f should NOT be positive,
# AND relax_ceiling_blocked_count should be >= 1 if a relax was suppressed.

# URA ERROR log grep — no missing-CONF crashes from existing zones:
# ha_get_logs source=system_service slug=core | grep -E 'universal_room_automation.*ERROR'
# Expected: 0 matches in the hour post-restart.
```

## Acceptance

```yaml
version: v4.7.18
hypotheses:
  - id: H1
    name: relax_ceiling_mode_dropdown_present_surface_1
    description: |
      The new operator dropdown "Skip relax on hot days" must appear on
      the HVAC Coordinator → Dynamic Preset Surface 1 form with exactly
      5 options (auto, conservative_85, moderate_90, aggressive_95, off).
    query:
      kind: config_flow_schema
      step: hvac_dynamic_preset
      field: dpm_relax_ceiling_mode
    expected:
      condition: "options_set_equals"
      value: ["auto", "conservative_85", "moderate_90", "aggressive_95", "off"]
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h

  - id: H2
    name: relax_ceiling_f_sensor_attr_numeric
    description: |
      Bucket sensor exposes relax_ceiling_f attribute, numeric or null
      depending on mode (null only when source=="off"). Per-zone entity:
      sensor.ura_energy_coordinator_dynamic_preset_bucket_<zone>.
    query:
      kind: ha_state_attribute
      entity: sensor.ura_energy_coordinator_dynamic_preset_bucket_upstairs
      attribute: relax_ceiling_f
    expected:
      condition: "is_numeric_or_null"
      value: null
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h

  - id: H3
    name: relax_ceiling_source_reflects_operator_choice
    description: |
      Sensor attribute relax_ceiling_source matches the operator's
      configured mode in entry.options after a save. Per-zone entity:
      sensor.ura_energy_coordinator_dynamic_preset_bucket_<zone>.
    query:
      kind: ha_state_attribute
      entity: sensor.ura_energy_coordinator_dynamic_preset_bucket_upstairs
      attribute: relax_ceiling_source
    expected:
      condition: "in"
      value: ["auto", "manual_conservative", "manual_moderate", "manual_aggressive", "off"]
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h

  - id: H4
    name: relax_ceiling_blocked_count_fires_in_production_heat
    description: |
      After at least one >=90F day post-deploy with auto mode AND
      ring has 14+ entries, relax_ceiling_blocked_count > 0. Proves
      the heat-wave drift gate fires in production. Per-zone entity:
      sensor.ura_energy_coordinator_dynamic_preset_bucket_<zone>.
      C-M3 contract: relax_ceiling_blocked_count and
      relax_ceiling_last_blocked_at are read as a PAIR; one without
      the other is malformed and would not have survived restore.
    query:
      kind: ha_state_attribute
      entity: sensor.ura_energy_coordinator_dynamic_preset_bucket_upstairs
      attribute: relax_ceiling_blocked_count
    expected:
      condition: ">"
      value: 0
    window:
      first_check_after: 168h    # 7 days
      confirm_after: 720h         # 30 days
      alert_if_violated_after: 2160h  # 90 days
      only_during: forecast_apparent_high_seen_geq_90f

  - id: H5
    name: surface_2_no_bucket_cells_rendered
    description: |
      Surface 2 (per-zone DPM config) form schema MUST NOT include any
      of the 16 bucket cell fields nor the customize_buckets toggle.
      Regression check for D1 strip.
    query:
      kind: config_flow_schema
      step: zone_dynamic_preset
      field_names_must_not_include:
        - zone_dynamic_preset_customize_buckets
        - zone_dynamic_preset_cool_home_low
        - zone_dynamic_preset_cool_home_high
        - zone_dynamic_preset_mild_home_low
        - zone_dynamic_preset_mild_home_high
        - zone_dynamic_preset_hot_home_low
        - zone_dynamic_preset_hot_home_high
        - zone_dynamic_preset_extreme_home_low
        - zone_dynamic_preset_extreme_home_high
        - zone_dynamic_preset_cool_sleep_low
        - zone_dynamic_preset_cool_sleep_high
        - zone_dynamic_preset_mild_sleep_low
        - zone_dynamic_preset_mild_sleep_high
        - zone_dynamic_preset_hot_sleep_low
        - zone_dynamic_preset_hot_sleep_high
        - zone_dynamic_preset_extreme_sleep_low
        - zone_dynamic_preset_extreme_sleep_high
    expected:
      condition: "all_absent"
      value: true
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h

  - id: H6
    name: existing_zones_load_without_errors_after_strip
    description: |
      Every existing DPM-enabled zone loads without missing-CONF crashes
      after the Surface 2 schema strip. entry.options bucket cells stay
      readable (data preserved); runtime ignores them. URA ERROR log
      must remain clean for one full hour post-restart.
    query:
      kind: log_grep
      source: home_assistant_core
      pattern: "universal_room_automation.*ERROR"
    expected:
      condition: "no_matches_in_window"
      value: null
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
```

## Rollback

HACS install v4.7.17.2 — old v4.7.17.2 rolling-median frame restored. `CONF_DPM_RELAX_CEILING_MODE` persists dormant in `entry.options` (v4.7.17.2 ignores it). Ring Store widened payload (potentially >14 entries) loads truncated via v4.7.17.2's `cleaned[-14:]` slice. No data loss either direction.

## Sibling cycles (deferred)

- **v4.7.19 string audit** — per-option dropdown descriptions for `relax_ceiling_mode` (C-M2 deferral) + broader v4.7.4-era orphan keys (C-L1) + dead mirror entries (C-L2).
- **v4.7.19 hygiene sweep** — A-L1..L4 telemetry/restart-resilience polish + B-L1..L4 dead-form-branch + restart-race MAX-of-restored + B-L4 i18n machinery (single-locale workaround acceptable as-is).
- **v5.0 bucket-cell removal sweep** — strip 16 per-zone CONFs from `energy_const.py` (still readable for diagnostic `classify_bucket()`).
- **v5.0 architectural debt** — `_build_dynamic_preset_schema` 21→4 positional arg cleanup (C-L3 documented intentional back-compat).
