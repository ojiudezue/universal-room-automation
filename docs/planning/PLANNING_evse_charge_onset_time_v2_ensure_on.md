# PLANNING — EVSE/L1 charge-onset time (v2 — at the off-peak ensure-on, the real actuation site)

Card: **EVSE-CHARGE-ONSET-TIME-1**
Status: PLAN (v2, correct-site rebuild). Supersedes `PLANNING_evse_charge_onset_time.md` (wrong site — gated the `_paused_by_battery_drain` release instead of the ensure-on; built, reviewed, then **backed out and deleted**; develop code verified byte-identical to origin).
Recommended tier: **Tier 2-DB** (3 framing-disjoint reviews) + plan-review before build.

## 0. Why v2 exists (the correcting insight)

There are **three distinct charger mechanisms**; v1 gated the wrong one:
- `_paused_by_dp` — **DP drain-precedence** (the arbitration layer; `_apply_dp_*` releases). Untouched.
- `_paused_by_battery_drain` — the **older battery-drain pause** (`determine_battery_drain_actions`). ← v1 gated this (WRONG). Untouched in v2.
- **the off-peak proactive ensure-on** in `determine_actions` — the **single actuation site** that turns a charger back ON once it's off-peak, *after* DP releases (`_paused_by_dp` clears) or a drain-pause clears (via `_stronger_peer_holds`). ← **v2 gates here.**

"Don't start charging until the onset time" is a property of **when the charger is first turned ON in the off-peak window** — which is exactly the ensure-on. v1's site only fired on a battery-drain-pause *release*, so a charger that was never drain-paused got turned on by the ensure-on at off-peak start regardless of onset. (Historical note: v1's own lineage shows Rev 1/2 *were* at the ensure-on and were wrongly abandoned as "too much surface." v2 returns there but **minimally** — a defer-the-start check, not an AND-gate over the branch.)

## 1. Institutional context verified

**Sites (read end-to-end during scoping):**
- **EVSE ensure-on:** `EVChargerController.determine_actions` off_peak branch, the "2c" ensure-on at `energy_pool.py:~1247` — `if not state["is_on"]: actions.append(turn_on); self._proactive_offpeak_holds.add(evse_id)`. Guarded above by `if self._stronger_peer_holds(evse_id) or evse_id in self._paused_by_dp: continue` (`~:1189`), the `grid_charge_on` breaker-safety cede (`~:1211`), and `force_charge_active` (`~:1238`).
- **Plug ensure-on:** `SmartPlugController.determine_actions` off_peak branch, ensure-on at `energy_pool.py:3120` — same shape, guarded by the `_paused_by_battery_drain / _paused_by_fill_priority / _paused_by_load_shed` carry-over check (`:3021`), `grid_charge_on` (`:3040`), `force_charge_active` (`:3053`).
- **Excess-solar path is separate** (`_paused_by_fill_priority` / SolarFollowController) — NOT the off-peak grid ensure-on, so gating the ensure-on leaves solar charging untouched. (Reviewer C confirmed the gate would have exactly the intended call sites.)

**REUSED (salvaged from the deleted branch — logic was sound, only its call site was wrong; saved at `scratchpad/salvage_evaluate_onset_gate.py`):**
- `_evaluate_onset_gate(now, enabled, onset_str, max_hold_h, must_start_by_min) -> (onset_permits, must_start_by_reached)` — bounded-window overnight-only + must-start-by backstop + enable + seconds-tolerant parse + fail-OPEN on now=None. **Reused verbatim**; only the *caller* moves to the ensure-on.
- `_parse_hhmm` (seconds-tolerant), `ONSET_MAX_HOLD_H = 8.0` module const, `next_occurrence_of_hhmm` (extract into `energy_drain_precedence.py`), the D-LOW-1 `ms_ref = max(now - max_hold_h, onset_instant - max_hold_h)` clamp.
- Enable toggle: `CONF_ENERGY_EVSE_CHARGE_ONSET_ENABLED` (config-flow bool, default True) + `switch.ura_ev_charge_onset_enabled` (bespoke subclass routing through `set_ev_charge_onset_enabled` — the B-CRIT-A fix) + `set_ev_charge_onset_enabled`/`set_ev_charge_onset_time` coord fan-out to BOTH controllers + `_EC_SETTER_DISPATCH` + `OPTIONS_RELOAD_SUPPRESS_KEYS` (the B-CRIT-2 fix) + `time.ura_ev_charge_onset_time` on the CM-forwarded `INTEGRATION_PLATFORMS` (the B-CRIT-1 fix).
- Reused knob: `CONF_DP_MUST_START_BY_MIN_PAST_MIDNIGHT` (=180=03:00) for the must-start-by escape.

