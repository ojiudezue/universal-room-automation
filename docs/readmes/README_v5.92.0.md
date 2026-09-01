# v5.92.0 — EVSE/L1 charge-onset gate (SHIPS DORMANT)

**Card:** `EVSE-CHARGE-ONSET-TIME-1`
**Tier:** 3 (4 framing-disjoint reviews + 2 plan-reviews + orchestrator independent mutation-verify).
**Merge:** `feature/evse-charge-onset-v3@639596c06` → develop.
**Posture:** **ships DORMANT** — `switch.ura_ev_charge_onset_enabled` defaults **OFF**; on deploy the coordinator behaves byte-identically to v5.91.4 until the operator turns the switch on.

## Problem

The operator wants EV/L1 charging to hold until a configurable **onset time** (e.g. 01:00) so charging lands in the cheap overnight window instead of starting the moment off-peak opens. There is **no single "start charging" site** to gate — a charger is turned ON by ~15 sites across the coordinator (off-peak ensure-on, DP reversion, arbitrage release, fill-priority resume, drain-release, …). Two prior attempts failed by gating the wrong/incomplete site (v1 = drain-release only; v2 = ensure-on only, missed 6 paths — both backed out, develop verified untouched).

## Solution — a gated turn-on funnel

A shared `_charge_on_or_defer(...)` funnel wraps the `switch.turn_on` emission and **withholds it while the onset hold window is open**, at the real charge-START paths; escapes and true-solar bypass. The onset predicate `_evaluate_onset_gate` is a **bounded pre-onset window** (`0 < onset_instant − now ≤ ONSET_MAX_HOLD_H` = 8h) using the existing day-boundary primitive `next_occurrence_of_hhmm` (extracted from `compute_must_start_by`), with a must-start-by (03:00) escape.

**Gated (routed through the funnel / inline onset gate):** off-peak ensure-on (EVSE + plug), DP reversion, drain-release (EVSE + plug), **arbitrage release** (D-HIGH-1), **fill-priority `forecast_decayed` dusk leg** (EVSE + plug, D-HIGH-2). **Bypass (never gated):** DP must-start-by (03:00 liveness), excess-solar (daytime solar-share), force-charge. **Un-gated (documented, edge/rare):** `release_all_*` toggle paths, grid-cap resume.

**Knobs:** `time.ura_ev_charge_onset_time` (default "01:00") + config-flow TimeSelector; `switch.ura_ev_charge_onset_enabled` (default **OFF**) + config-flow bool — the kill switch; `ONSET_MAX_HOLD_H = 8.0` (module const); reused `CONF_DP_MUST_START_BY_MIN_PAST_MIDNIGHT` (03:00 escape). Observability: `binary_sensor.ura_ev_charge_onset_active`.

## Safety posture / invariants (all verified)

- **INV-ONSET:** enabled + inside the hold window + must-start not reached → the gated sites emit no `switch.turn_on` for an OFF charger. The daytime `soc_recovered` (solar-share) leg is intentionally **ungated**.
- **INV-NO-INTERRUPT:** the funnel only withholds a turn-on for an already-OFF charger — never emits `turn_off`, never interrupts a running charge.
- **INV-ESCAPE:** must-start-by (03:00) + force-charge always start; with default onset 01:00 < 03:00 the escape never binds and the 8h bounded window releases at 01:00 (L1 anti-stranding, restart-safe).
- **INV-BASELINE:** enable OFF / blank / malformed onset / now=None → byte-identical to v5.91.4.
- **INV-TURN-ON-ONLY:** no DP/drain/arbitrage/solar decision logic changed; no peer-owner added; only the turn-on emissions + additive wiring + the byte-faithful `next_occurrence_of_hhmm` extraction.
- **Cross-midnight:** drains 10pm day1 → held across midnight → releases 01:00 day2 (reuses the existing day-boundary code; named test + mutation anchor).

## Reviews

