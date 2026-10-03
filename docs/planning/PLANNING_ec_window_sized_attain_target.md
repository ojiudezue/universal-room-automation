# PLANNING — EC window-sized attain target (peak_buffer_target becomes a cap)

**Card:** to be minted at build dispatch after the adjacency sweep (candidate id `EC-ATTAIN-WINDOW-SIZED-TARGET-1`).
Adjacent cards: `ATTAIN-SOLAR-AGGRESSION-INVESTIGATE-1` (done/closed, `kanban.data.yaml:6216`), `EC-SOC-LADDER-FULL-WIRING-1`
(D2 parked, `:2657`), `ATTAIN-SEASONAL-BEHAVIOR-TRACE-1` (`:26471`), `ATTAIN-UNBOUNDED-RATE-WINTER-MASK-1` (`:26500`), SPEC Q3/Q6.
**Written:** 2026-10-03 by ura-planner. **Status: plan only. No code edited.**
**Tier: 3** (see §9). TWO plan reviews before build; FOUR framing-disjoint build reviews; orchestrator re-verification;
operator checkpoint before deploy; no restart while the house sleeps.

**Operator rulings this plan implements (2026-10-03):**
- Peak / mid-peak avoidance is the top imperative. The evening may drain below the forecast floor, then park.
- **Option 1:** size the attain/arbitrage charge target per boundary instead of a fixed `peak_buffer_target=80`.
  Target ≈ expected house use in the upcoming high-rate window + desired end floor − expected solar, clamped to
  [reserve, cap]. The existing `peak_buffer_target` knob becomes the **cap** (cap = old value ⇒ today's ceiling).
- **Option 4:** risk-adapt the end floor (inclement / outage risk, winter morning mid-peak exposure).
- **Option 2 (summer):** spend battery on true peak inside mid-peak. Optional add-on. **Parked in this plan** (§8).
- Winter: verify the morning mid-peak; if present, attain charges overnight toward it. EV conflict: L2 turn-taking
  (EV first, battery after, sized charge; EV must-start-by wins); L1 share-instead-of-pause if breaker headroom allows.
- **Grid charging decisions are owned by attain only** (no new grid-charge producer).

**Line-number caveat:** `energy_battery.py` was being edited concurrently while this plan was written (the
daylight-horizon / poor-night-floor build). Line numbers drifted by ~50-70 between two reads in this session.
Every site below is cited by **symbol** first, with a line number that is approximate. Plan review #1 must
re-grep on the build base commit.

---

## 0. Institutional context verified

### 0.1 Prior-art scan (code) — REUSE-or-BUILD per piece

| Piece | Verdict | Existing symbol (file, approx line) |
|---|---|---|
| Cap value / live knob | **REUSED** — `PeakBufferTargetNumber` (`number.py:~1468-1530`) → `EnergyCoordinator.set_peak_buffer_target` (`energy.py:~9461`) → `BatteryStrategy._peak_buffer_target` (ctor `energy_battery.py:~538`). Semantics change from "target" to "cap"; entity id unchanged. | as cited |
| Single seam so all ~65 readers see the sized value | **REUSED DESIGN (parked)** — `PLANNING_ec_soc_ladder_full_wiring.md` §D2: turn `_peak_buffer_target` into a read property over a raw backing field; validators read RAW. That D2 was parked (shipped v5.103.35 without it; grep `_peak_buffer_target_raw` → 0 hits). This plan builds that seam and composes both clamps (its `> top drain` clamp + sizing) in ONE property. | `PLANNING_ec_soc_ladder_full_wiring.md:187-210` |
| Upcoming window boundary + period | **REUSED** `_attain_target_boundary(now, tou_period)` (`energy_battery.py:~3960`), `TOURateEngine.get_next_high_rate_transition` (`energy_tou.py:645`) | as cited |
| Window END (start of next off_peak) | **NEW (small helper in `energy_tou.py`)** — no `get_window_end` exists. The hour-walk pattern exists in `get_next_high_rate_transition` and `peak_ahead_before_offpeak`; extend that shape. | `energy_tou.py:577-687` |
| End floor (tomorrow's forecast floor) | **REUSED** `_drain_target_for(at)` (`energy_battery.py:~1938`), the effective, ladder-clamped, multi-day-max floor. Called with `at = window_end`. | as cited |
| Battery kWh per % | **REUSED** `_battery_capacity_kwh()` with LKG cache (`energy_battery.py:~3843`); fallback `ARB_LADDER_DEFAULT_BATTERY_KWH` (`:300`). DP uses `DP_CAPACITY_KWH_PER_SOC_PP=0.40` (`energy_const.py:1621`) ⇒ ~40 kWh. One source must win: use `_battery_capacity_kwh()`; the DP constant stays DP's. | as cited |
| Window house-load estimate | **BUILD — gated on D0.** EC has **no per-window consumption forecast.** `EnergyForecast._estimate_consumption` (`energy_forecast.py:352`) returns a **daily** kWh (R1 regression `CONSUMPTION_REGRESSION_V1` or legacy DOW arm, gated by `CONF_R1_ESTIMATOR_SHADOW_ONLY`). The only window-ish use today is DP's flat `predicted_consumption_kwh / 24` (`energy.py:_dp_house_load_kw ~4352`). `energy_history` has `hour_of_day` + `tou_period` columns (`database.py:784`, `:1948-1958`) but **180-day retention** (`__init__.py:2302`) ⇒ no Dec-Feb rows. D0 decides between (a) R1-daily × window-share, (b) a fitted per-season×window profile constant (rung 1, like `CONSUMPTION_REGRESSION_V1`), (c) NO-GO. | as cited |
| Solar credit **before** the boundary | **REUSED, NOT added to the target** — already in the attain/rung projection via `_expected_solar_surplus_pct` (`energy_battery.py:~3867`) with `SOLAR_CAPTURE_FACTOR=0.5` (`:260`, CLOSED memo: keep 0.5). Subtracting it from the target as well would **double-count** (§1 finding F-DC). | as cited |
| Solar credit **during** the window | **NEW knob, default 0** (v1). `_expected_solar_surplus_pct` slices the daily forecast pro-rata by daylight overlap, so it is flat across the day and over-credits late afternoon. That is unsafe for a 17:00-21:00 window. | — |
| Risk adder: inclement | **REUSED** `_floor_reserve(existing, effective_reserve, hold_depth)` (`energy_battery.py:~3417`). partial_hold already raises every CHARGE/HOLD emission. `full_hold` storm precharge is a separate producer and is untouched. | as cited |
| Risk adder: forecast uncertainty | **NEW knob** — a named-bucket Select (quantile of D0's error distribution). See §5. | — |
| L1 / L2 classification | **REUSED** DP's rule `charger_rate_kw <= DP_L1_RATE_THRESHOLD_KW (3.0)` on measured `ev_load_w` (`energy_drain_precedence.py:665`, `energy_const.py:1613-1615`). | as cited |
| EV need, house-load model, must-start-by | **REUSED** `_dp_needed_kwh_plugged` (`energy.py:~4300`), `compute_must_start_by` (`energy_drain_precedence.py:374`), `CONF_DP_MUST_START_BY_MIN_PAST_MIDNIGHT=03:00` (`energy_const.py:1585`). | as cited |
| Breaker pause during grid charge | **REUSED, UNCHANGED in this cycle** — `_execute_breaker_safe_dispatch` (`energy.py:6671`): any `charge_from_grid` intent (decision or live/LKG switch) ⇒ pause **all** EVs, label `breaker`. | as cited |
| Non-battery import guard | **REUSED** `arbitrage_grid_import_guard_kw` (default 12 kW, `energy_const.py:861`), `_effective_import_kw` (`energy_battery.py:~2814`). | as cited |
| Charge-window timing | **REUSED** `_is_charge_window_open` + live Number `arbitrage_charge_lead_time_min` (live 180). **Config-first lever for L2 turn-taking** (§D4). | `energy_battery.py:~2771` |

### 0.2 Prior plans / analysis consulted

- `PLANNING_attain_shortfall_sizing.md` (full read). This is the most important prior art. Shortfall sizing = `clamp(pbt − credited_solar, floor, pbt)`
  was **killed** on 2026-09-09 (`kanban.data.yaml:6316-6406`):
  - **P1:** `reserve_level` is the discharge floor **and** the charge target (one Enphase number, Bug Class #63).
  - **P2:** latch/phase exits key on `soc >= peak_buffer_target`.
  - Schedule-limit is unsupported on this site.
  - CFG modulation is infeasible (~35-min actuation lag, v5.3.8 drift self-abort).
  - rung_0 defer is short-circuited on wasteful days.
  - Measured waste: ~$140-270/yr. On 11/13 summer days solar alone could **not** refill to the pre-peak SOC.

  **How this plan differs:** it does not lower reserve below the level we want at the boundary. The sized target
  **is** the level we want at the boundary, so P1 does not apply: holding reserve = target is the desired behaviour.
  It also routes through one property, so P2 exits use the same value (no split-brain, review C-7 "44-read
  split-brain"). It **does not subtract solar from the target** (§1 F-DC). It does **not** modulate CFG.
- `PLANNING_ec_soc_ladder_full_wiring.md` (§0-§2.2, §D2): consumer table P1-P22/V1-V3/R1/W1-W2. This is the seam design reused here.
- `PLANNING_ec_daylight_horizon_and_poor_night_floor.md` (full): WAIT now holds `_drain_target_for(now)`. Its INV-W0/W1 bound the lower clamp here.
- `AUDIT_ec_drain_floor_and_pingpong_2026_10_03.md` (full): per-night SOC shapes. Shoulder mid-peak 17-21 discharges to ~30 % by 21:00 on 10-01/10-02. **This is direct evidence that the evening window used ~50 pts (~20 kWh) of an 80 % buffer**, which is the first sanity number for D0.
- `SPEC_ec_behaviour_contract.md`: §0 vocabulary (TOU table), rows A8/A9/A12/A13, INV-1..9, Q3, Q6.
- Kanban `ATTAIN-SEASONAL-BEHAVIOR-TRACE-1`: attain is season-agnostic and charges to the fixed target. "All winter charging on typical days depends on the attain net". `ATTAIN-UNBOUNDED-RATE-WINTER-MASK-1`: fence, never bound the attain rate to the solar horizon.
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.1-2.4b, §3, §4, §5.6.
- Memory bodies (index-level + those cited by the above): attain solar aggression CLOSED keep 0.5; charge-onset correct site; EV drain precedence shipped; marginal-benefit pushback; measure-before-build; numbers get knobs; named buckets; label style guide; single-user-no-back-compat **CHANGING** (2nd home goes live 2026-10-03/04: optional integrations must degrade gracefully, no house-specific quirks in shared paths).

### 0.3 Code read for this plan

`energy_battery.py`: `_classify_attain_rung` (head), `_get_arbitrage_phase`, `_floor_reserve`, `_get_arbitrage_decision`,
`_attain_target_boundary`, `_attain_target_period_at_or_above_current`, `_midpeak_rate_lt_peak`,
`_should_attain_peak_buffer`, `_get_attainability_decision`, `_get_attainability_hold_decision`,
`_get_attainability_hold_current_decision`, `reset_arbitrage_chunk`, `_adopt_attain_state_from_hardware`,
`_maybe_run_reboot_recovery`, `_run_attain_branch` (holding/charging legs + entry tail), peak / mid-peak / off-peak
legs of `determine_mode` (~5370-5700), `_is_charge_window_open`, `_recheck_forecast_on_charge_entry`,
`_effective_import_kw`, `_record_attain_sample`, `_observed_net_charge_rate_per_hour`, `_battery_capacity_kwh`,
`_threshold_position`, `_next_action_estimate`.
`energy.py`: `_execute_breaker_safe_dispatch`, `_dispatch_post_decision_tou_and_arbitrage` (head),
`_dp_house_load_kw`, arbitrage savings log (~3405-3430), `_check_threshold_ladder` (~9262-9341).
`energy_tou.py`: ctor, `get_next_high_rate_transition`, `get_today_high_rate_transitions`.
`energy_const.py`: `PEC_TOU_RATES` (15-66), DP constants (1585-1621).
`energy_forecast.py`: `_do_prediction`, `_compute_v1`, `_estimate_consumption`.
`energy_drain_precedence.py`: `TransitionInputs`, `evaluate_dp_transition`, `compute_must_start_by`.
`database.py`: `energy_history` DDL and migration.

### 0.4 Config-first check

- **Option 1 (sizing):** no setting does it. Hand-turning the `peak_buffer_target` Number per season is the poor-man's
  version, and the measured case in D0 decides whether that is good enough (see §1 marginal-benefit).
- **L2 turn-taking (winter):** **a knob turn may solve most of it.** Lowering `arbitrage_charge_lead_time_min` from 180
  to ~90-120 moves the winter charge window from 02:00 to 03:00-03:30 for the 05:00 boundary. That leaves the EV
  21:00-03:00 off-peak with no breaker pause. The cost is that the shoulder/summer windows shrink too. D0 measures
  whether a sized charge fits in the shorter window (§D4).
- **L1 share:** needs a breaker rating that is not in any config (grep `main_breaker|service_amp|panel_amp` → 0).
  This is an operator fact first.

---

## 1. Producer / Consumer checks + marginal-benefit decomposition

### 1.1 Producer of the new value (sized target T)

```
W        = upcoming high-rate window [b0, b1)  (b0 = _attain_target_boundary; b1 = NEW tou.window_end(b0))
L_q      = window house load at quantile q (kWh)          ← D0-gated estimator
S_w      = solar credit DURING W (kWh)                    ← knob, default 0
F_end    = _drain_target_for(b1) (%)                      ← reused end floor (tomorrow / next window)
need_pct = (L_q − S_w) / capacity_kWh × 100 / η_dis       (η_dis: discharge efficiency const, D0-confirmed)
T_raw    = F_end + need_pct + risk_pct                    (risk_pct: winter-morning / outage adder, Option 4)
L_lo     = max(reserve_soc, wait_floor(now))              (WAIT floor shipping now; lower clamp)
T        = min(cap, max(L_lo, ceil(T_raw)))               then _floor_reserve(...) at each emission (unchanged)
```

Dependency health (to be measured in D0): the consumption telemetry (SPAN mains or Envoy consumption) is live; Solcast
is not needed in v1 (S_w=0); `sun.sun` is not needed; TOU table is built-in PEC unless a rate file is loaded (D0 checks
`tou_file_status`).

**F-DC (double-count finding, changes the operator's literal formula):** the operator's formula subtracts "expected
solar before/during". Solar **before** the boundary is already credited in the attain entry projection
(`_should_attain_peak_buffer`: `projected = soc + rate×h + solar_surplus` compared to the target) and in rung_0/1. If
we also subtract it from T, the same kWh is credited twice: grid charges to (T − solar) and the gate then also assumes
solar lifts SOC. **Rule: T is a need (what must be in the battery at b0). Solar-before stays only in the projection
that decides whether grid is needed to reach T.** Solar-during-W is a legitimate need reducer and gets its own knob
(default 0).

### 1.2 Consumers of T (hypothesis; plan review #1 re-enumerates)

All readers of `self._peak_buffer_target` in `energy_battery.py` (65 textual hits on 2026-10-03) plus 3 readers in
`energy.py` and 1 in `energy_const.py`. Classified by what they must read:

| Class | Sites (symbol) | Reads |
|---|---|---|
| Rung ladder (D) | `_classify_attain_rung`: None guard, `soc >= target`, entry/exit bands | **effective T** |
| Arbitrage phase (D) | `_get_arbitrage_phase` HOLD predicate | **T** |
| Arbitrage emissions (E) | `_get_arbitrage_decision` HOLD, CHARGE (`_floor_reserve(T)`, reason text) | **T** |
| Attain entry (D) | `_should_attain_peak_buffer` None guard, `soc >= T`, `projected < T` | **T** |
| Attain emissions (E) | `_get_attainability_decision`, `_get_attainability_hold_decision` | **T** |
| Attain transitions (D) | `_run_attain_branch` charging→holding `soc >= T`; entry log | **T** |
| Reboot adoption (D) | `_adopt_attain_state_from_hardware` holding/charging by `soc vs T` | **T, with restart rule INV-S2b** |
| Summer mid-peak continuation (D) | `determine_mode` mid_peak leg `soc < T` → `_run_attain_branch(tou_period="mid_peak")` | **T for the PEAK window** (boundary re-pointed by `_attain_target_boundary`) |
| Completed-chunk HOLD (E) | `determine_mode` off-peak short-circuits (both owners) | **T (chunk snapshot)** |
| Display (N) | `_threshold_position`, `_next_action_estimate`, `get_status` attrs, `energy.py` cycle-start log | **T, plus new `peak_buffer_cap` + basis attrs** |
| Validators (V) | `get_status` `validate_threshold_ladder(...)`, `energy.py _check_threshold_ladder` + anomaly payload | **RAW cap** (else detect-and-swallow, soc-ladder I-2) |
| Coordinator API (R) | `energy.py` `peak_buffer_target` / `arbitrage_target` properties, `set_peak_buffer_target` | **RAW cap** (Number round-trip) |
| Config validator | `energy_const.validate_threshold_ladder` (`peak_buffer_target > top drain`) | **RAW cap** (invariant #2 is a cap property now) |

Consumers that do **not** read T but are affected:
- **Breaker pause** (`_execute_breaker_safe_dispatch`). A lower T means shorter CFG-on, so a shorter EV pause. This is the intended EV benefit.
- **WAIT floor** (shipping now) is the lower clamp input.
- **Mid-peak discharge legs** (shoulder/winter `reserve=effective_reserve`) drain whatever T bought. "Evening may drain below the forecast floor" is already today's behaviour.
- **Arbitrage savings ledger** (`energy.py ~3405`) keys on phase, not T. Unchanged.
- **Inclement precharge** (`charge_from_grid=True` at the inclement leg) has its own storm target. Unchanged, and not a T reader.

Dashboards (`lovelace.ura_v6/v7/v8`, PWA): display only. `peak_buffer_target` attr now shows the effective T. The new `peak_buffer_cap` shows the knob.

### 1.3 Marginal-benefit decomposition (pushback, CLAUDE.md duty)

Built-in rates (`PEC_TOU_RATES`): off-peak $0.0435; shoulder/winter mid-peak $0.0864; summer peak $0.1618.
Battery ≈ 40 kWh.
- **Cost of over-charging** (today's fixed 80 when need is lower): the surplus is not lost. Shoulder/winter mid-peak
  discharges to reserve, and anything left serves off-peak load the grid would have served at the same off-peak price.
  The real cost is round-trip loss (~10 %) on the surplus: ≈ $0.004/kWh. Example: 10 kWh surplus/day ≈ **$0.04/day ≈ $15/yr**, plus cycle wear.
- **Cost of under-charging:** each missing kWh is bought at mid-peak instead of off-peak: ≈ $0.043/kWh (shoulder/winter), ≈ $0.12/kWh (summer peak).
- **Newsvendor optimum:** q* = c_under / (c_under + c_over) ≈ 0.043/0.047 ≈ **0.91** (shoulder/winter) and ≈ **0.97** (summer peak). So the right target is a **high quantile** of window load. In summer the cap will almost always bind, which is today's behaviour.

**Conclusion before D0:** the direct **$ value of sizing alone is small** (tens of $/yr). It is not "free money". The
cycle earns its Tier-3 cost only if D0 confirms at least one of these:
- (a) **Winter overnight grid-charge to 80 % every night.** See §2 W-1. This is a latent behaviour that starts on Dec 1. Sizing the 05:00-09:00 window could cut a nightly ~20-25 kWh grid charge plus a double daily cycle.
- (b) **EV contention.** Shorter breaker pauses on nights with an L2 session.
- (c) **Cycle wear.** Operator to weigh it.

If D0 shows (a)/(b) are immaterial, the recommendation is **NO-GO on Option 1**, with a hand-tuned seasonal cap
(knob turn) as the config-first fallback. That outcome is recorded with the measured number.

---

## 2. Winter TOU verification (done statically; D0 confirms live)

Built-in `PEC_TOU_RATES["winter"]` (`energy_const.py:51-65`), months 12/1/2:
- off_peak (0-5), (9-17), (21-24)
- mid_peak (5-9), (17-21)
- **no `peak` period**

**Yes, there is a 05:00 morning mid-peak.** The live table may be overridden by a rate file. D0 reads
`TOURateEngine.get_period_info()["rate_source"/"tou_file_status"]` from the strategy sensor or diagnostics.

Consequences in **today's** code, all traced and none yet exercised live (attain shipped June 2026; no winter since):
- **W-1 (latent, important).** Winter off-peak 21:00-05:00. The charge window opens at 05:00 − 180 min = **02:00**.
  With the arbitrage gate closed (typical day), the attain branch runs (`determine_mode` off-peak leg →
  `_run_attain_branch`). `_should_attain_peak_buffer` projects `soc + rate×h + solar_surplus`. Overnight, `rate` is
  negative (house load) and the pre-dawn solar slice is ~0 before 05:00, so `projected < 80` ⇒ **attain grid-charges
  to 80 % every winter night**, holds to 05:00, then mid-peak discharges to reserve. Then the 17:00 boundary (window
  opens 14:00) charges again. Two grid-charge cycles per day. Sizing applies to both boundaries independently.
  SPEC Q6 asked about this. **Operator must rule** on whether winter overnight attain is wanted at all (§10 Q4).
- **W-2.** `_midpeak_rate_lt_peak` is False in winter/shoulder (no peak), so mid-peak attain continuation is dormant.
  Sizing for winter is off-peak only.
- **W-3.** Winter morning end floor: b1 = 09:00, followed by off-peak 09-17. `F_end = _drain_target_for(09:00)` names
  the 17:00 boundary's target day (peak-anchored resolver). That is the right floor: it is what the battery should keep
  going into the day.
- **W-4 (EV).** Any CFG-on tick pauses **all** EVs (breaker invariant). A 02:00 charge window collides with the DP
  must-start-by 03:00. Today the breaker pause wins over must-start-by. The operator says must-start-by should win (§D4).

---

## 3. Falsifiable invariants (Reviewer D falsifies these)

- **INV-S0 (fixed mode is byte-identical).** With `attain_target_mode = fixed` (the kill switch), every decision dict
  (mode, reserve_level, charge_from_grid, phase, reason) is byte-identical to pre-change for **every** input, including
  restart adoption and all 4 CFG-on producers.
- **INV-S1 (bounds).** In sized mode, the effective target T obeys `min(cap, L_lo) <= T <= cap` on every tick. Every
  reserve emission from the arbitrage CHARGE/HOLD, attain CHARGE/HOLD and completed-chunk HOLD sites equals
  `_floor_reserve(T, effective_reserve, hold_depth)`. When cap < L_lo (legal: cap 25, poor floor 30), T = cap, which
  is today's behaviour.
- **INV-S2 (no in-chunk lowering).** Between two `reset_arbitrage_chunk` calls, T is non-decreasing tick over tick.
  It is computed at chunk start (first eligible tick) and may only re-size **upward** (e.g. the forecast worsens).
  **INV-S2b (restart):** if after a restart the hardware shows CFG on or the commanded reserve is above reserve_soc
  inside an attain/arbitrage window, then T ≥ min(cap, hardware reserve). A restart can never lower a held buffer.
- **INV-S3 (one value per tick).** Within a tick, every reader in §1.2 that reads "T" sees the same number. There is
  one property computed once per tick, or a chunk snapshot. No reader may read the raw cap except the V/R/config rows.
- **INV-S4 (degrade = cap).** If any sizing input is unavailable (load estimate None/stale, `window_end` None,
  capacity None with no LKG, TOU None), then T = cap for that chunk. That is today's behaviour, with an
  `attain_target_basis = "fallback_cap:<reason>"` attr. The 2nd home without SPAN/consumption telemetry gets exactly
  today's behaviour.
- **INV-S5 (no new grid-charge producer).** The set of code paths that can emit `charge_from_grid=True` is unchanged:
  arbitrage CHARGE, attain CHARGE, inclement precharge ×2. For identical inputs and SOC trajectory, sized mode's
  CFG-on ticks are a **subset** of fixed mode's. Sizing can end a charge earlier and never start one where fixed would not.
- **INV-S6 (latch coherence, P2 of the killed plan).** `_attain_state` charging→holding fires exactly when
  `soc >= T`. The latch can never be stuck "charging" with `soc >= T`. HOLD reserve equals T, not the cap.
- **INV-S7 (validators raw).** `threshold_ladder_violation` fires on the raw cap exactly as today. A sized T below
  the top drain is not a ladder violation.

---

## D0 — Measurement probe (FIRST deliverable; go/no-go gate). Read-only, no HA changes.

One-shot `ssh ha "python3 -" < probe.py` over the HA recorder (states + long-term `statistics`), plus a URA DB read
(`energy_history`, `decision_log`). Report goes into this doc as §11 and gates D1-D4.

**D0.1 — Window load: actuals and estimator accuracy (the sizing go/no-go).**
- **Entities (verify by registry first; do not assume):** house consumption power or energy, ideally
  `sensor.span_panel_current_power` + `_2` (the DP source). Cross-check against Envoy consumption and the
  `energy_history.whole_house_energy` column. Subtract EV draw (`sensor.garage_{a,b}_power_minute_average`), because
  EV load is excluded from window need: EVs are paused in high-rate windows.
- **Windows, per day, for as far back as data exists:**
  - shoulder 17-21
  - summer 14-16, 16-20, 20-21
  - winter 05-09, 17-21. Use recorder long-term **hourly statistics** to reach Dec 2025 - Feb 2026. `energy_history` is 180 days only. If no winter statistics exist, say so; winter sizing then ships **fallback_cap** (INV-S4) until a winter of data exists.
- **Actual:** kWh of non-EV house load per window. Also battery discharge kWh per window, as a cross-check that the
  battery actually served it.
- **Estimators scored (no fitting on the test half; split by date):**
  - E0 = R1 daily prediction (`energy_daily.predicted_consumption_kwh`) × hours/24. This is the existing EC-derived figure.
  - E1 = R1 daily × empirical window share (share fitted on the train half, per season×window).
  - E2 = trailing-14-day same-window median (no model).
  - E3 = E2 + temperature term (HDD/CDD at window start).
- **Metrics per season×window×estimator:** n, bias (mean error), MAE, P50/P85/P90/P95 of `actual − estimate`, and the
  **q\*-quantile margin** (kWh to add so ≥ q\* of windows are covered).
- **Gate:** sizing is GO for a season×window only if the chosen estimator's P90 margin ≤ **4 kWh (~10 % SOC)** and
  |bias| ≤ 1.5 kWh. Otherwise that window ships fallback_cap. (Both thresholds are review-gated module constants in
  the report, not tuned after the fact.)

**D0.2 — Counterfactual replay value (the marginal-benefit gate).** For each historical window, with the chosen
estimator + margin, compute:
- T_sized vs 80
- kWh not grid-charged
- shortfall kWh (actual need > T_sized − F_end), priced at mid-peak/peak minus off-peak
- RTE saving priced at off-peak

Report net $/season and $/yr, and the count of shortfall windows. **Gate:** projected net ≥ **$40/yr** OR W-1/EV
contention is material (D0.4). Otherwise recommend NO-GO + seasonal cap knob turns.

**D0.3 — Winter TOU + shoulder sanity.** Live `rate_source`/`tou_file_status`; enumerate live periods for a Dec/Jan/Feb
date via the engine (diagnostics or the strategy sensor attrs). Confirm 05-09 mid-peak. Also re-derive from the recorder
the 10-01/10-02 shoulder evening (80 % at 17:00 → ~30 % at 21:00) as the D0.1 sanity row.

**D0.4 — EV × charge-window overlap.** Over all recorder history:
- nights with an L2 session (garage_a/b > 3 kW) that overlap [b0 − lead, b0]
- session start/end/kWh
- whether `evse_paused_by_arbitrage` (label breaker) cut a session
- how long the battery grid-charge took at the measured CFG charge rate (battery_power during attain CHARGE ticks, plus the ~35-min actuation lag)

From this, compute whether a **sized** charge fits in [03:00, 05:00) for winter (lead-time knob scenario) and
[15:00, 17:00) for shoulder.

**D0.5 — Breaker headroom for L1 + battery.**
- Peak of `net_power_w` and of `battery_power_w` during past CFG-on ticks, the 99th percentile non-battery house load
  at 02:00-05:00, and measured L1 draw (1.4-1.9 kW).
- Report peak total kW versus the **main-breaker rating, which must come from the operator** (not in config or code).
  Use 80 % continuous. Without the rating, D0.5 reports the numbers only, and L1-share is NO-GO.

**D0.6 — Fixture.** Hand-build `quality/tests/fixtures/ec_window_sized_target_2026.json`: per window
(date, season, window, actual_kwh, E-chosen estimate, end-floor class, SOC at b0/b1, cap, reserve). Commit it as the
replay oracle (hand-built first; automation is diffed against it).

### Acceptance
- **Verify:** §11 report committed with the D0.1 table, D0.2 $, D0.3 periods, D0.4 overlap table, D0.5 numbers.
- **Verify:** a per season×window GO/NO-GO line, and an overall cycle GO/NO-GO.
- **Verify:** fixture rows cite recorder `last_updated` / statistics `start`.

---

## D1 — Effective-target seam (property) + fixed/sized mode. *Gated: D0 overall GO.*

**Changes (`energy_battery.py`):**
1. Rename storage to `self._peak_buffer_cap_raw` (ctor). Add `@property _peak_buffer_target`, which returns the
   effective T:
   - **fixed mode:** raw cap (byte-identical; INV-S0). Compose the parked soc-ladder D2 clamp here **only if** that
     card is revived. **Not in this cycle**, to keep INV-S0 trivially true.
   - **sized mode:** the chunk snapshot `self._sized_target_snapshot` if set, else raw cap.
2. `@_peak_buffer_target.setter` → writes raw (keeps the ~19 test-fixture assignments + `set_peak_buffer_target`
   working).
3. Re-point V/R/config rows (§1.2) to raw: `get_status` validator call; `energy.py` `_check_threshold_ladder` + payload;
   `energy.py` `peak_buffer_target`/`arbitrage_target` properties. **This is the I-2 anti-swallow edit and gets its
   own mutation anchor.**
4. `get_status`: `peak_buffer_target` = effective T (what the strategy acts on); new `peak_buffer_cap` = raw; new
   `attain_target_mode`, `attain_target_basis` (dict: window, b0, b1, load_q_kwh, quantile, end_floor, risk_pct,
   solar_during_kwh, capacity_kwh, fallback_reason).

### Acceptance
- **Test:** `test_fixed_mode_byte_identical_all_paths`. Parametrised over the §6 matrix. Decision dicts are compared
  against a **pre-change oracle captured from the base commit** (fixture JSON, not re-imported code).
- **Test:** `test_validators_read_raw_cap` (cap 40 / poor 50 ⇒ violation fires with payload 40, in both modes).
- **Mutation:** point the validator at the property ⇒ the test above goes RED. Return raw cap from the property in sized mode ⇒ D2 tests go RED.

## D2 — Window sizing producer + chunk snapshot. *Gated per season×window by D0.1.*

1. `energy_tou.py`: NEW `get_high_rate_window_end(start_dt, lookahead_hours=24)` — the first off_peak hour after
   `start_dt`, walking forward like `get_next_high_rate_transition`. Summer handles 14-16 → 16-20 → 20-21 as **one**
   window only if consecutive non-off_peak. Plan review must rule which window attain targets in summer: today the
   off-peak boundary is 14:00 (mid_peak), and the mid-peak leg re-points to peak. Recommended for v1: **summer stays
   fixed** (q*≈0.97 ⇒ cap binds; §1.3), and sizing is enabled for shoulder and winter only via a per-season enable in
   the mode Select (§5).
2. `energy_battery.py`: NEW pure method `_compute_sized_target(now, soc, tou_period) -> (T, basis)` implementing §1.1.
   It takes no side effects and reads the estimator, which is injected from the coordinator (EC owns the predictor;
   `BatteryStrategy` has no predictor backref today — see `_battery_capacity_kwh` docstring). Wiring: EC sets
   `strategy._window_load_estimator = callable(window_start, window_end) -> (kwh_q, basis)` at setup, mirroring
   `attach_coord`. If the estimator is None ⇒ fallback_cap (INV-S4).
3. **Snapshot rules (INV-S2):**
   - Compute at the first off-peak tick where `_is_charge_window_open(now)` is True, or at the first arbitrage/attain
     evaluation in the chunk if earlier (rung ladder runs before the window opens).
   - Store `_sized_target_snapshot` with `_sized_target_chunk_id`.
   - Re-size only upward, at most once per 30 min (`SIZED_TARGET_RESIZE_MIN`, rung 1).
   - Clear in `reset_arbitrage_chunk`.
   - For the mid-peak D1b leg, the snapshot is for the PEAK window and is keyed separately by boundary.
4. **Restart (INV-S2b):** in `_adopt_attain_state_from_hardware` (cfg on), seed
   `_sized_target_snapshot = max(computed, min(cap, live reserve))` **before** the holding/charging classification
   reads `_peak_buffer_target`. If the cfg is unknown (defer), do not seed.
5. Reason strings: "Charging the battery from the grid to {T}% (sized for 17:00-21:00: ~{L} kWh + {F_end}% floor; cap {cap}%)".

### Acceptance
- **Test:** `test_sized_target_formula_hand_oracle`. Literals hand-derived in comments (e.g. `# L=18 kWh, cap 40 kWh ⇒ 45 %; F_end 30 ⇒ 75`).
- **Test:** `test_sized_target_no_solar_before_double_count`. The same day with a large forecast gives the same T; only the attain entry decision changes.
- **Test:** `test_snapshot_non_decreasing_within_chunk` (INV-S2); `test_snapshot_cleared_on_chunk_reset`.
- **Test:** `test_restart_never_lowers_held_buffer` (INV-S2b): cfg on, reserve 80, computed 55 ⇒ T 80 ⇒ no reserve drop.
- **Test:** `test_latch_exits_at_sized_target` (INV-S6): charging, soc reaches T=60 ⇒ holding, HOLD reserve 60, CFG off.
- **Test:** `test_degrade_to_cap_each_input` (INV-S4), one case per missing input.
- **Test:** `test_cfg_on_ticks_subset_of_fixed` (INV-S5) over the replay fixture.
- **Test:** `test_replay_window_sized_2026` — drives the real `determine_mode` over D0.6 rows. It asserts:
  - (1) T per window equals the fixture's hand T;
  - (2) shortfall windows ≤ D0.2's predicted count;
  - (3) no CFG-on in any high-rate hour.

  The docstring states that the replay asserts emitted decisions per recorded input, not a re-simulated SOC.
- **Mutation (Reviewer C):** per §1.2 class, neuter ONE reader at a time (read raw cap instead of T). A named test must
  go red each time: rung band, phase HOLD predicate, arbitrage CHARGE emission, attain entry `projected < T`, attain
  charging→holding, attain HOLD emission, completed-chunk HOLD, reboot adoption, mid-peak continuation gate. Use
  `PYTHONDONTWRITEBYTECODE=1` and a cleared `__pycache__`.
- **Live:** first shoulder chunk after deploy: `attain_target_basis` populated, `peak_buffer_target` < `peak_buffer_cap`
  when the window need is small, the attain reason cites the sized number, and SOC at 21:00 ≥ reserve with mid-peak
  import ≈ 0 (`sensor` grid import over 17-21).
- **Discriminating observation:**
  - Fix working: T < cap and mid-peak import ≈ 0.
  - Under-sizing failure: T < cap and grid import > 0.5 kWh in 17-21 while SOC sits at reserve before 21:00.
  - Seam failure: T shown < cap but `current_commanded_reserve` = cap.

## D3 — Risk adapters (Option 4). *Gated: D2 GO.*

- **Inclement:** no new code. `_floor_reserve` partial_hold already raises T at every emission. `full_hold` is
  untouched. Test pins that partial_hold 50 with T 40 ⇒ emits 50.
- **Forecast uncertainty:** quantile from the Select (§5), fed to the estimator.
- **Winter morning exposure:** `risk_pct` adder for windows starting before sunrise (`_daylight_bounds`, REUSED). The
  adder value is a D0-derived constant (rung 1, `SIZED_TARGET_PREDAWN_RISK_PCT`). It is only built if D0.1 shows the
  05-09 window's error is materially wider than the evening's. Otherwise it is 0 and documented.
- **Outage risk:** no outage-probability producer exists (grep found inclement only). **NOT built**; operator
  question §10 Q5.

## D4 — EV turn-taking (winter L2) and L1 share. *Gated: D0.4 / D0.5; operator Q7/Q8.*

- **Step 1 (config-first, recommended):** if D0.4 shows a sized charge fits in ≤ 120 min including the ~35-min lag,
  propose the operator set `arbitrage_charge_lead_time_min` to that value (Number, live). The EV keeps 21:00-03:00
  un-paused; the DP must-start-by 03:00 releases it before the window. **No code.** Record why.
- **Step 2 (only if step 1 is insufficient):** must-start-by precedence. During an active DP must-start-by claim or a
  charging L2 session with remaining need, **defer attain/arbitrage CHARGE entry** until
  `latest_start = b0 − (need_kWh / measured_charge_kW + lag + margin)`. This is a new time-coupled entry gate (state
  machine × time seam, the worst bug family). It needs its own falsifiable invariant ("CFG never on while a
  must-start-by-claimed EVSE is inside its claim, unless now ≥ latest_start") and is **Tier 3 on its own**.
  Recommend **carding it separately** rather than folding it in.
- **L1 share:** this changes the breaker invariant (1) of `_execute_breaker_safe_dispatch`. It is a **safety
  invariant**. **NOT built** without the operator's main-breaker rating and D0.5 numbers showing ≥ 20 % margin at
  80 % continuous. If built later: allow an EVSE classified L1 (measured < `DP_L1_RATE_THRESHOLD_KW`) to stay on
  during CFG iff `house_p99 + L1_max + battery_charge_max ≤ 0.8 × breaker_kW`. The breaker rating is a config-flow
  field (rung 2, per-deployment). Separate card.

---

## 5. Knobs (Numbers Get Knobs + named buckets)

| Knob | Rung | REUSED / NEW | Why this rung |
|---|---|---|---|
| `peak_buffer_target` Number → label "**Battery charge max**" (helper: "Most the battery is grid-charged to before a high-rate window") | 3 | REUSED (semantics: cap) | Operator already tunes it; cap = old value ⇒ today's ceiling |
| `attain_target_mode` Select: "Fixed (charge to max)" / "Sized for evening (shoulder+winter)" / "Sized all seasons" | 3 | NEW | Live kill switch. **Default "Fixed"** for new installs and the 2nd home; this house set by the operator after D0 |
| Sizing safety Select: "Lean" / "Balanced" / "Safe" ⇒ quantile P75 / P90 / P97 | 3 | NEW | Named buckets per configurability-clarity memo; default "Balanced" ≈ q* |
| `SIZED_TARGET_RESIZE_MIN` = 30 | 1 | NEW | Anti-flap protocol window; changing it needs review |
| `SIZED_TARGET_SOLAR_DURING_FACTOR` = 0.0 | 1 | NEW | Safety-adjacent; raise only on measured evidence |
| `SIZED_TARGET_PREDAWN_RISK_PCT` = D0 value or 0 | 1 | NEW (conditional) | Fitted from D0, like CONSUMPTION_REGRESSION_V1 |
| `WINDOW_LOAD_PROFILE_V1` (season×window share or medians) | 1 | NEW (if D0 picks E1/E3) | Fitted coefficients must be reproducible, so no live knob |
| `SIZED_TARGET_DISCHARGE_EFF` | 1 | NEW | Physical constant, D0-confirmed |
| `arbitrage_charge_lead_time_min` | 3 | REUSED | D4 step 1 lever |

Kill-switch semantics are documented on the mode Select itself: Fixed = byte-identical to pre-change.

## 6. Config-extreme matrix (tests parametrise)

| Axis | Values |
|---|---|
| cap | 30, 40, 80, 95, 100 |
| reserve_soc | 5, 10, 40, 60 |
| drain ladder | defaults {10,15,20,30,30}; poor 50 > cap 40 (inverted, legal); all = reserve |
| WAIT floor vs cap | floor 30 / cap 25 (T = cap); floor 60 / cap 80 |
| mode | fixed, sized-shoulder-winter, sized-all |
| safety bucket | Lean, Balanced, Safe |
| season / window | summer 14:00 (mid) + peak continuation; shoulder 17-21; winter 05-09 and 17-21; no high-rate transition (None ⇒ cap) |
| load estimate | 0 kWh, 5, 20, 60 (> capacity ⇒ cap), None |
| capacity | 40 kWh, None + LKG, None no LKG (⇒ cap) |
| inclement | allow_discharge, partial_hold 50, full_hold |
| restart | cfg on + reserve 80 + computed 55; cfg unknown; cfg off |
| time | chunk start, mid-chunk forecast worsens (raise), forecast improves (no lower), 15 min before boundary (handoff lead), after boundary |
| EV | none, L2 11.6 kW, L1 1.6 kW, both |
| SOC | None, 5, T−1, T, T+1, 100 |

Key cells (asserted):
- load 60 kWh ⇒ T = cap
- cap 25 < floor 30 ⇒ T = 25 (= today)
- forecast improves mid-chunk ⇒ T unchanged
- restart with reserve 80 ⇒ no drop

## 7. Docs (same commit)
- `ENERGY_COORDINATOR_MANUAL.md`:
  - §2.3: "charges to a target sized for the coming window, never above Battery charge max".
  - §3.1: knobs.
  - §4: new attrs.
  - §5.6: mode Select = kill switch.
  - §6: version row.
  - A winter section on W-1..W-4.
- `SPEC_ec_behaviour_contract.md`: rows A8/A13, Q3/Q6 resolution.
- `strings.json` / `translations/en.json`: label + helper text for the renamed Number. Remove "v4.5.0: replaces…" from user-facing text.
- Kanban: close the loop on `ATTAIN-SOLAR-AGGRESSION-INVESTIGATE-1`'s revisit trigger. This plan is a different lever (need-sizing, not solar-crediting).

## 8. Non-goals
- **Option 2** (summer: spend battery on true peak inside mid-peak). This is a discharge-policy change on the summer
  mid-peak hold leg. Card it separately, with revival when summer sizing data exists (next June).
- CFG on/off modulation, schedule-limit, `SOLAR_CAPTURE_FACTOR` (all closed with evidence).
- The parked soc-ladder D2 `> top drain` clamp (composes into the same property later; not in this cycle).
- Inclement precharge target.
- A new outage-risk producer.
- L1 share and must-start-by entry deferral (separate cards; §D4).
- Folding arbitrage CHARGE into attain (§10 Q6).

## 9. Tier and review plan
**Tier 3.** The change threads one value through a shared primitive with ~65 readers and four state machines (rung,
arbitrage phase, attain tri-state, completed-chunk HOLD). The failure mode is one missed reader (Bug Class #53) or a
raw/effective split-brain (killed-plan C-7). It is cost-and-comfort-impacting, and the area has a multi-fix-up
history (v5.3.8, v5.5.3, v5.17.x).
- **Plan reviews (2):**
  - (1) Completeness: re-grep every `_peak_buffer_target` reader on the build base and classify it per §1.2; confirm the 4 CFG-on producers; confirm the TOU walk for `window_end` in all 3 seasons; confirm the restart path order.
  - (2) Build-prediction. Likely builder errors: subtracting solar-before (F-DC); reading the cap in one emission; letting the snapshot drop on re-size; seeding the restart snapshot after classification; validators reading the property; hollow oracles that read `_compute_sized_target` in the assertion.
- **Build reviews:**
  - A: arithmetic / clamp / units.
  - B: state-machine integrity, restart, no suppression of legitimate CHARGE, fixed-mode byte-identity.
  - C: per-reader source mutation (§D2 list).
  - D: falsify INV-S1/S2/S2b/S5/S6 across the whole surface, including pre-existing code, with legal-config repros.
- Orchestrator re-greps and re-runs mutations; operator checkpoint before deploy.

## 10. Operator questions
1. **Economic gate.** Sizing alone is worth tens of $/yr by the decomposition in §1.3. Do you accept NO-GO if D0
   shows < ~$40/yr and no material winter or EV effect? The fallback is hand-set seasonal caps.
2. **Safety bucket default.** Balanced ≈ P90 matches the cost ratio. OK?
3. **F-DC.** Confirm solar-before stays in the "do we need grid" projection and is **not** subtracted from the target.
   Solar during the window defaults to 0.
4. **Winter overnight charge (W-1).** Today's code will grid-charge to 80 % every winter night from 02:00 starting Dec 1,
   then again in the afternoon. Do you want overnight attain toward 05:00 at all (sized), or should winter attain
   target only 17:00 (SPEC Q6)?
5. **Is the 80 % partly outage backup?** Sizing lowers evening SOC on light-load days. Should "outage risk" set a
   minimum (e.g. `T ≥ X%` always), and is there a signal you trust for it beyond inclement?
6. **"Grid charging owned by attain only".** Today arbitrage CHARGE (poor days) and inclement precharge also grid-charge.
   This plan sizes the arbitrage target too and adds no producer. Do you want arbitrage CHARGE folded into attain (a
   separate cycle)?
7. **L2 turn-taking.** Is a lead-time knob change (e.g. 180 → 120) acceptable even though it shortens the shoulder/summer
   windows too, or do you want the must-start-by entry deferral built (separate Tier-3 card)?
8. **L1 share.** What is the main breaker / service rating? Without it, L1 share stays NO-GO.
9. **Second home.** Default mode "Fixed" there (today's behaviour). OK?
10. **Lower clamp.** T ≥ max(reserve, tonight's WAIT drain floor). OK? Otherwise HOLD could sit below WAIT.

## 11. D0 report
*(to be appended by the probe run)*

## §D0 results (2026-10-03)

Read-only probe, `ssh ha "python3 -"` over `home-assistant_v2.db?mode=ro` (long-term hourly `statistics`, plus 7 days of
`states`) and `universal_room_automation.db?mode=ro`. Scripts: session scratchpad `d0_attain/probe.py` (+ s1-s10 discovery
scripts). Nothing was written to HA, the DBs or repo code. D0.6 (fixture) is out of scope for this run.

### D0.0 Producer check: which load series is real (changes the plan's entity assumption)
- **The Envoy "consumption" CT is NOT house load.** It leaves out battery-served load. Example, 09-01 17-21: Envoy
  consumption 10.1 kWh, but grid net 1.4 + solar 11.4 + battery discharge 26.9 − charge 0.7 = **39.0 kWh**. Envoy
  consumption stats also exist only from 2026-04-11.
- **SPAN `current_power` + `current_power_2` (hourly mean) IS house load.** Checked against the Envoy energy balance
  (net + production + discharge − charge) over 2,996 hours from April onward: totals 21,262 vs 20,928 kWh (+1.6 %),
  hourly ratio P10/P50/P90 = 0.79/1.015/1.10. The battery is not inside the SPAN mains reading, so subtracting
  `span_panel_battery_battery_power` is wrong. That correction was tried and gave 2 kWh for 10-01, against 19.3 kWh by
  energy balance. The series goes back to **2025-03-12**, so it covers **winter 2025-26**. Battery telemetry only starts
  2026-03-17, so winter had no battery flows in it.
- EV is subtracted using `garage_{a,b}_power_minute_average` (hourly mean). Both EVSEs sit inside the SPAN reading:
  09-30 01-05 shows SPAN 48.6 kWh with EV 21.2 kWh.
- `energy_daily.predicted_consumption_kwh` has only 202 rows. E0/E1 are scored on n=36-66 test windows only, and none
  in winter.

### D0.1 Window load (non-EV house kWh) and estimator accuracy
Split by date: first half = train, second half = test. Error = actual − estimate. The gate is the chosen estimator's
P90 ≤ 4.0 kWh and |bias| ≤ 1.5 kWh. "q\*-margin" is the q\* quantile of test errors.

| Season × window | days | actual mean / P90 / max kWh | E0 test MAE | E1 test MAE | E2 test bias / MAE / P90 / P95 | E3 test bias / MAE / P90 | chosen | q\* margin | **Gate** |
|---|---|---|---|---|---|---|---|---|---|
| shoulder 17-21 | 196 | 21.1 / 30.3 / 40.4 | 14.4 | 14.1 | +0.43 / 5.25 / **10.1** / 11.0 | +1.92 / 6.33 / 11.0 (n=31) | E2 | 10.4 (q 0.91) | **NO-GO** |
| summer 14-16 | 231 | 17.8 / 23.8 / 30.9 | 16.7 | 21.4 | +0.10 / 4.09 / **5.9** / 8.3 | +0.15 / 4.11 / 6.0 | E2 | 9.6 (q 0.97) | **NO-GO** |
| summer 16-20 | 229 | 32.7 / 41.1 / 51.1 | 34.0 | 46.0 | −0.95 / 5.94 / **7.6** / 10.1 | −0.57 / 5.85 / 8.2 | E3 | 12.9 (q 0.97) | **NO-GO** |
| summer 20-21 | 233 | 8.1 / 11.9 / 15.3 | 8.7 | 9.7 | −0.01 / 2.40 / 3.7 / 4.7 | 0.01 / 2.44 / 3.8 | E2 | 5.5 (q 0.97) | GO (moot: not an attain boundary) |
| winter 05-09 | 85 | 10.8 / 15.3 / 18.2 | – | – | +0.73 / 2.97 / **5.0** / 6.1 | n/a (temp history too short) | E2 | 5.1 (q 0.91) | **NO-GO (by 1 kWh)** |
| winter 17-21 | 87 | 12.9 / 17.5 / 23.7 | – | – | −0.45 / 2.92 / **3.7** / 6.4 | n/a | E2 | 4.1 (q 0.91) | **GO** |

- E0/E1 (the R1 daily prediction, scaled by hours or by window share) are useless at window level: MAE 9-46 kWh, with
  bias up to −47. The daily predictor does not carry window shape.
- E3's temperature term adds nothing. The fitted slope is about 0 in shoulder and summer, and the test MAE is no better.
- **Today's realised outcome with fixed 80** (Envoy SOC, April onward): shoulder 17-21 SOC at b0 median 96 %, at b1 median 46 %, b1 P10 = **10 %** (reserve).
  Median grid import is 1.2 kWh, P90 is 9.3 kWh. Summer 16-20 ends at a median of 55 %. In short: shoulder evening
  load (mean 21, P90 30 kWh) is often **larger** than the 80→20 % usable band (~23 kWh), so a cap of 80 already
  under-covers about 10 % of shoulder evenings.

### D0.2 Counterfactual replay ($ vs fixed 80)
Assumptions: chosen estimator plus q\* margin; capacity 40 kWh; η_dis 0.95; F_end 20 %; T = min(80, ceil(F_end + need)).
Over-charge cost = 10 % RTE × surplus, priced two ways: "low" uses the off-peak energy rate $0.0435, "eff" uses the
effective $0.086 including delivery and transmission. Shortfall versus fixed is priced at mid/peak minus off-peak.
Results are scaled to season days.

| Window | n | T mean (P10-P90) | kWh not grid-charged / window | extra shortfall windows | net $/yr low / eff |
|---|---|---|---|---|---|
| shoulder 17-21 | 159 | 80 (80-80), cap binds | 0 | 0 | 0 / 0 |
| summer 14-16 / 16-20 | 217 / 102 | 80, cap binds | 0 | 0 | 0 / 0 |
| winter 05-09 | 78 | 61.5 (59-65) | 7.4 | 4 | 2.54 / 5.37 |
| winter 17-21 | 80 | 66.4 (62-71) | 5.4 | 9 | 1.28 / 3.35 |
| (summer 20-21, not a boundary) | 219 | 56 | 9.5 | 6 | 4.83 / 9.74 |

**Total, all real boundaries: ≈ $4-9/yr**, against the **$40/yr** gate. Avoided grid-charge throughput is about
1,150 kWh/yr, all in winter. That is the cycle-wear argument (c), and the operator would have to value it. **Gate: NO-GO.**

### D0.3 TOU + shoulder sanity
- Live `sensor.ura_energy_coordinator_tou_period` attrs: `rate_source = "universal_room_automation/tou_rates.json (PEC, effective 2026-01-01)"`, `tou_file_status = "ok"`.
- `/config/universal_room_automation/tou_rates.json` (read directly) is identical to built-in `PEC_TOU_RATES`. Winter
  (months 12/1/2): off_peak 0-5, 9-17, 21-24; **mid_peak 5-9 and 17-21; no peak**. **§2 confirmed: the 05:00 morning
  mid-peak is real** (W-1..W-4 stand). The engine itself was not executed for a December date. This is a file read,
  and the file equals the built-in table.
- Shoulder sanity row:

  | Date | SPAN load | Battery discharge | Grid import | SOC 17:00 → 21:00 |
  |---|---|---|---|---|
  | 10-01 | 19.7 kWh | 17.9 kWh | 1.4 kWh | 75 → 23 % |
  | 10-02 | 17.9 kWh | 16.6 kWh | 1.7 kWh | 70 → 24 % |

  Load ≈ discharge + import, so the load series is consistent.
- **W-1 value check:** winter 05-09 mean load is 10.8 kWh. Serving it from overnight off-peak instead of 05-09 mid-peak
  is worth ≈ 10.8 × 0.043 ≈ $0.46/day ≈ **$40/winter** before RTE. On price alone, overnight attain toward 05:00 is
  worth keeping. Sizing it trims only ~7 kWh/night of throughput (same as above). Operator Q4 is still a wear/policy call.

### D0.4 EV × charge-window overlap; charge rate + lag
EV sessions are hourly-stats sessions (a session = hours with mean > 1.5 kW; L2 = hourly max > 3 kW), covering
2025-03-08 to 2026-10-01. The lead window is [b0 − 180 min, b0]: 14-17 shoulder/winter, 02-05 winter, 11-14 summer.

| Season | L2 sessions | mean kWh | sessions overlapping a lead window | median start hour |
|---|---|---|---|---|
| shoulder | 206 | 11.5 | **80 (39 %)** | 12 |
| summer | 133 | 11.5 | 33 (25 %) | 13 |
| winter | 67 | 14.8 | **40 (60 %)** | 10 |
| L1 (all) | 12 | 6.5-8.5 | 3 | 6-9 |

- `evse_paused_by_arbitrage` attr exists and was set on 1,352 strategy-state ticks in the last 7 days, for both
  garages. Garage_a L2 sessions over those days (09-28..10-01, 01:57-06:05) ran overnight, outside the pause.
- **Measured CFG charge** (7-day `states`, attain/arbitrage charge segments): battery power max 16.0-16.3 kW.
  Segments ran 16→81 % in 106 min and 14→83 % in 110 min, both measured from the window open (lag included).
  That is ≈ 0.6-0.65 pp/min end-to-end. One anomalous segment (10-01, 10→30 % over 419 min) is unexplained and not
  investigated.
- **A full fixed charge from about 15 % to 80 % already fits in ~110 min.** So the D4 step-1 knob turn
  (`arbitrage_charge_lead_time_min` 180 → 120) frees about one hour of EV time per chunk **without any sizing**. A sized
  charge (≈ 20→62-71 %) would fit in about 60-80 min.
- The plan's ~35-min actuation lag was not separately measured. The segment durations include it.

### D0.5 Breaker headroom
- CFG-on ticks (n = 1,658, 7 days): grid net power P50 9.7 kW, P99 22.2 kW, max **24.2 kW**. Battery charge max 16.3 kW.
- All-time hourly max Envoy net 35.0 kW. SPAN battery power range −32.6 to +28.9 kW (hourly max/min).
- House load at 02-05 (non-EV, hourly mean): P99 10.5 kW. SPAN hourly max at 02-05, including EV: P99 22.0 kW.
- L1 (garage_a 1-2.3 kW band) median 1.63 kW. EV maxima are garage_a 21.2 kW (hourly-max artefact or two vehicles,
  not resolved) and garage_b 7.5 kW.
- `sensor.span_*_main_breaker_rating` entities exist but are all `unavailable`. **The main-breaker rating is still
  unknown, so L1-share is NO-GO** (as planned). The operator must supply it (Q8).

### GO / NO-GO
| Stage | Verdict | Basis |
|---|---|---|
| D0.1 shoulder 17-21 | **NO-GO** | P90 10.1 > 4.0 kWh; q\*-margin 10.4 kWh, so the cap always binds |
| D0.1 summer (14:00 / peak) | **NO-GO** | P90 5.9-7.6 kWh; q\* 0.97, so the cap binds (matches §1.3) |
| D0.1 winter 05-09 | **NO-GO** (marginal) | P90 5.0 > 4.0 kWh |
| D0.1 winter 17-21 | **GO** | P90 3.7, bias −0.45 kWh |
| D0.2 value | **NO-GO** | ≈ $4-9/yr ≪ $40/yr |
| D0.4 EV contention | **Material, but solved by config** | 39-60 % of L2 sessions overlap the lead window; full charge fits in ~110 min, so the lead-time knob 180 → 120 needs no sizing |
| D0.5 L1 share | **NO-GO** | no breaker rating |
| **Overall (D1-D3)** | **NO-GO** | Only 1 of 5 real windows passes, the $ value is an order of magnitude below the gate, and the EV benefit is reachable by a knob turn |

**Recommendation:**
- Park D1-D3, with a revival trigger: the operator values cycle wear (~1,150 kWh/yr of avoided winter grid throughput),
  OR a window-level estimator gets P90 ≤ 4 kWh in shoulder.
- Instead, propose a config-first operator action: `arbitrage_charge_lead_time_min` 180 → 120 (D4 step 1).
- If wanted, a hand-set winter cap is available as a knob turn.
- Q4 (winter overnight attain) stays an operator policy call. On price it is worth about $40/winter, so keep it.