**NEW (only what the site change requires):**
- `_onset_deferred: set[str]` per controller — observability of which chargers are currently onset-held (RAM only; not persisted — a held charger re-derives its state next tick from the gate). Justification: the v1 gate-open sensor read a release-branch; the ensure-on site needs its own deferred set.

**Prior art consulted:** `AUDIT_dp_live_behavior.md` (charger inventory: 2 L2 EVSEs garage_a/b + 1 L1 charger on 2 Moes smart-plug sockets, plug tier); the deleted-branch review records (3 Tier-2-DB rounds + 2 re-review rounds — all findings folded into the salvage list above); the superseded v1 plan (lineage).

## 2. Falsifiable invariant

**INV-ONSET (single property the cycle must guarantee):** When the enable toggle is ON and `now` is inside the onset hold window (`0 < onset_instant - now <= ONSET_MAX_HOLD_H`) and must-start-by is not reached, the off-peak proactive ensure-on issues **no** `switch.turn_on` for an OFF charger, at BOTH the EVSE and plug tiers. **Falsified by:** any reachable off_peak tick where an OFF, otherwise-eligible charger receives `switch.turn_on` while inside the hold window with the toggle ON and must-start-by unreached.

Corollary invariants (each independently falsifiable):
- **INV-NO-INTERRUPT:** onset NEVER issues `switch.turn_off`. It only withholds a turn-on for an already-OFF charger; a running charge (`is_on`) is never affected. Falsified by any onset-path `turn_off`.
- **INV-ESCAPE:** must-start-by (03:00, reused knob) forces the ensure-on even inside the hold window. Falsified by an OFF charger still withheld once `now >= must_start_instant`.
- **INV-BASELINE:** enable=OFF (or blank/malformed onset, or now=None) → the ensure-on is byte-identical to develop. Falsified by any behavioral diff on the disabled path.
- **INV-UNTOUCHED:** DP (`_apply_dp_*`, `_paused_by_dp`), the battery-drain pause (`determine_battery_drain_actions`), and excess-solar (`determine_excess_solar_actions` / fill-priority) are byte-identical to develop. Falsified by any diff outside `determine_actions` (both tiers) + the additive wiring.

## 3. Deliverables

### D1 — the onset gate at the ensure-on (both tiers)
At the EVSE "2c" ensure-on (`~:1247`) and the plug ensure-on (`:3120`), wrap ONLY the OFF-charger turn-on:
```python
if not state["is_on"]:
    onset_permits, must_start_by_reached = _evaluate_onset_gate(
        now_local, self._ev_charge_onset_enabled, self._ev_charge_onset_time,
        ONSET_MAX_HOLD_H, must_start_by_min,
    )
    if not (onset_permits or must_start_by_reached):
        # ONSET HOLD — defer the off-peak START until the window opens.
        # Never turn_off (INV-NO-INTERRUPT); drop TOU/proactive bookkeeping
        # so a stale hold can't survive; record the deferred state.
        self._paused_by_us.discard(evse_id)
        self._proactive_offpeak_holds.discard(evse_id)
        self._onset_deferred.add(evse_id)
        continue
    self._onset_deferred.discard(evse_id)
    actions.append({"service": "switch.turn_on", "target": switch_entity, "data": {}})
    self._proactive_offpeak_holds.add(evse_id)
# (already-on chargers fall through untouched — onset never interrupts)
```
Thread `now_local` and `must_start_by_min` into `determine_actions` (both tiers) from the coord tick (mirror how the coord already passes `now`/`dp_must_start_by_min` elsewhere). `enabled`/`onset_time` are already controller instance state via the fan-out setters.

### D2 — enable toggle + time entity + wiring (all salvaged, all with the fixes)
Reinstate the salvaged enable/time surface **with the review fixes already applied**: bespoke enable switch routing through the setter; both CONF keys in `_EC_SETTER_DISPATCH` AND `OPTIONS_RELOAD_SUPPRESS_KEYS`; `Platform.TIME` on `INTEGRATION_PLATFORMS`; entities re-read `entry.options` on `SIGNAL_ENERGY_ENTITIES_UPDATE`; seconds-tolerant parser; D-LOW-1 clamp; D-LOW-3 coord getter reads its own field.

