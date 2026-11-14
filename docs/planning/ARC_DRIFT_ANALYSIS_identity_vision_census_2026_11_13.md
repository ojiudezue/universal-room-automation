# Arc drift analysis: identity, vision and census (2026-11-13)

Written so the analysis survives compaction. Companion docs: `ARC_identity_vision_census_map.md` (branch
`plan/arc-map`, e241cbb3), CLAUDE.md identity-model rule, memory `reference_identity_model_f1_f5.md`.

## The operator's goals (verbatim, the charter)

- "Vision is to assist census accuracy. And assist arrivals accuracy and personalization. Especially when combined
  with facial recognition from the nvr systems. Frankly our job is to make it faster and faster until it can
  eventually be used in security applications too."
- "I need away to be fast acting. That's how it saves $ on energy treatment." (hard constraint)
- "We don't have an away problem... Away Provenance is fine."
- Earlier in the arc: "make census almost bullet proof at entry... You could even essentially base census entirely on
  this"; "guests should be both vision and frigate/protect person counts with deconfliction. Until we trust vision";
  "The hard part about census is NOT residents"; "focus on that technical part of the design. When to fast sample,
  how fast that comes back. What the later batch tells us and how fast that comes back and when the complete
  synthesis lands. We need to simulate this"; "egress only names people who are already home... Who made this rule?
  ... It should do both".
