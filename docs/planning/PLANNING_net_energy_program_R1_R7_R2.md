# PLANNING — Net-Energy Classification Program (R1 → R7 → R2)

## REV 2 — 2026-11-01 (planner refresh; the July text below is kept as history)

### What changed since July
- **Shipped:** R1 v1 estimator (v5.18.0) in shadow, `CONF_R1_ESTIMATOR_SHADOW_ONLY=True` `energy_const.py:170`, never flipped. R7 `EnergyProjector` shipped v5.18.0 and is live at five battery sites (`energy_battery.py:4268, 4339, 4436, 5438, 6261`). **R2 never built.**
- **No shadow value is persisted.** `energy_daily.predicted_consumption_kwh` is always the legacy arm while the gate is on; `shadow_predicted_consumption_kwh` is attrs-only (`energy_forecast.py:831`). July's "R1 shadow scoring" was never measurable from the DB. Rev-2 fix: the EC cycle's D5 prediction log records both arms.
- **Temperature input bug:** `_compute_v1` is fed the weather entity's current temperature at prediction time (`energy_forecast.py:~182-198, :399`, run ~midnight + sunrise), while the fit used daily-mean outdoor temperature (`scripts/energy/fit_consumption_regression.py:159-166`). Correct input = target-day forecast daily mean, the same feature as the fit.
- **Legacy predictor is broken, not just weak:** 19 legacy predictions of 350–2274 kWh/day between 06-26 and 10-04 (e.g. 2274 on 09-10). Any trust-hierarchy argument that "legacy is the safe incumbent" is false.
- **EV reality:** Envoy, Emporia and SPAN totals all include EV load (kanban correction_2026_10_03), so consumption actuals already contain EV. The 18.58 kWh/day constant is **unvalidated**. SPAN Garage A/B EVSE energy counters are unusable (Garage B jumps ~1e5–1e6 Wh/day Mar–Aug); hourly power sums give 2–3 kWh/day Mar–Sep, Oct 7.2 ± 8.7. `enphase_ev` and Emporia EV sessions not yet checked.

### Consumer evidence: who reads predicted consumption (re-run 2026-11-01)
| Consumer | file:line | Kind |
|---|---|---|
| `predicted_net_kwh` sensor | `sensor.py:12098` | display |
| forecast attrs incl. shadow | `sensor.py:12154` | display |
| `predicted_consumption_kwh` sensor | `sensor.py:12193`, `energy.py:12803` | display |
| `predicted_import_kwh` | `energy.py:12782` → `sensor.py:12142` | display |
| `energy_daily` write + error % | `energy.py:3569-3622`, `database.py:5060-5120` | DB record (persisted) |
| `battery_full_time` flat fallback | `energy_forecast.py:698` | display (no decision reader; `energy_projector.py:46` marks it out-of-family) |
| **DP drain-pause `house_load_kw`** | `energy.py:5216` via `_dp_house_load_kw` → real-tick `energy.py:5585` and shadow `:5336` | **DECISION input when source ∈ {`max_span_r1` (code default, `energy_const.py:2248`), `r1_base`}.** Live config: `energy_dp_enable=true`, `energy_dp_house_load_source="live_span"` → not consumed live today. |
| Battery class / arbitrage / attain / drain | `energy_battery.py:2667-2962` | **solar-only** (Solcast vs monthly thresholds); does NOT read predicted consumption. This is exactly what R2 would change. |

**Conclusion:** flipping R1 out of shadow changes display, the DB record, and one latent decision input (DP house load) that is dark in this install but live under the code default. Nothing in battery reserve / arbitrage / attain / drain / HVAC / EVSE gating reads it until R2. So: **R1-flip + temp fix + EC display work = Tier 2-DB is defensible, provided the DP path is fenced.** R2 (and any PV10 weighting) stays Tier 3.

### Backtest (one-shot, 2026-11-01; actuals from `energy_daily`, temp = daily mean of `sensor.thermostat_bryant_wifi_backhallway_outdoor_temperature`; 133 usable days)
MAE / bias (pred − actual), kWh/day:

| Month | n | legacy (raw) | v1 @ `avg_temperature`* | v1 @ daily mean | v1 @ daily max |
|---|---|---|---|---|---|
| Mar | 4 | 70.5 / −70.5 | 41.9 / +41.9 | 51.9 / +51.9 | 93.5 / +93.5 |
| Apr | 9 | 56.8 / −51.9 | 22.4 / +22.4 | 28.4 / +28.4 | 51.3 / +51.3 |
| May | 22 | 40.4 / −25.0 | 22.9 / +11.1 | 23.5 / +17.7 | 51.6 / +51.6 |
| Jun | 26 | 52.8 / −14.8 | 19.5 / +3.5 | 16.7 / +9.7 | 39.3 / +38.1 |
| Jul | 17 | 85.6 / +43.8 | 39.6 / +5.5 | 36.0 / +24.1 | 57.5 / +55.9 |
| Aug | 13 | 77.6 / +45.4 | 29.9 / +11.2 | 32.3 / +7.9 | 48.2 / +48.0 |
| Sep | 13 | 688 / +630 | 50.5 / −23.4 | 45.4 / −14.7 | 33.2 / +26.8 |
| Oct | 29 | 209 / +209 | 16.7 / +11.9 | 21.2 / +16.5 | 56.4 / +56.4 |

