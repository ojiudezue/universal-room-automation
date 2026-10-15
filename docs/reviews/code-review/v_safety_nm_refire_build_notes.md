# Build notes — SAFETY-NM-REFIRE-UNWIRED-1 (plan Rev 4 + 4.1)

Branch `feature/safety-nm-refire` (from develop `1ddadfbfb`). Builder: ura-super-builder, 2026-10-15.
Scope built: D1, D2, D4 (docs), D6, tests. D5 withdrawn: `notification_manager.py` is untouched
(`git diff develop -- .../notification_manager.py` is empty), so `_repeat_alert` is byte-identical.

## Invariant (plan §1, INV-REFIRE Rev 4, post-ACK path)
For Safety CRITICAL `{smoke, carbon_monoxide, flooding}`: (1) still active at cooldown expiry, with no
pending clear: exactly one `_re_evaluate_hazard` re-page carrying the same `hazard_type`/`location`.
(2) Clear hold pending with no raising sensor at expiry: zero re-pages, NM goes IDLE. (3) A relapse
cancels the hold, so the re-page happens at expiry. (4) Unacked alerts latch until acked
(no Safety-side silencing).

## Sites (re-grepped)
| Site | file:line (post-build) | Notes |
|---|---|---|
| D1 sole `NotificationAction(` in safety | `safety.py:2580-2591` | `rg 'NotificationAction\('` gives one match |
| D2 `is_hazard_active` | `safety.py:3403-3435` | sole caller `notification_manager.py:3039` (`rg is_hazard_active custom_components/`: defs base:237, safety, security:825) |
| D6 flooding location | `safety.py:1920` | `location=` |
| D6 flooding message | `safety.py:1927` | message string |
| Manager forward (unchanged) | `manager.py:1070-1081` | driven by T6/T7 via the real `_execute_action` |

## Tests — `quality/tests/test_safety_nm_refire.py`
The plan's `quality/tests/safety/` and `quality/tests/notification_manager/` directories do not exist (the
suite is flat), so all tests live in one flat file.

| Plan id | Test | Class | develop |
|---|---|---|---|
| T1 | `test_safety_notification_action_carries_hazard_type_location` | F | FAILED |
| T2 | `test_safety_is_hazard_active_true_when_active` | R | PASSED |
| T2b (conjunct drills) | `test_safety_is_hazard_active_hold_branch_needs_both_conjuncts` | F | FAILED |
| T2c (roc + hold) | `test_safety_is_hazard_active_roc_key_pending_is_inactive` | F | FAILED |
| T3 | `test_safety_is_hazard_active_false_when_cleared` | R | PASSED |
| T4 | `test_safety_is_hazard_active_false_during_clear_hold[300/86400]` (hold extremes) | F | FAILED x2 |
| T5 | `test_safety_is_hazard_active_true_on_relapse_during_hold` | R | PASSED |
| T6 | `test_safety_smoke_repeat_phase_is_life_safety` | F | FAILED |
| T7 | `test_nm_re_evaluates_safety_hazard_round_trip` | F | FAILED (`600 == 120`) |
| T7-neg | `test_nm_re_evaluate_no_refire_during_pending_clear` | R / intermediate | PASSED |
| T9 | `test_safety_flooding_location_is_deterministic` | F | FAILED (`'Kitchen, Garage'`) |

develop run (tests applied, source unpatched): **8 failed, 4 passed**. Post-build: 12 passed.
T7 uses a pass-through spy on `async_notify`, has pushover enabled for one person, and asserts the new
per-channel `log_notification` rows (`hazard_type='smoke'`, `location='Garage'`, `severity='CRITICAL'`).
T9 runs the real `_check_flooding_escalation` in subprocesses with `PYTHONHASHSEED=0` and `=1`.

