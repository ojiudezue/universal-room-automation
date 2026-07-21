# PLANNING — Sticky DP Pause Yields To Live Excess-Solar Claim

**Charter (operator, verbatim):** "High solar energy days should be squeezed for every joule."

**Not a regression fix.** The v5.15/BAEC precedence "sticky DP outranks
excess-solar" is correct-by-design for the ACTIVE transition case (battery
deliberately draining to a target). This cycle is a **design refinement**:
identify the sub-case where the safety rationale is absent-by-construction
and let the joules through.

---

## Motivating fixture — 2026-07-20, garage A

Observed shape (cite this as the acceptance replay):

- Garage A entered a Battery-Aware EV Charging (BAEC / drain-precedence)
  TRANSITIONED window overnight; carrier collapsed to HOLD_ONLY once the
  transition math cleared, but `_paused_by_dp` retained garage A because
  the sticky reversion (`energy.py::_apply_dp_reversion`) defers on any
  non-`off_peak` TOU period. The house entered mid_peak → the sticky-defer
  branch (`energy.py:4091-4097`, "TOU=%s, keeping DP claim (sticky)")
  keeps membership + the "dp" dispatch owner until 21:00 off_peak.
- Attribute observed live: `pause_reason_human = "drain-precedence
  transition (paused)"` on garage A into mid-afternoon.
- Battery hit 100%, excess-solar activated. In
  `energy_pool.py::determine_excess_solar_actions` the per-EVSE claim
  loop checks the stronger-owner set (`energy_pool.py:773-792`); the
  `_paused_by_dp` peer-check (line 786) causes garage A to be SKIPPED
  ("held by stronger pause reason — skipping"). Garage B (not in the
  DP set) was claimed and charged.
- Consequence: surplus PV that garage A's plugged car could have
  absorbed was exported. The two cars only diverge because of plug-in
  timing at the BAEC transition — code path is identical, only per-device
  set membership differs.

---

## Institutional context verified

**Files read end-to-end / in-range for scoping:**
- `custom_components/universal_room_automation/domain_coordinators/energy.py`
  DP surface — `_apply_dp_reversion` (4040-4127), `_apply_dp_must_start_release`
  (4129-4186), `_dp_decision_tick` + HOLD_ONLY orphan retry driver
  (3485-3653), `_apply_evse_battery_hold` (3656-...), the DP carrier state
  enum usages (`_DPState.HOLD_ONLY` / `TRANSITIONED` / `MUST_START_FORCED`),
  restore path (1420-1544, 1755-1772).
- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py`
  excess-solar claim (`determine_excess_solar_actions` 711-830), the TOU
  pause skip for excess-active (516-582), the fill-priority / drain / grid-cap
  peer-owner constellation, `pause_reason_human` derivation (1730-1770),
  restore blob field carriage for `_paused_by_dp` / `_excess_solar_active`
  (426-434).
- `docs/reviews/code-review/battery_aware_ev_charging_tier3.md` — the full
  BAEC Tier-3 ledger (CRIT-1/2, H-1..H-5, D2-H1/H2, D2-M1, D3-L1).
  Specifically the D2-H2 sticky rationale (docstring-claimed-parity-not-
  implemented lesson) and D2-H1 (orphan retry driver + KV persistence).

**Greps run + prior-art call-out for every proposed addition:**
- Proposed change surface: NO new constants, NO new sensors, NO new
  config-flow fields, NO new Number/Select/Switch. See "Numbers Get
  Knobs" below — the whole point is a condition-derived yield.
- Verified there is no existing "yield-excess" predicate:
  `grep -n "yield\|dp_yield\|excess.*dp\|dp.*excess" energy*.py` → the
  only excess/DP interaction site is the peer-owner skip at
  `energy_pool.py:786` (and its symmetric guard in the off_peak
  ensure-on branch called out at 583-585). NEW predicate justified —
  no equivalent gate exists.
- Verified `_DPState` enum members: HOLD_ONLY, TRANSITIONED,
  MUST_START_FORCED (used at `energy.py:3488, 3499, 3517, 3593, 3612,
  3628, 3639, 3642, 3647, 3650`). REUSED — we key the yield on
  existing state, no new state.
- Verified `_paused_by_dp` set + `_release_pause_dispatch_owner(evse_id,
  "dp")` ownership-drop primitive already exists (`energy.py:4104-4110,
  4165-4170`). REUSED — the yield uses the same handoff primitive that
  the sticky-reversion clean-release uses.

**Prior planning docs consulted (skim):** the BAEC family under
`docs/planning/` (drain-precedence build A / B1 / B2a / B2b-i..iii + the
c27df04c naming ratification memo). The relevant priors are the sticky
rationale (D2-H2) and the orphan retry driver (D2-H1); this doc extends
that machinery, does not replace it.

**Design doc:** DP-owner precedence lives in the BAEC Tier-3 review record
above; no `docs/Coordinator/EnergyPool.md` yield section exists yet — this
doc becomes the authoritative record.

---

## Refinement (the falsifiable core)

**Invariant pair the cycle MUST guarantee (state up front for D framing):**

- **INV-YIELD-1 (permissive, opportunity):** An EVSE whose DP pause is
  **deferred-reversion-only** — i.e. `_dp_carrier.state == HOLD_ONLY`
  AND `evse_id in _paused_by_dp` — is claimable by excess-solar whenever
  excess conditions hold (`SOC >= excess_solar_soc AND remaining_forecast
  >= excess_solar_kwh_threshold AND tou_period != "peak"`). No config
  combination may prevent the claim.
- **INV-YIELD-2 (restrictive, safety, LOAD-BEARING):** An EVSE paused
  by an **ACTIVE** DP transition — i.e. `_dp_carrier.state IN
  {TRANSITIONED, MUST_START_FORCED}` — is NEVER released by excess-solar,
  under any config, TOU period, SOC value, or forecast. This is the
  distinction that preserves the BAEC design: draining the house battery
  to a target so the car can charge off-peak MUST NOT be short-circuited
  by a mid-drain solar spike (the spike would collapse the very reserve
  the drain was engineered to build).

Falsification framing for the D reviewer: find any legal config +
runtime state where INV-YIELD-2 breaks, OR where INV-YIELD-1 fails to
fire when its predicate holds.

---

## (a) Placement decision + rationale

**Two candidate sites analyzed.**

**Option A — sticky-defer branch of `_apply_dp_reversion`
(`energy.py:4091-4097`).** Add "excess conditions hold" as a
release-permitting disjunct alongside `tou_period == "off_peak"`, so the
sticky loop cleanly releases at the reversion tick instead of deferring.

- Pro: the release goes through the existing sticky-clean-release
  machinery (owner drop + dispatch + floor collapse are already correct).
- Con (blocking): forces `_apply_dp_reversion` and its symmetric partner
  `_apply_dp_must_start_release` to import excess-solar conditions
  (SOC/forecast/threshold) — a **reverse dependency**: DP reversion
  should know DP; excess-solar should know excess. Fragments the yield
  logic across two DP release paths.
- Con: INV-YIELD-2 guard (only when HOLD_ONLY) becomes a negated
  precondition threaded through both DP paths; must-start-release must
  learn to NOT yield even though it too walks `_paused_by_dp`. Easy to
  regress.
- Con: the yield fires only on reversion ticks, not the moment
  excess-solar decides. Extra latency; a plugged car with a green
  claim waits for the next DP decision cycle.

**Option B — excess-solar claim path (`energy_pool.py:786`,
`determine_excess_solar_actions`).** Replace the flat
`evse_id in self._paused_by_dp` skip with a state-aware guard:
`in _paused_by_dp AND dp_carrier.state != HOLD_ONLY`. When the
condition allows the claim, execute the ownership handoff at the
claim site (discard from `_paused_by_dp`, release the "dp" dispatch
owner, add to `_excess_solar_active`, dispatch `switch.turn_on` —
mirrors the existing `_paused_by_us` TOU-claim path already at
lines 793-815).

- Pro: ownership direction is correct — excess-solar owns "when may I
  claim", DP owns "am I in an active transition".
- Pro: the yield fires the moment excess-solar decides (no wait for
  a DP tick); the sticky-defer loop simply finds an empty set on its
  next pass and collapses the floor cleanly via the existing
  `if not self._ev._paused_by_dp: self._dp_decision_soc = None`
  branch at `energy.py:4126-4127`.
- Pro: INV-YIELD-2 is one predicate at one site — trivially
  falsifiable, trivially reviewable. `MUST_START_FORCED` is protected
  by the same guard (state != HOLD_ONLY).
- Pro: the atomic ownership handoff (discard `_paused_by_dp` + release
  "dp" owner + add `_excess_solar_active` + dispatch) happens in one
  transaction — cannot orphan (addresses the D2-H1 stranded-pause
  history).
- Con: excess-solar path grows one branch of DP awareness. Contained,
  named, one site.

**Verdict: Option B.** Placement at the excess-solar claim site. The
load-bearing guard `dp_carrier.state == HOLD_ONLY` lives with the
claim, in one predicate, and the ownership handoff is atomic at the
claim. Option A was rejected primarily on the reverse-dependency /
fragmentation grounds — the same reason `_apply_dp_reversion` was kept
DP-only during BAEC Tier-3 (D2-H2).

---

## (c) Ownership handoff mechanics

**Claim (excess-solar wins):**

1. Predicate holds: excess conditions met, `evse_id in _paused_by_dp`,
   `_dp_carrier.state == HOLD_ONLY`, EVSE not in any strictly-stronger
   peer set (drain / fill_priority / grid_cap / load_shed — kept as-is;
   these outrank both DP and excess-solar).
2. **Atomic handoff (single tick, no await between steps):**
   - `self._paused_by_dp.discard(evse_id)`
   - `self._release_pause_dispatch_owner(evse_id, "dp")` (existing primitive)
   - `self._excess_solar_active.add(evse_id)`
   - If `not state["is_on"]`: append `switch.turn_on` action.
3. **Floor collapse:** happens naturally on the next DP tick — when
   `_apply_dp_reversion` (or `_dp_maybe_tick`) sees `not _paused_by_dp`
   it clears `_dp_decision_soc`. If garage A was the last sticky member,
   the composed reserve floor drops on the next cycle. If a second EVSE
   is still deferred-sticky, the floor stays pinned (INV-DP3 preserved).
4. **KV persistence:** the existing `evse_dp_paused` KV write
   (`energy.py:1544, 1772`) captures the mutated `_paused_by_dp` set on
   the next persistence tick. Restart mid-yield is safe: on restore, if
   garage A is in `_excess_solar_active` (persisted at
   `energy_pool.py:426`) it will be re-evaluated by
   `determine_excess_solar_actions` on the first post-restart tick;
   if conditions no longer hold, the existing off-conditions branch
   (`energy_pool.py:816-830`) turns it off cleanly. Garage A is NOT
   in `_paused_by_dp` post-yield, so the HOLD_ONLY orphan retry driver
   at `energy.py:3517-3520` does not fire against it (correct — DP no
   longer owns it).

**Un-claim (excess conditions fall away, non-peak):**

- Existing off-conditions branch turns off, discards from
  `_excess_solar_active`. Garage A returns to its stopped-EVSE resting
  state. It does NOT re-enter `_paused_by_dp` (the DP transition
  already completed; carrier is HOLD_ONLY; there is nothing to hold).

**Un-claim (peak arrives while yielded):**

- Existing peak branch (`energy_pool.py:727-746`) turns off and
  discards from `_excess_solar_active`. Same ending — HOLD_ONLY with
  empty `_paused_by_dp` membership. Correct: peak, plus DP no longer
  owns the car.

**No ownerless gap.** At every point between step 2 sub-steps there is
either a "dp" owner (before) or an `_excess_solar_active` claim (after);
because the four mutations happen in one synchronous block before the
next `await` (dispatch is fire-and-forget via `hass.services.async_call`
+ actions list; no yield between set mutations), no concurrent tick
observes a bare EVSE. This mirrors the atomic pattern in the existing
TOU-pause claim (`energy_pool.py:794-815`) which we know is safe.

**Restart mid-yield.** Enumerated above; the persisted blob carries the
final ownership state; nothing to reconcile.

---

## (d) Interaction sweep

- **TOU pause skip for excess-active EVSEs (`energy_pool.py:520-521`):**
  unchanged. Yielded garage A is in `_excess_solar_active`; the TOU
  pause loop already skips it. No new interaction.
- **`_apply_evse_battery_hold` captured-SOC hold:** when a yielded EVSE
  starts charging under excess-solar, the existing hold-capture at
  start-of-charge logic (see `_apply_evse_battery_hold` docstring,
  `energy.py:3690-3701`) pins the hold reserve at the SOC observed at
  charge start. **Interplay:** at the yield moment SOC is ≥
  `excess_solar_soc` (default 95). The captured hold-reserve is thus
  ≥ 95, which is a NO-OP against any reasonable reserve floor (all DP
  floors are ≤ target %, and target ≤ 100). The hold does nothing
  restrictive under excess-solar; INV-DP3 max()-composition still holds
  because we composed against `_paused_by_dp` and garage A is no longer
  a member. **Explicit acceptance:** the captured-SOC hold is inert
  under yield; verify with a test that a yielded EVSE does not lift the
  battery reserve floor above its pre-yield value.
- **fill_priority / grid_cap / load_shed:** stronger-owner peer set kept
  as strict skip in the excess-solar claim. Yield does NOT change the
  strictly-stronger precedence; INV-YIELD-1 only claims against DP-in-
  HOLD_ONLY, never against safety/cost owners.
- **`_paused_by_battery_drain` / `_paused_by_arbitrage`:** unchanged in
  the excess-solar skip list. These are distinct ownership tokens from
  `_paused_by_dp`; the yield is scoped to DP alone.
- **`pause_reason_human` (`energy_pool.py:1730-1770`):** post-yield
  garage A returns `("excess_solar", "excess solar (charging)")` at
  line 1763 (correct — reflects the new owner). Pre-yield it returned
  the DP reason. LIVE observability improvement is a side benefit.
- **The symmetric guard at `energy_pool.py:583-585`** (off_peak ensure-on
  carry-over that also checks `_paused_by_dp`): NOT touched. Off_peak
  ensure-on is a distinct branch from excess-solar and its
  "don't disturb an active DP transition" rationale applies identically
  to HOLD_ONLY (off_peak reversion will release naturally on the next
  DP tick without help). Yielding here would be a separate refinement
  with a different marginal-benefit case; we do NOT bundle it.

---

## Numbers Get Knobs

**Explicit target: zero new knobs.** The yield is condition-derived
from primitives that already have knobs:

- `excess_solar_soc` (Number entity, existing) — governs "battery full
  enough to yield".
- `excess_solar_kwh_threshold` (Number entity, existing) — governs
  "enough remaining PV to matter".
- `tou_period != "peak"` — governed by the TOU engine (existing).
- `_dp_carrier.state == HOLD_ONLY` — internal state, correctly NOT a
  knob (safety property, not a policy).

The operator legitimately tunes the excess-solar thresholds already; a
new knob would either shadow one of these or introduce a
"yield sensitivity" surface with no natural operator intent behind it.
**No new Numbers, no new module constants, no new config-flow fields.**

---

## Tier verdict

**Tier 3 (four framing-disjoint reviews + adversarial completeness).**

Rationale:
- Money path (surplus joules captured vs exported) AND safety-adjacent
  (INV-YIELD-2 protects the drain-target invariant that BAEC was built
  to guarantee — a break here silently drains the house battery through
  a mid-transition period, the exact failure mode BAEC Tier-3 spent
  four review passes closing).
- Shared-primitive pause-owner set (`_paused_by_dp`) with a new
  additive release path — Bug Class #53 territory (computed-but-not-
  consumed / owner-drop-without-retry).
- The area has multi-fix-up history (BAEC: 1 build + 3 fix-ups +
  Tier-3 D re-pass; D2-H1 was a diff-blind pre-existing gap the
  build's grep missed). D-framed adversarial completeness is what
  caught the analogous BAEC leak — the same discipline applies here.
- Tier-3 elevation over Tier 2-DB is warranted specifically because
  INV-YIELD-2 is a single-site protection whose failure mode is
  silent joule-drain, not a crash. Operator-directive "delicate"
  posture applies (2026-06-16 rule).

**Four framings:**
- **A — local correctness:** the new guard predicate, the atomic
  handoff sub-steps, ordering, no-await interleaving, `is_on` gating
  of the dispatch.
- **B — integration / state-machine integrity:** interaction with
  `_apply_dp_reversion` sticky loop (empty set → floor collapse),
  `_dp_maybe_tick`, HOLD_ONLY orphan retry driver, restart mid-yield,
  captured-SOC hold interplay, TOU-skip loop, off_peak ensure-on
  carry-over guard NOT regressing.
- **C — mutation-executed test authority:** per-site source mutations.
  Bypass the HOLD_ONLY guard (predicate becomes always-true) → a test
  MUST fail proving INV-YIELD-2 (yield under TRANSITIONED). Bypass
  the excess-condition predicate → a test MUST fail proving we don't
  yield without conditions. Bypass the ownership handoff (comment out
  `_release_pause_dispatch_owner`) → a test MUST fail proving the DP
  owner is dropped. Aggregate monkeypatch is NOT acceptable — each
  site individually.
- **D — adversarial completeness (diff-blind):** state INV-YIELD-1 +
  INV-YIELD-2 in falsifiable form. Re-enumerate ALL emission/decision
  sites that touch `_paused_by_dp` OR `_excess_solar_active` OR
  `_dp_carrier.state` — including pre-existing code not in the diff.
  Concrete legal-config repros required for any flagged leak. Explicit
  target: any pre-existing site that reads DP membership without
  state-awareness and could be affected by the new yield path (e.g.
  `_apply_evse_battery_hold` composition, restore path, floor
  collapse, KV write cadence).

Orchestrator independent verification (mandatory Tier-3): re-grep every
`_paused_by_dp` reference; re-run one mutation on the load-bearing
HOLD_ONLY guard; confirm at least one specific test goes RED. Operator
checkpoint BEFORE deploy.

---

## Deliverables

### D1: Yield predicate + atomic handoff at excess-solar claim

- Modify `energy_pool.py::determine_excess_solar_actions` (~line 786):
  - Replace the flat `evse_id in self._paused_by_dp` skip with a
    state-aware guard. The check requires access to
    `_dp_carrier.state`; wire via a small accessor on the EnergyBattery
    coordinator (existing owner of `_dp_carrier`) — reuse the existing
    reference path used by other cross-module checks (verify at build
    time; if no accessor exists, add a read-only property, NOT a knob).
  - When yield fires: execute the four-step atomic handoff (discard
    `_paused_by_dp`, release "dp" owner, add `_excess_solar_active`,
    dispatch turn_on if not already on) mirroring the existing
    `_paused_by_us` claim block just below.
  - Log at INFO: `"excess solar: claimed %s from deferred DP hold
    (dp_carrier=HOLD_ONLY, SOC=%.0f, remaining=%.1f kWh)"`.