- Added 2026-11-14 (drift caught): "we may need a consolidated boundary crossing and person awareness function etc. That all
  consumers can [read] and producers can feed?" and "Unified functions or layers are powerful only if we get it right and
  make sure there are no leaks." (Constraint: one person-awareness layer with one ingest point per fact and one read
  surface; contract docs/planning/CONTRACT_person_awareness_layer.md; a code guard fails on any new leak; every plan in
  the arc states how it feeds or reads through the layer.)
  How Claude restated it at the time (2026-11-13, the drift's origin): "I'll bring you a reuse-first proposal, not a new
  layer", then carded PERSON-AWARENESS-READ-API-1 as "public census accessors; one ID-normalization function; read views
  on the presence coordinator, one per use class". That kept the consumers-read half and dropped the producers-feed half:
  no single ingest point per fact was ever specified, so each producer (crossing vision -> ledger, NVR witness, sightings,
  stream health) got its own "one X" entry. The plan consolidation (drift #13, arc map merge check) merged documents and
  seams but never checked plans against this contract, so it could not catch it. Operator 2026-11-14: "This is why we
  consolidated the plans." Correction: the contract names both halves; the merge check and every plan review now test
  "feeds through the one ingest, reads through the one surface".
  Name: **the person-awareness layer**. Diagram: CONTRACT_person_awareness_layer.md §1. Why it is worth having (the
  2026-11-13 utility judgment: private census reads, scattered ID normalization, existing host, the F3/F5 ceilings,
  vision leading later): same doc §0a.
- Added 2026-11-14: "vision will eventually be able to pull short clips of video to watch. Make sure no plan precludes
  that." (Constraint: every vision deliverable keeps a frame-source path that can take a short clip, e.g. llmvision
  `video_analyzer` on a Frigate clip, not only still frames; plan reviews check it.) Also: "Interior vision is meant to
  supplement person counts sensors. And allow us to describe what is happening with people when we need it. It should
  add depth (emotion is the deepest). Privacy in the main objection." "Accept privacy now. If the accuracy holds up, we
  should move to local." "A dead camera is not a presence or absence of signal. Its faulty equipment."
- Settings: "help with accuracy (first) and contribute to good alert hygiene (second)"; "Switches should have a
  config flow entry"; "Name of switch. not good yet."
- Process: "We should do the hard parts sooner and learn faster"; "We need completion"; "Always forward for this
  arc"; plans "clean and streamlined... not Frankenstein"; "I didn't want artificial seams that will sink us later."
- Added 2026-11-14 (drift check: operator goals missing from this charter until now):
  - Dual NVR: "For all camera work I like to exercise both nvr platforms simultaneously, then cross compare to reduce
    errors"; "centralize the evidence and keep the policy with each feature"; the per-camera agreement record is
    "Critical for learning. Has to be baked into the design." Dead camera: "I assume if even one nvr has the cam it
    doesn't count as dead" (NOT true in code yet: stream health judges per camera entity; see drift #15).
  - Registry: "Unacceptable to do the latter anymore" (never infer device, platform, person or room from names).
  - Alerts: "A. Alert now, name it afterwards" (latency over precision; late identity is a follow-up).
  - Windows: "15 mins" / "make both 15 mins" (checkpoint and dead-input hold). Switch name: "Vision Assisted Census".
  - Music following and room rules are in the arc: "No shadow mode... Treat the reformulations as full blown mission
    critical feature that must work on day 1... This is where our features die and are not switched on"; "observability
    and logs that allow diagnostics and tuning"; bounce safety between adjacent rooms; Sonos leads in the master; MA
    first with native backup.
  - v6.0.0: "step 8 is fine. You better get a move on"; "we don't need to be so conservative on shipping this live as
    soon as the arc matures and comes together."
  - Personalization: "Don't want to defer too much. Music is rarely exercised so it's not a good trigger. It's a really
    cool novelty. Demos well. When needed it's beautiful." Shared rooms: "don't do it when someone is already in that
    room including in your own room. Shares spaces, likely same."
  - Phase 2 evidence: "They need about 10 weeks. Foul. Why that long?" (gates sized to real error rates, not calendar).

## Drift found, and the correction

| # | Operator said | How it drifted | Correction (status) |
|---|---|---|---|
| 1 | Vision assists census accuracy, arrivals, personalization | Phase 2 became a hold that only delayed AWAY (rev 3-5). Three reviews made it safe; none asked whether it was the goal | Rejected by operator. Rev 7: census split by use, awareness view, vision feeds census with deconfliction (done, re-reviewed 1e76c98a) |
| 2 | AWAY must stay fast | The hold design would have delayed AWAY | Hard invariant INV-P2-AWAY-LATENCY; AWAY reads the trust view only (done) |
| 3 | "Your not ready doesn't hold up. It depends on error rates you don't have" | A per-frame guard bar (29/30) blocked Phase 2 though the build used a set-level guard | Gate removed; go/no-go on measured ledger drift, arrival match, group walks (done) |
| 4 | Census accuracy with vision + NVR deconfliction | Rev 6 put vision in separate sensors, census untouched | Census split by use (rev 7); one dedup function `deconflict_house` (arc map M2) |
| 5 | Two-stage latency design with simulation | Parked; shrank to a lever list | Restored in rev 7 with a timing simulation gate (done) |
| 6 | Egress should name arrivals | EGRESS-DIRECTION-AWARE-IDENTITY-1 planned, unbuilt; arrival accuracy capped at ~30% named | Sequenced in the arc map; F-NOTIFY blocked on it (done in plan) |
| 7 | Personalization | Suggestion class folded away | Named consumer of the awareness view (rev 7) |
| 8 | Interior vision | Recommended "not now" | Carded VISION-INTERIOR-SIGHTINGS-1 in the arc |
| 9 | Settings accuracy, labels, config-flow entries | PERIMETER-SWITCH-LABELS-AND-FLOW-PARITY-1 not started | Sequenced after perimeter Part A (pending) |
| 10 | Agnostic fixes | PTZ fix keyed on one camera; panel watchdog keyed on Frigate | Vision location check (camera-agnostic); KS app-health watchdog (homelab) |
| 11 | The F1-F5 framework | Lost in compaction | Restored in CLAUDE.md + memory; every plan states its F and consumer classes |
| 12 | "Census and sightings never feed each other" | Rule outlived its purpose (face double counting) and blocked interior vision | Retired; replaced by one dedup-by-evidence function |
| 13 | Clean plans, no seams | Crossing-vision plan stacked rev 3-7 with override sections; several plans changed the same seams | Arc map merge analysis; clean rewrite + equivalence review before approval (pending) |
| 14 | Facts in plans | Planner asserted the residency producer was dead and the lock fix undeployed | Orchestrator verified and corrected before review |
| 15 | "if even one nvr has the cam it doesn't count as dead"; "exercise both nvr platforms" | Stream health (S1 develop, S2 batch-2) judges dead per camera ENTITY; the W1 Frigate-to-sibling pairing in camera_resolver.py is never consulted, so a dead Frigate entity with a live Protect twin is held / released and can block the ledger anchor | Card: fold liveness across the W1 pair (2026-11-14 drift check, open) |
| 16 | "consumers can read and producers can feed"; "no leaks" | Read half built (ship 1 develop, ship 2 batch-2); the ingest half (dispatch_person_arriving, G1-G6, G9, attach_crossing_attribute), the layer guard test and the push registry exist only in the contract, while step 7 and step 8 plans add producers | Recommend ship 3 (ingest + guard) before the step 7 build (2026-11-14, operator asked) |
| 17 | "Don't want to defer too much... not a good trigger" | Step 8 parked the profile extras behind two weeks of arrival-music episodes, which rarely fire | Pull bedroom/bathroom/owners, per-room and time-of-day playlists, per-action opt-in and welcome scene into step 8 (proposed 2026-11-14) |
| 18 | Charter completeness | Music/room rules, v6.0.0, dual NVR, registry, alert latency, windows and naming lived only on cards and in CLAUDE.md | Recorded above (2026-11-14) |
| 20 | "The layer was just a prereq" (2026-11-14 16:45) | The afternoon went to the layer: three ship 3 plan revisions, a 3a/3b split, 60 guard rulings, leak sizing. Meanwhile the arc deliverables it unblocks did not move. Step 8 (v6.0.0, "get a move on") sat at plan rev 3.1 with no re-review and no build. Music repair ("features die... day 1") was fixed but not shipped. The interior-vision plan ("I want this tight and not deferred") has never been reviewed. | Back to the arc (2026-11-14 16:50). Ship 3a builds now, leak cleanup is carded behind the arc (LAYER-LEAK-CLEANUP-1), and the order is music ship, then step 8 re-review plus its parallel D0/D1 build, then interior-vision plan review. |
| 21 | Dead-camera rule ("a stale NVR reading never counts") | Four review rounds kept finding HIGHs in per-reader coverage, a risk-reduction loop on a feature that may never fire | Operator chose option A (pages and house-wide camera health), with coverage parked behind a measured trigger (DEAD-CAMERA-TWIN-COVERAGE-1). That is a recorded tradeoff, not silent drift |
| 22 | Unplanned test-hygiene work | Order-dependent test leaks blocked batch 2 and census-p2 twice (about 3 h) | Fixed at the source each time, with the remainder carded on TEST-SUITE-POLLUTION-AND-STALE-DRILLS-1. No arc scope changed |
| 19 | Questions answered | Six operator questions from 11-13/11-14 went unanswered (perimeter gates off by design, AI person check and config-flow parity, dynamic masks, fan veto on NVR pairing and NVR-down, stream-health purpose and snapshot count) | Prober answering (2026-11-14) |

## Root causes

1. **Reviews checked safety and correctness, never goal fidelity.** The AWAY-hold design passed every framing.
2. **Planners resolved goal-vs-risk tradeoffs themselves** instead of surfacing them (hold AWAY to avoid risk).
3. **Silent deferral.** Hard pieces (two-stage latency, egress naming, interior vision) were parked without the
   operator choosing to park them.
4. **Compaction strips the framework and verbatim goals**; the board kept decisions, not the "why".
5. **Revisions layer instead of rewrite**, so earlier designs stay in the builder's path.
6. **Plans are scoped per card, not per seam**, so parallel plans change the same contract.
7. **Stale facts propagate**: planners trust earlier summaries instead of checking deploy state.

## Anti-drift rules for ambitious arcs

1. **Arc charter.** Each ambitious arc has one charter doc: operator goals verbatim, hard constraints, non-goals,
   the model it lives in (F1-F5 here). Every plan, review and builder brief links it and is re-read against it.
2. **Goal-fidelity review framing.** Every Tier 3 plan review includes a framing whose only question is: does this
   deliver the charter's goals, and does it violate a hard constraint? Safety framings alone cannot catch drift.
3. **Tradeoffs go to the operator.** When reducing risk would change what is delivered, the planner names the
   tradeoff and the orchestrator asks; the planner never picks the safer-but-different product.
4. **No silent deferral.** Parking any piece of a charter goal needs the operator's yes and a card with a trigger;
   the arc-close gate checks it.
5. **One clean document per scope.** Plans are rewritten, not layered; history moves to an archive file; a reviewer
   confirms equivalence before approval.
6. **Arc map and seam check.** A new card or plan in the arc runs the merge check (same function, field or contract
   = merge unless reasoned otherwise) against the arc map.
7. **Drift check at milestones.** At each plan approval, ship, and after compaction: compare in-flight plans with
   the charter and report a drift table like the one above.
8. **Verify facts before dispatch.** Deploy state, live values and code claims in a brief are checked, not carried
   from summaries.
9. **Verbatim operator quotes on the card** for every goal-shaping decision (the `operator_<date>_*` fields).

## Suggested mechanism

A `ura-arc` skill that loads the charter and arc map, runs the drift check, and is invoked at plan dispatch, plan
approval, ship and session start for any arc marked ambitious. The charter for this arc is the "operator's goals"
section above until it gets its own file.
