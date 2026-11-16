# Step 8 §10.1 parallel set: review A (local correctness) + G (goal fidelity)

Branch `feature/step8-identity-actions` (worktree `builder-step8`), step 8 code diffed as
`git diff 486b2783...HEAD -- custom_components quality` (tip `470b760c`). Spec: `PLANNING_identity_actions_v6.md`
rev 3.4 §10.1 plus its "Decided deviations" table; D0 report `AUDIT_identity_actions_d0_2026_11_15.md`.
Read in full first: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`, the charter
(`ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`), `CONTRACT_person_awareness_layer.md`, and the plan
sections §1, §5, §8-§10. Corrections-ledger claims were not re-asserted.

Facts: this set produces no F1-F5 fact. It is per-person policy storage (consumer side) for future F5 consumers
(arrival music and the welcome scene, comfort class).

**Tree hazard.** While this review ran, another agent's mutation drill was live in the same worktree: first
`config_flow.py`, then `person_profiles.py` (`own_rooms` with bathrooms removed). Two failures in my one targeted
pytest run came from that drill. No verdict here rests on a test result. Reviewer C and the validator should own
the worktree serially.

## (A) Local correctness

| # | Sev | Site | Finding / failing input | Class |
|---|---|---|---|---|
| A1 | MEDIUM | `config_flow.py` `async_step_people_rooms_music` (fields keyed `vol.Optional(r["entry_id"])`); `strings.json` `people_rooms_music` has no `data` block | The fields are keyed by room config entry_id. HA cannot translate a dynamic key, so it shows the raw key as the label. Input: Oji turns on Different music per room with Master Bedroom (entry `01J…`) as his room. The form then shows a field labelled `01J…`, with no room name anywhere. Fix: name the rooms in order in the description placeholder, or key the fields by a stable slug of the room's own `room_name` and map that back to entry_id. | Label style guide / operator clarity |
| A2 | MEDIUM (gate) | `test_person_profile.py:337-345` skips when `fixtures/people_form_visible_2026_11_1.json` is missing (it is missing) | The D1 B0 live spike has not run. The `visible` condition shape (`{"field","value"}`, with a list meaning AND), the marker's `description` kwarg and the drop-on-hidden behaviour are checked only against a stub marker, which is the builder's own model of HA 2026.11. Plan §8 D1 says that if (i) fails, stop and redesign. This must run before ship, and the skip must not count as a pass. | #62 adjacent (the stub is the oracle) |
| A3 | LOW (verify in B0) | `person_profiles.py:224-257` `merge_profile_save` keeps the stored value when a key is absent | If the HA frontend leaves out an optional field the user cleared (as it leaves out hidden ones), then clearing Daytime music, My music or the welcome scene can never clear it. The stored pick survives and is still used when its toggle is on. Input: vary_time is on, the user blanks Daytime music and saves, and `music_day` stays. "A blank pick clears it" is reachable only if the frontend sends null or `{}`. Check this in B0. If the field is left out, use `_present` (the section-present set that is already returned) to tell "section submitted, key missing" (cleared) apart from "hidden". | Semantics of absent vs cleared |
| A4 | LOW | `automation.py:1768-1775` | When the welcome scene is under a hold or unavailable, the per-light path runs, not the room's slot scene. A room with a working slot scene therefore gets per-light lighting on a broken welcome scene. The plan says only "fell back", so this is a defensible reading. Record it, or retry with `slot_scene` on `unavailable` only (not on `hold`). | Spec ambiguity |
| A5 | LOW (latent) | `config_flow.py` `_media` puts `cur` in a MediaSelector `suggested_value` | A pasted-URI pick (`_people_apply_uri_fallback`) carries no `entity_id`. Shown again as a suggested value and saved unchanged, it fails `MediaSelector.__call__`, which requires `entity_id` without `accept` (verified in the venv). Unreachable while `PEOPLE_MUSIC_URI_FALLBACK_ENABLED=False`. Turning the knob on must also handle this. | Latent knob path |
| A6 | LOW | `config_flow.py` `_people_suggestions` | `PEOPLE_SUGGEST_MAX_VISITS` 5000 counts rows for the whole house, newest first, not per person. With heavy visit volume, the 30-day share leans toward recent days. Display only. | — |
| A7 | LOW (tracking) | `person_profiles.py:118-133` | Only the pure name-to-entry_id lookup is built. The cached map, rebuilt on `SIGNAL_ROOM_ENTRY_LIFECYCLE` (§5.1), does not exist yet. That is correct for §10.1, but it must appear in D2's plan-completion list. | #53 risk if forgotten |

Cleared, each with evidence:

- **One-id key.** `profiles_from_options` and `get_person_profile` re-key through `tracked_person_entity_id`, and `_people_save` writes under the same id. Display-name and entity-id `tracked_persons` both resolve to one profile. This is a string rule, but it is the sanctioned `person_ids` rule, not a registry guess.
- **Owners derived.** `room_owners` reads the profiles and nothing is stored on rooms.
- **Room-name map.** Blank, unknown, away, home and not_home all read None.
- **Master default True.** `DEFAULT_MUSIC_ON_ARRIVAL_START` is used both by `arrival_master_on` and by the form default (`config_flow.py:10523-10526`). Grep: no other reader of `music_on_arrival_start` uses a False default. The `music_following.py:567` docstring still says "OFF by default"; that is a stale comment to fix in D7.
- **`_cond` / `visible` feature-detect.** `inspect.signature` is checked once and cached, with a plain `vol.Optional` fallback on failure.
- **Suggestions never stored.** They go into `description_placeholders` only. The clock is naive local on both sides: `log_person_entry` writes `datetime.now()` and the read uses `str(_dt.now())`, so the string comparison is consistent.
- **Save-time validation.** Music on without a usable default pick, or scene on without a scene, is refused. The person label goes through `display_of` with no raw `person.*` read.
- **Media pick shape.** `normalize_media` keeps `entity_id` only when it is a string containing a dot, and `play_pick` strips it. The deviation is justified: HA 2026.2.3 `MediaSelector.__call__` adds `vol.Required("entity_id")` when `accept` is absent (checked in the venv).
- **`pick_media` truth table.**
  - `auto_music` off: None.
  - Sleep or any other slot: None.
  - vary_room on, own room, valid pick: the room pick.
  - vary_room on, not an own room: falls through.
  - vary_time on: the evening pick for the evening slot, the day pick for the day slot. A blank or invalid pick falls through.
  - Otherwise: the default, or None.
- **Volume clamp.** `music_volume` clamps to [0.05, 1.0]. Non-numeric input gives 0.30, NaN gives 0.05 and inf gives 1.0. The ×room-scale clamp to 0..1 is D2 and not built (correct for §10.1).
- **`occupied_since()`.** It is a pure delegate of `get_became_occupied_time()` (`coordinator.py:6396-6404`), with one source.
- **Entry hook.** Only the day/evening caller passes `arrival_override=True` (`automation.py:1591`). The sleep caller (`:1488`) uses the default False. With the engine stub returning None, the path is `slot_scene`, then the same hold check, state guard and one `scene.turn_on`, and the return is True only on `applied`. That matches the pre-change behaviour. Any engine exception, or a value that is not a `scene.*` string, reads None. The engine key `hass.data[DOMAIN]["music_following"]` is the `MusicFollowing` instance that carries the stubs (`__init__.py:3432`).
- **`note_arrival_scene_result`.** It fires only when a welcome scene was returned. Its four reasons map one to one onto the `_activate_scene_checked` exits, and the inner try/except means it cannot be skipped by a raise.
- **Profile sensor.** It is created on the CM entry (`sensor.py:243`). `AggregationEntity` does not set `should_poll`, so it polls and reads CM options fresh, and a save shows without a reload. Attributes are unrecorded. Tracked persons are read from integration `data`, the same as the PersonCoordinator (`person_coordinator.py:220`).
- **D6 types.** They are in `MEMORY_EPISODE_TYPES` only and not writer-backed, so no absence trip-wire can fire on them. This matches the plan; they move when D2/D3 add the writers.
- **No reload.** `person_profiles` is in both `OPTIONS_RELOAD_SUPPRESS_KEYS` and `_NO_LIVE_ATTR_KEYS` (`__init__.py:7591`, `:7735`), and `music_on_arrival_start` was not added again.

## (G) Goal fidelity

1. **Does §10.1 move toward the goals?** Yes, but only through the store. The People step and the profile are the
   PERSON-PROFILE-PREFERENCES-1 foundation, and the extras (bedrooms and bathrooms, time-of-day and per-room music,
   per-action opt-in, welcome scene) are all in. That honours "Don't want to defer too much" (drift #17). Nothing in
   §10.1 acts. A resident who fills in the People step today sees no behaviour change.
2. **Do the decided deviations change what is delivered?** No. Keeping `entity_id` affects only storage, and playback
   still plays on the room's own player. The scene result as a string carries more information than the bool did.
   `occupied_since` returns the same value.
3. **BLE F5, plainly.** On D0 data the `ble` source opens zero intents: 0 of 9 pass. GPS led every one of them, so a
   BLE F5 arrives after a later arrival edge and reads `recent_departure`. If it were not rejected there, the
   duplicate gate would catch it behind the geofence intent. In practice D2 rests on geofence alone, which passes 9 of
   15 and is not dead. `camera_egress` is 0 until step 7 ships. The design is not building on a source that never
   fires. However:
   - It is spending real build and review cost on one that does. The plan carries about eight `ble` tests and drills
     (patio LOST, S3 dog walk, overrule, unknown walk, boot window) for zero measured contribution.
   - §10 makes **BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 a must-ship-before-v6.0.0 dependency** for that same zero-yield
     source. That gates v6.0.0 ("get a move on") on nothing measurable.
   - **Recommendation for the operator:** demote BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 from the v6.0.0 gate. Keep `ble`
     as a supplementary source that fails closed, with its gates (cheap, and safe), and drop the dedicated `ble`
     drills to the two that guard safety (no departure seen; recent departure).
4. **Next to the BLE point, D0 shows a "never fires" risk in D2's occupied gate (HIGH for D2, not for §10.1).** Own
   motion leads the BLE room entry by a median of 3 to 7 minutes in the bedrooms, but `ARRIVAL_OCCUPIED_LEAD_S` is
   120 s. At 120 s most real entries would read `skipped_occupied` on the person's own motion. That is the rev 3 H3
   shape coming back in measured form. `occupied_since()` is built for exactly this gate. The lead (or an
   own-motion rule) must be decided with the operator before D2 builds; it is not a builder choice. Kids' bedrooms
   have no speakers, and the master's welcome scene passes about 1 entry in 3 under the zone rule (§12 Q4). Both are
   operator items that set how often "When needed it's beautiful" happens at all.
5. **§10.1 work that matters only once D2/D3 exist:** `pick_media`, `play_pick`, `music_volume`,
   `room_entry_id_for_name`, `occupied_since()`, `arrival_scene_for` / `note_arrival_scene_result` with the
   `automation.py` hook and the `ARRIVAL_SCENE_RESULT_*` constants, the D6 episode types, the profile sensor's
   `last_arrival_action` (always None), and the master relabel to "Arrival actions" (its description promises
   behaviour that does not yet exist). The only parts with standalone value are the People step, the profile store
   and the profile sensor. Shipping §10.1 alone delivers configuration with no actuation, so it is not v6.0.0.

## Verdict

**FIX-REQUIRED (small)** for the §10.1 set:

1. A1: label the Music-by-room fields with room names.
2. A2: run the D1 B0 live spike and record the fixture before ship. Do not ship on the stub alone.
3. A3: settle absent-versus-cleared in the same B0, and fix it with `_present` if the frontend leaves out cleared
   fields.

The LOWs (A4-A7) can be fixed in the same pass or recorded. Before D2 is dispatched, the operator decides two things
(G3, G4): drop the BLE producer card from the v6.0.0 gate, and size `ARRIVAL_OCCUPIED_LEAD_S` (or an own-motion
rule) against D0's 3-to-7-minute lead.

| Sev | Found |
|---|---|
| HIGH | 0 in §10.1 (1 goal-fidelity HIGH aimed at D2: G4) |
| MEDIUM | 2 (A1, A2) |
| LOW | 5 (A3-A7) |
