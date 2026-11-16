# URA v6.0.0 (DRAFT): identity actions, arc step 8

**Status: DRAFT, not deployed.** Plan: `docs/planning/PLANNING_identity_actions_v6.md` (rev 3.2). This
draft covers the §10.1 parallel set only (branch `feature/step8-identity-actions`, cut from
`feature/music-following-repair` @ `c5685b5f`). D2-D4 decision logic and D5 are not built yet.

## Built (§10.1 set)

- **D0 probe** `scripts/probes/identity_actions_d0.py`: read-only. Sections (a), (a1) counted-return
  share (review 3.1 H1), (a2) room occupancy onset minus BLE entry per own room plus location update
  cadence, (b), (c), (d). Not run yet; the operator runs it (`ssh ha "python3 -" < ...`).
- **D1 People step** (CM options menu "People"): pick a tracked person, then "My rooms" (bedrooms, bathrooms)
  and "Automate my entries" (music, volume, by time of day, per room, welcome scene). Store: CM option
  `person_profiles`, keyed by `person.*` id (one id rule); rooms by room entry_id; owners derived. A
  "Music by room" step follows when "Different music per room" is on and an own room has a speaker. A
  save never reloads the CM (`person_profiles` in `OPTIONS_RELOAD_SUPPRESS_KEYS` + `_NO_LIVE_ATTR_KEYS`).
  "Play my music" with no pick, or the welcome scene on with no scene, is refused at save.
- **Conditional fields**: `config_flow._cond` uses HA 2026.11 `data_entry_flow.Optional(visible=...)` when
  its signature takes `visible` (checked once), else a plain `vol.Optional` (every field shows).
- **Master** `music_on_arrival_start`, relabelled "Arrival actions": day 1 ON (consumer
  `person_profiles.arrival_master_on`, form default `DEFAULT_MUSIC_ON_ARRIVAL_START`).
- **Profile sensor** `sensor.ura_person_profile_<slug>` per tracked person (Music Following device):
  state = automated actions (0-2); attributes unrecorded.
- **`pick_media`** (`person_profiles.py`): room > time of day > default, slot from the room's own
  `resolve_slot`; sleep slot and `auto_music` off give None.
- **Entry-path hook**: `RoomAutomation._maybe_activate_slot_scene` (day / evening caller only) asks
  `hass.data[DOMAIN].get("music_following").arrival_scene_for(<room entry_id>)`; the engine method returns
  None until D3, so the entry path is byte-identical.
- **D6 episode types** `arrival_music`, `welcome_scene` registered (writer-health sets join with D2/D3).

## B0 live spike: PENDING (operator / orchestrator, HA 2026.11.1 CM options flow)

| Check | Result |
|---|---|
| (i) `data_entry_flow.Optional(visible=...)` inside URA's `vol.Schema` renders and serializes; record per-field `visible` to `quality/tests/fixtures/people_form_visible_2026_11_1.json` | PENDING (if it fails to serialize: stop and redesign with the operator) |
| (ii) MediaSelector in the options flow: render, submitted value shape, `entity_id` required | PENDING. Note: on 2026.2.3 a value without `entity_id` is rejected when `accept` is unset, so the stored pick keeps the browse player for re-display (playback drops it) |
| (iii) MA browse + play of the stored id on a different MA player | PENDING. Fallback ready: `const.PEOPLE_MUSIC_URI_FALLBACK_ENABLED` (rung 1, False) adds "or paste a Music Assistant URI" fields; `PEOPLE_MUSIC_URI_CONTENT_TYPE` ("music") is unverified |

## Live validation

Not deployed. Prospective: People form shows 4 fields with everything off and the music fields when
"Play my music" is ticked; profile sensor shows the saved fields; no CM reload in the log on save;
master label reads "Arrival actions".
