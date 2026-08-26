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

## Validated 2026-08-26 (post-restart, 01:39 CDT — a post-midnight, class-disagreement read)

Live-validated against the restarted instance (`sensor.ura_energy_coordinator_ev_charging_status` + `sensor.ura_energy_coordinator_battery_strategy`). SOC 15%, `soc_source=envoy` (primary), cloud divergence 0.2pp (healthy).

| Criterion | Observed evidence | Result |
|---|---|---|
| Cross-midnight anchoring keys to the peak day, not calendar-tomorrow | At 01:39 CDT (post-midnight): `target_day_source=solcast_today`, `target_day_class=excellent` — names **today's** class while `tomorrow_solar_class=good`. Pre-fix this would have read tomorrow's class. | **PASS** (the core fix, observed post-midnight) |
| INV-DTDS-3 — accessor / emitter / `_threshold_position` / `_next_action_estimate` all return the SAME drain target | `current_offpeak_drain_target=15` reads **15 identically** across `current_park_floor=15`, `current_commanded_reserve=15`, `effective_release_floor=15`, and `threshold_position` ("15.0%, target=excellent"). No naive-vs-composed divergence. `15` is the multi-day-max composed value (today excellent→10 lifted by d1/d2 good→15). | **PASS** |
| INV-DTDS-1 (display axis) — `tomorrow_solar_class` / `forecast_outlook.d1_class` stay calendar-D+1 | `tomorrow_solar_class=good`, `forecast_outlook.d1_class=good` — display axis unchanged, distinct from the peak-anchored `target_day_class=excellent`. | **PASS** |
| D6 — `ev_charging_status` publishes DP decision attrs with `dp_source` | `dp_state=hold_only`, `dp_last_eval_soc=7`, `dp_drain_floor=80`, `dp_eval_age_min=4116`, `dp_source=live` — all populated, non-sentinel, carrier-sourced (usefully surfacing the last DP eval is ~68h stale rather than hiding it). | **PASS** |
| D7 — per-EVSE structured `per_bay_state` | `garage_a/garage_b={state:idle,...}`; both Moes sockets `{state:charging, actual_kw:1.44}` (1440W→kW). idle↔charging discriminated live. `throttled`/`paused` labels present but not exercised (no throttle/pause event live — organic). | **PASS** (idle/charging axis proven; throttle discriminator awaits an organic throttle event) |
| No new URA errors post-restart | `error_log` scan: zero `custom_components.universal_room_automation` entries. Boot noise present is unrelated (wiim dup-IDs, mqtt reconnect, roborock, bermuda registry matches). | **PASS** |

**Deferred to a cleaner night (organic):** the *strict* reason-string parity discriminator — `arbitrage_phase ∈ {n/a, wait}` AND `hold_depth == allow_discharge` with `current_offpeak_drain_target` matching today's class value — could not run tonight because `arbitrage_phase=attain` (projection-driven grid catch-up to the 80% peak buffer). The `target_day_source=solcast_today` + `target_day_class=excellent` read is strong positive evidence in the meantime. Also note tonight the multi-day-max makes today's (excellent→10) and tomorrow's (good→15) *values* both resolve toward 15, so the value alone doesn't discriminate tonight — the class/source labels do.

**Boot transient dismissed:** both sensors read `unknown` for ~2 min post-restart until the energy coordinator's first tick (01:39:05), then published well-formed status. Expected warm-up, not a defect.
