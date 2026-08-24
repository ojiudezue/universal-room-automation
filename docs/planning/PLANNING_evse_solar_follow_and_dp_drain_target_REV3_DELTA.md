# PLANNING Rev-3 DELTA — pause-owner precedence, P8 upgrade, P6 adoption

**Base plan:** `PLANNING_evse_solar_follow_and_dp_drain_target.md` (Rev-2 passed a third plan
review with DISPATCH BUILD). This delta is applied ON TOP of Rev-2 and supersedes only the
sections it names. Everything Rev-2 settled remains — this is not a re-litigation.

**Scope of Rev-3:** three items surfaced by the coordinator's post-review P-item read that all
three plan reviews missed because they were pointed at Rev-1 fixes, not P8's surface.

---

## Rev-3 §A — BLOCKING FIX: solar-follow must consult the pause-owner precedence system

### A.1 The defect (independently verified against source)

`domain_coordinators/energy_pool.py:383-412` — `_stronger_peer_holds(evse_id)` is the shared
chokepoint arbitrating five peer owners (`_paused_by_battery_drain`, `_paused_by_fill_priority`,
`_paused_by_grid_cap`, `_paused_by_arbitrage`, `_paused_by_load_shed`; `_paused_by_blind_window`
also carried via `EV_REGISTRY.iter_peer_holds()` after the Phase-2 refactor). The docstring
states verbatim that these owners **"outrank BOTH the TOU ensure-on proactive-turn-on path AND
the excess-solar claim path"**. `_paused_by_dp` is intentionally EXCLUDED from the helper and
must be consulted inline at each caller with its own semantics (docstring `:394-400`).

Rev-2 mentions the pause machinery exactly once (in a non-goal about `_paused_by_dp`). Nowhere
does D1 consult `_stronger_peer_holds()` before writing amps or capturing `_original_amps`. That
is a real reachable defect.

**Concrete legal-config repro (arbitrage CHARGE-phase mutual exclusion, live v4.5.0 D4):**

1. Arbitrage's CHARGE phase fires (`PLANNING_v4.5.0_TRANSITION_NOTES.md:60`); it pauses active
   EVSEs by adding them to `_paused_by_arbitrage`.
2. Same tick or shortly after, excess-solar conditions are still true → the EVSE remains in
   `_excess_solar_active` (arbitrage does not clear excess-solar membership; different owner sets).
3. `SolarFollowController` 60-s tick fires. Under Rev-2's control law, it iterates
   `_excess_solar_active`, reads the current-limit entity (which reports whatever the paused
   charger last held — a perfectly legal amperage), stores it as `_original_amps`, then writes a
   modulated limit.

**Two harms, both real:**

- Solar-follow acts on a device a stronger owner has claimed (violates the docstring's own
  precedence rule).
- `_original_amps` is laminated to the value read off the paused charger. This is A-HIGH-3's
  failure shape through a different door — `SOLAR_FOLLOW_CAPTURE_SANITY_A=20A` does NOT catch it
  because the value read from a paused charger is a normal amperage (it's the last commanded
  value; nothing about "paused" implies "low"). Restore on eventual excess-solar release then
  writes back the wrong "original."

**Note the symmetry with the existing design:** fill-priority already consults exactly this same
guard (this is the prior art PB-1 leans on for D2's drain-protection skip). Excess-solar's
`_stronger_peer_holds` check happens at the CLAIM path (`energy_pool.py:1598-1607`). D1 rides
membership *inside* an already-claimed session and inherits nothing about ongoing peer holds —
those can arise mid-session (e.g. arbitrage CHARGE firing after excess-solar claimed the EVSE).

### A.2 New invariant (falsifiable)

**INV-SF-7 (stronger-peer subordination).** Under any config and any tick, while
`_stronger_peer_holds(evse_id) is True` OR `evse_id in self._paused_by_dp`,
`SolarFollowController` performs NO write to `evse_id`'s current-limit entity AND NO capture of
`_original_amps[evse_id]`, on any reachable path. This holds regardless of
`_excess_solar_active` membership.

Reason `_paused_by_dp` is checked INLINE, not folded into the helper: the same two-site
convention `_stronger_peer_holds`'s docstring documents (TOU adds it inline; excess-solar treats
it as conditionally yieldable via INV-YIELD-1). Solar-follow's rule is stricter than TOU's
because it is a WRITER, not a switch actuator — for D1's purposes, DP-held is always "hands off."

