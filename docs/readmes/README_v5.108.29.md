# v5.108.29: People settings screen (step 8 §10.1, nothing acts yet)

Cards: PEOPLE-SCREEN-1 (this release; child of PERSON-PROFILE-PREFERENCES-1, which stays open for D2 arrival music,
D3 welcome scene, D4 departure pause, D6/D7 and v6.0.0).
Plan: `docs/planning/PLANNING_identity_actions_v6.md` rev 3.6.1 (29b3aac9) §10.1. Branch
`feature/step8-identity-actions` (fix pass b769c29e, develop merge 235f5c0f).
Tier 2-DB: reviews A + G, B, C (130 per-site mutations), then a fix pass with 40 of 40 fix sites RED on mutation.

**Configuration only.** The new profiles are stored and shown; no code reads them to act. Arrival music, welcome
scenes and the departure pause are later releases. Lighting is byte-identical: the entry-path hook returns nothing
until the welcome-scene engine exists. Saving the People screen never reloads the integration.

## What ships

- **People screen** (URA integration options > People). Pick a person, then:
  - their bedrooms and bathrooms (rooms list filtered to current rooms; a deleted or retyped room is dropped on save);
  - "Arrival actions" master switch (ON by default), auto music, music volume (clamped), daytime / evening / my music
    picks, "different music per room" (each room labelled by its name), welcome scene (must be a `scene.*`);
  - suggestions from history are shown, never stored.
  - Clearing a pick clears it; a field that is hidden by its toggle keeps its stored value.
- **Profile store** in the integration options `person_profiles`, keyed by the one person-id rule; owners derived.
- **Sensor** `sensor.ura_person_profile_<person>` (diagnostic, polled): state 0-2, attributes unrecorded, deleted rooms
  dropped from `rooms`.
- **Speakers** (config, 2026-11-15): Jaya Bedroom and Ziri Bedroom now have room players (`media_player.jayas_room_3`,
  `media_player.ziris_room_3`).

## Validated 2026-11-15 (restart ~21:47 CST)

| Criterion | Result | Evidence |
|---|---|---|
| B0 form renders | PASS | CM entry 01KJEC3FYPYAGBQKZWC94CR8GR > People: person picker lists person.ezinne / oji_udezue / jaya / ziri; picking oji renders `people_profile` with sections `my_rooms` (bedrooms 47 rooms, bathrooms 8, options are value/label pairs so names display) and `automate` (auto_music, music_default media, volume 0.05-1, vary_time, day, evening, vary_room, auto_scene, welcome_scene `scene.*`). Flow aborted, nothing saved |
| B0 save / clear-field shape | pending operator | needs a real save from the UI; the code handles both "omitted" and "sent empty" (A3) |
| Profile sensors | PASS | `sensor.ura_person_profile_{ezinne,oji_udezue,jaya,ziri}` all present, state 0 (no profiles yet), distinct ids |
| No reload on save | pending first save | in-suite: `person_profiles` in both no-reload key sets (pins 134) |
| Lighting unchanged | PASS by construction + suite | the entry hook returns None until the D3 engine exists |
| Logs | PASS | system log ERROR filtered on `universal_room_automation`: 0 entries |

HA config change in the same window (operator "Remove it"): `device_tracker.okosisipadmini6_2` removed from `person.oji_udezue` (backup `.claude/tmp/person.storage.bak-20261115`); the iPad was the source of all 29 phantom arrivals in D0b.

## Not in this release

D2 arrival music engine, D2b follow-me option, D3 welcome scene engine (incl. the slot-scene retry, review B2), D4
departure pause, D6 episode writers, D7 trip-wires, the D0b probe, the live Music Assistant playback test. Review C LOWs
L5, L7-L12 (display / unreachable). All on PERSON-PROFILE-PREFERENCES-1.
