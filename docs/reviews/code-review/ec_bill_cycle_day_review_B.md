# EC-BILL-CYCLE-DAY-WIRED-1 — Review B (async / lifecycle / reload-suppression / restart / test authority)

Branch `fix/ec-bill-cycle-day-wired` @ 00c394da5, base = merge-base e0beb6f82 (three-dot verified).
Not HVAC/presence scope; state-of-play docs not required.

## Findings

| ID | Sev | Site | Class | Finding |
|---|---|---|---|---|
| B1 | MEDIUM | `domain_coordinators/energy.py:11390` | Untracked background task (supersession) | `set_bill_cycle_day` overwrites `_bill_cycle_reseed_task` without cancelling a still-running prior task. Two saves in quick succession (day 23→15, then 15→10) leave task#1 orphaned: teardown (`:11754`) cancels only the latest, and task#1 began with the day-15 window. If its DB read completes after task#2's, `reseed_cycle` writes the day-15 window totals last, so `cost_this_cycle` is stale until the next restart or boundary. Fix: cancel the prior task before you create the new one (2 lines). |
| B2 | LOW | `energy.py:11754` | Hollow lifecycle coverage | The teardown cancel is untested. Mutation M3 (cancel → `pass`) left the suite GREEN (195 passed). |
| B3 | LOW (pre-existing) | `__init__.py:8639` fall-through | Mixed-save drop | One save that changes this key plus a non-allowlisted, non-EC-construction key goes to the CM reload. The CM reload does not rebuild the EC (the EC is built in parent setup; see comment at `__init__.py:8619`). The new day is then applied only at the next parent reload or restart. Every `_EC_SETTER_DISPATCH` key behaves the same way, so this is not a regression. With an EC construction key in the same save, the parent reload fires (`:8624-8637`). The rebuild then reads the day through `energy_entity_config` (`__init__.py:3821-3823` → `energy.py` ctor), so that case is correct. The setter never double-applies: the in-place path and the reload path are mutually exclusive. |
| B4 | LOW | `energy.py:11395-11403` | Day-boundary-blind | `now` is captured before the await, and the query end is `now.date()`. If the await spans local midnight, today's accumulators are reset and yesterday's `energy_daily` row falls outside the query, so yesterday drops from the cycle total until restart. The window is milliseconds wide. Note only. |

## Cleared

- **Reseed vs. decision-cycle accumulate:** holds. `reseed_cycle` (`energy_billing.py:560-569`) is synchronous after the single await and reads the live `_*_today` accumulators. Ticks that land during the DB read are folded into "today", and none are overwritten. The decision cycle gains no await.
- **No-op path:** byte-identical. Same day → `changed=False` → no task, no re-key (`test_coordinator_setter_unchanged_day_schedules_nothing`).
- **Re-key without wipe:** `_cycle_start_date` is re-keyed to the new boundary, so `_check_cycle_reset` (`energy_billing.py:517-527`) does not zero the running cycle. Drill M2 below confirms this.
- **Restart:** the ctor clamps the key from options. `_restore_cycle_from_db` (`energy.py:1564`) and the PA snapshot restore (`energy_billing.py:1020-1036`) both key on the new day. PA persists its re-keyed `cycle_start_date`, so after a live change it survives a restart.
- **Snapshot bookkeeping:** the key joins `applied` only after the setter returns, so partial-apply re-diff semantics are intact.
- **Four hand-written stub lists:** the pattern predates this branch. `_verify_hand_typed_conf_literals` and the count assert (111) guard drift. The new test module drives the real package (`_apply_in_place` on a real `EnergyCoordinator`), so the authority is real. The existing maintenance trap stays as it was; this branch adds nothing to it.

## Mutation drills

Each drill ran the 5 related files, 195 tests, with `PYTHONDONTWRITEBYTECODE=1` and `__pycache__` cleared. The tree was restored after each and `git status` was clean.

| Mutation | Result |
|---|---|
| M1: drop `bill_cycle_day=` from the CostTracker ctor | RED: 7 tests, including `test_cost_tracker_uses_configured_cycle_day` |
| M2: drop the `_cycle_start_date` re-key in `CostTracker.set_bill_cycle_day` | RED: `test_mid_cycle_change_rekeys_without_wiping`, `test_new_boundary_resets_on_the_new_day_only` |
| M3: drop the teardown `_reseed.cancel()` | GREEN, recorded as finding B2 |

## Verdict

**FIX-REQUIRED (small):** B1 must be fixed. Cancel the prior reseed task in `set_bill_cycle_day` before you create the new one. B2 should be fixed in the same pass: add a test that tears down with the task in flight and asserts it was cancelled. B3 and B4 can be accepted or carded.
