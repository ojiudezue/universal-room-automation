# PLANNING — EVSE solar-following amp modulation + DP drain-target mis-sourcing fix

**Cycle name:** `evse-solar-follow-and-dp-drain-target`
**Tier:** **Tier 3** (operator ruling: "Tier 3 means cost in review. Code itself can be simple.")
**Threads:** `energy`
**Cards:** `EVSE-SOLAR-FOLLOW-AMPS-1` (D1, D2), `EVSE-DRAIN-PRECEDENCE-KNOB-80-1` (D3)
**Design source:** the two card bodies (esp. `DESIGN_CLOSED_2026_08_23`,
`SIGNAL_DESIGN_FINAL_2026_08_23`, `SENSOR_DELTA_MEASURED_2026_08_23`, `SCOPE_FENCE_2026_08_23`,
`OPERATOR_ANSWERS_AND_VERIFIED_FACTS_2026_08_23`, `RE_VERIFIED_2026_08_23_card_stands_memory_was_stale`,
`SCOPING_2026_08_20_ONE_NUMBER_THREE_ROLES`, `RECOMMENDED_DESIGN_D_SPLIT_THE_ROLES`) and
`docs/planning/AUDIT_excess_solar_and_evse_prior_art.md`.
**Probes:** `scripts/probes/delta_probe.py`, `scripts/probes/skew_probe.py`.

**Revision 8 (2026-08-23) — narrow.** Operator asked: *"The idea is to divide by the active
denominator? Could be 1 or 2. And detect that accurately? Garage B is not used often at the
moment but that could change."* Verified in source: `_excess_solar_active.add(evse_id)` at
`energy_pool.py:1656` happens inside `if not state["is_on"]:` (`:1650`) after the switch is
turned on; nothing on that path checks plug presence. `charging = power > 100 W` at `:691`.
An empty-but-switched-on bay reads `charging=False, power≈0, power_source="sensor"` — Rev-5's
ELIGIBLE gate passes. So with one car on garage_a and an empty garage_b: `N_eligible = 2`,
`A_total` splits in half, garage_a receives ~half the surplus, the rest exports. **50%
under-use on the ordinary two-charger install; opposite of the cycle's purpose; latent
today because garage_b is lightly used, live the day the second bay starts being used.**

Distinction from Rev-5's `power_source` gate: that gate filters FABRICATED power (7600 W
`switch_status` fallback that inflates the numerator). Rev-8's defect is ZERO power from a
HEALTHY sensor that inflates the denominator. Different failures, opposite directions.
Neither gate catches the other.

**Fix, two separate predicates (avoiding the chicken-and-egg trap the operator flagged):**
- **ELIGIBLE** (Rev-5 semantics preserved — this IS "COMMANDABLE" per coordinator's
  phrasing): in `_excess_solar_active`, not peer-held, `power_source == "sensor"`.
  Receives amp writes.
- **DRAWING** ⊆ ELIGIBLE: additionally `charging == True`. Counts toward the allocation
  denominator AND the S_eligible add-back.

A bay that is ELIGIBLE but not DRAWING gets a **MIN safe-parking command** (6 A) — it can
start (relay closes at pilot floor, not 48 A) but it does NOT dilute the denominator. A
bay that transitions to DRAWING mid-window is picked up by the next tick's denominator
and allocation re-splits. The one-tick lag (≤60 s) is acceptable: (a) it self-corrects; (b)
the pre-written MIN command caps the plug-in transient at 1.44 kW/bay (hardware floor), not
11.5 kW (48 A default) — INV-SF-4 stays satisfied within its `max(..., N·MIN·240)` term;
(c) errs toward under-draw for the newly-drawing bay, which INV-SF-4 permits.

Rev-1..Rev-7 preserved. §12 change log names each edit. Nothing else re-opened.

---

## 0. Tier-3 elevation and framing

(Unchanged.)

---

## 1. Falsifiable invariants

### INV-SF-1 (non-perturbation)
`SolarFollowController` emits no `switch.turn_on`/`switch.turn_off`. Writes only
`number.set_value` to a current-limit entity, only for an EVSE in `_excess_solar_active`.

### INV-SF-2 (writes only inside sessions)
Both sets empty → zero writes.

### INV-SF-3 (restore is load-bearing, restart-safe)
After removal from `_excess_solar_active` by any code path, current-limit restored to saved
`_original_amps` within one restore tick — subject to INV-SF-7.

