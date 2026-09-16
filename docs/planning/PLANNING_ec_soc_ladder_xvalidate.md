# PLANNING — EC-SOC-LADDER-XVALIDATE-1: SOC-ladder cross-field validation

**Card:** EC-SOC-LADDER-XVALIDATE-1
**Status entering plan:** pre_planning; the card's 2026-09-12 verify-sweep marks it
**PARTIALLY-DONE** — the save-time reject + runtime `threshold_ladder_violation`
anomaly + `safely_ordered_ladder()` accessor SHIPPED on
`feature/energy-validate-staleness` (energy.py:9163/9264, energy_const.py:1156-1323).
**This plan covers the residual only**: switch live consumers onto the safe
accessor so a runtime-inverted ladder cannot flip a gate polarity, plus close the
SCOPE gap the accessor's own docstring flags at energy.py:9267-9275.
**Tier:** 2-DB (shared validator + shared runtime accessor consumed by multiple
EC decision paths; regression-prone per standing policy — 3 framing-disjoint
reviews).

---

## Institutional context verified

### Prior planning / analysis harvested
- **PLANNING_dp_sticky_yields_to_excess_solar.md:521-525** — parked D3/S5:
  extend `validate_threshold_ladder` with `fill_priority_soc < excess_solar_soc`,
  `ev_battery_drain_soc` vs `excess_solar_soc`, DP drain targets vs inclement
  floor, `must_start_by` past end-of-night.
- **BACKLOG_part2_cross_field_invariants_unenforced.md:1-74** — O3 (EC pair
  `fill_priority_soc` vs `excess_solar_soc`) semantically real, no
  enforcement at the time; O4 (egress pause/resume) analysed as NOT an
  invariant → out of scope for THIS card, egress-side.
- **AUDIT_excess_solar_and_evse_prior_art.md** — P1 row (:822) confirms the
  solar-follow amp cycle actively modulates the 80/95 band, which is what
  "fires the trigger" of the parked D3.

### Code surface surveyed (grepped, read end-to-end for the pieces touched)
- `energy_const.py:1148-1323` — **validator + canonical doc EXIST**:
  `validate_threshold_ladder(...)` extended with `fill_priority_soc`,
  `excess_solar_soc`, `ev_battery_drain_soc`,
  `inclement_partial_hold_reserve_floor` kwargs (all optional, None-skipped);
  `CANONICAL_SOC_LADDER_DOC` enumerates the 6 invariants.
- `config_flow.py:4668,4722` — save-time invocation of the extended validator
  (reject-at-source path).
- `energy.py:9163-9262` — `_check_threshold_ladder()` (runtime guard) emits
  `threshold_ladder_violation` anomaly, once/hour/code, with a boot-time
  suppression that does NOT stamp the rate-limit window if the DB isn't up
  yet (B4 fix-up already in place).
- `energy.py:9264-9304` — `safely_ordered_ladder()` accessor: **clamps only
  2 of the 6 invariants** (ev_drain up to reserve; fill_priority down to
  excess_solar). Its own docstring flags this SCOPE gap and says
  consumers must not adopt it until missing invariants are added.
- Setters: `energy.py:9475/9495/9515` (`set_ev_battery_drain_soc`,
  `set_fill_priority_soc`, `set_excess_solar_soc`) — each calls
  `_check_threshold_ladder()` (energy.py:9484/9503/9525).
- Raw-attr consumers of the three EV-band knobs (candidates for the switch):
  - `energy.py:6025-6026` — actuation-tick snapshot `fill_priority_soc_tick`
    / `excess_solar_soc_tick` (B-M3 / D1 race guard).
  - `energy.py:6178,6198,6361` — `soc_threshold=self._ev_battery_drain_soc`
    into `DrainProtectionController`.
  - `energy.py:9707,9792,9797,10584,10587` — `_fill_priority_soc` /
    `fill_priority_target_soc=` into downstream planners.
  - `energy_pool.py:1327,1823` — `getattr(coord, "_ev_battery_drain_soc",
    None) or 0` (pool-side drain guard).
  - `energy_battery.py:6234-6236` — already routes through
    `validate_threshold_ladder` for a battery-side check (parallel call site;
    verified, not modified by this plan).

