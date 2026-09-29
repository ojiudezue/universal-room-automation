# Plan Review — PLANNING_energy_lifetime_counter_poisoning.md

**Date:** 2026-09-29
**Card:** ENERGY-CONSUMPTION-FORECAST-POISONED-1
**Verdict:** PLAN-FIX-REQUIRED (rev 1) → revised rev 2 folds all findings.

## Findings (from coordinator plan-review pass)

### CRIT — plan defect, blocks build
- **CRIT-1 — Ceiling placed too late in `_maybe_reset_daily`.** `_maybe_reset_daily` feeds `actual_kwh` into `record_actual_consumption` (`energy.py:2840`), `evaluate_accuracy` (`:2845`), `get_adjustment_factor` (`:2854`), and `_solar_forecast_error_baseline.update` (`:2860`) BEFORE the async `_save_daily_snapshot` (`:2877`). A ceiling that runs inside `_save_daily_snapshot` (or in the DAO) leaves in-memory learning already poisoned for that day. **Fix:** place `_apply_daily_ceiling` immediately after the `actual_kwh <= 0` guard at `:2824-2830` and BEFORE `:2839`; on trip set both `actual_kwh` and `solar_produced_kwh` to None. Add acceptance: after the trip midnight, with no restart, `predicted_consumption_kwh` stays inside the shadow-arm band and no DOW deque entry exceeds the ceiling.
- **CRIT-2 — Restore rule inverted.** Rev 1 said "reject restored snapshot > live+ε". That ACCEPTS 0.045505 (which is BELOW live ~18.8 MWh) — the exact live case today (`energy_midnight_snapshot` = `2026-09-29 | cons NULL | prod 0.045505`). Contradicts the sibling test. **Fix:** reject if `snapshot < LKG − ε` OR `(live − snapshot) × 1000 > DAILY_*_MAX_KWH`; if live is None at restore, defer acceptance to first accepted live read; restore LKG irrespective of `snapshot_date` (which only gates the snapshot values, `:2320`).

### HIGH — correctness/completeness, must fix in plan
- **HIGH-3 — LKG semantics drift + invariant misses low-snapshot case.** "LKG" was used to mean three things (max-accepted, last-seen, persisted-snapshot). Define once: **LKG(counter) = max accepted reading + ts**; accept iff `≥ LKG − ε` AND `≤ LKG + MAX_LIFETIME_JUMP × elapsed`. Restate invariant so both endpoints must be accepted.
- **HIGH-4 — Legit-reset policy unspecified.** Latch-forever converts one lost day into permanent loss. Glitch = constant non-growing value; real reset = growing from low. Add: re-baseline LKG downward after `N` accepted monotonically-increasing reads spanning `LKG_STALE_REBASELINE_HOURS`, with anomaly; add upper-jump bound.
- **HIGH-5 — Cross-check re-seed site is unreachable.** `energy.py:3077-3097` sits inside `elif divergence_pct < 5` (`:3065`) AND further gated by `envoy_today_kwh > our_delta_kwh * 2 and our_delta_kwh < 5` (`:3077`) — mutually exclusive at any reasonable magnitude. Also gated dark by `:3014` early-return (live `lifetime_consumption` is NULL today). Introduced v4.3.0 commit `2c8f9c389`; stranded. **Fix:** drop from guarded SET sites; classify KEEP+DOCUMENT (do not delete this cycle, card follow-up) with proof.
- **HIGH-6 — Two-layer guard makes per-site drills pass by design.** Guarding getters AND SET sites means neutering one leaves the other covering it (drill green even though a site is unguarded). **Fix:** single guard point at the getters; separately guard restore (`:2321-2328`) and the subtraction endpoints (`:2745-2823`); drill those three.
- **HIGH-7 — New undercount path introduced by the fix.** Getter rejects at midnight → rollover leaves snapshot None (`:2896`) → mid-day seed-if-None (`:2911`) → part-day row passes ceiling, drags DOW deque down (audit: 06-19 and 08-28 were mid-day seeds). **Fix:** seed from LKG when LKG age `< LKG_STALE_REBASELINE_HOURS` (production is flat overnight); else mark `partial_day = 1` and row NULL. Scope restart-mid-day seeding explicitly.
- **HIGH-8 — Second-order poisoning via unbounded `pct_error` on control path.** Rows with clean consumption but poisoned prediction (09-01 predicted 0.1, error 213,147%; 09-04..09-12 −39..−92%) keep adj factor pinned. `PCT_ERROR_BOUND = 200` + `pct_error_bounded` already exist (`energy_forecast.py:41-42, 829-875`) but `PLANNING_forecast_accuracy_fix.md` deliberately kept the control path raw. Live `evaluate_accuracy` (`energy.py:2845` → `energy_forecast.py:852-880`) is still unbounded. **Fix:** explicit decision to extend the clamp to the control path; do NOT rely on the `:1446` filter (which is consumption-only anyway — see MED-10).

