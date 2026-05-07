# PLANNING v4.5.0 — Battery Strategy Redesign

**Status:** Planned, not started
**Tier:** Feature cycle (Tier 2 — 2 reviews + live validation per CLAUDE.md)
**Predecessors:** v4.3.4 (production), `PLANNING_v4.3.3_multi_day_solcast_lookback.md` (superseded — folded as D3)
**Effort estimate:** 1 cycle (~520 prod / ~580 test LoC)

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

## Frame: cost-minimization nexus (EC)

The Energy Coordinator (EC) is the central decision-maker for every controllable load: battery charge/discharge, EV charging, and — once v4.7.x B5 lands — discretionary appliances (LG ThinQ, Rainbird, etc.). The single objective is **minimize total energy cost over time** subject to comfort, safety, and forecast-confidence constraints.

This frame matters because it dictates how new capabilities plug in:

- **v4.5.0 (this cycle)** — battery + EV coordination via TOU + Solcast forecast. Adds the "load coordination policy" pattern via D4 mutual-exclusion (battery grid-charge pauses EV).
- **v4.6.0 (Routine Awareness)** — anomaly reconciliation + per-room presence/routine signals feed EC for predictive load shaping.
- **v4.6.x (advanced topics, deferred)** — Bayesian-derived `peak_buffer_target`; charge-rate control via `barneyonline/ha-enphase-energy` HACS (see "Advanced topics" section); solar-aware partial top-up.
- **v4.7.x (B5 Appliance Scheduler)** — extends D4's load coordination pattern to dishwasher/dryer/oven/irrigation. Plug into the same EC decision tick. The mutual-exclusion set on `EVChargerController` becomes one of several "paused-by-policy" sets; appliances will get the analog.
- **v5.0** — config subentries + architectural debt cleanup; no behavior change.

For v4.5.0 specifically: D4 introduces the pattern (`_paused_by_arbitrage` set + paused-by-reason precedence rules). v4.7.x will copy that shape onto each appliance controller. Designing it right now means B5 has a clean integration point.

## Goals

1. Fix the arbitrage waste problem: charged energy must be preserved through the off-peak window until it actually displaces the next high-rate import window.
2. **Charge with adequate safety margin within off-peak, biased earlier on same-day target windows** — schedule grid-charging so the buffer is locked in well before the next high-rate window. When the target window is same-day (e.g., summer noon target 16:00 peak), start as soon as morning intraday solar telemetry confirms the forecast (~early morning), not at the off-peak entry the night before. Earlier start = safety margin against charge stalls and full intraday-telemetry confirmation; only delay when forecast freshness genuinely demands it (rare).
3. Eliminate the boundary collision between drain targets and arbitrage trigger by removing `arbitrage_trigger` entirely. The arbitrage gate becomes forecast class only.
4. Reduce user-surface complexity: remove the `arbitrage_trigger` slider; rename `arbitrage_target` to `peak_buffer_target` (clearer naming).
5. Add multi-day forecast awareness so D+2 forecasts can modulate when to fire arbitrage.
6. Prevent compound-load grid spikes: when battery is grid-charging at hardware rate (~20 kW), don't let an EVSE simultaneously pull additional grid load. Establish the load-coordination pattern that B5 (v4.7.x) will extend to appliances.
7. Surface enough diagnostic state that the user can see *why* the strategy made each decision and what phase it's in.

## Non-goals (deferred)

- **Removing drain targets entirely.** They remain as the fallback when arbitrage is disabled. Drop only `arbitrage_trigger`.
- **Config flow restructure** (paginated, rate-plan top-level toggle, net-metering branch). Folded out to v4.5.1 to keep v4.5.0 review surface manageable.
- **Per-EVSE drain protection thresholds** (one threshold for all EVSEs).
- **Generator-aware battery strategy** (treats generator presence as another power source). Future.
- **Appliance load coordination** (LG ThinQ, Rainbird) — v4.7.x B5. v4.5.0 establishes the pattern (D4) that B5 will copy.
- **Advanced energy-cost optimization topics** — Bayesian `peak_buffer_target`, charge-rate control via barneyonline HACS, solar-aware partial top-up, cycle-wear amortization in ROI math, season-variable buffer. See "Advanced topics — deferred to v4.6.x" section below for the consolidated list and rationale.

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

### State matrix — which path runs when (CRITICAL — read before implementing)

