# Review: fix/mf-skip-tv-audio (811032eb9), Tier 1, framing A

Diff base: merge-base b0c783231 (`git diff develop...fix/mf-skip-tv-audio`). Tests: test_music_following*.py, 231 passed.

## Findings
- **Placement holds.** music_following.py:2625 runs after `source_not_playing` and before path resolution (2851), the fade (3003), join (3074) and play_media (3086). Every check before it is read-only. The arrival engine's play_media (1422) plays from a profile pick and never moves a source, so bypassing `_pipeline` there is correct.
- **No false positives.** HA Sonos reports `source` as "TV" or "Line-in" (sonos/const.py:183-185) and None for streamed music. Linkplay/WiiM reports "Wifi" or "Spotify" for streams (linkplay/media_player.py:44-69). Neither is in the set. Values are lower-cased and stripped.
- **LOW, false negatives (bug class #53, partial coverage):** linkplay "ARC", "Line In 2", "Optical 2", "Coaxial", "Coaxial 2", "Phono", "RCA", "XLR" and "Bluetooth" are missing from MF_NON_TRANSFERABLE_SOURCES (const.py:4578). These cases behave as before the fix. A prefix match ("line in", "optical", "coaxial") plus "arc" would cover them.
- **MF_OUTCOMES consumers** (sensor.py:8743, music_following.py:454/2262/2391) build their dicts from the tuple, so the new outcome is included automatically. It is not in `_NOT_SKIPS`, so it counts as a skip, which is correct.
- The `why` string follows the existing `(outcome, reason)` convention.

**Verdict: SHIP.** The LOW is optional.
