# Review B: camera input stream health S1 (cross-coordinator, restart, lifecycle)

Branch `feature/camera-input-stream-health-s1` @ b9af53dc. Diff base `git merge-base develop HEAD` = 1d6ce7a8 (verified, three-dot).
Plan `docs/planning/PLANNING_camera_input_stream_health.md` S1.

Read completely before reviewing: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`,
`HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (no §10 ledger claim re-asserted). Targeted run: `test_camera_stream_health.py`
23 passed. Live config read (read-only, `.storage`): the three panel person sensors each sit on a Frigate device with
exactly one enabled `camera.*` (fb5ea1f6 / dd5643cd / 48b0493a), so all three resolve; no panel camera is in any URA
room camera list.

**Verdict: SHIP.** No CRITICAL / HIGH. One MEDIUM (a pre-existing bypass leg outside INV-STREAM's input scope, not
reachable in live config) to document, four LOWs.

## Findings

| # | Sev | Site | Finding | Class |
|---|---|---|---|---|
| B-M1 | MEDIUM | `coordinator.py:4225-4241` (v3.5.1 camera override) | The room's camera override reads `camera_manager.get_person_sensor_for_area(room_area)` raw: no `_fusion_filter_active`, no stream-health check. Repro (legal config, not live today): add `camera.up_hallway_panel` to Upstairs Hallway's room cameras (area resolves to the room). Outage: S1 excludes the frozen `binary_sensor.up_hallway_panel_person_occupancy` from the presence leg; the room times out; the override then sees the same frozen `on` and sets `STATE_OCCUPIED` True, source `camera`, which also stamps HVAC evidence (`_stamp_hvac_evidence` counts `source == "camera"`). Held until the P24 failsafe. INV-STREAM is scoped to the motion/presence/occupancy lists, so this is not a falsification, but it is the same harm on a sibling leg. Fix in S2 (read `camera_input_stream_dead` there) or record it in the state-of-play §4 note next to STEP-EXCLUDE-4. | #53 one-missed-site (sibling leg) |
| B-L1 | LOW | `camera_stream_health.py` state vocabulary | HA writes a registry entity that is not loaded yet as `unavailable` with `restored: True`, not `None`. The plan §5 says "not loaded = no opinion"; the code treats it as dead. Effects: (a) Frigate integration in SETUP_RETRY > 30 min (F2 host down) pages one HIGH "Camera stream dead" per resolved input (3 today) for an integration outage; (b) at boot, if Frigate's binary_sensor platform loads > 120 s after the first room tick and before its camera platform, a real `on` is excluded for that tick. Suggest treating `attributes.restored` as no opinion. | observation/state-vocabulary |
| B-L2 | LOW | `evaluate` grace clock | Restart with a stream already dead: the frozen `on` (retained MQTT) can create room occupancy (lights on) for up to grace + one poll + room timeout after boot, because the grace counts from the first observing tick. Deliberate (restore rewrites `last_changed`) and documented in the state-of-play; far better than the pre-S1 4 h. Accept. | restart |
| B-L3 | LOW | `_paged_episode` (RAM) vs `_stuck_signal_nm._LATCHES` (module) | A room reload mid-episode after the HIGH page loses `_paged_episode`, so no LOW recovered NM is sent for that page; an HA restart mid-outage can page again the same day. Same accepted shape as STUCK-SENSOR-1 B-LOW-1. Accept. | restart |
| B-L4 | LOW | live acceptance | `sensor.upstairs_hallway_unavailable_entities` is `disabled_by: integration` (entity is `_attr_entity_registry_enabled_default = False`), so the plan's Live check cannot read it there without enabling it. Validator note. | validation surface |

## Forward trace (excluded input → actions)

- **Room edges / lights / fans off:** every fusion leg (`coordinator.py:3759-3773`), trigger attribution (`:3787-3803`), radar-sole (`_live_on_set` `:5902`), D2 witness (`:2314`) read `_fusion_filter_active`; `any_sensor_active` drops, the room vacates after its timeout, and room-tier lights/fans/covers follow `STATE_OCCUPIED`. Holds.
- **HVAC:** `hvac_occupied` reads the room's `occupied`; the evidence stamp uses the post-filter `any_sensor_active` (`coordinator.py:5416`, `:6140-6180`), so a frozen input neither stamps nor extends HVAC evidence. Fast-path exit runs off the room refresh as before. No HVAC code touched. Holds (except B-M1's camera leg).
- **Zone roll-up (S2 not built):** presence `ZonePresenceTracker` / substrate still counts the frozen `on` (STEP-EXCLUDE-4), while `aggregation.py` zone sensors (`:1392`, `:1443`, ... read room `STATE_OCCUPIED`) release. Two zone views disagree for the outage. Pre-existing class (same as P22 stuck sensors), documented in PRESENCE state-of-play §4 and the header entry. Acceptable for S1.
- **AWAY / house state:** presence inference reads no room `STATE_OCCUPIED` (grep `presence.py`); nobody-home / night_raw read the tracker and live sensor state, α reads trackers + census. So S1 cannot make AWAY slower or flap. Census ripple (`camera_census._room_tier_corroboration_by_area`, `:3029-3060`) loses the room's corroboration, which only moves the stuck-camera classifier toward dropping the frozen camera (toward fewer phantom bodies). `person_coordinator.py:1726` Tier-3 disambiguation stops placing a person in the vacated room. Both correct direction.
- **Fan recheck:** a vacated room is vetoed `not_occupied` (`presence_fan_recheck.py:583`); `any_radar_bearing_on_now` is fusion-filtered. No recheck on a stream-dead room. Fine.
- **Duty-cycle corroborators:** read raw `_is_sensor_on`, but the panel sensors (presence list, kind mmwave) are not corroborator kinds (`sensor_role.py` motion/pir/pir_split/bed). Not reachable.
- **sensor_exclusion contract:** `camera_stream_dead` promotes after `reset_tick` (`:3499`) every tick, released implicitly by not re-promoting; no external reader of `_exclusion_set` outside `coordinator.py`. Chatter's release `clients_for` check runs before this client promotes, but only pops `_stuck_sensor_kinds`, which this client never writes. Multi-client on one input (P22 at 4 h + camera) is idempotent per client. Holds.

## Restart / lifecycle

- Registry listener: subscribed after `super().async_config_entry_first_refresh()` succeeds (`:1556-1566`), appended to `_unsub_state_listeners`, which first_refresh clears on re-entry (`:1525-1527`) and unload clears (`__init__.py:6096-6099`). No other site clears that list. No leak.
- Per-tick cost: resolution cached; rebuild only on input-list change or registry event (invalidate is O(1), rebuild O(inputs) with `get_entries_for_device_id`). Per tick: one `hass.states.get` per resolved camera. Negligible. 40 bus listeners on `entity_registry_updated`, each O(1).
- NM tasks via `async_create_task` follow the existing `untracked-ok` pattern; fire-and-forget, no state touched after await.

## Invariant checklist

| Invariant | Status |
|---|---|
| INV-STREAM (configured inputs, room fusion) | PASS (B-M1 is a sibling leg outside its scope) |
| Unresolved / kill switch False byte-identical | PASS (no promote, tracker state only) |
| AWAY not slower, no flap | PASS (no presence inference input changed) |
| Listener cleanup on reload/unload | PASS |
| S1-alone zone/census inconsistency documented | PASS (state-of-play header + §4) |

Must-fix: none. Recommended: record B-M1 in the state-of-play and S2 scope; consider B-L1 (`restored` = no opinion).