4 framing-disjoint Tier-3 reviews (A local-correctness SHIP, C test-authority SHIP, B FIX-REQUIRED→fixed, D FIX-REQUIRED→fixed) + 2 pre-build plan-reviews. Findings fixed: B-CRIT-A (enable switch was inert — bespoke subclass routes through `set_ev_charge_onset_enabled`), D-HIGH-1 (arbitrage release), D-HIGH-2 (fill-priority dusk), D-MED (observability + invariant wording), LOWs. **Orchestrator independently re-ran the neuters** — switch-routing / arbitrage / fill-priority / ensure-on / DP-reversion / drain-release all go RED on bypass (anchors are real; the prior hollow-anchor miss is closed). 75/75 cycle tests; 0 new full-suite failures vs develop. Record: `docs/reviews/code-review/` + `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` (turn-on surface map, D5) + `docs/reviews/URA_CODE_TRACING_METHODOLOGY.md`.

## Acceptance criteria

- **Verify (dormant boot):** post-deploy, `switch.ura_ev_charge_onset_enabled` = **off**; `time.ura_ev_charge_onset_time` = "01:00"; `binary_sensor.ura_ev_charge_onset_active` = off; clean boot, no new URA ERRORs; charger behavior byte-identical to v5.91.4.
- **Live (operator-gated test):** flip `switch.ura_ev_charge_onset_enabled` ON on an off-peak evening before 01:00 → garage_a/b + the Moes L1 sockets stay OFF (deferred), then turn ON at 01:00; flip OFF → they start immediately. `binary_sensor.ura_ev_charge_onset_active` reflects the held set.
- **Test:** 75 cycle tests; per-site neuter→RED for all gated sites + the switch.

## Validated 2026-08-31 (post-restart, dormant boot)

| Criterion | Observed evidence | Result |
|---|---|---|
| Entities registered on the CM entry | `switch.ura_energy_coordinator_ev_charge_onset_overnight`, `time.ura_energy_coordinator_ev_charge_onset_time`, `binary_sensor...ev_charge_onset_active_deferred`, `..._gate_open`, `sensor...ev_charge_onset_l1_over_hold_seconds` all present (B-CRIT-1 concern cleared live) | **PASS** |
| Ships dormant (enable OFF) | gate sensor attrs: `ev_onset_enabled=false`, `plug_onset_enabled=false`; `switch...overnight`=off | **PASS** |
| Functional onset time defaulted | gate sensor attrs: `ev_onset_time="01:00"`, `plug_onset_time="01:00"` (controller value — what the gate reads) | **PASS** |
| No spurious deferrals / holds | `binary_sensor...active_deferred`=off; `ev/plug_paused_by_battery_drain`=[]; `l1_over_hold_seconds`=0 | **PASS** |
| Byte-identical behavior (dormant) | `sensor.ura_energy_coordinator_ev_charging_status`=idle; house_state=home_evening; charger behavior unchanged | **PASS** |
| No new URA ERRORs | `error_log` structured scan (14:18–20:30): **zero ERROR/tracebacks**, zero onset-related lines; all URA entries WARNING + pre-existing (dead energy sensors per room-audit, FanPolicyOracle boot-lifecycle fallback, camera-census boot reconnect, Envoy warmup, SOC divergence) | **PASS** |

**Boot-only transient noted + dismissed:** `time.ura_energy_coordinator_ev_charge_onset_time` displays `unknown` on first boot (RestoreEntity, never set via the entity) while the *functional* onset value (controller attr `ev_onset_time`) is correctly `01:00`. The gate reads the controller attr, not the entity, so behavior is correct; the entity display is cosmetic. Polish candidate: seed the time entity's displayed value from the coord on boot (low-priority, non-blocking).

**Operator-gated live test (pending — the organic discriminator, per `--revisit`):** with `switch...ev_charge_onset_overnight` ON before 01:00 on an off-peak night → garage_a/garage_b + the Moes L1 sockets stay OFF (deferred), then all turn ON at ~01:00; flip OFF → start immediately. To be recorded when the operator runs it.