### MED — planning corrections
- **MED-9 — Prior art was under-scanned.**
  - `save_energy_state` / `restore_energy_state` KV (`database.py:4959, :4972`, e.g. `peak_avoidance_snapshot` at `energy.py:2390`) removes any need for schema change to persist LKG.
  - `lkg.py` `LkgValue.to_blob/from_blob` = serialisation prior art.
  - `envoy_cache` table (`database.py:1232`) exists; not the vehicle here but shows the pattern.
  - Rev 1 claimed midnight-snapshot payload lives at `energy.py:2491-2496` — WRONG; that is `save_envoy_cache` payload. Actual midnight-snapshot payload is at `:2371-2375`.
  - Solar ceiling ignored `CONF_ENERGY_SOLAR_NAMEPLATE_W` (`energy_const.py:915`, 19.4 kW); derive, don't hardcode.
- **MED-10 — `:1446` solar filter is a no-op.** `get_energy_daily_recent` (`database.py:4528`) does NOT project `solar_production_kwh`. Read-side ceilings must target the specific SELECTs. Split the audit's "2270" locus into restore path (`energy_forecast.py:736`) vs live push (`energy.py:2840` — the CRIT-1 target).
- **MED-11 — Anomaly cadence.** One anomaly per counter per rejection episode (≤1/day) via `_store_crosscheck_anomaly_event` pattern (`energy.py:3099`); otherwise write-flood risk.
- **MED-12 — ε not measured.** Add one-shot recorder probe over all 6 lifetime sensors for hour-to-hour decreases BEFORE choosing ε (measure-before-build). Mark as D-1 gate.
- **MED-13 — D3 hygiene errors.** Backup via `sqlite3 ".backup"` or `VACUUM INTO`, NOT `cp` (WAL DB is unsafe under `cp`); check free space. NULL is correct (readers filter `IS NOT NULL` at `database.py:4532, :4555, :5053`; DELETE would drop billing columns summed by `get_energy_daily_for_cycle` `:4482`). Do NOT null `predicted_consumption_kwh` (diagnostic value; the prediction was what the model said at the time). Verify with the actual constants, not the `>1000` heuristic. Include 09-24/25.
- **MED-14 — Site enumeration contradiction.** Rollover is `:2895-2900` (SIX counters). Rev 1 alternately said "two" and "no fourth site"; fix.
- **MED-15 — Live discriminator must be condition-based.** Frame acceptance around "the first midnight where the outgoing snapshot or the 00:00 reading equals 0.045505" (measurable from `energy_midnight_snapshot`), and distinguish success by the anomaly payload + absence of a predicted-consumption jump — not a wall-clock date.

### LOW — housekeeping
- **LOW-16** — Drop the "feeds daily billing" claim about `energy_daily`; billing runs off different sensors.
- **LOW-17** — Note `energy_forecast.py:661` display consumer. The guard MUST NOT live in shared `_get_state_float` (`energy.py:10577`) — that path is used by SPAN power reads and would break unrelated math.
- **LOW-18** — Name the regression fixture source: `scripts/probes/energy_consumption_forecast_poison_probe.py` section B (midnight-LTS reads for the four poisoned dates + today).

## Marginal-benefit pushback (added)
Rev 2 required to add an Option S (SIMPLIFY) vs Option F (FULL) section per CLAUDE.md. Option S = D0 + CRIT-1-placed-correctly + `partial_day` marker minimal + bounded `pct_error` on live path + D3. Option F = S + LKG ratchet + CRIT-2 restore rule + HIGH-4 reset policy. Must state which shapes S misses with measured frequency from the audit, recommend with margin reasoning, and keep per-option Tier (S = Tier 2, F = Tier 2-DB).

## Disposition
Rev 2 revised to fold CRIT-1, CRIT-2, HIGH-3, HIGH-4, HIGH-5, HIGH-6, HIGH-7, HIGH-8 into the plan body and Option F design; MED-9..MED-15 and LOW-16..LOW-18 folded into institutional context, site enumeration, D-1 gate, and D3 procedure. Option S vs F section added; recommendation: **Option F**, on measured margin (both-ends-glitched undercount at 1.0% of rows / 33% of glitch days is the specific shape S misses, and the LKG design has small containable ingredient cost since it reuses the KV DAO). Ready for build dispatch on Option F once D-1 probe reports ε.