### D3 — observability
`binary_sensor.ura_ev_charge_onset_active` (any charger in `_onset_deferred`), attrs: which entity_ids are held, onset time, enabled, next onset instant. (Drop the v1 L1-over-hold sensor — the bounded window caps the hold; the deferred set is the signal.)

### D4 — knobs (Numbers-Get-Knobs)
- `ONSET_MAX_HOLD_H = 8.0` — module const (rung-1 safety bound; kill via a huge value).
- `CONF_ENERGY_EVSE_CHARGE_ONSET_TIME` — config-flow TimeSelector + `time` entity (default "01:00").
- `CONF_ENERGY_EVSE_CHARGE_ONSET_ENABLED` — config-flow bool + switch entity (default True). **The kill switch: OFF ⇒ INV-BASELINE.**
- Reused `CONF_DP_MUST_START_BY_MIN_PAST_MIDNIGHT` (03:00) — the must-start escape.

## 4. Acceptance criteria — DISCRIMINATING

- **INV-ONSET:** at both tiers, off_peak tick, charger OFF, enabled, onset "01:00", now 22:00 (delta 3h ≤ 8h), must-start unreached → **no turn_on** emitted, entity in `_onset_deferred`. Under the plausible-failure (gate absent), the SAME tick emits `switch.turn_on` — the two outcomes differ in the action list, so the test discriminates.
- **INV-ONSET boundary:** now 01:00 exactly → next instant is +24h → not in window → **turn_on emitted** (releases at the boundary). now 10:00 (delta 15h > 8h, daytime) → **turn_on emitted** (overnight-only; daytime charges normally).
- **INV-NO-INTERRUPT:** charger already `is_on` inside the hold window → **no turn_off** emitted (assert the action list contains no turn_off for that entity).
- **INV-ESCAPE:** onset "05:00", must-start 03:00, now 04:00, charger OFF → `must_start_by_reached=True` → **turn_on emitted**. Mutation: drop the `or must_start_by_reached` → the test goes RED.
- **INV-BASELINE:** enabled=False → the `determine_actions` action list is byte-identical to develop for a representative off_peak fixture (charger OFF → turn_on emitted, no deferral). Mutation: force enabled=True in `_evaluate_onset_gate` → a disabled-baseline test goes RED.
- **INV-UNTOUCHED:** `git diff develop` shows changes ONLY in `determine_actions` (both tiers) + additive helper/const/switch/time/sensor/config wiring; `determine_battery_drain_actions`, `_apply_dp_*`, `determine_excess_solar_actions` are byte-identical.
- **Wire-in anchors (mandatory, neuter→RED, orchestrator re-verified):** each of — enable switch → coord setter → both controllers; `set_ev_charge_onset_time` → both controllers; `now_local` + `must_start_by_min` threaded into both `determine_actions`; each D1 gate disjunct — has a behavioral test that goes RED when its exact site is neutered. Source-grep / `inspect.signature` / direct-controller-call tests are NOT acceptable (the v1 failure mode).
- **Live:** post-restart, on an off_peak evening before 01:00 with `switch.ura_ev_charge_onset_enabled` ON, the garage EVSEs + the Moes L1 sockets stay OFF (in `_onset_deferred`), then turn ON at 01:00; flipping the switch OFF starts them immediately.

## 5. Non-goals (explicit)
- **No change to DP, the battery-drain pause, or excess-solar.** Onset only withholds the off-peak ensure-on start.
- **Never turn a charger OFF** for onset (no mid-charge interruption).
- **No plug-tier DP participation** (the separate phase-4 parity cycle).
- **No anchor/session persistence** (v1's removed machinery — the window is computed from `now`).

## 6. Tier / review
Tier 2-DB. **Plan-review before build** (one adversarial pass: re-enumerate every off_peak turn_on site independently — is the ensure-on truly the only start path that needs gating? verify the salvaged helper's math; confirm the non-goal diffs). Then build → 3 framing-disjoint reviews (A local-correctness + boolean/helper math; B wiring/lifecycle/CRIT-fix carry-over from salvage; C test-authority via per-site neuter + adversarial completeness on INV-ONSET across ALL off_peak turn_on paths). Orchestrator independent mutation-verify before ship. Operator checkpoint before deploy (behavioral default 01:00; ships enable ON or OFF per operator).
