# Camera input stream health S1 - Review C (test authority via real per-site source mutation)

Branch `feature/camera-input-stream-health-s1`, HEAD 4f7471a0, diff base `git merge-base develop HEAD` = 1d6ce7a8 (verified).
Method: 130 single-site mutants of production source (tracker, resolver, coordinator, sensor, const, `__init__` unload),
one at a time, original text restored in a try/finally, `__pycache__` purged and `PYTHONDONTWRITEBYTECODE=1` per run.
Test set per mutant: `test_camera_stream_health.py` + `test_camera_resolver.py` + `test_sensor_exclusion.py` +
`test_unavailable_entities_chatter.py` (+ `test_cycle_a_room_resilience.py` for the lifecycle mutants). Baseline 82 passed.
Result: 83 RED, 47 GREEN. Of the GREEN rows, 9 are equivalent mutants (cleared below) and 38 are untested sites.
Tree clean after every mutant (verified `git status` at end).

## Verdict: FIX-REQUIRED

## Must-fix (HIGH / MEDIUM)
| # | Sev | Site (mutant) | Why it matters |
|---|---|---|---|
| 1 | HIGH | `coordinator.py` `_camera_stream_registry` -> `return None` or `er.async_get(None)` (co.registry-seam-none, x.er-import-missing-seam) | The test double overrides this seam, so the real `er.async_get(self.hass)` never runs. A broken seam makes every input `registry_error`, the feature silently dead, and no WARN (derived=False). Class #62/#53 wire-in anchor. Need one test that calls the real method with a stubbed `er.async_get`. |
| 2 | HIGH | `coordinator.py` `_apply_camera_stream_health_tick` input list: drop `motion_sensors` or `occupancy_sensors` (co.inputs-no-motion, co.inputs-no-occupancy) | Harness only puts a camera-backed input in `mmwave_sensors`; `occupancy_sensors` is always `[]` and the motion list holds a non-camera ZV. A Frigate/Protect occupancy or motion input in the other lists is never excluded and the suite is green. One-missed-site (#53). |
| 3 | HIGH | Listener lifecycle: subscribe placed before the re-setup clear block (x.subscribe-before-clear); re-setup clear loop removed (x.resetup-state-clear-loop-removed); unload loop removed (x.unload-state-loop-removed) | No test proves the registry listener survives the `async_config_entry_first_refresh` clear, is not duplicated on re-setup, or is unsubscribed on unload. `test_first_refresh_subscribes_registry_listener` patches the subscribe method and checks only that it was called. Subscribe-before-clear unsubscribes it immediately: cache never invalidates in production, suite green. (The re-setup/unload loops are pre-existing generic code, but this cycle adds the first listener whose correctness depends on them.) |
| 4 | MEDIUM | `coordinator.py` tick fail-open guard: `except Exception` -> `except KeyError` (co.tick-exc-unguarded) | The "a raise leaves this tick pre-S1" contract is untested. With the guard gone a tracker/registry/state exception breaks the room tick. Add a test where `evaluate` raises. |
| 5 | MEDIUM | `camera_stream_health.py` `value is None or value == _UNKNOWN` -> `value == _UNKNOWN` (csh.state-none-treated-live) | Module docstring specifies "no state -> no opinion, `since` neither set nor cleared". A missing camera state clearing the stamp is untested (only `unknown` is). Restart/removed-entity blip could reset a real dead episode. |
| 6 | MEDIUM | `coordinator.py` recovered NM `kind=` (co.recover-kind) | Page kind and key are pinned, recovered kind is not. A recovered NM under a different kind never pairs with / clears the HIGH page. Assert `kind == "camera_stream_dead"` on recover calls. |
| 7 | MEDIUM | `camera_stream_health.py` stamp prune (csh.prune-off) | A camera dropped from the room's inputs keeps its stamp; re-adding it later is declared dead with no grace. Need a test: stamp, remove input, re-add, expect fresh grace. |
| 8 | MEDIUM | `camera_stream_health.py` `is_dead` None-resolution guard (csh.isdead-none-resolution-guard) | Public getter before the first tick or after `invalidate()` is untested; without the guard it raises AttributeError. Also a design note: after a registry event `invalidate()` makes the getter return None ("no opinion") for a currently-dead input until the next tick, which S2 readers will see. Test and document. |
| 9 | MEDIUM | `camera_resolver.py` `if not device_id` guard (res.no-device-guard) and fallback-path filters (res.fallback-device-filter, res.fallback-no-filter) | Fallback loop with `device_id None` would match every device-less camera entity. Guard and fallback are untested; `test_camera_resolver.py` has no test of `own_camera_entity_for_input` at all (all resolver coverage is via the stream-health file). |

## LOW (untested sites, fix in-cycle if cheap)
| Mutant | Gap |
|---|---|
| csh.registry-getter-raise-unguarded, csh.statefetch-exc-unguarded, res.exc-reason, res.lookup-exc-unguarded, sn.exc-unguarded | Every `except Exception` fail-open branch (registry getter, state getter, registry `async_get`, device lookup, sensor snapshot) has no test that raises. |
| csh.warn-ignores-derived, csh.warn-ignores-resolved | Zero-resolved WARN has only the positive test; no test that a non-camera room or a partially resolved room stays silent (log spam on every room if the `derived` term is lost). |
| csh.grace-const-name-ignored | Grace lookup from `_const` is untested (tests use value-sensitive literals, so changing the constant is caught, but a hardcoded 120.0 is not). |
| res.entry-none-guard, res.no-camera-guard, res.no-device-derived, res.camplatform-off, res.lookup-exc-derived, res.derived-platform-only, res.derived-cameras-only, res.resolved-derived-false | Resolver reason strings and the `camera_derived` truth table are not asserted (only one derived case via the WARN test). |
| csh.recover-camera-blank, co.recover-message, co.page-title, co.page-diagnosis, co.page-remedy | NM payload text unasserted (kind/key/severity/exclusion_engaged are). |
| co.ctor-roomname, co.subscribe-trailing-invalidate | Room name in WARN text; catch-up invalidate after subscribe. |

## Cleared as equivalent (GREEN is correct)
csh.registry-none-branch-off (resolver catches the AttributeError and returns the same `registry_error`), csh.dedupe-off and csh.empty-eid-kept (the dict dedups), csh.dead-since-none-guard-off (unreachable: `unavailable` always stamps), csh.dead-unresolved-allowed (`get(None)` is not `unavailable`), res.sorted-off (single camera only), sn.isinstance-guard (TypeError lands in the existing except), co.subscribe-import-fail-raise (test-stub-only branch), co.firstrefresh-subscribe-before-clear (my mutant clears after super() and before subscribe; harmless, not a real defect).

## RED rows (specific test named is available per run; summary)
83 mutants RED, including: grace `>=`/boundary and const value (60/600), NM `>=` boundary and const value (0/600), kill switch, unknown state, stamp overwrite/never/no-clear, camera-state check, latch off (episode and per-day), episode add / day set / page append, recover never / discard, return slots, `is_dead` always True/False, unresolved-not-None, snapshot fields, exclusion client name and NM kind constants, resolver disabled/non-camera/multi/zero/cache invalidation/rebuild on input change/no-cache, tick call site removed, mmwave input list, promote off/wrong client/reason, NM page loop/recover loop/early-return, page kind/key/severity/exclusion_engaged, recover key, getter true/false/none, snapshot empty, subscribe call-site/append/callback/wrong-event, sensor attribute writes, `_unrecorded_attributes`.

## Cycle-note
Builder's 23 drills were not trusted; all 130 above were run independently. The harness' `_Room` stub (seam override, `occupancy_sensors=[]`, motion list non-camera) is the root cause of rows 1 and 2.
