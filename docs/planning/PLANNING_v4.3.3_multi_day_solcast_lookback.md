# PLANNING v4.3.3 — Multi-Day Solcast Forecast Lookback

> **⚠ SUPERSEDED 2026-05-06.** This work has been folded into the broader Battery Strategy v2 Overlay cycle as deliverable D3. See `PLANNING_v4.5.0_battery_strategy_v2_overlay.md` for the active spec. This document is retained as historical reference for the original design rationale and risk analysis (much of which carries over to v4.5.0 D3).
>
> **Why folded:** the multi-day forecast and the v2 strategy redesign are tightly coupled — both modulate when arbitrage fires. Shipping them in a single coherent cycle (one toggle for v2 mode, one for multi-day awareness, both off by default for calibration) is cleaner than two stacked Tier 2 cycles touching the same code paths.

**Status:** SUPERSEDED — folded into v4.5.0 D3
**Tier:** Was Feature cycle (Tier 2 — 2 reviews + live validation per CLAUDE.md)
**Predecessor:** v4.3.2 (when planned)
**Effort estimate:** Originally 1 cycle; now ~120 prod / ~200 test as part of v4.5.0

## Context

Today's `BatteryStrategy.classify_tomorrow_solar()` looks **one day ahead** (D+1 only) when picking the off-peak drain target and deciding whether to fire arbitrage. This produces correct decisions when D+1 forecast is reliable AND D+2 is similar — and bad decisions in the asymmetric cases:

- **D+1 excellent, D+2 poor**: drain to 10% tonight (drain_excellent=10) → tomorrow's sun refills → tomorrow night drain to 30% (drain_poor=30) → D+2 starts at 30%, peak hits, expensive imports we should have anticipated tonight.
- **D+1 good, D+2 very_poor**: same shape but worse.
- **D+1 poor, D+2 excellent**: drain only to 30% tonight; tomorrow's sun overproduces; arbitrage savings forecast (v4.3.0 D4) overstates actual savings because the charged kWh never gets consumed.

Solcast publishes a 7-day forecast (D+0…D+6) via the existing integration:
```
sensor.solcast_pv_forecast_forecast_today          # D+0
sensor.solcast_pv_forecast_forecast_tomorrow       # D+1
sensor.solcast_pv_forecast_forecast_day_3          # D+2
sensor.solcast_pv_forecast_forecast_day_4          # D+3
sensor.solcast_pv_forecast_forecast_day_5          # D+4
sensor.solcast_pv_forecast_forecast_day_6          # D+5
sensor.solcast_pv_forecast_forecast_day_7          # D+6
```

URA already imports D+0 and D+1. v4.3.3 adds D+2 (and architecturally allows up to D+3) and uses the multi-day outlook to drive smarter overnight strategy.

User direction (2026-05-06): "Thinking of doing this since if done correctly it will be high value." The "if done correctly" is the operative phrase — arbitrary multi-day arithmetic on increasingly-uncertain forecasts can make decisions WORSE, not better. This plan is conservative on that axis.

## Goals

