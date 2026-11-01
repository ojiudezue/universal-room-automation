# Review C - test authority (real per-site mutation), fix/ble-grace-fleet-fraction b13a151ea (base 338908dd7)

Method: detached worktree .claude/worktrees/revC-b13a1; one production-source edit at a time, PYTHONDONTWRITEBYTECODE=1, __pycache__ cleared per run, 5 target test files (baseline 137 passed, 3 deselected), `-x`, file restored after each (try/finally), worktree status clean (only the drill script, removed). Mutations: 6 GREEN, the rest RED (all drill output in-session).

## RED (all others) - first failing test
- coordinator `_ble_absent_since` clear x8 sites, `_ble_grace_used` clear x7 sites: each RED (test_override_vacant_and_recheck_release_clear_stamp[*], test_present_tick_resets_absence_stamp, test_d2_demotion_ends_ble_only_episode, test_grace_used_resets_only_on_episode_end)
- grace helper: ENABLED gate, GRACE_S<=0 gate, chain-unbroken, ble_only anchor, cap refuse, window boundary, used refuse, open-sets absent_since / grace_used: all RED (test_ble_absence_grace.py)
- cap helper: enabled gate, fail-open None, `> cap`, room-type default: RED
- grace branch: elif removal, source label, ble_persons, timeout_remaining, ble_absence_grace flag, STATE_OCCUPIED: RED (test_single_empty_tick_holds_ble_chain)
- present-branch cap via shared helper: RED (test_grace_branch_never_fires_cap_nm_or_moves_anchor)
- person_coordinator: prune cutoff/future/undated, load no-op, save, raise-only, fold append, warm prior-day, warm eid, max remembered, ABS_MIN, cold legacy, assign effective, save-on-change, non-numeric guard, latch uses _effective_floor, tick call: RED (test_person_ble_fleet_fraction.py)
- __init__ load-before-first-refresh (line removed): RED test_first_refresh_sees_restored_ring

## GREEN (untested sites)
| # | Mutation | Sev | Note |
|---|---|---|---|
| 1 | `__init__.py:3099` call site `_async_start_person_coordinator(` -> undefined name | MEDIUM | Helper is tested, the wire-in at the setup call site is not (wire-in anchor rule; a revert to the old inline construct would silently drop the restore). Needs a test that drives async_setup_entry path or a source-order anchor that detaches the call. |
| 2 | `math.ceil` -> `math.floor` (person_coordinator `_update_fleet_floor`) | MEDIUM | No test uses an odd remembered fleet where ceil != floor at the 0.5 fraction. Add case e.g. R=61 -> 31 vs 30 and R=5 vs ABS_MIN. |
| 3 | `_local_date`: `dt_util.as_local(now).date()` -> `now.date()` | LOW | No test straddles local midnight with a non-local tz. |
| 4 | `_prune_fleet_memory` sort removed | LOW | Equivalent for max()/membership; only changes persisted order. Likely equivalent mutant. |
| 5 | `async_load_fleet_memory` `ring = []` reset in except removed | LOW | A malformed later entry keeps earlier parsed entries instead of empty ring (partial restore). Corrupt-store tests use cases where the first entry fails. Add a [good, bad] payload case. |
| 6 | person_coordinator ctor `_effective_floor` init 99 | LOW | Effectively equivalent (overwritten before first use); only the pre-first-tick window differs. Not worth a test. |

## Verdict: FIX-REQUIRED (MEDIUM x2, cheap)
Must-fix: (1) a test anchoring the `__init__` call site, (2) an odd-fleet ceil boundary test. LOWs (#3, #5) fix in-cycle; #4/#6 equivalent, no action.
