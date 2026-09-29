# Code review — HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1 (pre-cool/banking restore uses the configured Heat Low)

_Tier 1, run under the overnight contract: built and reviewed to the `review` lane, **not merged or deployed**._

Branch `feature/hvac-precool-restore-heat-low`: `e478e0368` build, `71e932f3f` L2 comment fix.

## Reviews
| Review | Framing | Verdict |
|---|---|---|
| A | local correctness, edges, consumers (read the state-of-play doc in full first) | **SHIP**, 2 LOW |
| Orchestrator | per-site mutation: fallback reverted to `cool - 7.0` | 2 of 3 new tests red, restored 3/3 green, tree clean |

Consumer map (review A): the restart reconcile (:530) and the prune (:635) use only `high`. The S11 human-manual raw release writes `target_temp_low` = the new value (the intended fix). S11 named release pins a preset only. The banking token's `pre_target_low` reaches only the log, the notification and the `hvac_excursion_events` row. There is no false `restore_ok=0`, because that is the wire result. The arrester's `_compute_override_delta` compares against the configured heat (`hvac_override.py:7017-7019`), so the change *removes* a +15 °F false delta on a summer-away raw release. On this Carrier, `target_temp_low` is the heat setpoint (`ha_carrier/climate.py:477`). An inverted range is unreachable because the options flow enforces a ≥3 °F deadband (`config_flow.py:6923-6929`).

## Findings
| ID | Severity | Bug class | Finding | Status |
|---|---|---|---|---|
| L1 | LOW | #63 coincidental equality (sibling sites) | `cool - 7` survives at DPM apply `hvac.py:3541`, `sensor.py:10264` (display) and `dynamic_preset.py:905`. The DPM throttle could mis-match after a fallback release, but only once D9 is enabled (off today) | COVERED: the CPR plan deletes `hvac.py:3541` and writes the configured heat (`PLANNING_hvac_enable_custom_preset_ranges.md:268, :395, :659`). No new card. |
| L2 | LOW | Doc drift | Stale "mirrors DPM apply at hvac.py:1330-1338" comment | FIXED `71e932f3f` |

## Summary
| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRIT/HIGH/MED | 0 | 0 | 0 |
| LOW | 2 | 1 | 1 (covered by CPR) |

## Notes
- The pre-existing failure `TestD5Migration::test_restore_entity_off_overrides_options_true` also fails on develop, so it is not from this branch.
- The branch also fixes this test file's stub loader (a missing `emit_set_preset_mode`), which made 27 tests error with ImportError when the file was run on its own on develop.
- Summer effect: sleep low goes 69→70 and away low 75→60. Both are harmless while cooling.
