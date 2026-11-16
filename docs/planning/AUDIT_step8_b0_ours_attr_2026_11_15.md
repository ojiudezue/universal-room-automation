# AUDIT: step 8 D2 B0 passive check, "ours" attribute (2026-11-15)

Prober, read-only. Window: recorder `/config/home-assistant_v2.db`, earliest row in window 2026-11-08 ~03:32 CST to 2026-11-15 22:08 CST (~7 days).
Scripts: `.claude/tmp/b0_probe_{players,registry,attrs,queue,wiimq}.py` (read-only SQLite URI mode=ro over `ssh ha`).
Read first: PLANNING_identity_actions_v6.md rev 3.6.1 lines 753-767 (D2 B0 / HIGH-2 branches T / Q / neither; `ARRIVAL_OURS_ATTR`).
Engine read: branch feature/step8-d2-engine, `music_following.py`.

## VERDICT: INSUFFICIENT (passive history cannot settle T vs Q), with two hard findings

1. Nothing in 7 days resembles an engine start. Every playing session on every room player and twin was an externally started Spotify Connect or AirPlay session, never an MA queue start from a playlist/album URI. Evidence: `active_queue` is `None` on every playing state of every WiiM twin (jayas_room_7, kitchen_7, patio_7, breakfast_7, dining_7, master_bathroom_7, master_shower_7, study_a_7, ziris_rooom_3), `app_id` is `spotify` / `airplay`, never `music_assistant`. No attribute equal to a playlist URI was ever seen (content ids observed over all 188 MA media_players, playing states only: `wiimu_airplay` 3029, `spotify:track:<id>` 519, `homeTheater-input` 167, `line-in` 25+3, `AIRPLAY` 2, `SPOTIFY` 2, empty 1).
2. Branch T is falsified for those sessions and for the native WiiM: the MA twin's `media_content_id` changes every track (e.g. kitchen_7 11-14 10:35, 7 titles, 7 distinct `spotify:track:` ids), and the native WiiM players expose NO `media_content_id` at all. `queue_position` / `queue_count` on native WiiM are constant 0 (jayas_room_3, 11-14 09:16-18:03). So `media_content_id` is stable across tracks only if MA reports the queue-start URI, which no history row shows; by the MA source below it reports the current item's URI, so T is expected false for real queue starts too.

## Per-attribute table (playing sessions, spanning several tracks)

| Attribute | MA twin (`*_7`, ziris_rooom_3) | Native WiiM (`*_3`) | Per track? Holds for session? |
|---|---|---|---|
| media_content_id | `spotify:track:<id>` / `wiimu_airplay` (AirPlay) | absent | per track (Spotify); constant only for AirPlay |
| media_content_type | `music` | `music` | constant, non-discriminating |
| media_title / media_artist / media_album_name | change | change | per track |
| media_playlist | never present | never present | n/a |
| app_id | `spotify` / `airplay` | absent | holds (identifies source, not "ours") |
| source | `Spotify` / `AirPlay` | `Spotify` / `AirPlay` / `Breakfast` (group follower name) | holds, but changes mid-session once (patio_3 11-14 11:06 AirPlay to Spotify) |
| active_queue | `None` always (queue ids never seen) | absent | n/a |
| mass_player_type | `player` | absent | constant |
| queue_id | not an attribute | not an attribute | n/a |
| queue_position / queue_count | absent | 0 / 0 | constant 0, useless |

## Entity classes

- WiiM native (`wiim` platform, registry): jayas_room_3, kitchen_3, patio_3, breakfast_3, dining_3, master_bathroom_3, master_shower_3, study_a_3, utility_3, ziris_room_3, livingroomwiimsub_2. No content id, no queue attribute.
- WiiM MA twins (platform `music_assistant`, unique_id `wiim_uuid:<UUID>` matching the native `wiim` unique_id): *_7 and `ziris_rooom_3` (twin of ziris_room_3). Note README_v5.108.26 inventory lists `_5` twins (kitchen_5 etc., unique_id `upc...`); the playing twins are the `_7` / `wiim_uuid` ones. The `_5` entities have 0 playing rows. Which twin the engine's `_ma_candidates` picks needs the engine author to confirm (not verified here).
- Sonos: native `media_player.master_bedroom_sonos` (platform sonos) plays only TV (`x-sonos-htastream:RINCON_804AF277BE0D01400:spdif`, source TV, queue_size 1), per track none. Its MA twin `master_bedroom_sonos_2` has 30 rows, never playing, attributes only device_class/icon. No Sonos music session in window.
- Denon `living_room_2`: 0 playing rows, no content id attr; no MA twin. Not measured.

