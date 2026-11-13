---
name: ura-arc
description: >
  Anti-drift protocol for AMBITIOUS URA arcs (multi-plan, multi-cycle, Tier 3 work such as identity/vision/census).
  Loads the arc charter (operator goals verbatim, hard constraints, non-goals, model) and the arc map, runs a drift
  check, and enforces goal-fidelity review, no silent deferral, one clean doc per scope, and the seam/merge check.
  Load at: plan dispatch, plan approval, ship, session start or after compaction for any arc marked ambitious, and
  whenever the operator asks "are we drifting?".
---

# URA ambitious-arc protocol

Origin: 2026-11-13 identity/vision/census arc. Three framing-disjoint reviews passed a design (vision holding AWAY)
that solved a problem the operator did not have and slowed the one thing they needed fast. 14 drifts in one arc:
`docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`. CLAUDE.md wins over this skill.

## Arc registry

| Arc | Charter | Arc map | Model |
|---|---|---|---|
| identity / vision / census | `docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md` (goals section) | `docs/planning/ARC_identity_vision_census_map.md` | F1-F5 (CLAUDE.md, `PLANNING_person_sighting_layer.md` §2A, manual §5.5) |

Add a row when the operator marks an arc ambitious. A charter holds: the operator's goals verbatim, hard
constraints, non-goals, the model the arc lives in, and the promotion ladder if one applies.

## Rules

1. **Charter first.** Every plan, review and builder brief in the arc links the charter and states which charter
   goal it serves. A deliverable that serves none is out of scope or the charter is stale; ask.
2. **Goal-fidelity review.** Every Tier 2+ plan review in the arc includes a framing whose only questions are: does
   this deliver the charter goals as the operator stated them; does it break a hard constraint; did a risk-reduction
   change WHAT is delivered? Findings are severity-ranked like any other framing (CLAUDE.md, framing G).
3. **Tradeoffs go to the operator.** If reducing risk changes the product, the planner names the tradeoff and the
   orchestrator asks. Never pick the safer-but-different product silently.
4. **No silent deferral.** Parking any piece of a charter goal needs the operator's yes and a card with a revival
   trigger, linked in the arc (batch / parent) so the arc-close gate sees it.
5. **One clean document per scope.** Rewrite, never layer revisions or "section X wins" overrides. History goes to an
   archive file headed NOT A BUILD SPEC. A reviewer confirms equivalence with the last reviewed version before the
   operator approves.
6. **Seam / merge check.** Before a new card or plan is accepted into the arc, check the arc map: if it changes the
   same function, field or contract as another plan, or one would need re-planning when the other lands, MERGE unless
   a reason is written down. Update the arc map.
7. **Drift check at milestones** (plan dispatch, plan approval, ship, session start, after compaction): produce a
   table `operator said | where it drifted | correction | status`, quoting the operator. Zero drift is a valid result;
   say so.
8. **Verify facts before dispatch.** Deploy state, live values and code claims in a brief are checked now, not carried
   from summaries or earlier agents.
9. **Verbatim quotes on cards.** Every goal-shaping decision is recorded on the card as `operator_<date>_<topic>` with
   the operator's words.

## Drift-check procedure

1. Read the charter goals and constraints, the arc map, and the cards in the arc (`batch` / links).
2. Pull the operator's goal statements since the last check (transcript or card `operator_*` fields).
3. For each in-flight plan/build: which goal it serves, which constraint it could break, what it defers.
4. Output the table (rule 7); card or fix each drift the same turn; tell the operator the corrections.
