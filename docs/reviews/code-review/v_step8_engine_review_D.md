# Step 8 arrival engine, review D (adversarial completeness, diff-blind)

Branch `feature/step8-d2-engine` @ f7277a07, base c67b8a78 (merge-base with develop, three-dot). Read-only.
Read first, in full: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`; plan rev 3.6.1 §5.4-§6;
D0b audit. Live reads (selected keys only): room config for bedrooms and bathrooms, zone players, the four bedroom/bathroom
players' `group_members`.

**Live mitigation.** `ARRIVAL_OURS_ATTR = None` (`const.py`), so the window-end stop and the departure pause are always
withheld today (`wait_kept_unverified` / `departure_kept_unverified`). Live exposure is the START and the SCENE paths.
The stop and pause findings below are latent: they arm when B0 sets the attribute, and they must be fixed before that.

## Invariants, falsifiable form

- START: no `play_media` from step 8 unless a counted, non-stale, out-of-boot, away-≥MIN arrival edge, AND no other
  person or guest can hear the target player.
- WAIT: each `started` ends in exactly one recorded terminal; the stop never reaches a player someone is hearing.
- SCENE: welcome scene only in the owner's own bedroom, at most once per entry.
- DEPARTURE: at most one `media_pause` per stamp; none after an owner arrival edge; none on a grouped player.

## Leaks

| # | SEV | Invariant | Site | Repro (legal config) |
|---|---|---|---|---|
| D1 | MEDIUM (latent until B0) | WAIT exactly-one / trip-wire | `music_following.py` `_window_end_music` stop `await self._call(...)` then `_music_end(...wait_expired_stopped)`; `_on_player` sets `not_ours_seen` on URA-context writes too | Stop issued; player turns idle and the listener (URA context, no reversal) sets `not_ours_seen` and spawns `_arrival_tick`. If that tick runs while the stop await is still open, it records `wait_ended_not_ours` and ends the stamp. Then `wait_expired_stopped` is suppressed (`music_done`), the reversal watch sits on a dead stamp, and `stopped_then_arrived` can never count, so the `arrival_stop_premature` HIGH trip-wire goes blind. The same race in `_departure_check`: the pause's own state write leads to `departure_kept_not_ours` being recorded for a pause URA sent. Or, if the state has not changed yet, a second concurrent check sends a second `media_pause`, breaking "exactly once". Fix: mark the stamp "acting" (or done) before the await and ignore URA-context writes in `_on_player` for `ours`. |
| D2 | MEDIUM (latent until B0) | WAIT never-stop-a-listener; NEVER-INTERRUPT | `_window_end_music` has no group check (departure has B6) | Oji's music starts on the master Sonos. At minute 5 Ezinne, downstairs, joins the living-room Sonos to the master group, so the content is the same and `ours` holds. Oji never goes up and the master reads vacant, so at 15:00 `media_stop` on the master stops the living room Ezinne is listening to. Fix: run the B6 group test before the stop (`wait_kept_group`). |
| D3 | MEDIUM (live, start half) | START "into an occupied room" | `_music_start` gates 3/6: `_any_playing` only checks members that are PLAYING, and there is no group test | The target player sits in an IDLE Sonos group with another room (groups persist after playback). Oji arrives, and `play_media` on a grouped member plays on the coordinator, so the whole group plays, including a room where people are. Not grouped live today (`group_members` null on all four players); legal and common. Fix: refuse (`skipped_grouped`) when `group_members` lists another entity. |
| D4 | MEDIUM (live, start; latent stop/pause) | START / WAIT / DEPARTURE "someone listening" | `_others_in_room`, `_room_occupied` read only the target room; the ensuite rule applies to P only | Oji and Ezinne share Master Bedroom and Master Bathroom (live). Ezinne is in the Master Bathroom (BLE-placed), the bedroom is vacant, Oji's GPS edge fires: music starts on `master_bedroom_sonos_2`, which she hears. Oji stays in the kitchen, so at window end the bedroom is vacant, nobody is "in R", and there is no co-owner intent, so it stops (once B0 is set). The departure pause behaves the same way (step 5-6 checks the stamp room only). Fix: for the "others" checks use the stamp room's suite (owners' bedroom ∪ bathroom set) and the co-owner's placement in any of it. |
| D5 | MEDIUM (latent config) | START "into an occupied room" | `_get_room_player` returns the house-zone player (`_get_zone_player_config`) for a room with no own speaker; `_target_room` / `_music_start` treat it as the room's | A bedroom with no `room_media_player` and no area speaker, in a zone with `zone_player_entity` set (legal). Music starts on the zone speaker, audible in every room of the zone; occupancy, others and backstop checks look only at the bedroom. Live: no zone players configured, so not reachable today. Fix: the arrival target accepts a room-owned player only (config or area), never the zone fallback. |
| D6 | LOW-MEDIUM | START "never on a flap" | gate 3b DB path `_away_long_enough` + residency `counted_return` M-2(ii) | The ledger is never seeded at setup (`_feed_residency` sees no event for a person already `home` when presence subscribes). Ziri leaves at 07:45 (departure row D). HA restarts 15:28-15:33 and Ziri gets home at 15:30. Person flips `home` before URA presence subscribes, so there is no event and no arrival row. Hours later a Bermuda reload makes person.ziri `unknown -> home`: `counted=True` (no real transition since setup), not stale, not boot; `left_at` None; DB: D with no later A, so it passes and music starts while she has been home for hours. Fix: when `left_at` is absent and `old_state` is unknown/unavailable, fail closed (`departure_missing`). |
| D7 | LOW | START double start (NEVER-INTERRUPT) | `_music_start`: no per-room in-flight guard; `_open_intent` inserts the intent after `await _target_room` | Oji and Ezinne (co-owners) have edges within the play_media latency (~1-5 s). Ezinne's `_any_playing` runs while Oji's `play_media` is in flight and reads idle, so a second `play_media` replaces Oji's pick. Both stamps sit on one player and Oji's `ours` is read after the second pick. Fix: a per-player in-flight set held across gates 6-7. |
| D8 | LOW | WAIT/COUNTED | `_open_intent` schedules the window timer before `await _music_start` | With `ARRIVAL_WINDOW_S` below `ARRIVAL_VERIFY_S` (20 s), the timer fires during verify and the intent is popped. Then `started` is written, but the wait has no timer and no intent, so there is never a terminal wait outcome. A rung-1 extreme; clamp the window to ≥ VERIFY or schedule the timer after the start. |
| D9 | LOW | SCENE | `arrival_scene_for`: the ambiguous and toggle checks run BEFORE the bedroom check | Two owners of a shared bathroom (e.g. kids, Jack-and-Jill) arrive together, and an entry in the shared BATHROOM ends both scenes `scene_skipped_ambiguous` before either reaches their own bedroom. The scene is lost, not misapplied. Move the bedroom test first. |
| D10 | LOW | START | `_target_room` picks the first bedroom whose player EXISTS, not one that is available | Live: `media_player.master_bedroom_sonos_2` reads `unavailable` now, so Oji/Ezinne get `skipped_no_player` instead of falling back to `master_bathroom_3`. Lost action only. |
| D11 | LOW (residual, measured none) | START phantom for BLE-only persons | gate 3b is clock-only | Jaya/Ziri have no GPS, so a ≥15 min BLE silence at home (yard, phone in a bag) then a `home` edge counts as an arrival. D0b: 12 of 12 of their arrivals were real (7 days), so not seen. Card, no fix. |

## Cleared (holds because)

- Flags: `counted is not True`, `source_stale is not False`, `in_boot_window is not False` all fail closed on a missing attribute (`_async_arrival`). The iPad phantom class is rejected by `source_stale` (D0b addendum, 29 of 29).
- `ARRIVAL_MIN_AWAY_S` 0 / backstop 0 / lookback 0 / window 0: documented kill-switch semantics (window 0 means no intent; lookback 0 fails closed). MIN_AWAY 0 lets every GPS flap through, by design: note it on the knob.
- Departure after a later arrival: check 0 reads the ring `edge_ts >= departure_ts` (flaps included) and fails closed when truncated, with no await between the checks and the pause call.
- Person with no own room, or with neither toggle on: `skipped_no_rooms`. Room with no player: `skipped_no_player` (but see D5 / D10).
- Guest threshold 2: house `guest` OR unidentified ≥ 2 (`cls="comfort"` reads trust via `view_for_class`); a None census fails open, counted and trip-wired as planned. A single phoneless daytime visitor starts music (accepted, D0b).
- Backstop window [t_a-480, t_a] with nobody placed: starts by operator rule B (accepted residual, named).
- Gate 3b DB DAO: no LIMIT, ASC order; the current edge is excluded by the strict `<`.
- Restart sweep: terminal sets include the lost outcomes, so each is written once; boot window covers the CM reload (presence reloads with it).
- No F5 read remains (`SIGNAL_PERSON_ARRIVING` connect and handler deleted). House state is seeded at setup (`domain_coordinators/music_following.py:189-191`).

## Forward trace (producers to actions)

The only `play_media` / `media_stop` / `media_pause` / `scene.turn_on` writers are music-following transfer (pre-existing,
per-person switch), the step 8 engine (opt-in `auto_music` / `auto_scene` per profile, master default ON) and
`automation._activate_scene_checked` (the room entry path). No HVAC, NM or `infer()` write from step 8. HA automations
on `person.*`: outside URA, not enumerated. No unapproved action was found, except the scope widenings in D3 / D4 / D5,
which reach rooms beyond the owner's.

## Checklist

| Invariant | Verdict |
|---|---|
| INV-V6-ARRIVAL-START | LEAK (D3, D4, D5 latent-config, D6, D7) |
| INV-V6-ARRIVAL-WAIT | LEAK, latent (D1, D2, D4, D8) |
| INV-V6-SCENE-ROOM | PASS (D9 loses a scene, never misapplies one) |
| INV-V6-DEPARTURE | LEAK, latent (D1 double-pause / misrecord, D4) |

## Verdict: FIX-REQUIRED

Must fix: D1, D2, D3, D4 (D1/D2 before B0 sets `ARRIVAL_OURS_ATTR`; D3/D4 are live on the start). Should fix in-cycle: D5, D6, D7, D8, D9, D10. Card: D11.
