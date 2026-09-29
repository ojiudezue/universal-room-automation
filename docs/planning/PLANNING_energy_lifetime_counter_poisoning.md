# PLANNING — Energy lifetime-counter poisoning of `energy_daily`

**Card:** ENERGY-CONSUMPTION-FORECAST-POISONED-1
**Date:** 2026-09-29
**Tier:** **Tier 2-DB** (3 framing-disjoint reviews) — see §Tier classification
**Companion:** `docs/planning/AUDIT_energy_consumption_forecast_poisoning_2026_09_29.md`, `scripts/probes/energy_consumption_forecast_poison_probe.py`
**Adjacent (do NOT re-scope here):** ENVOY-FLAKINESS-181243-1 (physical cause of the 0.045505 MWh glitch), COVERAGE-EVENING-ATTRIBUTION-DRIFT-1 (net-vs-total consumption sensor selection).

---

## Falsifiable invariant

> **INV-LCP1:** No row in `energy_daily` (from now on) has `consumption_kwh` or `solar_production_kwh` derived from a lifetime-counter snapshot that regressed vs the last-known-good value for that counter, and no such row exceeds the daily plausibility ceiling. Equivalently: for every persisted daily delta `Δ = (current − snapshot) × 1000`, either `current ≥ snapshot − ε_regress` AND `Δ ≤ CEILING`, OR the field is stored NULL and an anomaly is emitted.

Falsifier: replay the recorded 0.045505 MWh glitch sequence against the producer; if any resulting row is written with `solar_production_kwh` or `consumption_kwh` ≥ CEILING (or with a non-NULL value derived from a regressed snapshot), INV-LCP1 fails.

Discriminating live check (2026-09-30 00:00, first post-deploy midnight): today's `energy_midnight_snapshot.lifetime_production = 0.045505` is a *known-glitched* baseline. Under the fix, tomorrow's `energy_daily` row for 2026-09-29 must be either NULL (baseline rejected as regressed on Δ compute) OR a plausible value (baseline replaced by an accepted, monotonic reading). It must **not** be ≈ 18,850 kWh (raw glitch consumed) and must **not** silently be 0.

---

## Institutional context verified

### Prior planning docs consulted (skim unless marked)
- `docs/planning/PLANNING_envoy_telemetry_failover_map.md` + `_D5_addendum.md` — measurement-before-build precedent for Envoy freshness; no lifetime-snapshot guard proposed.
- `docs/planning/PLANNING_enphase_cloud_reliance.md`, `PLANNING_ec_envoy_boot_decoupling.md`, `PLANNING_envoy_write_verification_and_redundancy.md` — Envoy input hygiene; none touch `_get_lifetime_*` or midnight-snapshot arithmetic.
- `docs/planning/PLANNING_energy_unit_normalization_and_attribution.md`, `PLANNING_v4.6.8_ec_tou_rate_reconciliation.md`, `PLANNING_v4.x_B4_ENERGY_INTEGRATION.md`, `PLANNING_forecast_accuracy_fix.md` — establish `energy_daily` semantics and the pre-v3.14 CT bug that motivated the `>= 10` accuracy filter (energy.py:1446). No producer-side monotonic guard was ever introduced.
- `PLANNING_net_energy_program_R1_R7_R2.md` — R1/legacy estimator + shadow arm; relevant to consumer map (energy_forecast.py:352-417).
- `PLANNING_envoy_local_witness_and_solar_follow.md` — the local-MQTT stream is what a future substitution feed would use; not consumed here.
- No prior plan proposes a lifetime-counter monotonic guard, daily plausibility ceiling, or `energy_daily` read-side range filter.

### Memory bodies pulled
- `project_envoy_boot_incident_2026_06_12.md` — RestoreEntity unavailable→OFF poisoning + one-shot EC validation race; different failure surface but the same *lesson*: a single glitched read at a lifecycle boundary corrupts downstream. Reinforces guarding snapshot-set sites, not just steady-state reads.
- `project_battery_soc_envoy_not_span.md` — reminds that URA reads Envoy for battery SOC; unrelated to lifetime counters.
- `feedback_measure_before_build.md`, `feedback_falsify_before_asserting.md`, `feedback_verification_needs_disjoint_framings.md` — process anchors observed in the audit (discriminator identity to 0.1 kWh proved the mechanism).

