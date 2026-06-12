# Code Review — Fan-Trust State Extension (sleep → home_night/waking)

**Branch:** `feature/fan-trust-state-extension` (e4088f7 build → a9801fe legacy re-contract → 491138c consolidated fix-up)
**Plan:** `docs/planning/PLANNING_fan_trust_state_extension.md` (+ operator amendments + §12 decisions)
**Protocol:** Operator-mandated Tier 2-DB — 3 framing-disjoint reviews + focused 4th pass. **Date:** 2026-06-11

**Operator intent:** extend fan STOP control (blip protection) beyond sleep; supreme criterion: "If there is no one there, we want it away for sure and especially for HVAC."

## The design correction the panel forced
The build extended ALL four sleep-gated sites — including the fan **auto-activation** side, which the operator never asked for. Reviewers A and B independently showed the consequences (21:00 house-wide flip-on; house-level "person home" proxy holding fans in empty rooms for hours — sound at sleep where home⇒in-bed, wrong at home_night where people roam). Final shape: **stop-protection + zone preset-trust + speed cap extend; activation stays sleep-only.**

## Findings ledger (deduped)
| ID | Sev | Finding | Status |
|---|---|---|---|
| B-C1 / A-H2 | CRITICAL/HIGH | Empty-room indefinite hold at home_night: zone/house-level person evidence applied to room-level fan decisions; only release was the person leaving the HOUSE | FIXED (491138c) — flank states require bedroom room-type; sleep keeps v4.7.13 zone-proxy; supreme-criterion test passes |
| B-H2 | HIGH | ON-side activated fans temperature-unconditionally at 21:00 across all occupied bedrooms (daily flap + energy) | FIXED — ON-side reverted to sleep-only (operator asked for stop control, not start) |
| A-H1 / B-H1 / C-3 | HIGH | `fan_sleep_policy=off` honored by nobody on coordinator-managed rooms (room-level off-path dead via automation.py:1509 early-return) AND the build had silently removed even the LOW cap for off rooms; dueling-writers flap risk | FIXED — ON-side excludes policy=off (incl. at sleep); off→conservative LOW cap; live per-tick policy read (A-M2); dead room-path flagged in-code as pre-existing backlog |
| C-1 | HIGH | All 24 behavioral tests skipped in the full suite — zero real-path coverage at the deploy gate | FIXED — `_is_stub_module` force-upgrade loader; 24 skips → executions (proof: polluter-pair run 75/75); 4th pass verified the predicate cannot clobber disk-loaded real modules |
| C-2 | HIGH | Mirror cap tests (copy-pasted logic) + a sentinel-equals-itself test | FIXED — rewritten production-path |
| A-M1 | MEDIUM | Cap not bedroom-gated: LOW-capped living-room fan during home_night TV | FIXED — cap bedrooms-only at flank states, house-wide at sleep |
| B-M1 | MEDIUM | Mode-2 pause vs trust-activated fans at home_night (recreating the "disconcerting pause" while awake) | RESOLVED by ON-side revert (no trust-activated fans outside sleep) |
| A-M2 | MEDIUM | Policy frozen at discover_fans | FIXED — live read, exception-safe cached fallback |
| C-4 | MEDIUM | My own 4000-char window re-contract was too generous (3 `continue`s in range — guard removal would pass) | FIXED — re-anchored on the trust predicate, 2400 chars (4th pass: tighter than the original) |
| C-5 | MEDIUM | Loader del/reassigned a shared sys.modules key | FIXED — stub-detection upgrade path; no real-module clobber |
| A-L1 | LOW | Zone-trust suppression INFO ~12/hr/zone all night | FIXED — DEBUG one-shot per (zone,state), cleared on state change (re-INFOs once nightly) |
| C-6 | MEDIUM | Named coverage gaps (transition chains, restart, policy precedence) | FIXED — 6 new tests; restart test honestly scoped |
| A-L2 | LOW | Original incident also mentioned home_evening/guest flips — not covered | ACCEPTED — intentional scope (plan §8); revisit if live shows flips there |
| B-L1 | LOW | Zone preset-trust holds comfort for hours when person is elsewhere in-house | ACCEPTED — operator's live-bug fix outweighs; preset-hold not actuation |
| 4th-M1 | MEDIUM | policy=off rooms still temp-activated at sleep via the STANDARD path (trust exclusion only gates the trust branch) | BACKLOG — documented in-code; conservative cap mitigates |
| 4th-L1 | LOW | The 5 pollution fixes depend on alphabetical collection order | ACCEPTED — noted; loader is order-immune for THIS file's own tests |

## Statistics
CRITICAL 1/1 · HIGH 4/4 · MEDIUM 5/5 fixed (1 new backlog) · LOW 4 (1 fixed, 3 accepted). Suite: **37 failed / 5638 passed / 14 errors — net −7 vs develop** (5 pre-existing pollution failures legitimately fixed by the loader, empirically verified at baseline + tip), zero new failures.

## QUALITY_CONTEXT recommendations
1. **Trust-scope mismatch** (new class candidate): evidence valid at one scope (house/zone "person home") applied to a finer-scope decision (room-level actuation) — sound only when the coarse scope implies the fine one (sleep⇒in-bed). State extensions must re-derive the implication.
2. **Skip-gated tests are decorative until proven executing**: any `skipif` behavioral suite must carry an execution-count proof in the cycle's gate evidence.

## Operator revision 2 (2026-06-11, post-review — commit 2077832 on develop)

Operator clarified the product model: **fan actuation is temperature-driven
only, never house-state-driven — at sleep included.** The pre-existing
hotfix-B `sleep_occupied_activate` (occupied bedroom + off fan → ON at LOW,
temp-unconditional; an add-on to the June-1 OFF-side incident fix) was
REMOVED entirely. Rationale: seasonally wrong in winter; fights manual-off
after the 1h cooldown; manual-on is one tap and the HOLD then blip-protects
it. Final contract: ON = on (hold-protected through home_night/sleep/waking);
OFF = stays off unless temperature demands; manual actions always win.
Tests re-contracted (cool occupied bedroom at sleep stays OFF; warm one
starts via the temp path; emitted-label-form source guards).
