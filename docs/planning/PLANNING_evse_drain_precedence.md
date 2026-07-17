# PLANNING — EVSE Drain-Precedence (hold-then-eval)

**Version target:** TBD (post behavioral-write-verify)
**Tier:** **Tier 3 — operator pre-classified "super high risk"**
**Sequence position:** THIRD. Depends on completion of:
1. Enphase cloud-reliance cycle (stabilizes the SOC / battery-power / EVSE-charging telemetry the eval logic reads).
2. Behavioral write-verify cycle (guarantees that a reserve write intended by the transition heuristic actually landed on hardware; without it, the transition can silently no-op and leave the battery frozen while the strategy thinks it released).
Do NOT build until both ship + live-validate. This cycle's eval logic is only trustworthy on top of the freshness + write-confirmation contracts they establish.

**Status:** Design only. No code. This planning doc is a spec + probe order; build gated on operator go after probes report.

---

## Tier elevation rationale (Tier 3, not Tier 2-DB)

Per `CLAUDE.md` Tier 3 triggers — this cycle satisfies **all three**:
- **Threads a value through a shared primitive consumed by many emission sites** — the battery reserve floor. Multiple writers already exist: `BatteryStrategy._result`, inclement partial/full-hold, arbitrage attain floor (v5.5.3), `_apply_evse_battery_hold` (max()-only-raise contract). This cycle adds a *fourth* class of writer (hold→drain transition) that must interoperate with all of them without demoting a stronger floor. Bug Class #53 (computed-but-not-consumed) has struck this surface before (v5.5.3 D-HIGH-1, 7 unclamped emission sites).
- **Cost-AND-safety-impacting.** Wrong transition → car doesn't charge by morning (comfort/safety) OR battery drains at peak-adjacent hours (silent cost). Both failure modes are silent under current telemetry.
- **Precedence change on the cost-sensitive EV/battery seam with race history.** The v5.15.0 EV charge-start dead band (release-at-floor + sticky), the v4.7.28 off-peak ensure-on, the drain-pause resume gates (v4.7.6 D1), and force-charge precedence (A-H1) all live on this seam.

Operator directive: **4 framing-disjoint reviews (A local correctness / B integration + state-machine / C test-authority via real per-site mutation / D adversarial completeness diff-blind) + operator checkpoint BEFORE deploy, not just before build.** Reviewer D re-enumerates the entire reserve-writer surface, including pre-existing code.

---

## Falsifiable invariant (state up front — Reviewer D falsifies exactly this)

> **INV-DP1 (drain-precedence master):** At no reachable tick does the battery discharge more than `HOUSE_LOAD_TOLERANCE_KW` above measured house load while any EVSE is charging, **except** during a bounded post-transition window where the transition eval has explicitly paused all charging EVSEs AND released the reserve to the drain target AND stamped the transition decision to the ledger.
>
> **INV-DP2 (car-charge liveness):** A car that entered a `hold-then-eval` transition state ALWAYS reaches its must-start-by deadline in the CHARGING or DONE state — never HELD.
>
> **INV-DP3 (floor supremacy preserved):** The transition NEVER lowers a floor owned by a stronger protection: inclement partial/full-hold, blind-hold, arbitrage attain floor, force-charge, or any future strategy floor. Composition is `max()` on the way up, and the transition may only *substitute* the hold's contribution — not the strategy's floor.
>
> **INV-DP4 (blind-hold gate):** No transition eval fires while `is_blind_hold` is true. No fresh SOC → no eval → hold stands. Edge-triggered on blind-hold enter/exit.
>
> **INV-DP5 (single-writer stamp):** Every reserve write on the transitioned path stamps `_desired_stamped_at` fresh so the write-verify reversion sweep does not false-alarm `write_reverted`.

D's job: produce a concrete, legal-config reachable repro that breaks any of INV-DP1..5.

---

## Institutional context verified