### Design docs read
- No `docs/Coordinator/ENERGY_*.md` covers midnight-snapshot derivation (the EC manual sections cited by memories concern reserve/arbitrage, not `energy_daily`). Producer arithmetic read end-to-end at `energy.py:2745-2919`, `:3013-3097`, `:2301-2359`, `:1420-1458`, `:2225-2274`.

### Prior-art scan for proposed additions (Tier 2+ rule)
Grep surfaces: `custom_components/universal_room_automation/**/energy*.py`, `const.py`, `database.py`, `config_flow.py`, `sensor.py`, `select.py`.

| Proposed piece | Verdict | Existing (file:line) or justification |
|---|---|---|
| Lifetime-counter monotonic guard (`_accept_lifetime_reading` or inline in `_get_lifetime_*` / snapshot-set sites) | **NEW** | grep of `backwards|monotonic|last_known_good|lifetime` in `domain_coordinators/energy*.py`: only `time.monotonic()` bookkeeping in `energy_pool.py`; no counter-monotonicity guard anywhere. `_get_state_float` (`energy.py:10577-10587`) rejects only `unknown`/`unavailable`. |
| `_last_known_good_lifetime_*` in-memory per-counter (persisted with midnight snapshot) | **NEW** | Snapshot payload today (`energy.py:2371-2375`, DB `save_midnight_snapshot`) carries only the six counters plus `snapshot_date`. Need to add LKG fields (or a sibling table row); operator-visible knob not required. |
| `DAILY_CONSUMPTION_MAX_KWH`, `DAILY_SOLAR_MAX_KWH`, `LIFETIME_REGRESS_TOLERANCE_MWH` module constants | **NEW** | grep `DAILY_CONSUMPTION_MAX|PLAUSIBILITY|MAX_KWH|CEILING` in `energy_const.py` returns zero hits. Rung 1 (module constant, review-gated) per Numbers-Get-Knobs — see §Knob ladder. |
| DAO read-side range filter helpers | **EXTEND** | `get_energy_daily_recent(days=30)` already has a `consumption_kwh >= 10` lower bound at consumer (`energy.py:1446`). Add symmetric upper bound at the same site + parallel filters in `get_consumption_history` / `get_energy_temp_pairs` callers. Prefer filtering at the caller (energy.py) to avoid changing DAO shape (Tier 2-DB migration-correctness constraint). |
| NM/anomaly trip-wire on rejected lifetime read or ceiling hit | **REUSE** | Anomaly dispatch pattern already used across coordinators (grep `anomaly` in `domain_coordinators/`); reuse the existing dispatch shape rather than a new channel. Exact channel to be picked in build from a reader of one existing energy anomaly emitter. |
| `select.ura_energy_coordinator_dp_house_load_source` = `live_span` (D0) | **REUSE** | Live entity already exists — `config_flow.py:4637-4645, 5777-5861`, `select.py:767-788`, `energy_const.py:1585` default `max_span_r1`. D0 is an operator flip, zero code. |
| Data-cleanup DB write | **NEW (one-shot)** | No general "null-out row" service exists; will be a supervised SQL script under `scripts/one_shots/`. No permanent code. |
| Docstring correction at `_dp_house_load_kw` | **EXTEND** | `energy.py:4352-4394` docstring says "R1 fitted-model" but reads legacy `predicted_consumption_kwh`. Documentation-only. |

### Code locations surveyed end-to-end
- `energy.py`: 1370-1460 (restore path), 2225-2360 (regression restore + midnight-snapshot restore/save), 2470-2500 (snapshot payload), 2700-2950 (lifetime getters + daily derivation + rollover snapshot set + `_save_daily_snapshot`), 3010-3100 (cross-check re-seed), 4340-4400 (`_dp_house_load_kw`), 8521 & 9136 (extra `_save_midnight_snapshot` callers, no snapshot mutation), 10577-10600 (`_get_state_float`).
- `energy_forecast.py`: 129-170, 300-420, 730-780, 880-910 (estimator + adjustment factor + DOW deque).
- `database.py`: 4438-4560, 4519, 4542, 5041-5070 (`log_energy_daily`, `get_energy_daily_recent`, `get_energy_temp_pairs`, `get_consumption_history`), 2321-2328 restore path.
- `energy_const.py`: 136 (D-MED-1 R2-flip note), 170 `CONF_R1_ESTIMATOR_SHADOW_ONLY`, 1585 default house-load source.
- `config_flow.py:4637-4645, 5777-5861`, `select.py:767-788` — the D0 knob.