### REUSE-or-BUILD verdicts per proposed piece
| Piece | Verdict | Cite |
|---|---|---|
| Cross-field validator (the 4 kwargs, all 6 invariants) | **REUSED — already extended** | energy_const.py:1156-1306 |
| Save-time reject in options/coordinator flow | **REUSED — already wired** | config_flow.py:4668,4722 |
| Runtime anomaly emitter (`threshold_ladder_violation`) | **REUSED — already wired** | energy.py:9163-9262 |
| Safe accessor `safely_ordered_ladder()` | **EXTEND (BUILD residual)** — must cover all 6 invariants before adoption | energy.py:9264-9304 |
| Consumer switch (raw-attr → accessor) | **BUILD (net-new residual)** — no consumer today; card's disposition names this as the residual | see call-site table above |
| Canonical ladder doc constant | **REUSED** | energy_const.py:1317-1323 |
| Numbers-Get-Knobs placement | **REUSED** — the ladder members are already the right rung: `reserve_soc` = ModuleConst-derived seed + options-flow write-back; `fill_priority_soc`, `excess_solar_soc`, `ev_battery_drain_soc` = Number-entity rung (number.py:1330,1462,1578) exactly per the ladder doctrine; drain-quality targets = per-quality Numbers. **No new knobs proposed by this plan.** |

### Memory bodies pulled
- `feedback_tier2db_for_regression_prone` — elevate to 3 framing-disjoint
  reviews; applies here (shared validator + shared accessor).
- `feedback_wire_in_anchor_mandatory` — every consumer switch needs a
  behavioural anchor (mutation-neuter the accessor and prove a *specific*
  test fails).
- `feedback_coincidental_equality_masks_concept_split` — `very_poor`
  defaulting to `poor` is Bug Class #63; the validator already forces the
  discriminating test; the consumer switch must not re-collapse it.
- `feedback_do_robust_fix_not_bandaid_and_card` — since the accessor is the
  robust seam and it's already built, the correct move is to close the
  SCOPE gap and adopt it, not to card-around.

### Design docs
- `docs/Coordinator/ENERGY_COORDINATOR.md` skimmed for the SOC-ladder section
  (canonical doc string is authoritative; docstring at energy_const.py:1148
  is the in-source spec).

---

## Falsifiable invariant (state before build)

Under any legal Number/options-flow combination of the ladder knobs, no
consumer of an SOC-ladder member SHALL read a value that violates any of the
six canonical invariants below. Falsification: find a legal sequence of
Number entity writes that leaves at least one enumerated consumer reading a
raw attribute whose value violates a canonical invariant AND drives a
different action than the safe-clamped value would drive in the same tick.

### The 6 canonical invariants (verbatim from energy_const.py:1309-1316)
1. `reserve_soc <= drain_excellent <= drain_good <= drain_moderate <= drain_poor <= drain_very_poor`
2. `peak_buffer_target > max(drain_poor, drain_very_poor)`
3. If `arbitrage_trigger` set: `reserve_soc < arbitrage_trigger < drain_poor`
4. `fill_priority_soc <= excess_solar_soc`  *(O3 / D3 core)*
5. `ev_battery_drain_soc >= reserve_soc`
6. `inclement_partial_hold_reserve_floor >= reserve_soc`

Save-time path enforces all 6 by reject (config_flow.py:4722). Runtime path
detects all 6 by anomaly (energy.py:9189). **Only #4 and #5 are clamped by
`safely_ordered_ladder()` today**; #1, #2, #3, #6 are detect-only. Consumers
that read raw attrs bypass the clamp entirely.

---

## Deliverables

### D1 — Close the SCOPE gap in `safely_ordered_ladder()`

Extend the accessor at `energy.py:9264-9304` so it returns a safe value for
EVERY ladder member a consumer might read, not only fill_priority / ev_drain.
Add to the return dict:
- `peak_buffer_target` clamped UP to `max(drain_poor, drain_very_poor) + 1`
  when the buffer-ceiling invariant (#2) is violated (raise the ceiling,
  never lower a drain).
