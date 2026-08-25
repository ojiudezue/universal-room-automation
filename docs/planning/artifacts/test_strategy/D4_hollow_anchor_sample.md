# D4 — Hollow-anchor drill, N=15 call sites

**The distinction that matters:** every drill neuters the CALL SITE in production source, never the
helper body. The call is replaced in place with a no-op of the same shape
(`(lambda *a, **k: None)(` for sync, `(lambda *a, **k: asyncio.sleep(0))(` for awaited calls), which
keeps multi-line call expressions syntactically valid while removing the effect. A helper-level drill
structurally cannot detect an uncalled helper; this one can.

Protocol per site: baseline run → mutate → run → **restore in a `finally:`** → `git status --porcelain`.
`PYTHONDONTWRITEBYTECODE=1`, `__pycache__` scrubbed before the batch. A site is **BOUND** iff at least
one NAMED test fails under mutation that did not fail at baseline.

## Result

| verdict | count |
|---|---|
| **BOUND** (a named test failed) | **5** |
| **UNBOUND / hollow** (call site deletable, tests green) | **8** |
| INCONCLUSIVE (target file could not run at baseline) | 2 |
| **hollow rate** | **8/13 = 62%** |

The plan's discriminator was `H/15 ≥ 5/15 ⇒ systemic`. Measured **H = 8 of 13 evaluable sites**. The
anchor pattern is systemic, and this is the fifth consecutive cycle to show it.

## Per-site table

| # | call site | what it does | verdict | newly-failing test(s) under mutation | git status after |
|---|---|---|---|---|---|
| S1-SEED | `custom_components/universal_room_automation/domain_coordinators/hvac_override.py:3881` | _verify_restore() task creation (Tier-3 reviewer seed) | **BOUND** | `quality/tests/test_ac_ramp_pipeline_hardening.py::TestT5VerifyRestoreCallSites::test_failure_branch_calls_backfill_with_false`<br>`quality/tests/test_ac_ramp_pipeline_hardening.py::TestT5VerifyRestoreCallSites::test_success_branch_calls_backfill_with_combined_true` | `?? docs/planning/artifacts/` |
| S2 | `custom_components/universal_room_automation/domain_coordinators/presence.py:7098` | SIGNAL_PRESENCE_ENTITIES_UPDATE fan-out | **UNBOUND** | **none** — the call site is deletable with the suite green | `?? docs/planning/artifacts/` |
| S3 | `custom_components/universal_room_automation/domain_coordinators/chatter_detector.py:417` | listener teardown call | **BOUND** | `quality/tests/test_chatter_detector.py::test_chatter_detector_unsubscribe_called_on_teardown` | `?? docs/planning/artifacts/` |
| S4 | `custom_components/universal_room_automation/domain_coordinators/energy_battery.py:2083` | battery strategy signal emit | **UNBOUND** | **none** — the call site is deletable with the suite green | `?? docs/planning/artifacts/` |
| S5 | `custom_components/universal_room_automation/domain_coordinators/optimization.py:456` | SIGNAL_OPTIMIZER_INTENT emit | **UNBOUND** | **none** — the call site is deletable with the suite green | `?? docs/planning/artifacts/` |
| S6 | `custom_components/universal_room_automation/perimeter_alert.py:1439` | person-leg NM notify | **BOUND** | `quality/tests/test_perimeter_alert_nm_routing.py::test_ACRIT1_empty_adjacency_single_hop_away_keeps_todays_severity`<br>`quality/tests/test_perimeter_alert_nm_routing.py::test_DCRIT1_loiterer_cooldown_expired_repeat_dispatches`<br>`quality/tests/test_perimeter_alert_nm_routing.py::test_DCRIT2_distinct_second_person_same_camera_dispatches`<br>`quality/tests/test_perimeter_alert_nm_routing.py::test_DCRIT3_adjacent_camera_first_alert_never_silenced`<br>…+41 more | `?? docs/planning/artifacts/` |
| S7 | `custom_components/universal_room_automation/domain_coordinators/hvac.py:2863` | HVAC service actuation | **INCONCLUSIVE** | n/a — baseline was `1 error in 0.08s`, the target file cannot even collect on this host (see D1 bucket B4) | `?? docs/planning/artifacts/` |
| S8 | `custom_components/universal_room_automation/domain_coordinators/hvac_override.py:5388` | AC-ramp started DB row write | **UNBOUND** | **none** — the call site is deletable with the suite green | `?? docs/planning/artifacts/` |
| S9 | `custom_components/universal_room_automation/domain_coordinators/safety.py:2943` | SIGNAL_SAFETY_ENTITIES_UPDATE emit | **UNBOUND** | **none** — the call site is deletable with the suite green | `?? docs/planning/artifacts/` |
| S10 | `custom_components/universal_room_automation/domain_coordinators/notification_manager.py:2153` | NM delivery service call | **BOUND** | `quality/tests/test_notification_manager.py::TestNotifyRouting::test_critical_bypasses_quiet_hours`<br>`quality/tests/test_notification_manager.py::TestNotifyRouting::test_medium_fires_pushover`<br>`quality/tests/test_notification_manager.py::TestPushoverDeviceTargeting::test_send_pushover_no_device_omits_target`<br>`quality/tests/test_notification_manager.py::TestPushoverDeviceTargeting::test_send_pushover_with_device`<br>…+2 more | `?? docs/planning/artifacts/` |
| S11 | `custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py:715` | substrate update signal emit | **UNBOUND** | **none** — the call site is deletable with the suite green | `?? docs/planning/artifacts/` |
| S12 | `custom_components/universal_room_automation/database.py:421` | DB write-queue enqueue | **BOUND** | process **HUNG** under mutation (no exit in 120 s) — behaviour demonstrably changed | `?? docs/planning/artifacts/` |
| S13 | `custom_components/universal_room_automation/coordinator.py:2914` | exclusion promote call site | **UNBOUND** | **none** — the call site is deletable with the suite green | `?? docs/planning/artifacts/` |
| S14 | `custom_components/universal_room_automation/domain_coordinators/hvac_fans.py:1530` | fan actuation service call | **INCONCLUSIVE** | n/a — baseline was `1 error in 0.08s`, the target file cannot even collect on this host (see D1 bucket B4) | `?? docs/planning/artifacts/` |
| S15 | `custom_components/universal_room_automation/domain_coordinators/notification_manager.py:2525` | SIGNAL_NM_ALERT_STATE_CHANGED emit | **UNBOUND** | **none** — the call site is deletable with the suite green | `?? docs/planning/artifacts/` |