### Kanban adjacency
- `ENVOY-FLAKINESS-181243-1` — physical cause of the 0.045505 glitch (Session-closed / firmware-check bug). **Non-goal here.** This card unblocks *tolerance*, not *cause*.
- `COVERAGE-EVENING-ATTRIBUTION-DRIFT-1` — separate concern (net vs total consumption sensor). Uses different lifetime sensor and different math; the D2 read-side ceiling helps both by evicting the same poisoned rows, but the coverage arithmetic is not otherwise re-scoped here.

---

## Independent site enumeration

### Lifetime-counter READ sites (grep `_get_lifetime_` in energy.py)
`_get_lifetime_consumption` (2714), `_get_lifetime_production` (2718), `_get_lifetime_net_import` (2722), `_get_lifetime_net_export` (2726), `_get_lifetime_battery_discharged` (2730), `_get_lifetime_battery_charged` (2734). All six ultimately call `_get_state_float` at 10577 which lacks a monotonic guard.

### Snapshot payload construction (must include LKG)
`energy.py:2491-2496` (snapshot-payload dict — sibling to save site).

### Snapshot SET sites (mutate `_lifetime_*_snapshot`) — hypothesis check vs audit
The audit lists three (2895-2919 rollover + seed-if-None, 3081-3097 cross-check re-seed, restore 2321-2328). Independent re-grep confirms the same three, no fourth:

1. **Rollover** — `energy.py:2895-2896` (`_lifetime_consumption_snapshot = current_lifetime; _lifetime_production_snapshot = current_production`), then `_save_midnight_snapshot()` scheduled at 2905.
2. **Seed-if-None** — `energy.py:2908-2911` (post-rollover safety net for a None counter earlier in the day).
3. **Cross-check re-seed** — `energy.py:3081-3097` (`_check_and_correct_snapshots`, re-seeds ALL six counters if any drift exceeds the internal cross-check).
4. **DB restore** — `energy.py:2321-2328` (same-day restore of the six counters + `snapshot_date`).

All four MUST route through the new `_accept_lifetime_reading` guard, and (3) must also validate DB-restored values against the live reading (else a stale glitched DB row poisons a fresh boot).

**Two additional `_save_midnight_snapshot()` callers** (`energy.py:8521, 9136`) do NOT mutate snapshot values — they only re-persist the current in-memory state — but they DO become poison-persistence channels if the in-memory state is already poisoned. No new logic needed; they are protected transitively by guarding the four sites above.

### Daily-derivation site (Δ compute)
`energy.py:2745-2823` — must consult the LKG guard on both `current_*` and `_..._snapshot` before subtracting; existing negative-delta guard (`:2789`) and `actual_kwh <= 0` guard (`:2825`) remain but do NOT catch the overcount case.

### `energy_daily` READER sites (grep confirmed)
- `energy.py:1441` → `db.get_energy_daily_recent(30)` — accuracy / adjustment-factor refit. Only lower-bound `>= 10` filter at 1446.
- `energy.py:2235` → `db.get_energy_temp_pairs(min_days=30)` — temperature regression refit on every startup (`:1371`).
- `energy.py:2270` → `db.get_consumption_history(days=60)` — DOW deques.
- `energy_forecast.py:766-774` `record_actual_consumption` — in-memory DOW push during a running day.
- Display sensors (no trust): `sensor.py:11652-11774` via `energy.forecast_today` / `energy.py:10052/10095-10126`; diagnostics `energy.py:10733`.
- `_dp_house_load_kw` (`energy.py:4352-4394`) — **TRUST** consumer of `predicted_consumption_kwh`, feeds Battery-Aware EV Charging.

All READER sites must apply the plausibility ceiling before feeding the value into (a) regression fit, (b) DOW deque, (c) adjustment factor, (d) in-memory `record_actual_consumption`.

---

## Deliverables

### D0 — Config-first: operator knob flip (OPERATOR DECISION)
Flip `select.ura_energy_coordinator_dp_house_load_source` from `max_span_r1` to `live_span`. Zero code, reversible, removes the only *decision* consumer's exposure while D1–D3 land.