### Code read end-to-end
- **`custom_components/universal_room_automation/domain_coordinators/energy_pool.py`** — `determine_battery_drain_actions` (Path A), v5.15.0 release-at-floor F + sticky release, v4.7.6 D1 resume gates, cooldowns, force-charge precedence A-H1.
- **`custom_components/universal_room_automation/domain_coordinators/energy.py`** — `_apply_evse_battery_hold` (energy.py:3007), `_is_any_evse_charging` (energy.py:2999), gate at energy.py:3376 in the main decision tick, the `max()`-only-raise contract (energy.py:3042-3049), INV-D2-LEDGER stamping (energy.py:3050-3069), the v5.17.1 D-HIGH-2 append-path clamp to `_last_reserve_level_desired` (energy.py:3086-3090), and the v5.17.3 D3 boot-HOLD-CURRENT fallback to `_last_reserve_level` (energy.py:3091-3099).
- **`energy_battery.py`** — `_result` reserve emit + desired stamping (~:3562-3564, :3834), interaction with the 2% deadband (why the v5.17.1 D-HIGH-2 append path existed).
- **v5.5.3 arbitrage-WAIT floor supremacy** — inclement floor threaded through arbitrage + attain paths (commit df57ab1e); the Reviewer D pattern that caught D-HIGH-1 (the 7th unclamped site).

### Prior planning + memory
- `docs/planning/PLANNING_v5.5.3_arbitrage_wait_reserve_floor.md` — Tier 3 template, invariant framing, Reviewer D pattern.
- `docs/planning/PLANNING_v5.15.0_ev_charge_start_deadband.md` — release-at-floor F, sticky, live-validated 2026-07-13.
- `docs/planning/PLANNING_v4.7.28_ev_offpeak_ensure_on.md` — off-peak re-enable of TOU-paused EVSE switch at 21:00.
- Memory `project_ev_drain_precedence_cycle.md` (operator ratification 2026-07-16 late) — the design v2 spec this doc formalizes.
- Memory `project_ev_charge_start_deadband.md` — v5.15.0 root cause (dead band read static reserve).
- Memory `project_ev_pause_post_peak_midpeak_decision.md` — durable EV principle: solar-first → never drain battery into car → off_peak grid cheapest.
- Memory `project_inclement_arbitrage_wait_floor_gap.md` — floor-supremacy pattern (resolved v5.5.3).
- `docs/QUALITY_CONTEXT.md` — Bug Class #48 (transient over-trust) informs the eval-latching design; Bug Class #53 (computed-but-not-consumed) is D's primary hunting frame.

### Design docs read
- `docs/Coordinator/energy.md` (battery + EVSE seams).
- `docs/Coordinator/energy_pool.md` (drain machinery, resume gates).

### Grep verifications for proposed additions
Every knob below is annotated REUSED (file:line) or NEW (why nothing equivalent).

---

## Numbers Get Knobs — placement ladder per operator rule (2026-07-16)

Every behavioral number gets a named knob with a rung + one-line why. `KILL:` documents kill-switch semantics.

