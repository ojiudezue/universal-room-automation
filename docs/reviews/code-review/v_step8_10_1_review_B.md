# Step 8 §10.1 parallel set: Review B (integration, lifecycle, data integrity)

Branch `feature/step8-identity-actions` @ `470b760c`, diff `486b2783...HEAD -- custom_components quality`
(three-dot; `486b2783` is develop's tip and the merge `48fd8deb`'s second parent; develop has no
`custom_components` change since). Docs read: PLANNING_identity_actions_v6.md §5.5, §10, §10.1; contract and
PRESENCE state of play (this set adds no presence read; `occupied_since` delegates to
`get_became_occupied_time`).

## Verdict: SHIP (no CRITICAL/HIGH). Two MEDIUMs to fix in-cycle or card before D3.

## Findings

| # | Sev | Where | Finding / repro | Class |
|---|---|---|---|---|
| B1 | MEDIUM | config_flow.py `_people_profile_schema` rooms fields (`vol.Optional(PROFILE_ROOMS_BEDROOM, default=list(stored...))` / bathroom) | A stored room entry_id that is no longer an option makes the People form refuse its own default. HA `SelectSelector.__call__` (venv selector.py:1477-1485) is `vol.In(options)` per item. Repro: profile `rooms_bedroom=[X]`; delete room X (or change a bathroom's type away from bathroom, which drops it from `baths`); open People, pick the person, press Submit untouched -> invalid value, save blocked until the user removes the raw-id chip. Fix: filter the defaults to the current option values (and drop the dangling ids on save). | Stale reference after rename/delete (#7 stale data source) |
| B2 | MEDIUM (lands with D3; inert now) | automation.py:1768-1776 | When the engine returns a welcome scene and the hold check or state guard fails, the function returns False and the per-light path runs. The room's own slot scene is never tried. Once D3 returns scenes: room with `CONF_LIGHT_SCENE_EVENING` configured + owner's welcome scene `unavailable` -> per-light lighting instead of the room's scene. The plan text says "the state guard fell back", so this matches the letter; decide in D3 whether `unavailable`/`error` should retry `slot_scene` (hold must stay per-light). Today the stub returns None, so it is unreachable. | Existing-outcome change behind a new override |
| B3 | LOW | sensor.py `PersonProfileSensor.extra_state_attributes` `rooms` | A deleted room shows as its raw entry_id (`names.get(r, r)`). Unrecorded and diagnostic, so no leak; cosmetic. Pair with the B1 fix. | Stale reference |
| B4 | LOW | domain_coordinators/music_following.py:567 | Docstring still says CONF_MUSIC_ON_ARRIVAL_START is "OFF by default"; it is now `DEFAULT_MUSIC_ON_ARRIVAL_START = True` (const.py:5033). | Doc drift |

## Checks that hold

1. **Store round-trip / no reload.** `_people_save` writes `{**options, person_profiles: ...}` via
   `async_create_entry`; only `person_profiles` changes, it is in `OPTIONS_RELOAD_SUPPRESS_KEYS`
   (`__init__.py:7735`) and `_NO_LIVE_ATTR_KEYS` (`:7590`), so the CM listener takes the subset branch
   (`:8855`) and advances the snapshot via the `_NO_LIVE_ATTR_KEYS` loop (`:8528`). It is not in
   `_EC_CONSTRUCTION_ENTITY_KEYS`, so no parent reload. `music_on_arrival_start` was already in the suppress set
   and is not re-added. Readers (`get_person_profile`, sensor, `arrival_master_on`) read `entry.options` fresh;
   the sensor is polled (AggregationEntity does not set `should_poll=False`), so a save shows within one scan.
2. **Master migration.** Key unchanged; only the default flips. Live CM options (read-only, `.storage`): key
   absent, so it reads ON after deploy. The only consumer today is `person_profiles.arrival_master_on`, which
   nothing calls yet; `_handle_person_arriving` is still a DEBUG no-op. No actuation change in this set.
3. **Restart.** Profiles are persisted options; profile sensor unique_id is slug-based and stable; no restored
   state. Room rename is safe (entry_id keys, names resolved live).
4. **Entry hook byte-identity.** With `arrival_scene_for` returning None: `scene_id = slot_scene(...)` as before;
   APPLIED->True, HOLD/UNAVAILABLE/ERROR->False, which is the pre-change return per branch; the outer
   except is unchanged; `_note_arrival_scene_result` is not called. The sleep caller (automation.py:1488) does
   not pass `arrival_override`, so it never reads the engine. Hold semantics are lighting's own (same
   `_maybe_activate_slot_scene` hold check, fallback to the per-light path that honours holds).
5. **Merge integrity.** `git diff <develop> HEAD -- music_following.py` is only the two stub methods; no other
   definition of `arrival_scene_for` / `note_arrival_scene_result` exists. `MEMORY_EPISODE_TYPES` diff vs develop
   is +2 (`arrival_music`, `welcome_scene`), nothing dropped.
6. **People label.** `_people_tracked` (config_flow) is the only caller of the `display_of` label; it is new on
   this branch, so no other code depended on the friendly name.
7. **Guard delta = 0.** Ran `_layer_guard_engine.scan_tree` on both trees: 280 hits at `486b2783`, 280 at HEAD,
   no per-key delta; `compare(...)` against the allowlist returns `[]`.
8. **Profile sensor.** Unrecorded: rooms, shared_room_owners, music, welcome_scene, last_arrival_action,
   person_entity. Recorded state is an integer 0-2. Diagnostic category. No location or presence data.
9. **D6 types.** No writer in the tree emits `arrival_music` / `welcome_scene` (grep: only const.py, the sensor
   attr name and strings). Writer-health and absence trip-wires iterate `MEMORY_WRITER_BACKED_EPISODE_TYPES`
   only (database.py:11556, :11606), which does not contain them, so nothing alarms before D2/D3.

## Stats
CRITICAL 0 · HIGH 0 · MEDIUM 2 · LOW 2. Classes: stale reference (2), override changes existing outcome (1),
doc drift (1).