## Engine read (feature/step8-d2-engine, music_following.py)

- Start path (lines ~1120-1160): `play_eid = ma or native`; calls `media_player.play_media` on the MA twin with the stored pick (`**pick`); verifies `playing` after `ARRIVAL_VERIFY_S`; stamp built by `_read_ours` (line 1211) which reads `_c.ARRIVAL_OURS_ATTR` from BOTH `stamp.native` and `stamp.ma` and keeps any non-None value; `_ours_now` (1226) compares `state.attributes[attr] == stamp value` on each. `ARRIVAL_OURS_ATTR` is `None` in const (const.py:5223 in that worktree), so `verifiable()` is false and the window-end stop / departure pause are inert until set.
- Because native WiiM has no content id and no queue attribute, reading the attribute on the native is a no-op (value None, skipped), so only the MA twin can ever carry a stamp.

## MA integration source (for the untested branch)

WebFetch of home-assistant/core `homeassistant/components/music_assistant/media_player.py` (dev branch, fetched 2026-11-15, no line numbers returned): `extra_state_attributes` returns `ATTR_ACTIVE_QUEUE` = `active_queue.queue_id` or None; `active_queue` = `mass.player_queues.get(player.active_source)`; `media_content_id` = `player.current_media.uri` (current item, not the queue); `app_id` = `music_assistant` when a queue exists, else `player.active_source`. `media_playlist` does not exist as an attribute. Installed-version source not verified (not found on the host); treat as expectation.

## Recommended ARRIVAL_OURS_ATTR

`active_queue`, read on the MA twin only (the `*_7` / `wiim_uuid` MA entity the engine plays on), as the provisional Q-branch value. Reasoning: it is the only attribute that, per MA source, is stable across tracks of an MA queue session. CAVEATS (must be settled by the live B0 with operator present, not by this probe): (a) never observed non-None on any twin in 7 days, so its presence and value after `play_media` are unproven; (b) per MA source, a queue id is per-player (`queue_id = player_id` fallback), so it likely equals the same string for ANY MA queue on that player, including one the operator starts by hand. It would then prove "an MA queue is active", not "our start", and would mis-label operator playback on the same player as ours. If the live B0 shows that, the discriminator needs the stamp plus another signal (for example `media_content_id` captured at start AND `app_id == music_assistant`, with the stop gated on queue replacement rather than track), which is a planning question for the operator ("neither" branch).

## Falsification

What would change this: any live read after a real engine `play_media` showing `active_queue` non-None and unchanged across a skip (supports Q), or `media_content_id` unchanged across a skip (supports T). History cannot contain these; the first engine start in the house will. The engine's own `music_end` "started" event carries `ours_attr` and `ours_verifiable`, so the first real arrival start reports whether the stamp was readable.

## Not measured

Denon (no playing history), Sonos music (only TV), any MA-started session, URI-fallback paste. No playback was started; no HA state changed.

## Addendum 2026-11-15 22:30 CST: which MA twin does music following target? (read-only)

Method: `_ma_candidates` (music_following.py:1140-1195) replayed by hand over `.storage/core.entity_registry`, `core.device_registry`, `core.config_entries` (scripts `.claude/tmp/mfcand_probe*.py`); 7-day state mix from the recorder (`ssh ha sqlite3 -readonly`). No HA changes, no media calls.

**Verdict: (b) for all 10 WiiM rooms. Music following targets a twin that is never even available, so the MA path can never be taken; transfers silently fall back to native WiiM join.**

Candidate lists (reason in brackets). `_7` is NOT in any list:

| Room | room_media_player | candidates | `_5` 7-day states | actual playing twin |
|---|---|---|---|---|
| Study A | study_a_3 | study_a_5 [mac_in_ma_id] | unavailable x27 | study_a_7 (not listed) |
| Guest Bedroom 2 | up_guest_room_3 | up_guest_room_5 [mac_in_ma_id] | unavailable | up_guest_room_7 |
| Study B | study_b_3 | study_b_5 [mac_in_ma_id] | unavailable | study_b_7 |
| Guest Bedroom 1 | guest_room_3 | guest_room_5 [mac_in_ma_id] | unavailable | guest_room_7 |
| Kitchen | kitchen_3 | kitchen_5 [mac_in_ma_id] | unavailable x27 (kitchen_7: playing 104) | kitchen_7 |
| Ziri Bedroom | ziris_room_3 | ziris_rooom [mac_in_ma_id] | unavailable x27 | ziris_rooom_3 |
| Jaya Bedroom | jayas_room_3 | jayas_room_5 [mac_in_ma_id] | unavailable | jayas_room_7 |
| Garage B | garage_b_3 | garage_b_5 [mac_in_ma_id] | unavailable | garage_b_7 |
| Laundry | utility_3 | utility_5 [mac_in_ma_id] | unavailable | utility_7 |
| Master Bathroom | master_bathroom_3 | master_bathroom_5 [mac_in_ma_id] | unavailable | master_bathroom_7 |
| Master Bedroom | master_bedroom_sonos_2 (is MA) | itself [is_ma] | unavailable (never music; native Sonos plays TV only) | n/a |
| Living Room | living_room_2 (denonavr) | none | n/a | n/a (ma_not_covered) |

Why `_7` is missed: the `_7` MA devices carry identifier `('music_assistant','wiim_uuid:FF98F359-7D20-0A82-DAB8-1047FF98F359')` (study_a_7 shown). Matching rules are same-device, `media_player.*` identifier wrap, and the native device's MAC contained in the identifier hex (1175-1186). `wiim_uuid:` ids carry no MAC and no HA entity id, so none fires. The `_5` ids (`upc0f5358bec04`) embed the MAC, hence the hit. The native device's own identifier is `('wiim','FF98F3597D200A82DAB81047')`, which is exactly the `_7` uuid with dashes stripped (plus a trailing 8-hex suffix). Checked: 10/10 WiiM rooms map to exactly one `_7`/`ziris_rooom_3` this way.

Twins, devices: every `_5`, `_7`, `_airplay`, `_6` (aircast) twin is its own MA device (distinct device_id, distinct `music_assistant` identifier); none shares a device with the native wiim entity. So `_5` and `_7` are two MA player entries for one physical speaker (different MA providers/protocol entries; the `up`/`wiim_uuid`/`upcccc` prefixes suggest UPnP/WiiM/aircast providers, provider mapping inferred from the id prefixes, not verified in MA).

Caller selection rules (all in music_following.py; no other file calls `_ma_candidates`, grep of custom_components):
- `_resolve_path` 1202-1221: FIRST playing source candidate (`playing[0]`, 1208); target = first candidate with same match-kind, else first candidate (1209-1210). Gate: needs source cands, target cands AND a playing source cand (1207). Here the source cands are `_5`, never playing, so it takes `reasons.append("ma_source_not_playing")` (1225).
- `_bonus_candidates` 1550 (exclusion set, ALL candidates) and 1569-1572 (`mas[0][0]`, first; only when path is MA/via_ma, which cannot happen here).
- hazard scope 1959: ALL candidates added to the stop scope, so `_7` is not in the hazard-stop set (native `_3` configured players are, so the speaker is still reached via native; `_7` MA queue itself not directly stopped. Not traced further).

Impact on a transfer: no failure and no wrong-provider play. `_resolve_path` falls to the native branch 1228-1240: both players platform wiim with grouping feature, so PATH_JOIN (native) with reason `ma_source_not_playing`; Master Bedroom/Living Room use generic or ma_not_covered. The MA-first path (queue transfer, ma_join extend) is dead for every WiiM room. Note the `playing` test reads state of `_5`, which is `unavailable`, so it is always false.

Falsifier checked: if `_5` ever played or was available, (b) would be wrong; recorder shows only `unavailable` for all 11 listed twins over 7 days.

Smallest fix (not applied): in `_ma_candidates` add a fifth rule inside the identifier loop: if `sval.startswith("wiim_uuid:")` and the native device has a `wiim` identifier W, and `sval[10:].replace("-","").upper().startswith(W.upper())`, append `(x.entity_id, "wiim_uuid_match")`. Registry-only, ~6 lines, no name guessing. Also prefer entries whose state is not `unavailable` (or drop `mac_in_ma_id` hits that are unavailable) so `playing[0]`/`(same_kind or t_cands)[0]` picks `_7` over `_5`; with both listed, `_5` currently sorts first only by registry order, so the filter or reorder is required. Needs its own tests; Tier 2 (shared transfer path), not run here.