| Knob | Rung | REUSED / NEW | Why this rung |
|---|---|---|---|
| `CONF_DP_ENABLE` (master switch) | Switch entity | NEW — no `_enabled` gate for drain-precedence exists | Live kill switch. Off → hold-only, today's behavior. `KILL: false disables all transition eval.` |
| `CONF_DP_EVAL_DELAY_MIN` (min minutes hold must be active before eval fires) | Number entity | NEW | Operator legitimately tunes by observation; 1-tick eval too jumpy (Bug Class #48). Default candidate 5-10 min pending probe. |
| `CONF_DP_MARGIN_MIN` (safety margin on drain_hours + charge_hours < night_hours) | Number entity | NEW | Operator observation-tunable ("more margin if car needs to be ready by 6am"). |
| `CONF_DP_MUST_START_BY` (latest allowable charge start, HH:MM) | Number entity (minutes-past-midnight) | NEW — v5.15.0 uses `arbitrage_charge_lead_time` (180 min); NOT reusable, semantic is "start no later than", not "start N min before deadline" | Live-tunable overnight policy. |
| `CONF_DP_HOUSE_LOAD_SOURCE` (live SPAN vs R1 base prediction vs blended) | Select entity | NEW | Sensitive to Enphase-cloud-reliance cycle outputs; select surface documented in options flow. |
| `CONF_DP_NEEDED_KWH_FALLBACK` (worst-case assumption when car SOC unknown) | Number entity | NEW | Live tunable; default = full battery capacity kWh minus 10% buffer, pending probe. |
| `DP_CAPACITY_KWH` (battery usable capacity) | Module constant `energy_const.py` | REUSED — verify existing capacity constant covers this; else NEW | Change requires review (physical property). |
| `DP_HOUSE_LOAD_TOLERANCE_KW` (INV-DP1 slack) | Module constant | NEW | Safety bound; change gates INV-DP1. Requires review. |
| `DP_TRANSITION_MAX_DURATION_H` (bound on the "bounded window" of INV-DP1) | Module constant | NEW | Safety bound; caps how long a transition can hold the paused-EVSE + released-reserve state before falling back to hold. |

Kill-switch semantics documented on `CONF_DP_ENABLE` (master off = today's Path B unconditional).

---

## Measure Before You Build — MANDATORY B0 probes (operator rule 2026-07-13)

Cycle value depends on empirical properties of already-recorded data. **Build gated on probe outputs.** All probes are one-shot, read-only, run via `ssh ha "python3 -" < script.py` against the recorder DB. Output goes into an audit doc (`docs/planning/AUDIT_evse_drain_precedence.md`) as the acceptance fixture.

### Probe P1 — Boundary-time SOC distribution
**Question:** How often would the transition heuristic even be triggered (SOC high enough at plug-in that drain-then-charge fits before morning)?
**Read:** `sensor.envoy_*_battery` state history at every EVSE `charging` edge (plug-in) for last 90 days.
**Output:** Histogram of SOC at plug-in; count how many nights had `SOC > 40` at plug-in.
**Gate:** If <10% of plug-ins had `SOC > 40`, the marginal benefit collapses → recommend park the cycle (Marginal-Benefit Decomposition rule).

### Probe P2 — Overnight house-load distribution
**Question:** What's the realistic `house_load_kw` prior for the drain_hours estimator?
**Read:** SPAN whole-house consumption for 21:00–06:00 windows, last 90 days, keyed by season.
**Output:** Per-season p50/p90 overnight load, hourly shape (does load slump after 01:00?).
**Gate:** Sizes `CONF_DP_HOUSE_LOAD_SOURCE` default + `CONF_DP_MARGIN_MIN` default. If shape is bimodal (guests vs empty), the estimator needs a state input.

### Probe P3 — Car charge session sizes
**Question:** What's the `needed_kwh` prior when car SOC is unknown?
**Read:** EVSE session `energy_kwh` history per charge session, last 90 days, both cars separately.
**Output:** p50/p90/p99 kWh per session per car.
**Gate:** Sets `CONF_DP_NEEDED_KWH_FALLBACK` default. If p99 ≈ full battery, worst-case assumption is the only safe default; if p50 << full, allow a shorter default with clear operator override.

### Probe P4 — Historical "would-transition" replay
**Question:** On last 90 nights, how many would the eval have transitioned vs held? Of transitioned nights, would the car have finished charging by must-start-by?
**Read:** SOC + EVSE-charging + SPAN-load history over 21:00–06:00 windows.
**Output:** Counterfactual replay table: night, decision (hold/transition), predicted finish time, actual charge kWh delivered.
**Gate:** If replay shows >5% of transition decisions would have missed must-start-by under the default margin, the margin default MUST be raised before ship (or the must-start-by guard's fallback path MUST be proven).

**No build begins until P1-P4 complete and audit doc reviewed by operator.**

---

## Interaction matrix (this seam's hazard surface — Reviewer B + D coverage map)

Each row = an interaction. Reviewer B verifies runtime composition; Reviewer D falsifies.

| Interaction | Hazard | Required behavior |
|---|---|---|
| Transition vs **force-charge override** (A-H1 in `energy_pool.py`) | Transition pauses EVSE while force-charge trying to run | Force-charge wins unconditionally; transition eval MUST check force-charge state and yield. |
| Transition vs **TOU pause** (v4.7.28 off-peak ensure-on) | ensure-on re-enables switch at 21:00; transition wants EVSE paused | Transition-owned pause is a *distinct* state from TOU-owned pause; ensure-on must not un-pause a transition-paused EVSE. Reuse the `_paused_by_us` provenance flag (backlog-audit #9 memo flagged this as SHARED with EVSE TOU control — verify + separate). |
| Transition vs **grid-import cap** | Draining battery + house load may still hit import cap during transition | Transition eval reads current import + projected drain load; if exceeding cap, hold stands. |
| Transition vs **blind-hold supremacy (INV-DP4)** | Transition eval fires with a stale SOC read | Hard gate: `if is_blind_hold: return` at the top of the eval. Edge-triggered on blind-hold exit — allow one eval on the first fresh SOC tick post-blind. |
| Transition vs **inclement floors** (v5.5.0/v5.5.3) | Inclement floor > drain target; releasing reserve to drain target would demote the floor | `max(inclement_floor, drain_target)` — transition releases to `max()`, never below inclement. If inclement floor >= SOC, transition is a no-op → hold stands. |
| Transition vs **arbitrage attain floor** (v5.5.3) | Attain floor is a stronger protection during charge-to-target | Same `max()` composition. Reviewer D re-enumerates every reserve-writer to confirm no site emits a raw drain-target without composing. |
| Transition vs **reversion sweep** (behavioral write-verify cycle) | Fresh reserve write on transition must be recognized by the sweep | Every transition-owned reserve write stamps `_desired_stamped_at` fresh (INV-DP5). Reviewer C exercises this by mutating the stamp site. |
| Transition vs **multi-EVSE** (one car transitions, second plugs in mid-drain) | Second plug-in triggers hold reader; state machine confused | Design decision: second plug-in during transition = **transition stays** (both cars will be released at floor). Reviewer B verifies with a real 2-EVSE trace fixture. |
| Transition vs **`_evse_hold_soc` capture** (energy.py:3379) | Hold releases `_evse_hold_soc = None` when transition pauses EVSEs (no charging → hold false) | Transition must persist its own SOC/decision separately from `_evse_hold_soc`; DO NOT rely on the hold's captured SOC after transition. |
| Transition vs **restart mid-window** | HA restarts at 02:00 with transition active, EVSE paused, reserve released | Persist transition state to KV (mirror `_save_evse_state` pattern used by v5.17.1 B-MED-1 eager-persist). On restart, if transition-active flag + still within must-start-by, restore paused state. If past must-start-by, force-start car (INV-DP2). |

---

## Deliverables

### D1 — Transition state machine (design + KV persistence)

A per-decision-tick state machine tracked on `EnergyCoordinator`:
- `HOLD_ONLY` (default, master switch off or eval says no)
- `HOLD_PRE_EVAL` (hold active, waiting `CONF_DP_EVAL_DELAY_MIN`)
- `EVAL_TRANSITION` (one-shot eval fires)
- `TRANSITIONED` (EVSE(s) paused, reserve released to `max(inclement_floor, drain_target)`, ledger stamped)
- `MUST_START_FORCED` (must-start-by reached; EVSE released regardless of drain progress)

**REUSED:** `_evse_battery_hold_active` flag (energy.py:3376+); extend NOT replace.
**NEW:** `_dp_state`, `_dp_transitioned_at`, `_dp_must_start_by_dt`, `_dp_last_eval_at`, `_dp_persist_key` in KV.

**Acceptance:**
- **Verify:** state transitions logged at INFO on every edge.
- **Sensor:** `sensor.ura_energy_drain_precedence_state` reports current state + `transitioned_at` attr + `must_start_by` attr.
- **Test:** unit tests drive the state machine through every legal transition + every illegal transition (rejected).
- **Live:** on next evening plug-in with SOC>40, state moves `HOLD_PRE_EVAL → EVAL_TRANSITION → TRANSITIONED` within `CONF_DP_EVAL_DELAY_MIN` + 1 tick.

### D2 — Transition heuristic + eval (`_evaluate_dp_transition`)

Pure function operating on a `TransitionInputs` dataclass:
```
drain_hours = (soc - drain_target) * capacity_kwh / house_load_kw
charge_hours = needed_kwh / charger_rate_kw
fits = (drain_hours + charge_hours + margin_h) <= night_hours_remaining
```
Returns `TransitionDecision(transition: bool, reason: str, computed_finish_dt: dt)`.

**Acceptance:**
- **Verify:** decision + inputs logged at INFO on every eval (INV-DP5-observability).
- **Sensor:** `sensor.ura_energy_drain_precedence_last_eval` shows inputs (SOC, house_load_kw, needed_kwh, drain_hours, charge_hours, margin_h, fits) as attrs.
- **Test:** parameterized fixture from P1/P2/P3 probe output; every historical night in the fixture yields a documented expected decision. This is the acceptance fixture Marginal-Benefit rule requires.
- **Live:** at least one transition + one hold decision observed in 14 days; both match the audit-doc counterfactual replay.

### D3 — Transition execution (pause + reserve release, ledger stamp)

Applies `TransitionDecision.transition == True`:
1. Pause all charging EVSEs via existing pause primitive (REUSE `energy_pool` drain-pause path — do NOT create parallel writer). Provenance flag `_paused_by_dp` (distinct from `_paused_by_us` — see backlog-audit #9).
2. Emit reserve action at `max(inclement_floor, drain_target)`; compose via `max()` with any existing reserve action, matching the `_apply_evse_battery_hold` contract (energy.py:3042).
3. Stamp `_desired_stamped_at` + `_last_reserve_level` (INV-DP5).
4. KV persist transition state (mirror v5.17.1 B-MED-1 pattern, energy.py:3389+).

**Acceptance:**
- **Verify:** reserve write observed on hardware within one write-verify sweep of the transition edge.
- **Sensor:** ledger attrs on the reserve sensor show `desired = max(inclement, drain_target)`.
- **Test:** Reviewer-C-style real per-site mutation: neuter each of the 4 sub-steps (pause, reserve-write, stamp, KV-persist); a specific test MUST fail for each.
- **Live:** after transition, `sensor.envoy_*_battery` shows monotonic decrease toward drain target; import ~ 0 while transitioned.

### D4 — Reversion + must-start-by guard

- On EVSE completion (SOC reached) OR must-start-by deadline reached OR blind-hold enter → exit `TRANSITIONED` state cleanly. If must-start-by: release EVSE regardless.
- REUSE v5.15.0 release-at-floor F + sticky machinery for the normal case.

**Acceptance:**
- **Verify:** every transitioned night ends in CHARGING or DONE by must-start-by (INV-DP2).
- **Sensor:** `sensor.ura_energy_drain_precedence_state` returns to `HOLD_ONLY` post-completion.
- **Test:** simulate must-start-by fire during EVAL_TRANSITION, TRANSITIONED, mid-drain.
- **Live:** operator observes car charged by morning on every transitioned night for 14 days.

### D5 — Observability + operator surfaces

- `sensor.ura_energy_drain_precedence_state` — state + rich attrs (last decision, inputs, transitioned_at, must_start_by).
- `sensor.ura_energy_drain_precedence_last_eval` — pure eval inputs+outputs.
- `switch.ura_dp_enable` — master kill switch (persists via existing Switch-persistence machinery).
- Number entities per Knobs table above.
- Rung attrs on knobs (per v5.17.x rung-attrs pattern).

**Acceptance:**
- **Live:** all sensors + switches survive restart with restored state.

---

## Open judgment calls (operator input required before build)

1. **`needed_kwh` source of truth.** Options: (a) worst-case fallback constant; (b) per-EVSE historical p90 from P3; (c) R1 estimator's EV term (if it exposes a per-session projection). Probe P3 informs, operator decides.
2. **`house_load_kw` source.** Live SPAN vs R1 base prediction vs blended `max(live_span, r1_base)`. Live SPAN is fresh but noisy at plug-in edge; R1 is smoothed but may lag. Probe P2 informs; operator picks default for `CONF_DP_HOUSE_LOAD_SOURCE`.
3. **`must_start_by` default.** Reasonable default = 04:00. Operator confirms. Interacts with `arbitrage_charge_lead_time` (180 min today).
4. **Multi-EVSE second-plug-in policy.** Design assumes "transition stays, both released at floor." Alternative: "revert to hold on second plug-in." Operator picks; Reviewer D probes both.
5. **Blind-hold-exit re-eval.** Do we allow one eval immediately on blind-hold exit, or wait a full `CONF_DP_EVAL_DELAY_MIN`? INV-DP4 permits either; operator preference.

---

## Review protocol (Tier 3 — 4 framing-disjoint reviews)

**Pre-review:** `git tag pre-review-v<version>` per CLAUDE.md.

- **Review A — local correctness.** Per-site arithmetic on drain_hours/charge_hours, clamp composition (`max()` chain), datetime math on must-start-by (Bug Class #11 UTC-vs-local; #21 naive/aware).
- **Review B — integration + state-machine.** Every row of the interaction matrix; restart behavior; ensure-on interplay; second-EVSE plug-in mid-transition; the reversion sweep; force-charge yield; TOU boundary tick v5.17.3.
- **Review C — test authority via REAL per-site source mutation.** Reviewer edits production source to neuter ONE load-bearing site at a time (pause, reserve-write, stamp, KV-persist, blind-hold gate, must-start-by fire), runs suite, confirms a SPECIFIC test fails, restores. Global monkeypatch of the reserve writer is NOT sufficient.
- **Review D — adversarial completeness / diff-blind.** Sole job: falsify INV-DP1..5 with a legal-config reachable repro. Re-enumerates the ENTIRE reserve-writer surface (`_apply_evse_battery_hold`, `BatteryStrategy._result`, inclement partial/full-hold, arbitrage attain floor, force-charge, this cycle's D3) — including pre-existing sites (v5.5.3 D-HIGH-1 pattern). Falsifiable-invariant repro required per finding.

**Orchestrator independent verification before ship — MANDATORY.** Re-grep every reserve-writer emission site; re-run one source mutation on the load-bearing D3 write; confirm a specific test fails.

**Operator checkpoint BEFORE deploy** (not just before build). Surface: final review outcome + invariant proof + P4 counterfactual replay comparison to the first N live nights (once shipped, before closing cycle).

---

## Plan Completion Tracking

At close of cycle, explicitly document:
- Which knobs shipped vs deferred.
- P1-P4 probe outputs preserved in audit doc.
- Any Reviewer D findings deferred (with rationale) tracked in QUALITY_CONTEXT.md or backlog memory.
- Post-restart Live Validation table written back into `README_v<version>.md` per operator rule 2026-06-05.

## OPERATOR RATIFICATION — 5 judgment calls (2026-07-17 ~01:20)

1. **needed_kwh = per-EVSE session-history p90 + worst-case fallback**, with
   operator refinement: only sessions terminated BY THE CAR (charge-complete)
   are uncensored full-charge observations; sessions ended by URA's switch-off
   are censored and must be excluded (or treated as lower bounds) when
   deriving p90. P3 probe must classify session-end cause (car-stop vs
   switch-stop) from recorder data.
2. **house_load = max(live SPAN, R1 base prediction)** — conservative blend.
3. **must_start_by default = 03:00** (operator: L1 chargers are slow; more
   conservative than the 04:00 candidate). Rung-1 reviewed constant.
4. **Second plug-in during active transition: transition stays (one state
   machine)** — with operator's hardware clarification: L2 Emporia EVSEs
   auto-activate on plug detection; L1 is a dumb 120V plug behind a wall
   smart-switch — when paused (switch off at wall) there IS no plug-event
   detection. A manual wall-switch press is an operator override → existing
   manual-override/cooldown machinery handles it; no new state.
5. **Blind-exit re-eval = immediate one-shot** on first sighted tick (eval is
   read-only decision math; actuation still routes through guarded paths).
