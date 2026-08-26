# v5.91.1 — Off-peak drain-target peak-anchored + DP/EVSE telemetry (DRAIN-TARGET-DAY-STALENESS-1)

**Cards:** `DRAIN-TARGET-DAY-STALENESS-1`, `DP-BATTERY-AUTHORITATIVE-TELEMETRY-1` (D6/D7)
**Tier:** 3 (reserve-affecting shared primitive; the value threads through the DP value-stamp — Bug Class #53).
**Branch:** `feature/midnight-drain-target` @ `30d5b95af` → merged to develop.

## What this ships

The off-peak drain target was keyed to **calendar-tomorrow** (`solcast_tomorrow`), so after local midnight it narrated and (via the DP stamp) drained toward the wrong day. This keys it to the **peak-anchored target day** through a single source of truth `_drain_target_for(now)`:

- **D1/D1b/D2** — `_resolve_target_day(now) -> (class, offset)` (peak-anchored) + `_drain_target_for(now)` (resolver + multi-day max), threaded into `current_offpeak_drain_target(now)`.
- **D3** — the emitter derivation, `_threshold_position`, and `_next_action_estimate` all route through `_drain_target_for`, killing the naive-vs-composed display divergence. **The partial_hold clamp and the DP value-stamp are preserved** — the stamp now carries the peak-anchored composed value to DP (HIGH-2, mutation-verified: repointing the derivation turns `test_dp_value_stamp_carries_peak_anchored_target` red). Cross-cycle effect: DP's drain floor becomes peak-anchored (and the mid-hold midnight discontinuity is removed).
- **D6 (telemetry)** — always-on DP decision attrs on `sensor.ura_energy_coordinator_ev_charging_status` (`dp_state`, `dp_last_eval_soc`, `dp_drain_floor`, `dp_eval_age_min`, `dp_source: live|shadow`), sourced from the carrier — no more diagnosing off display prose or a disabled sensor.
- **D7 (telemetry)** — per-EVSE structured `{state: paused|throttled|charging, owner, commanded_amps, actual_kw}` (throttle discriminated against the bay's captured baseline, not a hardcoded 48; `off` distinct from `paused`).

## Review

Tier-3, four framing-disjoint reviews. Core verdict SHIP (arithmetic/resolver/HIGH-2 stamp/INV-DTDS/DST/arbitrage-boundary all clean); 7 must-fix on narration + telemetry surfaces fixed in one pass (the convergent emitter reason-string, D6-blank-in-default-config shadow fallback, the two D7 label bugs, the resolver silent-except, the solcast-unavailable fallback). Orchestrator re-verified by hand (HIGH-2 stamp mutation bites; D6/D7 now mutation-anchored) — full-suite name-diff **0 new failures**. Consolidated: `docs/reviews/code-review/midnight_drain_target_consolidated.md`.

## Acceptance criteria

- **Verify:** at a stubbed `now` at offset 0 with class disagreement, the accessor, emitter pre-clamp, `_threshold_position`, and `_next_action_estimate` all return the SAME drain target (INV-DTDS-3).
- **Verify:** `tomorrow_solar_class` / `forecast_outlook.d1_class` stay calendar-D+1 (INV-DTDS-1 display axis).
- **Live (the discriminator):** on the next cross-midnight class-disagreement night, at ~02:00 CDT read `sensor.ura_energy_coordinator_battery_strategy` — `reason` names TODAY's class and `current_offpeak_drain_target` matches, NOT tomorrow's. Read `arbitrage_phase` + `hold_depth` first; the parity check discriminates when `arbitrage_phase ∈ {n/a, wait}` AND `hold_depth == allow_discharge`.
- **Live (telemetry):** `ev_charging_status` publishes the D6 dp_* attrs (with `dp_source`) and D7 `per_bay_state`.

## Post-deploy validation — (to be written back after a cross-midnight night)
