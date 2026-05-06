# PLANNING v4.3.0 — Grid Arbitrage Hardening

**Status:** Planned, not started
**Tier:** Feature cycle (Tier 2 — 2 reviews + live validation per CLAUDE.md)
**Predecessor:** v4.2.29 (current production)
**Effort estimate:** 2-3 cycles

## Context

During the 2026-05-06 morning session a critical latent bug was found in the grid arbitrage strategy: it has never actually charged the battery in the entire life of the feature (since v3.11.0). See `docs/transitions/SESSION_TRANSITION_2026-05-06.md` for the discovery trail and live evidence.

The user asked to NOT ship the bug fix as a standalone v4.2.30 hotfix. Instead, fold it into a feature cycle that also builds out the runtime sliders, drain target reconciliation, ROI tracking, and a diagnostic surface that would have caught the bug had it existed. v4.3.0 is that bundle.

## Goals

1. Fix the silent reserve-level bug so arbitrage actually charges the battery.
2. Surface arbitrage trigger and target as live-tunable Number entities (not config-flow only) — matches the v4.2.10 pattern used for off-peak drain sliders.
3. Reconcile arbitrage thresholds with off-peak drain targets so they don't fight each other or oscillate at boundary conditions.
4. Build an ROI sensor that tracks per-cycle savings so users can validate the strategy is paying off.
5. Add a diagnostic attribute on the battery strategy sensor that shows where current SOC sits relative to all configured thresholds.

## Non-goals (deferred)

- Multi-day forecast lookback (v4.3.x or later)
- EV/arbitrage shared off-peak budget (needs `energy.py` orchestrator refactor — separate feature cycle)
- Dashboard "estimated savings if enabled" widget (depends on D3 ROI sensor; build after D3 ships)
- User-tunable solar classification thresholds (already partially implemented at `energy_battery.py:194` — verify and expose in config flow as a small add)
- Enphase `savings` mode opt-in (low value, high risk; revisit only if user explicitly wants it)

## Deliverables

### D1: Reserve-level fix (CRITICAL)

**File:** `domain_coordinators/energy_battery.py:407-416, 424-433`

**Change:** in both Phase B activation and Phase B continuation paths, change:
```python
reserve_level=self.reserve_soc          # ← user's default floor
```
to:
```python
reserve_level=self._arbitrage_target    # ← arbitrage charge target
```

**Why:** Enphase `self_consumption` mode treats `reserve_battery_level` as both the SOC floor AND the charge target when `charge_from_grid=ON`. Setting reserve to the user's floor (e.g. 10%) means Enphase sees "SOC=10, reserve=10, hold" and never imports despite charge_from_grid being enabled. Setting reserve to the arbitrage target (e.g. 80%) tells Enphase "charge from grid until SOC=80, then hold."

**Also fix:** the cosmetic state-lag bug in the envoy-unavailable early return path (`energy_battery.py:295-310`). The early return sets `arbitrage_active: False` in the result dict but doesn't reset `self._arbitrage_active`. Add `self._arbitrage_active = False` (or, better, leave `_arbitrage_active` truthful and just have the early-return reflect actual in-memory state).

**Acceptance criteria:**
- Verify: `grep` shows no remaining `reserve_level=self.reserve_soc` inside Phase B paths.
- Test: `test_arbitrage_uses_target_as_reserve` — assert `result["reserve_level"] == arbitrage_target` whenever `arbitrage_active=True` in the returned dict. This is what should have caught the original bug.
- Test: `test_arbitrage_active_resets_on_envoy_unavailable` — assert `_arbitrage_active` is False after a determine_mode call where envoy is offline.
- Live: after deploy, with arbitrage_enabled=True and SOC<trigger and tomorrow="poor", the charge_from_grid switch should turn ON AND the actual battery SOC should rise within ~30 min. `sensor.envoy_*_battery` increasing is the success signal.

### D2: Arbitrage runtime sliders

**Files:** `number.py` (new entity classes), `__init__.py` (registration), `domain_coordinators/energy_battery.py` (read from entity at decision time)

**New entities:**
- `number.ura_energy_coordinator_arbitrage_soc_trigger` (range 0-100, step 1, default 30, mode SLIDER, category CONFIG)
- `number.ura_energy_coordinator_arbitrage_soc_target` (range 0-100, step 1, default 80, mode SLIDER, category CONFIG)