### A.3 Rev-3 control-law patch (supersedes Rev-2 §3.D1 step 8 sub-steps)

Add a peer-hold guard at the head of the per-EVSE loop AND before capture:

```
# Per-tick control law, Rev-3 (deltas to Rev-2 in **bold**)
1. If _excess_solar_active empty AND _original_amps empty: return.
2. For each evse_id with _original_amps set but NOT in _excess_solar_active:
     **a. If _stronger_peer_holds(evse_id) or evse_id in _paused_by_dp:
          DEFER restore this tick (do not clear _original_amps).
          Rationale: a stronger owner is actively controlling. Restoring 48 A
          under them contradicts precedence and may fight their intent.
          Restore fires on the NEXT tick after both membership sets clear.**
     b. Else: emit ONE number.set_value(_original_amps[evse_id]); clear entry.
3. If _excess_solar_active empty: return.
4. Read surplus S. If unavailable for STALE_MAX_TICKS: no writes.
5. Build ELIGIBLE = {evse_id in _excess_solar_active where NOT
   _stronger_peer_holds(evse_id) AND evse_id not in _paused_by_dp}.
   **If ELIGIBLE empty: no writes and no captures this tick (INV-SF-7).**
6. N = len(ELIGIBLE).  (NOT len(_excess_solar_active) — fleet allocation
   is over eligible EVSEs only, else B-3 recurs at fleet level.)
7. A_total_target = floor(S * 1000 / (240 * PHASES)).
8. A_per_evse_raw = A_total_target // N.
9. For each evse_id in ELIGIBLE:
     a. Capture _original_amps[evse_id] per Rev-2 fix 6 if unset.
     b..h. (unchanged from Rev-2)
```

**Two design decisions stated explicitly (per coordinator ask):**

- **On pause ENTRY while modulated** — a stronger peer starts holding an EVSE that is currently
  in a solar-follow session at, say, 14 A. **Decision: LEAVE `_original_amps` in place, do NOT
  restore before yielding.** Rationale: (1) restoring 48 A under a stronger owner (arbitrage,
  grid-cap, load-shed) risks fighting them — arbitrage CHARGE explicitly pauses to bound
  compound load; a restore-then-yield would blip the pilot to 48 A momentarily. (2) The stronger
  owner has turned the SWITCH off; the current-limit value on the (now off) charger is
  cosmetic until the switch re-closes. (3) When the stronger owner releases, either
  excess-solar is still active and D1 continues modulating from the last saved `_original_amps`
  (correct), or excess-solar is no longer active and step 2 fires the restore on the NEXT tick
  (correct).
- **On pause RELEASE** — stronger peer clears (`_paused_by_arbitrage.discard(evse_id)`, etc.).
  Two sub-cases:
  - EVSE still in `_excess_solar_active`: next D1 tick (≤60 s later) resumes modulation. There
    is no explicit re-arm signal from D1 — it discovers the eligibility change by re-reading
    `_stronger_peer_holds` each tick. The ≤60 s window matches Rev-2's PB-2 resolution.
  - EVSE no longer in `_excess_solar_active`: step 2 fires restore on the NEXT tick.

**One-line rationale for not adding a signal:** subscribing to owner-set change events would
couple D1 into `energy_pool.py` mutation sites, expand blast radius, and re-introduce the exact
bootstrap-observer problem B-5 rejected. The 60-s discovery latency is the same class as the
Rev-2 PB-2 window and is bounded.

### A.4 Files changed by Rev-3 §A

- `domain_coordinators/energy_pool.py` — `SolarFollowController` gains the ELIGIBLE-set
  computation at every write and capture path (~10 LoC delta from Rev-2 spec).
- No changes to `_stronger_peer_holds` itself — Rev-3 consumes the existing helper unchanged.
  Adding `dp` to the shared helper is explicitly rejected per the docstring's two-site
  convention.
- No changes to `EV_REGISTRY` / `energy_pool_owners.py`.

### A.5 Acceptance criteria for INV-SF-7 (discriminating, mutation-anchored)

* **T-PEER-1:** put EVSE in both `_excess_solar_active` AND `_paused_by_arbitrage`. Run one D1
  tick. Assert zero `number.set_value` writes AND `_original_amps` remains unset. Under the bug
  (Rev-2 as-written), one write + one capture fire. Different observation.
