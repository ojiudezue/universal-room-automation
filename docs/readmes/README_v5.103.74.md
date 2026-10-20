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

## Validated 2026-10-20

Restarts carrying this build: 02:05 CDT (07:05:40Z, recorder run 1199) and 09:59 CDT (14:59:25Z, run 1200). Evidence comes from the 09:59 boot unless marked. Read-only checks (ha-mcp, the recorder DB, the URA DB via `ssh ha`).

| Criterion | Result | Evidence |
|---|---|---|
| Install and load | PASS | `/config/custom_components/universal_room_automation/manifest.json` version `v5.103.75` (it carries .73 and .74). `ha_get_integration`: 50/50 URA entries `loaded`. `system_log` ERROR filter for URA: 0 entries. error_log after boot has WARNING-level boot transients only (sensors unavailable for 60s, census cameras unavailable, HA deprecation notices). |
| No "reserve witness fallback" INFO line | Cannot observe | The URA logger runs at WARNING (`log_level_raw: 30` on every entry), so this INFO line can't show in logs either way. Indirect evidence: `sensor.envoy_482543015950_reserve_battery_level` exists and resolves (state `10`). |
| Witness reads the live sensor, not 10 | As expected, but this test can't tell the two apart | Live reserve is 10 (`sensor.envoy_482543015950_reserve_battery_level = 10`; strategy `last_verified_write_reserve_soc.oracle_seen = "10.0"`, commanded 10). The live value equals the old hard-coded 10, so this reading can't distinguish the fix from the bug. At 09:59 the Envoy was still coming up (`envoy_available: false`, `command_trail.hardware_enforced.value = null`). Re-check when the reserve is above 10. |
| Divergence rows drop | PASS (early) | URA DB `anomaly_log`, `metric_name LIKE '%witness_divergence%'`: **0 rows since 07:05Z** (02:05 CDT). Daily baseline: 10-10 35, 10-11 172, 10-12 58, 10-13 16, 10-14 37, 10-15 29, 10-16 32, 10-17 120, 10-19 21. Caveat: 10-18, and 10-20 before the restart, also had 0, so ~8 h at zero is consistent with the fix but doesn't prove it yet. |
| No false `pending_write_stuck` pages with `oracle_seen=10.0` | PASS | 0 `pending_write_stuck` anomaly rows since 07:05Z. There were 2 `write_verification_failed` rows (09:16Z, 09:36Z), both `reason: self_heal_starvation` on `reserve_soc` commanded 10. That is a different path and not a stuck-write page. Strategy attribute `pending_write_stuck_state.reserve_soc.active = false`. |

Restart: installed, **restart held**. It ships in the same restart as v5.103.73.
