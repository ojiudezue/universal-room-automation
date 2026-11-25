## Music following no longer tries to move AirPlay (MF-MA-PATH-NON-MA-SOURCE-1)

**What changed.** When someone plays music to a WiiM speaker over AirPlay and walks to another room, music following now skips the move with the named outcome `source_not_transferable` (reason `input=AirPlay`, or `content=wiimu_airplay`). It does this before touching any speaker: no volume duck, no Music Assistant call, no play_media.

**Why.** AirPlay is pushed from the phone. Music Assistant has no queue for it, so every Music Assistant transfer failed (`ma:HomeAssistantError`, MA log "Resume queue requested but queue ... is empty"). From 11-21 to 11-24 there were 30 failed/ma decisions and no successes. At those failures the source speaker read `source: "AirPlay"` and its Music Assistant twin read `app_id: airplay`, `media_content_id: wiimu_airplay`, `active_queue: null`. No server-side path can move a phone's AirPlay stream.

**How.** `"airplay"` was added to `MF_NON_TRANSFERABLE_SOURCES` and `"wiimu_airplay"` to `MF_NON_TRANSFERABLE_CONTENT_PREFIXES` in `const.py`. These feed the existing pre-move gate (`_non_transferable`), which already skips TV and line-in. The check reads the speaker's attributes only, never entity names. Real Music Assistant queues still move over the MA path.

**Not done.** Moving AirPlay by joining WiiM speakers (linkplay join) is left out. It needs an attended live test first.

**Live acceptance (after deploy).**
- An AirPlay walk writes a `music_follow_decision` row with outcome `source_not_transferable` and reason `input=AirPlay`.
- The count of `failed` / path `ma` / `ma:HomeAssistantError` rows stops growing (30 as of 11-24).
- A walk with a real Music Assistant queue still produces path `ma`.