**Trade-off (must be surfaced to operator):** `live_span` uses SPAN R1+R2 minus EV load. SPAN occasionally reads ~0 kW (e.g. 09-06 21:09) → `_dp_house_load_kw` may return near-zero → DP evaluates with unusually low load → abstains with `MISSING_INPUTS` or `already_below_target` more often (audit §6 counterfactual). The audit shows 0 measured verdict flips even under the poisoned `max_span_r1` state, so this is a small-margin change either way.

**Acceptance criteria**
- **Operator confirms:** knob observed at `live_span` in the UI; `select.py:785` `_conf_key` persists via options flow.
- **Live:** next DP eval snapshot in `sensor.ura_energy_coordinator_ev_charging_plan` shows `house_load_kw` no longer equal to `predicted_consumption_kwh / 24` within ±0.02 (the current 30/31 pattern breaks).
- **Discriminating:** if `live_span` reads 0 during eval, the eval reports `MISSING_INPUTS`, not a decision using 0.

### D1 — Producer guard: monotonic lifetime + daily ceiling + anomaly
Add `_accept_lifetime_reading(counter_name: str, value_mwh: float | None, last_known_good_mwh: float | None) -> float | None`. Returns `value_mwh` if `value_mwh is not None AND (last_known_good_mwh is None OR value_mwh >= last_known_good_mwh - LIFETIME_REGRESS_TOLERANCE_MWH)`; else returns `None` and increments an anomaly counter.

Wire at:
1. Each of the six `_get_lifetime_*` (2714-2736) — read-path: reject regressed values BEFORE they reach any snapshot-set site or Δ compute.
2. Rollover snapshot set (2895-2896): guard `current_lifetime` / `current_production` against the outgoing `_lifetime_*_snapshot` (which becomes the new LKG) before overwriting.
3. Seed-if-None (2908-2911): a None snapshot may accept a first reading only if it passes the persisted LKG (from restore or last save).
4. Cross-check re-seed (3081-3097): the "corrected" value MUST pass the guard vs the incumbent snapshot; if not, keep incumbent and emit anomaly.
5. Restore (2321-2328): reject a restored snapshot that is `> live_current + ε` (a stale DB row from a glitched save poisons the boot — same 0.045505 sequence). If rejected, treat as no-snapshot and let seed-if-None do its job at rollover.

Persist LKG per counter in the midnight-snapshot payload (extend `_save_midnight_snapshot` `energy.py:2371-2375` + DAO shape; **additive column, no back-compat migration risk beyond Tier 2-DB DAO change** — Review B target).

Daily-ceiling guard in `_save_daily_snapshot` (2921) BEFORE `log_energy_daily`: if `actual_kwh > DAILY_CONSUMPTION_MAX_KWH` or `solar_produced_kwh > DAILY_SOLAR_MAX_KWH`, write NULL for that field and emit anomaly `energy.daily_plausibility_reject` with the raw computed value + counter LKGs in the payload.

**Acceptance criteria**
- **Test:** `test_lifetime_reading_regression_rejected` — feed the recorded 0.045505 sequence into a stubbed `_get_state_float`; assert `_lifetime_production_snapshot` never adopts 0.045505 once LKG ≥ 10 MWh; assert `energy_daily` write is either NULL or plausible.
- **Test (each of 4 SET sites):** per-site mutation — comment out the guard at each site individually; a distinct test must fail per site. If any bypass leaves the suite green, that site is untested.
- **Test:** `test_daily_ceiling_writes_null_and_anomaly` — a synthetic Δ of 18,850 kWh writes NULL + fires anomaly with the expected payload keys.
- **Test:** `test_restore_rejects_stale_glitched_snapshot` — DB restore path (2321-2328) with `lifetime_production = 0.045505` and live `_get_lifetime_production` = 15.8 MWh must not adopt 0.045505.
- **Sensor:** `sensor.ura_energy_coordinator_energy_forecast_today` — after next full-day cycle, `predicted_consumption_kwh` returns to the 126-175 kWh envelope of the shadow v1 arm within 1 restart.
- **Live (2026-09-30 00:00):** the 2026-09-29 `energy_daily` row is EITHER NULL (baseline rejected) OR ≤ `DAILY_CONSUMPTION_MAX_KWH` — **not** ≈ 18,850 and **not** silently 0. Cross-check: an anomaly of type `energy.daily_plausibility_reject` OR `energy.lifetime_regress_reject` appears in the anomaly table with a today-dated `at`.
- **Live (discriminator):** `energy_midnight_snapshot` row for 2026-09-30 carries `lifetime_production ≥ last_known_good − ε`, never 0.045505.

