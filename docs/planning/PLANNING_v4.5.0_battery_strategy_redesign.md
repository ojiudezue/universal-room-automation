# PLANNING v4.5.0 — Battery Strategy Redesign

**Status:** Planned, not started
**Tier:** Feature cycle (Tier 2 — 2 reviews + live validation per CLAUDE.md)
**Predecessors:** v4.3.4 (production), `PLANNING_v4.3.3_multi_day_solcast_lookback.md` (superseded — folded as D3)
**Effort estimate:** 1 cycle (~470 prod / ~520 test LoC)

## Context

Through v4.3.0–v4.3.4 we've shipped the battery strategy as a five-knob system:

- `reserve_soc` — outage safety floor
- `drain_target_excellent / good / moderate / poor` — forecast-trust drain heuristic (4 sliders; very_poor falls back to poor)
- `arbitrage_trigger` — rescue-charge SOC threshold
- `arbitrage_target` — rescue-charge SOC ceiling

Through several user-driven design conversations on 2026-05-06 we surfaced fundamental issues in the current model:

1. **Drain-target conflicts arbitrage when arbitrage is on.** With `arbitrage_trigger=20 < drain_target_poor=30`, arbitrage is unreachable from above — Phase A locks the battery at 30%. Arbitrage only fires as a "rescue" if SOC entered off-peak below 20. Result: arbitrage almost never fires in practice.

2. **Charged energy gets drained before it's valuable.** Even when arbitrage fires, the morning after charging to 80% sees Phase A drain back down to drain_target during the long morning off-peak window. By the time peak hits at 16:00 (summer), battery is at drain_target (10–40%), not 80%. The arbitrage "savings" calculation in v4.3.0 D4 acknowledged this with a methodology disclosure ("may overstate"), but the real fix is to *enforce* the assumption.

3. **The drain target system is forecast-confidence-weighted draining**, designed for a world where arbitrage doesn't exist. With arbitrage available, the drain decision becomes: "drain less when forecast is bad" → which conflicts with arbitrage's "charge more when forecast is bad." Two coupled concerns that should be separated.

The redesign acknowledges that **drain targets are still meaningful when arbitrage is OFF**. They stay as the fallback for `arbitrage_enabled = False`. The new behavior is an arbitrage-on path that takes precedence over drain targets when (arbitrage_enabled AND tomorrow_class in poor/very_poor).

User direction (2026-05-06): "Arbitrage overrides drain targets completely on poorer forecast tomorrows. On good forecast tomorrows, drain targets assert themselves." That's the rule. Cleanly stated.

**Single-user scope**: URA has one production install. **No backward-compatibility constraints**. We can rename, remove, and restructure freely without preserving v1 behavior. The mode-toggle / dual-strategy plan from earlier drafts has been simplified accordingly.

## Goals

1. Fix the arbitrage waste problem: charged energy must be preserved through morning off-peak until it actually displaces peak/mid-peak imports.
2. Eliminate the boundary collision between drain targets and arbitrage trigger by removing `arbitrage_trigger` entirely. The arbitrage gate becomes forecast class only.
3. Reduce user-surface complexity: remove the `arbitrage_trigger` slider; rename `arbitrage_target` to `peak_buffer_target` (clearer naming).
4. Add multi-day forecast awareness so D+2 forecasts can modulate when to fire arbitrage.
5. Add charge rate cap to prevent 20 kW grid spikes from arbitrage.
6. Surface enough diagnostic state that the user can see *why* the strategy made each decision.

## Non-goals (deferred)

- **Removing drain targets entirely.** They remain as the fallback when arbitrage is disabled. Drop only `arbitrage_trigger`.
- **Bayesian-derived dynamic peak_buffer_target** (e.g., compute per-day-type buffer from observed peak-window discharge history). Future cycle (v4.6.x or later) once new strategy is calibrated.
- **Variable peak_buffer_target by season** (summer needs more buffer than shoulder due to 4hr peak vs 4hr mid_peak). One number for v4.5.0; auto-tune later.
- **Cycle-wear amortization in ROI math.** Current ROI math doesn't subtract battery degradation cost. Reasonable approximation today; refine when usage data warrants.
- **Config flow restructure** (paginated, rate-plan top-level toggle, net-metering branch). Folded out to v4.5.1 to keep v4.5.0 review surface manageable.
- **Per-EVSE drain protection thresholds** (one threshold for all EVSEs).
- **Generator-aware battery strategy** (treats generator presence as another power source). Future.