Both attach to the existing Energy Coordinator device (matches existing `OffPeakDrainNumber` pattern at `number.py:287`). Both are RestoreEntity for slider persistence across restarts.

**Wiring:** `BatteryStrategy.determine_mode()` should read `_arbitrage_trigger` and `_arbitrage_target` from the EnergyCoordinator's current state (set by the slider's `async_set_native_value`), not from config-flow snapshot at init. Mirror `OffPeakDrainNumber.set_offpeak_drain()` flow — slider write calls `energy.set_arbitrage_trigger(value)` / `energy.set_arbitrage_target(value)` on the coordinator.

**Acceptance criteria:**
- Verify: changing slider value updates the coordinator's `_arbitrage_trigger` / `_arbitrage_target` within the next decision cycle (5 min) without entry reload.
- Test: `test_slider_value_used_at_decision_time` — assert determine_mode reads the live entity value, not the init-time config value.
- Live: drag slider → observe sensor.ura_energy_coordinator_battery_strategy reason string change to reflect new threshold within 5 min.

### D3: Drain/arbitrage threshold reconciliation

**File:** `domain_coordinators/energy_battery.py` (validation logic), `number.py` (slider validation)

**Problem:** Today the defaults are:
- `arbitrage_trigger` = 30
- `drain_target_poor` = 30 (same!)
- `arbitrage_target` = 80

Edge case: when tomorrow is "poor" and SOC oscillates around 30%, Phase A (drain to 30) and Phase B (charge to 80) can fight. SOC drains to 30 → load nudges below 30 → arbitrage triggers → charges back to 80 → drain target says drain back to 30 → repeat. Battery thrashes.

**Reconciliation rules to enforce:**
1. `arbitrage_trigger < drain_target_poor` (otherwise arbitrage triggers exactly when drain stops, oscillation). Default: trigger=20, drain_poor=30, leaving a 10% buffer.
2. `arbitrage_target > drain_target_excellent` AND `> drain_target_good` AND `> drain_target_moderate` AND `> drain_target_poor` (otherwise after charging, Phase A would immediately drain back). Default: target=80, all drain_targets <= 30, so this holds.
3. `arbitrage_trigger >= reserve_soc` (don't arbitrage below the user's safety floor). Default: trigger=20 or 30, reserve_soc=10 typical.
4. UI guard: when user adjusts a slider that violates a rule, log a warning and clamp to the nearest valid value. Do NOT silently accept invalid configs — visible warning in the log + a status attribute on the battery strategy sensor.

**Default change recommendation:**
- `arbitrage_trigger`: keep at 30, OR reduce to 20 to widen the buffer with `drain_target_poor`.
- Discuss with user before defaulting changes.

**Acceptance criteria:**
- Verify: setting `arbitrage_trigger > drain_target_poor` via slider produces a log warning and a sensor attribute `threshold_warning: "trigger above drain_target_poor (oscillation risk)"`.
- Test: `test_threshold_validation_warns_on_overlap`.
- Test: `test_threshold_validation_warns_on_target_below_drain`.

### D4: Per-cycle ROI sensor

**Files:** `domain_coordinators/energy_battery.py` (cycle accounting), `sensor.py` (new sensor classes), `database.py` (persistence)

**New sensors (Energy Coordinator device):**
- `sensor.ura_arbitrage_savings_today` — sum of arbitrage savings since midnight, USD
- `sensor.ura_arbitrage_savings_month` — sum since billing cycle start, USD
- `sensor.ura_arbitrage_savings_total` — lifetime sum since v4.3.0 deploy, USD

**Calculation per cycle (5 min):**
- If arbitrage was active during this cycle AND grid power was being imported:
  - `kWh_charged_this_cycle = grid_import_during_cycle (kWh)`
  - `cost_this_cycle = kWh_charged * off_peak_rate_at_cycle_start`
  - The "saved" cost is the difference between off-peak rate (paid) and the rate that WOULD have been paid at peak / mid-peak time when this energy is consumed tomorrow.
  - **Heuristic for v4.3.0:** assume the charged kWh displaces tomorrow's peak imports (in summer) or mid-peak imports (in shoulder/winter). `saved_per_kwh = peak_rate - off_peak_rate` (summer) or `mid_peak_rate - off_peak_rate` (shoulder/winter).
  - `savings_this_cycle = kWh_charged * saved_per_kwh * round_trip_efficiency` where `round_trip_efficiency = 0.90` (Enphase typical).
