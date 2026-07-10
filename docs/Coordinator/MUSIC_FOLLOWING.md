# Music Following Coordinator — Design Doc

**Owner:** Music Following Coordinator (`domain_coordinators/music_following.py`) wrapping the standalone `MusicFollowing` class (`music_following.py`).

**Priority:** 30 (lowest active coordinator).

**Architecture:** Event-driven. `evaluate()` returns `[]`. Transfers fire from `TransitionDetector` callbacks and dispatcher signals, not from the intent pipeline.

---

## Trigger surfaces

| Trigger | Path | Purpose |
|---|---|---|
| `TransitionDetector` listener | `music_following.py:147` → `_on_person_transition` | Primary transfer path. Only sees transitions that pass ping-pong suppression in `transitions.py:231`. |
| `SIGNAL_SAFETY_HAZARD` | `domain_coordinators/music_following.py:184` → `_handle_safety_hazard` | Stop all playback on critical hazard (gated by `CONF_MUSIC_ON_HAZARD_STOP`). |
| `SIGNAL_SECURITY_EVENT` | `domain_coordinators/music_following.py:199` → `_handle_security_event` | Stop all playback on critical security event (gated by `CONF_MUSIC_ON_SECURITY_STOP`). |
| `SIGNAL_PERSON_ARRIVING` | `domain_coordinators/music_following.py:190` → `_handle_person_arriving` | v5.10.0 D9: log at DEBUG only; the arrival-start feature was never implemented. |
| `SIGNAL_HOUSE_STATE_CHANGED` (v5.10.0 D2) | `domain_coordinators/music_following.py::_handle_house_state_changed` | Feeds the current house state into the sleep/night gate. |

## Transfer decision gates (in order)

Every gate lives inside `_on_person_transition` → `_execute_transfer`. Reading the sequence top-to-bottom describes exactly what happens on a transition. Order below is authoritative (v5.10.0 fix-up A-MED-1 — reconciled with `music_following.py`):

Gates 1-4 run in `_on_person_transition` BEFORE lock acquisition.

1. **Same-room short-circuit**. Records `same_room` (v5.10.0 D4).
2. **Enabled-person membership**. `_enabled_persons` is populated at setup from `CONF_TRACKED_PERSONS` and re-synced on the coordinator's setup / options-flow update (v5.10.0 fix-up FIX-5). Per-person MFPersonFollowSwitch prefs are the source of truth.
3. **Minimum confidence**. `MIN_CONFIDENCE` — instance-shadowed by the coordinator from `CONF_MF_MIN_CONFIDENCE`.
4. **BLE proximity threshold**. `_mf_high_confidence_distance` injected from `CONF_MF_HIGH_CONFIDENCE_DISTANCE`. Reads `person_coordinator.data[person_id]["closest_distance"]`.
5. **Concurrency lock acquisition** (v5.10.0 D6). Single `async with self._transfer_lock:` (no `.locked()` pre-check).

Gates 6-13 run inside `_execute_transfer` — under the lock.

6. **Stale-transition age check** (v5.10.0 D6, tz-aware normalization in v5.10.0 fix-up B-MED-1). If transition timestamp older than `CONF_MF_STALE_TRANSITION_SECONDS` → records `stale_transition`, returns.
7. **House-state gate** (v5.10.0 D2). If `HouseState.SLEEP` and `CONF_MF_SLEEP_SUPPRESS` is on → records `sleep_suppressed`, returns. If `HouseState.HOME_NIGHT`: `block_all` → returns; `dwell_only` → BEHAVES AS `block_all` and logs a one-shot WARNING today (no per-person bedroom surface yet — v5.10.0 fix-up FIX-3); `off` (default) → allow.
8. **Per-person + target cooldown**. `MUSIC_TRANSFER_COOLDOWN_SECONDS = 8`. Records `cooldown_blocked`.
9. **Player resolution** — `_get_room_player(from_room)` / `_get_room_player(to_room)`. Strategy chain: room config `room_media_player` → zone config `zone_player_entity` → HA Area lookup (multiroom-platform preference in v5.10.0 D7) → naming convention.
10. **Target availability pre-flight** (v5.10.0 D1). Target state must exist and not be `unavailable`/`unknown`; otherwise records `target_unavailable`, returns WITHOUT fading source.
11. **Source-room occupancy guard** (v5.10.0 D3; predicate redesigned in v5.10.0 fix-up FIX-4). Primary: another tracked person's `location == from_room` (via person_coordinator). Secondary (untracked-guest coverage): substrate `occupancy` kind active on `from_room` (motion / mmwave EXCLUDED — residual-prone). Records `source_has_others`.
12. **Source-playing check**. Source must be `STATE_PLAYING`.
13. **Winner rule**. Target not already playing. Records `active_playback_blocked`.
14. **Transfer method dispatch** — MASS `transfer_queue` → same-platform `join` → generic `play_media`.
15. **Post-transfer verification**. Skipped on same-platform `join` path in v5.10.0 D12.
16. **Group cleanup** — schedule delayed `unjoin` of source and volume restore.

## Cross-tier signal reads (REUSED)

- `person_coordinator.data[person_id]["closest_distance"]` — BLE proximity read at `music_following.py:263`.
- `OccupancySubstrate` — v5.10.0 D3 room-occupancy read (non-blocking property).
- `SIGNAL_HOUSE_STATE_CHANGED` payload `HouseStateChange` (`signals.py:173`) — sleep/night gate.

## Tunables (config-flow FIELDS, not entities)

Per CLAUDE.md "Number Fields = Form Fields":