\* `energy_daily.avg_temperature`; NOT confirmed to equal the prediction-time temperature, so this column is not a true "as-run live" reconstruction. True live temps (00:05 / sunrise weather state) were not recovered.

Refit (OLS, CDD+HDD+intercept, train Mar–Sep n=104, test Oct n=29): Oct MAE 14.1 (base 60/62), 14.5 (65), 15.2 (68); bias ≈ −3. CDD slope ≈ 4.3 kWh/°F vs v1's 2.20. HDD terms unstable (one cool month). Balance point barely matters on this data.

Readings: (1) v1 beats legacy every month. (2) Daily max is the wrong feature; daily mean is right (it matches the fit). (3) v1 runs **positive-biased** (+8 to +24 most months with daily mean); the 2025-fit intercept/season/EV constants are stale, not just the temp input. (4) A 2026 refit cuts Oct MAE to ~14 with near-zero bias. Mean actuals: 90 (Mar) → 181 (Sep) → 120 (Oct) kWh/day.

### Revised R1 scope (for the merged cycle)
1. Feed `_compute_v1` the **target-day forecast daily mean** (`AggregationEntity._get_forecast_temp` `aggregation.py:1187` gives high/low; mean ≈ (high+low)/2 unless hourly forecast is available; plan reviewer to verify which fields the configured weather entity exposes).
2. **Re-fit** `CONSUMPTION_REGRESSION_V1` → `_V2` on 2025-06..2026-10 daily-mean data with the fit script; fitted balance point (research §2); EV folded into the base until an EV series is trustworthy (constant EV term dropped or re-estimated, not assumed). Keep V1 constants for one release (kill-switch revert).
3. Flip `CONF_R1_ESTIMATOR_SHADOW_ONLY` → False only after the D5 log shows v2 MAE ≤ legacy (trivially true) AND v2 |bias| ≤ 10 kWh/day over ≥14 days in shadow. Until then both arms are logged.
4. **DP fence:** before the flip, either pin `_dp_house_load_kw` to `live_span` semantics for the R1 term or add an explicit test that `max_span_r1` behaviour is a declared, reviewed decision change. Recommended: keep `max_span_r1` reading v1 but require the D-reviewer to price it (max() with a live value means v1 only matters when it exceeds live load — bounded upside).

### R2 still worth it?
Not re-measured (solar-only vs net misclassification probe skipped this pass). July's B0 said solar-only was wrong on 65% of days, direction undercharge (~$120/yr). With a corrected estimator that number needs re-running on Aug–Oct data **before** R2 is planned — that probe is R2's D0 gate. R2 remains Tier 3 and absorbs the PV10 pessimism weight idea (research §5).

### Program structure, rev 2
- **Cycle α (Tier 2-DB, merged with EC-COST-AND-FORECAST-MATH-1):** EC savings/cost D1–D7 + R1 temp fix + v2 refit + both-arm prediction log + guarded shadow flip. See `PLANNING_ec_savings_and_tomorrow_forecast.md` §12.
- **Cycle β (Tier 3, unchanged discipline):** R2 widener + PV10 weight, gated on the re-run misclassification probe and ≥14 days of α's log.

---

**Filed:** 2026-07-16 · **Author:** planner (ura-planner framing) · **Program owner:** Energy Coordinator (EC)
**Tier (program-wide, operator-mandated):** **AUTO TIER 3** for every phase.
Operator directive: *"very sensitive work that needs x-checking at all stages; EC is the most important IP we have next to HC."*
Program builds NOTHING in this doc — plan only. Each phase is its own cycle with its own planning doc, its own baseline tag, its own 4 framing-disjoint reviews (A/B/C + D adversarial completeness), its own mutation-anchored tests executed for real, orchestrator independent verification before ship, and an operator checkpoint BEFORE deploy.

Sequencing (fixed): **R1 (estimator rebuild + shadow) → R7 (projection unification) → R2 (net-aware widener)**. R8 (DPM / HVAC precool / EV solar-aware adoption of the new primitive) is a FOLLOW-ON to be evaluated after R2 has ≥30 days of live data — NOT bundled here.

---

## Institutional context verified

Per CLAUDE.md this section is the proof-of-work.

