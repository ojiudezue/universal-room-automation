# Bug Class #48 Sprint — Cycle Link Doc

Bug Class #48 (transient-vs-reliable arbitration / signal-trust hierarchy) is a multi-cycle sprint. This doc tracks every cycle that contributes to the canonical helper. New cycles append here.

## Definition

**Bug Class #48 — Transient-vs-reliable arbitration.** When a transient presence signal (camera burst, mmWave bounce, PIR blip) disagrees with a persistent/reliable signal (person tracker, zone_persons aggregator, BLE proximity), the reliable signal should win — but only when its trust conditions are met (tracker not stale, phone not left behind, census not seeing a face, etc.). The canonical helper lives in `domain_coordinators/presence.py::PresenceCoordinator.should_veto_due_to_reliable_signals` with per-scope `Pattern A..F` dispatch.

## Cycle list

| Cycle | Status | Scope | Pattern | Summary |
|---|---|---|---|---|
| v4.7.13 | shipped | sleep-state zone presence | Pattern B (`zone_aggregator` SLEEP fallback) | First reliable-signal veto: zone_persons=home during SLEEP overrides quiet room sensors. |
| v4.7.14 | shipped | house inference AWAY | inline at `StateInferenceEngine.infer()` | Person-tracker all-away vetoes camera ghost presence. Pre-helper: logic inline in `infer()`. |
| v4.7.14.1 | shipped | house inference AWAY tightening | inline H1+H2+H3 | H1: `census_count == 0` predicate. H2: exclude `phone_left_behind=on` persons. H3: exclude STALE/LOST `tracking_status` persons. Production semantics canonical for veto trust; still inline in `_run_inference` (not yet consumed by helper). |
| v4.7.15 | shipped | helper extraction + multi-scope | Patterns A/B/C/D/E in `should_veto_due_to_reliable_signals` | D1 extracts the public helper + `VetoDecision`/`ReliableSignal`/`TransientSignal` dataclasses. D2 adds Pattern C (zone aggregator non-sleep). D3 adds Patterns D (WAKING gate) + E (GUEST exit). D4 relocates `check_zone_occupancy_confidence`. D5 `signal_consensus` sensor + mirror. D6 HVAC/compliance defer gates. **Pattern A in the helper does NOT yet consume v4.7.14.1 H1/H2/H3 — a parallel diagnostic-only invocation in `_run_inference` covers the gap.** |
| **v4.7.15.1** | **THIS CYCLE — Tier 2-DB** | consolidation | Pattern A consumes H1/H2/H3 | Refactor Pattern A to accept `census_count` (transient), `person_phone_trustworthy` (reliable, per-person), `person_tracking_active` (reliable, per-person). The v4.7.14.1 inline `_phone_trustworthy` / `_tracking_active` helpers become input builders for the consolidated helper call. The parallel diagnostic invocation is deleted. Source invariants in `test_v4715_universalize_veto.py::TestSiblingCyclePreservation` are re-baselined against post-v4.7.14.1 canonical truth. v4.7.14.1 in-test mirrors deleted with behavioral replacements driving the production helper. |
| v4.7.16 | future | room-level density | Pattern F (`room_level_weighted`) | Diagnostic-only stub today (fall-through `fired=False`). v4.7.17+ flips to gating once consensus calibration data is collected. |

## Cross-references

- Primary plan: `docs/planning/PLANNING_v4.7.15.1_pattern_a_consumes_v4_7_14_1.md`
- v4.7.15 plan: `docs/planning/PLANNING_v4.7.15_universalize_bug_class_48_veto.md`
- v4.7.14.1 plan: `docs/planning/PLANNING_v4.7.14.1_forgotten_phone_hotfix.md`
- v4.7.14 plan: `docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md`
- v4.7.13 plan: see Phase A sprint memos
- Reviewer C of v4.7.14.1 §C4 merge-order instructions (load-bearing for v4.7.15.1): `docs/reviews/code-review/v4.7.14.1_review_C_test_authority_merge_risk.md`

## Quality gate

Tier 2-DB review protocol (three parallel reviewers, disjoint framings — see CLAUDE.md and `feedback_db_sensitive_3x_targeted_reviews.md`):

- **Reviewer A** — Correctness of refactored Pattern A + filtered tracked_count flow + source-invariant honesty
- **Reviewer B** — Signal-chain integrity + diagnostic surface preservation + write-ordering of `_last_veto_decision`
- **Reviewer C** — Test fixture authority (Bug Class #44) + integration-branch merge fidelity
