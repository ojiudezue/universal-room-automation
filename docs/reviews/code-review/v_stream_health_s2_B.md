# Review B: camera input stream health S2 (cross-coordinator, HVAC, AWAY, restart, lifecycle)

Branch `feature/camera-input-stream-health-s2`, HEAD `8fee2e47`. Diff base is the merge-base `3ec3f4d2` (= develop's v5.108.21 reconcile commit, verified with `git merge-base`), three-dot diff. Plan `docs/planning/PLANNING_camera_input_stream_health.md` S2.

Read completely before reviewing: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`. No claim in either corrections ledger is re-asserted here. No tests run (nothing needed one; framing C owns mutation).

## Verdict: SHIP (no CRITICAL / HIGH). Two MEDIUMs to fix in the fix-up pass; LOWs optional.

## Findings

| # | Sev | Site | Finding | Bug class |
|---|---|---|---|---|
| B-M1 | MEDIUM | `domain_coordinators/presence.py:2433-2441` (`check_zone_occupancy_confidence`, Source 3) | An S2 site was missed. Source 3 reads each HVAC zone's `zone_cameras` entity state raw (`state == "on"`) and never asks `entity_stream_dead`. The only caller is the HVAC D6 stale-occupancy failsafe (`hvac.py:3097-3105`): a frozen `on` from a dead-stream camera adds one confirmation, so the 4 h failsafe resets its timer instead of forcing away. Repro (legal config): zone with ≥2 rooms and `zone_cameras = [binary_sensor.<cam>_person_occupancy]`. The camera has been `unavailable` past the 120 s grace and its person sensor is frozen `on`. A stuck radar holds the zone HVAC-occupied for more than 4 h, and a second room is occupied: possible = 4, threshold 2, confirmed = camera 1 + Source 4 1 = 2, so the timer resets and D6 never fires. Pre-S2 behaviour was the same, so this is not a regression, but it is a camera-evidence reader outside the one getter, and the S2 doc note "HVAC needed no change: it reads room `occupied`" (PRESENCE doc line 11) is wrong for this path. Fix: `if state and state.state == "on" and not _camera_entity_stream_dead(self.hass, camera_entity)`, plus correct the doc line. | #53 one missed site |
| B-M2 | MEDIUM (design, document it) | `occupancy_substrate.py` `recheck_entities` → zone tracker → `presence.infer` nobody-home | A camera dying can trigger AWAY. S2 treats a dead input as OFF at the zone tier, not as unknown. At the tick the grace expires, `recheck_entities` dispatches kind False, the zone reads empty, and nobody-home (`census_count == 0 AND NOT any_zone_occupied`, PRESENCE §2 step 0) can fire on the next inference. SLEEP → AWAY is a legal edge (`house_state.py:107-110`). Repro: house SLEEP, a phoneless guest asleep in a room whose only `on` input is a camera-derived sensor (Frigate occupancy or kiosk panel motion filed in `motion_sensors` / `occupancy_sensors`), census 0. The camera goes `unavailable` with the input frozen `on`. 120 s + one poll later the zone empties, `_zone_night_raw` (room limb = tracker, which follows the substrate) reads empty, and nobody-home moves SLEEP → AWAY. The census side (dedup rule 5) calls a dead camera a MISSING term, but the zone tier turns it into "empty", and nobody-home reads empty zones as absence. This is the plan's chosen semantics (the frozen `on` is not evidence either), and it matches S1 at the room tier. It is still a state flip at the moment a camera dies, and neither the plan nor the doc names it. Ask the operator to accept it by name and record it in the PRESENCE doc S2 paragraph, or make the night_raw / nobody-home read treat a stream-dead holder as "unknown → hold". | #63 (missing ≠ zero concept split, zone tier vs census) |
| B-L1 | LOW | `coordinator.py:2629-2636` + `coordinator.py:1636-1675` | The discharge runs synchronously INSIDE `_async_update_data`. `recheck_entities` → `_dispatch` → `SIGNAL_SUBSTRATE_KIND_CHANGED`, and the room's own `_on_substrate_kind_changed` → `_trigger_rate_limited_refresh` → `async_create_background_task(self.async_refresh())`. So every flip spawns a second refresh of the same room while the first is still in progress (the tick has awaits after line 3811). The concurrent-refresh class already exists for any state event that lands mid-await; S2 makes it deterministic once per flip. The second tick sees the same dead set (no second flip, no loop), and its fusion result is identical, so I found no observable harm. Optional: skip the self-room refresh for stream rechecks, or notify after the tick returns. | concurrent refresh / reentrancy |
| B-L2 | LOW | `camera_stream_health.py:229-235` (S1 `evaluate`) amplified by `coordinator.py:2631-2636` | Per-tick flap if a camera alternates `unavailable` ↔ `unknown` (or `unavailable` ↔ restored placeholder). An `unknown` tick drops the input from `dead` (it is required to be `== unavailable`), while `_unavail_since` survives a gap shorter than the grace. The dead set therefore flips every 30 s tick, and each flip rechecks the input and dispatches occupied / vacant to the zone tracker (AWAY hysteresis is 30 s, `house_state.py` DEFAULT_HYSTERESIS). The room tier (S1) already flaps the same way, and HA camera entities rarely read `unknown`, so reachability is low. Not an S2 defect, but S2 carries the flap into house state. Candidate fix (S1): while a stamp is live and inside continuity, treat `unknown` as "keep the previous dead verdict". | no-flap |
| B-L3 | LOW | `presence.py:831-833` (`_any_camera_occupied`) | Event-loop cost and ordering. `entity_stream_dead` is called for EVERY camera in `_camera_last_seen` on every `_derived_mode` read, before the cheap occupied / timeout test. For a person binary sensor that is not a room input, that is `input_stream_dead` (every room coordinator, ~43 calls), then a registry lookup, then `camera_stream_dead` (another ~43 calls, each scanning that room's `_resolution`). Roughly 500 operations per camera per read. It runs only when BLE and Tier 1 are both empty (short-circuited above), so the cost is bounded, but it is wasted on cameras that are not occupied anyway. Fix: test `_camera_occupied` / timeout first and call the getter only for a camera that would return True. The other sites already call the getter only for an entity that reads `on` (substrate `_kind_on_now`, the switch-off live path, the fan gate, night rooms, fan_veto), so their cost is proportional to the on-count. Census `_stream_dead_interior` runs per census pass over the interior list (3 loops); acceptable. | event-loop cost |
| B-L4 | LOW | `occupancy_substrate.py` `recheck_entities` | Does not test `_is_torn_down`, which `_handle_state_change` and refresh do (lines 523, 536). Teardown is await-free and the `hass.data` key is popped right after (`presence.py:9370-9384`), so I found no reachable window. Add the guard for symmetry. | lifecycle symmetry |
| B-L5 | LOW (doc) | PRESENCE doc S2 paragraph "Restart" | Room RELOAD has the same window as restart, and the doc names only restart. On a room options save the old coordinator is popped (`__init__.py:6150`) and the new one is stored only after its first refresh (`__init__.py:5562`), with fresh RAM. Meanwhile `input_stream_dead` answers None, a substrate re-seed counts the frozen `on`, and the zone can read occupied for grace + one poll, then release (vacant → occupied → vacant at the zone tier). This returns to pre-S2 behaviour and is bounded. Add "reload" next to "restart". | restart / reload |

## Forward trace per S2 site (live config)

| Site | Reaches | Direction when a camera dies | AWAY slower / blocked? |
|---|---|---|---|
| Substrate `_kind_on_now` + switch-off path + `recheck_entities` | zone tracker `_room_occupied` → `any_zone_occupied` (nobody-home, path β indoor guard, ARRIVING trigger, D4d trip-wire), `_zone_night_raw` (SLEEP nobody-home, D1b wake, `sleep_raw_hold`) | evidence removed → zone empties | No. It can only make AWAY possible sooner (B-M2). |
| Zone camera tier `_any_camera_occupied` | `_derived_mode` / `raw_occupied`, night_raw camera limb | evidence removed | No |
| `_room_radar_sole_capable` | presence fan-interference gate | dead non-radar dropped from the on-set, so the gate may fire more often | No (it suppresses holds) |
| `fan_veto._has_recent_motion` / `_has_camera_person` | comfort-fan AWAY / VACATION veto (3 actuation sites) | the veto holds the fan off more often in AWAY | No; correct direction (fan off when away) |
| Census both loops + `_get_unrecognized_camera_count` | `census_count`, `unidentified_count`, `face_id_set` (gated on `frigate_available`), `visitors_present` `legs.cam` | counts drop. If every interior camera is dead: "all camera platforms unavailable" (`degraded=True`, one WARNING per pass) | No. α needs `unidentified == 0` and face 0, and both only fall. `camera_input_dark` (α skip) is computed separately from the `person_count_sensor` states (`compute_camera_input_dark_frame`, `camera_census.py:186-273`), which S2 does not touch, so S2 cannot newly set FRIGATE-FLEET-DARK. |
| Guest mode | GUEST is armed by the stay latch (DB walk) and the 30-min room gate; Path A arms nothing (PRESENCE §10 #30, re-confirmed: `_guest_gate_armed` feeds `guest_reason` / `visitors_present` only) | lower `unidentified` can only lower `legs.cam` | n/a |
| HVAC | reads room `occupied` (S1-filtered) and house state; no `hvac*.py` reads a zone tracker (grep: no `raw_occupied` / tracker / `_zone_night_raw` reads) | follows house state | No, except the D6 Source 3 leak (B-M1), which holds rather than retreats |

**Spurious bursts to HVAC or lights:** S2's recheck dispatches only into the zone tracker and the room's own (redundant) refresh. Lights and HVAC read the room tier, where S1 already decided this tick, so S2 adds no burst on those paths. At death the zone gets one vacant edge; at recovery, one occupied edge if the input is still frozen `on`, then the input's next real state event. The only multi-edge shapes are B-L2 (alternation) and B-L5 (reload).

## Restart / lifecycle

- Restart: the tracker, `_dead_now` and `_camera_stream_prev_dead` are RAM. Every getter answers None until the room resolves and the grace passes, so the zone counts the frozen `on` for about 120 s + one 30 s poll; then the flip runs `recheck_entities`. Before boot-settle the substrate bucket is written silently, and the boot-settle release reconciles the tracker to the substrate, so the discharge is not lost. Holds.
- Room coordinators are found through `hass.data[DOMAIN][entry_id]` (`__init__.py:5562`, popped `:6150`), filtered on the `_camera_stream_health` attribute. Correct: only room coordinators carry it.
- S2 adds no listener, timer or task. The registry listener is S1's (stale-mark, keeps the old answer until the rebuild). Unchanged.
- Kill switch `CAMERA_INPUT_STREAM_HEALTH_ENABLED` False: `_dead_now` stays empty, `camera_is_dead` returns False, the fold returns False, every consumer counts as before, and no flip ever runs. The no-op path is byte-identical.
- The refresh seed / swap is await-free under the lock (`occupancy_substrate.py` refresh body), so a recheck cannot interleave with a swap.

## S1 and other exclusion clients

S2 reads only the S1 tracker (`_dead_now`), never the `SensorExclusionSet`. P22, duty-cycle and chatter exclusions still do not reach the zone tier (STEP-EXCLUDE-4 unchanged, as documented). An input excluded by chatter AND dead reads True through S1 alone. No interaction found. One stale-answer edge: a room whose refresh raises before line 3811 keeps its last `_dead_now`, so its getter stays True. There is no early return before the tick in `_async_update_data` (checked from `:3476` to `:3811`), so only an exception can cause this.

## Must-fix list (fix-up pass)

1. B-M1: honour `entity_stream_dead` at `check_zone_occupancy_confidence` Source 3, add a mutation-anchored test, and correct the PRESENCE doc's "HVAC needed no change" line (and the HVAC doc §3.2 D6 row) in the same commit.
2. B-M2: operator acceptance by name of "a camera death can let nobody-home fire (SLEEP → AWAY included)", recorded in the PRESENCE doc S2 paragraph, or a hold-on-unknown read in night_raw / nobody-home.

LOWs B-L1 to B-L5 are optional in-cycle (each is 1-15 LoC or doc only).

## Bug class tally

| Class | Count |
|---|---|
| #53 one missed site | 1 |
| #63 concept split (missing vs empty) | 1 |
| Concurrent refresh / reentrancy | 1 |
| No-flap | 1 |
| Event-loop cost | 1 |
| Lifecycle symmetry | 1 |
| Restart / reload doc gap | 1 |
