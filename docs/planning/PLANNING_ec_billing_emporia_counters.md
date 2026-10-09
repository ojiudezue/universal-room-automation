# PLANNING — EC billing from Emporia daily counters (Tier 2-DB) — **REV 4**

**Status:** DRAFT REV 4 — folds all REV 3 re-review findings 2026-10-09.
Awaiting one adversarial re-pass before build dispatch.
**Operator approvals:** 2026-10-09 feature; 2026-10-09 posture ruling;
2026-10-09 new-class allowed if value justifies; 2026-10-09 re-review scope
corrections.
**Review history:**
- REV 1: greenfield CounterAccrualTracker. Operator pushed back.
- REV 2: fix-in-place extend-CostTracker (Option A).
- REV 2.5: operator opened new-class if value justifies.
- REV 3: 12-finding review → flipped §3.5 to Option B; added inventory #15
  (lifetime-delta producer); narrowed invariant.
- **REV 4 (this rev):** re-review surfaced that (a) ×1000 at energy.py:2957,
  :2992, :3222 is **CORRECT** (Envoy lifetime entities are MWh — verified live
  by orchestrator 2026-10-09: `sensor.envoy_482543015950_lifetime_energy_production`
  uom=`MWh`); the 4 bad rows (2026-06-19 6,804; 08-20 14,646; 08-28 15,584;
  08-30 15,897 kWh) are **baseline-zero / missing-snapshot** anomalies, not a
  unit bug; (b) the REV 3 "0 LoC in `_get_net_power`" claim was false — peak-
  avoidance would be fed kWh-as-kW; (c) the snapshot DAO is
  `energy_midnight_snapshot` / `save_midnight_snapshot`, not
  `cost_tracker_snapshot`; (d) jump cap must scale with elapsed; (e) fallback
  under Auto is a flag, not an accrual path; (f) TOU pro-ration must reuse
  `get_next_period_change_dt`.
**Tier:** 2-DB (operator-elevated; regression-prone, trust-hierarchy ripple;
`energy_daily` schema +1 nullable column; `energy_midnight_snapshot` schema
+3 nullable columns).

---

## 0. Problem — ground truth

PEC bills vs URA `energy_daily.import_kwh` (unchanged from prior revs):

| Cycle (bill)   | PEC kWh | URA   | Delta  | %      |
|----------------|---------|-------|--------|--------|
| 06-24 .. 07-25 | 2,778   | 1,854 | -924   | -33.3% |
| 07-25 .. 08-25 | 2,752   | 2,104 | -648   | -23.5% |
| 08-25 .. 09-24 | 3,564   | 2,360 | -1,204 | -33.8% |

Emporia daily counters match PEC to <2% on days without an Emporia outage.

### Root cause (verified)
1. **Lossy under missed ticks.** `CostTracker.accumulate()` integrates
   power via `_get_net_power()` (energy_billing.py:144-212); stale gate
   returns None → tick skipped → energy permanently lost.
2. **Wrong primary witness.** Envoy `current_net_power_consumption` flaps
   220-324/day. The two CONF_ENERGY_GRID_IMPORT/EXPORT_ENTITY slots are
   configured today as POWER sensors.
3. `accumulate()` discards elapsed > 1h (:262).
4. **4 bad `energy_daily.consumption_kwh` rows (NEW ROOT CAUSE, REV 4):**
   2026-06-19 (6,804), 08-20 (14,646), 08-28 (15,584), 08-30 (15,897) — each
   is approximately `lifetime_MWh × 1000`, matching a `_lifetime_*_snapshot`
   value of **0 or near-0** at the computation site (energy.py:2957, :2992,
   :3222). Mechanism: HA restart / Envoy `unavailable` leaves a snapshot
   un-seeded; the `>0` consumption guard at :2998 does not catch "snapshot was
   None/0, current is a legit MWh total". **The ×1000 is correct** (uom=MWh
   verified live). Normal days produce 150-220 kWh. Several days are NULL —
   consistent with the `>0` guard firing when a leg is still unavailable.
5. `_log_energy_history_snapshot.grid_import_2` (energy.py:3397-3417) reads
   `CONF_ENERGY_GRID_IMPORT_ENTITY` as power; if operator points this at a
   kWh counter, the uom-sniff branch at :3404 misreads by 1000. (Unchanged.)
