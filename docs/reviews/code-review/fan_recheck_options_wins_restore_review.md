# Review: FAN-RECHECK-FORM-RESTORE-REVERT-1 (fan re-check switches, options win over restore)

Branch `fix/fan-recheck-options-wins-restore` (5a286f10 fix + 7d25125f review LOW). Tier 1, one review (framing A), overnight pass 2026-11-12. Not deployed.

## Change
`switch.py`: `FanRecheckEnabledSwitch`, `RoomFanRecheckEnabledSwitch` and `RoomFanRecheckL2AllowedSwitch` `async_added_to_hass` now use the entry value (data merged with options) when the key is present. RestoreEntity fills in only when the key is absent. Before this change, an options-flow save reloaded the entry, and HA's RestoreEntity (which stores the current state on removal, `restore_state.py:251-283`) put the pre-save value back. Live instance: Garage A options hold `room_fan_recheck_enabled=False` and `fan_recheck_l2_allowed=False`, but both switches showed `on`. The 4th `_mirror_options` switch (`_RoomBooleanOptionSwitch`) already had options-first precedence and was left unchanged.

## Verification
- Builder: 16 new tests in `quality/tests/test_fan_recheck_options_wins_restore.py`. Mutation drills on all 4 sites: each went RED on its 2 named tests. `-k fan_recheck`: 212 passed.
- Orchestrator: re-ran the master-site drill after the builder's fixture change. Result: 2 failed (`test_master_options_win_over_restore[False-on|True-off]`), restored to 16 passed, tree clean.
- Reviewer A: SHIP, 16 passed.

## Findings

| # | Sev | Finding | Bug class | Status |
|---|---|---|---|---|
| 1 | LOW | Docstrings and the block comment said "RestoreEntity is the runtime store/source" | Stale doc vs code | FIXED (7d25125f) |
| 2 | LOW | `_RoomBooleanOptionSwitch` reads options only; the new sites read data and options merged. They differ only when a key is in data but not in options, and the new sites then match the runtime consumer `_merged_config` | Dual-writer precedence asymmetry | ACCEPTED (harmless) |
| 3 | LOW | No test for "key only in entry.data, restore disagrees" | Test gap | DEFERRED (optional) |

| Severity | Found | Fixed | Deferred/accepted |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 0 | 0 | 0 |
| MEDIUM | 0 | 0 | 0 |
| LOW | 3 | 1 | 2 |

Bug class: dual-writer precedence divergence (options flow vs RestoreEntity). This is the same class as the 2026-07-22 F2 guard on `_RoomBooleanOptionSwitch`. QUALITY_CONTEXT candidate: "a switch that mirrors to options must let options win at add, because an options save reloads the entry and RestoreEntity reverts the save."

## Live expectation after deploy
Room switches change only what they display: Garage A's two switches read `off`, which matches the runtime value the engine already uses. Master: `hass.data["fan_recheck_master_enabled"]` follows CM options. Live, that is `True` with the switch `on`, so nothing changes.