The two-axis matrix below is the authoritative reference for `determine_mode()` routing. Implementation MUST preserve every row exactly. The drain-target path is **unchanged from v4.3.4** for every row marked "(existing)" — those rows are NOT touched in v4.5.0 except via the rename of `arbitrage_target` → `peak_buffer_target` (which doesn't affect drain logic).

| `arbitrage_enabled` | `tomorrow_class` | TOU period | Path | Reserve floor | Notes |
|---|---|---|---|---|---|
| **False** | poor / very_poor | off_peak | drain-target (existing) | `drain_target_poor` (30) | "Poor hold" — battery refuses to discharge below 30% during off-peak. Identical to v4.3.4. |
| **False** | excellent | off_peak | drain-target (existing) | `drain_target_excellent` (10) | Existing v4.3.4 behavior. |
| **False** | good | off_peak | drain-target (existing) | `drain_target_good` (15) | Existing v4.3.4 behavior. |
| **False** | moderate | off_peak | drain-target (existing) | `drain_target_moderate` (20) | Existing v4.3.4 behavior. |
| **False** | unknown | off_peak | drain-target (existing) | `drain_target_unknown` (40) | Most conservative fallback; existing v4.3.4 behavior. |
| **True** | poor / very_poor | off_peak, charge window closed, SOC < target | **arbitrage WAIT** | `reserve_soc` (10) | New: no artificial drain floor; battery serves loads normally. SOC drifts. |
| **True** | poor / very_poor | off_peak, charge window open, SOC < target, forecast confirms | **arbitrage CHARGE** | `peak_buffer_target` (80) | New: grid charge ON; D4 EV mutual-exclusion engages. |
| **True** | poor / very_poor | off_peak, charge window open, SOC < target, forecast re-check IMPROVED | **arbitrage WAIT (locked)** | `reserve_soc` (10) | New: chunk lock fires (no charge), stays in WAIT for rest of chunk. |
| **True** | poor / very_poor | off_peak, SOC ≥ target | **arbitrage HOLD** | `peak_buffer_target` (80) | New: locks battery at target; preserves buffer for upcoming high-rate window. Reached via CHARGE, solar overfill, or starting SOC. |
| **True** | excellent / good / moderate / unknown | off_peak | drain-target (existing) | `drain_target_<class>` | Arbitrage gate doesn't fire on these classes; existing v4.3.4 behavior. |
| any | any | mid_peak / peak | DISCHARGE (existing) | `reserve_soc` (10) | Existing v4.3.4 discharge behavior. Battery serves loads, displacing imports. |
| any | any | grid disconnected (outage) | BACKUP (existing) | high reserve | Existing v4.3.4 short-circuit at line 312. Arbitrage phases don't apply. |
| any | any | storm forecast | BACKUP (existing) | storm reserve | Existing v4.3.4 storm path runs BEFORE off-peak decision (line 326 vs 391). Arbitrage phases don't apply. |

**Key invariants the implementation must preserve:**

1. When `arbitrage_enabled=False`, the v4.3.4 drain-target behavior is byte-for-byte preserved. The "poor hold" (drain_target_poor=30) is the user's only protection in this state — it must continue to work exactly as before.
2. The arbitrage path NEVER fires when `arbitrage_enabled=False`, regardless of forecast.
3. The arbitrage path NEVER fires when `tomorrow_class` is excellent / good / moderate / unknown — only on poor/very_poor (or D+2 equivalent if multi-day enabled).
4. HOLD requires `arbitrage_enabled=True AND poor/very_poor AND off_peak AND SOC ≥ peak_buffer_target`. If any of those is false, HOLD does not apply.
5. WAIT and HOLD are mutually exclusive within a tick — the one whose condition is met wins. CHARGE supersedes both when its conditions are met.
6. Storm and outage paths run BEFORE the arbitrage gate; they short-circuit any arbitrage phase decision.

**Phase predicate cheat sheet (for implementing `_get_arbitrage_phase`):**

```python
# Pre-conditions (must all be true to even consider arbitrage phases):
gate = (arbitrage_enabled
        AND tomorrow_class in ("poor", "very_poor")  # or D+2 equivalent
        AND tou_period == "off_peak"
        AND not storm_forecast
        AND grid_connected)

if not gate:
    return "n/a"  # fall through to drain-target path or existing override

# Phase resolution (order matters — first match wins):
if soc >= peak_buffer_target:
    return "hold"
if charge_window_open AND not chunk_completed AND forecast_recheck_still_poor:
    return "charge"
return "wait"
```

### Arbitrage path: four-phase state machine

When the rule fires AND we're in an off-peak chunk that ends in a high-rate window (mid-peak or peak):

| Phase | When | Reserve level | Charge from grid | Notes |
|---|---|---|---|---|
| **WAIT** | Off-peak, before charge window opens | `reserve_soc` (safety floor only) | OFF | Battery serves house loads naturally; SOC drifts based on solar/loads. No artificial drain target. |
| **CHARGE** | Off-peak, charge window open, SOC < target, forecast still poor | `peak_buffer_target` | ON | Grid charges battery up to target. EV mutual-exclusion (D4) engages. |
| **HOLD** | Off-peak, SOC ≥ target, before next high-rate transition | `peak_buffer_target` | OFF | Lock SOC at or above target so the buffer is intact when high-rate window begins. Solar can still charge above target (Enphase reserve = floor). |
| **DISCHARGE** | mid_peak / peak | `reserve_soc` | OFF | Existing logic — battery serves loads, displacing high-rate imports. |

**Charge window timing:**
```
charge_start_time = next_high_rate_transition - arbitrage_charge_lead_time_min
```
Default `arbitrage_charge_lead_time_min = 360` (6 hours). Rationale: full charge from `reserve_soc=10%` to `peak_buffer_target=80%` ≈ 25 kWh / 20 kW grid rate ÷ 0.9 RTE ≈ 1.4 h. With a 6 h lead time, charge completes ~4.5 h before the high-rate window — a generous safety margin against Enphase stalls, breaker hiccups, or unexpectedly slow charge ramps. For same-day target windows (the common case in summer and winter-evening) this also means charging fires once a few hours of morning intraday solar telemetry has confirmed the forecast, not the night before based on Solcast alone. The lead_time is configurable via D7 slider (range 60–720); shorter values lean on freshest-forecast at the cost of safety margin.

Concrete examples (PEC summer, peak 16:00-20:00, off-peak 21:00-14:00):
- 21:00 yesterday → enter off-peak, tomorrow=poor → **WAIT** phase begins
- ~06:00 today → sunrise; intraday Solcast updates begin
- 08:00 today → charge window opens (= 14:00 - 6h); re-evaluate Solcast (now informed by 2 h of actual production data); if still poor → **CHARGE**
- ~09:30 today → SOC reaches 80% → **HOLD**
- 09:30 - 14:00 → HOLD locks buffer at 80% (~4.5 h)
- 14:00 today → off-peak ends, mid-peak begins → **DISCHARGE** (existing logic)
- 16:00-20:00 → peak; battery continues discharging
- 21:00 today → off-peak begins again; chunk lock resets

PEC winter has two high-rate windows per day (05:00-09:00 morning + 17:00-21:00 evening), so v4.5.0 may run two charge cycles/day in winter. Note: the morning window (05:00) target is "cross-day" — at 23:00 - 6h = 23:00, charge fires before sunrise, so no intraday telemetry advantage. Forecast freshness is whatever Solcast last refreshed overnight. Acceptable for cycle wear (battery spec >6000 cycles); flag in risks. v4.6.x Bayesian-derived sizing will choose to skip the smaller window if not worth it.

**Forecast re-check on charge entry**: at the moment the WAIT→CHARGE transition fires, re-call `classify_solar_day(d=1)` (and D+2 if multi-day enabled). For same-day targets, this call also benefits from intraday solar telemetry already accumulated since sunrise. If the class is no longer "poor"/"very_poor", abort the charge cycle, mark chunk as completed (lock prevents retry), and stay in WAIT until the chunk ends. The earlier-by-default lead time means we re-check earlier, but with intraday data already informing the call.

### Per-chunk lock

`self._arbitrage_chunk_completed: bool` — one arbitrage cycle per off-peak chunk. Set True when:
- SOC reaches `peak_buffer_target` during CHARGE, OR
- Charge window opens but forecast re-check says class is no longer poor (we abort cleanly).

Reset False on TOU transition INTO off-peak (handled by `_tou.check_period_transition()`). Prevents oscillation if SOC drifts post-completion or forecast wobbles.

### High-rate-transition detection

Helper `_tou.get_next_high_rate_transition(now) -> tuple[datetime, str] | None`:
- Returns `(transition_dt, period_name)` for the next time the period leaves "off_peak" (i.e., enters "mid_peak" or "peak"), looking up to 36 hours ahead.
- Returns `None` if no high-rate window in the lookback window (rare).

This subsumes the previous "pre-peak / post-peak off-peak" distinction. The new model is uniformly "next high-rate transition" — works the same in summer, shoulder, winter; works across midnight; works for both peak and mid-peak targets.

### Reserve level writes (continuous control)

URA already writes `number.enpower_*_reserve_battery_level` every decision tick (5 min). The new strategy just changes WHAT value gets written based on the rule above. No new control mechanism needed; reuses existing reserve-write infrastructure.

## Deliverables

### D1 — Arbitrage path implementation (four-phase state machine)

**File:** `domain_coordinators/energy_battery.py`

New instance state:
```python
self._arbitrage_chunk_completed: bool = False    # per-chunk lock (replaces session lock)
self._peak_buffer_target: int = 80
self._hold_phase_enabled: bool = True
self._arbitrage_charge_lead_time_min: int = 360   # configurable; bias earlier for safety + same-day intraday confirmation
self._arbitrage_phase: str = "wait"               # "wait" | "charge" | "hold" | "discharge" | "n/a"
```

New methods:
- `_get_arbitrage_phase(soc, now, tomorrow_class, d2_class) -> str` — returns one of `"wait"`, `"charge"`, `"hold"`, or `"n/a"` (off-peak phases only; mid_peak/peak handled by existing discharge logic). Returns `"n/a"` when arbitrage gate doesn't fire.
- `_is_charge_window_open(now) -> bool` — `True` when `(next_high_rate_transition - now) <= lead_time_min`. Uses `_tou.get_next_high_rate_transition()`.
- `_recheck_forecast_on_charge_entry() -> bool` — re-pulls Solcast on first entry to CHARGE phase; returns True if forecast still warrants the charge. False → abort, set chunk lock, fall back to WAIT.
- `_get_arbitrage_decision(soc, now, tomorrow_class, d2_class) -> dict` — wraps the phase logic, returns the action dict (reserve_level, charge_from_grid, reason, phase).

Updates `determine_mode()`:
- New branch in off-peak path: if `arbitrage_enabled AND tomorrow_class in (poor, very_poor)` (or D+2 equivalent if multi-day enabled), route to `_get_arbitrage_decision()`.
- Reset `_arbitrage_chunk_completed = False` when `_tou.check_period_transition()` returns `"off_peak"`.
- Set `_arbitrage_chunk_completed = True` when:
  - SOC first reaches `peak_buffer_target` during CHARGE, OR
  - Charge window opens but forecast re-check returns False (clean abort).
- Update `self._arbitrage_phase` on every tick for sensor exposure (D6).

**Phase-to-action mapping:**
```python
WAIT:      {"reserve_level": reserve_soc,         "charge_from_grid": False, "reason": "arbitrage WAIT — charge window not yet open"}
CHARGE:    {"reserve_level": peak_buffer_target,  "charge_from_grid": True,  "reason": f"arbitrage CHARGE — target {peak_buffer_target}%"}
HOLD:      {"reserve_level": peak_buffer_target,  "charge_from_grid": False, "reason": "arbitrage HOLD — preserving buffer for next high-rate window"}
```

**Removed**: the v3.11.0 Phase B logic (arbitrage_trigger gate). Replaced wholesale by the new path. No `arbitrage_trigger` field on `BatteryStrategy` anymore.

**Note on EV battery drain protection during HOLD/CHARGE**: battery doesn't discharge during these phases, so drain-protection signals will be quiet. Not a bug — the protection re-engages naturally during DISCHARGE. Documented in code comment.

#### Acceptance criteria
- **Verify**: arbitrage_enabled + tomorrow=poor + off-peak entry + 8h before next high-rate (outside lead_time=360): phase = WAIT, no grid charge
- **Verify**: arbitrage_enabled + tomorrow=poor + 5h before next high-rate (within lead_time=360): phase = CHARGE, grid charge ON
- **Verify**: phase transitions WAIT → CHARGE → HOLD → (DISCHARGE on TOU edge)
- **Verify**: forecast re-check on CHARGE entry: tomorrow flips to good → abort cleanly, set chunk lock, return to WAIT
- **Verify**: arbitrage_enabled + tomorrow=poor + SOC=80 already (above target) at charge window: skip CHARGE, go directly to HOLD
- **Verify**: arbitrage_enabled + tomorrow=excellent: phase = "n/a"; falls through to drain_target_excellent=10
- **Verify**: arbitrage_disabled + tomorrow=poor: phase = "n/a"; falls through to drain_target_poor=30
- **Verify**: HOLD doesn't prevent solar charging above target (Enphase reserve = floor, not ceiling)
- **Verify**: chunk lock holds across midnight in winter (cross-midnight off-peak chunks); resets only on transition INTO off-peak
- **Verify**: charge_lead_time_min user override (e.g., 120 or 600) shifts charge window correctly
- **Test**: `test_phase_wait_when_charge_window_closed`
- **Test**: `test_phase_charge_when_window_opens_and_forecast_confirms`
- **Test**: `test_phase_hold_when_target_reached`
- **Test**: `test_charge_entry_forecast_recheck_aborts_on_improvement`
- **Test**: `test_chunk_lock_prevents_oscillation`
- **Test**: `test_chunk_lock_resets_on_off_peak_entry`
- **Test**: `test_winter_two_chunks_per_day_each_charges_independently`
- **Test**: `test_arbitrage_disabled_uses_drain_targets`
- **Test**: `test_arbitrage_enabled_excellent_uses_drain_target_not_arbitrage`
- **Test**: `test_phase_summer_full_day_sequence` — fixture walks through 21:00→14:00→16:00→20:00 ticks
- **Live**: with arbitrage_enabled + tomorrow=poor: phase sensor reports WAIT through overnight, transitions to CHARGE in early morning (~08:00 summer with default lead_time=360), HOLD locked through midday, DISCHARGE at mid-peak/peak

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

### D4 — Arbitrage / EV mutual-exclusion (compound-load protection)

**Files:** `domain_coordinators/energy_pool.py`, `domain_coordinators/energy.py`

**Original D4 (saw-tooth charge rate cap) was dropped** during 2026-05-07 plan review. Reasons:

1. **It would flap.** Enphase's `charge_from_grid` is a binary switch (no rate control). When ON, battery pulls at hardware rate (~20 kW). When OFF, ~0 kW. Saw-tooth threshold sits between these two states; hysteresis can't bridge them — system toggles every 5-min decision tick.
2. **It doesn't solve the actual problem.** PEC residential plans don't have demand charges, so "average rate cap" via saw-tooth provides no cost benefit. The user's other concern — breaker tripping — requires actual peak-rate limiting, which Enphase firmware doesn't expose. Saw-tooth manages averages but instantaneous draw during ON portions is still 20 kW.

**Replacement: mutual-exclusion scheduling.** The compound-load case (battery 20 kW + EV 7.4 kW + house base 5 kW = 32 kW = 134A) is the real panel-stress scenario. Solo battery charge at 20 kW (83A) is well within main breaker capacity. **Don't run arbitrage AND EV charging simultaneously.**

**Logic** in `EnergyCoordinator._async_decision_cycle`, after `determine_mode` returns:
```python
arbitrage_charging = decision.get("arbitrage_active") and decision.get("charge_from_grid")

if arbitrage_charging:
    # Pause any running EVSEs for compound-load protection
    for evse_id, state in self._ev._evse.items():
        if state["is_on"] and evse_id not in self._ev._paused_by_arbitrage:
            self._ev._paused_by_arbitrage.add(evse_id)
            actions.append(turn off the EVSE switch)
            _LOGGER.info("EV %s paused for arbitrage compound-load protection", evse_id)
else:
    # Not charging from grid — release any EVs we paused
    for evse_id in list(self._ev._paused_by_arbitrage):
        self._ev._paused_by_arbitrage.discard(evse_id)
        # Only resume if TOU permits AND no other pause reason holds
        if (tou_period == "off_peak"
            and evse_id not in self._ev._paused_by_grid_cap
            and evse_id not in self._ev._paused_by_battery_drain
            and evse_id not in self._ev._paused_by_us):
            actions.append(turn on the EVSE switch)
            _LOGGER.info("EV %s resumed (arbitrage released)", evse_id)
```

**New `_paused_by_arbitrage` set on `EVChargerController`** mirrors the existing `_paused_by_us`, `_paused_by_grid_cap`, `_paused_by_battery_drain` patterns (proven shape). New attribute on `EnergyEVChargingStatusSensor` so user can see *why* the EV was paused.

**No new config option.** Mutual-exclusion is unconditional — there's no use case where you want simultaneous 20+7 kW draw on a normal residential panel. Add a config flag in a future cycle if needed.

#### Acceptance criteria
- **Verify**: arbitrage charging starts → all running EVSEs pause within 1 decision tick (≤5 min); `paused_by_arbitrage` attribute populates
- **Verify**: arbitrage completes (SOC reached target) → paused EVSEs resume on next tick
- **Verify**: arbitrage releases due to TOU transition (off_peak ends) → paused EVSEs resume if TOU still permits
- **Verify**: EV plugged in during ongoing arbitrage charging → does NOT start (added to `_paused_by_arbitrage` proactively)
- **Verify**: peak/mid_peak EV pause (existing TOU rule) takes priority over arbitrage release — EV stays paused if TOU forbids
- **Test**: `test_arbitrage_charging_pauses_active_evse`
- **Test**: `test_arbitrage_completion_releases_evse`
- **Test**: `test_evse_blocked_during_ongoing_arbitrage`
- **Test**: `test_resume_respects_other_pause_reasons` (grid_cap + battery_drain still hold)
- **Test**: `test_no_flap_when_arbitrage_phase_oscillates_briefly` — simulate adjacent ticks where conditions for CHARGE flicker (e.g., forecast re-check returns slightly different value, SOC reading momentarily noisy). Chunk lock must prevent EV pause/resume oscillation. EV pauses at most once per chunk; resumes at most once per chunk.
- **Live**: during overnight arbitrage cycle, observe garage_a switching off when arbitrage starts charging; back on when SOC reaches target (or off-peak ends)

**What this does NOT solve** (accepted limitation, documented):
- Solo battery 20 kW spike during arbitrage (Enphase firmware doesn't expose rate control on this install)
- Non-EVSE house loads during arbitrage (HVAC ~3 kW, oven, dryer) — not URA-controlled, so URA can't pause them. Real-world worst case: HVAC compressor cycle + battery = ~23 kW = 96A on main breaker. Safe.

### D5 — Storm / EVSE / generator interaction guards

**File:** `domain_coordinators/energy_battery.py`, `domain_coordinators/energy.py`

Audit existing precedences to ensure the new arbitrage path doesn't conflict:

**Storm forecast** (`has_storm_forecast() == True`): currently routes to `BATTERY_MODE_BACKUP` with high reserve. The arbitrage phase machine (any of WAIT/CHARGE/HOLD) should DEFER to storm path. Verify storm check runs BEFORE off-peak decision in `determine_mode()` (it does — line 326 vs line 391). Add explicit comment so future refactors don't reorder.

**EVSE Battery Hold** (`_apply_evse_battery_hold`): when EV is charging, captures SOC and overrides reserve_level. Could collide with the arbitrage HOLD phase (which sets reserve = peak_buffer_target, possibly different from EVSE-captured SOC). EVSE hold wraps the strategy's decision, applying after — so it can lock at a different SOC than arbitrage wanted. **Acceptable**: EVSE hold's purpose is "don't let battery cover EV load," which is a stricter version of HOLD's "preserve buffer." Not a regression. Note that under D4 mutual-exclusion the EV won't be charging during the CHARGE phase anyway, so this collision is mostly theoretical post-D4.

**Generator running** (`_generator.is_running() == True`): currently no special path in `determine_mode`. If generator is running, Enphase is in backup mode and reserve_level writes don't affect output. Document the precedence.

**Grid disconnected** (`!grid_connected`): existing `BATTERY_MODE_BACKUP` short-circuit at line 312. Arbitrage phases don't apply; backup mode wins. Document.

#### Acceptance criteria
- **Verify**: storm forecast + tomorrow=poor + arbitrage_enabled: storm path wins; reserve = storm_reserve_level (high)
- **Verify**: EVSE hold + arbitrage HOLD phase: EVSE-hold's captured SOC wins (acceptable; documented)
- **Test**: `test_storm_overrides_hold_phase`
- **Test**: `test_evse_hold_takes_precedence_over_hold_phase`
- **Test**: `test_grid_disconnected_skips_arbitrage_decision`

### D6 — Sensor diagnostics + methodology refresh

**File:** `domain_coordinators/energy_battery.py:get_status()`

Update `BatteryStrategySensor` attributes:
- Remove: `arbitrage_trigger` (entity gone)
- Rename: `arbitrage_target` → `peak_buffer_target`
- Add: `arbitrage_phase`: str — `"wait"` | `"charge"` | `"hold"` | `"discharge"` | `"n/a"`
- Add: `arbitrage_chunk_completed`: bool — surfaces the per-chunk lock state
- Add: `next_high_rate_transition`: ISO datetime string — when the upcoming mid-peak/peak window starts (drives the user's mental model of "when will charging happen")
- Add: `charge_window_opens_at`: ISO datetime string — `next_high_rate_transition - lead_time_min` (only non-null when arbitrage gate is open)
- Add: `forecast_outlook` (from D3): `{d1_class, d1_kwh, d2_class, d2_kwh, horizon_enabled}`
- Add: `evse_paused_by_arbitrage`: list[str] — EVSE IDs paused for compound-load protection (D4)

Update `threshold_position` and `next_action_estimate` strings to reflect the phased model. Example `next_action_estimate` strings:
- WAIT: "Holding; CHARGE begins at HH:MM (in N min)"
- CHARGE: "Grid charging to N%; ETA HH:MM"
- HOLD: "Buffer locked at N%; DISCHARGE begins at HH:MM"

**Methodology disclosure refresh** on `EnergyArbitrageSavings*` sensors:
- Old: "may overstate if actual solar exceeds forecast"
- New: "estimate is realistic within ±10% — late-charge window + forecast re-check minimizes wasted grid imports; HOLD preserves buffer until high-rate window"

The methodology field becomes more accurate because the strategy now (a) defers grid charge until close to high-rate window, (b) re-checks forecast at that point, and (c) preserves the charge until peak.

**`arbitrage_active` field semantics**:
- True during CHARGE
- True during HOLD (we charged today, holding for upcoming high-rate window)
- False during WAIT, DISCHARGE, "n/a"

#### Acceptance criteria
- **Verify**: sensors show `peak_buffer_target` attribute (not `arbitrage_target`)
- **Verify**: `arbitrage_phase` matches actual decision-cycle state
- **Verify**: `next_high_rate_transition` and `charge_window_opens_at` reflect TOU correctly
- **Verify**: methodology string updated
- **Test**: `test_get_status_includes_phase_attributes`
- **Test**: `test_charge_window_opens_at_computed_correctly`
- **Test**: `test_methodology_string_updated`

### D7 — Config-flow option additions

**File:** `config_flow.py:async_step_coordinator_energy`

Changes to the existing single-page energy form:
- Remove field: `CONF_ENERGY_ARBITRAGE_SOC_TRIGGER`
- Rename field: `CONF_ENERGY_ARBITRAGE_SOC_TARGET` → `CONF_ENERGY_PEAK_BUFFER_TARGET`
- Add fields:
  - `CONF_ENERGY_SOLCAST_DAY_3_ENTITY` (entity selector, optional)
  - `CONF_MULTI_DAY_HORIZON_ENABLED` (boolean, default False)
  - `CONF_HOLD_PHASE_ENABLED` (boolean, default True)
  - `CONF_ARBITRAGE_CHARGE_LEAD_TIME_MIN` (number, default 360, range 60-720 minutes) — minutes before next high-rate window when grid charge starts. Higher = more safety margin and (for same-day targets) more intraday solar telemetry informing the forecast re-check; lower = leans on freshest possible forecast at the cost of margin.

Pagination is v4.5.1's job; D7 just adds/renames within the existing form.

#### Acceptance criteria
- **Verify**: form save persists all new options
- **Verify**: existing user's `arbitrage_target` value migrates to `peak_buffer_target` on first save
- **Test**: validate-on-submit catches edge cases
- **Test**: migration test for the rename

### D8 — TOU helpers (high-rate transition awareness)

**File:** `domain_coordinators/energy_tou.py`

Add `TOURateEngine.get_next_high_rate_transition(now, lookback_hours=36) -> tuple[datetime, str] | None`:
- Returns `(transition_dt, period_name)` for the next time the TOU period leaves "off_peak" — i.e., enters "mid_peak" or "peak".
- Walks forward up to `lookback_hours` (default 36) to handle continuous off-peak chunks that span midnight (e.g., summer 21:00 → 14:00 next day).
- Returns `None` if no high-rate window in the lookback window (rare; e.g., extended off-peak holiday rate).

Also add `get_today_high_rate_transitions(now) -> list[tuple[int, str]]` for diagnostic display (used by sensor + tests).

#### Acceptance criteria
- **Verify**: `get_next_high_rate_transition` for summer at 12:00 today → `(today 14:00, "mid_peak")`
- **Verify**: same call for summer at 22:00 → `(tomorrow 14:00, "mid_peak")` (skips through continuous off-peak across midnight)
- **Verify**: shoulder at 14:00 → `(today 17:00, "mid_peak")`
- **Verify**: winter at 22:00 → `(tomorrow 05:00, "mid_peak")` (skips 21:00→05:00 continuous off-peak)
- **Verify**: winter at 10:00 → `(today 17:00, "mid_peak")` (after morning mid-peak ended; before evening)
- **Test**: `test_next_high_rate_transition_summer`
- **Test**: `test_next_high_rate_transition_winter_cross_midnight`
- **Test**: `test_next_high_rate_transition_returns_none_on_holiday_offpeak`

## Advanced topics — deferred to v4.6.x

These optimizations all push the cost-minimization curve further but each carries either calibration dependencies on v4.5.0's data, third-party-integration risk, or non-trivial scope. Listed here for traceability and to keep v4.5.0 review surface manageable. They will be revisited after v4.5.0 has 4-8 weeks of live data on the user's install.

| Topic | Why deferred | What it would unlock |
|---|---|---|
| **Bayesian-derived `peak_buffer_target`** (per-day-type) | Needs v4.5.0's fixed-target model + observed peak-window discharge history as the calibration baseline. Existing `BayesianPredictor` + `RoomPowerProfile` provide the substrate. | Per-day-type buffer (e.g., weekday 75%, weekend 85%, summer Sunday 90%) instead of one fixed target. Stops over-buying grid energy on lighter-load days. |
| **Charge-rate control via `barneyonline/ha-enphase-energy` HACS** | Third-party integration; needs scoped firmware test on the user's Enphase install before depending on it. If it works, **obsoletes the entire D4 mutual-exclusion design** (battery + EV could charge concurrently at controlled rates) and eliminates the 20 kW grid-spike. | Slow charge across the entire off-peak chunk (no compound-load risk ever); battery + EV concurrent charging; gentler cycle wear (lower C-rate); cleaner solar-coordination. |
| **Solar-aware partial top-up** | Needs intraday solar telemetry + better-than-Solcast same-day prediction (Bayesian engine). | Only grid-charge the gap between current SOC and the target *after* subtracting expected remaining solar production. Avoids redundant grid charge on misclassified-poor days. |
| **Intraday-confirmed dynamic lead time** | Builds on `RoomPowerProfile` + Bayesian forecast confidence model from this cycle's calibration data. | v4.5.0 ships a fixed `arbitrage_charge_lead_time_min`. Dynamic version watches morning intraday solar production vs Solcast forecast — if production is meaningfully ahead/behind the forecast, the system advances or delays CHARGE accordingly within the chunk. Tightens timing on confident-poor days; widens it on uncertain or borderline days. |
| **Cycle-wear amortization in ROI math** | Requires battery-specific wear coefficient + observed cycle-count history. | More honest arbitrage savings number — net of degradation cost rather than gross. |
| **Season-variable `peak_buffer_target`** | Bayesian path obsoletes this (per-day-type subsumes per-season). | Different buffer per season (summer 4-hour peak vs shoulder no-peak vs winter 4-hour mid-peak). |
| **Per-high-rate-window economic gate** | Bayesian engine + observed load profiles. | In winter, decide whether to charge for the smaller morning mid-peak window (05:00-09:00) vs only the larger evening one (17:00-21:00). v4.5.0 charges for both unconditionally. |
| **Arbitrage decisions integrated with appliance scheduling** | Depends on v4.7.x B5 (LG ThinQ + Rainbird integration). | Whole-home cost minimization — defer dishwasher/dryer to off-peak; align EV charge with battery charge OR with cheap solar overflow; pre-cool/heat HVAC into the high-rate window using buffer charge. |

**Reference roadmap entries**: see `MEMORY.md` index → `project_roadmap_decisions_2026_05_06.md` for the version sequencing. v4.6.0 (Routine Awareness) provides the per-room signals; v4.6.x is the umbrella for these advanced energy-cost topics; v4.7.x B5 adds appliances; ultimate goal across all of these is total energy-cost minimization.

## Open questions

1. **Default `peak_buffer_target`** — 80 (current `arbitrage_target` default) or higher (e.g., 90 to maximize buffer)? My pick: **80** — if the user dragged the slider away from 80, that custom value carries over via the migration.

2. **Default `arbitrage_charge_lead_time_min`** — 360 (6 h, my pick) vs 240 (tighter, slightly fresher forecast) vs 480 (very generous). 360 gives ~4.5 h between charge completion and high-rate window — safe margin for stalls and, for same-day target windows, ample intraday solar telemetry to inform the forecast re-check at CHARGE entry. The user has stated preference: earlier start is better when target window is same-day; freshness benefit doesn't dominate once we have intraday telemetry. v4.6.x dynamic lead-time (intraday-confirmed) will compute this adaptively per day.

3. **`hold_phase_enabled` granularity** — should it be a separate toggle from `arbitrage_enabled`? My pick: **yes, separate**. User might want arbitrage charging but not the HOLD phase (rare; useful for debug). Default ON.

4. **Default for `multi_day_horizon_enabled`** — OFF (calibration cycle) or ON? My pick: **OFF**. Solcast D+2 accuracy is meaningfully worse than D+1; calibrate first, then flip on after observing.

5. **Mutual-exclusion resume policy** — when an EVSE was paused by arbitrage, should it auto-resume the moment arbitrage completes (SOC ≥ peak_buffer_target) within the same off-peak chunk, or wait until off-peak ends? My pick: **auto-resume**. Off-peak rates still apply; no reason to leave the EV unfilled when the battery is done.

6. **Winter two-charge-per-day default** — winter has two high-rate windows (05:00-09:00 morning, 17:00-21:00 evening). v4.5.0 charges before each. Acceptable for cycle wear (~700 cycles/yr ≈ 11k lifetime cycles vs >6k spec) but cycle-wear ROI math (deferred to v4.6.x) may want to skip the smaller window. **Default ON for both windows for v4.5.0**; advanced gate is a v4.6.x topic.

7. **Drain `_get_offpeak_drain_target("very_poor")`** — currently falls back to `poor`. Stay or add explicit very_poor slider? My pick: **stay**. Very_poor is rare; not worth a separate slider.

8. **Treatment of `tomorrow_class = "unknown"`** — current code excludes from arbitrage gate. New code keeps that: unknown → no arbitrage; drain_target_unknown=40 (most conservative drain). Don't bet money on uncertain forecasts.

## Risks ranked

**Statistical (highest):**
1. **Over-charges on misclassified-poor days**: Solcast says "poor" but reality is good → arbitrage wasted off-peak charge that solar would have refilled for free. Mitigation: late-charge window + forecast re-check on CHARGE entry (D1) — by 12:00 noon (summer) we have 6+ hours of intraday solar telemetry to validate the morning forecast call. Cost ceiling per misclassified day: peak_buffer_target × battery_capacity × off_peak_rate ≈ 80% × 36 kWh × $0.043 = $1.24.
2. **Under-discharges during high-rate window**: load consumed less than expected, battery ends high-rate window still near target → no recurring problem; just minor over-buffering. Mitigation: peak_buffer_target slider lets user tune down if observed peak demand is low. v4.6.x Bayesian path solves this dynamically.

**Implementation (medium):**
3. **Charge-window timing mis-estimate**: at default lead_time=360, full charge from 10% takes ~1.4 h, leaving ~4.5 h of HOLD margin before the high-rate window. If Enphase stalls or charge rate drops, we have generous margin to recover. Mitigation: lead_time slider lets user tune; `arbitrage_phase` sensor exposes timing visually; live validation observes actual charge durations and HOLD efficacy.
4. **Chunk lock state at restart**: `_arbitrage_chunk_completed` doesn't persist across HA restart. If HA restarts mid-CHARGE or mid-HOLD, chunk lock resets and we may re-fire. Acceptable: restart is rare; cost of one extra cycle is bounded; HOLD will simply re-engage at same target.
5. **Storm/EVSE/generator precedence regressions**: new phased path is a new code branch; could miss an interaction. Mitigation: D5 explicit guard tests.
6. **Migration of `arbitrage_target` value**: must work cleanly on first deploy. Mitigation: explicit migration test (D7).
7. **EV battery drain protection becomes vestigial during HOLD** (battery doesn't discharge, so no drain to detect). Not a bug; flag in docs. Re-engages naturally during DISCHARGE.
8. **Compound-load mutual-exclusion (D4) edge cases** — multi-EV households (URA target install has only one Tesla but `EVChargerController` handles N), pause-reason precedence interactions. Pattern is the same one B5 will extend; getting it right now pays off later.

**System (low):**
9. **Schema migration** — single-user; no compatibility surface beyond the install.
10. **Cycle wear** — winter fires twice/day (morning + evening high-rate windows). Worst-case ~730 cycles/yr × 10 years = 7300 cycles, slightly over Enphase IQ Battery 10 spec of ~6000. Mitigation: v4.6.x cycle-wear ROI math + per-window economic gate will reduce this to roughly 365/yr.

## Cost

| Component | Production | Test |
|---|---|---|
| D1 arbitrage path (phased state machine) | ~200 | ~330 |
| D2 remove trigger / rename target | ~70 | ~50 |
| D3 multi-day Solcast | ~120 | ~200 |
| D4 arbitrage / EV mutual-exclusion | ~50 | ~80 |
| D5 interaction guards | ~50 | ~100 |
| D6 diagnostics + methodology | ~80 | ~60 |
| D7 config-flow options | ~60 | ~30 |
| D8 TOU helpers (next high-rate transition) | ~50 | ~50 |
| **Total gross** | **~680** | **~900** |

(Actually closer to ~520 / ~580 net since D2 removes existing code rather than only adding.)

## Tier 2 Review Plan

### Review 1 (Core A): Domain logic
- Arbitrage phase state machine correctness (WAIT → CHARGE → HOLD → DISCHARGE transitions; no spurious transitions)
- Charge-window timing arithmetic (lead-time math; cross-midnight; DST boundaries)
- Forecast re-check on CHARGE entry (idempotent; doesn't fire repeatedly within a chunk)
- Per-chunk lock invariants (no oscillation, no double-fire within a chunk; resets only on transition INTO off-peak)
- High-rate-transition detection edge cases (multiple windows/day in winter; cross-month-boundary; holiday off-peak)
- D3 multi-day classification correctness (target day's month, not today's)
- D4 mutual-exclusion correctness (paused EVSEs resume when arbitrage releases; respect other pause reasons; pattern aligns with future B5 appliance hooks)
- Storm/EVSE/generator interaction precedences

### Review 2 (Core B): Lifecycle / integration
- Migration of `arbitrage_target` → `peak_buffer_target` (data preservation)
- Chunk lock state at restart boundary (acceptable to lose; document)
- Phase persistence across HA restart (compute from current state on first tick post-restart; no stale phase)
- D6 sensor attribute changes (sensor reference compat with the user's automations / dashboards — they may reference `arbitrage_target`)
- D7 config-flow validation (no required-field regressions)
- Bug Class scan: #1 lifecycle, #19 untracked tasks, #28 sync update_listener

### Live validation (Review 3)
After deploy + 14-day observation cycle:
1. **D1 phased killer signal**: with arbitrage_enabled + tomorrow=poor + SOC<80:
   - Phase = WAIT during overnight off-peak (battery serves loads, SOC drifts down based on actual usage)
   - Phase transitions to CHARGE at expected time (6 h before next high-rate window with default lead_time=360 — in summer ≈ 08:00 today for the 14:00 mid-peak transition)
   - SOC rises to `peak_buffer_target` over ~1–1.5 h of grid charging
   - Phase = HOLD until off-peak ends (~4.5 h of HOLD in summer at default lead_time)
   - Phase = DISCHARGE during mid_peak/peak; SOC drops to `reserve_soc`
2. **D1 forecast re-check**: at least once during 14 days, observe a CHARGE-entry abort where Solcast had said "poor" overnight but intraday telemetry shows actual is "good" — chunk lock sets without grid charge fired.
3. **D2**: peak_buffer_target slider exists; arbitrage_trigger slider gone; existing value migrated correctly.
4. **D3**: at least 3 decision cycles in 14 days where multi-day rule diverges from single-day; reason string shows both classifications.
5. **D4**: during a CHARGE phase, observe `garage_a` switching off the moment phase enters CHARGE; back on when phase enters HOLD or DISCHARGE. EV sensor's `paused_by_arbitrage` attribute populates and clears correctly.
6. **D5**: storm forecast event during observation → verify storm path wins (phase = "n/a", storm reserve applied).
7. **D6**: `arbitrage_phase`, `next_high_rate_transition`, `charge_window_opens_at` attributes correctly track state across decision ticks.
8. **Calibration metric**: arbitrage_savings (this_cycle, total) accumulates correctly.

## Ship plan

**Single ship as v4.5.0.** All deliverables in one commit. No staged rollout, no opt-in mode — single user, no compatibility surface.

**Calibration phase**: deploy + observe for 14 days. If multi_day_horizon shows clear value, flip default ON in v4.5.1 (or by user toggling). Mutual-exclusion (D4) and HOLD phase default ON from day 1 (clear improvements; no calibration needed). Phased timing (D1) defaults ON; lead_time default 360 min (6 h) — observe whether this is too generous or too tight and tune in v4.5.1. The v4.6.x intraday-confirmed dynamic lead time will eventually replace the fixed value with adaptive behavior.

## Dependencies / preconditions

- v4.3.4 (current production) — ✅ shipped
- `PLANNING_v4.3.3_multi_day_solcast_lookback.md` — superseded; folded as D3
- v4.5.1 (config flow restructure) — separate cycle; not a hard dependency for v4.5.0

## Acceptance criteria summary

The release is "done" when:
- arbitrage_enabled + tomorrow=poor + SOC<target: phases through WAIT → CHARGE (late in off-peak) → HOLD → DISCHARGE; charge starts ~lead_time before next high-rate window
- arbitrage_enabled + tomorrow=poor with intraday improvement: forecast re-check at CHARGE entry aborts cleanly; chunk lock prevents retry
- arbitrage_enabled + tomorrow=excellent: phase = "n/a"; drain_target_excellent applies
- arbitrage_disabled + any forecast: phase = "n/a"; drain_target_X applies (existing behavior, unchanged)
- `peak_buffer_target` slider replaces `arbitrage_target`; user's saved value migrated correctly
- `arbitrage_charge_lead_time_min` slider exists with sane default (360)
- `arbitrage_trigger` slider gone; no references in code
- Multi-day Solcast (D+2) toggle adds D+2-aware decisions when enabled
- Mutual-exclusion: CHARGE phase pauses any active EVSE; resumes correctly on phase exit (subject to TOU + other pause-reason precedence). Pattern documented as the precedent v4.7.x B5 will extend to appliances.
- `arbitrage_phase`, `next_high_rate_transition`, `charge_window_opens_at`, `forecast_outlook`, `arbitrage_chunk_completed`, `evse_paused_by_arbitrage` attributes appear on the relevant sensors
- All Tier 2 review CRITICAL/HIGH findings resolved; LOW findings explicitly tracked per memory `feedback_review_bug_visibility.md`
