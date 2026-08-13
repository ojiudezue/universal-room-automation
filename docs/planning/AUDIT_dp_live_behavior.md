# AUDIT: EV Drain-Precedence — Live Behavior (read-only probe)

**Date:** 2026-08-12 (probe run against live URA DB + HA recorder, read-only)
**Scope correction:** DP is NOT in shadow mode. `switch.ura_energy_coordinator_battery_aware_ev_charging` is ON; actuation shipped in the v5.21–v5.24 arc. This audit replaces the originally-tasked shadow-eval probe (AUDIT_dp_shadow_eval_probe.md was never written; this doc is the deliverable).

## Data sources (all read-only)

| Surface | Location | Window |
|---|---|---|
| DP tick ledger | `decision_log` table, `decision_type='dp_eval'`, URA DB `/config/universal_room_automation/data/universal_room_automation.db` | 4,181 rows, 2026-07-23 12:54 → 2026-08-13 02:47 (21 nights) |
| Eval reason detail | HA recorder (`home-assistant_v2.db`), `sensor.ura_energy_coordinator_ev_charging_plan` attrs (`last_eval_snapshot`) | 1,653 state rows, ~2026-08-05 → now (recorder retention) |
| Current machine state | `energy_state` KV, key `drain_precedence_state_v1` | live |
| Pause provenance | `energy_state` keys `evse_dp_paused`, `evse_battery_drain_paused` | live, both `[]` |

## 1. Full decision history

- **4,181 dp_eval ticks over 21 nights** (~205/night, 5-min cadence, all `tou_period=off_peak` — the tick is gated to off-peak as designed).
- **State distribution: HOLD_ONLY 4,071 / HOLD_PRE_EVAL 110 / TRANSITIONED 0 / MUST_START_FORCED 0.**
- **Arms (hold engaged, HOLD_ONLY→HOLD_PRE_EVAL): 83 arm events across 6 nights** (07-23: 51, 07-24: 14, 07-25: 1, 08-03: 1, 08-07: 8, 08-11: 8). The other 15 nights had zero EVSE charging during off-peak (max charger rate 0.0 kW).
- **TRANSITIONED: never — 0 in 21 nights.** `evse_dp_paused` has never held a member in the live KV. The actuation leg (pause EVSE, release reserve, must-start-by force-release) has **never fired organically**.
- Current KV state: `hold_only`, last eval 2026-08-11T22:29 CDT, decision `transition=false reason=l1_only` (soc 26, drain_target 80, rate 1.42 kW, house 15.5 kW, must_start_by 03:00) — matches the live sensor.

## 2. Decline audit — were the declines right?

Observed decline reasons (recorder window + KV):

| Reason | Where seen | Verdict in hindsight |
|---|---|---|
| `l1_only` | 07-23 (all night, rate ~1.3 kW), 08-11 (1.41 kW) | **RIGHT.** The L1 carve-out is doing exactly its job: 25 kWh at 1.4 kW = ~18 h charge — can never fit before 03:00; pausing a 1.4 kW trickle buys ~nothing. Even without the gate, `already_below_target` would decline (soc 26 vs target 80). |
| `already_below_target` | 08-05/08-06 evals (soc 9, rate 3.35 kW L2) | **RIGHT.** Battery SOC (7–30 on every charging night at eval time) was far below `drain_target_soc=80` — there is nothing above the drain target to give the house, so pausing the car has zero drain yield. |
| `blind_hold` | 08-07 heavily (65 blind ticks; L2 up to 11.66 kW while Envoy blind), 08-11 pre-21:17 | **RIGHT per INV-DP4.** No fresh SOC → hold stands. On 08-07 the car charged at L2 the whole window with battery soc 7–14; a sighted eval would have declined `already_below_target` anyway — the blind gate cost nothing that night. |

**Structural fact:** with `drain_target_soc = 80`, a transition requires battery SOC > 80 *while an L2 EVSE is charging, off-peak, sighted*. In 21 nights that conjunction never occurred once — every night with L2 charging had battery SOC ≤ 30 at eval time (evening peak had already drained it). Every decline was arithmetically correct; the eval also never flapped to a wrong "fits".

