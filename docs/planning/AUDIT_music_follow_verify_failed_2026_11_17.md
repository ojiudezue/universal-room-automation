# AUDIT: music_follow_decision 7/7 verify_failed (probed 2026-11-17 08:13 CST, read-only)

## Verdict
verify_failed is a REAL failure of an impossible transfer, not a verify-side defect. Not a .33/.34 regression: all 7 episodes (UTC 14:28-19:09 on 11-16 = 08:28-13:09 CST) predate the v5.108.33 deploy (commit abe2c3418, 15:18 CST) and the 15:32 restart. Zero episodes have been written since, and zero existed before 11-16 (memory_episodes min started_at = 2026-11-16T14:28 UTC), so there is no verify_ok baseline to compare.

## Mechanism
- Source in all 7: media_player.master_bedroom_sonos (platform sonos, soundbar) playing `x-sonos-htastream:RINCON_804AF277BE0D01400:spdif`, source "TV", title "TV" (recorder, 5 min before/after each episode). It is TV audio over SPDIF, not a music queue.
- _resolve_path (music_following.py:2826-2870): MA first needs MA twins of both ends. Source has none (`_ma_candidates` 2743 returns [] ) -> reason `ma_not_covered`; platforms differ (sonos vs wiim) -> `no_common_grouping` -> PATH_GENERIC. path_reason in every episode: "generic ma_not_covered,no_common_grouping".
- Generic path (_start_target, 3030+): `play_media` of the source's media_content_id on the target. Target WiiM cannot play a Sonos-proprietary htastream URI.
- Verify (_transfer_then_release, 2990-3011): sleep mf_verify_delay (2 s, const.py:4464), then reads target state; not playing -> restore volumes, return verify_failed. It reads the right entity (rec.target_player) and the right attribute (state).
- Recorder ground truth: ep1 (08:28) master_bathroom_3 goes playing at +1.6 s with title = the x-sonos-htastream URI ("URL Stream"), then idle at +3.7 s (media_content_id None). Ep 6/7 (Kitchen/Patio): kitchen_3 / patio_3 stay idle, only source/title attributes change. Eps 2-5: no target state rows in window. Music never moved; source kept playing throughout (no state change). Caveat: ep1 shows a brief false "playing" blip; the 2 s check landed after it (verify_ms 2033, target_state idle). A longer/shorter delay could have mis-read it as success.
- Side effect: move mode fades the source before verify (3410-ish "fade" block, then _restore_saved on failure) -> a ~2 s volume duck on the TV soundbar per attempt.

Episodes (CST 11-16; person; from -> to; path; source -> target; verify_ms; target_state):
1 08:28 Oji MasterBed->MasterBath generic sonos->master_bathroom_3 2033 idle (playing blip +1.6s, idle +3.7s)
2 08:30 Oji MasterBed->MasterBath generic same 2000 idle
3 08:44 Oji same 2000 idle
4 08:49 Oji same 2000 idle
5 09:12 Oji same (direct) 2653 idle
6 13:07 Ezinne MasterBed->Kitchen generic sonos->kitchen_3 2001 idle
7 13:09 Ezinne Kitchen->Patio (source stayed master sonos via lookback) generic sonos->patio_3 2001 idle

## media_player.master_bedroom_sonos_2
- Master Bedroom config entry OPTIONS room_media_player = media_player.master_bedroom_sonos_2 (data has None). Warning at music_following.py:3687 (`_get_room_player_src`).
- Entity registry: not live. It is in deleted_entities: platform music_assistant, unique_id media_player.master_bedroom_sonos (the MA wrapper of the HA Sonos), orphaned 2026-11-16 04:39 UTC (22:39 CST 11-15). No renamed successor; the Sonos device (faca3e9c...) now has only media_player.master_bedroom_sonos (sonos).
- Not the cause of any of the 7: the lookup falls through to zone/area (3689-3720) and the episodes' source_player is master_bedroom_sonos. It is the same event that removed the Sonos MA twin, so it is a contributing cause of `ma_not_covered` (MA wrapper gone), but even with an MA twin the content is TV input and could not be queue-transferred. Warning spam only (68x).

## Smallest fix
1. Code (Tier 1): in _resolve_source/_transfer entry, if source media_content_id startswith `x-sonos-htastream:` (or source attr "TV"/line-in) -> skip with outcome like `source_not_transferable` (no fade, no play_media). Charter note: following TV audio is not music; if the operator wants TV audio to follow, only a Sonos-native join to a Sonos target can do it.
2. Config: set Master Bedroom room_media_player to media_player.master_bedroom_sonos (or clear it) to stop the warning. Whether MA should re-wrap the Sonos (restore the MA twin) is an MA-side action; unknown why it was removed.
3. Needed test case: a real music source (Spotify on Sonos or an MA queue) has never been exercised in the episode data; the generic/MA path for real music is unverified by these 7.