* **T-PEER-2:** put EVSE in `_excess_solar_active`, then MID-SESSION add it to
  `_paused_by_grid_cap`. Tick 1: modulation fires and captures original amps. Tick 2 (after
  grid-cap add): assert no write, `_original_amps` PRESERVED (not cleared, not overwritten).
  Under bug, tick 2 overwrites capture with paused-charger reading.
* **T-PEER-3 (DP inline check):** put EVSE in `_excess_solar_active` AND `_paused_by_dp` with
  `_dp_carrier.state == HOLD_ONLY` (the INV-YIELD-1 yieldable case). Assert D1 still writes
  NOTHING to the EVSE. INV-SF-7 is stricter than INV-YIELD-1 by design (D1 is a WRITER, not
  the excess-solar claim path).
* **T-PEER-4 (release-edge restore deferred under peer hold):** save `_original_amps={"garage_a":
  32}`, drop garage_a from `_excess_solar_active`, add garage_a to `_paused_by_load_shed`. Tick:
  no restore write, `_original_amps` retained. Remove from `_paused_by_load_shed`. Next tick:
  restore fires. Under bug (unconditional restore), the restore fires under the load-shed pause.
* **T-PEER-5 (fleet allocation over ELIGIBLE, not membership):** garage_a and garage_b both in
  `_excess_solar_active`; garage_a additionally in `_paused_by_arbitrage`. S=5 kW. Assert
  garage_b commanded to 20 A (full 5 kW share, since N_eligible=1), garage_a untouched. Under
  bug (fleet over full set), each gets 10 A → garage_b at 2.4 kW leaves ~2.6 kW on the table
  while arbitrage is charging the battery anyway (double-benefit failure — not harmful but
  suboptimal). Also verify garage_a `_original_amps` remains unset.
* **Mutation drill (Review C new axis C17):** neuter the ELIGIBLE-set computation to
  `ELIGIBLE = _excess_solar_active`; T-PEER-1/2/3/4/5 must fail.
* **Live:** during the first sunny day with arbitrage CHARGE firing (rare — requires the
  tomorrow-poor arbitrage plan to overlap solar excess), sensor attribute
  `solar_follow.eligible_evses` shows arbitrage-held EVSE excluded; sensor attribute
  `solar_follow.deferred_restores` counts release-edge restores held pending peer release. Both
  ARE new observability attributes on the D1 status sensor.

### A.6 Review D adversarial task (new)

Re-enumerate ALL sites that mutate any of the 6 peer-hold owner sets and confirm each site
either (a) does not need to signal D1 (D1 re-reads eligibility each tick) or (b) does signal D1
if a change to that policy is made later. Also enumerate any code path where a WRITE to a
current-limit entity outside D1 could exist (currently none — audit §1 row 11 verified). If any
future writer is added, INV-SF-7's peer-hold semantics must be added to it (documented as a
design fence for future work).

---

## Rev-3 §B — P8 disposition UPGRADE + compound-load coupling with existing D4

Rev-2 §11 marked P8 as REJECT-WITH-EVIDENCE with a placeholder rationale. Rev-3 has the actual
evidence.

### B.1 P8's rejection premise, verbatim

`PLANNING_v4.5.0_TRANSITION_NOTES.md:50-56`:

> **Mistake 4: "D4 = Saw-tooth charge rate cap"** … **Why it was wrong: Two reasons, both
> fatal.** *(1) It would flap.* Enphase's `charge_from_grid` is a binary switch (no rate
> control). When ON, battery pulls at hardware rate ~20 kW. When OFF, ~0 kW. Saw-tooth
> threshold sits between these two states; **hysteresis can't bridge them** — system toggles
> every 5-min decision tick.

### B.2 Why P8's premise does NOT apply to this cycle

The premise is a HARDWARE constraint on the Enphase `charge_from_grid` switch: it is binary; a
hysteresis band placed between two non-existent intermediate states cannot bridge them; the
saw-tooth flaps every tick. That is correct for that actuator.

The Emporia EVSE `current_limit` number entity is **continuous 6-48 A step 1**
(`INSTITUTIONAL_CONTEXT_VERIFIED_2026_08_23` on the card: `min=6 max=48 step=1 unit=A`
verified live). D1's hysteresis band operates in a state space with 43 legal intermediate values
between the endpoints. There is no analogue of the "cannot bridge" failure — the band lives
inside the legal continuous range and reduces write cadence to exactly the class of "genuine
change vs measurement noise" it exists to distinguish.