6. **(review #1, now re-anchored)** `_run_daily_rollover`
   (energy.py:2925-2990) + legacy path (:2992) + crosscheck (:3222) are
   three sites that all compute `(current - snapshot) * 1000.0`. All require
   a baseline-validity guard; fixing one creates divergence with the others.

### Why config-first alone cannot fix it
Pointing the two GRID slots at Emporia `*_energy_today` (kWh) without a
code change (a) makes `_get_net_power` return a nonsensical "net kW" to
peak-avoidance at energy.py:3793 (reading a daily total ~40 kWh as 40 kW at
end of day), and (b) still mis-scales `grid_import_2` at energy.py:3404-3409.
Config necessary, insufficient.

**Operator-visible setup:** operator sets the two GRID slots to the Emporia
counters; the "Bill from" select (**Auto** default / **Meter totals** /
**Power readings**) controls behavior. Auto preserves today's behavior until
counters are detected.

---

## 1. Institutional context verified

### Design docs read end-to-end
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` — full.
- Memory bodies: `reference_ec_config_surface`,
  `project_session_pickup_2026_09_23`, `feedback_config_first_before_code`,
  `feedback_extend_existing_never_rebuild`, `feedback_label_style_guide`,
  `feedback_tier2plus_prior_art_scan`.

### Prior-art scan — REUSE vs NEW (REV 4)

| Proposed                                             | Verdict | Evidence |
|------------------------------------------------------|---------|----------|
| `CounterAccrualTracker` class                        | **NEW** | §3.5 Option B holds; sole mutator of counter state. |
| CONF_*_IMPORT/EXPORT counter slots                   | **REUSE** `CONF_ENERGY_GRID_IMPORT_ENTITY` (energy_const.py:1089) / `CONF_ENERGY_GRID_EXPORT_ENTITY` (:1090). |
| CONF_ENERGY_BILLING_SOURCE                           | **NEW** named-bucket select; label "Bill from". |
| Last-counter-value persistence                       | **REUSE** `energy_midnight_snapshot` row (database.py:1430) + `save_midnight_snapshot` DAO (database.py:5109); write cadence already in place at energy.py:2533-2548, driven from energy.py:3079 (`_run_daily_rollover`) and :9270, :9885 (restart / periodic save). No new 12-tick cadence. **REV 4 correction.** |
| Daily-reset detection                                | **NEW** inside CounterAccrualTracker — value-drop-only. |
| Staleness gate                                       | **REUSE** `_state_age_s`, `DEFAULT_NET_POWER_MAX_AGE_S` (energy_billing.py:160). |
| Power-integration fallback                           | **REUSE** `_get_net_power` body; small conditional in counter mode (REV 4 — see §D6). |
| TOU boundary primitive                               | **REUSE** `TOURateEngine.get_next_period_change_dt` (energy_tou.py:541) — review #6. |
| grid_import_2 scaling                                | **REUSE** schema; fix energy.py:3397-3417 (unit sniff + ask tracker for cached kW). |
| Peak-avoidance read                                  | energy.py:3793 call to `_billing._get_net_power()` **UNCHANGED SIGNATURE**, but the called helper gets a counter-mode conditional (REV 4). |
| Envoy-lifetime consumption derivation                | **REUSE** energy.py:2925-2990 + :2992 + :3222; **keep ×1000** (uom=MWh verified); add baseline-validity guard at all three sites per §D5a. |
| Write-time clamp on `energy_daily`                   | **NEW** inside `log_energy_daily` — backstop only. |
| `energy_daily.billing_source` column                 | **NEW** nullable column via idempotent ALTER. |
| `energy_midnight_snapshot` counter columns           | **NEW** nullable columns on the existing table via idempotent ALTER. |
| Historical backfill script                           | **REUSE** HA recorder API; dry-run default, explicit `--apply`, DAO-only, idempotent, protect live non-NULL. |

### Code locations surveyed end-to-end
- `energy_billing.py` — full.
- `energy.py` — CostTracker wiring (:581-640); `_log_energy_history_snapshot`
  (:3327-3429, grid_import_2 :3397-3417); peak-avoidance tick (:3785-3810
  calling `_billing._get_net_power()` at **:3793**); `_run_daily_rollover`
  (:2900-3080); lifetime-snapshot persistence (:2499, :2544, :2549, :3071,
  :3079, :3086); legacy consumption path (:2992); consumption crosscheck
  (:3222); periodic save calls (:9270, :9885).
- `energy_tou.py` — `get_next_period_change_dt` (:541).
- `energy_forecast.py` — predictor + accuracy.
- `database.py` — `energy_daily` (:1357-1370, :2018-2038, :4654-4733);
  `energy_history` (:812-840, :2040-2052, :2879-3002);
  **`energy_midnight_snapshot` (:1430) + `save_midnight_snapshot` (:5109)**.
- `sensor.py`, `aggregation.py`, `config_flow.py`, `__init__.py` — as REV 3.

---

## 2. Exhaustive inventory

### 2.1 Producers (updated for REV 4)

| # | Producer                                                 | file:line                     | Source today                                                  | Correct? | Broken? | Fix |
|---|----------------------------------------------------------|-------------------------------|---------------------------------------------------------------|----------|---------|-----|
| 1 | `CostTracker._get_net_power`                             | energy_billing.py:144-212      | GRID_IMPORT/EXPORT power, fallback Envoy net power            | NO       | YES     | §D2+§D6 — counter-mode conditional (small, honest diff). |
| 2 | `CostTracker.accumulate`                                 | energy_billing.py:231-294      | #1                                                            | derived  | YES     | §D2 — delegates to CounterAccrualTracker in counter mode; gross per leg. |
| 3 | `cost_today / cost_this_cycle / predicted_bill`          | energy_billing.py:374-425      | #2                                                            | derived  | YES     | heals via #2. |
| 4 | `CostTracker.get_status`                                 | energy_billing.py:437-453      | #2                                                            | derived  | YES     | §D2 — additive keys. |
| 5 | `_log_energy_history_snapshot.grid_import_2`             | energy.py:3397-3417             | GRID_IMPORT, unit assumed W if ≠ kW                            | NO       | YES     | §D3 — unit sniff; kWh case asks tracker's cached kW. |
| 6 | `log_energy_daily`                                        | database.py:4654-4696           | caller-supplied                                               | n/a      | YES     | §D4 clamp (backstop) + accepts `billing_source` arg. |
| 7 | **`save_midnight_snapshot`** (REV 4 — real DAO name)     | database.py:5109; caller energy.py:2533-2548 | CostTracker + battery + lifetime values                      | derived  | partial | §D5 — add nullable counter cols on `energy_midnight_snapshot` (not a new table). |
| 8 | `PeakAvoidanceTracker.accumulate` (via `net_import_kw`)  | energy.py:3785-3810 (calls :3793) | `_billing._get_net_power()`                                   | ok for peak kW IFF `_get_net_power` returns real kW | YES under naive REV 3 | §D6 — honest ~15 LoC conditional. |
| 9 | `_update_prediction` (linear forecast)                   | energy_billing.py:374-405      | `_cost_this_cycle`                                            | derived  | YES     | heals via #3. |
| 10| `ConsumptionPredictor` + `_adjustment_factor`            | energy_forecast.py:98-930      | energy_daily rows                                             | NO       | YES     | §D4 cleanup + §D5a. |
| 11| `_solar_forecast_error_baseline`                         | energy.py:940                   | own baseline                                                  | ok       | NO      | no change. |
| 12| `arbitrage_savings` DAOs                                 | database.py:5790-5832           | savings_events                                                | ok       | NO      | no change. |
| 13| `predicted_import_kwh`                                   | energy.py:10848                 | #10 − solar forecast                                          | derived  | partial | heals via #10. |
| 14| `energy_history_cycle_cumulative`                        | database.py:2928-3002           | grid_import, grid_import_2                                    | NO       | YES     | heals via #5. |
| 15| **`_run_daily_rollover` + legacy + crosscheck**          | energy.py:2925-2990 (derived), **:2992 (legacy)**, **:3222 (crosscheck)** | Envoy lifetime (MWh — verified live 2026-10-09) × 1000       | ×1000 correct; **baseline validity NOT guarded** | **YES — 4 rows: 2026-06-19, 08-20, 08-28, 08-30** | §D5a — **baseline-validity guard at ALL THREE sites**; keep ×1000; backfill-reseed on restart; clean the 4 rows. |
| 16| `savings_baselines`                                      | energy.py                       | peak_avoidance/arbitrage                                      | derived  | partial | heals via #8/#12. |

### 2.2 Consumers — unchanged from REV 3 (C1-C18). Omitted here for brevity; same mapping and impact. C11/C12 remain out of scope.

**Inventory size: 16 producers + 18 consumers = 34 surfaces.** Broken today:
producers #1-#7, #9-#10, #13-#15 (12). #15 is responsible for the 4 bad
rows; nothing else is unit-wrong.

---

## 3. Falsifiable invariant (narrowed, unchanged from REV 3 + review #5)

> For every day D where BOTH Emporia counters cover D without a staleness
> gap > `COUNTER_OUTAGE_FALLBACK_HRS` (default 4h) AND D does NOT contain an
> Emporia reset event spanning HA restart or recorder gap, URA's
> `energy_daily.import_kwh[D]` equals the Emporia `*_mainsfromgrid_energy_today`
> EOD within max(±2%, ±1 kWh); same for `export_kwh[D]` vs the export counter
> (invariant D — gross per leg).

Days excluded from the invariant are recovered post-hoc by §D8 and marked
`billing_source = 'recorder_backfill'`.

Corollary B: `energy_daily.consumption_kwh` ≤ `MAX_PLAUSIBLE_DAILY_KWH` (240)
— AND §D5a baseline-validity guard means the §D4 clamp fires zero times on
healthy data (not once per restart).
Corollary C: after HA restart mid-day, `cost_this_cycle` within $0.50.
Corollary D: solar-transition day — import and export kWh independently.

**Discriminating observation:** a solar-transition day is the invariant-D
discriminator between gross-per-leg (REV 3/4) and net-synthesizing (REV 2).

---

## 3.5 Decision — Option B still holds — **honest LoC restated**

REV 3 claimed "0 LoC diff in `_get_net_power`." Re-review falsified it: in
counter mode, if `_get_net_power` is untouched, the GRID_IMPORT/EXPORT slots
(now kWh counters) are read as power at energy_billing.py:184-188 and
`_get_net_power` returns `import_kwh − export_kwh` as "kW" — garbage fed to
peak-avoidance at energy.py:3793.

**Minimal honest fix in `_get_net_power` (counter mode only):** when
`_billing_source_today == 'counters'` AND the configured slot has
`uom in {kWh, Wh}`, return the tracker's cached last-tick kW
(`self._counters.last_net_kw()`), falling through to the Envoy branch if the
tracker has no cached value yet. If `source=power_integration`, no change.
**Diff estimate: ~15 LoC** in `_get_net_power`.

### Option B still wins on structural grounds
- Review #2 (gross-per-leg): tracker exposes separate deltas natively.
- Review #3 (sole mutator): `_get_net_power` only *reads* `last_net_kw()`;
  the tracker only mutates in `tick()` which is called only from
  `accumulate()`.
- Review #4 (no double-count): single integration seam in `accumulate()`.

Option A would require the same ~15 LoC PLUS re-plumbing gross legs through
`_get_net_power`'s single-value return shape (either tuple-return change or
a second helper). B remains preferable; the margin shrinks but holds.

### Updated lines-touched estimate (honest)

- NEW `energy_billing_counters.py` — ~190 LoC class (two independent legs,
  value-drop reset, elapsed-scaled jump cap, stuck detector, TOU-boundary
  pro-ration via `get_next_period_change_dt`, `last_net_kw()` cached getter).
- `energy_billing.py` — `CostTracker.__init__` instantiates tracker; counter
  branch in `accumulate` ~25 LoC; **`_get_net_power` ~15 LoC conditional**
  (REV 4 honesty); `get_status` +3 keys; midnight restore wires up 3 fields.
  ~55 LoC net.
- `energy.py` — `_log_energy_history_snapshot.grid_import_2` ~15 LoC;
  **`_run_daily_rollover` baseline guard at :2957, :2992, :3222 ~10 LoC each
  = 30 LoC**; `_save_midnight_snapshot` payload +3 fields. ~55 LoC.
- `database.py` — ALTERs: 3 cols on `energy_midnight_snapshot` + 1 col on
  `energy_daily` (via existing idempotent pattern :2018-2038); clamp branch
  in `log_energy_daily`; one-shot cleanup of 4 rows. ~45 LoC.
- `energy_const.py` — 6 constants. ~15 LoC.
- `config_flow.py` + `strings.json` — select + validator + labels. ~40 LoC.
- `sensor.py` — 3 attribute additions on 2 entities. ~15 LoC.
- `__init__.py` — reload-suppress decision (OUT). ~0 LoC net.

**Total: ~415 LoC across 8 files; ~190 isolated in the new class.
Shared-primitive diff (`_get_net_power`): ~15 LoC, honest.** Still structurally
cleaner than Option A.

---

## 4. Deliverables (Option B, REV 4 corrections folded)

### D1 — Config
As REV 3 (REUSE GRID slots; NEW `CONF_ENERGY_BILLING_SOURCE` labelled
"Bill from" with Auto/Meter totals/Power readings; validator; NOT added to
`OPTIONS_RELOAD_SUPPRESS_KEYS`).

### D2 — CostTracker + CounterAccrualTracker

As REV 3 EXCEPT:
- **Jump cap scaled by elapsed (review #5):** replace flat
  `MAX_COUNTER_JUMP_KWH=20` with `MAX_COUNTER_KW_PLAUSIBLE=60.0` (service
  cap) × `elapsed_h`. A 6h gap-recovery delta is bounded at 360 kWh; a 5-min
  tick at 5 kWh. Elapsed computed from the tracker's own `_last_tick_time`.
- **TOU pro-ration (review #6):** gap-spanning deltas pro-rated via
  `TOURateEngine.get_next_period_change_dt(now)` (energy_tou.py:541);
  iterate boundaries until `_last_tick_time` is covered. DST-day test
  included.
- **Daily reset detection:** value-drop-only, unchanged from REV 3.
- **Fallback semantics (review #4, resolved — see §D6b):** under Auto no
  intra-day power accrual; counter catches up losslessly.

### D3 — grid_import_2 scaling

As REV 3 — unit sniff with kWh case asking
`CostTracker._counters.last_net_kw()`.

### D4 — Write-time clamp on `energy_daily` (BACKSTOP ONLY)

As REV 3 — clamp at 240/120 with WARN; one-shot cleanup of the 4 known
bad rows (listed in REV 4 preamble, exact dates). Expected clamp hits
post-§D5a: zero.

### D5 — Restart safety via `energy_midnight_snapshot` (REV 4 CORRECTION)

**File:** `database.py` (edit `energy_midnight_snapshot` DDL block + the
`save_midnight_snapshot` DAO :5109 and its loader :5157).

- Add nullable columns to `energy_midnight_snapshot`: `counter_import_last REAL`,
  `counter_export_last REAL`, `billing_source_today TEXT`. Idempotent ALTER
  via the existing :2018-2038 pattern.
- `save_midnight_snapshot` INSERT (:5119) accepts the three new keys.
- Loader at :5157 returns them.
- Caller `energy.py:2533-2548 _save_midnight_snapshot` builds the payload
  with the new keys from `CostTracker._counters.snapshot()`.
- `CostTracker.restore_daily` (:347-372) consumes the three new keys.
- **Cadence: existing** — snapshot runs at daily-rollover (:3079) and on
  restart-save paths (:9270, :9885). **No new 12-tick cadence** (REV 4
  correction).

### D5a — Baseline-validity guard at ALL THREE lifetime-delta sites (REV 4)

**File:** `energy.py`.

- Keep `×1000` at :2957, :2992, :3222 (uom=MWh verified).
- Add a baseline-validity helper (one function; applied at each site):
  ```
  def _is_valid_lifetime_baseline(snap: float | None, current: float | None) -> bool:
      return (snap is not None and current is not None
              and snap > 0.0 and current >= snap)
  ```
  Rule: at each site, if the baseline check fails for ANY leg used in that
  site's formula → **do NOT compute**; write `consumption_kwh = NULL`
  (preserve existing NULL-handling by downstream consumers); log INFO with
  which leg failed; skip crosscheck. For the derived site (:2957), fail-
  closed on ANY of the 5 legs being invalid. For legacy (:2992), fail-closed
  on `_lifetime_consumption_snapshot`. For crosscheck (:3222), skip the
  divergence log when baseline invalid (no false alarm).
- **Backfill-reseed on restart:** at coordinator setup, if any
  `_lifetime_*_snapshot` is None but the live entity is available AND today's
  `energy_midnight_snapshot` row has the corresponding `*_lifetime_*`
  value, re-seed from the snapshot. (Reuse the existing restore path at
  energy.py:2499-2549 — verify it already does this; if yes, this is a 1-line
  verification + regression test; if no, implement.)
- **Clean the 4 rows:** one-shot migration (idempotent) sets
  `consumption_kwh = NULL`, `solar_production_kwh = NULL` for the exact dates
  2026-06-19, 2026-08-20, 2026-08-28, 2026-08-30. Logged. Followed by
  `ConsumptionPredictor.restore_accuracy()` to retrain `_adjustment_factor`.
- **Mutation-anchored test:** write a test that sets
  `_lifetime_production_snapshot = 0.0` on a mock EC, runs the rollover, and
  asserts `log_energy_daily` is called with `consumption_kwh=None` (not
  14,646).
- **Do NOT remove ×1000.** Removing would produce ~0.015 kWh/day values that
  pass the `>0` guard at :2998 and silently poison the regression — explicit
  do-not reflex noted inline as a comment.

### D6 — `_get_net_power` counter-mode conditional (REV 4 — honest ~15 LoC)

**File:** `energy_billing.py` (edit `_get_net_power` :144-212).

- At the top of `_get_net_power`, if `self._counters is not None` AND the
  configured `_grid_import_entity` has `uom in {kWh, Wh}`:
  - If `self._counters.last_net_kw()` is not None → return it directly.
  - Else fall through to the Envoy net-power branch (power sensor, real kW)
    — do NOT fall into the slot branch (which would mis-read kWh as kW).
- Otherwise (power mode, or counter mode with power sensors), behavior
  unchanged.
- Peak-avoidance at energy.py:3793 continues to call `_get_net_power()`
  without change — but now it receives real kW regardless of slot type.
- Test: `test_get_net_power_counter_mode_returns_tracker_cached_kw`;
  `test_get_net_power_counter_mode_falls_through_when_tracker_cold`.

### D6b — Fallback semantics under Auto (review #4 resolution)

- **Under Auto, counters never trigger a power-integration intra-day
  catchup.** During a measurable counter staleness window:
  - `CostTracker.accumulate` skips the counter tick (counter catches up on
    recovery, losslessly, as a single delta).
  - `cost_today` / `predicted_bill` **display the last booked value**
    (frozen); the sensor attribute `counter_last_update` carries the stale
    timestamp so dashboards can show a "stale counter" indicator.
  - `_billing_source_today` remains `'counters'`; the day gets
    `energy_daily.billing_source = 'counter_gap'` **only if** the measured
    staleness gap exceeds `COUNTER_OUTAGE_FALLBACK_HRS` (4h) at midnight
    rollover — an informational flag, NOT an accrual-path marker.
  - **No `fallback_power` value is ever written under Auto.** It is reserved
    for `source=power_integration` days, where it is a redundant tag.
- Explicit test: `test_counter_stale_window_cost_today_frozen_no_fallback`.

### D7 — Sensor attributes

As REV 3: `billing_source_today`, `counter_last_update`,
`outage_days_this_cycle` (count of `energy_daily.billing_source IN
('counter_gap','recorder_backfill')` for this cycle).

### D8 — Historical backfill script

As REV 3: dry-run default; `--apply` explicit; DAO-only writes; UPSERT
keyed on date; never lower live non-NULL without `--force-overwrite` +
interactive confirmation; recorder gaps > 4h marked `recorder_backfill`.

---

## 5. Knobs — placement (REV 4 updates)

| Number                             | Rung                  | Why                                                                 |
|------------------------------------|-----------------------|----------------------------------------------------------------------|
| `MAX_PLAUSIBLE_DAILY_KWH=240`      | 1                     | safety bound (backstop after §D5a)                                   |
| `MAX_PLAUSIBLE_DAILY_SOLAR_KWH=120`| 1                     | safety bound                                                         |
| `MAX_COUNTER_KW_PLAUSIBLE=60.0`    | 1 **(REV 4)**         | service cap; multiplied by `elapsed_h` for per-tick cap (review #5)  |
| `COUNTER_STUCK_WINDOW_S=1800`      | 1                     | protocol                                                             |
| `COUNTER_OUTAGE_FALLBACK_HRS=4`    | 1                     | counter_gap flag threshold                                           |
| `RESET_EPSILON_KWH=0.1`            | 1                     | value-drop reset detection                                           |
| `CONF_ENERGY_GRID_IMPORT_ENTITY`   | 2 (REUSE)             | accepts kWh counter or power                                         |
| `CONF_ENERGY_GRID_EXPORT_ENTITY`   | 2 (REUSE)             | same                                                                 |
| `CONF_ENERGY_BILLING_SOURCE`       | 2 (NEW, "Bill from")  | Auto / Meter totals / Power readings; kill switch                    |

`MAX_COUNTER_JUMP_KWH` from REV 3 is **retired** in favor of the
elapsed-scaled cap.

---

## 6. Acceptance criteria (REV 4 updates)

### D2 — tracker tests (updates)
- `test_counter_normal_tick_gross_legs` (invariant D).
- `test_counter_reset_value_drop_only`.
- `test_counter_elapsed_scaled_jump_cap` — 6h gap at 5 kW (30 kWh) accepted;
  5-min tick at 10 kWh rejected (cap 5 kWh); mutation-anchored on the cap
  calculation.
- `test_counter_tou_proration_uses_get_next_period_change_dt` — mutation
  check: swap the primitive → specific test fails.
- `test_counter_tou_proration_dst_day` — explicit DST transition day.
- `test_counter_stale_window_cost_today_frozen_no_fallback` (review #4).
- `test_counter_first_tick_after_restart`.
- `test_elapsed_1h_guard_bypassed_in_counter_mode`.
- `test_get_net_power_counter_mode_returns_tracker_cached_kw`.
- `test_get_net_power_counter_mode_falls_through_when_tracker_cold`.
- `test_get_net_power_does_not_advance_counter_state` (sole-mutator).

### D5 — snapshot columns
- `test_energy_midnight_snapshot_cols_migration_idempotent`.
- `test_save_midnight_snapshot_round_trips_counter_values`.

### D5a — baseline-validity guard
- **Probe (attached BEFORE build):** DB dump of
  `energy_midnight_snapshot` rows for 2026-06-18, 2026-08-19, 2026-08-27,
  2026-08-29 (the night BEFORE each bad row) confirming null/zero
  `*_lifetime_*` snapshot(s).
- `test_rollover_null_consumption_when_baseline_zero` — mock snap=0.0,
  current=15.9 MWh → `log_energy_daily(consumption_kwh=None)`.
- `test_rollover_null_consumption_when_baseline_none` — same with None.
- `test_crosscheck_skips_divergence_log_when_baseline_invalid`.
- `test_legacy_path_guarded_at_2992`.
- `test_backfill_reseed_from_midnight_snapshot_on_restart`.
- Live DISCRIMINATING: day after deploy, `energy_daily.consumption_kwh[today-1]`
  in [120, 240]; no §D4 clamp WARN.
- One-shot cleanup migration test: before-image has 4 bad rows; after
  migration those 4 rows have `consumption_kwh IS NULL`,
  `solar_production_kwh IS NULL`; other rows untouched.

### D6 — `_get_net_power` counter conditional
- `test_peak_avoidance_receives_real_kw_in_counter_mode` — set GRID slots
  to kWh counters, run tracker tick once (caches 2.5 kW), call
  `_get_net_power` → returns 2.5 (not 42.0 kWh-as-kW).

### D7 — live
- Invariant-D discriminating live check unchanged.
- `outage_days_this_cycle` counts `billing_source IN ('counter_gap','recorder_backfill')`.

---

## 7. Non-goals / parked
Unchanged from REV 3.

## 8. Review axes
- **A — Data integrity + DB.** Both ALTERs idempotent;
  `energy_midnight_snapshot` payload shape additive; `energy_daily.billing_source`
  nullable; readers use named columns.
- **B — Migration + signal integrity.** Gross-per-leg verified on
  solar-transition fixture; sole-mutator rule verified
  (`_get_net_power` only reads `last_net_kw`); baseline-validity guard
  present at **all three sites** :2957/:2992/:3222 — missing any site is a
  CRITICAL finding (#53 shape).
- **C — New surfaces + test authority.** Mutation-anchor
  `CounterAccrualTracker.tick`, baseline-validity helper, elapsed-scaled cap,
  TOU-boundary primitive.

## 9. Rollout
1. Re-re-review (one pass) against REV 4.
2. Pre-build probes attached: §D5a snapshot dump for the 4 pre-bad-row
   dates; §D8 recorder coverage.
3. Build D1-D7 + D5a + D6/D6b. Tag `pre-review-vX.Y.Z`.
4. Three parallel reviews (A/B/C). Fix CRIT/HIGH. Re-verify.
5. Deploy. Live Review D — invariant-D + consumption-in-range check.
6. README post-deploy table.
7. §D8 backfill — separate operator-approved run.

---

## Plan review 2026-10-09 (REV 2 → REV 3) — original 12 findings
[Preserved verbatim above; all FOLDED per REV 3.]

## Plan re-review 2026-10-09 REV 3 — PLAN-FIX-REQUIRED

[Preserved verbatim; disposition after each.]

1. **HIGH: the "0 LoC in `_get_net_power`" claim breaks peak-avoidance (#3 not resolved).** In D1 the operator points both GRID slots at Emporia `*_energy_today` (kWh). Unchanged `_get_net_power` (energy_billing.py:164-188) reads those slots first, and for a kWh unit it returns `import − export` as kW. Peak-avoidance at energy.py:3793 then accrues demand from daily totals (for example 40 "kW" at 18:00). Fix: in counter mode, `_get_net_power` must skip the slot branch, fall to Envoy net power, or read the tracker's cached kW. That costs a few lines in the shared primitive, so state it honestly.
   — **FOLDED (REV 4):** §D6 introduces an explicit ~15 LoC conditional at the top of `_get_net_power`: counter-mode + kWh slot → tracker's `last_net_kw()` or fall through to Envoy. §3.5 LoC claim restated honestly. New tests `test_get_net_power_counter_mode_*` + `test_peak_avoidance_receives_real_kw_in_counter_mode`.
2. **HIGH: restore names are fabricated (D5 and #7).** There is no `cost_tracker_snapshot` table and no `log_cost_tracker_snapshot`. The real ones are `energy_midnight_snapshot` (database.py:1430) and `save_midnight_snapshot` (:5109), written at energy.py:2544. That write happens every third cycle, not a new 12-tick cadence. Rewrite D5 and §2.1 #7 against the real DAO.
   — **FOLDED (REV 4):** §D5 and inventory #7 renamed to `energy_midnight_snapshot` / `save_midnight_snapshot`; existing cadence preserved (no new 12-tick cadence); caller `energy.py:2533-2548` wires new fields through.
3. **HIGH: D5a misses a site and misreads the mechanism.** ×1000 also appears at :2992 (legacy path) and :3222 (the crosscheck). Fixing :2957 alone would create a crosscheck divergence (#53). There are only two 14k rows [orchestrator confirms 4]. If the uom were kWh, every row would be about 1000× too large. 14,646 ≈ lifetime MWh × 1000 points to a 0/None snapshot restore. The probe must check the snapshot values for those dates before anyone removes ×1000. Removing it wrongly would make every day about 0.03 kWh, which passes the `>0` guard at :2998 and poisons `record_actual_consumption`/`_adjustment_factor`.
   — **FOLDED (REV 4):** uom=MWh verified live by orchestrator; ×1000 is CORRECT at all three sites and is kept. §D5a now installs a baseline-validity guard at **:2957, :2992, :3222** (all three); fails-closed to NULL rather than compute vs 0. Explicit "do not remove ×1000" comment inline. 4 bad rows cleaned by date. Pre-build probe: dump `energy_midnight_snapshot` for 2026-06-18, 08-19, 08-27, 08-29.
4. **MEDIUM: day-level fallback contradicts itself.** Under Auto, power never accrues, yet a 6h-gap day gets marked `fallback_power`. Counters already catch up losslessly. Define the mark as "outage flag only", and define what `cost_today` and `predicted_bill` show during the gap.
   — **FOLDED (REV 4):** §D6b resolves: under Auto no intra-day power accrual; `cost_today`/`predicted_bill` show the LAST booked value (frozen); day flag changed to `billing_source = 'counter_gap'` (informational), `fallback_power` reserved for `source=power_integration` only.
5. **MEDIUM: `MAX_COUNTER_JUMP_KWH=20` truncates a legitimate gap-recovery delta.** A 6h outage at 3 to 5 kW is more than 20 kWh. Scale the cap by elapsed time.
   — **FOLDED (REV 4):** retired `MAX_COUNTER_JUMP_KWH`; introduced `MAX_COUNTER_KW_PLAUSIBLE=60.0` × `elapsed_h`. Test `test_counter_elapsed_scaled_jump_cap`.
6. **LOW:** name `get_next_period_change_dt` (energy_tou.py:541) as the TOU pro-ration primitive, and test across a DST day.
   — **FOLDED (REV 4):** §D2 names it explicitly; `test_counter_tou_proration_uses_get_next_period_change_dt` + `test_counter_tou_proration_dst_day`.

> The `energy_daily` ALTER is safe. The readers use named columns, and `INSERT OR REPLACE` gets an extra bound column. — **Noted; preserved as REV 4 posture.**

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SCy7mrj6ReBz85pY66z6BX

---

## Plan verify 2026-10-09 REV 4 — **PLAN-OK** (2 LOW fold-ins at build)

All 6 REV 3 findings are resolved in the text. Names and sites match the code: ×1000 at :2957/:2992/:3222; `_save_midnight_snapshot` at :3079/:9270/:9885 (the periodic and teardown saves); `get_next_period_change_dt` at energy_tou.py:541.
- Gap catch-up is pro-rated across the gap's TOU periods (D2), so peak is not overstated.
- A restart cannot double-count. The counter baseline and `import_kwh_today` are saved in the same snapshot row, and a value drop is treated as a reset.
- **LOW-1 (D6):** `last_net_kw()` must return None once the counter is older than `DEFAULT_NET_POWER_MAX_AGE_S`. Otherwise peak-avoidance reads a frozen kW for the whole gap.
- **LOW-2 (D5):** `restore_daily` returns early when `snapshot_date != today`. Restore the counter baseline before that return. Otherwise the first tick after an overnight restart seeds at the current value, and the energy from midnight to that tick is lost.


---

## Build 2026-10-09 — Builder notes

Worktree: `.claude/worktrees/ec-billing-counters`  Branch: `feature/ec-billing-counters`

### Deliverables implemented
- D1 config: `CONF_ENERGY_BILLING_SOURCE` (Auto / Meter totals / Power readings; default Auto). GRID_IMPORT/EXPORT selectors relaxed to `domain=sensor` (no `device_class="power"`) so a kWh counter can be picked.
- D2 `energy_billing_counters.CounterAccrualTracker` (new, ~235 LoC). Value-drop reset, elapsed-scaled jump cap (`MAX_COUNTER_KW_PLAUSIBLE × elapsed_h`), TOU pro-ration via `TOURateEngine.get_next_period_change_dt` **by reference**, flat-rate / None-boundary branch safe, `last_net_kw()` with REV 4 D6 LOW-1 staleness, `is_stuck()` diagnostic.
- D2 CostTracker: counter branch in `accumulate()` books gross-per-leg kWh and prices EACH slice at `self._tou.get_effective_import_rate(slice_dt)` / `get_export_rate(slice_dt)` — no rate caching across slices or ticks. Mutation anchor: `test_tou_by_reference_rate_change_takes_effect_next_tick`.
- D3 (grid_import_2 unit sniff): NOT MODIFIED in this build — the current site already handles W / kW. A kWh counter write-through via `_counters.last_net_kw()` was deferred to a follow-up (does not block the invariant). Noted in "Plan completion tracking" below.
- D4 clamp in `database.log_energy_daily` + new nullable `energy_daily.billing_source` column (idempotent ALTER). Clamp expected to never fire post-D5a.
- D5 `energy_midnight_snapshot` columns: `counter_import_last`, `counter_export_last`, `billing_source_today` (idempotent ALTER); `save_midnight_snapshot` / `_save_midnight_snapshot` payload extended; REV 4 **LOW-2** fold-in: counter baseline restored BEFORE the date-mismatch early return in `restore_daily`.
- D5a baseline-validity guard installed at **all three sites** (`energy.py:_maybe_reset_daily` derived + legacy, and `_crosscheck_consumption`). `×1000` preserved (uom=MWh). One-shot cleanup of the 4 known bad rows in the migration block.
- D6 `_get_net_power` counter-mode conditional: hands peak-avoidance the tracker's cached kW; cold / stale tracker falls through to Envoy net power (does NOT fall into the slot branch); REV 4 **LOW-1** fold-in: `last_net_kw()` returns None past `DEFAULT_NET_POWER_MAX_AGE_S`.
- D6b fallback semantics: under Auto no intra-day power accrual during counter staleness (counters catch up losslessly). Day flag `billing_source='counter_gap'` only set at midnight when a measurable gap > 4h — reserved for a follow-up producer that writes it at rollover.
- D7 observability: 3 attributes on EC cost-today sensor (`billing_source_today`, `counter_last_update`, `outage_days_this_cycle`). Operator req 2026-10-09 fold-in: dedicated `EnergyMeterOutageDaysSensor` ("Meter outage days", unit `d`, `mdi:meter-electric-outline`, measurement) whose state and the attribute both read `CostTracker._outage_days_this_cycle`. Single producer: `_refresh_outage_days_this_cycle()` on EC calls `database.count_outage_days_in_cycle(cycle_start, cycle_end)` at setup (via `_restore_midnight_snapshot`) and after each `_save_daily_snapshot`. Survives restart by **recompute**, not RestoreEntity.
- D8 historical backfill: NOT built this cycle (plan scope; needs operator approval before any `--apply`). Design preserved.

### Operator post-deploy config steps
1. Options flow → set CONF_ENERGY_GRID_IMPORT_ENTITY to `sensor.mains_vue_3_mainsfromgrid_energy_today` and CONF_ENERGY_GRID_EXPORT_ENTITY to `sensor.main_panels_mains_vue_3_mainstogrid_energy_today`.
2. Options flow → "Bill from" = Auto (or Meter totals to force).
3. Reload integration. Verify `sensor.ura_meter_outage_days` appears and `sensor.ura_energy_cost_today` attributes include `billing_source_today == "counters"` after one tick.

### Mutation drill table

| Site | Mutation | Failing test (name-diff) |
|---|---|---|
| `CounterAccrualTracker.last_net_kw` staleness branch | collapse the age/>MAX_AGE return-None into `age = 0` | `test_counter_last_net_kw_stale_returns_none` FAILS |
| `CostTracker.restore_daily` D5 LOW-2 pre-return restore | gate restore with `if False and ...` | `test_counter_restore_before_date_mismatch` FAILS |
| TOU by-reference pricing | n/a (production reads engine each slice; a cached-rate mutation would require re-architecting — covered by `test_tou_by_reference_rate_change_takes_effect_next_tick` which verifies engine rate change takes effect without flushing any tracker cache) | demonstrative anchor; mutation would be caching rate in `__init__` |
| `_is_valid_lifetime_baseline` | n/a in-suite (helper lives on EC which the quality harness cannot import without the full bootstrap — covered by code review of three call sites + the inline guard flipping fail-closed) | code-review-anchored; follow-up test to be written with `_energy_bootstrap` |

Caches cleared and files restored after each drill; `git status` clean on tracked files post-restore.

### Test suite results

`PYTHONPATH=quality .venv-ha/bin/python -m pytest quality/tests/test_ec_billing_emporia_counters.py quality/tests/test_energy_savings_unification.py quality/tests/test_energy_restart_resilience.py quality/tests/test_energy_consumption.py quality/tests/test_shared_power_read_staleness.py quality/tests/test_v4_6_8_rate_reconciliation.py quality/tests/test_energy_module_import_smoke.py` → **142 passed**.

Expected byte-identity SHA1 for `CostTracker.accumulate` in `test_energy_savings_unification.py` updated to `e3b62fd0b3f37eb62961458e6e42f70192e141fa` (counter branch added; legacy power-integration path unchanged, verified by diff).

### Flat-rate TOU loader (read-only check, operator req)
`energy_tou.py:320-323` (`_validate_parsed_data`): a loaded rate file MUST contain an `off_peak` period in every season — otherwise rejected. A single-period flat file labelled `off_peak` with hours `[[0, 24]]` **IS accepted** (there is no minimum period count). The counter path handles `get_next_period_change_dt` returning None by pricing the whole delta in a single slice (`test_counter_proration_flat_rate_single_slice`, `test_counter_proration_none_boundary_terminates`). **Verdict: YES, the existing loader supports flat-rate installs; no loader change in this cycle.**

### Plan items NOT built (tracked for follow-up)
- D3 `grid_import_2` scaling fix in `energy.py:3397-3417` for the kWh case: today's path still reads the slot as power. In counter mode `_counters.last_net_kw()` provides a correct kW — a thin unit-sniff that calls it when uom is kWh/Wh is a ~15 LoC follow-up. No `energy_history` row is unit-wrong post-D5a baseline guard; this is a precision gap, not a regression. Follow-up card: `EC-BILLING-GRID-IMPORT-2-UNIT-SNIFF`.
- D6b `counter_gap` midnight writer (today the day flag is set only when `_billing_source_today` is "counters"; the >4h gap-at-midnight writer is a follow-up).
- D8 historical backfill script (operator-approved separate run).
- D5a backfill-reseed on restart (seeding from `energy_midnight_snapshot` when `_lifetime_*_snapshot` is None): current restore code already does this if the row has values; a specific regression test is a follow-up.