| CONF_ | Default | Role |
|---|---|---|
| `CONF_MF_COOLDOWN_SECONDS` | 8 | Per-person same-target cooldown |
| `CONF_MF_PING_PONG_WINDOW` | 60 | Return-trip suppression in `transitions.py` |
| `CONF_MF_VERIFY_DELAY` | 2 | Post-transfer verification pause |
| `CONF_MF_UNJOIN_DELAY` | 5 | Source release delay after transfer |
| `CONF_MF_POSITION_OFFSET` | 3 | Cross-platform seek offset |
| `CONF_MF_MIN_CONFIDENCE` | 0.6 | Minimum transition confidence |
| `CONF_MF_HIGH_CONFIDENCE_DISTANCE` | 8.0 ft | BLE proximity ceiling |
| `CONF_MF_SLEEP_SUPPRESS` (v5.10.0) | True | Suppress transfers in SLEEP |
| `CONF_MF_NIGHT_SUPPRESS_MODE` (v5.10.0) | `off` (default changed in v5.10.0 fix-up FIX-3 — dwell_only had no per-person bedroom surface and silently suppressed every HOME_NIGHT transition) | HOME_NIGHT policy |
| room-level `room_media_volume_scale` (v5.10.0) | 1.0 | Per-room cross-platform loudness scale |

## Stat glossary

Consumed by `MusicFollowingHealthSensor`, `MusicFollowingTransfersTodaySensor`, `MusicFollowingLastTransferSensor`, and the `AnomalyDetector`.

| Stat | Meaning | Wired by |
|---|---|---|
| `success` | Verified transfer | `_execute_transfer` post-verify |
| `failed` | Transfer method returned False | `_execute_transfer` |
| `unverified` | Method OK, target not playing | `_execute_transfer` |
| `cooldown_blocked` | Per-person same-target cooldown (`MUSIC_TRANSFER_COOLDOWN_SECONDS`) hit. NOTE (v5.10.0 fix-up A-MED-2): lock serialization is no longer counted here — v5.10.0 D6 removed the `.locked()` pre-check that used to emit this stat on contention. Real lock-serialized transitions now flow through and are decided by the stale-transition guard. | `_execute_transfer` |
| `active_playback_blocked` | Winner rule (target already playing) | `_execute_transfer` |
| `low_confidence` | Below `MIN_CONFIDENCE` or BLE too far | `_on_person_transition` |
| `ping_pong_suppressed` | v5.10.0 D4: wired from `transitions.py:231` back into MF | `TransitionDetector._is_ping_pong` |
| `same_room` (v5.10.0 D4) | Same-room transition short-circuit | `_on_person_transition` |
| `target_unavailable` (v5.10.0 D1) | Target speaker offline | `_execute_transfer` pre-flight |
| `sleep_suppressed` (v5.10.0 D2) | House state SLEEP block | `_execute_transfer` |
| `night_suppressed` (v5.10.0 D2) | HOME_NIGHT policy block | `_execute_transfer` |
| `source_has_others` (v5.10.0 D3) | Guest-in-source-room guard | `_execute_transfer` |
| `stale_transition` (v5.10.0 D6) | Transition age > threshold | `_on_person_transition` inside lock |

Skip visibility: `MusicFollowingLastTransferSensor` also carries `last_skip_reason`, `last_skip_from_room`, `last_skip_to_room`, `last_skip_time` (v5.10.0 D8).

## Cross-coordinator invariants (Tier 2-DB reviews)

1. **Silent-actuator invariant:** MF SHALL NOT modify source volume, call `unjoin`, or call `play_media`/`join`/`transfer_queue` if the resulting user experience is "music disappears from source without appearing at target."
2. **Sleep/guest invariant** (v5.10.0): During `HouseState.SLEEP` (with `CONF_MF_SLEEP_SUPPRESS` on) or when the source room has another identified/unidentified occupant besides the transitioning person, MF SHALL NOT call any actuation service on any media_player.

## Ping-pong location call-out

Ping-pong is enforced in `transitions.py:231`, BEFORE MF sees the transition. The MF-side `ping_pong_suppressed` counter is fed back from that call site in v5.10.0 D4 (previously vestigial — Bug Class #53 subclass).

## Device layout

All MF diagnostic sensors + the CM master enable-switch attach to the coordinator device via `_music_following_device_info()` (`sensor.py:5873`, `switch.py:191`). Per-person MF Switch entities (v5.10.0 D5) attach to the MF coordinator device (with an in-code TODO noting a future migration to per-person devices when they exist).

### Known limitation (v5.10.0 fix-up C-M1): person add/remove requires manual CM reload

`_build_per_person_mf_switches` (`switch.py:_build_per_person_mf_switches`) is called once per CM entry setup. When the operator adds or removes a tracked person from the INTEGRATION entry's person-tracking step, the CM entry does NOT auto-reload — the per-person switches will not appear/disappear until the operator manually reloads the Coordinator Manager entry from the HA UI (or the next HA restart). The MusicFollowing singleton is reconciled anyway via `sync_enabled_persons` at MF-coordinator setup (v5.10.0 fix-up FIX-5), so behavior is correct even without the switch; only the UI surface is out of date.

Automating a CM-entry reload on integration-entry option changes was considered and dropped: cross-entry reload orchestration risks introducing new race conditions with the CM's own options-flow, and the operator-visible payoff is small (a rare configuration change).

## Egress diagnostic (D0 note)

If a room has an active `SIGNAL_EGRESS_STATE` hold (windows open), MF still transfers normally today. Not a bug per se, but noted here for future reviewers.