### Prior-art surfaces surveyed (code read end-to-end during scoping)
- `custom_components/universal_room_automation/domain_coordinators/energy_forecast.py` — `_do_prediction` (:211), `_estimate_consumption` (:239), `_predicted_net_kwh` published at :225, sunrise anchoring at :200, occupancy-weighted blend at :300, temp regression fields `_temp_regression_base` / `_temp_regression_coeff` at :254-263 (already structural — R1 slots in as coefficients + regression shape upgrade, NOT a new field).
- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — `_classify_forecast` at :1140-1173, `classify_solar_day` at :1175-1205 (monthly P25/P50/P75; monthly mode NEVER returns `very_poor` — R6 rider). Arbitrage gate at :4166-4183 (opens iff class ∈ {poor, very_poor}). Attain branch at :4189+. Drain-target map built at :311 from `energy_const.DRAIN_TARGETS`.
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py` — `SOLAR_MONTHLY_THRESHOLDS` at :81, `DRAIN_TARGETS` at :531-535. Inclement CONFs at :~1215+ (surface pattern reused for R2 gate config).
- `energy_daily` DAO — carries `consumption_kwh`, `solar_production_kwh`, `predicted_consumption_kwh`, `prediction_error_pct` (per B0 §E). R1 shadow-mode consumer is this table; no schema change needed for R1.
- Inclement I-BH1 / I-BH2 / I-D3 (v5.17.5) — blind-hold total contract. R2 must NOT allow a "net-aware widener" path to open a fresh grid import while degraded. Every phase's D reviewer re-enumerates against these.
- I-AH1 (v5.17.4 rung projection additive-surplus shape) — R7 unifies rung + attain + reason projections onto ONE primitive; the additive-surplus shape and solar-horizon rate bound are the invariants that must survive the unification byte-identical on the no-op path.
- `.claude/skills/ura-energy-strategy-reference/` and `.claude/skills/ura-energy-invariants-campaign/` — read; the campaign skill's leak-taxonomy (Bug Class #53 computed-but-not-consumed) is the framing template for R7 D-pass.

### Prior planning docs consulted
- `docs/planning/B0_net_energy_classification_probe.md` — the evidence base. Headline: solar-only classification wrong 65% of days; direction is UNDERCHARGE ($120/yr), not overcharge ($13/yr); consumption estimator R²=−1.55 must be rebuilt; temp regression achieves R²=0.38–0.42, CDD dominant at 3.05 kWh/CDD; day-of-week R²=0.01 (dead signal). R5 CLOSED: full-span Enlighten export landed 2026-07-16.
- `docs/reviews/code-review/v5_17_4_rung_projection_solar_bound.md` — I-AH1, rung projection additive-surplus shape + solar-horizon rate bound; the shape R7 must preserve.
- `docs/reviews/code-review/v5_17_5_blind_hold_tier3.md` — I-BH1 / I-BH2 / I-D3 blind-hold total contract; the invariants R2's widener must NOT relax (widener may only open the gate under SIGHTED SOC + FRESH desire; blind-hold vetoes the widener like it vetoes attain).
- (Skim) `docs/reviews/code-review/` — v5.5.0 inclement (Bug Class #53 origin), v5.15.0 (drain-target reserve-emit surface — R2 touches the same map).

### Memory bodies pulled
- `project_inclement_arbitrage_wait_floor_gap.md` — resolved v5.5.3; R2 must not reopen this via a widener path that bypasses the inclement reserve floor.
- `project_battery_soc_envoy_not_span.md` — Envoy is authoritative SOC; any R7 projection primitive reads Envoy tier per the SOC-source contract.
- `feedback_no_fabrication_dhcp_incident.md` — do not attribute behaviors we have not read in this session.

### Design docs read
- `docs/Coordinator/EnergyCoordinator.md` (skim — projection sites, arbitrage/attain owner map).
- `docs/Coordinator/EnergyForecast.md` if present — else energy_forecast.py source is authoritative for this cycle.

### Greps run — REUSED vs NEW
- `predicted_net_kwh` — **REUSED**, `energy_forecast.py:225`. R2 consumes it; no new attr needed at the source.
- `_estimate_consumption` — **REUSED**, `energy_forecast.py:239`. R1 replaces DOW-blend arm with reviewed constants + season+HDD/CDD regression; keeps method signature; keeps occupancy blend arm intact.
- `_temp_regression_base` / `_temp_regression_coeff` — **REUSED** fields. R1 upgrades their source (offline-fit constants baked in as defaults; runtime self-scoring can override).
- `SOLAR_MONTHLY_THRESHOLDS` — **REUSED**, `energy_const.py:81`. R2 does NOT replace; adds a parallel `NET_KWH_WIDENER_THRESHOLDS` (or single scalar).
- `classify_solar_day` — **REUSED**, `energy_battery.py:1175`. R2 does NOT replace; R2 wraps its consumers with a widener that may bump the returned class one step worse.
- `project_soc_at_boundary` / net-day classifier service — **NEW** primitive owner (R7). Justification: the rung projection (v5.17.4), the attain-entry projection, the reason-string projection, and the attrs each compute their own approximation of "SOC at boundary" — I-AH1 review record explicitly notes the divergence risk. R7 collapses to one owner. Grep confirms multiple call sites compute `soc + rate*hours` or `soc + (rate+surplus)*hours` independently.
- `prediction_error_pct` — **REUSED**, `energy_daily` DAO column. R1 shadow-scoring writes to it; no schema change.
- `NET_KWH_WIDENER_THRESHOLD` (or bounds table) — **NEW** const. Justification: no equivalent net-kWh threshold exists; solar-only P25/P50/P75 does not encode net. Reviewed constant baked from R1 fit backtest (R2).
- `CONF_NET_WIDENER_MODE` / `CONF_NET_WIDENER_ENABLED` — **NEW** CONF. Justification: kill-switch. Follows the `CONF_INCLEMENT_*` surface pattern (energy_const.py :~1215+).
- `arbitrage_cycles.solar_class` / `arbitrage_cycles.net_class` columns — **NEW** DAO fields (R3 rider inside R2). Justification: B0 §F.6 called out that the current tables don't persist class; without it, the next probe cannot measure the deployed gate.

If any grep target above turns out to have an existing sibling I missed, the phase planning doc revises to REUSED before its build starts.

---

## Program-wide invariants (survive ALL phases; D re-enumerates each phase)

- **I-NE1 — blind-hold supremacy.** Any net-aware widener MUST fail-closed under blind-hold (I-BH1/2) and MUST NOT re-dispatch from stale desire (I-D3). Widener is a *sighted-only* modifier.
- **I-NE2 — inclement floor supremacy.** Widener MUST NOT override the inclement partial_hold reserve floor (v5.5.3 fix; Bug Class #53). Floor wins.
- **I-NE3 — projection singleton (post-R7).** After R7 lands, every consumer that answers "SOC at boundary X" MUST call the ONE primitive. No caller may recompute additive-surplus / solar-horizon bound independently. D-pass re-enumerates every emitter.
- **I-NE4 — observability mirrors decision.** Attrs on `sensor.ura_energy_coordinator_battery_strategy` (and siblings) MUST display the SAME numbers the decision used — not a re-derivation. Operator directive: *"mirrored at minimum."*
- **I-NE5 — shadow before actuation.** R1's estimator lands in SHADOW MODE (log-only; no consumer sees the new number) for N days before R2 is allowed to consume it. R2 lands with a kill-switch CONF defaulting OFF for the first live proof day.
- **I-NE6 — rollback is a constant flip.** Each phase's live behavior toggles via one constant / one CONF / one kill-switch. No phase ships a rollback that requires a code revert.

---

## R1 — Consumption estimator rebuild (offline-fit constants + shadow scoring)

### Falsifiable invariant
*Under R1, `predicted_consumption_kwh` on any masked-clean holdout day satisfies MAE ≤ 20 kWh across the holdout split (exact split: **train = 2025-02-25 → 2026-04-30, holdout = 2026-05-01 → 2026-07-15**, both masked per README zero-runs). D falsifies by finding a masked-clean holdout day where the fitted model produces > 20 kWh error, OR by finding a runtime path that bypasses the new coefficients and falls back to the old DOW blend.*

### Scope
1. **Offline fit (committed script, reproducible).** `scripts/energy/fit_consumption_regression.py` fits season + HDD/CDD (base 65°F) against `data/enphase/site_energy_{consumption,production}_daily_2025-02-24_to_2026-07-15.csv`, masking outage zero-runs and the 2026-05-28 negative day per `data/enphase/README.md`. Drops day-of-week entirely (R²=0.01 per B0 §E). Outputs a reviewed-constant block written into `energy_const.py` (e.g. `CONSUMPTION_REGRESSION_V1 = {"base": ..., "cdd_coeff": ..., "hdd_coeff": ..., "season_dummies": {...}, "fit_date": "2026-07-16", "train_span": "2025-02-25..2026-04-30", "holdout_MAE_kwh": ...}`). Script is the x-check: any reviewer re-runs it and gets byte-identical constants.
2. **Runtime consumer.** `_estimate_consumption` (`energy_forecast.py:239`) grows a new arm: if `CONSUMPTION_REGRESSION_V1` present AND temp available AND season derivable, use `base + cdd_coeff*CDD + hdd_coeff*HDD + season_dummy`. DOW arm removed (not deweighted — removed; R²=0.01 = dead signal). Occupancy blend arm at :285 untouched.
3. **Shadow scoring loop.** Nightly (existing `energy_daily` roll site), write `predicted_consumption_kwh` (already exists) and populate `prediction_error_pct` with `(pred − actual) / actual`. Add a new column `predicted_consumption_source` (`'v1_regression'` / `'dow_legacy'` / `'fallback'`) — **NEW DAO column, DDL-only migration, additive**.
4. **Shadow mode gate.** New `CONF_R1_ESTIMATOR_SHADOW_ONLY` (default TRUE). When TRUE, `_predicted_consumption_kwh` published to attrs + energy_daily but NO downstream consumer (R2, DPM, EV solar-aware) reads it. R2 phase-gate will flip it OFF after N=14 shadow days pass.
5. **Backtest as CI test.** `tests/energy/test_consumption_regression_backtest.py` loads the CSVs, applies R1 fit, asserts MAE ≤ 20 kWh on the holdout split. This test is the durable regression harness.

### REUSED vs NEW
- REUSED: `_estimate_consumption`, `_temp_regression_base/coeff` (repurposed as the loaded constant), `predicted_consumption_kwh`, `prediction_error_pct`, `energy_daily` table.
- NEW: `scripts/energy/fit_consumption_regression.py`; `CONSUMPTION_REGRESSION_V1` const; `predicted_consumption_source` DAO column (additive migration); `CONF_R1_ESTIMATOR_SHADOW_ONLY`; backtest CI test.

### Acceptance criteria
- **Verify (offline):** fit script committed, re-runnable, deterministic (fixed seed / no randomness). Reviewer B independently re-runs and confirms byte-identical constants.
- **Verify (backtest):** `test_consumption_regression_backtest.py` PASSES with MAE ≤ 20 kWh on the stated holdout split. `pytest -k consumption_regression_backtest` GREEN.
- **Verify (mutation-anchored):** ura-reviewer C mutates the runtime consumer to fall back to the DOW arm; a specific test fails (site-mutation authority).
- **Sensor:** `sensor.ura_energy_coordinator_predicted_consumption_kwh` attr `source == 'v1_regression'` post-restart.
- **Sensor:** `sensor.ura_energy_coordinator_prediction_error_pct` populates nightly.
- **Test:** `test_consumption_regression_backtest`, `test_estimator_shadow_only_gates_consumer`, `test_dow_arm_removed`, `test_fit_script_reproducible`.
- **Live (Day 0–14 shadow):** `energy_daily.predicted_consumption_source = 'v1_regression'` for each day. Rolling 14-day MAE ≤ 22 kWh (looser than backtest to allow noise). No R2/DPM/EV code path reads the new value (grep confirms; D re-enumerates).
- **Live (post-shadow):** operator checkpoint reviews the 14-day shadow report; flips `CONF_R1_ESTIMATOR_SHADOW_ONLY` OFF only as R2's prerequisite.

### Tier-3 protocol for R1
- **Baseline tag:** `pre-review-vX.Y.Z-R1`.
- **4 framing-disjoint reviews:**
  - A — offline fit correctness (arithmetic, masking, holdout leakage, unit sanity — consumption CSV = kWh, production CSV = **Wh** per README; conversion is a load-bearing site).
  - B — runtime integration + backward compat (no consumer reads new value while shadow flag TRUE; DOW arm truly removed everywhere; DDL migration additive; RestoreEntity round-trip).
  - C — mutation-anchored test authority via REAL per-site source mutation. Neuter each load-bearing site (fit-script mask, runtime source selector, shadow gate, DDL) one at a time; confirm a specific test fails.
  - D — adversarial completeness. Enumerates every path that could bypass the new regression (fallback branches, occupancy-blend interaction, temp=None path, boot before constants load, unit-mismatch on the Wh production CSV). Includes pre-existing paths, not just the diff.
- **Orchestrator independent verification before ship:** re-run the fit script, re-run one C mutation, grep every reader of `_predicted_consumption_kwh` and confirm shadow gate covers all.
- **Operator checkpoint BEFORE deploy** (fit constants + backtest MAE + kill-switch state).
- **Post-deploy live validation (Review E):** README write-back with observed 14-day shadow MAE; PASS/FAIL per acceptance row.

### Rollback
Flip `CONF_R1_ESTIMATOR_SHADOW_ONLY` TRUE (already default). If constants are wrong, revert the const block; runtime fallback to occupancy blend + fixed-multiplier bands (pre-R1 behavior).

---

## R7 — Projection unification (one primitive)

### Falsifiable invariant
*Under R7, every consumer that answers "battery SOC at boundary T given current SOC, rate, solar horizon" MUST call the ONE primitive `EnergyProjector.project_soc_at_boundary(now, boundary_t)`. Under no reachable (legal-config) state can any of: the rung projection, attain-entry projection, reason string, or attribute display, compute the answer via an independent additive-surplus / solar-horizon rate expression. D falsifies by finding one such independent computation path in the code, live or dead.*

Corollary invariants preserved: **I-AH1** (additive-surplus shape + solar-horizon rate bound survive byte-identical on the no-op path); **I-BH1/2/D3** (projector fails-closed / returns `None` under blind-hold; no consumer may substitute a default).

### Scope
1. **New primitive.** `energy_projector.py` (new module under `domain_coordinators/`) exposes `class EnergyProjector` with `project_soc_at_boundary(now, boundary_t, ctx) -> ProjectionResult(soc_pct, source, horizon_min, rate_pct_per_h, surplus_pct, blind: bool)`. Uses I-AH1 additive-surplus shape and solar-horizon rate bound. Reads Envoy SOC tier (per SOC-source contract). Returns `None` (or a sentinel with `blind=True`) under blind-hold.
2. **Consumer migration.** Each existing site is rewritten to call the primitive:
   - rung projection (v5.17.4 site, `energy_battery.py`)
   - attain-entry projection (`energy_battery.py:4189+`)
   - reason string builder(s) — every reason that quotes a "projected SOC" value
   - attrs on `sensor.ura_energy_coordinator_battery_strategy` (and rung/attain attrs)
   - attain-reason entry-time rider (per operator addendum): reason includes the entry-time projected SOC + horizon used, so observability mirrors the decision.
3. **Byte-identical no-op path.** For a no-blind, no-widener state, the primitive returns EXACTLY the value the old rung site returned. Recorder-based diff test (compare pre-R7 vs post-R7 emissions across a synthetic 24h scenario) MUST show zero divergence on the no-op path.
4. **Kill-switch.** `CONF_R7_USE_UNIFIED_PROJECTOR` (default TRUE at ship; provided as a rollback lever only). If flipped FALSE, each consumer falls back to its pre-R7 inline expression (kept behind a `if not USE_UNIFIED` branch for one release, then removed in the following release).

### REUSED vs NEW
- REUSED: additive-surplus shape (v5.17.4); solar-horizon rate bound (v5.17.4); Envoy SOC tier reader; blind-hold gate.
- NEW: `EnergyProjector` module + `ProjectionResult` dataclass; `CONF_R7_USE_UNIFIED_PROJECTOR`; entry-time projected-SOC field on attain-reason attr.

### Acceptance criteria
- **Verify (grep):** post-migration, grep of `soc.*\+.*rate.*\*.*hours` (and variants) returns ZERO hits outside `energy_projector.py`. D re-runs this grep independently.
- **Verify (byte-identical no-op):** synthetic-scenario diff test: 0 divergence between pre-R7 and post-R7 emission stream on a no-widener, sighted state.
- **Verify (blind-hold):** projector returns `None`/`blind=True` for every degraded tier state matrix D enumerates. Every consumer handles `None` fail-closed.
- **Verify (mutation-anchored):** C mutates the projector to return a wrong number; each consumer's dedicated test fails (proves consumer routes through primitive).
- **Sensor:** `sensor.ura_energy_coordinator_battery_strategy` attr `attain_reason` includes `projected_soc_at_peak_entry_pct` + `horizon_min` (mirrors decision).
- **Sensor:** rung attrs (bands 77/83 style from v5.17.4) still inside [0,100]; horizons annotated.
- **Test:** `test_projector_no_op_byte_identical`, `test_projector_blind_returns_none`, `test_projector_grep_singleton` (a test that greps the source tree for banned patterns and fails on hit), plus per-consumer mutation tests.
- **Live:** on a no-arbitrage-entry day, `attain_reason` and rung attrs show the SAME `projected_soc` value the log-line's decision cited (mirror check).
- **Live:** on the next arbitrage-entry day, entry-time rider shows projected SOC + horizon used AT ENTRY (frozen), and reversion sweep does NOT re-derive.

### Tier-3 protocol for R7
- **Baseline tag:** `pre-review-vX.Y.Z-R7`.
- **4 framing-disjoint reviews:**
  - A — primitive correctness (additive-surplus shape preserved; solar-horizon bound preserved; SOC-source tier hierarchy; unit sanity).
  - B — consumer-migration completeness (every site migrated; no double-emit; no consumer computes independently; kill-switch fallback truly reproduces pre-R7 behavior).
  - C — mutation-anchored test authority per site (real source mutation on the projector AND per consumer; confirm each consumer's site-specific test fails).
  - D — adversarial completeness / diff-blind. Re-enumerates the ENTIRE invariant surface (I-AH1, I-BH1/2, I-D3, I-NE3). Includes pre-existing sites that might still compute independently and weren't in the diff (this is the v5.5.3 D-HIGH-1 lesson). Every leak comes with a concrete legal-config repro.
- **Orchestrator independent verification before ship:** personally re-grep every projection site; re-run one C mutation on the load-bearing consumer; confirm blind-hold behavior in a synthetic degraded state.
- **Operator checkpoint BEFORE deploy** (grep-singleton proof + byte-identical diff report + blind-hold enumeration).
- **Post-deploy live validation (Review E):** README write-back — mirror check PASS, blind-hold handling PASS (or "not exercised, monitor").

### Rollback
Flip `CONF_R7_USE_UNIFIED_PROJECTOR` FALSE; consumers fall back to inline expressions for one release. Full revert is a const-block flip, no code revert.

---

## R2 — Net-aware class widener (attacks the $120 undercharge leak)

### Falsifiable invariant
*Under R2, on the 361-day B0 backtest, the widener converts **≥ 70% of the 59 D2 undercharge days** (solar-class ∈ {good, excellent} AND net < −30 kWh) to a **gate-open** classification (i.e., widened class ∈ {poor, very_poor}) WITHOUT adding more than **5 net-new false-charge days** (days where widened class is gate-open but net ≥ −14 kWh — the D1 shape). The net-kWh threshold is TUNED to this constraint pair, and the backtest is committed as an executable test. D falsifies by finding a legal-config state where the widener opens a fresh grid import while (a) blind-hold active, (b) inclement partial_hold active, (c) I-NE2 floor engaged, or (d) attain-entry guards would otherwise veto.*

### Scope
1. **Widener primitive.** In `energy_battery.py`, wrap `classify_solar_day` consumers with a step: if `predicted_net_kwh` (recalibrated per R1 — enforced via `predicted_consumption_source == 'v1_regression'`) is below `NET_KWH_WIDENER_THRESHOLD` AND solar-class ∈ {good, excellent}, bump the class **one step worse** (excellent → good → moderate → poor). Never skip more than one step. Widener is a *pure function* over (`solar_class`, `predicted_net_kwh`, thresholds, R1-source flag) — no side effects; testable in isolation.
2. **Consumer wiring.** Widened class is consumed by:
   - arbitrage gate (`energy_battery.py:4166-4183`)
   - attain-entry branch (`energy_battery.py:4189+`)
   - drain-target lookup (`DRAIN_TARGETS`)
   - reason string ("widened due to net-kWh")
   - attrs on `sensor.ura_energy_coordinator_battery_strategy`: `solar_class_raw`, `solar_class_widened`, `net_kwh_used`, `net_kwh_threshold`, `widener_active`, `widener_source_flag`. Observability mirrors decision (I-NE4).
3. **R6 resolution (`very_poor` unreachable in monthly mode).** Deliberately resolve: **keep monthly mode's ceiling at `poor`**; widener may bump `poor` → `very_poor` only via the net-kWh path (documents the class as a "net-severity" signal, not solar-severity in monthly mode). Alternative considered and REJECTED (adding a `very_poor` monthly threshold) because B0 shows `poor` already covers the low-solar tail and confuses the widener's semantic.
4. **R3 rider — persistence.** DAO migration on `arbitrage_cycles` (or `energy_daily`, per DAO owner review at build): add `solar_class_raw`, `solar_class_widened`, `predicted_net_kwh_snapshot`, `solcast_forecast_kwh_snapshot`. Additive migration only. Feeds the next probe.
5. **Kill-switches.**
   - `CONF_R2_WIDENER_ENABLED` (default FALSE on first deploy; operator flips ON after 1 live proof day of R2 attrs showing widened=solar for a no-widener day).
   - `CONF_R2_WIDENER_SHADOW_ONLY` (default TRUE on first deploy — attrs populate but consumers still read raw class). Two-stage rollout: shadow-only for N=7 days, then flip both flags to promote to live.
6. **Blind-hold + inclement guards.** Widener is a *sighted-only, non-inclement* modifier. Under blind-hold OR inclement partial_hold/full_hold, widener returns raw class unchanged. Enforced at widener entry with two explicit guards, each with its own mutation-anchored test.

### REUSED vs NEW
- REUSED: `classify_solar_day`, `predicted_net_kwh`, arbitrage gate, attain branch, `DRAIN_TARGETS`, `SOLAR_MONTHLY_THRESHOLDS`, R7 projector (widened class does not affect projection shape — R7 primitive still reads raw SOC/rate; widener acts on *class* only).
- NEW: `NET_KWH_WIDENER_THRESHOLD` (reviewed const, tuned from backtest); `CONF_R2_WIDENER_ENABLED`, `CONF_R2_WIDENER_SHADOW_ONLY`; `solar_class_raw` / `solar_class_widened` / `net_kwh_used` / `net_kwh_threshold` / `widener_active` / `widener_source_flag` attrs; `arbitrage_cycles` (or `energy_daily`) columns per R3 rider; blind-hold + inclement guards at widener entry.

### Acceptance criteria
- **Verify (backtest as CI test):** `tests/energy/test_r2_widener_backtest.py` loads the 361-day B0 dataset, computes widened classes at `NET_KWH_WIDENER_THRESHOLD = <tuned>`, asserts:
  - `converted_undercharge_days / 59 >= 0.70`
  - `new_false_charge_days <= 5`
  The tuned threshold is committed alongside the assertion values; changing the threshold requires re-running and re-committing.
- **Verify (invariant preservation):** dedicated tests for I-NE1 (widener returns raw under blind-hold), I-NE2 (widener returns raw under inclement hold, and even when it opens the gate, inclement floor is respected downstream), I-NE5 (widener refuses when `predicted_consumption_source != 'v1_regression'`), I-AH1 / I-BH1/2 / I-D3 (unchanged by R2).
- **Verify (mutation-anchored):** C mutates each of the 4 consumer sites (arbitrage gate, attain-entry, drain-target lookup, reason) to read raw class instead of widened; each dedicated test fails.
- **Verify (R6 deliberate):** test asserts monthly mode never returns `very_poor` from the base classifier; only widener may.
- **Sensor:** `sensor.ura_energy_coordinator_battery_strategy` attrs `solar_class_raw`, `solar_class_widened`, `net_kwh_used`, `net_kwh_threshold`, `widener_active`, `widener_source_flag` all present post-restart.
- **DAO:** `arbitrage_cycles` (or `energy_daily`) rows carry raw + widened class + net + solcast snapshot for every day post-migration.
- **Test:** `test_r2_widener_backtest`, `test_widener_blind_hold_returns_raw`, `test_widener_inclement_returns_raw`, `test_widener_refuses_stale_estimator_source`, `test_widener_at_most_one_step`, `test_r6_monthly_no_very_poor_from_base`, per-consumer mutation tests, DAO round-trip.
- **Live (Day 0 shadow):** `widener_active` attr populates; `solar_class_widened` may differ from `solar_class_raw` on high-consumption sunny days. NO downstream consumer reads widened (shadow gate). Grep + log check confirm.
- **Live (post-shadow promotion, operator checkpoint):** on the first day widener actually promotes (e.g., forecast good + predicted_net < threshold), arbitrage gate opens, drain-target deepens, `attain_reason` cites "widened due to net-kWh = X vs threshold Y", and the observed post-day energy_daily row shows the imported deficit landed in off-peak (not peak/mid-peak). README write-back with $ estimate for the day (vs the counterfactual solar-only outcome).
- **Live (blind-hold day):** confirm widener returned raw and gate stayed closed.
- **Live (inclement day):** confirm widener returned raw and inclement floor governed.

### Tier-3 protocol for R2
- **Baseline tag:** `pre-review-vX.Y.Z-R2`.
- **4 framing-disjoint reviews:**
  - A — widener arithmetic + threshold tuning (backtest assertion values, at-most-one-step invariant, R6 deliberate resolution).
  - B — consumer-migration correctness + inclement/blind-hold precedence (I-NE1, I-NE2, I-NE5). Every consumer reads widened; every guard fails closed.
  - C — mutation-anchored per-site tests (widener guard, each of 4 consumers, DAO write). Real source mutation, byte-identical restore.
  - D — adversarial completeness. Enumerates every path where widener could cause a fresh grid import under any degraded/inclement/reserve-floor state. Includes pre-existing paths (v5.5.3 style D-HIGH-1 leak search). Config-boundary combinatorial: `NET_KWH_WIDENER_THRESHOLD` × `solcast_today` × `predicted_consumption_kwh` × `blind_state` × `inclement_state` × `hour_of_day` — test at extremes and inversions (e.g., predicted_net exactly at threshold; predicted_net = None; solcast = None; source_flag stale).
- **Orchestrator independent verification before ship:** personally re-run the backtest CI test; re-grep every consumer to confirm it reads widened; re-run one C mutation on the arbitrage-gate site; confirm blind-hold + inclement guards both engage in a synthetic degraded state.
- **Operator checkpoint BEFORE deploy** (backtest numbers, tuned threshold, kill-switch state, D enumeration table). **Two operator checkpoints** for R2: one before deploy (shadow-mode ON), one before flipping `CONF_R2_WIDENER_ENABLED` to promote to live actuation.
- **Post-deploy live validation (Review E):** README write-back with observed shadow-week attrs + first promotion day $-outcome + blind-hold/inclement PASS rows.

### Rollback
Flip `CONF_R2_WIDENER_ENABLED` FALSE (or `CONF_R2_WIDENER_SHADOW_ONLY` TRUE). Widener returns raw class; system reverts to pre-R2 gate behavior. No code revert required.

---

## Cross-phase x-check plan (who verifies what, at each stage)

| Stage | Artifact | Verifier | Method |
|---|---|---|---|
| R1 offline fit | `fit_consumption_regression.py` + `CONSUMPTION_REGRESSION_V1` const | Reviewer B (independent) | Re-run script; assert byte-identical constants + backtest MAE |
| R1 runtime | `_estimate_consumption` + shadow gate | Reviewer C (mutation) | Neuter shadow gate; assert dedicated test fails |
| R1 live | 14-day shadow report | Orchestrator + operator | Rolling MAE ≤ 22 kWh; source flag = `v1_regression` on every row |
| R7 primitive | `EnergyProjector` module | Reviewer A + D | Correctness proof + grep-singleton assertion |
| R7 migration | consumers | Reviewer B + C | Byte-identical no-op diff + per-consumer mutation |
| R7 live | mirror check | Orchestrator + operator | Attr `projected_soc` == log-line value |
| R2 backtest | `test_r2_widener_backtest.py` | Orchestrator (before ship) | Re-run CI test; assert ≥70% / ≤5 constraints; commit tuned threshold |
| R2 review | 4 framings incl. D adversarial | Reviewers A/B/C/D in parallel | Findings ledger + mutation-anchored proofs |
| R2 shadow live | attrs + DAO snapshot | Orchestrator + operator | 7-day shadow; no consumer reads widened; DAO carries raw + widened |
| R2 promoted live | first promotion day | Operator | README write-back with $-outcome vs counterfactual |
| All phases | blind-hold + inclement supremacy | Reviewer D + orchestrator | Synthetic degraded-state test + live day observation |

---

## Program phase-gate diagram

```
[R1 build] → [R1 Tier-3 review (A/B/C/D)] → [Op checkpoint] → [R1 deploy, shadow-only]
     → [14-day shadow, MAE ≤ 22 kWh] → [Op checkpoint: flip shadow OFF as R2 prereq]
        → [R7 build] → [R7 Tier-3 review] → [Op checkpoint] → [R7 deploy]
           → [1 live day mirror check] → [Op checkpoint: R2 unblocked]
              → [R2 build + backtest tuning] → [R2 Tier-3 review] → [Op checkpoint #1]
                 → [R2 deploy, shadow-only] → [7-day shadow]
                    → [Op checkpoint #2] → [flip CONF_R2_WIDENER_ENABLED] → [live actuation]
                       → [30-day observation] → [R8 evaluate]
```

Any phase-gate can send the phase back one step (shadow extension, threshold retune, additional review). No phase auto-advances.

---

## R8 — Follow-on (evaluate after R2 has ≥30 live days; NOT scoped here)

Candidate consumers of the recalibrated primitive: DPM relax-ceiling (temp is dominant driver — 3 kWh/CDD), HVAC pre-cool (same input), EV solar-aware charging (net vs gross surplus on D2 days). Each is its own Tier-3 cycle. Decision to build R8 is DATA-DRIVEN from R2's 30-day observation, not pre-committed here.

---

## Deferred / explicitly out of scope

- Bayesian consumption model. B0 §F.4: R² ceiling ~0.4 is a data limit, not a model limit; residual sd ~18 kWh MAE is occupancy/EV/pool events. Revisit only if R2 residuals show event-conditioning signal.
- Solcast forecast archival for the next probe. R3 rider (inside R2) persists the snapshot at classification time; a separate archival pipeline is not needed until the next probe cycle.
- Winter-specific tuning. B0 winter n=35; wait for R1's first winter (Nov–Feb 2026-2027) before retuning any winter constants.

## Plan-completion tracking discipline (per CLAUDE.md)

Each phase's post-cycle README MUST list what was NOT built from that phase's planning doc (skipped/deferred + why + where tracked). Program-level tracking of R8 and Bayesian deferral lives in this doc.