P8's rejection is therefore load-bearing FOR THE ENPHASE SURFACE and does not transfer. Rev-3
records this as an explicit REJECT-WITH-EVIDENCE quotation, not a characterisation.

### B.3 P8's REPLACEMENT is D4 arbitrage/EV mutual exclusion — and it already covers the
    compound-load case D1 was NOT designed to solve

`PLANNING_v4.5.0_TRANSITION_NOTES.md:60`:

> **The right approach:** D4 became **arbitrage / EV mutual-exclusion**. The compound-load case
> (battery 20 kW + EV 7.4 kW + house base 5 kW = 134A on main breaker) is the real panel-stress
> scenario. Solo battery 20 kW is well within breaker capacity (~83A). Don't run arbitrage AND
> EV charging simultaneously: when arbitrage's CHARGE phase fires, pause active EVSEs via the
> existing pause-reason pattern.

**Operator ask on this cycle** (`OPEN_QUESTIONS_FOR_OPERATOR` / `SCOPE_FENCE`): draw ceilings,
demand overages, breaker trips — safety-capacity is a stated dimension of the D1 justification.

**The compound-load safety argument is already bounded by v4.5.0 D4**, which pauses EVSEs during
arbitrage CHARGE via `_paused_by_arbitrage`. Rev-3 §A now correctly subordinates D1 to that
pause. So D1 does NOT re-solve compound-load safety — the arbitrage path does. D1's remaining
job is narrowly:

- **Solar-matching benefit** (economics — do not drain the house battery to fill the car).
- **Service-capacity bound WITHIN a session** (INV-SF-4 caps total draw by measured surplus).

The 48 A ceiling per EVSE and the fleet-allocation cap (INV-SF-6) are the service-capacity
bounds WITHIN normal operation; the arbitrage mutex is the bound for the compound-load edge
case. Two mechanisms, disjoint surfaces, no duplication.

**Scope narrowing recorded:** if a plan reviewer or the operator was reading INV-SF-4 as "the
solar-follow controller IS the compound-load safety mechanism," Rev-3 explicitly disclaims that.
The compound-load mechanism lives in v4.5.0 D4. D1 is the solar-matching mechanism and cooperates
with D4 via §A's peer-hold subordination.

### B.4 P8 disposition — final

**REJECT-WITH-EVIDENCE**: the Enphase-binary premise (`PLANNING_v4.5.0_TRANSITION_NOTES.md:55`)
does not apply to the continuous 6-48 A EVSE current-limit surface. D1 is not a re-proposal of
P8's saw-tooth mechanism on a different actuator; it is amp modulation over a genuinely
continuous surface with a legal hysteresis band. **P8's replacement (v4.5.0 D4 mutex) already
bounds the compound-load case D1's INV-SF-4 was NOT designed to solve; Rev-3 §A subordinates D1
to D4 via peer-hold precedence.**

---

## Rev-3 §C — P6 disposition (flashg1/SolarCharger prior-art study)

Read `PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md:41`:

> **`flashg1/SolarCharger`** … documents … **anti-flap power-monitor duration thresholds**, and
> **per-load weighting/prioritization** — all relevant patterns for B5.

### C.1 Anti-flap power-monitor duration threshold

Direct prior art for D2's release-gate hysteresis (`SOLAR_RELEASE_MIN_TICKS`,
`SOLAR_RELEASE_MIN_ON_S`). The pattern is: do not react to instantaneous surplus dips; require
the dip to persist for a configured duration before acting. That is exactly D2's design. Rev-3
records ADOPTED-WITH-SHAPE-MATCH: no code delta needed — D2 already implements the pattern
under different names. The disposition upgrade is from "we happened to design this ourselves"
to "we deliberately match the shape of `flashg1/SolarCharger`'s field-tested anti-flap primitive
because it is the correct one."

### C.2 No-interference / manual-override mode