## Notes

- **S1-SEED reproduces the reviewer's finding's shape but inverts its verdict.** Neutering the
  `self.hass.async_create_task(_verify_restore())` call site at `hvac_override.py:3881` DOES red two named
  tests. Either the site was bound after the Tier-3 review, or the reviewer's drill targeted a different
  line. Recorded as observed; not reconciled within this cycle.
- **S12 is BOUND by hang, not by assertion.** Neutering `database.py:421 await self._write_queue.put(...)`
  leaves `test_database_resilience.py` waiting forever on a future nothing resolves. That is a real
  binding, but it is the worst possible failure signal — a test that hangs instead of failing is
  indistinguishable from the teardown wedge.
- **S7 and S14 are not evidence of anything.** `test_hvac_fan_control.py` reports `1 error in 0.08s` at
  baseline on this host; the mutation could not be evaluated. They are excluded from the rate.
- The repo already contains a hand-built version of this drill: `quality/tests/test_chatter_wire_in.py`
  runs 25 source-mutation drills as ordinary suite tests via a `_SourceMutation` context manager that
  spawns nested `pytest` subprocesses. That file is both proof the technique is understood here AND the
  single most likely origin of the 'source-mutating test without guaranteed restore' hazard the parent
  card records: if the suite is killed mid-drill, production source is left mutated.

## Every git-status line, as the plan requires

```
S1-SEED: ?? docs/planning/artifacts/
S2: ?? docs/planning/artifacts/
S3: ?? docs/planning/artifacts/
S4: ?? docs/planning/artifacts/
S5: ?? docs/planning/artifacts/
S6: ?? docs/planning/artifacts/
S7: ?? docs/planning/artifacts/
S8: ?? docs/planning/artifacts/
S9: ?? docs/planning/artifacts/
S10: ?? docs/planning/artifacts/
S11: ?? docs/planning/artifacts/
S12: ?? docs/planning/artifacts/
S13: ?? docs/planning/artifacts/
S14: ?? docs/planning/artifacts/
S15: ?? docs/planning/artifacts/
```

`?? docs/planning/artifacts/` is this cycle's own new artifact directory and is the only entry. No
production file was left modified by any drill.
