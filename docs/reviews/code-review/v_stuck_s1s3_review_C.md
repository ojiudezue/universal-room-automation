# Review C - stuck-sensor truth S3a / S3b / S1 - test authority by per-site source mutation

Branch `feature/stuck-sensor-s1-s3`, diff base `c67b8a78...HEAD` (custom_components only). Sites enumerated from the diff, not from the builder's drill list.
Method: one production edit per run, `__pycache__` purged, `python -B`, `PYTHONDONTWRITEBYTECODE=1`, `-x`, `-m ""` (drills included), file set = the 3 cycle files + chatter (4), sensor_exclusion, stuck consequence/watchdog (3), fan_recheck (4), crossing_vision_p3_first, reload pins (4), occupancy capability, sensor_capability_and_role, mmwave_fan_demotion, v462_d6_select. Baseline 600 passed. Every mutation restored in `finally`; `git status` clean after the batch.

## Totals
74 mutations: 52 RED (specific test named in run log), 21 GREEN, 1 invalid (a16: removed an import still used -> collection error; not a test-authority datum).
GREEN triage: 9 equivalent mutants, 12 test gaps (4 MEDIUM, 8 LOW). No CRITICAL/HIGH.

## RED (load-bearing, authoritative) - summary by site
S3a: integration>CM precedence (a1), invalid-value skip (a2), CM fallback (a3), flush fn (a6), CM-update flush in `invalidate_knob_cache` (a7), entry-type filter (a8), no cache poison on exception (a10), room resolver routes via `chatter_mode_option` (a11), integration listener flush (a12), reload-suppress key (a13), select current_option (a14), select write flush (a15).
S3b: token split (hyphen/underscore/whitespace) and lower() (b2-b5).
S1: knob values (c1-c4), tolerance gate (c6-c8), class predicates incl. all still-holder branches, PIR/ZV membership, radar not in set (d1-d11, d13), stamp call site and motion list (e1, e4), tol0 new-run stamp and pop (e6, e8), tol>0 seen-on (e11), new run at last_changed (e14), gap boundary and restart (e15-e17), unseen-off branch (e18), unseen uses last_tick (e22), last_tick / on_lc stamping (e23, e24), missing-state first-tick (e26), off pop boundary/never/always (e27-e29).

## GREEN rows
| Mutation | Site | Class | Sev | Needed test |
|---|---|---|---|---|
| a4 cache-read clears after check | `_nm_cycle_a.chatter_mode_option` | equivalent (clear after the hit-return, no observable effect) | - | - |
| a5 cache never written | same | equivalent (cache is perf only) | - | optional: second call does not re-iterate entries |
| b1 drop exact `ms600-un` | `FAMILY_BY_MODEL_ID` | equivalent: the new token splitter resolves `ms600-un` via `FAMILY_BY_MODEL_TOKEN["ms600"]`; entry is redundant | LOW (dead entry) | - |
| b6 drop exact `ms600 9.0.0` | same | equivalent, same reason | - | - |
| c5 drop `tol<=0` early return | `_p22_off_gap_tolerance_s` | equivalent (returns tol=0 either way) | - | - |
| e5 drop `seen` dedupe | `_p22_stamp_tick` | equivalent (second pass idempotent; also a two-rooms test exists) | - | - |
| e12 `lc=lc` instead of `now` when last_changed None | stamp, tol>0 | equivalent in prod (an `on` state always has last_changed); only a mock exposes it | LOW | optional: state stub without last_changed |
| e20 drop `lc > prev_lc` | unseen-off branch | equivalent: unchanged `lc` is always <= previous tick, so `lc - last_tick` is negative | - | - |
| e21 `prev_lc` None guard variant | same | equivalent (`lc > lc` False) | - | - |
| **c9** read room config from `entry.data` only (drops `entry.options`) | `_p22_off_gap_tolerance_s` | TEST GAP | **MEDIUM** | Fixture entry has `options={}` (test file l.436-437). Add: sensor lists AND `CONF_SENSOR_CAPABILITIES` override supplied only via `entry.options`; assert tolerance > 0 for a ZV input and 0 for an override-to-radar input. Rooms edited via the options flow keep lists in options, so the mutant silently disables S1 in production. |
| **e2** drop `occupancy_sensors` from stamp call | `_update_data` call site | TEST GAP | **MEDIUM** | Only the motion list is exercised through `test_update_tick_slice_runs_the_stamp`. Add a tick-slice test per list (motion / mmwave / occupancy): an input only in that list gets `_sensor_on_since` stamped. |
| **e3** drop `mmwave_sensors` from stamp call | same | TEST GAP | **MEDIUM** | Same test as e2. |
| **e7** tol0 branch no longer records `_post_restart_seen_on` | stamp, tol 0 | TEST GAP | **MEDIUM** | STUCK-SENSOR-1 D3 MED-1 restart-safety for still holders/unknown family: restored `_sensor_on_since` must gain no exclusion until a live `on` is seen; assert `_post_restart_seen_on` contains a radar/unknown input after a tol-0 on-tick (and not before). |
| c10 exception path returns 10.0 instead of 0.0 | `_p22_off_gap_tolerance_s` | TEST GAP (fail-safe) | LOW | Make `resolve_sensor_family` raise; assert tolerance 0.0. |
| a9 `{**options, **data}` merge order | `chatter_mode_option` | TEST GAP | LOW | Entry with `data[CONF_CHATTER_MODE]=A`, `options[...]=B`; assert B (options override data). |
| e9 tol0 stops clearing `_p22_off_since` | stamp | TEST GAP | LOW | Class flips tol>0 -> 0 mid-run (override change); assert stale off bookkeeping does not leak. |
| e10 tol0 stops clearing last_on_tick / on_lc | stamp | TEST GAP | LOW | Same flip; assert the maps are empty after a tol-0 tick. |
| e13 `get` instead of `pop` on off_since | stamp | TEST GAP | LOW | Short seen off, then (later) a long unseen off: stale `off_since` makes the `elif` shadow the unseen-off branch and keeps the run. Add that sequence; assert restart. |
| e19 unseen-off `>=` -> `>` | stamp | TEST GAP | LOW | Boundary test for the unseen branch at exactly `tol` (the seen branch has `test_p22_off_gap_boundary`; unseen has none). |
| e25 `setdefault` for off_since | stamp | TEST GAP | LOW | off -> unavailable transition (new last_changed) while the run is open: stamp must be overwritten with the later stretch (the docstring says "overwritten, never setdefault"). |
| d12 drop BLE kind from `_STILL_HOLDER_KINDS` | `is_still_holder` | TEST GAP | LOW | `test_is_still_holder_pure` covers bed/camera/mmwave; add a BLE-kind cap (override and list kind) -> True. |

## Other observations
- b1/b6: both exact-match entries are dead after the splitter change; keeping them is harmless but they are not test-anchored. Not worth a test.
- a16 shows `CONF_CHATTER_MODE` is imported at module level in `__init__.py` and still used by the migrate block; nothing to add.
- Drill-marked tests ran (`-m ""`); the cycle files carry no source_mutation-gated tests that were skipped.

## Verdict
**FIX-REQUIRED (tests only, no production change)**: add the four MEDIUM tests (c9, e2+e3, e7). The eight LOW gaps may ride the same pass (each is 5-15 lines). Production code held up: every behavior-bearing S3a/S3b/S1 site that is not in the table above went RED on a specific test.