## Architecture

### The strategy rule (single statement)

```
if arbitrage_enabled AND tomorrow_class in ("poor", "very_poor"):
    use arbitrage path (D1)
else:
    use drain-target path (existing logic; unchanged)
```

Drain targets still apply when:
- `arbitrage_enabled == False`
- `tomorrow_class in ("excellent", "good", "moderate", "unknown")`

### Arbitrage path (the new behavior)

When the rule fires AND we're in an off-peak window:

1. **Pre-peak off-peak** (today's peak/mid_peak still ahead):
   - If `SOC < peak_buffer_target` AND `not _arbitrage_completed_in_session`: charge from grid; `reserve_level = peak_buffer_target`
   - Else: hold; `reserve_level = current SOC`
2. **Post-peak off-peak** (today's peak/mid_peak passed; we're in the late-evening / overnight window before tomorrow's peak ~16-20 hrs away):
   - If `SOC < peak_buffer_target` AND `not _arbitrage_completed_in_session`: charge from grid; `reserve_level = peak_buffer_target` (refill for tomorrow's peak)
   - Else: hold at peak_buffer_target via reserve_level (don't drain — tomorrow's peak is closer than another off-peak refill opportunity)

When in mid_peak / peak: existing logic (discharge to reserve_soc) — unchanged.

### Session lock

`self._arbitrage_completed_in_session: bool` — prevents oscillation. Set True when SOC reaches `peak_buffer_target` during charging. Reset False on TOU transition INTO off-peak (handled by `_tou.check_period_transition()`). One arbitrage cycle per off-peak window.

### Pre/post-peak detection

Helper `_is_pre_peak_off_peak(now) -> bool` uses `_tou.get_next_transition(now)`:
- True if next transition is to `"peak"` or `"mid_peak"` AND happens later TODAY (not wrapped to tomorrow).
- False if no peak/mid-peak ahead today (we're in post-peak off-peak window).

### Reserve level writes (continuous control)

URA already writes `number.enpower_*_reserve_battery_level` every decision tick (5 min). The new strategy just changes WHAT value gets written based on the rule above. No new control mechanism needed; reuses existing reserve-write infrastructure.

## Deliverables

### D1 — Arbitrage path implementation

**File:** `domain_coordinators/energy_battery.py`

New instance state:
```python
self._arbitrage_completed_in_session: bool = False
self._peak_buffer_target: int = 80
self._pre_peak_hold_enabled: bool = True
```

New methods:
- `_is_pre_peak_off_peak(now) -> bool`
- `_get_arbitrage_decision(soc, now, tomorrow_class) -> dict` — returns the action dict for the arbitrage path

Updates `determine_mode()`:
- New branch in off-peak path: if `arbitrage_enabled AND tomorrow_class in (poor, very_poor)`, route to arbitrage decision.
- Reset `_arbitrage_completed_in_session = False` when `_tou.check_period_transition()` returns `"off_peak"`.
- Set `_arbitrage_completed_in_session = True` when SOC first reaches `peak_buffer_target` during charging.

**Removed**: the v3.11.0 Phase B logic (arbitrage_trigger gate). Replaced wholesale by the new path. No `arbitrage_trigger` field on `BatteryStrategy` anymore.

#### Acceptance criteria
- **Verify**: arbitrage_enabled + tomorrow=poor + pre-peak off-peak + SOC=30: charges to peak_buffer_target=80
- **Verify**: arbitrage_enabled + tomorrow=poor + pre-peak off-peak + SOC=80 (already at target): holds at 80 (reserve = 80)
- **Verify**: arbitrage_enabled + tomorrow=excellent: falls through to drain_target_excellent=10 path
- **Verify**: arbitrage_disabled + tomorrow=poor: falls through to drain_target_poor=30 path
- **Verify**: pre-peak hold doesn't prevent solar charging above 80 (Enphase reserve = floor, not ceiling)
- **Verify**: session lock holds across midnight (continuous off-peak in shoulder); resets at next TOU transition into off-peak
- **Test**: `test_arbitrage_pre_peak_charge_then_hold_then_discharge_at_peak`
- **Test**: `test_session_lock_prevents_oscillation`
- **Test**: `test_session_lock_resets_on_off_peak_entry`
- **Test**: `test_post_peak_off_peak_refills_when_below_target`
- **Test**: `test_arbitrage_disabled_uses_drain_targets`
- **Test**: `test_arbitrage_enabled_excellent_uses_drain_target_not_arbitrage`
- **Live**: with arbitrage_enabled + tomorrow=poor: SOC rises from current value toward peak_buffer_target; holds through morning; discharges at peak

### D2 — Remove `arbitrage_trigger`; rename `arbitrage_target` → `peak_buffer_target`

**Files:** `domain_coordinators/energy_const.py`, `number.py`, `config_flow.py`, `strings.json`

**Removed**:
- `DEFAULT_ARBITRAGE_SOC_TRIGGER` constant
- `CONF_ENERGY_ARBITRAGE_SOC_TRIGGER` config key
- `ArbitrageSOCNumber` instance with role="trigger" (the v4.3.0 D2 slider)
- `EnergyCoordinator.set_arbitrage_trigger()` method
- `BatteryStrategy._arbitrage_trigger` field
- All references in tests
- Strings file entries for the trigger slider

**Renamed**:
- `DEFAULT_ARBITRAGE_SOC_TARGET` → `DEFAULT_PEAK_BUFFER_TARGET`
- `CONF_ENERGY_ARBITRAGE_SOC_TARGET` → `CONF_ENERGY_PEAK_BUFFER_TARGET`
- `ArbitrageSOCNumber(role="target")` → `PeakBufferTargetNumber` (or rename existing class with role removed)
- `EnergyCoordinator.set_arbitrage_target()` → `EnergyCoordinator.set_peak_buffer_target()`
- `BatteryStrategy._arbitrage_target` → `BatteryStrategy._peak_buffer_target`
- Sensor attributes: `arbitrage_target` → `peak_buffer_target` everywhere
- Config flow field labels via strings.json
- Entity friendly name "Arbitrage SOC Target" → "Peak Buffer Target"

**Migration**: User has one install. Manually update entry options once via config flow if the auto-migration doesn't carry the old key value. Add a small one-time `_migrate_arbitrage_target_to_peak_buffer()` helper at startup that reads `entry.options[CONF_ENERGY_ARBITRAGE_SOC_TARGET]` and writes `entry.options[CONF_ENERGY_PEAK_BUFFER_TARGET]`, then clears the old key. Single-user-friendly migration; ~15 LoC.

#### Acceptance criteria
- **Verify**: `grep arbitrage_trigger` returns zero hits in production code
- **Verify**: `grep arbitrage_target` returns zero hits (renamed everywhere)
- **Verify**: existing user's saved value carries over to new key on first startup post-deploy
- **Test**: `test_migration_arbitrage_target_to_peak_buffer_target`
- **Test**: `test_no_arbitrage_trigger_references_remain`
- **Live**: post-deploy, EC device card shows "Peak Buffer Target" slider; "Arbitrage SOC Trigger" slider gone

### D3 — Multi-day Solcast forecast lookback (D+2 awareness)

**Files:** `domain_coordinators/energy_const.py`, `domain_coordinators/energy_battery.py`

This is the work originally planned as v4.3.3 (now superseded — `docs/planning/PLANNING_v4.3.3_multi_day_solcast_lookback.md` marked obsolete).

**New constant + auto-derive:**
```python
DEFAULT_SOLCAST_DAY_3_ENTITY: Final = "sensor.solcast_pv_forecast_forecast_day_3"
CONF_ENERGY_SOLCAST_DAY_3_ENTITY: Final = "energy_solcast_day_3_entity"
```

(Solcast `forecast_day_3` = D+2 because Solcast's day-numbering is 1-indexed including today.)

**New method on `BatteryStrategy`:**
- `classify_solar_day_n(days_ahead: int) -> str` — uses per-month percentile thresholds with the *target day's* month (handles cross-month-boundary forecasts correctly).

**Arbitrage gating extension:**
- Base gate: `tomorrow_class in ("poor", "very_poor")`
- Multi-day gate: `tomorrow_class in BAD OR d2_class in BAD` (where `BAD = ("poor", "very_poor")`)
- Toggleable via new `multi_day_horizon_enabled` config (default False; opt in after observing baseline)

**Drain rule when `arbitrage_enabled = False`:**
- `effective_drain_target = max(_get_offpeak_drain_target(tomorrow_class), _get_offpeak_drain_target(d2_class))` — pick the more conservative (higher) value.

#### Acceptance criteria
- **Verify**: arbitrage_enabled + tomorrow=good + d2=poor + multi_day_horizon=on: arbitrage fires
- **Verify**: arbitrage_enabled + tomorrow=good + d2=excellent + multi_day_horizon=on: arbitrage doesn't fire
- **Verify**: arbitrage_disabled + tomorrow=excellent + d2=poor + multi_day_horizon=on: drain target = drain_poor
- **Test**: `test_classify_day_n_uses_target_day_month` (cross-month test)
- **Test**: `test_multi_day_arbitrage_fires_on_d2_alone`
- **Test**: `test_d2_unknown_falls_back_to_d1_only`
- **Test**: `test_25_combination_d1_x_d2_matrix` — exhaustive (5×5 forecast classes)
- **Live**: 14-day calibration cycle observes ≥3 decisions where multi-day rule diverged from single-day

### D4 — Charge rate cap (saw-tooth control)

**File:** `domain_coordinators/energy_battery.py`

Problem: Enphase doesn't expose a grid-charge-rate limit on this user's firmware. Without intervention, arbitrage can pull 20 kW from the grid in bursts, risking demand-charge spikes and panel breaker trips.

**Approach: saw-tooth control** — when arbitrage is charging AND grid_import exceeds threshold, briefly turn off `charge_from_grid`. Resume when import drops below threshold − hysteresis.

**New config:** `CONF_ENERGY_ARBITRAGE_MAX_GRID_KW: Final = "energy_arbitrage_max_grid_kw"`. Default `8.0` (kW). Range 2–20. Slider in EC Configuration section.

**Logic addition in arbitrage charging path:**
```python
if charging_active:
    grid_import_kw = self._battery.battery_power_w / 1000.0  # via v4.3.4 helper
    if grid_import_kw > arbitrage_max_grid_kw:
        # Pause arbitrage — turn off charge_from_grid
        self._arbitrage_paused_for_rate = True
        return self._result(..., charge_from_grid=False, reserve_level=current_SOC, ...)
    elif (grid_import_kw < arbitrage_max_grid_kw - HYSTERESIS_KW
          and self._arbitrage_paused_for_rate):
        self._arbitrage_paused_for_rate = False
        # Resume arbitrage on next decision tick
```

`HYSTERESIS_KW = 0.5` to avoid thrashing.

#### Acceptance criteria
- **Verify**: with rate cap = 8 kW and arbitrage charging at 20 kW: charge_from_grid pauses within 1 decision tick
- **Verify**: when grid_import drops below 7.5 kW (cap − hysteresis): charge_from_grid resumes
- **Verify**: arbitrage eventually completes (SOC reaches target) — saw-tooth doesn't prevent completion
- **Test**: `test_rate_cap_pauses_arbitrage_when_exceeded`
- **Test**: `test_rate_cap_resumes_with_hysteresis`
- **Test**: `test_rate_cap_does_not_block_completion`
- **Live**: monitor `sensor.envoy_*_current_net_power_consumption` during arbitrage; verify it stays ≤ cap

### D5 — Storm / EVSE / generator interaction guards

**File:** `domain_coordinators/energy_battery.py`, `domain_coordinators/energy.py`

Audit existing precedences to ensure the new arbitrage path doesn't conflict:

**Storm forecast** (`has_storm_forecast() == True`): currently routes to `BATTERY_MODE_BACKUP` with high reserve. Pre-peak hold should DEFER to storm path. Verify storm check runs BEFORE off-peak decision in `determine_mode()` (it does — line 326 vs line 391). Add explicit comment so future refactors don't reorder.

**EVSE Battery Hold** (`_apply_evse_battery_hold`): when EV is charging, captures SOC and overrides reserve_level. Could collide with pre-peak hold (which sets reserve = current SOC, possibly different from EVSE-captured SOC). EVSE hold wraps the strategy's decision, applying after — so it can lock at lower SOC than arbitrage wanted. **Acceptable**: EVSE hold's purpose is "don't let battery cover EV load," which is a stricter version of pre-peak hold's "don't drain." Not a regression.

**Generator running** (`_generator.is_running() == True`): currently no special path in `determine_mode`. If generator is running, Enphase is in backup mode and reserve_level writes don't affect output. Document the precedence.

**Grid disconnected** (`!grid_connected`): existing `BATTERY_MODE_BACKUP` short-circuit at line 312. Pre-peak hold doesn't apply; backup mode wins. Document.

#### Acceptance criteria
- **Verify**: storm forecast + tomorrow=poor + arbitrage_enabled: storm path wins; reserve = storm_reserve_level (high)
- **Verify**: EVSE hold + pre-peak hold: EVSE-hold's captured SOC wins (acceptable; documented)
- **Test**: `test_storm_overrides_pre_peak_hold`
- **Test**: `test_evse_hold_takes_precedence_over_pre_peak_hold`
- **Test**: `test_grid_disconnected_skips_arbitrage_decision`

### D6 — Sensor diagnostics + methodology refresh

**File:** `domain_coordinators/energy_battery.py:get_status()`

Update `BatteryStrategySensor` attributes:
- Remove: `arbitrage_trigger` (entity gone)
- Rename: `arbitrage_target` → `peak_buffer_target`
- Add: `pre_peak_hold_active`: bool — True when currently in pre-peak hold state
- Add: `arbitrage_completed_in_session`: bool — surfaces the lock state
- Add: `forecast_outlook` (from D3): `{d1_class, d1_kwh, d2_class, d2_kwh, horizon_enabled}`
- Add: `arbitrage_paused_for_rate`: bool — surfaces when D4 rate cap is active

Update `threshold_position` and `next_action_estimate` strings to reflect the new model.

**Methodology disclosure refresh** on `EnergyArbitrageSavings*` sensors:
- Old: "may overstate if actual solar exceeds forecast"
- New: "estimate is realistic within ±10% — pre-peak hold enforces preservation through morning until peak"

The methodology field becomes more accurate because the strategy now actually preserves the charge.

**`arbitrage_active` field semantics**:
- True during charging
- True during pre-peak hold ("we charged tonight, holding for peak")
- False otherwise

#### Acceptance criteria
- **Verify**: sensors show `peak_buffer_target` attribute (not `arbitrage_target`)
- **Verify**: `pre_peak_hold_active` is True when expected (during morning off-peak with poor forecast)
- **Verify**: methodology string updated
- **Test**: `test_get_status_includes_new_attributes`
- **Test**: `test_methodology_string_updated`

### D7 — Config-flow option additions

**File:** `config_flow.py:async_step_coordinator_energy`

Changes to the existing single-page energy form:
- Remove field: `CONF_ENERGY_ARBITRAGE_SOC_TRIGGER`
- Rename field: `CONF_ENERGY_ARBITRAGE_SOC_TARGET` → `CONF_ENERGY_PEAK_BUFFER_TARGET`
- Add fields:
  - `CONF_ENERGY_ARBITRAGE_MAX_GRID_KW` (number)
  - `CONF_ENERGY_SOLCAST_DAY_3_ENTITY` (entity selector, optional)
  - `CONF_MULTI_DAY_HORIZON_ENABLED` (boolean)
  - `CONF_PRE_PEAK_HOLD_ENABLED` (boolean, default True)

Pagination is v4.5.1's job; D7 just adds/renames within the existing form.

#### Acceptance criteria
- **Verify**: form save persists all new options
- **Verify**: existing user's `arbitrage_target` value migrates to `peak_buffer_target` on first save
- **Test**: validate-on-submit catches edge cases
- **Test**: migration test for the rename

### D8 — Visibility helpers (peak window awareness on TOU engine)

**File:** `domain_coordinators/energy_tou.py`

Add `TOURateEngine.get_today_high_rate_transitions(now) -> list[tuple[int, str]]` returning today's upcoming transitions to peak/mid_peak. Used by `_is_pre_peak_off_peak()`.

Currently `get_next_transition(now)` returns just the next single transition — fine for the binary check, but having the full day's schedule available simplifies test fixtures.

#### Acceptance criteria
- **Verify**: returns `[(14, "mid_peak"), (16, "peak"), (20, "mid_peak")]` for summer at 12:00
- **Verify**: returns `[(17, "mid_peak")]` for shoulder at 12:00
- **Verify**: returns `[]` for shoulder at 22:00 (no high-rate windows ahead today)

## Open questions

1. **Default `peak_buffer_target`** — 80 (current `arbitrage_target` default) or higher (e.g., 90 to maximize buffer)? My pick: **80** — if the user dragged the slider away from 80, that custom value carries over via the migration.

2. **`pre_peak_hold_enabled` granularity** — should it be a separate toggle from `arbitrage_enabled`? My pick: **yes, separate**. User might want arbitrage charging but not pre-peak hold (rare but conceivable for testing). Default ON.

3. **Default for `multi_day_horizon_enabled`** — OFF (calibration cycle) or ON? My pick: **OFF**. Solcast D+2 accuracy is meaningfully worse than D+1; calibrate first, then flip on after observing.

4. **Saw-tooth charge rate cap default** — 8 kW (conservative) or 10 kW? My pick: **8 kW**. Allows full Encharge 10 charge rate (~5 kW per battery × 1.6 = 8 reasonable), leaves headroom for house base load + any EVSE running concurrently.

5. **Drain `_get_offpeak_drain_target("very_poor")`** — currently falls back to `poor`. Stay or add explicit very_poor slider? My pick: **stay**. Very_poor is rare; not worth a separate slider.

6. **Treatment of `tomorrow_class = "unknown"`** — current code excludes from arbitrage gate. New code keeps that: unknown → no arbitrage; drain_target_unknown=40 (most conservative drain). Don't bet money on uncertain forecasts.

## Risks ranked

**Statistical (highest):**
1. **Over-charges on misclassified-poor days**: Solcast says "poor" but reality is good → arbitrage wasted off-peak charge that solar would have refilled for free. Mitigation: saw-tooth rate cap (D4) limits damage; pre-peak hold preserves charge through morning so peak does displace it; D6 methodology disclosure honest about the limitation.
2. **Under-discharges during peak**: peak load consumed less than expected, battery ends peak still high → no recurring problem; just minor over-buffering. Mitigation: peak_buffer_target slider lets user tune down if observed peak demand is low.

**Implementation (medium):**
3. **Session lock state at restart**: `_arbitrage_completed_in_session` doesn't persist across HA restart. Acceptable: restart is rare; over-charge cost on a fresh session is bounded.
4. **Storm/EVSE/generator precedence regressions**: new path is a new code branch; could miss an interaction. Mitigation: D5 explicit guard tests.
5. **Migration of `arbitrage_target` value**: must work cleanly on first deploy. Mitigation: explicit migration test (D7).
6. **EV battery drain protection becomes vestigial during pre-peak hold** (battery doesn't discharge, so no drain to detect). Not a bug; flag in docs.

**System (low):**
7. **Standard schema migration** — single-user; no compatibility surface beyond the install.
8. **Cycle wear** — fires arbitrage more often than current code (one per poor day vs rare). 365 cycles/year × 16 years = 6000 lifetime cycles; within battery spec. Track in v4.6.x ROI math refinement.

## Cost

| Component | Production | Test |
|---|---|---|
| D1 arbitrage path | ~150 | ~250 |
| D2 remove trigger / rename target | ~70 | ~50 |
| D3 multi-day Solcast | ~120 | ~200 |
| D4 charge rate cap | ~80 | ~100 |
| D5 interaction guards | ~50 | ~100 |
| D6 diagnostics + methodology | ~70 | ~50 |
| D7 config-flow options | ~50 | ~20 |
| D8 TOU helpers | ~30 | ~30 |
| **Total** | **~620** | **~800** |

(Actually closer to ~470 / ~520 net since D2 removes existing code rather than only adding.)

## Tier 2 Review Plan

### Review 1 (Core A): Domain logic
- Arbitrage path correctness vs Enphase semantics
- Session lock invariants (no oscillation, no double-fire)
- Pre/post-peak detection edge cases (multiple peak windows in summer; cross-month-boundary)
- D3 multi-day classification correctness (target day's month, not today's)
- D4 saw-tooth control stability (no infinite oscillation around hysteresis boundary)
- Storm/EVSE/generator interaction precedences

### Review 2 (Core B): Lifecycle / integration
- Migration of `arbitrage_target` → `peak_buffer_target` (data preservation)
- Session lock state at restart boundary (acceptable to lose; document)
- D6 sensor attribute changes (sensor backward compat with the user's automations / dashboards — they may reference `arbitrage_target`)
- D7 config-flow validation (no required-field regressions)
- Bug Class scan: #1 lifecycle, #19 untracked tasks, #28 sync update_listener

### Live validation (Review 3)
After deploy + 14-day observation cycle:
1. **D1 killer signal**: with arbitrage_enabled + tomorrow=poor + SOC<80, verify SOC rises during off-peak AND stays at peak_buffer_target through morning until peak begins.
2. **D2**: peak_buffer_target slider exists; arbitrage_trigger slider gone; existing value migrated correctly.
3. **D3**: at least 3 decision cycles in 14 days where multi-day rule diverges from single-day; reason string shows both classifications.
4. **D4**: monitor net_power during arbitrage; verify it stays ≤ cap (default 8 kW).
5. **D5**: storm forecast event during observation → verify storm path wins.
6. **D6**: `pre_peak_hold_active` attribute correctly tracks state across decision ticks.
7. **Calibration metric**: arbitrage_savings (this_cycle, total) accumulates correctly.

## Ship plan

**Single ship as v4.5.0.** All deliverables in one commit. No staged rollout, no opt-in mode — single user, no compatibility surface.

**Calibration phase**: deploy + observe for 14 days. If multi_day_horizon shows clear value, flip default ON in v4.5.1 (or by user toggling). Saw-tooth rate cap and pre-peak hold default ON from day 1 (clear improvements; no calibration needed).

## Dependencies / preconditions

- v4.3.4 (current production) — ✅ shipped
- `PLANNING_v4.3.3_multi_day_solcast_lookback.md` — superseded; folded as D3
- v4.5.1 (config flow restructure) — separate cycle; not a hard dependency for v4.5.0

## Acceptance criteria summary

The release is "done" when:
- arbitrage_enabled + tomorrow=poor + SOC<target: charges to target, holds through morning, discharges at peak
- arbitrage_enabled + tomorrow=excellent: drain_target_excellent applies (no arbitrage)
- arbitrage_disabled + any forecast: drain_target_X applies (existing behavior, unchanged)
- `peak_buffer_target` slider replaces `arbitrage_target`; user's saved value migrated correctly
- `arbitrage_trigger` slider gone; no references in code
- Multi-day Solcast (D+2) toggle adds D+2-aware decisions when enabled
- Charge rate cap saws-tooth correctly under simulated 20 kW import
- `pre_peak_hold_active`, `forecast_outlook`, `arbitrage_completed_in_session`, `arbitrage_paused_for_rate` attributes appear on BatteryStrategySensor
- All Tier 2 review CRITICAL/HIGH findings resolved; LOW findings explicitly tracked per memory `feedback_review_bug_visibility.md`
