# URA v5.108.35: describe finds a room by its HA area name or alias; music following skips TV audio

Cards: VISION-INTERIOR-SIGHTINGS-1 (residual `residual_2026_11_17_describe_alias`; parent stays open for the vision
count leg, D4 census flip and ledger floor), ZONE-HAS-HOME-PERSON-UNCALLED-1 (docs only), MUSIC-FOLLOWING-TRANSFER-REPAIR-1 (residual
`residual_2026_11_17_verify_failed`). Tier 1, one review each (SHIP: `docs/reviews/code-review/v_describe_area_alias_review.md`,
`v_mf_skip_tv_audio_review.md`; the music review LOW, numbered linkplay inputs, fixed in 114877b1f).

## Why

The first live describe failed. The operator texted "describe family room" (2026-11-17 07:57) and got "I don't know a
room or person called 'family room'." The URA room is "Living Room" (area `living_room`); "family room" is the
household's word for it. `_describe_target` matched only the exact URA room name.

## What changed

- `person_sighting._describe_target` (`_rooms_by_area_word`): after the exact URA room name (unchanged, still wins), a
  target matches a room whose configured area (`CONF_AREA_ID`) has that name or alias in the HA area registry
  (casefold, whitespace normalised). An area word that maps to two or more rooms is refused: "'X' could mean A, B. Send
  the room name." Then the person branch (unchanged). Registry only; no entity-id or camera-name guessing.
- An unknown target's reply now ends "Rooms with a camera: ..." (from the interior camera groups), so the right word is
  in the reply.
- If the area registry lookup fails, the area step is skipped and describe still answers.
- `hvac_zones.zone_has_home_person` docstring marks it retired (no production caller). No behaviour change.

Precedence note (review LOW): an area name or alias now wins over a tracked person's first name if the two are equal.
No area word equals a resident first name today.

## Music following: TV and line-in sources are not followed

All 7 `music_follow_decision` episodes on 2026-11-16 were `verify_failed`
(`docs/planning/AUDIT_music_follow_verify_failed_2026_11_17.md`). The source was the Master Bedroom Sonos playing TV
audio (`x-sonos-htastream:...:spdif`, source "TV"). Music Assistant had dropped its Sonos wrapper on 11-15, so the
generic path sent the Sonos-only stream URI to a WiiM by `play_media`, which cannot play it, and move mode ducked the TV
for ~2 s before each failed verify. Not a v5.108.33/.34 regression (all 7 predate the .33 install).

- `music_following._non_transferable` runs in `_pipeline` right after the source-is-playing check, before path
  resolution, fade, join or `play_media`, so the MA, join and generic paths are all covered. New outcome
  `source_not_transferable` (in `MF_OUTCOMES`, counted as a skip), reason `content=<prefix>` or `input=<source>`.
- Knobs (rung 1, `const.py`): `MF_NON_TRANSFERABLE_CONTENT_PREFIXES` (`x-sonos-htastream:`, `x-rincon-stream:`),
  `MF_NON_TRANSFERABLE_SOURCES` (tv, line-in, hdmi, optical, spdif, aux, analog, arc, phono, rca, xlr, bluetooth and
  spellings), `MF_NON_TRANSFERABLE_SOURCE_PREFIXES` (line in, line-in, optical, coaxial, hdmi: linkplay numbers inputs).
- Reads only the source player's state attributes; Sonos reports `source` None for streamed music and linkplay
  "Wifi" / "Spotify", so real music still follows.
- Tests: 6 + 5 parametrized in `test_music_following_repair.py`; mutation: check removed -> 5 RED; prefix match
  removed -> 3 RED (Line In 2, Coaxial 2, Optical 2).

Operator config (not code): Master Bedroom `room_media_player` still names the deleted MA entity
`media_player.master_bedroom_sonos_2` (68 log warnings, no functional effect: lookup falls through to the Sonos).
Point it at `media_player.master_bedroom_sonos`, or re-add the Sonos in Music Assistant (which also restores the MA path).

## Operator action

Add the alias "Family Room" to the Living Room area (Settings > Areas > Living Room > Aliases). Until then "describe
living room" works, and "describe family room" gets the new reply listing the camera rooms.

## Tests

`test_describe_resolves_room_by_area_alias`, `test_describe_resolves_room_by_area_name`,
`test_describe_area_alias_ambiguous_refuses`, `test_describe_exact_room_name_wins_over_alias`; updated unknown-reply
text in `test_describe_unknown_target_no_call` and `test_describe_person_name_forms_and_ambiguous_first_name`. Mutation
drills: alias set dropped, area-match return removed, covered-room suffix removed: each RED on a named test.

## Live checks after install

1. `describe family room` before the alias: reply lists "Rooms with a camera: ...".
2. After the alias is added: `describe family room` returns a Living Room description (describe_requests +1, no
   describe_unresolved increment).

3. Next TV-audio session on the Master Bedroom Sonos with a room move: `Music follow decision ... outcome=source_not_transferable reason=content=x-sonos-htastream:` and no volume dip.
4. First real-music move (Spotify / MA queue): not `verify_failed`.

## Validated (to be written back after install)

## Not done

- Nothing planned was skipped.
