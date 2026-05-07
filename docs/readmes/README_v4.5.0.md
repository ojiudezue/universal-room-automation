# v4.5.0 — Battery Strategy Redesign + Unit-Consistency Sweep

**Date:** 2026-05-07
**Type:** Tier 2 feature cycle (8 deliverables; ~1,100 prod / ~1,200 test LoC net)
**Predecessor:** v4.3.4
**Plan:** `docs/planning/PLANNING_v4.5.0_battery_strategy_redesign.md`
**Transition notes:** `docs/planning/PLANNING_v4.5.0_TRANSITION_NOTES.md`

---

## Summary

Replaces the v3.11.0 SOC-trigger arbitrage gate with a **forecast-class-only gate** + a **four-phase state machine** (WAIT → CHARGE → HOLD → DISCHARGE). The previous design wasted off-peak grid charge: even when arbitrage fired, Phase A drain logic immediately drained the battery back to `drain_target_poor` before the next high-rate window. v4.5.0 closes that gap with a **HOLD phase** that locks the buffer in place until the high-rate window begins.

Also folded in: **multi-day Solcast** (D+2 awareness), **arbitrage / EV mutual-exclusion** (compound-load protection), **TOU helpers** for cross-midnight charge-window math, and a **unit-consistency sweep** that fixes a HIGH-severity bug class (#30 — kW vs W drift across firmware versions in `solar_production`, `net_power`, `total_consumption`, billing accumulator).

---

## What changed

### D1 — Arbitrage four-phase state machine

`BatteryStrategy.determine_mode()` now routes through `_get_arbitrage_decision()` whenever the gate is open (`arbitrage_enabled AND target_day_class in poor/very_poor`).

| Phase | When | Reserve | Charge from grid | Notes |
|---|---|---|---|---|
| **WAIT** | Off-peak, before charge window opens | `reserve_soc` (10) | OFF | Battery serves loads naturally; SOC drifts |
| **CHARGE** | Off-peak, charge window open, SOC < target, recheck still poor | `peak_buffer_target` (80) | ON | Grid charges battery; D4 EV mutual-exclusion engages |
| **HOLD** | SOC ≥ target | `peak_buffer_target` (80) | OFF | Buffer locked at target; solar can still charge above |
| **DISCHARGE** | mid_peak / peak | `reserve_soc` (10) | OFF | Existing logic; battery covers load, displaces high-rate imports |

**Charge window timing:** `charge_start_time = next_high_rate_transition - arbitrage_charge_lead_time_min`. Default `lead_time = 360 min` (6 h) — biases earlier-start so same-day target windows benefit from intraday Solcast updates accumulated since sunrise. Hard min 120 (physics floor + safety margin), hard max 720.

**Per-chunk lock:** one arbitrage cycle per off-peak chunk. Resets on TOU transition INTO off_peak. Prevents oscillation if SOC dips post-completion or forecast wobbles.

**Forecast re-check:** at first WAIT→CHARGE transition per chunk, re-classifies the target day. If forecast improved, sets chunk_completed=True and stays in WAIT for the rest of the chunk.

### D2 — Remove `arbitrage_trigger`; rename `arbitrage_target` → `peak_buffer_target`; add lead-time entity

- **Removed (production):** `_arbitrage_trigger` field, `arbitrage_soc_trigger` constructor param, `set_arbitrage_trigger()` method, the `ArbitrageSOCNumber(role="trigger")` slider, the `CONF_ENERGY_ARBITRAGE_SOC_TRIGGER` form field. `grep arbitrage_trigger` returns 0 hits in production runtime path (only optional kw in `validate_threshold_ladder` and the `_LEGACY` migration marker remain — both documented).
- **Renamed:** `ArbitrageSOCNumber(role="target")` → `PeakBufferTargetNumber`. `CONF_ENERGY_ARBITRAGE_SOC_TARGET` → `CONF_ENERGY_PEAK_BUFFER_TARGET`. `set_arbitrage_target` retained as deprecated alias of `set_peak_buffer_target` for the migration window.
- **Added:** `ArbitrageChargeLeadTimeNumber` — a `NumberMode.BOX` entity (NOT slider — user has slider fatigue; minute-precision values easier to type) on the EC device card. Mirrors `OffPeakDrainNumber`'s post-v4.3.2 RestoreEntity-based pattern; **no `async_update_entry` writeback** (snap-back regression guard).
- **Migration:** `_migrate_arbitrage_target_to_peak_buffer()` in `__init__.py`, idempotent via `arbitrage_target_rename_migration_done` flag. Runs BEFORE the CM coordinator manager initializes so the renamed key is in place when EC reads it. User's existing saved value carries over.

### D3 — Multi-day Solcast (D+2 awareness)

- New `solcast_day_3` property reads `sensor.solcast_pv_forecast_forecast_day_3` (= D+2; Solcast's day numbering is 1-indexed including today).
- New `classify_solar_day_n(days_ahead)` method — uses target day's month for percentile thresholds (handles cross-month forecasts).
- `_classify_target_day(now)` resolves the day class for the day containing the next high-rate transition — fixes the "tomorrow" mis-targeting when an off-peak chunk crosses midnight.
- Multi-day arbitrage gate broadening: when `multi_day_horizon_enabled` is ON, the gate also fires when D+2 is poor/very_poor.
- Drain-target fallback path: when arbitrage is OFF and horizon is ON, picks the more conservative drain target between D+1 and D+2.
- **Default OFF** during calibration cycle (Open Question #3) — flip to ON in v4.5.x patch after observing.

### D4 — Arbitrage / EV mutual-exclusion

The compound-load case (battery 20 kW + EV 7.4 kW + house base ~5 kW = 134A on main breaker) is the real panel-stress scenario. v4.5.0 prevents it.

New `_paused_by_arbitrage` set on `EVChargerController`. When `arbitrage_phase == CHARGE`:
- Pause every running EVSE (turn off + claim).
- Proactively claim already-off EVSEs (so mid-cycle plug-in can't start).

When phase exits CHARGE (HOLD, DISCHARGE, or n/a):
- Release the set.
- Resume each EVSE only if TOU permits AND no other pause reason (`grid_cap`, `battery_drain`, `paused_by_us`) holds.

Establishes the `_paused_by_<reason>` set + precedence-rule pattern that **v4.7.x B5** will copy onto appliance controllers (LG ThinQ, Rainbird).

**Note on saw-tooth charge rate cap (original D4):** dropped during plan review — Enphase's `charge_from_grid` switch is binary (no rate control), saw-tooth would flap; PEC residential has no demand charges, so average-rate-cap provides no cost benefit. Mutual-exclusion solves the actual breaker-stress concern.

### D5 — Storm / EVSE-hold / generator interaction guards

Audit + explicit precedence comment in `determine_mode()` to prevent re-ordering. Order:
1. Envoy unavailable → hold state, no commands
2. Grid disconnected → BACKUP
3. Storm forecast → BACKUP / pre-charging (storm wins over arbitrage)
4. Peak / mid_peak → existing discharge logic
5. Off-peak → arbitrage phase OR drain-target fallback

EVSE hold remains a post-decision wrapper — captured-SOC override during EV charging. Acceptable collision with HOLD phase; D4 mutual-exclusion makes it rare in practice.

### D6 — Sensor diagnostics + methodology refresh

`BatteryStrategySensor` now surfaces (via `BatteryStrategy.get_status()`):
- `arbitrage_phase` (`wait` / `charge` / `hold` / `discharge` / `n/a`)
- `peak_buffer_target` (alongside legacy `arbitrage_target` alias)
- `target_day_class`
- `next_high_rate_transition` (ISO datetime)
- `next_high_rate_transition_period` (`mid_peak` / `peak`)
- `charge_window_opens_at` (= transition − lead_time)
- `arbitrage_chunk_completed`
- `arbitrage_charge_lead_time_min`
- `forecast_outlook` (D+1, D+2, horizon_enabled)
- `evse_paused_by_arbitrage` (cross-ref from EV controller)

Methodology disclosure on the four arbitrage savings sensors (predicted_bill, today, cycle, total) updated to v4.5.0 phased-model framing — accuracy ±10% claim, replaces "may overstate if solar overproduces."

### D7 — Config-flow option additions

- Removed: `CONF_ENERGY_ARBITRAGE_SOC_TRIGGER` field
- Renamed: `CONF_ENERGY_ARBITRAGE_SOC_TARGET` → `CONF_ENERGY_PEAK_BUFFER_TARGET`
- Added: `CONF_ENERGY_MULTI_DAY_HORIZON_ENABLED` (default OFF), `CONF_ENERGY_SOLCAST_DAY_3_ENTITY` selector
- **Lead-time NOT in form** — lives on EC device card per URA mirror pattern (memory `feedback_ura_mirror_pattern.md`)
- **`hold_phase_enabled` NOT added** — HOLD is unconditional whenever the arbitrage gate is open (per plan; toggle would re-enable the v3.11.0 bug this redesign fixes)

### D8 — TOU helpers (next high-rate transition)

New `TOURateEngine.get_next_high_rate_transition(now, lookback_hours=36)` — walks forward at hour granularity to find the next off_peak → mid_peak/peak transition. Crosses midnight cleanly (essential for summer 21:00→14:00 chunks and winter 21:00→05:00 chunks). Plus `get_today_high_rate_transitions(now)` diagnostic helper.

### Bonus — Unit-Consistency Sweep (Bug Class #30)

While preparing v4.5.0 for deploy, a HIGH-severity bug class was found in 5 production sites and fixed in the same cycle. Same shape as v4.3.4's `battery_power_w` fix — newer Envoy firmware reports `solar_production`, `net_power`, and `total_consumption` in **kW**, but consumer code did `value / 1000.0` assuming W. The double-divide produced 1000× too small numbers.

**Specific impacts (latent until newer Envoy firmware deployed):**
- Bill prediction — `accumulate()` math (`net_power_kw × hours = kWh`) silently 1000× off
- EV grid-import-cap threshold — `8 kW` cap never trips when net_power reports kW (kW/1000 ≈ 0)
- Load shedding threshold — same shape as grid-import cap
- DB energy history snapshot — solar/grid_import logged at 1000× too small values

**Fix:** Added `solar_production_w`, `net_power_w`, `total_consumption_w` properties on `BatteryStrategy` / `EnergyCoordinator` that read each entity's `unit_of_measurement` and normalize. Updated all 5 callsites + the billing fallback path. Plus a defensive UoM check in `EVChargerController._get_evse_state` for kW-reporting EVSE integrations (Tesla Wall Connector via some integrations).

**Bug class #30 documented** in `docs/QUALITY_CONTEXT.md` with prevention checklist.

### Test infrastructure pinning (rides along, no version of its own)

Discovered: `quality/tests/` had ~180 phantom failures because `pytest-asyncio` wasn't installed in the env. The plugin is required by ~14 test files; without it, async test markers turned into collection errors counted as failures, masking the real baseline for ~2 months.

- New `quality/requirements_test.txt` pinning `pytest>=8.2`, `pytest-asyncio>=1.0`
- `quality/DEVELOPMENT_CHECKLIST.md` documents `pip install -r quality/requirements_test.txt` as first-time setup
- `docs/QUALITY_CONTEXT.md` tech debt #0 baseline updated: 86+14 → **57+14 calibrated**

The deeper tech debt #0 work (drive 57+14 → 0 + add CI guard) is **v4.5.2**'s scope.

---

## Tier 2 Review

Per CLAUDE.md mandate. Each deliverable's review listed below; full per-D review tables in this document's Git history.

| Deliverable | CRITICAL | HIGH | MEDIUM | LOW | Status |
|---|---|---|---|---|---|
| D1 (state machine) | 0 | 0 | 0 | 2 | clean |
| D2 (rename + migration + lead-time entity) | 0 | 0 | 1 (pre-existing #20 pattern) | 3 | clean |
| D3 (multi-day) | 0 | 0 | 0 | 0 | clean |
| D4 (EV mutual-excl) | 0 | 0 | 1 (manual-override → v4.6.x) | 1 | clean |
| D5 (interaction guards) | 0 | 0 | 0 | 0 | clean |
| D6 (sensor diag) | 0 | 0 | 0 | 1 | clean |
| D7 (config-flow) | 0 | 0 | 0 | 1 | clean |
| D8 (TOU helpers) | 0 | 0 | 0 | 2 | clean |
| Unit sweep | 0 | **2 fixed** | 0 | 1 | clean |

**No CRITICAL findings. All HIGH findings (in unit sweep) fixed.** All LOW findings explicitly documented per memory `feedback_review_bug_visibility.md`.

**Verdict: READY TO DEPLOY.**

---

## Tests

**v4.5.0 specific:** 186 new tests across 4 files
- `quality/tests/test_energy_battery.py` — D1 phase machine (31), D2 rename + lead-time (14), D3 multi-day (11), D5 guards (4), unit sweep (9)
- `quality/tests/test_energy_tou.py` — D8 cross-midnight + diagnostics (17)
- `quality/tests/test_v450_d2_migration.py` — D2 migration helper (4, new file)
- `quality/tests/test_v450_d4_arbitrage_ev.py` — D4 mutual-exclusion (11, new file)

**Suite delta with calibrated baseline (`pytest-asyncio` pinned):**
- Before v4.5.0: 57 failed, 14 errors, 1530 passed
- After v4.5.0: 57 failed, 14 errors, 1716 passed (+186)
- **Zero new regressions.**

---

## Plan Completion Accounting

Per CLAUDE.md mandate. Items planned but deferred (NONE silently dropped):

| Item | Origin | Reason | Tracked for |
|---|---|---|---|
| Manual-override cooldown for `_paused_by_arbitrage` | D4 | Arbitrage CHARGE windows are short (~1-2h); low impact | v4.6.x |
| Removing `arbitrage_target` alias from `get_status` output | D6 | Migration ergonomics — keep until user automations confirmed migrated | v4.6.0 |
| Removing `CONF_ENERGY_ARBITRAGE_SOC_TRIGGER_LEGACY` constant | D2 | Single-run migration marker | v4.6.0 |
| Renaming `total_consumption_kw` → `total_consumption_w` (the property is mis-named historically) | Sweep | Property rename would break external sensor automations | v4.6.0 |
| Pagination, rate-plan top-level toggle, net-metering branch | D7 | Out-of-scope per plan non-goals | v4.5.1 |
| Bayesian peak_buffer_target, charge-rate via barneyonline HACS, solar-aware partial top-up, intraday-confirmed dynamic lead time, cycle-wear amortization, season-variable buffer, per-window economic gate, appliance-coordinated arbitrage | All | Per plan "Advanced topics" — needs v4.5.0 calibration data first | v4.6.x |

---

## Live validation (post-deploy, 14-day observation)

Full 50-checkpoint plan in this README's accompanying message. Highlights:

**Phase 1 (Day 0, ≤1h post-deploy):** HACS shows `installed_version: v4.5.0`. EC device card shows new "Peak Buffer Target" slider + "Arbitrage Charge Lead Time" number-box (NOT slider). Old "Arbitrage SOC Trigger" / "Arbitrage SOC Target" sliders gone. Migration ran exactly once.

**Phase 2 (Day 1-3) — D1 phase machine:** With arbitrage_enabled + tomorrow=poor + SOC<80, observe:
- WAIT through overnight off-peak
- CHARGE transition at ~08:00 today (default lead_time=360 → 14:00 mid_peak − 6h)
- HOLD locked at 80% through midday (~4.5h)
- DISCHARGE during mid_peak/peak

**Phase 3 (Day 1-3) — D2 snap-back regression:** Adjust lead-time entity 360 → 240, restart HA, value persists. Reload entry, value persists. Below-min/above-max rejected at HA frontend or clamped+warned at coord setter.

**Phase 4 (during first arbitrage CHARGE) — D4:** `garage_a` switches off within 1 decision tick when phase enters CHARGE. `paused_by_arbitrage` attribute populates. Resumes when phase exits CHARGE (subject to TOU + other pause-reason precedence).

**Phase 8 (24h) — Unit sweep regression:** Bill prediction within ~10% of pre-deploy value (no 1000× drift). EV grid_import_cap fires correctly when net import >8 kW.

**Phase 9 (Day 14) — Calibration:** `arbitrage_savings_today/cycle/total` accumulates non-zero on poor-tomorrow days. DB rows in `arbitrage_cycles` match phase=CHARGE periods only (HOLD's solar gains NOT counted as arbitrage savings).

---

## Deploy notes

- No DB schema changes
- Public API: `arbitrage_target` / `set_arbitrage_target` retained as deprecated aliases through v4.5.x; remove in v4.6.0
- Manifest auto-stamped to v4.5.0 by `deploy.sh`
- HACS download required after deploy.sh per memory `feedback_verify_hacs_install.md`
- First-time test setup: `python3 -m pip install -r quality/requirements_test.txt`

---

## Risks (monitored during 14-day live observation)

| Risk | Cost ceiling | Mitigation |
|---|---|---|
| Misclassified-poor day → wasted off-peak grid charge | ≤$1.24/day (80% × 36 kWh × $0.043) | Forecast re-check at CHARGE entry |
| Restart loses chunk_completed flag | ≤1 extra cycle/day | Acceptable per plan; phase recomputes on first tick |
| EVSE-hold collides with HOLD phase | EVSE-hold's captured SOC wins | Documented as acceptable; D4 makes the collision rare |
| Solar-overproduction inflates HOLD savings | Mitigated: accounting gates on phase=CHARGE only | Unit-tested |
| Cycle wear (winter 2 cycles/day) | ~730/yr × 10yr = 7300 vs 6000 spec | v4.6.x per-window economic gate will reduce |

---

## Next

- **v4.5.1** — Config-flow restructure (paginated energy form, rate-plan top-level toggle, net-metering branch)
- **v4.5.2** — Test baseline cleanup (drive 57+14 → 0; add CI failure-count guard) — tech debt #0
- **v4.6.0** — Routine Awareness with reconciled AnomalyEvent foundation
- **v4.6.x** — Advanced energy-cost optimization (Bayesian peak_buffer, charge-rate control, solar-aware partial top-up, intraday-confirmed dynamic lead time)
- **v4.7.x** — B5 Appliance Scheduler (extends D4's `_paused_by_<reason>` pattern to LG ThinQ + Rainbird)
- **v5.0** — Config subentries + architectural debt cleanup