### INV-SF-4 (draw bounded by measured surplus — Rev-8 restated on DRAWING vs ELIGIBLE)
`ELIGIBLE = {evse_id ∈ _excess_solar_active where NOT _stronger_peer_holds(evse_id) AND
evse_id ∉ _paused_by_dp AND _get_evse_state(evse_id).power_source == "sensor"}` (commandable).
`DRAWING = {evse_id ∈ ELIGIBLE where _get_evse_state(evse_id).charging is True}` (subset;
`charging = power > EVSE_CHARGING_POWER_THRESHOLD = 100 W`).
`S_eligible = -grid_W + Σ_{DRAWING} evse_power_w` — **the add-back sums only DRAWING bays,
because a non-drawing bay contributes zero physical power to the load `grid_W` is measuring
and adding zero-back would be numerically identical anyway**.

**Bound on commanded amps at a given tick:**
`Σ_{i ∈ DRAWING} A_i · 240 · PHASES ≤ max(S_eligible, N_drawing · MIN · 240)`.
`Σ_{i ∈ ELIGIBLE \ DRAWING} A_i · 240 · PHASES` is BOUNDED by
`(N_eligible - N_drawing) · MIN · 240` (each non-drawing ELIGIBLE bay is commanded MIN safe-
parking; if a plug goes in mid-window the physical draw ramps to at most MIN·240 = 1.44 kW
per bay).

**Bound on physical draw within a ≤60 s window** (accounting for at-most-one bay
transitioning from non-DRAWING to DRAWING between ticks):
`Σ_{physically drawing at time t} A_i · 240 · PHASES ≤ max(S_eligible, N_eligible · MIN · 240)`.
The over-commit due to a plug-in mid-window is bounded by `(N_eligible - N_drawing) ·
MIN · 240` and lasts ≤60 s. On the ordinary N_eligible=2 install this is ≤1.44 kW for ≤60 s
(≤24 Wh over the window) — trivial vs the yo-yo class this cycle prevents (many kWh over
minutes).

### INV-SF-5 (asymmetric reaction to a lagging signal)
Down uncapped; up gated + capped. PRIMARY is 60 s average; up-gate contains ramp mismatch.

### INV-SF-6 (fleet allocation — Rev-8 restated on DRAWING)
Let `N_denom = max(1, N_drawing)` — the max()-with-1 prevents division-by-zero in the
all-idle degenerate case and mathematically expresses "if a single bay is starting, treat
it as the sole denominator so it gets the full commanded surplus."
`A_total_target = floor(S_eligible / (240 · PHASES))`.
`A_per_drawing = clamp(A_total_target // N_denom, MIN, MAX)`.

**Command routing (Rev-8):**
- DRAWING bays receive `A_per_drawing`.
- ELIGIBLE \ DRAWING bays receive `SOLAR_FOLLOW_MIN_AMPS` (6 A) as a **safe-parking
  command**. This caps the plug-in transient at MIN·240 = 1.44 kW/bay for ≤60 s (see
  INV-SF-4).

**Degenerate cases:**
- `N_drawing == 0, N_eligible ≥ 1` (all idle): `N_denom = 1`; but there are no DRAWING bays
  to command; all ELIGIBLE bays receive MIN safe-parking. `A_per_drawing` is computed but
  routed to no one this tick (log INFO). This lets a bay that starts drawing next tick be
  allocated correctly without divide-by-zero.
- `N_drawing = 1, N_eligible = 2` (one drawing, one idle): the drawing bay receives
  `A_per_drawing` computed with `N_denom = 1` (full commanded surplus); the idle bay
  receives MIN safe-parking. If the idle bay starts drawing before the next tick, its
  physical draw is bounded by MIN·240 per INV-SF-4's within-window clause.
- `N_drawing == N_eligible ≥ 1` (all drawing): standard equal-split.

### INV-SF-7 (stronger-peer subordination — NO EXCEPTIONS)
While `_stronger_peer_holds(evse_id) is True` OR `evse_id ∈ _paused_by_dp`, no write to
that EVSE and no capture. Applies to BOTH step 2a (restore) AND step 5 (modulation).
`_paused_by_dp` inline. No exceptions carved out for individual peer owners.

### INV-RELEASE-1 (D2)
Release fires only when `not conditions_met OR solcast<floor` AND streak ≥ MIN_TICKS AND
session age ≥ MIN_ON_S.

### INV-DP-DRAIN-1 / 1b / 2 / 3 / 4 (unchanged)
See §3.D3.

---

## 2. Institutional context verified

(Unchanged from Rev-7 except:)

* `energy_pool.py:1650-1656` — the excess-solar CLAIM path: `if not state["is_on"]:` →
  emit `switch.turn_on` + `_excess_solar_active.add(evse_id)`. **No plug-presence check
  anywhere on this path** (Rev-8 verification). An Emporia bay with no vehicle draws ≈0 W
  when the relay is closed. This is the source of the "empty bay dilutes denominator"
  defect Rev-8 fixes.