### Acceptance Criteria — D1

- **Verify (INV-YIELD-1):** with `_dp_carrier.state = HOLD_ONLY`,
  `evse_id in _paused_by_dp`, `SOC >= 95`, `remaining_forecast >= 5.0`,
  `tou_period = "mid_peak"` → EVSE moves from `_paused_by_dp` to
  `_excess_solar_active`, dispatch fires `switch.turn_on`, "dp" owner
  dropped, one INFO log line as specified.
- **Verify (INV-YIELD-2, TRANSITIONED):** same conditions but
  `_dp_carrier.state = TRANSITIONED` → EVSE remains in `_paused_by_dp`,
  no dispatch, `_excess_solar_active` unchanged, existing skip DEBUG
  log fires.
- **Verify (INV-YIELD-2, MUST_START_FORCED):** same as above with
  `MUST_START_FORCED` → identical no-yield result.
- **Verify (peer safety owners strictly outrank yield):** yield
  predicate true BUT EVSE also in `_paused_by_grid_cap` (or
  fill_priority / load_shed / drain / arbitrage) → no yield, still
  skipped by strictly-stronger owner check.
- **Sensor:** `sensor.<ev>_pause_reason` (via `pause_reason_human`)
  transitions from `"drain-precedence transition (paused)"` to
  `"excess solar (charging)"` at the yield tick.
