# v5.103.74: the reserve write check reads the live Envoy reserve sensor

Card: EC-SELFHEAL-UNEXPLAINED-RESENDS-1. Audit: `docs/planning/AUDIT_ec_selfheal_resends_root_cause_2026_10_18.md`. Plan: `docs/planning/PLANNING_ec_reserve_witness_fix.md` (plan-reviewed). Reviews: `docs/reviews/code-review/ec_reserve_witness_review_AB.md` (A SHIP, B SHIP) and `_C.md` (SHIP, 24 mutations).

**Tier 2, raised to 3 framing-disjoint reviews.** It sits on the reserve write path's verification: it arms the 3 h stand-down and decides CRITICAL pages. Deploy risk: LOW. Only the read side changes.

## Problem → solution

- **The problem.** The reserve write verifier's local witness, `number.enpower_482348004678_reserve_battery_level`, has read only 10 (or unavailable) since 2026-08-05.
  - This caused 2–7 false resend attempts a day and 0–3 CRITICAL pages a day (`oracle_seen=10.0`), each arming a 3 h stand-down.
  - It also masked any real failure whose command was 10.
- **Operator ruling.** "Why a new setting? What's the real problem". So there is no new setting, the ±2 tolerance is unchanged, and `energy_reserve_soc_entity` is not repointed (it stays the write-fallback target).
- **The fix.** Only the reserve branch of `_local_entity_for` changes. It now prefers the official `enphase_envoy` reserve SENSOR (`sensor.envoy_<serial>_reserve_battery_level`, unique_id `<serial>_reserve_soc`).
  - The sensor is found through the entity registry, anchored on the configured SOC sensor's Envoy unique_id, so the general case works at any Envoy home.
  - It falls back to the number only when the sensor cannot be resolved (missing, disabled, or a non-Envoy SOC), with an INFO line logged once.
  - It never falls back because the sensor reads unavailable; it abstains instead.
- **Diagnostics.** The stuck-write anomaly row gains `hw_witness_entity`.
- **Unchanged:** the write path, the resend ladder, the stand-down, the CRITICAL logic, failover routing, and the charge-from-grid and storage-mode witnesses.

## Tests

- `test_ec_reserve_witness_resolution.py`: 17 tests.
  - Masked failure (10-12/13 case: commanded 10, sensor 14) escalates with `oracle_seen=14.0`.
  - Commanded 80 with sensor 80 stays silent.
  - 9 vs 10 is converged under ±2.
  - Unavailable abstains; a disabled sensor falls back; a non-Envoy SOC behaves as today.
  - The Enpower number with the same suffix is not picked.
  - An empty serial falls back.
- Mutation: builder M1–M7 plus the empty-serial guard; Review C ran 24 single-site mutations. All RED except equivalent or display-only mutants.
- Full name-diff at 7c3902cfd vs f9fb1f5ba: **CLEAN, 0 NEW / 0 GONE**.

## Residual (pre-existing, carded on the parent)

During an Envoy local outage the watchdog abstains with no time bound, and cloud verification still pages. The old witness had the same blind spot. A code trip-wire for "witness unavailable > N min while an episode is open" goes on EC-SELFHEAL-UNEXPLAINED-RESENDS-1.

## Live validation (to be replaced by a Validated table)

- **Load:** manifest v5.103.74 loaded, no URA ERRORs, no "reserve witness fallback" INFO line on this house (the sensor resolved).
- **Witness reads live:** the command trail's hardware witness reads the live sensor value, not 10.
- **Divergence rows drop:** `write_local_witness_divergence` rows fall from a 13–172/day baseline to near zero (one-shot DB query at disposal).
- **No false pages:** no `pending_write_stuck` rows with `oracle_seen=10.0` unless the sensor read 10.

Restart: installed, **restart held**. It ships in the same restart as v5.103.73.