`flashg1/SolarCharger` supports a "no-interference" mode where manual user actions on the
charger are respected and the controller yields. D1 does not have a "manual override" concept
today. **Rev-3 clarification (adopt in spirit, not as new machinery):** the operator can turn
off `CONF_SOLAR_FOLLOW_ENABLED` (rung 3 Switch, already in Rev-2's knob table) as the coarse
kill switch. For finer control — "I manually set garage_a to 24 A and want D1 not to touch it"
— the manual write itself is captured by D1's `_original_amps` mechanism on the NEXT session
entry (Rev-2 fix 6). Between sessions there is no D1 write at all (INV-SF-2). Within a session,
D1 sees the operator's 24 A as `A_current`, computes its own `A_target`, and either respects it
(if within the deadband) or overrides it — that is by design; the operator's manual override is
a within-session policy question we defer.

**Explicit non-goal (Rev-3, folded into §4):** NOT building a per-EVSE "no-interference latch"
that suppresses D1 for the remainder of a session after a manual write is detected. The card's
scope fence puts D1 fully inside excess-solar sessions; the operator's within-session manual
override lives on the parked cycle for a `self_modulates`-style opt-out
(audit §2.2 references a similar dormant flag on the Emporia surface). Recorded, not built.

### C.3 Per-load weighting / prioritization

Not applicable to this cycle. Two identical L2 chargers; INV-SF-6 uses equal-split allocation
(explicit non-goal §4: no priority ordering). Recorded for the parked cycle that would add L1
support or a third EVSE.

### C.4 P6 disposition — final

**ADOPT (anti-flap shape-match; no code delta beyond what Rev-2 D2 already spec'd).** Recorded
for provenance so a future reviewer does not re-derive the same pattern without knowing there
is field-tested prior art. Manual-override latch and per-load weighting: recorded as parked
non-goals for this cycle.

---

## Rev-3 change log

| Item | Severity | Rev-3 change |
|---|---|---|
| Pause-owner precedence missed by D1 | **BLOCKING** | New INV-SF-7; control law patched with ELIGIBLE set; entry/release policy stated; peer-held EVSEs excluded from fleet allocation denominator; T-PEER-1..5 tests + mutation drill C17; new observability attributes; Review D re-enumeration task added |
| P8 disposition rationale placeholder | Correction | Verbatim quote of rejection premise; explicit non-transfer to continuous 6-48 A surface; compound-load explicitly ceded to v4.5.0 D4 mutex; scope narrowed |
| P6 not read | Correction | ADOPTED anti-flap shape-match with `flashg1/SolarCharger`; manual-override & priority weighting recorded as parked non-goals |
| P1, P5, P13 | No change | Coordinator: DEFER remains correct |

## Rev-3 supersession notes

- Rev-2 §3.D1 per-tick control law step 8 is superseded by Rev-3 §A.3 (the ELIGIBLE-set
  variant). Rev-2 fix 6 (capture guard) is retained UNCHANGED as the second line of defence
  against the throttle-capture hazard — INV-SF-7 handles the peer-hold case; A-HIGH-3's
  `SOLAR_FOLLOW_CAPTURE_SANITY_A` still handles the stale-restart case (a different door).
- Rev-2 §3.D1 D1.7 write-budget: unchanged. INV-SF-7 reduces writes; budget cap remains
  containment.
- Rev-2 §11 P-item table row for P8: superseded by Rev-3 §B.4.
- Rev-2 §11 P-item table row for P6: superseded by Rev-3 §C.4.
- Rev-2 §12 change log: extended by the Rev-3 change log above.
- Rev-2 §4 non-goals: extended with "NOT building a per-EVSE no-interference latch (parked)."
- Rev-2 §8 Review C axes: extended with C17 (INV-SF-7 mutation drill).

## Cycle-close checklist delta (Rev-3)

- [ ] Fourth plan review of Rev-3 §A specifically (INV-SF-7 is a new invariant on a live
      precedence surface; deserves its own framing-disjoint pass rather than folding it into
      the general Tier-3 A/B/C/D reviews).
- [ ] Orchestrator pre-deploy re-grep of the six peer-hold owner sets + `_paused_by_dp`;
      confirm ELIGIBLE computation runs before every D1 write and capture.
- [ ] Live validation: T-PEER-1/T-PEER-5 exercised on a real arbitrage CHARGE overlap if one
      occurs in the eval window (rare — the tomorrow-poor arbitrage plan is uncommon during
      the sunny days D1 runs); otherwise mutation-drill-only, with the deferred criterion
      recorded in the README.
