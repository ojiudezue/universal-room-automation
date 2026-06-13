# PLANNING — Arbitrage Solar-Attainability Gate + 3-Rung Least-Cost Intervention Ladder

**Status:** Planning only — no build, no deploy. Filename carries no version (assigned at deploy time).
**Authoring date:** 2026-06-13 (revised same day to restore the operator's middle rung)
**Branch:** `develop` (v5.3.8 just shipped — attain machinery LIVE).
**Tier classification — operator-elevated Tier 2-DB.** This cycle changes battery/cost
strategy (a new gate predicate on the arbitrage path) AND edits a shared primitive (the
EVSE arbitrage-pause owner) consumed by both the existing arbitrage branch and the
proposed redirect rung. Textbook regression-prone per the standing policy (CLAUDE.md,
2026-06-08): battery ↔ grid ↔ cost ↔ EV ripple plus a documented breaker-safety
invariant. **3 framing-disjoint reviews + live validation + README write-back.**

**Proposed framings (disjoint by construction):**

- **A — Gate/projection correctness + no-flap.** TWO-PASS solar-attainability projection
  on the arbitrage `_gate_is_open` path: pass 1 (rung-0) with CURRENT loads, pass 2
  (rung-1) with EV load subtracted. Math, sign conventions, sliced-Solcast reuse from
  v5.3.8, latch/hysteresis on BOTH the rung-0 gate boundary AND the rung-0↔rung-1
  boundary so neither bangs around target. Interaction with existing `_gate_is_open`
  (must not silently widen on poor/very_poor days). EV-load-estimate correctness:
  sourced from the existing per-EVSE `power` read; no-solar-surplus short-circuit
  (rung-1 only meaningful when there IS solar to redirect). Cold-boot defer (same shape
  as v5.3.8 attain cold-boot). Day-class flap (good ↔ poor via d2_class) must not chain
  into rapid gate open/close churn.
- **B — EV pause-ownership precedence + breaker-safety invariant + resume races +
  redirect/breaker label correctness.** The cycle introduces a *distinction* between two
  pause reasons on the SAME set (`_paused_by_arbitrage`): rung-1 REDIRECT
  (solar-redirect, no grid charge, fast resume keyed on rung-0 projection recovery) vs
  rung-2 BREAKER (grid charging commanded, breaker-mandatory, sticky resume keyed on
  phase exit from CHARGE). This reviewer owns: (1) the breaker-safety invariant —
  whenever `charge_from_grid` is COMMANDED (rung-2 reached), EVs MUST be in the set
  with label `breaker`; redirect is structurally unreachable on a tick that commands
  grid charge; (2) resume semantics keyed on the CURRENT label each tick — rung-1 EVs
  auto-resume the moment the rung-0 projection recovers (gate flips closed), rung-2
  EVs only resume on phase exit from CHARGE; (3) mid-CHARGE label flips
  (redirect→breaker if solar collapses and we escalate to grid; breaker→redirect is
  DISALLOWED on a tick where grid charge is still commanded); (4) precedence with
  sibling pause owners (`_paused_by_us` TOU, `_paused_by_battery_drain`,
  `_paused_by_fill_priority`, `_paused_by_grid_cap`) — no 4th colliding owner; the
  v4.7.28 off_peak ensure-on carry-over-guard block (`energy_pool.py:518-526`) MUST
  continue to see `_paused_by_arbitrage` membership and skip ensure-on regardless of
  rung label.
- **C — Savings/economics + test authority.** Quantify on the incident shape (excellent
  solar, d2=poor): rung-0 saves a full chunk's grid cost; rung-1 saves a full chunk's
  grid cost AND keeps the EVs charging from redirected solar; rung-2 falls back to
  status-quo cost. What does rung-1 COST if the projection is wrong and we suppress EVs
  unnecessarily on a marginal day (the answer: EVs are paused but solar still flows to
  battery; if rung-0 recovers next tick, EVs resume — bounded by the tick cadence).
  Behavioral test fixtures drive the real arbitrage path on `BatteryStrategy.determine_mode`
  with real `energy_const.py` rates; no hand-mutated `_paused_by_arbitrage`, no
  hand-mutated `_arbitrage_pause_reason`, no hand-mutated `_attain_state`. Mutation
  authority: inverting the rung-0 predicate, the rung-1 re-projection (EV-load
  subtraction), the rung-1/rung-2 label assignment, the no-solar short-circuit, or the
  rung-1 resume keying each breaks ≥1 test.

---

## Institutional context verified

Per CLAUDE.md, this section is the proof-of-work that the planner consulted prior art
before scoping. Reviewers verify during review pass.

### Greps run + reads — REUSED vs NEW

| Proposed surface | Verdict | Evidence |
|---|---|---|
| Rung-0 solar-attainability predicate on `_gate_is_open` (CURRENT loads) | **NEW behavior, REUSED scaffolding.** Reuses the v5.3.8 projection — `_expected_solar_surplus_pct` (`energy_battery.py:1033-1102`) plus the K-tick observed-net-rate window (`_attain_soc_history`, `:209-216`, sampled by `_record_attain_sample` at `:959`) and `_should_attain_peak_buffer` projection shape (`:1258-1338`). The arbitrage gate currently opens on `target_day_class in (poor, very_poor)` OR d2 same in multi-day-horizon (`energy_battery.py:732-748`). NEW: a "rung-0 attainability override" that *suppresses* arbitrage CHARGE when today's projected SOC at boundary already meets `peak_buffer_target` from solar + observed rate alone (current loads). The override is a *narrowing* of `_gate_is_open` — keeps existing structure intact. | `_gate_is_open` at `:732-748` opens on multi-day-horizon `d2_class=poor` while today=excellent — the incident's literal hole. v5.3.8 attain projection at `:1033-1102` is the byte-identical math we need; the only new line is the call-site (suppression at `_gate_is_open` true-path). |
| Rung-1 re-projection with EV load REMOVED | **NEW logic, REUSED inputs.** Re-runs the v5.3.8 projection with the observed K-tick net rate ADJUSTED for "EVs paused". EV load is estimated by summing the existing per-EVSE `power` field returned from `EVChargerController._get_evse_state` (`energy_pool.py:308-314`) over all EVSEs currently `charging=True`. That sum (in watts) is converted to a %/h SOC delta via the same battery-capacity constant the attain machinery uses (`energy_const.py BATTERY_USABLE_KWH`, the divisor inside `_expected_solar_surplus_pct`). Adjusted rate = `observed_net_rate + (ev_load_w / 1000) / BATTERY_USABLE_KWH * 100`. If `ev_load_w == 0`, rung-1 collapses to rung-0 and is skipped. If `_expected_solar_surplus_pct(now) < SOLAR_NEGLIGIBLE_PCT_PER_H` (proxy for "no solar to redirect — night/dark"), rung-1 is skipped — pausing EVs frees nothing, go straight to rung-2. | Per-EVSE power read at `energy_pool.py:308-314` ALREADY normalized to watts (Bug Class #30 fix, `:286-288`). Already None-safe via `EVSE_ESTIMATED_POWER_W` fallback (`:303`). Solar-surplus pct is the v5.3.8 sliced-daylight estimator; reusing it for the "is there ANY solar to redirect" guard is byte-identical. No new physics, no new constants beyond the negligible-solar threshold. |
| Rung-2 grid charge commanding | **UNCHANGED.** Existing arbitrage CHARGE phase fires when `_gate_is_open` returns True. This cycle does not modify the rung-2 code path; it only narrows what reaches it (rungs 0 and 1 short-circuit first). | `_get_arbitrage_phase` at `:750-858` unchanged. |
| `_arbitrage_pause_reason` rung label dict | **NEW reason discriminator, REUSED set.** Add a parallel dict `_arbitrage_pause_reason: dict[str, str]` keyed by `evse_id` (values: `"redirect"` / `"breaker"`) that travels alongside `_paused_by_arbitrage` (`energy_pool.py:205`). Set membership remains the single source of truth for "is this EVSE paused by URA for arbitrage"; the reason map is *resume-policy metadata*. No 4th pause-owner set is created (operator constraint + load-shedding-cycle #15 collision class cross-ref). | The existing pattern of mirroring a set with side-data is already in use for dispatch tracking (`_release_pause_dispatch_owner` at `:360+`). Reusing the existing set means the v4.7.28 ensure-on carry-over-guard block (`energy_pool.py:518-526`) automatically sees both rung labels — neither rung permits an off_peak ensure-on. |
| Rung-1 resume policy (key on current label each tick) | **NEW policy, REUSED machinery.** The `False`-branch resume path (`energy_pool.py:1242-1273`) is invoked each tick. The cycle adds: per-tick, BEFORE the existing TOU/sibling-owner gates, check the rung label. Rung-1 EVs are resumed when `_gate_is_open` returns False (rung-0 projection now passes — gate naturally closes, this branch fires for them). Rung-2 EVs are resumed only on phase exit from CHARGE (same as today). The resume code path is THE SAME — only entry timing differs. The cycle relies on labels being recomputed each pause tick (the rung-decision lives at the top of the `True`-branch). | `:1249-1273` already enforces TOU + sibling-owner precedence on resume. We do NOT add a new resume code path; the natural gate-closes-when-rung-0-passes flow drives rung-1 resume automatically. Verification target for reviewer B: confirm the False-branch is invoked on every tick where `arbitrage_charging=False`, not just on the transition tick. |
| New `CONF_*` / sensor / entity / signal | **NONE.** Surfaces via existing `arbitrage_phase`, `reason` string, and the existing `paused_by_arbitrage` attribute on the EV diagnostic sensor (`energy_pool.py:1354`). Reason labels exposed as `paused_by_arbitrage_reasons` (NEW attribute on existing sensor — observability only, no new entity). Parsimonious-config rule (`feedback_parsimonious_room_config.md`) honored. **Operator ruling: no new `ARBITRAGE_BREAKER_RISK_KW` kW threshold; rung label is driven by whether `charge_from_grid` is actually COMMANDED (rung-2 reached). If a numeric backstop is needed, reuse `arbitrage_grid_import_guard_kw` (12 kW default).** |
| K-tick window / sample history for projection | **REUSED.** `_attain_soc_history` (`:214`) + `_record_attain_sample` (`:959`). Same window already in flight every off_peak tick when attainability is armed. Plan extends sample collection to fire on the arbitrage-armed off_peak tick as well so rung-0 and rung-1 have data when they're needed. Constant `K` lives in `energy_const.py` (v5.3.8 added it). |
| Cross-coordinator ripple | **HVAC: NONE.** HVAC's `_should_solar_bank` is read-only against battery state and does not consume `arbitrage_phase`. Verified by grep of `hvac.py` / `hvac_predict.py` for `arbitrage_phase` and `_paused_by_arbitrage` — zero hits in HVAC files. Cycle is bounded to EC. |

### Prior planning docs consulted

- `docs/planning/PLANNING_ec_hc_reboot_decision_pickup.md` (v5.3.8) — full read. Defines the attain machinery this cycle REUSES wholesale (projection, K-tick rate window, latch/hysteresis, cold-boot defer, daylight-sliced Solcast). Explicitly says v1 attain is observe-only on EVs and notes "EVSE-coordination follow-up cycle" as open Q #5. **This cycle IS that follow-up — three-rung ladder narrowing scope to (a) the GATE-side complement (suppress arbitrage when solar will deliver under current loads — rung 0), (b) the redirect rung (suppress arbitrage AND pause EVs when redirecting their load to the battery makes solar attain — rung 1), and (c) leaves the v5.3.8 attain branch on the post-gate fallback intact as the realized-divergence safety net.**
- `docs/planning/PLANNING_v4.5.0_battery_strategy_redesign.md` + `PLANNING_v4.5.0_TRANSITION_NOTES.md` — full read. v4.5.0 D4 is the source of the compound-load EV-pause rule (`determine_arbitrage_actions`, breaker math `20 kW battery + 7.4 kW EV + 5 kW base ≈ 134 A`). Confirms the breaker rationale is REAL and constrains rung-2 (we cannot freely reorder "pause EV" after "grid charge"). Also confirms `_gate_is_open` was *designed* as the single arbitrage entry gate — narrowing it (not duplicating it) is the right shape.
- `docs/planning/PLANNING_ev_offpeak_proactive_charging_and_persistence.md` (v4.7.28) — full read. Confirms off_peak ensure-on must not regress; carry-over guard at `energy_pool.py:518-526` is the integration point that already swallows `_paused_by_arbitrage` membership. Cycle MUST keep both rungs inside that set so ensure-on remains gated.
- `docs/planning/PLANNING_v4.7.29_day_boundary_fix.md` (Bug Class #51) — skim. Not a direct sibling here; cited as background on TOU-boundary blindness.

### Memory bodies pulled

- `feedback_db_sensitive_3x_targeted_reviews.md` + `feedback_tier2db_for_regression_prone.md` — confirms operator-elevated Tier 2-DB framing.
- `feedback_pre_deploy_zero_bugs_gate.md` — applies at deploy.
- `feedback_fix_lows_in_cycle.md` — LOWs fixed in same fix-up pass.
- `feedback_parsimonious_room_config.md` — informs no-new-CONF guardrail.
- `project_ev_offpeak_cycle_pickup.md` + `project_ev_pause_post_peak_midpeak_decision.md` — durable EV principle: "solar-first → never drain battery into car → off_peak grid cheapest". Rung-1 (REDIRECT) is the operationalization of "solar-first" for the buffer-build case: when solar can't fill battery AND charge cars, prefer the battery (cheaper for the household because off_peak grid will fill the cars later).
- `project_load_shedding_audit_backlog.md` — flagged the `_paused_by_us` collision class. This cycle's discipline: NO new pause-owner set; reuse `_paused_by_arbitrage` + reason-label side-map. Re-read to confirm rung labelling does NOT regress the EVSE TOU-control pause-by-us interaction documented there.
- `project_v53_8_*` (mental model from session pickup) — v5.3.8 attain shipped + LIVE; this cycle sits atop it.

### Design docs read

- `docs/Coordinator/ENERGY_COORDINATOR_DESIGN_v2.3.md` — decision-cycle ordering invariants. The rung-0 / rung-1 predicates slot INSIDE `_gate_is_open` (same precedence neighborhood, not a new layer); the rung-label assignment slots INSIDE `determine_arbitrage_actions` (no change to call-order at `energy.py:2484`). Slot-in, not insert-between.

### Code locations surveyed end-to-end during scoping

- `energy_battery.py` — `_gate_is_open` (`:732-748`), `_get_arbitrage_phase` (`:750-858`), `_get_arbitrage_decision` (`:860-937`), v5.3.8 attain machinery in full (`:939-2000`), `determine_mode` off_peak branch (`:2240-2294`), `_effective_import_kw` primitive (`:678-717`).
- `energy_pool.py` — pause sets declaration (`:196-205`), per-EVSE power read at `_get_evse_state` (`:257-314` — confirms `power` field is unit-normalized watts, falls back to `EVSE_ESTIMATED_POWER_W` when sensor unavailable), `determine_arbitrage_actions` (`:1183-1274`), v4.7.28 off_peak ensure-on carry-over guard (`:488-561`), arbitrage attribute on EVSE diag (`:1350-1355`).
- `energy.py` — decision-cycle call to `determine_arbitrage_actions` (`:2470-2489`) and the existing `arbitrage_charging` derivation.

---

## D1 — Three-Rung Solar-Attainability Ladder on the Arbitrage Gate

### Problem statement (from the live incident, 2026-06-13 11:00 CDT)

Excellent-solar summer day. Arbitrage gate opened because `d2_class=poor` via the
multi-day-horizon branch (`energy_battery.py:744-747`) — today=excellent was irrelevant
to the gate. Result: `arbitrage_phase=charge`, `charge_from_grid=True`, EVs paused. BUT
solar was 17.0 kW, battery charging at +9.7 kW, net = -0.26 kW (slightly exporting).
The chunk was running on solar alone — the grid lever was on but unused, and the EV
pause was structurally unjustified (no breaker risk because no grid was flowing).
Today's solar trajectory alone would have reached `peak_buffer_target=80` well before
the 14:00 mid_peak boundary.

The gate never asks "could today's solar reach target unaided before boundary?" or the
weaker "could today's solar reach target if we redirected the EV load to the battery?"
This cycle answers both.

### Operator's ladder (verbatim ordering)

> "Suppress EVs comes first and then Charge from Grid comes next in intervention."

Translated into a 3-rung ladder driven by a two-pass projection at the decision tick:

- **Rung 0 — Do nothing (NEW, gate-suppression with CURRENT loads).** Project SOC at
  the high-rate boundary using current observed net rate + sliced Solcast surplus.
  If `projected_soc ≥ peak_buffer_target + ENTRY_HYSTERESIS_PCT`, the gate stays
  closed. No EV pause, no grid charge. This is the "today's solar will deliver even
  while the EVs eat their share" path.
- **Rung 1 — Redirect EVs to battery (NEW, the operator's middle rung).** If rung-0
  misses, RE-PROJECT with the EV load removed: adjusted rate =
  `observed_net_rate + ev_load_pct_per_h`, where `ev_load_pct_per_h` is computed from
  the summed per-EVSE power reads (`EVChargerController._get_evse_state(...)["power"]`,
  watts, summed over all currently-charging EVSEs) divided by `BATTERY_USABLE_KWH`,
  scaled to %/h. If `projected_soc_with_evs_paused ≥ peak_buffer_target +
  ENTRY_HYSTERESIS_PCT`, the gate stays closed AND the cycle commands an EV pause via
  `determine_arbitrage_actions` with rung label `"redirect"`. No grid charge is
  commanded. Re-evaluated each tick: when rung-0 recovers (projection passes with EVs
  back on), the gate closes and the rung-1 EVs auto-resume via the False-branch
  resume path.
  - **No-solar guard.** Rung 1 is only meaningful when there IS solar to redirect. If
    `_expected_solar_surplus_pct(now) < SOLAR_NEGLIGIBLE_PCT_PER_H` (night / heavy
    overcast / near-sunset), pausing EVs frees no usable solar (the load just shifts
    to grid via the battery's null charge). Skip rung-1, go straight to rung-2.
  - **No-EV-load guard.** If `ev_load_w == 0` (no EV is charging right now), rung-1
    collapses into rung-0 — there's nothing to redirect. Skip rung-1, go to rung-2.
- **Rung 2 — Charge from grid (UNCHANGED, the existing arbitrage path).** If neither
  rung-0 nor rung-1 projects to target, `_gate_is_open` returns True as today and the
  full arbitrage CHARGE phase fires. EVs are paused with rung label `"breaker"`
  (mandatory: the ~20 kW compound-load breaker rationale from v4.5.0 D4 applies).
  EVs stay paused with `"breaker"` label until `arbitrage_charging` flips False
  (phase exit from CHARGE), regardless of intermediate projection wobble.

**Why this ordering is provably least-cost in money terms.** Rung 0 = $0 grid, EVs
charging on solar. Rung 1 = $0 grid, EVs paused but will resume on rung-0 recovery (or
fill at off_peak cheapest rate). Rung 2 = grid-charge spend + EVs paused. Rung 1 is
strictly cheaper than rung 2 for the household when it's reachable.

### Design

**Insertion point.** `energy_battery.py:_gate_is_open` (`:732-748`). The current
predicate returns True on forecast-class alone. The cycle adds the rung-0 and rung-1
short-circuits BEFORE the True return. Pseudocode shape (NOT final code, for review
framing only):

```python
def _gate_is_open(self, now, target_day_class):
    if not self._arbitrage_enabled:
        return False
    fc_gate_open = (
        target_day_class in ("poor", "very_poor")
        or (self._multi_day_horizon_enabled
            and self.classify_solar_day_n(2) in ("poor", "very_poor"))
    )
    if not fc_gate_open:
        return False
    # Rung 0: today's solar will deliver under current loads.
    rung = self._classify_attain_rung(now)
    if rung == "rung_0":
        self._arbitrage_intent = None  # no EV pause requested
        return False
    if rung == "rung_1":
        self._arbitrage_intent = "redirect"  # signals EV pause without grid charge
        return False
    # rung == "rung_2": gate opens, normal CHARGE phase fires.
    self._arbitrage_intent = "breaker"
    return True
```

**`_classify_attain_rung(now)`.** Returns one of `"rung_0" | "rung_1" | "rung_2"`.
Pure function of:
1. `soc`, `peak_buffer_target` — same inputs as `_should_attain_peak_buffer`.
2. `minutes_to_high_rate_boundary` — reuse `_attain_target_boundary` (`:1173`) /
   `_is_charge_window_open` (`:563-578`).
3. Observed net-charge-rate K-tick smoothed (`_attain_soc_history`, sampled at
   `_record_attain_sample`). Cycle ensures the sample is recorded ON THE ARBITRAGE
   PATH TOO (currently only sampled on the attain branch).
4. Sliced expected-solar surplus pct via `_expected_solar_surplus_pct` (`:1033`) —
   byte-identical reuse.
5. Current EV load in watts: summed per-EVSE `power` field from
   `EVChargerController._get_evse_state` over all EVSEs where `charging=True`. Crossed
   from EC to BatteryState via an accessor on the pool (cleanest seam: a small
   `EVChargerController.current_charging_load_w() -> float` helper read by the EC
   decision cycle and passed into `_classify_attain_rung` as an argument, so
   `energy_battery.py` does NOT need to import from `energy_pool.py`).

Logic:

```
projected_soc_rung0 = soc + (observed_rate + solar_surplus_pct) * (mins/60)
if projected_soc_rung0 >= peak_buffer_target + ENTRY_HYSTERESIS_PCT:
    return "rung_0"

# Rung-1 no-solar / no-EV guards
if solar_surplus_pct < SOLAR_NEGLIGIBLE_PCT_PER_H:
    return "rung_2"
if ev_load_w == 0:
    return "rung_2"

ev_load_pct_per_h = (ev_load_w / 1000.0) / BATTERY_USABLE_KWH * 100
projected_soc_rung1 = soc + (observed_rate + ev_load_pct_per_h + solar_surplus_pct) * (mins/60)
if projected_soc_rung1 >= peak_buffer_target + ENTRY_HYSTERESIS_PCT:
    return "rung_1"

return "rung_2"
```

**Hysteresis on BOTH boundaries (operator ruling: 3% / 3%).** Two latches:
- `_arb_rung0_latch: bool` — when True, gate is suppressed at rung 0; flips False only
  when `projected_soc_rung0 < peak_buffer_target - EXIT_HYSTERESIS_PCT`.
- `_arb_rung1_latch: bool` — when True, EVs are paused at rung 1; flips False only
  when EITHER rung-0 recovers (then EVs resume via gate-closed path) OR
  `projected_soc_rung1 < peak_buffer_target - EXIT_HYSTERESIS_PCT` (then escalate to
  rung 2).

Both `ENTRY_HYSTERESIS_PCT = 3` and `EXIT_HYSTERESIS_PCT = 3`. Constants in
`energy_const.py`. Cold-boot: empty sample history → both predicates return False
(rung_2 by default, conservative — same as v5.3.8 cold-boot defer).

**Phase-token semantics.**
- Rung 0: `_arbitrage_active = False`, `arbitrage_phase = ARBITRAGE_PHASE_NA`, reason
  clause `"arbitrage suppressed — today's solar projects {projected}% by {boundary},
  target {target}%, rate {rate:+.1f}%/h, solar +{surplus:.1f}%"`.
- Rung 1: `_arbitrage_active = False` (no grid charge), `arbitrage_phase =
  ARBITRAGE_PHASE_NA`, reason clause `"arbitrage suppressed via EV redirect — pausing
  EVs lifts projection to {projected_rung1}% (vs {projected_rung0}% with EVs on)"`,
  AND `_arbitrage_intent = "redirect"` propagates to `determine_arbitrage_actions` so
  the rung label is recorded against each paused EVSE.
- Rung 2: unchanged from today, `_arbitrage_intent = "breaker"`.

**Composition with the v5.3.8 attain branch (explicit, operator-ruled).** Rung 0
"do nothing" is NOT blind — the v5.3.8 attain branch lives on the post-gate fallback
side (`_gate_is_open == False`) and runs whether the gate is False by rung-0 or by
naturally-good forecast. If today's solar later disappoints relative to the rung-0
projection, the v5.3.8 attain branch's realized-divergence detector still fires and
engages charging. **D1 makes the gate cheaper; v5.3.8 keeps it safe.** The two compose
without shadow: rung-0 suppression is forecast-driven, attain is realized-shortfall
driven.

**What this does NOT change.**
- The four-phase arbitrage state machine (CHARGE/HOLD/WAIT/DISCHARGE) unchanged.
- `peak_buffer_target`, `_arbitrage_chunk_completed`, grid-import guard machinery
  untouched.
- Behavior on real poor-forecast days where neither rung-0 nor rung-1 projects to
  target — predicate returns `"rung_2"`, gate opens as before. Net behavioral change
  is zero on poor/very_poor days when both projections actually fail.

### Acceptance criteria

- **Verify (rung-0 math):** unit tests on `_classify_attain_rung` cover (a)
  live-incident shape (soc=36, rate=+9%/h, mins=180, surplus=+24%, target=80 →
  `"rung_0"`); (b) genuine poor-day shape (soc=20, rate=-1%/h, mins=240, surplus=+3%,
  ev_load=0, target=80 → `"rung_2"`); (c) cold-boot empty sample → `"rung_2"` (no
  suppression).
- **Verify (rung-1 math):** (d) "EVs eat the solar" shape (soc=40, rate=+2%/h with EVs
  on, ev_load_w=14000, surplus=+15%, target=80, mins=180 → `"rung_1"` because removing
  EV load shifts the rate enough); (e) "EVs paused still wouldn't make it" (soc=20,
  rate=-1%/h, ev_load_w=14000, surplus=+5%, target=80 → `"rung_2"`); (f) no-solar
  guard (`surplus < SOLAR_NEGLIGIBLE_PCT_PER_H`, ev_load_w>0 → `"rung_2"` not
  `"rung_1"`); (g) no-EV-load guard (rung-0 misses, ev_load_w=0 → `"rung_2"` not
  `"rung_1"`).
- **Verify (no-flap, both boundaries):** simulated 12-tick trajectory where the rung-0
  projection oscillates ±3% around target — `_arb_rung0_latch` toggles at most once.
  Second 12-tick trajectory where rung-0 misses and rung-1 projection oscillates ±3% —
  `_arb_rung1_latch` toggles at most once.
- **Verify (precedence):** on a `target_day_class=poor` day with `d2=poor` AND BOTH
  projections below target, gate still opens to rung-2. Mutation authority: removing
  the rung-2 fall-through inverts the test outcome.
- **Verify (rung-1 → rung-0 transition):** sequence where rung-1 is active, then
  solar surges and rung-0 passes. Assert gate flips to closed AND rung-1 EVs resume in
  the same tick via the existing False-branch path.
- **Verify (rung-1 → rung-2 escalation):** sequence where rung-1 is active (sunny but
  not enough), then clouds roll in and `solar_surplus_pct` drops below threshold.
  Assert next tick classifies `"rung_2"`, gate opens, paused EVs' label flips from
  `"redirect"` to `"breaker"`, and they stay paused through phase exit (no spurious
  resume on the redirect→breaker transition).
- **Verify (composition with v5.3.8):** rung-0 suppresses; later in the day realized
  net rate underperforms projection; the v5.3.8 attain branch (on the post-gate
  fallback path) still fires. The two are mutually compatible — explicit test that
  rung-0 short-circuit does not bypass attain machinery downstream.
- **Sensor:** `sensor.ura_energy_battery_strategy.reason` contains the rung-specific
  suppression clause; `arbitrage_phase = "n/a"` for rungs 0 and 1.
- **Live (rung-0):** Reproduce the 2026-06-13 shape on the next excellent-solar day
  with `d2_class=poor`. Verify gate stays closed via rung-0, EVs stay charging,
  battery climbs to `peak_buffer_target` from solar alone, NO grid pulled
  (`current_grid_cost_per_hour == 0` sustained). README entry: entity-attribute reads
  at three points (08:30 / 11:00 / 13:30), plus log scan for the rung-0 reason clause.
- **Live (rung-1):** On an excellent-solar day where the EVs are actively eating the
  solar enough that rung-0 misses but rung-1 attains, verify EVs pause with label
  `"redirect"`, battery reaches `peak_buffer_target` on solar, `charge_from_grid` is
  NEVER commanded, EVs resume the moment rung-0 projection recovers. README live
  entry shows the rung-1 reason clause, `paused_by_arbitrage_reasons` showing
  `"redirect"`, and the auto-resume timing.
- **Live (rung-1 → rung-2 escalation):** Cloudy / late-afternoon shape where rung-1
  was active and solar collapses. Verify the rung label visible on
  `paused_by_arbitrage_reasons` flips `"redirect"` → `"breaker"`, no spurious EV
  resume between the label flip, and grid charge commands begin. README entry
  documents the transition tick.

---

## D2 — Pause-Reason Label Threaded into `determine_arbitrage_actions`

### Problem statement

`determine_arbitrage_actions(arbitrage_charging=True, ...)` (`energy_pool.py:1213-1240`)
pauses every EVSE unconditionally when phase == CHARGE. With the rung 1 / rung 2
distinction from D1, the call site now needs to communicate **why** the pause is being
requested so the side-map carries the correct resume policy.

The label is **driven by D1's `_arbitrage_intent`**, NOT by a kW threshold on actual
grid draw. Operator ruling: redirect vs breaker is a decision about WHICH RUNG fired,
not about whether the current grid reading is above a magic number.

### Design

**Reason side-map.** Add alongside `_paused_by_arbitrage`:

```python
self._arbitrage_pause_reason: dict[str, str] = {}
# values: "redirect" (rung 1: EVs paused to redirect solar to battery; no grid charge
#                     commanded; resume the moment rung-0 projection recovers)
#         "breaker"  (rung 2: grid charge commanded; resume only on phase exit)
```

NO new set; `_paused_by_arbitrage` remains canonical membership. Label is metadata.

**Caller threads the rung intent.** `energy.py` decision-cycle call site
(`:2484-2489`) passes the D1-computed `_arbitrage_intent` (one of `"redirect"`,
`"breaker"`, or `None`) into `determine_arbitrage_actions` as a new
`pause_reason: str | None` argument. None means rung-0 (no pause; the
`arbitrage_charging=False` branch handles release of any prior-tick `_paused_by_arbitrage`
members per the rung-aware resume logic below).

**Pause path.** `determine_arbitrage_actions` becomes:

```python
def determine_arbitrage_actions(
    self, arbitrage_charging, tou_period, pause_reason=None,
):
    # arbitrage_charging here is the BROADER signal: True iff D1 wants
    # the EVs paused for ANY arbitrage reason (rung 1 OR rung 2).
    if arbitrage_charging:
        assert pause_reason in ("redirect", "breaker"), \
            "rung intent must be set when pausing"
        for evse_id, config in self._evse.items():
            # ... existing dispatch loop ...
            self._paused_by_arbitrage.add(evse_id)
            self._arbitrage_pause_reason[evse_id] = pause_reason
        return actions
```

Note the broadening: `arbitrage_charging` no longer maps 1:1 to "grid charge
commanded"; it now means "EVs should be paused for arbitrage". The CALLER decides
which rung. The variable name should be renamed in `energy.py` to reflect this
(suggested: `arbitrage_pause_requested` or `arbitrage_pause_intent`); flag for
reviewer A.

**Breaker-safety invariant (reviewer B's primary axis).** When the rung label is
`"breaker"`, EVs MUST be paused. The `"redirect"` label is only emitted on rung-1
ticks (D1 has already established no grid charge will be commanded). The invariant
is enforced at the assertion site: on any tick where `charge_from_grid` is commanded
(rung-2 was reached), the upstream caller MUST pass `pause_reason="breaker"`. A
unit test inverts this (caller passes `"redirect"` while rung-2 is active) and
asserts the assertion fires.

**Resume path — rung-aware.** `determine_arbitrage_actions(arbitrage_charging=False, ...)`
(currently `:1242-1273`) reads `self._arbitrage_pause_reason[evse_id]` each tick to
decide:
- **Rung-2 (`"breaker"`):** unchanged from today — release on phase exit from CHARGE
  (which is what gets us into this False-branch), subject to TOU + sibling-owner
  precedence.
- **Rung-1 (`"redirect"`):** release the moment we land in this False-branch (which
  happens automatically the tick after D1 transitions away from rung-1 — either down
  to rung-0 because solar surged, or up to rung-2 because solar collapsed). Same TOU
  + sibling-owner precedence applies.

**Mid-CHARGE label flip (operator-ruled #2).** A label change is sufficient IF resume
logic keys on the CURRENT label each tick. The False-branch above reads
`self._arbitrage_pause_reason[evse_id]` fresh; the True-branch overwrites it fresh.
Sequence (verified by test):
- Tick T: rung-1, EVs paused, label `"redirect"`.
- Tick T+1: solar collapses, rung-2 reached, caller passes `pause_reason="breaker"`.
  Label flips to `"breaker"` in the True-branch; EVs stay in the set (already in,
  short-circuit at `:1218`); no churn dispatch.
- Tick T+N: phase exits CHARGE. False-branch reads label `"breaker"` and applies
  rung-2 resume policy. Correct.

The redirect→breaker flip happens silently in the label dict; no EV state-machine
disruption. Document this transition explicitly so a future reviewer doesn't search
for a separate "promotion" code path that doesn't exist.

**Net change to `_paused_by_arbitrage` semantics: minimal.** The set itself behaves
identically. The cycle's actual code change is:
- Threading `pause_reason` through the call site.
- Adding the rung-label dict + populating it on every pause-True-branch iteration.
- Reading the label in the False-branch for resume decisions.
- Surfacing the label on `paused_by_arbitrage` diagnostic attribute as a parallel
  list `paused_by_arbitrage_reasons` (per-EVSE).

**Interaction with v4.7.28 off_peak ensure-on.** `energy_pool.py:518-526` carry-over
guard checks `evse_id in self._paused_by_arbitrage`. Both rung labels satisfy this
check identically — neither label permits a v4.7.28 ensure-on to re-issue turn_on.
The ensure-on stays gated until the EVSE leaves the set via the False-branch of
`determine_arbitrage_actions`. **No regression to v4.7.28 behavior.**

**Interaction with `_paused_by_us` (TOU) and load-shedding cycle.** Verified by re-read
of `project_load_shedding_audit_backlog.md`: the load-shedding EV tier proposes a 4th
pause-owner write to `_paused_by_us`, which collides with v4.7.28 TOU semantics. This
cycle adds NO new pause-owner set. The reason-label dict is local to arbitrage and
does not touch `_paused_by_us`. Cross-reference noted; no new collision introduced.

**Numeric backstop (operator-ruled, optional).** Per operator ruling #1, there is NO
new `ARBITRAGE_BREAKER_RISK_KW` constant. If during review a numeric backstop is
deemed necessary, REUSE the existing `arbitrage_grid_import_guard_kw` (12 kW default)
— do not invent a new CONF.

### Acceptance criteria

- **Verify (label assignment driven by rung):** unit tests on `determine_arbitrage_actions`
  parametrized by `pause_reason ∈ {"redirect", "breaker"}` — set membership identical,
  side-map differs accordingly.
- **Verify (breaker invariant — caller assertion):** mutation test — caller passes
  `pause_reason="redirect"` while D1 classified `"rung_2"`; assertion in
  `determine_arbitrage_actions` (or a guard at the call site in `energy.py`) fires.
- **Verify (None safety):** when `_arbitrage_intent=None` (rung-0, no pause requested),
  caller does NOT invoke the pause True-branch; the False-branch fires and any prior
  arbitrage-paused EVs are released per their stored label.
- **Verify (ensure-on integration):** v4.7.28 carry-over guard test — for both rung
  labels, off_peak ensure-on path observes `_paused_by_arbitrage` membership and
  skips. Asserts both `_proactive_offpeak_holds.discard` and `continue`.
- **Verify (no double-claim):** rerun with EVSE already in `_paused_by_battery_drain`
  → label is recorded BUT the pause action is not duplicated (no second turn_off).
  Reuses existing `:1218` "already paused" short-circuit.
- **Verify (resume keys on current label):** sequence (rung-1 / `"redirect"`, then
  rung-0 / False-branch) → EV resumed in same tick the False-branch fires.
  Sequence (rung-1 / `"redirect"`, then rung-2 / `"breaker"`, then phase exit) →
  EV paused throughout, resumed only on the phase-exit False-branch tick. Both
  derive from reading the CURRENT label.
- **Verify (label flip survives, no churn):** redirect→breaker transition — EV
  remains in `_paused_by_arbitrage` set across the boundary, label dict updates,
  no extra `switch.turn_off` dispatched (already off).
- **Sensor:** EV diagnostic sensor attribute `paused_by_arbitrage_reasons` lists
  per-EVSE rung labels matching the set membership.
- **Live:** On the 2026-06-13 shape post-deploy, the rung-1 path produces label
  `"redirect"` (validated via attribute read). On a separate cloudy/late-day shape
  where rung-2 is reached, label is `"breaker"`. README live entry shows both labels
  observed in a multi-day window OR documents why only one was seen.

---

## D3 — Tests + ledger conventions

- New tests under `quality/tests/` per CLAUDE.md.
- Fixtures drive REAL `BatteryStrategy.determine_mode` and REAL
  `determine_arbitrage_actions` — no hand-mutated `_paused_by_arbitrage`,
  `_arbitrage_pause_reason`, `_attain_state`, `_arb_rung0_latch`, or
  `_arb_rung1_latch`.
- Real `energy_const.py` rate schedule; mocked Solcast remaining + sunrise/sunset via
  the same test seams v5.3.8 used.
- Mutation-authority bar: ≥5 tests must fail when inverting any of (a) the rung-0
  predicate, (b) the rung-1 re-projection (EV-load subtraction), (c) the rung-label
  assignment in `determine_arbitrage_actions`, (d) the no-solar / no-EV-load guards,
  (e) the cold-boot defer.
- Review ledger at `docs/reviews/code-review/<deploy-version>_arbitrage_solar_attainability_ladder.md`
  per the standard Tier 2-DB shape: A/B/C findings, validator, fix-up.

---

## Plan Completion Tracking (to be filled at end of cycle per CLAUDE.md)

- [ ] D1 `_classify_attain_rung` + rung-0/rung-1 latches + suppression short-circuits
  in `_gate_is_open` + tests + reason narrative + `_arbitrage_intent` propagation.
- [ ] D1 EV-load accessor `EVChargerController.current_charging_load_w()` + caller
  threading from `energy.py:2484` into `_gate_is_open`.
- [ ] D2 `pause_reason` argument threaded from `energy.py:2484` →
  `determine_arbitrage_actions` + rung-label side-map + breaker-invariant assertion
  + rung-aware resume + tests.
- [ ] EV diagnostic sensor attribute `paused_by_arbitrage_reasons` shipped.
- [ ] README post-deploy validation table: live D1 rung-0 suppression on an
  excellent-solar day with d2=poor; live D1 rung-1 suppression with `"redirect"`
  label observed; live rung-1 → rung-2 escalation with label flip observed; live
  rung-2 (`"breaker"`) observed at least once on a real grid-charge tick.
- [ ] Backlog stubs for items explicitly deferred (none currently identified).

---

## Operator dispositions on prior open questions (now resolved — baked in)

1. **No `ARBITRAGE_BREAKER_RISK_KW` constant.** The `breaker` label is driven by
   whether `charge_from_grid` is actually COMMANDED (rung 2 reached), not by a kW
   threshold. If a numeric backstop is required during review, reuse
   `arbitrage_grid_import_guard_kw` (12 kW default) — no new CONF. — Resolved in D2.
2. **redirect→breaker mid-CHARGE flip.** A label change is sufficient because resume
   logic keys on the CURRENT label each tick. The False-branch reads
   `self._arbitrage_pause_reason[evse_id]` fresh, the True-branch overwrites it
   fresh. No separate "promotion" code path exists or is needed. Transition
   documented in D2. — Resolved.
3. **Hysteresis.** `ENTRY_HYSTERESIS_PCT = 3`, `EXIT_HYSTERESIS_PCT = 3`. Applied to
   BOTH the rung-0 gate boundary (`_arb_rung0_latch`) AND the rung-0↔rung-1
   boundary (`_arb_rung1_latch`). — Resolved in D1.
4. **"EV suppress first" = the rung-1 REDIRECT.** Resolved by restoring the explicit
   rung-1 in D1. EV pause precedes grid charge in the ladder; rung-1 pauses EVs
   without commanding grid charge, rung-2 only fires if rung-1's re-projection
   still misses. — Resolved.
5. **Composition with v5.3.8 attain.** Clean. D1 suppresses the arbitrage gate when
   solar attains under either projection; the v5.3.8 attain branch on the post-gate
   fallback still catches realized divergence if solar later disappoints. Rung-0
   "do nothing" ≠ blind; attain is the safety net. Explicit composition test in
   D1 acceptance criteria. — Resolved.

---

## Summary (≤350 words)

**Deliverables.**
- **D1 — Three-rung solar-attainability ladder on the arbitrage gate.** New
  `_classify_attain_rung(now)` inside `_gate_is_open` (`energy_battery.py:732`)
  runs a TWO-PASS projection at the decision tick. Rung 0: project SOC at the
  high-rate boundary with current observed rate + sliced Solcast surplus + current
  EV load; if `≥ target + 3%`, gate stays closed (do nothing). Rung 1: re-project
  with EV load removed (estimated from summed per-EVSE `power` watts via
  `EVChargerController.current_charging_load_w()`, divided by `BATTERY_USABLE_KWH`);
  if `≥ target + 3%`, gate stays closed AND `_arbitrage_intent = "redirect"`
  triggers an EV pause without commanding grid charge. No-solar and no-EV-load
  guards short-circuit rung-1 to rung-2. Rung 2: existing arbitrage CHARGE path
  fires, `_arbitrage_intent = "breaker"`. Symmetric 3%/3% hysteresis on BOTH the
  rung-0 gate AND rung-0↔rung-1 boundaries kills wobble. Cold-boot defers to
  rung-2 (conservative).
- **D2 — Rung-label-aware `determine_arbitrage_actions`.** Thread `pause_reason`
  argument from `energy.py:2484` (driven by D1's `_arbitrage_intent`).
  `_arbitrage_pause_reason: dict[evse_id, "redirect"|"breaker"]` side-map alongside
  the existing `_paused_by_arbitrage` set (no 4th owner set). Resume path reads the
  CURRENT label each tick: rung-1 EVs auto-resume when rung-0 recovers (gate closes,
  False-branch fires); rung-2 EVs only resume on phase exit from CHARGE.
  Redirect→breaker mid-CHARGE flip is a silent label change (no churn). Surfaces via
  new `paused_by_arbitrage_reasons` attribute on the existing EV diagnostic sensor.

**Key decisions (all operator-ruled).**
- 3-rung ladder ordering: do-nothing → redirect → grid, with redirect strictly
  cheaper than grid when reachable.
- No new CONF, no `ARBITRAGE_BREAKER_RISK_KW`; rung label is driven by rung intent.
- Hysteresis 3%/3% on both boundaries.
- Composition with v5.3.8 attain branch: D1 makes the gate cheaper; v5.3.8 keeps it
  safe via realized-divergence detection on the post-gate fallback.
- Breaker-safety invariant: every grid-charge-commanding tick MUST label EVs
  `"breaker"`; enforced by assertion.