Targeted siblings (post-build, together with the new file): test_safety_coordinator,
test_safety_hazard_clear_on_recovery, test_safety_humidity_junk_floor, test_v4_6_9_safety_recent_events,
test_zone_safety_alert, test_notification_manager, test_nm_cycle_b_safety_rails,
test_nm_cycle_c2_life_safety_union, test_nm_recovery_agebound, test_restart_safety_doctrine_1:
**596 passed** (includes the new file's 12).
Order robustness: 5 orderings with test_safety_coordinator / test_notification_manager /
test_safety_hazard_clear_on_recovery / test_nm_cycle_* before and after; all green. The manager
base-class reconciliation is scoped through monkeypatch.

## Per-site mutation drills
Method: one Python step per mutant (write mutant, clear `__pycache__`, `PYTHONDONTWRITEBYTECODE=1`,
run the new file + test_safety_hazard_clear_on_recovery + test_safety_coordinator, restore in
`finally`). `git status` was clean apart from the intended changes afterwards.

| Mutant (one site) | RED tests |
|---|---|
| D1a drop `hazard_type=` kwarg | T1, T6, T7 |
| D1b drop `location=` kwarg | T1, T6, T7 |
| D2 revert hold branch (whole) | T2b, T2c, T4[300], T4[86400], T7-neg |
| D2 drop `in _hazard_clear_pending` conjunct | T2b, T2c, `test_safety_is_hazard_active_ignores_roc_suffix` |
| D2 drop `not raising` conjunct | T2b |
| D2 drop `:roc` strip | T2c, `test_safety_is_hazard_active_ignores_roc_suffix` |
| D6a revert location `sorted` | T9 |
| D6b revert message `sorted` | T9 |

Wire-in: D1 is the call-site kwarg itself. T6/T7 drive it end to end through `evaluate` →
`_respond_to_hazard` → `CoordinatorManager._execute_action` → `NotificationManager.async_notify` →
`async_acknowledge` → `_cooldown_expired` → `_re_evaluate_hazard` → `is_hazard_active`.

## Plan discrepancy (reported, not improvised)
- Plan §9C says "revert D2 → T7 fails". It does not: T7's detector stays ON with no pending clear, so
  `is_hazard_active` is True with or without D2. At the NM level, D2 is anchored by T7-neg (RED on
  D1-with-D2-reverted, as the drill shows), and at the Safety level by T4/T2b/T2c. T7 anchors D1 only,
  through two failure modes: hazard_type missing fails the 120 s cooldown assertion; location missing
  fails the re-fire count.
- Tests added beyond the plan's list (T2b, T2c, and the T4 hold-extreme parameter): coverage only, no
  source scope added.

## Deferrals
None from D1/D2/D4/D6/tests. D5 withdrawn per plan. Carded follow-ups unchanged:
SAFETY-UNACKED-REPEAT-CADENCE-KNOB-1, SAFETY-NO-INITIAL-SENSOR-PASS-1, NM-MULTI-ALERT-TRACKING-1,
SECURITY-REFIRE-INTRUSION-KEY-1. Deploy hold (plan Rev 4.1): until the operator is home (Sun 10-18) or
Jaya has been shown how to ack.

---

# D7 — life-safety repeat schedule setting (plan Rev 4.2)

Develop `eddba5da4` was merged into the branch first (merge commit `043712560`).

## Life-safety hazard types and producers (enumerated before building)
Life-safety set = `NM_LIFE_SAFETY_HAZARDS` (`const.py:3391-3399`): `smoke, fire, carbon_monoxide,
water_leak, flooding, intruder, freeze_risk`, plus the extras knob `CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS`
(default `()`, `const.py:3508`; union in `_nm_cycle_a.py:200-221`). The live extras value was not
readable: the HA MCP options read of the CM entry came back empty, which does not mean it is unset.

Only CRITICAL alerts enter ALERTING/REPEATING, so the repeat schedule only affects CRITICAL producers.
Grep of every `hazard_type=` emit (NotificationAction + `async_notify`) across the integration:

| Producer | file:line | Token | Severity | Repeats? | Cadence today (develop) |
|---|---|---|---|---|---|
| Safety smoke | `safety.py:1864` → NotificationAction `:2580` | smoke | CRITICAL | yes | ladder (hazard_type was None before D1) |
| Safety CO ≥100 ppm | `NUMERIC_THRESHOLDS` → `:2580` | carbon_monoxide | CRITICAL | yes | ladder (None before D1) |
| Safety flooding | `safety.py:1917/1938` → `:2580` | flooding | CRITICAL | yes | ladder (None before D1) |
| Safety water leak | `safety.py:1868` | water_leak | HIGH | no | n/a |
| Safety freeze | `NUMERIC_THRESHOLDS` | freeze_risk | max HIGH | no | n/a |
| **Security entry, ALERT_HIGH** | `security.py:1580-1592` (severity `:1561-1563`) | **intruder** | **CRITICAL** | **yes** | **30 s flat** |
| Security unknown-person lockdown | `security.py:1046-1053` | intruder | HIGH | no | n/a |
| fire | — | fire | — | never emitted | — |
| Energy `_send_nm_alert` callers | `energy.py:3302, 5935, 6852, 7016, 7035` | envoy_offline, ev_must_start_by_held, evse_sensor_offline, circuit_anomaly, generator | — | — | not life-safety |
| Zone-monitoring tripwire | `zone_monitoring_tripwire.py:125` | zone_monitoring_leak | — | — | not in the set |
| Perimeter / HVAC / EC / stuck-signal / optimizer | (grep list) | exterior_*, hvac_*, etc. / None | — | — | not life-safety |

**Non-Safety producer that relies on 30 s today: YES — Security `intruder` CRITICAL** (EntryVerdict
ALERT_HIGH: an unknown person is present, which fires even when disarmed per `security.py:349-351`,
or an armed entry). On develop it repeats every 30 s until acked. Under the Rev 4.2 default
(`standard`) it repeats every 300 s for the first hour, then every 1800 s, then daily. Choosing `urgent`
restores 30 s for intruder and for Safety. The setting is global, not per producer. Reported to the
orchestrator for an operator decision; the builder did not decide the ship.

## Sites
| Site | file:line |
|---|---|
| Constants (rung 1 + key/default) | `const.py` after `NM_REPEAT_DAILY_AFTER_S` |
| Schedule read + normalise | `notification_manager.py` `_life_safety_repeat_schedule` |
| Interval life-safety branch (sole cadence consumer) | `notification_manager.py` `_repeat_interval_for_active_alert` |
| Phase labels | `notification_manager.py` `_repeat_phase` |
| Options-flow select | `config_flow.py` `async_step_coordinator_notifications_quiet` |
| Labels | `strings.json` + `translations/en.json` (`coordinator_notifications_quiet`) |
`_repeat_alert` is still unchanged (no D5 residue). It already calls `_refresh_config` and then
`_schedule_repeat`, which is how the setting takes effect live.

## Tests (added to `quality/tests/test_safety_nm_refire.py`)
develop source (eddba5da4, all four source files) against the full new file: **22 failed, 9 passed**.
The 9 that pass on develop: T2, T3, T5, T7-neg, `test_d7_urgent_is_30s_flat`,
`test_d7_urgent_value_is_case_insensitive`, and `test_d7_schedule_never_changes_non_life_safety` ×3.
The F set (red on develop): default ladder 300/1800/86400 at ages 0/3601/86401; explicit standard;
fast_start 60 then 300 at 600/601; unknown ×5 → standard; live change without reload (same NM
instance, entry options flipped, `_repeat_alert` reschedules at 30); Safety smoke end to end with
urgent; options flow shows the stored selection ×3; options round trip (save → re-open shows it → NM
consumes it). Post-build: 31 passed.

T6 was updated: under the default schedule a Safety smoke stays on the ladder (`phase1`/300). D1 is
still anchored by its `hazard_type == "smoke"` assertion and by T1/T7.

Existing tests changed because they pinned "life-safety = 30 s" (now the `urgent` schedule):
- `test_nm_cycle_b_safety_rails.py` (TestB1SubtypeCadence `_nm`, TestB1IntruderCadence): configure `urgent`.
- `test_nm_cycle_c2_life_safety_union.py::test_extras_promote_cadence_end_to_end`: configure `urgent`
  (the baseline overheat=300 vs promoted=30 discrimination is kept).
- `test_notification_hygiene.py::test_fix2_phase_boundaries_are_correct`: converted from a source-exec
  of the helper to a behavioural test on a real NotificationManager (checklist #7). It adds the
  standard-default and urgent assertions.

Targeted siblings green: 306 (NM + config-flow + cycle files) and 701 (strings parity, translation
coverage, reload suppression, safety files).

## D7 mutation drills (one site each; pyc cleared; restored; tree verified)
| Mutant | RED tests |
|---|---|
| D7a urgent `return 30` removed | d7 urgent ×2, d7 live-change, d7 e2e urgent, cycle_b ×3, hygiene ×2, c2 union |
| D7b fast_start branch removed | d7 fast_start, d7 options round trip |
| D7c fast_start window conjunct dropped | d7 fast_start |
| D7d life-safety branch → develop 30 s flat | T6, d7 default, d7 standard, d7 fast_start, d7 unknown ×5, d7 live-change, d7 round trip, hygiene boundaries |
| D7e default constant → urgent | T6, d7 default, d7 unknown[None], d7 live-change, d7 options shows[None], hygiene boundaries |
| D7f unknown-value normalisation removed | d7 unknown[""] |
| D7g `_repeat_phase` urgent label removed | d7 urgent ×2, d7 live-change, d7 e2e urgent |
| D7h `_repeat_phase` fast_start label removed | d7 fast_start, d7 round trip |
| D7i config key detached | d7 fast_start/urgent ×2/live-change/e2e/round trip, cycle_b ×3, hygiene, c2 union |
| D7j options-flow default ignores stored value | d7 options shows[fast_start/urgent], d7 round trip |
| D1a/D1b/D2/D6a re-drilled after the T6 change | still RED (T1/T7, T7-neg/T4, T9) |

## Open question (not built — reported)
- **Reload on save.** The new key is NOT in `OPTIONS_RELOAD_SUPPRESS_KEYS` / `_NO_LIVE_ATTR_KEYS`
  (`__init__.py`). The other fields on the same NM wizard step (quiet hours, safe word, cooldowns) are
  not there either, so a save that changes only this select reloads the Coordinator Manager, as those
  fields already do. NM reads the value live, so the reload is unnecessary. Suppressing it means
  adding the key to `_NM_C_KEYS` (the NM Cycle C precedent for `_refresh_config`-read keys) and
  stubbing it in four AST-slice loaders (`test_cm_reload_suppression`, `test_part2_ec_hc_writeback`,
  `test_reload_watchdog_hazard`, `test_room_options_reload_suppression`). That is outside the Rev 4.2
  text, so it was left for a ruling.
