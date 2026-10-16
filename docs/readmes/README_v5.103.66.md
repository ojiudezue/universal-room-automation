# v5.103.66: Reserve write governor (EC-RESERVE-WRITE-GOVERNOR-1)

**Tier 3.** Four framing-disjoint reviews: A SHIP, B SHIP, C FIX (test gaps), D FIX. All findings were fixed and each fix drilled with a source mutation. Orchestrator re-grep plus 3 own drills, all RED. Operator checkpoint: "Deploy" (2026-10-16). Arc step 1 of `docs/planning/ARC_energy_coordinator_resilience.md`.

## Problem
- The battery reserve was written from about 25 decision branches and 13 `set_value` call sites.
  - 470 writes went to `number.iq_battery_hacs_battery_reserve` in 7 days.
  - Few of them left a record of what was sent or why.
- The inclement-weather floor was enforced branch by branch, and three plan reviews kept finding branches that leaked below it.
- Nothing stopped a new code path from writing the reserve without being seen.

## Solution
- **One floor at `_result`:** the inclement partial-hold floor (`max(reserve_soc, reserve_floor)`) is registered once, at the single exit every decision goes through.
- **Truthful `reserve_write` activity rows at the real dispatch points:** the timer tap (C1), `_evaluate_battery` (C2) and force_redispatch (C3).
  - Each row carries status (`hvac_strategy.WriteStatus`), path, value, desire, hold owner, inclement floor and floor_ok.
  - Change gate: an identical key plus a hardware value already matching means no duplicate row. Redispatch and FAILED rows are never gated. A FAILED row does not arm the gate, so the recovery that follows is always logged.
  - The row writer can never raise into dispatch.
- **Bypass lint:** an AST test pins every reserve `set_value` writer (`energy_const.RESERVE_SET_VALUE_WRITERS`), including the mixed positional/keyword `async_call` form.
- **Optimizer hard deny (D-2):** the Optimization Coordinator can never write either battery-reserve entity.
  - It covers both the device-dispatch and the config-dispatch paths, and it applies even when the operator's deny list is empty.
  - A denied attempt is refused with an outcome of DISALLOWED, a `reserve_role_hard_deny` activity row and a WARNING.
- **Restart:** uses the existing `wv_commanded_ledger`; no new persistence.
- **Byte-identical decisions:** an A/B golden fixture, committed before the build, proves the reserve decisions are unchanged.

## Known limits
- If the kind of request changes but the value doesn't, that change gets no row (D-3).
- The timer path writes no rows unless the WriteVerifier is active (B-L2).
- Each TOU transition logs about 2 rows (B-L1).

## Tests
- Governor tests: 86 passed. The A/B golden fixture is unchanged.
- Full suite: 115 failed / 15103 passed, against the develop baseline of 119 / 15013.
  - One failure is new against the baseline: a timing-sensitive test in `test_deploy_scripts.py`. On a re-run a different test in that file failed instead. The branch doesn't touch the deploy scripts.

## Live validation (prospective)
- **Live:** within 1 h of a reserve change, `ura_activity_log` has a `reserve_write` row with non-null value, path and status, not sentinels.
- **Live:** the reserve behaviour is unchanged. The `battery_strategy` sensor and the reserve values look the same as before the restart.
- **Live:** there are 0 URA ERRORs mentioning reserve_write or hard_deny.
- **Live:** the Envoy reconnects after the restart.