- Accumulate and persist (DB table `arbitrage_cycles` with columns: timestamp, soc_before, soc_after, kwh_charged, off_peak_rate, displaced_rate, savings, season).

**Acceptance criteria:**
- Verify: `sensor.ura_arbitrage_savings_today` is `$0.00` before any arbitrage runs, increases monotonically as cycles complete.
- Test: `test_roi_calculation_summer_peak_displacement` — given known kWh charged at $0.043, displacement at $0.162, RTE=0.9 → savings = kWh × 0.107.
- Test: `test_roi_calculation_winter_no_peak` — winter scenario, displacement is mid-peak rate not peak.
- Test: `test_roi_resets_at_billing_cycle_day` — savings_month resets on `bill_cycle_start_day`.
- Live: after v4.3.0 deploys and arbitrage runs for one night, `savings_today` should reflect a realistic value (e.g. $0.50-$2.00 depending on kWh charged).

### D5: Threshold diagnostic attribute

**File:** `sensor.py` (`BatteryStrategySensor` extra attributes)

**Add to `extra_state_attributes`:**
- `threshold_position`: human-readable string describing where current SOC sits, e.g. `"SOC=45 — between drain_target_poor (30) and arbitrage_trigger (30) ⚠ overlap"` or `"SOC=10 — below arbitrage_trigger (30) and reserve_soc (10) — arbitrage will activate next cycle"`.
- `next_action_estimate`: what the strategy will likely do at the next decision cycle, e.g. `"will continue arbitrage charging until SOC reaches target (80%)"`.

**Acceptance criteria:**
- Verify: attribute updates each decision cycle (5 min).
- Live: the attribute reads sensibly across all four phases (peak, mid-peak, off-peak drain, off-peak arbitrage).

## Tier 2 Review Plan

### Review 1 (Core A): Domain logic
Focus: D1 fix correctness, D3 reconciliation rules, D4 ROI math.
- Does the reserve_level fix actually achieve the desired Enphase behavior? Verify against Enphase documentation.
- Are reconciliation rules complete? Any other oscillation scenarios?
- Is the ROI calculation honest? (don't over-credit; round-trip losses, opportunity cost of cycle wear)

### Review 2 (Core B): Lifecycle + integration
Focus: D2 slider entity lifecycle, D4 DB persistence, D5 sensor attribute timing.
- Does the slider read-from-entity pattern survive entry reload?
- Does the ROI persistence survive HA restart?
- Does the threshold diagnostic update reliably without race conditions?

### Live Validation (Review 3)
Focus: real-world behavior on the user's instance.
- Verify D1 by watching SOC rise from <30% to ≥80% during an off-peak arbitrage activation.
- Verify D2 by adjusting sliders mid-cycle and observing strategy change within 5 min.
- Verify D4 by checking `savings_today` accumulates as expected over one full off-peak window.
- Verify D5 by reading the diagnostic attribute at multiple SOC levels during a 24-hour cycle.

## Open Questions for the User

1. **`arbitrage_trigger` default:** keep at 30 (matching `drain_target_poor` and risking oscillation) or reduce to 20 (safer buffer)?
2. **ROI accounting period:** monthly resets on the bill cycle start day (current default day=23 per `DEFAULT_BILL_CYCLE_START_DAY`)?
3. **Custom solar threshold exposure (item E):** check whether `_solar_classification_mode == "custom"` path at `energy_battery.py:194` is wired through config flow already. If not, add a small config-flow option in this cycle for free.

## Out of Scope (Future Cycles)

- **Multi-day forecast lookback (item B):** look at next 2-3 days of Solcast forecast, not just tomorrow. Would prevent over-charging on day 1 when day 2 is sunny but day 3 is bad. Cycle of its own.
- **EV/arbitrage shared off-peak budget (item C):** needs orchestration refactor in `energy.py`. Defer until both EV and arbitrage have stable independent behavior.
- **Dashboard widget (item F):** "estimated savings if enabled" — depends on D4 (ROI sensor) being live for at least one bill cycle of historical data.
- **Enphase savings mode (item D):** still likely net-negative; revisit only if user explicitly wants it.
