# Review C (test authority, per-site source mutation) - commit 745dab09, base 884c98e2

Test set per drill: test_room_menu_adv_trim_and_room_rate, test_room_menu_trim, test_room_advanced_fields, test_v4_6_8_rate_reconciliation. pyc cleared, PYTHONDONTWRITEBYTECODE=1, tree restored after each (git status clean).

| # | Site mutated | Result | Killing test |
|---|---|---|---|
| 1 | init menu ignores show_adv (old full-menu branch) | RED | test_closet_advanced_mode_gets_trimmed_menu_and_more_settings; test_advanced_mode_menu_is_trimmed_too[*]; reveal test[True] |
| 2 | room_menu_hint early `if show_advanced` return | RED | test_closet_advanced_mode_gets_trimmed_..., test_room_menu_hint_variants |
| 3 | rate field back in room options energy step | RED | test_room_options_energy_step_has_no_rate_field; reveal tests[False/True] |
| 4 | rate field back in room-create energy step | RED | test_room_create_energy_step_has_no_rate_field |
| 5 | helper room tier restored (no caller passes) | RED (only) | test_effective_rate_ignores_room_override (TypeError signature pin) |
| 6 | helper tier + sensor.py:957 passes room_entry | RED | test_room_cost_today_uses_house_rate_not_stored_room_rate (1.1 vs 1.3) |
| 7 | helper tier + coordinator.py:5614 passes room_entry | RED set identical to #5 | NO behavioral test: coordinator weekly/monthly cost has zero coverage (grep of quality/tests for energy_cost_weekly/monthly = none) |
| 8 | `_STEP_EXTRA_OWNED_KEYS["energy"]` owns electricity_rate (reveal) | RED | test_closet_with_only_stored_room_rate_does_not_reveal_energy[False/True] |

## Findings
- MEDIUM (Bug #53 / untested site) coordinator.py:5614 weekly/monthly cost call: no test drives it; re-adding `room_entry=` there (with the helper tier restored) is caught only by the signature pin, not by any coordinator cost test. With the helper as shipped, a regressed call site would TypeError at runtime inside the cost block. Suggest one test driving the coordinator cost computation (STATE_ENERGY_COST_WEEKLY with room rate 0.11, house 0.13).
- LOW: #5 is guarded solely by a TypeError pin; behaviourally it is covered only via the sensor test. Acceptable.
- LOW (stale copy, not test): strings.json / translations/en.json lines ~438-444 and ~2171-2177 still carry "Room Fallback Rate Override" labels for the removed room field. Harmless dead strings.
- No hollow tests found: all new tests drive real flow handlers / real helper / real sensor; oracles are literals. The TypeError pin is a legitimate signature assertion.

## Verdict: SHIP (one MEDIUM test-gap on coordinator.py:5614; fix-in-cycle recommended, 1 small test)