- **Test:** new tests in `quality/tests/energy_pool/` covering all four
  bullets above, plus a restart-mid-yield test verifying persisted
  state carries the post-yield ownership (garage A in
  `_excess_solar_active`, NOT in `_paused_by_dp`) and post-restart
  re-evaluation is stable.
- **Test (interplay):** yielded EVSE starts charging → captured-SOC
  hold does NOT lift the composed reserve floor above the pre-yield
  value (INV-DP3 not regressed for peers).
- **Live:** replay the 2026-07-20 garage-A day shape — during the next
  high-solar day when battery reaches ≥95% while any EVSE carries a
  deferred DP pause (`pause_reason_human` shows "drain-precedence
  transition (paused)" with `_dp_carrier.state = HOLD_ONLY`), that
  EVSE transitions to `pause_reason_human = "excess solar (charging)"`
  within one decision cycle of excess-solar activation, `switch.turn_on`
  observed in HA logs, EV starts drawing PV. Record the observation
  window (entity attributes + timestamps) in
  `docs/readmes/README_v<version>.md` per Live Validation write-back
  rule.

### D2: KV / restore verification

- No new persisted field. Verify (existing writes) that the yielded
  EVSE's post-yield state round-trips correctly:
  - `evse_dp_paused` KV set on next persistence tick reflects the
    reduced `_paused_by_dp` set.
  - `_excess_solar_active` in the blob carries the yielded id.
  - Restart drops nothing; excess-solar re-evaluation on first post-
    restart tick either keeps it on (conditions still hold) or turns
    it off cleanly (existing off-conditions branch).

### Acceptance Criteria — D2

- **Test:** restart mid-yield with excess conditions still holding →
  yielded EVSE remains on, still in `_excess_solar_active`, still
  NOT in `_paused_by_dp`. HOLD_ONLY orphan retry driver
  (`energy.py:3517-3520`) does NOT re-add it (correct — DP no longer
  owns).
- **Test:** restart mid-yield with excess conditions no longer holding
  (e.g. SOC dropped below threshold overnight) → EVSE turns off,
  cleanly released from `_excess_solar_active`; DP does NOT re-claim.

---

## Marginal-Benefit note

- **Benefit:** captured surplus joules on high-solar days, scoped to
  the specific case where a plug-in-timing lottery at BAEC transition
  entry stranded one car in `_paused_by_dp` past off_peak. Frequency
  depends on how often the sticky-defer window overlaps a
  ≥95% SOC + kWh-surplus event; the 2026-07-20 fixture proves it is
  not zero. Order-of-magnitude estimate: a mid-peak-through-shoulder
  window of 4-6h of stranded excess PV × ~7 kW EVSE draw × the yield
  claiming that window = single-digit to low-tens of kWh per event.
  Non-trivial on the marginal, and the export-vs-charge economics
  favor charging by the full retail-import minus export-credit spread
  (materially positive on TOU).
- **Ingredient risk — name honestly:** a NEW release path on the
  `_paused_by_dp` owner set. This is exactly the shape of the BAEC
  D2-H1 / D2-H2 findings (owner drop without retry / owner drop with
  wrong ordering). The mitigation is architectural — HOLD_ONLY is the
  DP state machine's own signal that no active transition is in
  flight — but the discipline of INV-YIELD-2 protection at each site
  is what the D reviewer must falsify. Containment (Tier 3 review
  posture) is EVIDENCE of the risk, not a discount.
- **Marginal-benefit verdict:** the benefit is real and recurring on
  high-solar days; the ingredient risk is a single new release path
  with a clean state-machine-derived guard and no new knob. Recommend
  building at Tier 3. If D framing surfaces a pre-existing DP-membership
  reader without state-awareness (analogous to BAEC D2-H1), that's a
  fix, not a reason to abandon.
- **Simpler alternative considered + rejected:** "just widen the sticky
  defer to release on mid_peak too" — rejected, breaks INV-YIELD-2
  (releases active TRANSITIONED cars during mid_peak, draining the
  battery into cars during the exact window BAEC was built to protect).
  The state-aware yield is the minimal design that captures the
  benefit without regressing the invariant.
- **Parked (not deleted):** widening the yield to the off_peak
  ensure-on carry-over guard at `energy_pool.py:583-585` (symmetric
  case for a different branch). Evidence trigger to revisit: a
  measured occurrence of an EVSE stranded in `_paused_by_dp` at
  off_peak boundary that ensure-on would otherwise have claimed.

---

## Summary (return to caller)

- **Doc path:** `/Users/okosisi/Code/universal-room-automation/docs/planning/PLANNING_dp_sticky_yields_to_excess_solar.md`
- **Placement decision:** Option B — excess-solar claim site
  (`energy_pool.py::determine_excess_solar_actions`, current flat
  `_paused_by_dp` skip at line 786 becomes a state-aware guard).
  Rationale: correct ownership direction (excess-solar owns the claim
  predicate; DP owns transition state), atomic single-site handoff,
  INV-YIELD-2 becomes one falsifiable predicate, no reverse
  dependency into DP reversion, fires without waiting for the next DP
  tick.
- **Invariants:**
  - INV-YIELD-1 (permissive): HOLD_ONLY + `_paused_by_dp` membership +
    excess conditions ⇒ claimable, always.
  - INV-YIELD-2 (restrictive, load-bearing): TRANSITIONED or
    MUST_START_FORCED ⇒ NEVER released by excess-solar, any config.
- **Tier verdict:** Tier 3 (four framing-disjoint reviews + operator
  checkpoint before deploy). Money-path invariant on a shared pause-
  owner primitive with multi-fix-up history in the same surface.
- **New knobs:** zero.

## Reconciliation audit adjudication (2026-07-20, orchestrator)

A pre-ship tri-mechanism reconciliation audit (excess-solar x TOU x
BAEC, operator-mandated) flagged D1 HIGH: "the sticky-DP yield has no
reachable scenario because the HOLD_ONLY orphan retry
(energy.py:3532-3537) drains the sticky set earlier in the same tick."

**Adjudicated REFUTED by orchestrator source verification:**
- `_apply_dp_reversion` sticky-defers whenever
  `tou_period != "off_peak"` (energy.py:4108) — the retry driver calls
  reversion but reversion cannot drain the set during mid_peak.
- Excess-solar forbids activation only during `"peak"`
  (energy_pool.py:773); its conditions (SOC>=95, forecast>=5kWh) are
  the high-solar midday state, which falls in mid_peak.
- Concrete legal repro: night drain completes, reversion TOU-defers at
  mid_peak entry leaving a HOLD_ONLY orphan; 12:00 mid_peak, SOC 100,
  remaining forecast 20kWh. Retry -> reversion -> defer (set retained).
  Only the yield path can lawfully start the EVSE. This is the
  observed Garage B incident that motivated the cycle.
- The audit's counter-scenario used the off_peak morning window, where
  the retry legitimately wins and the yield being a no-op there is
  correct, not dead.

Answer to "what does this buy over the orphan retry": the retry can
never release during mid_peak by design; the yield is the only lawful
mid_peak escape for a sticky orphan under excess solar.

### Audit follow-ups accepted (pre-existing, non-blocking)
- **D2 MED:** force-charge does not release `_paused_by_dp` on a live
  TRANSITIONED carrier — override only enforced at the eval gate.
  Follow-up cycle.
- **D3 LOW / S5:** extend `validate_threshold_ladder`
  (energy_const.py:980) with cross-checks for
  fill_priority_soc < excess_solar_soc, ev_battery_drain_soc vs
  excess_solar_soc, DP drain targets vs inclement floor,
  must_start_by past end-of-night.
- **D4 LOW:** `_apply_dp_must_start_release` (energy.py:4166-4176)
  does not defer on `_paused_by_battery_drain` (INV-DP2 corner).
- **S1:** fold the two DP-internals-leaking sites (energy_pool.py:820
  + 842) into `EVChargerController.can_yield_dp()`.
- **S3 ratified:** do NOT collapse the owner sets into a single
  priority function — separable ownership is what lets
  framing-disjoint reviews catch distinct leaks (v5.5.3 D-HIGH-1
  precedent). Complexity is load-bearing.
