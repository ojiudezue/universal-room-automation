# Plan review: interior ledger floor §1b closure (completeness + build-prediction + G), 2026-11-17

Commit 352c7e7bf; anchors re-read on 335bf1284.

**Verdict: PLAN-FIX-REQUIRED** (two text fixes; no redesign)

## Prior findings
All 12 are closed in the spec text, not only in the closure map. The anchors hold: `crossing_ledger.py:45,239-240,298,345,352,403,446,515,57-60,71`; `crossing_vision.py:1859,2075,2429`; `const.py:2429,3510,3875,3883,3889,3896,7287,7331,7355-7356`; `_layer_guard_engine.py:245-247`. §6.2 now has row 9.

## New findings
| # | Sev | Finding |
|---|---|---|
| 1 | MED | **F-K cannot be measured as specified.** `set_unknown` (`crossing_ledger.py:325-329`) and `_ledger_disabled` (`crossing_vision.py:1788-1801`, reasons switch_off, kill and cap_zero) emit no `LedgerEvent` and write no row. The phrase "to the next ... `ledger_disabled` / `set_unknown`" therefore points at rows that do not exist. A mid-day cap_zero would count as known time and overstate F-K. Fix: name the source. Either add an unknown-transition row (a small Tier-3 touch) or use the first later `term` row with `reason=unknown` as the end bound, and state the error. |
| 2 | MED | **The expected numbers are misread.** In the audit's simulation (§4), "no restarts" means the ledger stays known forever after the first anchor. The 43.5/54.3 % figure is the share of the window that falls after that first anchor (11-13). It is not a ceiling set by occupancy. Over a longer window with no restarts, known time approaches 100 %. The line "between 28 % and 54 % under (c)" is not derived: 28 % is the restore result at 4 restarts a day. Restate the (c) expectation honestly as "not simulated; depends on whether the daily restart lands before or after that day's anchor (anchors occur on 4 of 7 days)". The line "25 % is the floor below which F-c cannot reach" is also unsupported. |
| 3 | LOW | (a)'s revival trigger depends on "lost known-time", which needs a counterfactual simulation. Define it as the audit's §2 "known-time destroyed" sum. |
| 4 | LOW | F-K is listed under "evaluated per strategy" but does not depend on strategy. |

## Rule consistency
Parking (a) follows "only proven code supersedes correct code". (b) keeps dead inputs holding, which follows the dead-camera rule.

## G
Pass. The floor feeds census and the ledger, not presence. It is display only, and the strategy Select is kept. **Tradeoff to name:** F-K changes *whether* the floor ships, not *what* it does. If restart discipline slips, the floor and the operator's "test in parallel" stay parked indefinitely. Q-F1/Q-F3 give the operator this choice, so state it there in those words.