* `energy_pool.py:691` — `charging = power > EVSE_CHARGING_POWER_THRESHOLD` (100 W at
  `energy_const.py:826`). This is the field D1's DRAWING subset predicates on.

All other §2 items unchanged from Rev-7.

---

## 3. Deliverables

### D1 — SolarFollowController

**Class shape (Rev-5/7 pin, unchanged Rev-8).**

**Design points, D1.2 surplus signal with `power_source` gate, D1.3 self-consistency stop,
D1.4 current-limit entities, D1.5 Solcast wiring for D2's release, D1.6 bounded readback
verify, D1.7 write-budget containment, D1.9 non-peer-hold owner accounting, STEP 0
edge-detector for `drain_trips_during_follow`:** all unchanged from Rev-7.

**Per-tick control law (Rev-8 update — steps 5-9 restated on DRAWING vs ELIGIBLE; steps
0-4 unchanged):**

```
0. STEP 0 edge-detector (Rev-7, unchanged): observe _paused_by_battery_drain
   membership transitions; increment _drain_trips_during_follow when an EVSE
   transitions from not-in to in the set while it is in _excess_solar_active.
   Snapshot updated every tick regardless of fast-path exit.

1. If _excess_solar_active empty AND _original_amps empty: return.

2. RESTORE PASS (iterate list(self._original_amps), unchanged Rev-5/7):
   - 2a: if peer-held or DP-held, DEFER (add to _deferred_restore_evses).
   - 2b: else if entity unresolvable (config prune), CLEAR entry + drop from gauge.
   - 2c: else restore.

3. If _excess_solar_active empty: return.

4. Read grid_W via D1.2 PRIMARY/FALLBACK. If both unavailable for STALE_MAX_TICKS: no writes.

5. Build ELIGIBLE (Rev-5 rules, preserved):
   ELIGIBLE = {evse_id in _excess_solar_active
               where NOT _stronger_peer_holds(evse_id)
               AND evse_id not in _paused_by_dp
               AND _get_evse_state(evse_id).power_source == "sensor"}.
   If ELIGIBLE empty: no writes, no captures (INV-SF-7). Return.

   Build DRAWING ⊆ ELIGIBLE (Rev-8 new):
   DRAWING = {evse_id in ELIGIBLE
              where _get_evse_state(evse_id).charging is True}.

6. N_eligible = len(ELIGIBLE); N_drawing = len(DRAWING); N_denom = max(1, N_drawing).

7. Compute add-back over DRAWING (Rev-8 corrects "over ELIGIBLE" from Rev-5/7 — a
   non-drawing bay contributes 0 to physical load so summing over DRAWING is
   arithmetically identical AND semantically clearer):
   add_back_w = 0.0
   for evse_id in DRAWING:
       s = self._ev._get_evse_state(evse_id)                    # noqa: SLF001
       if s.get("power_source") == "sensor":  # belt-and-braces; DRAWING implies this
           p = s.get("power") or 0.0
           try: add_back_w += float(p)
           except (TypeError, ValueError): pass
   S_eligible = (-grid_W) + add_back_w
   A_total_target = floor(S_eligible / (240 * SOLAR_FOLLOW_PHASES))

8. A_per_drawing_raw = A_total_target // N_denom.

9. For each evse_id in ELIGIBLE:
   a. Capture _original_amps[evse_id] per D1.6 capture guard if unset.
   b. If evse_id in DRAWING:
        A_target = clamp(A_per_drawing_raw, MIN, MAX)
      Else (ELIGIBLE \ DRAWING — safe-parking, Rev-8 new):
        A_target = SOLAR_FOLLOW_MIN_AMPS  # 6 A
   c. A_current = read current-limit entity (unavailable => skip THIS EVSE this tick).
   d. Deadband: skip if |A_target - A_current| < SOLAR_FOLLOW_DEADBAND_A.
   e. Step law (INV-SF-5):
        if A_target > A_current: up-gate + step-cap.
        else: down uncapped.
   f. Write-budget: skip + WARN if hour bucket exceeded.
   g. Emit {number.set_value, current_limit_entities[evse_id], A_write}.
   h. Schedule readback verify.
```

**One-tick lag statement (Rev-8, explicit per operator ask):** when an ELIGIBLE bay
transitions from not-DRAWING to DRAWING, the next tick's denominator picks it up and the
allocation re-splits. The intervening window is ≤60 s. During that window the newly-
drawing bay is physically drawing at its pre-written safe-parking command (MIN = 6 A,
1.44 kW) — the pilot floor cap prevents the 11.5 kW plug-in transient a 48 A default would
cause. INV-SF-4's within-window clause `max(S_eligible, N_eligible · MIN · 240)` bounds the
over-commit at `(N_eligible - N_drawing) · MIN · 240` for ≤60 s. On the ordinary
two-charger install this is ≤1.44 kW × 60 s = ≤24 Wh. Errs toward under-draw for the
newly-drawing bay (it ramps from MIN not from full surplus), which INV-SF-4 permits.