## 3. Frozen-battery nights (the 07-16 "correct but not smart" shape)

Bounded at approximately zero cost in this window. On every charging night the battery was already at/below the drain target (soc 7–30 vs 80), so releasing the reserve would have yielded no additional house-serving drain — the hold "froze" a battery that had nothing to give. The one candidate exception, 08-07 (L2 up to 11.66 kW under blind_hold), still had soc ≤ 14 whenever sighted. No night in this window shows the eval declining wrongly or failing to run when it should have. A kWh/$ quantification was therefore not computed — the eval's own per-tick arithmetic (drain_soc_pp ≤ 0) already proves the counterfactual yield is 0 on every logged night.

## 4. Behavior notes / defects found (not blockers)

1. **`decision_log.reason` is always None (MEDIUM, one-line fix).** `_log_dp_eval_decision` reads `getattr(self._dp_carrier, "reason", None)` (energy.py:4002) but `DrainPrecedenceState` has no `reason` field — all 4,181 rows carry `reason: null`. The real reason lives only in the sensor attrs / KV `last_eval_snapshot` (recorder-retention-bound, ~10 days). Should read `carrier.last_eval_snapshot["decision"]["reason"]`.
2. **Arm/decline churn (LOW, cosmetic).** While an EVSE charges and the eval declines, the machine loops HOLD_ONLY→HOLD_PRE_EVAL→(eval declines)→HOLD_ONLY every ~eval_delay (5 min live) — 102 state flips on 07-23, each edge KV-persisting (~12 writes/h while charging). Not actuation flapping (nothing is paused/unpaused), and write volume is modest, but a "declined recently, same inputs" backoff would quiet it if it ever bothers anyone.
3. **Stale `last_eval_snapshot` echo (INFO).** The sensor attrs repeat the last eval's snapshot (e.g. the 08-05 soc-9 snapshot echoed through 08-10) — expected event-anchored semantics per DP-OBSERVABILITY-1, just noting for future log readers.
4. Live knob values at last eval: eval_delay 5 min, margin 60 min, must_start_by 03:00, needed_kwh 25 (garage A), drain_target 80, house_load_source per select entity. Knob surfaces confirmed shipped: `switch...battery_aware_ev_charging`, `number...dp_eval_delay`, `dp_safety_margin`, `dp_must_start_by_min_past_midnight`, `dp_needed_kwh_garage_a/b`, `number...ev_battery_drain_soc`, `select...dp_house_load_source`.

## 5. Verdict — go/no-go on a remaining build

**NO remaining build. Close the card as shipped-with-organic-validation-pending.**

The state machine, eval math, gates (L1 carve-out, blind-hold, below-target, force-charge yield), knob surfaces, and actuation plumbing are live and behaving to spec; 21 nights of declines are all correct in hindsight; zero wrong-transition or flap-to-fits events. The only untested leg is the TRANSITIONED path itself, which has simply never been applicable (battery is always drained below target by plug-in time under the current drain_target=80).

**Single organic acceptance criterion:** the first night with an L2 plug-in while battery SOC > `drain_target_soc` (80) during off-peak and Envoy-sighted, verify: (a) EVSE pauses and appears in `evse_dp_paused`; (b) reserve releases to max(inclement_floor, drain_target) and battery serves the house; (c) car charging resumes at drain-target-reached or by must-start-by 03:00 (INV-DP2 — car full by morning); (d) clean reversion to HOLD_ONLY. Shipwatch-able from `sensor.ura_energy_coordinator_ev_charging_plan` history + `evse_dp_paused` KV.

**Optional micro-hotfix (Tier 1):** the `reason: null` decision_log bug (§4.1) — worth fixing so the durable ledger, not just the 10-day recorder, carries decline reasons for the eventual first-transition forensics.

**Operator question to surface (config, not code):** is `drain_target_soc = 80` intentional? It makes transitions rare by design — DP only pays when the battery is still >80% at plug-in. If the intent was "drain the battery into the house down to a low floor before the car charges", the knob wants a much lower value (e.g. 20–30), which would have made several of these 21 nights transition candidates. Pure entity-knob turn, zero code.