1. Read Solcast's D+2 forecast and classify it on the same per-month percentile scale as D+0/D+1.
2. Make the **off-peak drain target** more conservative when D+2 is meaningfully worse than D+1 (don't drain to 10% tonight if tomorrow's sun will get burned tomorrow night).
3. Make the **arbitrage trigger** fire on horizon-aware criteria, not just D+1 (charge tonight if EITHER D+1 or D+2 is poor — we know we'll need the buffer).
4. Surface the multi-day outlook on `BatteryStrategySensor` so the user can see what the strategy considered.
5. Ship behind a toggle defaulting to **off** so existing installs aren't surprised; calibrate for 2 weeks with the toggle on before declaring v4.3.3 ready for default-on in v4.3.4.

## Non-goals (deferred)

- **Look beyond D+2** in v4.3.3. Solcast accuracy degrades sharply past D+2 (per their published accuracy band; >50% relative error at D+5+). Architecture allows extending to D+3 in a later cycle if data shows it's worthwhile.
- **Continuous drain-target curve** (drain_target as a smooth function of forecast kWh instead of 5 buckets). The discrete excellent/good/moderate/poor/very_poor classification stays. Continuous mode is its own design.
- **Solcast-accuracy-weighted blending** of D+1 vs D+2. Could weight by Solcast's `forecast_accuracy` sensor, but that sensor is `unavailable` in the user's current install. Defer until accuracy data is reliable.
- **Multi-coordinator forecast sharing** (HVAC pre-cool decisions also looking at D+2). HVAC's pre-cool is a separate coordinator-level decision; not in v4.3.3 scope.
- **Bayesian forecast-correction** (track actual production vs Solcast forecast, learn a per-month correction factor). Long-running data collection task; v4.3.x or later.
- **Storm-event detection from D+2 forecast drops**. Already covered for D+1 by `has_storm_forecast()` weather entity check; D+2 storm anticipation isn't in scope.
- **Continuous arbitrage_target adjustment** (charge to 90% if both D+1 and D+2 are poor). Discrete target from slider; not adaptive within this cycle.

## Deliverables

### D1: Foundation — D+2 entity + multi-day classification helper

**Files:** `domain_coordinators/energy_const.py`, `domain_coordinators/energy_battery.py`

**`energy_const.py`** — new constant + auto-derive:
```python
DEFAULT_SOLCAST_DAY_3_ENTITY: Final = "sensor.solcast_pv_forecast_forecast_day_3"
CONF_ENERGY_SOLCAST_DAY_3_ENTITY: Final = "energy_solcast_day_3_entity"
```

(Solcast day_3 = D+2 because Solcast's "day_3" is 1-indexed including today.)

No need to touch `extract_envoy_serial` / `derive_envoy_config` — Solcast doesn't have a serial pattern; entity is fixed-name per HA's Solcast integration. User-overrideable via config flow if their Solcast install uses non-default entity names.

**`energy_battery.py`** — new wiring + helper:
- Constructor accepts `solcast_day_3_entity` kwarg (default None — reads from `DEFAULT_SOLCAST_DAY_3_ENTITY`).
- New method `classify_solar_day_n(days_ahead: int) -> str` returns "excellent" | "good" | "moderate" | "poor" | "very_poor" | "unknown" for any horizon day. Reuses existing per-month percentile thresholds (`SOLAR_MONTHLY_THRESHOLDS`) with the *target day's* month — not today's month — so cross-month-boundary forecasts classify correctly (May 31 looking at June 2 uses June thresholds).
- `classify_tomorrow_solar()` becomes a thin wrapper calling `classify_solar_day_n(1)`. No call-site changes; API stable.

**Acceptance criteria:**
- **Verify:** `classify_solar_day_n(2)` reads from `forecast_day_3` and returns the same classification logic as `classify_tomorrow_solar()` would for that kWh value.
- **Verify:** cross-month boundary: simulate May 31 looking at June 2, returns "good" if 90 kWh ≥ June p50.
- **Test:** `test_classify_day_n_uses_target_day_month` — pin date to last day of month, assert next-month thresholds applied.
- **Test:** `test_classify_day_n_invalid_days_ahead` — `days_ahead=0` returns today's class via `classify_solar_day()`; `days_ahead=8` returns "unknown" (out of horizon).
- **Live:** `sensor.ura_energy_coordinator_battery_strategy` attribute `forecast_outlook` (D3) shows D+1 and D+2 classifications matching expected values per current Solcast readings.

### D2: Multi-day decision logic in `determine_mode()`

**File:** `domain_coordinators/energy_battery.py`

**New config option:** `energy_multi_day_horizon_enabled` (bool, default `False` for v4.3.3 calibration cycle). Surfaced as a switch in EC Configuration section.

When **disabled** (default for v4.3.3): existing single-day behavior. Identical to v4.3.2.

When **enabled**:

**Drain rule** (Phase A, off-peak):
- Compute `tomorrow_class = classify_solar_day_n(1)` and `d2_class = classify_solar_day_n(2)`
- `effective_drain_target = max(_get_offpeak_drain_target(tomorrow_class), _get_offpeak_drain_target(d2_class))`
- Use `effective_drain_target` instead of `_get_offpeak_drain_target(tomorrow_class)`
- Higher target = more conservative drain (saves more juice for the worse day)
- Reason string updated: `"Off-peak drain — SOC X% > target N% (D+1=good, D+2=poor → use poor)"`

**Arbitrage rule** (Phase B, off-peak):
- Current: `arbitrage_enabled AND soc < trigger AND tomorrow_class in ("poor", "very_poor")`
- New: `arbitrage_enabled AND soc < trigger AND (tomorrow_class in BAD OR d2_class in BAD)`
- Where `BAD = ("poor", "very_poor")`
- Same arbitrage_target (no adaptive boost — that's deferred per non-goals)
- Reason string updated: `"Off-peak arbitrage — grid charging (SOC X%, D+1=good, D+2=very_poor → fire on D+2)"`

**Edge case — D+2 unknown** (Solcast forecast unavailable for D+2): fall back to D+1-only behavior. Don't punish the user with a more-conservative default just because data is missing. Log INFO `"D+2 forecast unavailable; falling back to single-day strategy this cycle"`.

**Acceptance criteria:**
- **Verify:** with toggle ON and D+1=excellent, D+2=poor, drain_target = drain_poor (30) not drain_excellent (10).
- **Verify:** with toggle ON and D+1=poor (already triggers arbitrage), D+2=excellent, behavior unchanged from v4.3.2 (arbitrage fires on D+1 alone).
- **Verify:** with toggle ON and D+1=good, D+2=very_poor, arbitrage fires (was: no, single-day says don't).
- **Verify:** with toggle OFF, behavior is bit-for-bit identical to v4.3.2 (regression-free default).
- **Test:** `test_multi_day_drain_uses_max_when_d2_worse`
- **Test:** `test_multi_day_drain_uses_max_when_d1_worse_no_change`
- **Test:** `test_multi_day_arbitrage_fires_on_d2_alone`
- **Test:** `test_multi_day_falls_back_when_d2_unknown`
- **Test:** `test_toggle_off_matches_v4_3_2_behavior` (uses pre-v4.3.3 fixtures unchanged)
- **Live:** observe at least 3 instances over 14 days where the multi-day rule diverges from single-day. Log shows the reason-string contains both classifications.

### D3: Diagnostic surface — forecast outlook on BatteryStrategySensor

**File:** `domain_coordinators/energy_battery.py:get_status()`

Add to status dict:
```json
"forecast_outlook": {
  "d1_class": "good",
  "d1_kwh": 95.4,
  "d2_class": "poor",
  "d2_kwh": 38.2,
  "horizon_enabled": true,
  "effective_drain_target": 30,
  "effective_drain_basis": "d2"  // "d1" | "d2" | "tied"
}
```

When horizon disabled, `d2_*` fields and `effective_*` fields are still computed (so user can preview the new behavior before enabling). `effective_drain_basis` shows which day determined the drain target.

Updates `threshold_position` and `next_action_estimate` strings (D5 from v4.3.0) to mention D+2 when horizon is on.

**Acceptance criteria:**
- **Verify:** `forecast_outlook.d2_class` matches Solcast's day_3 entity in attribute readback.
- **Verify:** `effective_drain_basis` correctly identifies which day chose the drain target.
- **Test:** `test_forecast_outlook_attributes_present`.
- **Test:** `test_effective_drain_basis_d1_when_d1_more_conservative`.
- **Live:** read `sensor.ura_energy_coordinator_battery_strategy.attributes.forecast_outlook` — values populate even when toggle is off.

### D4: Config-flow toggle + slider integration

**Files:** `config_flow.py`, `switch.py` (likely the existing CM switch platform), `__init__.py` wiring.

Add `CONF_ENERGY_MULTI_DAY_HORIZON_ENABLED: Final = "energy_multi_day_horizon_enabled"` to `energy_const.py`.

Surface as a switch entity under EC device's Configuration section: `switch.ura_energy_coordinator_multi_day_horizon`. Mirrors existing toggles like `Grid Arbitrage`, `Excess Solar Charging`. Initial state from config-flow option (default False).

Toggle write → `energy.set_multi_day_horizon_enabled(bool)` → mutates `BatteryStrategy._multi_day_horizon_enabled`.

**Acceptance criteria:**
- **Verify:** toggle exists in EC device card alongside other config switches.
- **Verify:** toggle state persists across HA restart (RestoreEntity if present, else config-flow value).
- **Verify:** toggling ON immediately changes drain target on next decision tick (within 5 min).
- **Test:** `test_horizon_toggle_state_propagates_to_battery_strategy`.
- **Live:** flip toggle ON, observe reason-string change to include D+2 within 5 min.

### D5: Tests + simulation

**Files:** `quality/tests/test_energy_battery.py`, possibly a new `test_multi_day_horizon.py`

New test class `TestMultiDayHorizon`. Coverage:
- All 25 combinations of (D+1 class × D+2 class) → asserts correct effective_drain_target and arbitrage_active.
- D+2 unknown fallback cases.
- Toggle off vs on regression check.
- Cross-month classification (D+2 in June while running on May 31).

No new harness fixtures required — extend `_BatteryHarness` to optionally set a D+2 forecast value, defaulting to "match D+1 = no behavior delta."

**Acceptance criteria:**
- **Verify:** 25-combination matrix test passes.
- **Verify:** existing 60 battery tests still pass (no regression with toggle off).
- **Live:** post-deploy with toggle on, watch logs for at least one decision cycle that emits a D+2-aware reason string.

### D6 (optional, defer if scope creeps): Forecast-vs-actual logging

Track each decision's `(d1_class, d2_class, effective_drain_target, arbitrage_active)` and the next day's actual production. Persist to a small DB table `solcast_decision_log` (timestamp, d1_class, d2_class, ...) for future Bayesian correction work in v4.4.x or later. Not strictly needed for v4.3.3 to ship — only enables retrospective analysis.

**Recommendation: ship D1–D5, defer D6** unless live validation calibration cycle reveals a need for it.

## Open questions for the user

1. **Horizon depth in v4.3.3**: 2 days (just D+2) or include D+3 (Solcast `forecast_day_4`)? My recommendation: **2 days only** for the calibration cycle. Adding D+3 doubles the combinatorial test surface and Solcast accuracy past D+2 is shakier.

2. **Default toggle state**: ship `multi_day_horizon_enabled = False` initially (calibration cycle), then v4.3.4 flips default to True after validation? Or default-on in v4.3.3? My recommendation: **default off for v4.3.3**, default on in v4.3.4 (or v4.3.5 if calibration is rough). Mirrors the v4.5.0 B7 silent-mode pattern.

3. **Drain rule strictness**: `max(d1_target, d2_target)` (always pick the more conservative day) or weighted (`0.7 × d1 + 0.3 × d2` with rounding)? My recommendation: **max**. Weighted blending with arbitrary coefficients invites tuning hell; max is interpretable and correct for the user's actual concern (don't run out of juice on D+2 because we drained for D+1).

4. **Arbitrage rule strictness**: fire if ANY day in horizon is poor (more aggressive — over-charges in mixed-forecast cases) or only when **both** are poor (more conservative — under-charges)? My recommendation: **either**. Symmetric with the drain rule (which uses max — i.e., the worse of the two days). If D+2 is poor, we want the buffer.

5. **Cross-month classification**: when D+2 falls in next month (e.g., May 31 looking at June 2), use D+2's month thresholds (cleaner) or today's month (simpler)? My recommendation: **D+2's month** — already proposed in D1. Negligible code cost; correct semantics.

6. **Scope creep watch**: should the D+2 entity be a config-flow option (user-overrideable) or hardcoded? My recommendation: **config-flow optional** — auto-derive from default name (`sensor.solcast_pv_forecast_forecast_day_3`), but allow override for users with non-standard Solcast setups.

## Risks ranked

**Statistical (highest):**
1. **Over-trust in D+2 forecast**: Solcast accuracy at D+2 is noticeably worse than D+1 (varies seasonally; their per-day accuracy bands quantify it). If D+2 forecast says "poor" but actual is "moderate," we've over-charged via arbitrage. Mitigation: **calibration cycle** (toggle-off default for 2 weeks) + log per-decision basis so we can post-mortem.
2. **Cascade effect**: a wrong D+2 call doesn't just affect tonight — it shifts SOC trajectory through tomorrow. Mitigation: keep the rule simple (max-of-two), no compounding.

**Implementation (medium):**
3. Cross-month classification edge case (e.g., DST, leap year). Mitigation: use `dt_util` consistently; test both transitions explicitly.
4. Toggle wiring race during entry reload. Same shape as v4.3.0 D2 sliders. Mitigation: same dispatcher-based deferred-push pattern.
5. Bug Class #19 (untracked tasks): if the toggle write triggers async reload, ensure background task is named.

**System (low):**
6. Standard regression risk on the existing v4.3.2 tests. Mitigation: toggle-off default = bit-for-bit identical behavior; existing tests pass without changes.

## Cost

| Component | Production | Test |
|---|---|---|
| D1 — D+2 wiring + `classify_solar_day_n` helper | ~50 | ~80 |
| D2 — Multi-day decision logic + reason strings | ~80 | ~150 |
| D3 — `forecast_outlook` diagnostic dict | ~40 | ~30 |
| D4 — Config-flow toggle + switch entity wiring | ~80 | ~40 |
| D5 — 25-combination test matrix + cross-month tests | — | ~200 |
| D6 — Decision logging (optional, deferred) | (~80) | (~40) |
| **Total (D1–D5 only)** | **~250** | **~500** |

Heavier on tests than production code — appropriate for a strategy logic change with combinatorial behavior.

## Tier 2 Review Plan

### Review 1 (Core A): Domain logic
- Multi-day classification correctness (per-month thresholds, target-day's month not today's)
- Drain rule semantics (max-of-two correctness)
- Arbitrage rule asymmetry (fire on EITHER bad day; verify no double-fire)
- Edge cases: D+2 unknown, both unknown, toggle off, cross-month, leap year
- Solcast accuracy disclosure: are we honest about the optimism? (mirrors v4.3.0 M9-C disclosure pattern)

### Review 2 (Core B): Lifecycle / integration
- Config-flow toggle persistence across entry reload (mirror v4.3.2 fix)
- Switch entity wiring follows existing pattern (Bug Class #28 — async update_listener)
- Background tasks for any reload triggered by toggle (Bug Class #19)
- Decision-tick budget impact (one extra entity read per cycle — negligible)
- Cross-coordinator: HVAC's solar-banking already gated on `_envoy_validation_ok`; D+2 doesn't change HVAC behavior

### Live validation (Review 3)
After deploy + 14-day calibration cycle with toggle on:
1. Daily log scrape: count decision cycles where multi-day rule diverged from single-day (target: at least 3 over 14 days, indicating the feature is doing something)
2. Verify zero "D+2 forecast unavailable" log lines outside of Solcast's known refresh windows
3. Compare arbitrage_savings_today across the calibration period vs the 14-day baseline before — is the multi-day rule producing better savings or worse? If meaningfully worse, REVERT and investigate.
4. User satisfaction signal: did the user observe correct behavior on a known-good asymmetric forecast pair (e.g., looking at the weather forecast and the drain target chose accordingly)?

## Ship plan

**Single ship as v4.3.3.** D1–D5 in one commit. D6 deferred unless calibration finds a need.

**Calibration phase**: ship with toggle default OFF. User flips toggle ON. Run 14 days. If the validation criteria above pass, v4.3.4 (or any subsequent) flips the default to ON.

**Rollback path**: if calibration shows worse savings or wrong decisions, flip the toggle OFF in their install (no code revert needed) and file a hotfix to fix the rule.

## Dependencies / preconditions

- Solcast integration installed and reporting `forecast_day_3` (verified in user's install — current value `63.7279` in May)
- v4.3.2 — ✅ shipped (this is the predecessor)
- v4.5.0 anomaly reconciliation — **NOT a dependency**; multi-day Solcast doesn't emit anomaly events

## Out of scope (future cycles)

- **D+3 lookback** (Solcast `forecast_day_4`) — extend horizon once D+2 calibration proves out
- **Continuous drain-target curve** — replace 5-bucket discrete classifier with smooth function
- **Bayesian forecast correction** — track forecast vs actual, learn per-month bias factor
- **Solcast accuracy weighting** — when Solcast's `forecast_accuracy` sensor is reliable, weight blends instead of `max`
- **HVAC pre-cool D+2 awareness** — current HVAC predictor only considers tomorrow; horizon-aware pre-cool is its own coordinator-level cycle
- **Storm event anticipation from D+2 forecast drops** — current `has_storm_forecast()` is D+0 only

## Acceptance criteria summary

The release is "done" when:
- `forecast_outlook` attribute on BatteryStrategySensor populates with both D+1 and D+2 classifications post-deploy
- Toggle exists, defaults to OFF, persists across reload
- 25-combination test matrix passes
- Toggle-OFF behavior is bit-for-bit identical to v4.3.2
- Toggle-ON: at least 3 decision cycles in 14 days where multi-day rule diverges from single-day, with reason-string showing both classifications
- Calibration period shows arbitrage_savings_today not meaningfully worse (within ±10% of v4.3.2 baseline) before flipping default ON in v4.3.4
