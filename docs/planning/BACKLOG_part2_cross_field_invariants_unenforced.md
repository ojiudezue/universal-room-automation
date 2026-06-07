# BACKLOG — Cross-field invariant enforcement: EC SOC pair + egress pause/resume pair

**Status:** Operator-decision pending. NOT shipped.
**Tier:** Tier 2 (UX + clamp + config_flow validation surface; cross-coordinator behavior).
**Filed:** 2026-06-06 during Part 2 build pass (per O3 + O4 of `PLANNING_part2_ec_hc_options_writeback_retrofit.md`).

## Two found-but-unenforced cross-field pairs

Build-pass verification surfaced two cross-field constraints that READ as
invariants in the planning docs and class docstrings but are NOT enforced
in either the entity setter (no clamp) or the OptionsFlow `config_flow.py`
form path (no validation). The Part 2 retrofit preserved that posture
without inventing new UX. Operator decides whether to enforce.

### O3 — `fill_priority_soc` vs `excess_solar_soc`

- `FillPrioritySOCNumber` (default 80) is the turn-OFF (pause-until) threshold.
- `ExcessSolarSOCNumber` (default 95) is the turn-ON (resume-at) threshold.
- The asymmetric dead band relies on `fill_priority_soc < excess_solar_soc`.
- **Verified 2026-06-06:** grep `config_flow.py` for the two CONF names
  surfaced no cross-field check; the EC setters at `energy.py:3904-3930`
  do not clamp either field against the other.
- **Failure mode if violated:** if the operator sets `fill_priority_soc=95`
  and `excess_solar_soc=90`, the gate logic flips polarity in the
  middle-band (80-95 default) → EVSE oscillates pause/resume at every
  SOC change in the inverted band.

### O4 — `hvac_egress_threshold_min` vs `hvac_egress_resume_delay_min`

- `HVACEgressPauseThresholdNumber` (default 3) = minutes a window must be
  open before pause fires.
- `HVACEgressResumeDelayNumber` (default 1) = minutes all egress windows
  must be closed before resume fires.
- **Verified 2026-06-06:** these are two independent timings (one gates
  pause, one gates resume); there is no documented "resume_delay must be
  ≤ pause_threshold" invariant in `hvac_egress.py` setter clamps
  (lines 133-154). The two values clamp ONLY to their own min/max bounds.
- **Failure mode if violated (uncertain):** likely none — these are
  independent gates on different state transitions. Worth confirming
  with the operator before adding a clamp that doesn't model the
  actual semantics.

## Recommendation for the operator decision

- O3 (EC pair): semantically real invariant, no enforcement today.
  Likely worth adding a bidirectional clamp mirroring the v4.7.25
  `VacancyGraceMinutesNumber` A-HIGH-1 pattern (`number.py:444-461`).
  Both entity setter + config_flow form path. Defensive clamp also in
  `_apply_in_place` for out-of-band writes.
- O4 (egress pair): probably NOT an invariant; recommend documenting
  that the two timings are independent and leaving behavior unchanged
  unless the operator confirms the constraint.

## What this cycle would deliver (if operator approves)

1. Mirror the A-HIGH-1 clamp pattern for `FillPrioritySOCNumber` +
   `ExcessSolarSOCNumber` setters.
2. Add cross-field validation to `config_flow.py` for the EC pair
   (combined-error pattern from v4.7.26 D5).
3. Add defensive clamp in `_apply_in_place` so out-of-band writes
   (external `async_update_entry`, future service/YAML path) can't
   leave an inverted pair.
4. New tests mirroring the v4.7.25 / v4.7.26 layered-clamp test suite.
5. Operator-confirmation on O4 — if no invariant, document the
   independence in the class docstrings (`number.py:2281-2476`) and
   close that half of the decision.

## Why this is not a blocker for Part 2 deploy

- Part 2 preserves the existing posture (no enforcement); behavior is
  byte-identical. The retrofit does not introduce a new way to violate
  the constraint, only persists the existing knobs through a different
  path (entry.options instead of RestoreEntity).
- The doctrine flip itself is the cycle's value; cross-field clamps
  are an orthogonal UX/data-integrity addition that deserves its own
  scoped review.