### D2 — Consumer/read-side range filter
At the three DAO consumers (`energy.py:1441`, `:2235`, `:2270`), apply symmetric bounds:
- `energy.py:1446` (existing lower-bound filter): also drop rows where `consumption_kwh > DAILY_CONSUMPTION_MAX_KWH` OR `solar_production_kwh > DAILY_SOLAR_MAX_KWH`. Bound `prediction_error_pct` to ±500 % before feeding `get_adjustment_factor` (`energy_forecast.py:893-908`).
- Regression pairs (2235): drop pairs whose `consumption > DAILY_CONSUMPTION_MAX_KWH`.
- DOW history (2270): drop rows above ceiling before the `record_actual_consumption` push.

Prefer caller-side filtering (leaves `database.py` DAO shape stable → passes Review B migration-correctness). Add a single `_is_plausible_daily_row(row)` helper.

**Acceptance criteria**
- **Test:** `test_read_side_filters_evict_poisoned_rows` — a fixture DB with the 4 real poisoned rows (2026-06-19 / 08-20 / 08-28 / 08-30) yields a regression fit with base ≈ 135.6 and coeff ≈ +1.85 (matches the audit's clean numbers within 5%).
- **Test:** `test_adjustment_factor_bounded_error` — an 8,014 % error row does NOT drag adj to 1.3.
- **Live:** post-restart, `sensor.ura_energy_coordinator_energy_forecast_today` `shadow_predicted_consumption_kwh` and `predicted_consumption_kwh` differ by < 30 kWh (currently 327 vs 146 = 181 kWh gap).
- **Live discriminator:** even BEFORE D3 cleanup, restarting HA post-D2 produces a plausible regression fit (base < 300, coeff > 0). If not, D2 is broken.

### D3 — Data cleanup (DESTRUCTIVE — OPERATOR APPROVAL REQUIRED, SUPERVISED)
One-shot SQL under `scripts/one_shots/cleanup_energy_daily_poisoned_rows.py` (invoked via `ssh ha "python3 -" < script`). Behaviour:

1. **Backup first (MANDATORY):** `cp /config/universal_room_automation/data/universal_room_automation.db /config/universal_room_automation/data/universal_room_automation.db.bak_YYYYMMDD_HHMM` — verify `ls -la` shows same byte count before proceeding.
2. **Confirm target rows** by re-running the audit-B discriminator on those 4 dates (proves nothing new has landed).
3. **Execute:**
   ```sql
   UPDATE energy_daily
      SET consumption_kwh = NULL,
          solar_production_kwh = NULL,
          predicted_consumption_kwh = NULL,
          prediction_error_pct = NULL
    WHERE date IN ('2026-06-19', '2026-08-20', '2026-08-28', '2026-08-30');
   ```
4. **Consider (operator decides row-by-row):** the two zero-solar undercount rows 2026-09-24 (48 kWh) and 2026-09-25 (78 kWh). Recommendation: NULL them too, same UPDATE with `date IN ('2026-09-24','2026-09-25')` — they poison DOW deques asymmetrically.
5. **Consider:** if the 2026-09-29 row was written poisoned before D1 shipped, add it to the same UPDATE.
6. **Verify:** re-run probe section A; assert 0 rows with `consumption_kwh > 1000` OR `solar_production_kwh > 300`.

**Acceptance criteria**
- **Operator:** explicit "go" logged in vibememo; backup path confirmed.
- **DB:** `SELECT COUNT(*) FROM energy_daily WHERE consumption_kwh > 1000 OR solar_production_kwh > 300` returns 0.
- **Live post-restart:** temperature regression fit reports base ≈ 135, coeff ≈ +1.85 in coordinator init log (`energy.py:2225-2258` refit path).
- **Discriminating:** the 4 dates now return NULL for both columns; other dates are untouched (`SELECT COUNT(*) FROM energy_daily WHERE consumption_kwh IS NOT NULL` decreases by exactly the number of cleaned rows).

### D4 — Docstring / concept-split fix (OPTIONAL, small)
At `_dp_house_load_kw` (`energy.py:4352-4394`): docstring claims "R1 fitted-model", but reads `predicted_consumption_kwh` = the **legacy** arm while `CONF_R1_ESTIMATOR_SHADOW_ONLY = True`. Fix docstring to name the legacy arm explicitly, OR (parsimony alternative, tracked separately) point the reader at `shadow_predicted_consumption_kwh`. **D4 in this cycle = docstring only.** Repointing is a decision-changing edit and belongs to the R2-flip cycle (`energy_const.py:136`).

**Acceptance criteria**
- Docstring names the actual field read; grep of the fix returns the corrected wording.

---

## Non-goals

- **Physical cause of Envoy's 0.045505 MWh glitch** — ENVOY-FLAKINESS-181243-1. This cycle *tolerates* the glitch; it does not *fix* Envoy.
- **Net vs total consumption sensor selection** — COVERAGE-EVENING-ATTRIBUTION-DRIFT-1.
- **`CONF_R1_ESTIMATOR_SHADOW_ONLY` flip** — the v1 arm is history-immune but flipping it is a decision change (see `energy_const.py:170` and D-MED-1 note at `:136`). Tracked separately; recommended AFTER D1–D3 land and refit is clean.
- **Net Energy sign convention** (audit §Not measured) — dashboard/audit card, separate scope.
- **Repoint `_dp_house_load_kw` to shadow v1** — belongs to R2-flip cycle, not here.
- **Retrofit anomaly channel taxonomy** — reuse existing channel shape; no channel-registry redesign.

---

## Numbers get knobs — ladder placement

| Number | Value (proposed) | Rung | Why |
|---|---|---|---|
| `DAILY_CONSUMPTION_MAX_KWH` | 600 | 1 (module constant, `energy_const.py`) | Safety bound on stored history; changing it invites drift in the DOW / regression fit and the accuracy adj factor. Must require review. |
| `DAILY_SOLAR_MAX_KWH` | 300 | 1 | Same argument. Roughly 2× nameplate day; leaves room for real edge highs, catches 6,700-15,900 poisoning. |
| `LIFETIME_REGRESS_TOLERANCE_MWH` | 0.001 (1 kWh) | 1 | Guards against float noise on legit Envoy reads; a wider tolerance would admit small regressions. Review-gated. |
| Anomaly channel name | `energy.daily_plausibility_reject`, `energy.lifetime_regress_reject` | Constants (module) | Named, greppable; not user-tunable. |
| `select.ura_energy_coordinator_dp_house_load_source` (D0) | flip to `live_span` | 3 (live entity) | Already at correct rung; operator turns it now, may revert after D1-D3. |
| `CONF_R1_ESTIMATOR_SHADOW_ONLY` (out of scope) | still `True` | 1 today | Flip is decision-changing; separate cycle. |

---

## Producer AND Consumer map (per operator 2026-08-16 rule)

**Producer of `energy_daily.consumption_kwh` / `.solar_production_kwh`:**
- Six lifetime getters (2714-2736) → `_get_state_float` (10577, no monotonic guard) → deltas at 2745-2823 → snapshot mutate (2895-2919 / 3081-3097 / 2321-2328) → `_save_daily_snapshot` (2921) → `log_energy_daily` (database.py:4438-4480).
- **Health of dependency:** production lifetime sensor glitched at 12/28 September midnights (audit §1). Currently glitched right now (`energy_midnight_snapshot.lifetime_production = 0.045505`). Consumption lifetime sensor equally exposed by symmetry (same Envoy transport, same `_get_state_float`).

**Consumers (trust vs display):**
| Consumer | Site | Class |
|---|---|---|
| `_dp_house_load_kw` → EV Battery-Aware charging | `energy.py:4352-4394` → `energy_drain_precedence.py:673-678` | **TRUST** (decision) |
| Accuracy / adjustment factor (self-referential feedback) | `energy.py:1420-1458` + `energy_forecast.py:893-908` | **TRUST** (feeds next prediction) |
| Temperature regression refit (every startup) | `energy.py:2225-2258` | **TRUST** (feeds legacy estimator) |
| Per-DOW deque | `energy.py:2264-2274` + `energy_forecast.py:766-774` | **TRUST** (feeds legacy estimator) |
| Forecast display sensors | `sensor.py:11652-11774` | display |
| Diagnostics blob | `energy.py:10733` | display |
| `_solar_forecast_error_baseline` | `energy.py:2863`, restored `:8792` | persisted only, no decision consumer found by grep |

---

## Tier classification

**Tier 2-DB (3 framing-disjoint reviews) + Plan Review (1 pass, per operator 2026-08-11 rule).**

**Why Tier 2-DB (not Tier 1 or 2):**
- Touches the producer that feeds daily billing / consumption accounting.
- Changes DAO-adjacent payload shape (adds LKG fields to `save_midnight_snapshot` / `restore_midnight_snapshot`).
- Includes a destructive DB write (D3).
- Under the standing 2026-06-08 policy (`feedback_tier2db_for_regression_prone`), regression-prone work defaults to Tier 2-DB even absent DAO changes.

**Why NOT Tier 3:**
- The invariant is **local and simple** (INV-LCP1: no persisted delta with regressed baseline or above ceiling), not threaded through many emission sites. The four snapshot-set sites are enumerated and finite.
- **No measured decision impact today** (audit §6: 0 verdict flips in the 18 rebuildable evals). Tier 3 is reserved for cost-AND-safety-impacting cycles with live blast radius or multi-site emission surfaces (the v5.5.3 arbitrage archetype).
- D0 is a config flip, not code; blast radius per code deliverable is one file (energy.py), one DAO row shape (database.py), and one one-shot script (D3).
- **Operator may elevate to Tier 3 if:** they judge the DAO-shape extension (LKG columns) high-blast; or they want a fourth adversarial-completeness pass on the snapshot-set enumeration (a 4th snapshot site the plan missed would be exactly the Tier 3 failure mode).

### Review framings
- **Review A — arithmetic + guard correctness.** Δ math at 2745-2823 with the new guard interposed; `_accept_lifetime_reading` behaviour incl. **Envoy-legitimate resets** (a real firmware/battery reset that lowers a lifetime counter — should this stay latched to old LKG forever? Recommended policy: latched forever unless operator "reset LKG" button; document explicitly). Ceiling values vs nameplate.
- **Review B — restart / restore / midnight-boundary interplay + DAO shape.** Interaction of restore (2321-2328) ↔ seed-if-None (2908-2911) ↔ cross-check re-seed (3081-3097) ↔ rollover (2895-2896) across a HA restart in the middle of a glitch window. DAO payload extension safety; existing readers unaffected; INSERT OR REPLACE preserves the new columns; migration path for existing DB.
- **Review C — test authority + new-surfaces round-trip.** Per-site mutation drill on each of the 4 SET sites (Tier-2-DB test-authority discipline elevated toward Tier 3's C framing — appropriate given the "one missed site" failure shape). Fixture replays the recorded 0.045505 sequence from the probe. Anomaly emissions round-trip through the existing dispatch shape.

Plan-review (single pass) verifies: institutional-context section complete; INV-LCP1 falsifiable; independent re-grep of the 4 snapshot sites (this plan's list is a hypothesis); knob-ladder placement; D3 backup gate present; D0 trade-off surfaced to operator.

---

## Plan completion tracking

Items deferred (not dropped):
- **`CONF_R1_ESTIMATOR_SHADOW_ONLY` flip** → tracked at `energy_const.py:136` D-MED-1 note; new card recommended after D1–D3 ship.
- **Repoint `_dp_house_load_kw` to `shadow_predicted_consumption_kwh`** → carded with the R2-flip cycle.
- **Envoy 0.045505 physical cause** → ENVOY-FLAKINESS-181243-1.
- **Net-consumption sensor selection** → COVERAGE-EVENING-ATTRIBUTION-DRIFT-1.
- **381 `dp_eval` rows with stale-reason logging quirk** → audit §6 flagged; recommend new card if operator wants.
- **"Reset LKG" operator button** — mentioned in Review A framing; deferred to a follow-up card unless the review requires it in-cycle.

---

## Post-ship supersession & consumer-gap audit (scheduled)

After D1-D3 ship and one clean day passes, run the standing post-ship audit against the *pre-existing energy-hygiene domain*: any old ad-hoc plausibility comments/heuristics in `energy.py` / `energy_forecast.py` that are superseded by `_accept_lifetime_reading` + the D2 filter, and any downstream that OUGHT to consume the new anomaly channel but doesn't yet (e.g. an NM tile summarising energy-hygiene rejects). Do not delete on that pass — bucket into DELETE / KEEP+WIRE / KEEP+DOCUMENT.
