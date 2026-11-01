# Review C - EC reserve false-revert fix-up (80b755e45, base 8e2e9b7b7) - test authority via per-site source mutation

Method: detached worktree, one production-source mutation at a time, suites
test_ec_reserve_false_revert_fixup.py + test_ec_reserve_oracle_phase2.py +
test_energy_write_verification.py (248 passed baseline), pycache cleared per run, restored in finally,
git status clean after. Worktree removed.

| # | Site mutated | Result | First failing test |
|---|---|---|---|
| M1 | step call in _sweep_surface removed | RED | test_witnessed_then_envoy_drop_no_page |
| M2 | gate or-clause in sweep removed | RED | test_witnessed_then_envoy_drop_no_page |
| M3 | kill switch ignored in step | RED | test_kill_switch_byte_identical |
| M4 | kill switch ignored in gate | RED | test_kill_switch_off_after_stamp_helper_false |
| M5 | no-ledger clear removed | GREEN | - |
| M6 | local None wrongly clears | RED | test_witnessed_then_envoy_drop_no_page |
| M7 | deadband < to <= | RED | test_deadband_boundary_no_stamp[17] |
| M8 | restamp cond: mem.value != cmd dropped | GREEN | - |
| M9 | restamp cond: first_at < cmd_at dropped | RED | test_same_value_newer_stamp_rewitness_restamps |
| M10 | last_at refresh removed | RED | test_witnessed_then_envoy_drop_no_page |
| M11 | raw None still stamps | RED | test_x4_oracle_unset_no_stamp_no_emit |
| M12 | contrary-reading clear removed | RED | test_contrary_local_clears_memory |
| M13 | cloud_at_first = cmd not raw | RED | test_witnessed_then_envoy_drop_no_page |
| M14 | gate: mem.value mismatch dropped | RED | test_memory_value_mismatch_never_qualifies |
| M15 | gate: first_at < commanded_at dropped | RED | test_ledger_same_value_newer_stamp_invalidates_memory |
| M16 | gate: sweep_witness None returns True | GREEN | - |
| M17 | gate: sw cmd/at ledger match dropped | GREEN | - |
| M18 | gate: reason != "unavailable" dropped | RED | test_low_soc_guard_neither_stamps_nor_qualifies |
| M19 | gate: cloud == V compare -> True | RED | test_cloud_moved_after_command_pages |
| M20 | gate: oracle_raw None guard dropped | GREEN (equivalent: float(None) raises, caught -> False) | - |
| M21 | gate: tz-naive guard dropped | GREEN (equivalent: naive/aware compare raises, caught -> False) | - |
| M22 | pending-episode guard dropped | RED | test_pending_episode_still_wins |
| M23 | const RESERVE_WITNESS_MEMORY_ENABLED default False | RED | test_witnessed_then_envoy_drop_no_page |
| M24-27 | each of 4 attribute outputs removed | RED | test_witnessed_then_envoy_drop_no_page (attrs asserted) |
| M28 | per-sweep _sweep_witness = None reset removed | GREEN | - |
| M29 | _sweep_witness not cached | RED | test_witnessed_then_envoy_drop_no_page |
| M30 | soc not passed to trusted_local_reserve | RED | test_deadband_inside_stamps[16] |

## Findings (GREEN rows)
- MEDIUM M16 (energy_write_verify.py ~L685 `if sw is None: return False`): fail-closed guard untested. If the memory step raises (swallowed) or returns early, sw is None and the gate would qualify CLOUD_STALE with no witness read this sweep. Needs a test: memory set, step raises/no sweep_witness -> status stays REVERTED/pages.
- MEDIUM M17 (~L688 sw_cmd/sw_at match): same-ledger binding between step read and gate untested; ledger can change across the awaits between step and gate. Test: mutate ledger (value or commanded_at) between step and gate -> no qualify.
- MEDIUM M28 (~L628 `self._sweep_witness = None` reset): stale witness from a previous sweep reused when this sweep's step exits early/raises. Test: sweep 1 caches reason "unavailable", sweep 2 step raises -> gate must not qualify. (M16/M17/M28 can share one or two tests.)
- LOW M5 (no-ledger clear): near-equivalent (gate also needs commanded and first_at >= commanded_at); add a ledger-cleared -> memory None assertion or accept.
- LOW M8 (restamp value-mismatch term): gate M14 independently catches stale-value memory; redundant defense, add a restamp-after-value-change assertion on mem.value or accept.
- M20/M21: equivalent mutants under try/except; no action.

Verdict: FIX-REQUIRED - add tests anchoring M16, M17, M28 (MEDIUM); M5/M8 optional LOW. 24 of 30 sites RED with specific named tests; core stamp/gate/kill-switch/attribute wiring is well anchored.