**Pause ENTRY/RELEASE policies:** unchanged Rev-6/7.

**D1.2 surplus signal:** unchanged Rev-5/7 EXCEPT the add-back sum in the formula is now
over DRAWING, not ELIGIBLE (arithmetically identical because non-DRAWING bays contribute
zero to physical power; the Rev-8 restatement is a clarity fix).

**Rev-8 pinned footguns (spec-level, complement Rev-7's edge-detector footguns):**

1. **Two predicates, one design.** ELIGIBLE (commandable) and DRAWING (denominator +
   add-back) are DELIBERATELY distinct sets. Collapsing them (a builder "simplifying" to
   `N_denom = len(ELIGIBLE)`) recreates the empty-bay-dilutes defect. C20 anchors this.
2. **Safe-parking is load-bearing, not decorative.** ELIGIBLE \ DRAWING bays receive MIN
   even if it looks wasteful. Skipping them leaves the current-limit at whatever the bay
   held (typically the operator's 48 A setting), and a plug-in mid-window then draws
   11.5 kW — the yo-yo class this cycle prevents. C20b anchors this.
3. **Chicken-and-egg avoided by construction.** A bay that is ELIGIBLE but not DRAWING
   receives a command (safe-parking MIN) so it CAN start — exclusion from the denominator
   is NOT exclusion from receiving a command, per the operator's flag.
4. **Original-amps capture happens on ENTRY to ELIGIBLE, not DRAWING.** A bay may be
   ELIGIBLE without ever DRAWING for a whole session (empty bay, session ends, no plug-in);
   D1.6's capture guard fires on the first tick the bay is in ELIGIBLE (unchanged). Restore
   on session end returns the bay to its captured original (unchanged Rev-5).

**D1.8 status sensor (Rev-8 adds two attributes):**

* `active`, `eligible_evses` (Rev-5), `s_eligible_kw`, `deferred_restore_evses` (gauge),
  `capture_rejected_low`, `drain_trips_during_follow` (Rev-7 edge-detector),
  `writes_per_hour_per_evse`, `current_amps`, `original_amps`, `stale_ticks`,
  `excluded_switch_status_evses` — all unchanged.
* **`drawing_evses: list[str]` (Rev-8 add)** — the DRAWING subset this tick. Observability
  aid: at-a-glance distinguishes "commandable" from "counts toward allocation." Live
  confirmation for T-DRAW-1's oracle.
* **`safe_parked_evses: list[str]` (Rev-8 add)** — the ELIGIBLE \ DRAWING subset this
  tick (bays receiving MIN safe-parking commands). Explicit surface for the "empty-bay
  gets 6 A" behaviour so a puzzled operator can find it without reading source.

**Constants** (unchanged Rev-4 table).

**D1 acceptance (Rev-8 updates):**

* All Rev-5/6/7 tests preserved except where noted below.
* **INV-SF-4 parametric** — fixture spec updated to distinguish DRAWING from ELIGIBLE.
* **INV-SF-6 fleet split** (`test_solar_follow_two_evses_split_surplus`) — fixture spec
  Rev-8 explicitly pins BOTH bays `charging=True, power > 100 W` so both are DRAWING
  (else the split test tests the safe-parking case, not the fleet-split case).
* **INV-SF-6 degenerate** (`test_solar_follow_two_evses_below_floor_holds_at_min`) —
  fixture pins both DRAWING at low share; unchanged mechanism.
* **T-PEER-5** oracle Rev-8 update: fixture has garage_a peer-held (drawing 7.4 kW,
  ineligible) and garage_b `charging=False, power=0` (ELIGIBLE, non-DRAWING). Under Rev-8:
  ELIGIBLE={garage_b}, DRAWING={}, N_drawing=0 → degenerate case: garage_b receives MIN
  (6 A) safe-parking. Under Rev-5 (pre-DRAWING split) the assertion was 8 A (S_eligible=
  2000, N=1). Rev-8's 6 A discriminates against both Rev-3 fleet-wide (16 A+) and Rev-5
  (8 A). Test docstring notes: T-PEER-5's discrimination is preserved because Rev-8's 6 A
  still differs from Rev-3's 39 A. Rev-8 assertion: garage_b commanded 6 A;
  `safe_parked_evses` contains garage_b; `drawing_evses` empty; no add-back into
  S_eligible (0 vs 7400 vs pre-Rev-4 fleet-wide).
* **T-DRAW-1 (Rev-8 new — the operator's empty-bay test):**
  `test_solar_follow_full_surplus_to_single_drawing_bay_when_other_bay_idle`.
  Fixture: garage_a and garage_b both in `_excess_solar_active`, neither peer-held, both
  `power_source="sensor"`. garage_a `charging=True, power=5000`. garage_b `charging=False,
  power=0` (empty bay, relay closed by claim path per `energy_pool.py:1650-1656`, no
  vehicle plugged). `grid_W = -5000` (5 kW exporting).
  Rev-8 expected: ELIGIBLE={a,b}, DRAWING={a}, N_drawing=1, N_denom=1, add_back=5000,
  S_eligible=10000, A_total=41, garage_a commanded 41 A (9.84 kW).
  garage_b receives 6 A safe-parking.
  `drawing_evses=["garage_a"]`, `safe_parked_evses=["garage_b"]`.
  Under bug (denominator = `len(ELIGIBLE) = 2`, Rev-5 behaviour): garage_a commanded 20 A
  (4.8 kW), garage_b commanded 20 A (would draw 20 A if plugged in). Discriminating:
  **41 A vs 20 A** for garage_a, both stated.
* **T-DRAW-2 (Rev-8 new — startup transition):**
  `test_solar_follow_startup_transition_re_splits_next_tick`.
  Tick 1 fixture as T-DRAW-1: garage_a DRAWING (5 kW), garage_b idle. Assert garage_a=41,
  garage_b=6 (safe-parking).
  Tick 2 fixture: garage_b transitions to DRAWING (`charging=True, power=1440` — pre-
  written 6 A × 240 V now flowing because the operator plugged in mid-window). `grid_W =
  -3560` (surplus dropped by garage_b's 1.44 kW). Rev-8 expected: ELIGIBLE={a,b},
  DRAWING={a,b}, N_drawing=2, add_back=5000+1440=6440, S_eligible=3560+6440=10000,
  A_total=41, A_per_drawing=20. garage_a commanded 20, garage_b commanded 20 (with the
  down-step logic for garage_a — from 41 to 20 — uncapped one-tick per INV-SF-5, so 20
  fires immediately; and up-step for garage_b — from 6 to 20 — gated by
  `UP_MIN_TICKS=3`, so garage_b commanded 8 A on tick 2 with the streak counter at 1).
  Assert: garage_a=20, garage_b=8, streak counters correct. **Under bug (safe-parking
  skipped in tick 1)**: garage_b was at 48 A pre-write, plug-in draws 11.5 kW, S_eligible
  computation on tick 2 sees `-grid_W - 11.5 kW - 5 kW` = way negative; the physical
  yo-yo the cycle prevents fires. Test observable: garage_b's fixture `power=11500` on
  tick 2 instead of 1440. Different observation.
* **T-DRAW-3 (Rev-8 new — degenerate all-idle):**
  `test_solar_follow_all_idle_commands_min_safe_parking`.
  Fixture: garage_a and garage_b both in `_excess_solar_active`, both
  `charging=False, power=0`, `grid_W = -10000`. Rev-8 expected: ELIGIBLE={a,b},
  DRAWING={}, N_drawing=0, N_denom=1 (max(1,0)). No DRAWING to allocate to; both bays
  receive MIN safe-parking. Assert both commanded 6 A; `drawing_evses=[]`;
  `safe_parked_evses=["garage_a", "garage_b"]`; no divide-by-zero crash. **Under bug
  (N_denom = N_drawing = 0)**: `ZeroDivisionError`.
* **Mutation C20 (Rev-8 new):** revert D1's step-8 denominator from `N_denom =
  max(1, N_drawing)` to `N_denom = len(ELIGIBLE)` (the Rev-5 behaviour) → **T-DRAW-1
  must fail** (garage_a commanded 20 A instead of 41 A).
* **Mutation C20b (Rev-8 new):** skip the safe-parking write in step 9b (change
  `else: A_target = MIN` to `else: continue`) → **T-DRAW-2 must fail** (garage_b's
  tick-2 `power` fixture models the 48 A physical draw of an un-parked bay).
* **Mutation C20c (Rev-8 new):** replace `N_denom = max(1, N_drawing)` with `N_denom =
  N_drawing` (drop the divide-by-zero guard) → **T-DRAW-3 must fail** (crash).

### D2 — Release-gate hysteresis only

(Unchanged from Rev-6.)

### D3 — DP drain-target mis-sourcing fix (FIVE R2 sites)

(Unchanged from Rev-3.)

---

## 4. Non-goals (explicit)

(Unchanged Rev-6/7 list. Rev-8 does not change or add non-goals — the DRAWING vs ELIGIBLE
distinction is a design refinement, not a scope expansion.)

Explicit note: NOT hooking into HA's device-registry or Emporia's plug-detection API to
detect vehicle presence directly. The `charging = power > 100 W` proxy is sufficient
because (a) an unplugged bay draws ≈0 W with a closed relay, so the proxy is a reliable
tri-state (empty/plugged-idle/drawing collapses to empty/drawing for D1's purposes —
plugged-idle-at-<100 W is not a real state on an EVSE that either draws at pilot floor
6 A × 240 V = 1.44 kW or draws nothing), (b) adding a plug-detection API dependency
would expand the cycle's coupling surface for no measurable benefit.

---

## 5. Known couplings

(Rev-6/7 items 1-12 unchanged.)

13. **Empty-bay dilutes allocation denominator (Rev-8 close).** `_excess_solar_active.add`
    (`energy_pool.py:1656`) happens on switch-on without a plug check; an empty bay is
    ELIGIBLE but not DRAWING. D1's DRAWING subset (Rev-8) is what the allocation
    denominator uses; safe-parking MIN command caps the plug-in transient. Distinct
    failure class from Rev-5's `power_source == "sensor"` gate (that filters FABRICATED
    power inflating the numerator; this filters ZERO power inflating the denominator).

---

## 6. Docs drift to fix in-cycle

(Unchanged from Rev-6.)

---

## 7. Test plan summary

Rev-7 D1 list preserved plus Rev-8 additions:

D1: [Rev-5..Rev-7 tests unchanged] + **T-DRAW-1**
`test_solar_follow_full_surplus_to_single_drawing_bay_when_other_bay_idle`;
**T-DRAW-2** `test_solar_follow_startup_transition_re_splits_next_tick`;
**T-DRAW-3** `test_solar_follow_all_idle_commands_min_safe_parking`.

Fixture updates:
- `test_solar_follow_two_evses_split_surplus`: BOTH bays `charging=True, power > 100 W`.
- **T-PEER-5** oracle: garage_b commanded 6 A (MIN safe-parking), not 8 A. Docstring
  notes this preserves discrimination against Rev-3 fleet-wide bug (39 A) and adds
  discrimination against Rev-5 ELIGIBLE-only-denominator behaviour (8 A).

D2/D3 unchanged.

---

## 8. Review plan — Tier 3, four framing-disjoint passes

* **A — local correctness.** ELIGIBLE-scoped writes + DRAWING-scoped allocation +
  DRAWING-scoped add-back; step 2a/2b/2c convention; N5 snapshot; unit conversions;
  Rev-7 STEP 0 edge-detector rules; **Rev-8: max(1, N_drawing) divide-by-zero guard;
  safe-parking command routing to ELIGIBLE \ DRAWING.**
* **B — integration / state-machine + byte-identical no-op.** Class shape; SLF001;
  R1/R3 grep-diff clean; restart paths; must-start-release corner;
  `determine_battery_drain_actions:1776-1959` byte-identical (Rev-6/7);
  `solar_replenishing` path byte-identical (Rev-6). **Rev-8: verify that the DRAWING
  subset construction inside D1 does NOT reach into `energy_pool.py:1650-1656` (the
  excess-solar CLAIM path) — the whole DRAWING derivation lives inside D1 via
  `_get_evse_state` reads.**
* **C — REAL per-site source mutation.** C1..C19b as Rev-5..Rev-7. **Rev-8 additions:**
  - **C20:** revert D1's `N_denom = max(1, N_drawing)` to `N_denom = len(ELIGIBLE)` (Rev-5
    behaviour) → **T-DRAW-1 must fail** (garage_a commanded 20 A instead of 41 A).
  - **C20b:** change step 9b's non-DRAWING branch from `A_target = MIN` to `continue` (no
    write) → **T-DRAW-2 must fail** (plug-in transient uncapped in tick 2).
  - **C20c:** replace `max(1, N_drawing)` with `N_drawing` (drop divide-by-zero guard) →
    **T-DRAW-3 must fail** (crash).
* **D — adversarial completeness / diff-blind.** All Rev-6/7 tasks unchanged. **Rev-8
  additional D task: enumerate every code path that adds to `_excess_solar_active` and
  confirm none of them establish plug presence (this is the source of the "empty bay is
  ELIGIBLE" fact D1 has to cope with — future work adding a plug-check at the CLAIM path
  is a separate cycle and would let D1 collapse ELIGIBLE = DRAWING).**

**Orchestrator pre-deploy verification:** Rev-6/7 grep set unchanged. **Rev-8 adds:**
grep-check that D1's step 8 uses `max(1, N_drawing)` (not `len(ELIGIBLE)` and not bare
`N_drawing`); grep-check that D1's step 9b has an `else: A_target = SOLAR_FOLLOW_MIN_AMPS`
branch (not `else: continue`). Operator checkpoint BEFORE deploy.

---

## 9. REUSE vs NEW

(Rev-6/7 rows unchanged. Rev-8 additions in **bold**.)

| Item | Verdict | Cite |
|---|---|---|
| ...(all Rev-6/7 rows preserved)... | | |
| **`_get_evse_state(...).charging` field as the DRAWING predicate (Rev-8)** | REUSE | `energy_pool.py:691` (`charging = power > EVSE_CHARGING_POWER_THRESHOLD`) |
| **DRAWING subset derivation inside D1 (Rev-8)** | NEW (inline in step 5) | Zero edits to `_excess_solar_active` claim path at `energy_pool.py:1650-1656` |
| **`max(1, N_drawing)` divide-by-zero guard for degenerate all-idle case (Rev-8)** | NEW (inline in step 6) | — |
| **Safe-parking MIN command for ELIGIBLE \ DRAWING (Rev-8)** | NEW (inline in step 9b) | Caps plug-in transient at 1.44 kW/bay for ≤60 s per INV-SF-4 within-window clause |
| **`drawing_evses` + `safe_parked_evses` status attributes (Rev-8)** | NEW (D1.8) | Observability for the DRAWING/ELIGIBLE distinction |

**Note on why the fix lives entirely inside D1 (Rev-8):** the operator's defect is
CONSUMED by D1 (denominator inflation) but ORIGINATES at the excess-solar CLAIM path in
`determine_excess_solar_actions:1650-1656` (which turns switches on without a plug check).
Fixing the CLAIM path (add a plug-presence check before adding to `_excess_solar_active`)
would collapse D1's ELIGIBLE = DRAWING and remove the need for safe-parking commands.
That is a different cycle — it changes the meaning of `_excess_solar_active` and would
ripple through every consumer of that set. Rev-8 fixes the consumer (D1) only; the
producer stays untouched (`energy_pool.py:1650-1656` byte-identical), matching Rev-6's
posture toward `determine_battery_drain_actions`.

---

## 10. Design pushback recorded

(Rev-6 PB-1 REJECTED, Rev-7 addendum unchanged. No Rev-8 changes.)

---

## 11. Parked P-items disposition

(Unchanged.)

---

## 12. Change log

Rev-1→Rev-2: 14 items.
Rev-2→Rev-3: pause-owner precedence BLOCKING; P8 upgrade; P6 ADOPT.
Rev-3→Rev-4: SF7-B1/B2 BLOCKING; SF7-H1/H2 HIGH; SF7-M1 MED; SF7-L1/L2 LOW; Q5 LOW.
Rev-4→Rev-5: BLOCKING-1/2/3; N1-N5; §13 register created.
Rev-5→Rev-6: PB-1 REJECTED with evidence; `determine_battery_drain_actions` byte-identical;
`solar_replenishing` LEAVE-ALONE; strategy-vs-safety-gate generalisation.
Rev-6→Rev-7: counter wire-point moved OUT (edge-detector in D1 STEP 0); three edge-detector
footguns; T-DRAIN-3/4; C19 re-targeted, C19b added.

**Rev-7→Rev-8:**

| Finding | Severity | Change |
|---|---|---|
| **Operator-verified: an idle or unplugged bay dilutes `N_eligible`, halving the allocation to the drawing car — 50% under-use on the ordinary two-charger install** | BLOCKING (operator-flagged) | INV-SF-4 restated to distinguish DRAWING from ELIGIBLE (add-back over DRAWING; commanded-amp bound on DRAWING with within-window clause covering plug-in transient). INV-SF-6 restated with `N_denom = max(1, N_drawing)`. Control law step 5 gains DRAWING subset construction; step 6 uses N_denom; step 8 uses N_denom; step 9b routes non-DRAWING ELIGIBLE bays to MIN safe-parking command. Four Rev-8 footguns pinned. Three new tests T-DRAW-1/2/3 (empty-bay full-surplus, startup transition, all-idle degenerate). Three new mutation drills C20/b/c. `drawing_evses` + `safe_parked_evses` status attributes for observability. T-PEER-5 oracle updated (garage_b commanded 6 A safe-parking under new degenerate case; docstring notes discrimination preservation). Fixture update on `test_solar_follow_two_evses_split_surplus` (both bays DRAWING). §5 known couplings item 13 added. §13 register gains new row. Chicken-and-egg trap explicitly avoided by the two-predicate separation (ELIGIBLE = commandable; DRAWING = counts toward denominator + add-back). |
| One-tick lag on startup transition | Correction | Explicit statement in D1: ≤60 s, self-corrects, pre-written MIN command caps plug-in transient at 1.44 kW/bay (not 11.5 kW), errs toward under-draw (INV-SF-4 permits). |
| Producer-side fix explicitly OUT OF SCOPE (Rev-8) | Correction | §9 note explains why D1 fixes the consumer, not the CLAIM path — matches Rev-6's byte-identical posture toward `determine_battery_drain_actions`. |

---

## 13. Closed concerns — must stay closed

(Rev-6/7 rows preserved.)

| Concern | Round originally closed | The one-line invariant that keeps it shut |
|---|---|---|
| ...(all prior rows unchanged)... | | |
| **An idle or unplugged bay dilutes the allocation denominator** | **Rev-8 (operator-flagged)** | Allocation denominator uses `N_denom = max(1, N_drawing)`, NOT `len(ELIGIBLE)`. DRAWING ⊆ ELIGIBLE is derived inside D1's step 5 from `_get_evse_state(evse_id).charging`. Non-DRAWING ELIGIBLE bays receive MIN safe-parking to cap plug-in transient. C20 re-verts denominator to `len(ELIGIBLE)` → T-DRAW-1 must fail. C20b skips safe-parking → T-DRAW-2 must fail. C20c drops divide-by-zero guard → T-DRAW-3 must fail. Future-revision grep-check: any code touching D1's step-8 denominator or step-9b routing trips this row. The CLAIM path at `energy_pool.py:1650-1656` (which lets an empty bay into `_excess_solar_active` without a plug check) is BYTE-IDENTICAL post-cycle — Rev-8 fixes the consumer, not the producer. Rule generalizes: when a producer emits a set with mixed semantic content, the consumer distinguishes by attribute rather than filtering the producer, unless the producer's set has only one consumer. |

---

## 14. Cycle-close checklist

(Rev-6/7 items preserved. Rev-8 additions in **bold**.)

* [ ] Targeted re-review of Rev-8 DRAWING/ELIGIBLE split (coordinator-scoped).
* [ ] Build in one branch off `develop`.
* [ ] Suite green + baseline-diff clean.
* [ ] Four framing-disjoint reviews A/B/C/D returned; CRITICAL/HIGH fixed.
* [ ] Orchestrator pre-deploy: re-grep five R2 sites; six peer-hold owner sets +
      `_paused_by_dp`; run mutation drills C17/b/c/d/e/f + C18 + C19 + C19b +
      **C20 + C20b + C20c**; zero-call-sites confirmation against
      `current_charging_load_w()` and bare `EVSE_ESTIMATED_POWER_W` inside
      `SolarFollowController`; grep-check `determine_battery_drain_actions` ZERO diff;
      grep-check `_drain_trips_during_follow` increment site occurs exactly ONCE inside
      `SolarFollowController.STEP 0`; grep-check `solar_replenishing` ZERO diff;
      **grep-check D1's step 8 uses `max(1, N_drawing)` (not `len(ELIGIBLE)`, not bare
      `N_drawing`); grep-check D1's step 9b has an `else: A_target = SOLAR_FOLLOW_MIN_AMPS`
      branch (not `else: continue`); grep-check the excess-solar CLAIM path at
      `energy_pool.py:1650-1656` is BYTE-IDENTICAL (producer untouched)**; diff-check
      against §13 register.
* [ ] Operator checkpoint before deploy.
* [ ] `README_v<version>.md` with prospective Live criteria.
* [ ] Deploy via `./scripts/deploy.sh`.
* [ ] Live validation: sunny-day D1 attributes including `s_eligible_kw`, `stale_ticks`,
      `excluded_switch_status_evses`, `drain_trips_during_follow`, **`drawing_evses`,
      `safe_parked_evses`**; **one-bay-active case (garage_a drawing, garage_b idle):
      garage_a commanded near-full-surplus per INV-SF-6, garage_b commanded 6 A safe-
      parking; `drawing_evses=["garage_a"]`, `safe_parked_evses=["garage_b"]`**;
      release-edge restore; D3 DP snapshot with plugged EV; A-CRIT-1/A-CRIT-2 direct;
      INV-SF-7 if arbitrage overlap; BLOCKING-1 live confirmation if Emporia cloud blip;
      drain-trip counter per-event increments;
      **Rev-8: if garage_b starts being used mid-session, next-tick allocation re-splits
      (`drawing_evses` grows to include garage_b, `safe_parked_evses` shrinks); plug-in
      transient bounded at 1.44 kW/bay for the ≤60 s lag.**
* [ ] README updated with observed `Validated <date>` table.
* [ ] Kanban cards shipped_organic; parked `project_ev_drain_precedence_cycle` retained.
* [ ] Post-ship supersession + consumer-gap audit per CLAUDE.md rule.
