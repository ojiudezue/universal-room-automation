# Code Review — OC Phase 5 Pillar A: Sibling-Coordinator Handshake

**Branch:** `feature/oc-pillar-a-handshake` (350f9b3 build → bbfa0fa fix-up → 4da0103 4th-pass)
**Plan:** `docs/planning/PLANNING_OC_phase5_handshake_and_admin_surface.md` Pillar A (D7/D8)
**Protocol:** Tier 2-DB — 3 framing-disjoint reviews + focused 4th pass. **Date:** 2026-06-10

## Findings ledger (deduped)

| ID | Sev | Finding | Status |
|---|---|---|---|
| A-C1 / C-C1 | CRITICAL | Veto loop never closed at L2: `await_veto` only called for propose_config, so sibling vetoes were purged unread AFTER the action ran — handshake advisory-only where the plan requires blocking. Masked by tests that never drove the broker end-to-end. | FIXED (bbfa0fa) — always await (zero-window harvests sync vetoes), outcome=vetoed recorded, service call skipped; real-broker e2e test |
| B-H1 | HIGH | L1 NOT inert: shadow intents dispatch on the live house and the new handlers fired real veto messages + INFO per finding per cycle | FIXED — handlers early-return (DEBUG only) at advisory/shadow, before any entity-resolution work |
| B-H2 / C-C2 / C-C4 | HIGH | Vacuous tests: inertness test proved payload shape not silence; double-subscribe tests asserted a sentinel equals itself; L1 gate test echoed its own input | FIXED — real-dispatcher zero-traffic assertion; subscribe path driven twice; production resolver exercised |
| A-H1 / C-C3 | HIGH | "Load-shed coverage equivalence" false: shed-controlled plugs not vetoed; EVSE veto fired only at off_peak (shedding runs at peak); EVSE `span_breaker` switches escaped the net | FIXED — breaker + shed-set (any period) + shed-active windows; claim retracted |
| 4th-H1 | HIGH | `_on_veto` lacked `@callback` — dispatcher could run it off-loop, defeating the synchronous-harvest contract + threading on `_pending_vetoes` (HA dispatcher semantics unverifiable offline; decorator is the safe, standard fix) | FIXED (4da0103) |
| A-M1 / B-M2 | MEDIUM | Veto inputs failed OPEN (TOU exception → allow) | FIXED — fail-closed on EVSE surfaces + rate-limited WARN |
| A-M2 | MEDIUM | Battery-writeable ids retained at init (#14 staleness under reload suppression) | FIXED — resolved fresh per call |
| B-M1 / C-C7 | MEDIUM | Teardown never reset `_optimizer_intent_unsub` → re-setup on same instance permanently veto-deaf | FIXED — reset in all three coordinators |
| C-C5 | MEDIUM | Energy/Presence handler payloads untested; no real-dispatcher wiring test | FIXED |
| C-C6 | MEDIUM | Veto attribution nondeterministic (last-writer-wins) | FIXED — first-veto-wins |
| 4th-M1 | MEDIUM | Shed veto omitted `_paused_by_battery_drain` plugs | FIXED (4da0103) |
| Re-contract | — | Pre-existing `test_optimizer_pending_veto_discarded_on_success` encoded the advisory-only semantics (and seeded a naive timestamp that crashed eviction under aware suite mocks) | RE-CONTRACTED to blocking semantics; `_evict_stale_vetoes` gained naive/aware tolerance (this week's recurring bug class) + overflow-sort key fix (4th-L1) |
| A-L1/L2, B-L1/L2, C-C8, 4th-L2 | LOW | Sync-contract deviation (documented); observation_mode blanket freezes optimizer house-wide (plan-faithful — operator awareness, see README); availability-poll lag; partial-set fallback in `_resolve_battery_writeables_live` | ACCEPTED/documented |

**Also in 4da0103 (operator-requested, 2026-06-10):** optimizer `status` recalibrated — "critical" reserved for critical-severity open findings; HIGH piles read "degraded" (live case: 5 dead-sensor HIGHs at house_score 55 read "critical" and "made it not as useful"). Lock-test reproduces the live case.

## Statistics
CRITICAL 1/1 · HIGH 4/4 · MEDIUM 6/6 fixed · LOW 6 accepted/documented. Suite: 5552 / 44 / 14 / 29 — baseline-exact, +40 cycle tests.

## QUALITY_CONTEXT recommendations
1. **Vacuous-test smell**: any test asserting a sentinel it just set, or echoing its own input through the code under test, certifies nothing — require the production path in the call chain.
2. Reinforce #44 (mock-masked dead path): the CRITICAL here survived 20 green tests because none drove intent→veto→outcome through the real broker.