- `drain_targets` (dict) with monotonic non-decreasing sort ANCHORED at
  `reserve_soc` (raise each below-reserve entry UP to `reserve_soc`; then
  monotonise by cumulative-max going excellent→…→very_poor). Do NOT force
  `very_poor` down to `poor` — that would silently collapse the concept
  split (Bug Class #63); collapse is only permitted when the raw operator
  values already equal (the coincidental-default case).
- `inclement_partial_hold_reserve_floor` clamped UP to `reserve_soc` when
  below.

Update the docstring to remove the "no consumer" warning and to list the
new full coverage; keep the Bug Class #53 note but flip it ("adoption
gated on scope-completeness — now met").

**Non-goal:** the accessor does NOT touch `arbitrage_trigger`; #3 stays
detect-only because arbitrage_trigger is currently passed as `None`
(energy.py:9192) and there is no live consumer to protect. Documented as
an explicit non-goal so a Tier-3 reviewer isn't reading it as an omission.

### D2 — Switch consumers off raw attrs onto the accessor

For each call site below, replace the raw-attr read with an accessor read
(cached once at the top of the enclosing method / tick to preserve the
existing B-M3 / D1 snapshot semantics). Ordered by blast radius:

| Site | file:line | New shape |
|---|---|---|
| Actuation-tick snapshot | energy.py:6025-6026 | `_l = self.safely_ordered_ladder(); fill_priority_soc_tick = _l["fill_priority_soc"]; excess_solar_soc_tick = _l["excess_solar_soc"]` |
| EV drain gate (breaker-safe dispatch) | energy.py:6178,6198,6361 | read `_l["ev_battery_drain_soc"]` from the same tick snapshot |
| Fill-priority downstream planners | energy.py:9707,9792,9797,10584,10587 | pass `_l["fill_priority_soc"]` in place of `self._fill_priority_soc` |
| Pool-side EV drain guard | energy_pool.py:1327,1823 | `getattr(coord, "safely_ordered_ladder", lambda: {})().get("ev_battery_drain_soc")` with the existing `or 0` fallback preserved |

The accessor call is O(dict-of-4); no rate concerns. Preserve the existing
snapshot discipline: each *tick* calls the accessor ONCE and threads the
snapshot downstream — do NOT re-call inside sub-branches (that would
re-introduce the B-M3 mid-tick race the original snapshot fixes).

### D3 — Anchor + mutation drill (Tier-3 discipline even at Tier 2-DB)

For each switched site, a behavioural test that (a) sets a legal but
inverted Number combination (e.g. fill_priority=90, excess_solar=85), (b)
drives one tick, (c) asserts the branch chosen is the safe-clamped one and
the un-clamped raw-attr value would have driven a DIFFERENT branch. Per
`feedback_wire_in_anchor_mandatory` the test must anchor on the enclosing
method's *behaviour*, not the accessor call. A source-mutation drill
neuters `safely_ordered_ladder()` to return raw attrs (identity dict) and
confirms each anchor FAILS with a named assertion — restore-and-status per
`feedback_unrestored_mutation_drill_poisons_evidence`.

### Non-goals (explicit)
- No new CONF_*, sensor, helper, or Number entity — every knob already
  exists at its correct ladder rung.
- No change to the save-time reject path (already SHIPPED and green).
- No change to the anomaly emitter (already SHIPPED with B4 fix).
- No change to `arbitrage_trigger` handling (detect-only stays).
- Egress pause/resume O4 pair — deferred as documented in
  BACKLOG_part2:45-50 (not an invariant).

---

## Acceptance criteria (testable)

- **Verify:** with fill_priority=90, excess_solar=85 (legal Number values,
  inverted), a single decision tick reads
  `fill_priority_soc_tick == 85` and the fill-priority branch does NOT
  fire above 85 — matching the safe-clamped intent, NOT the raw 90.
- **Verify:** with ev_battery_drain_soc=10, reserve_soc=20, one tick of
  the drain-protection path calls `DrainProtectionController` with
  `soc_threshold=20`, not 10.
- **Verify:** with inclement_partial_hold_reserve_floor=15, reserve_soc=20,
  the partial-hold consumer reads `>= 20`.
- **Verify:** `very_poor=30, poor=30` (coincidental default equality)
  survives the accessor unchanged — no silent collapse.
- **Verify:** with `very_poor=25, poor=30` (concept split, but very_poor
  BELOW poor), the accessor raises very_poor to 30 (monotone) and the
  anomaly still fires (detect-and-clamp, not detect-and-swallow).
- **Sensor:** on any Number-driven inversion, a
  `threshold_ladder_violation` anomaly with the correct `code` appears in
  the anomaly table within one tick (unchanged from today; regression
  guard).
- **Test:** the D3 mutation drill — replacing
  `safely_ordered_ladder()` with an identity passthrough — must fail at
  least one named test per switched site (site-specific, not aggregate).
- **Live:** post-restart, `sensor.<ec>_threshold_ladder_state` (if
  present; otherwise the anomaly table) shows no violation under the
  current live config; and a temporary Number write that inverts a pair
  (`ev_battery_drain_soc` below `reserve_soc`) causes the drain path to
  act on `reserve_soc` in the next tick (validated by anomaly emission
  timing + a single-tick decision log line the acceptance harness reads).

### Discriminating test plan (falsifies the invariant if broken)

Configure via test fixtures (no operator action needed):
```
reserve_soc = 20
drain_targets = {"excellent": 20, "good": 25, "moderate": 30,
                 "poor": 30, "very_poor": 25}   # very_poor BELOW poor
peak_buffer_target = 28                          # BELOW top-drain 30
fill_priority_soc = 90                           # ABOVE excess_solar
excess_solar_soc = 85
ev_battery_drain_soc = 10                        # BELOW reserve_soc
inclement_partial_hold_reserve_floor = 15        # BELOW reserve_soc
```
Every invariant is inverted, each independently reachable via legal
Number writes. Under the fix: EVERY consumer reads the clamped value; the
save-time path (independently) would have rejected the combination; the
runtime anomaly (independently) fires. Under a regression at ANY site,
the discriminating check for that site fails with a NAMED assertion,
identifying the leaking consumer.

---

## Tier + review framing

**Tier:** 2-DB (three framing-disjoint reviews + live validation +
README write-back). Rationale: the change adopts a *shared accessor*
across ≥8 call sites in ≥2 files (energy.py + energy_pool.py); any
single missed site is a silent leak (Bug Class #53, "computed but not
consumed" — inverse: "consumed but not computed-through-safe-seam").

**Reviewer framings (must be disjoint):**
- **A — Local correctness & scope-gap closure.** Every clause added to
  `safely_ordered_ladder()` is arithmetically correct at the boundary
  and does not silently collapse `very_poor==poor` distinctions when
  they diverge. Boundary tests at each ladder equality.
- **B — Cross-coordinator integration / tick-snapshot integrity.** Every
  switched site is under the *same* per-tick snapshot; no sub-branch
  re-reads through the raw attr; no double-emit of anomalies from
  clamped-but-detected paths; RestoreEntity boot ordering unchanged;
  energy_pool.py sites do not race with energy.py sites in the same
  tick.
- **C — Adversarial completeness / diff-blind.** Re-enumerate EVERY
  reader of `_fill_priority_soc`, `_excess_solar_soc`,
  `_ev_battery_drain_soc`, `_drain_targets`,
  `_peak_buffer_target`, and the inclement partial-hold floor across
  the entire coordinator surface (not just this diff). Any raw-attr
  reader NOT covered by D2 is a leak. Also verify no test-only shim
  reaches into `_fill_priority_soc` in a way that would silently bypass
  the accessor once adopted.

Orchestrator pre-deploy independent verification (per Tier-3 muscle
brought down to Tier 2-DB by operator standing policy): re-grep the
five attr names across `custom_components/` and confirm every non-test
reader routes through `safely_ordered_ladder()` OR is explicitly
justified (setter, accessor internals, validator input, translations).

---

## Refs
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py:1148-1323`
- `custom_components/universal_room_automation/domain_coordinators/energy.py:9163-9525`
- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py:1327,1823`
- `custom_components/universal_room_automation/config_flow.py:4668-4722`
- `docs/planning/PLANNING_dp_sticky_yields_to_excess_solar.md:521-525`
- `docs/planning/BACKLOG_part2_cross_field_invariants_unenforced.md:1-74`
- `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md:822`
