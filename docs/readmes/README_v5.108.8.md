# v5.108.8: Lights fade on every ambient path; faster, order-proof test suite

Cards shipped: `LIGHT-TRANSITION-COVERAGE-1`, `SNAP1-FRIGATE-TRAVERSAL-1`. Also merged: the `TEST-SUITE-PARALLEL-1` test fixes (card stays open: 11 parallel-only failures remain in two files that landed after the work branched; gate stays serial).

## 1. Every ambient light write fades (LIGHT-TRANSITION-COVERAGE-1)

**Why:** operator 2026-11-10 asked for a 1-2 s fade on all light actuation because it feels higher quality. The room fade knobs already existed (`CONF_LIGHT_TRANSITION_ON` / `_OFF`, `const.py:1236-1237`, defaults 1 s on / 3 s off at `const.py:1719-1720`) and entry/exit already used them, but five paths ignored them.

**Fix:** the room fade is now sent on the Room lights switch (on, night-light on, off; `switch.py` ~5654/5663/5697), the Away leave-on sweep (`automation.py` ~922), the shared-space turn-off (`automation.py` ~4694) and the actuator reconciler's dispatch (`actuator_reconciler.py` ~704, `light` domain only, fans excluded; added to the payload, not to `DesiredState.params`, so the no-op gate is unchanged). New helper `light_transition(cfg, *, on)` in `lighting/resolver.py` reads the existing knobs. No new knobs, no default change.

Stay instant on purpose: auto-off warning flash, alert lights and their restore (`automation.py`, `aggregation.py`), the NM light channel, security (`security.py:1726`) and safety (`safety.py:2701`). `switch.*` relays never get `transition` (46 of 84 URA lights in this house are relays and cannot fade). The two room fade fields now say so in their help text.

Full emission-site table: `README_DRAFT_light_transition_coverage.md`.

Reviews (Tier 2, elevated because the reconciler changed): `docs/reviews/code-review/light_transition_coverage_review_A.md` (SHIP), `..._review_B.md` (SHIP; LOW B-1 pre-existing, carded `LIGHT-FADE-OVER-5S-MANUAL-MISREAD-1`: a fade set above 5 s can make URA book its own change as manual; defaults do not trigger it).

## 2. Test suite runs in parallel with the same results as serial (TEST-SUITE-PARALLEL-1)

Tests only, no production change. Cross-file pollution (stubs and module evictions left behind, frozen clocks patched on the wrong `dt_util` copy) made serial and parallel runs disagree (18 vs 91 failures). Fixed donor by donor with `ModuleScope` / `import_scope`; a custom xdist hook (`quality/tests/_xdist_split.py`, `--dist loadfile` only) splits the three heaviest drill files. Parallel `-n 6 --dist loadfile` ~11 min vs ~33-41 min serial. Audit: `docs/planning/AUDIT_test_suite_parallel_2026_11.md`. Review: `docs/reviews/code-review/test_suite_parallel_1_review.md` (SHIP).

## 3. SNAP1 traversal test made hermetic (SNAP1-FRIGATE-TRAVERSAL-1)

The test walked the whole system temp dir and flagged any "etc"+"passwd" path, so files from other processes failed it. Production was never vulnerable: `_try_capture_frigate_event` sanitises the event id and two `_path_within` guards refuse escapes. The test now uses a private nested dir with a reachable escape path; drilled RED with the sanitiser and both guards off, restored clean.

## Not done
- `BLE-EXTEND-DRILL-RETARGET-1` (drill anchor stale after b13a151e) stays open.
- Switching the release gate to parallel by default is a process change, not in this release.

## Live validation (prospective)
- Toggle a room's Room lights switch: the `light.turn_on` service data carries `transition` = the room fade-in; a `switch.*` member has none.
- Alert lights still switch instantly.
- No URA ERROR after restart.

## Validated 2026-11-11 (restart ~07:02 CST, v5.108.8 via HACS, house `home_day`)
| Criterion | Result | Evidence |
|---|---|---|
| Installed + loaded | PASS | HACS download v5.108.8 succeeded; after restart `sensor.ura_coordinator_manager_house_state` = `home_day`, coordinators up |
| Load clean | PASS | system_log ERROR: no `universal_room_automation` entries; WARNINGs are the usual boot set (room sensors unavailable hold, Bermuda fallback, perimeter `_2` siblings, HVAC boot-settle timeout) |
| Room fade sent on the new paths | PROVEN IN-SUITE, live PENDING organic | HA logbook/state history does not expose service-call data, and toggling a Room lights switch would be house-visible with residents home; `test_light_transition_coverage.py` (11, every added site mutation-anchored) |
| Alert lights stay instant | PROVEN IN-SUITE | `test_alert_lights_stay_instant` |
| Relays never get `transition` | PROVEN IN-SUITE | site tests assert no `transition` in `switch.*` calls |

Pre-ship gate: serial full suite base `126421ba` vs candidate: 15 vs 15 failures, identical names, +11 passes. Merged develop in parallel (`-n 6 --dist loadfile`, 3 min): 11 failed, 15 base failures gone, 11 parallel-only failures (pass alone 72/72) in `test_arrester_operator_immunity` / `test_dp_drain_target_value_stamp`, carried on `TEST-SUITE-PARALLEL-1`.
