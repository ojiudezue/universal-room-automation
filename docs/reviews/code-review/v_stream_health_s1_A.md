# Review A (local correctness) + G (goal fidelity): camera input stream health S1

Branch `feature/camera-input-stream-health-s1` @ b9af53dc. Diff base `git merge-base develop HEAD` = 1d6ce7a8 (verified,
three-dot). Plan `docs/planning/PLANNING_camera_input_stream_health.md` S1. Read completely before review:
`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md` (no contradiction with code found; the doc's S1
paragraph at line 7 matches the code). Targeted run: `quality/tests/test_camera_stream_health.py` 23 passed.

## Verdict: SHIP (no CRITICAL / HIGH / MEDIUM). Three LOWs, fixable in-cycle (each < 10 LoC).

## A: local correctness

| Area | Result | Evidence |
|---|---|---|
| Tick ordering | holds | `reset_tick` `coordinator.py:3499` → P22 / STUCK-1 → chatter `:3733` → stream tick `:3746` → fusion legs `:3760-3773`. Every fusion read goes through `_fusion_filter_active` (`:2583`); the D2 witness (`:2314`) and `:5907` run later in the same tick, so they see the promotion. |
| Release after camera returns / kill flip | holds | `reset_tick` clears ALL clients (`sensor_exclusion.py:33,67`); the stream client re-promotes only `dead` (`coordinator.py` `_apply_camera_stream_health_tick`); `dead` is empty when the camera reads anything but `unavailable` or when `CAMERA_INPUT_STREAM_HEALTH_ENABLED` is False (`camera_stream_health.py` `evaluate`). An input can never stay excluded past the next tick. |
| Grace 119 / 120 / 121 s | holds | `(now - since) >= grace_s`: 119 counts, 120 and 121 excluded. `since` = first room tick observing `unavailable` (setdefault), so real release = outage + ≤ 30 s poll + 120 s + ≤ 30 s + room timeout. Matches the doc's stated semantics. |
| Restart blips | holds | < 120 s `unavailable` then any live state pops the stamp. Stamps are RAM; at boot a restored `unavailable` camera can exclude after 120 s, but its input is restored `unavailable` too, so no fusion change. |
| `unknown` / no state | holds (see LOW-1) | `continue` before stamp set or clear; input not dead that tick because `camera_state != unavailable`. |
| Resolution cache | holds (see LOW-2) | rebuilt when the ordered, de-duplicated input tuple changes; nulled by `EVENT_ENTITY_REGISTRY_UPDATED`. Listener added after `super().async_config_entry_first_refresh()`, unsub on `_unsub_state_listeners`, cleared at re-setup (`coordinator.py:1525`) and unload (`__init__.py:6096`). Stamps of cameras no longer watched are pruned. |
| `own_camera_entity_for_input` | holds | `get_entries_for_device_id(device_id)` default `include_disabled_entities=False` (HA `entity_registry.py:744`), plus an explicit `disabled_by is None` filter; `camera.*` prefix; exactly one → resolved, zero → `no_camera`, ≥ 2 (NVR / doorbell package camera) → `multi_camera`; registry errors fail open. Static, no WARN per call. |
| NM paging | holds | HIGH once per episode (`_paged_episode`) and once per (room, input) per local day (`now` = `dt_util.now()`, local, `coordinator.py:3413`); across midnight a still-paged episode does not re-page (`test_nm_one_page_per_episode_across_midnight`). LOW recovered only for a paged episode, also on kill flip (documented). `NM_AFTER_S = 0` disables pages only. |
| Getter contract | holds | `is_dead`: None if cache empty, input unknown, or unresolved; True iff in `_dead_now`; False otherwise (always False with the kill switch off). |
| Byte-identity unresolved / killed | holds | no `promote` call in either case; only additions are registry/state reads, one WARNING, two unrecorded display attributes. |

### LOW-1: a `since` stamp survives a no-opinion stretch of any length
`camera_stream_health.py` `evaluate`, the `value is None or value == _UNKNOWN: continue` branch. Repro: camera reads
`unavailable` at t0 (stamped), then `unknown` (or leaves the state machine) for hours, then `unavailable` again: the
input is excluded on that first tick with no grace, because `since` = t0. Harm small (the camera is in fact dead
again), but INV-STREAM says "continuously". Fix: clear the stamp after a no-opinion stretch longer than the grace, or
stamp a `last_seen_unavailable` and require it within one grace. Class: stale data source (#7).

### LOW-2: getter reads None while the exclusion still holds
`invalidate()` sets `_resolution = None`, so `is_dead` returns None from a registry event until the next room tick,
while the exclusion set still carries this tick's `camera_stream_dead` promotion. HA fires
`entity_registry_updated` for every entity in the house, so this window opens often. No S1 reader is affected (fusion
reads the exclusion set), but S2 readers would see "no opinion" for an input the room is excluding. Fix: keep the old
resolution and set a dirty flag that `_ensure_resolution` honours. Class: #63-adjacent (two views of one fact
disagreeing for a window). Fix before S2 lands at the latest.

### LOW-3: recovered NM for an input removed from the room mid-episode
`evaluate`'s recover loop walks `_paged_episode`; an input removed from config while paged leaves `dead`, so a
"counts again" LOW fires for an input that no longer exists. Cosmetic. Fix: drop `_paged_episode` entries not in
`ordered` silently.

### Not findings (checked)
- Fix #10 all-unavailable grace and the P22 stuck tally still read raw state (`coordinator.py:3439-3473`); a dead
  panel `on` keeps its `_sensor_on_since`, so P22 may still fire its own stuck NM after 4 h. Pre-existing, no fusion
  effect (the input is already excluded); a second page per long outage at most.
- The brand platform list in `own_camera_entity_for_input` only feeds the silence WARNING; `bool(cameras)` covers
  any other brand.

## G: goal fidelity

| Question | Answer |
|---|---|
| Agnostic (no camera name, app or NVR brand keyed)? | Yes. The rule keys on the input's own device holding exactly one enabled `camera.*` entity reading `unavailable`. No entity name, no KS app, no Frigate-only path. Answers the PTZ "not agnostic enough" criticism and drift row 10. |
| Delivers the objective (a frozen `on` from a dead camera stops holding rooms)? | Yes at room tier: the Up Hallway 14 h frozen `on` would release about 2-3 min + room timeout after the camera drops, not 4 h. Zone, fan recheck and census are S2 (stated, not silently deferred; card CAMERA-STREAM-DEAD-ZONE-AND-CENSUS-1). |
| Hard constraint "away must be fast acting"? | Not broken: S1 only removes evidence, so rooms release sooner; AWAY can only get faster. |
| Operator: "check on ks app health and restart it" | The restart / watchdog is homelab (plan §8; F2-PANEL-FFMPEG-CRASHLOOP-1 is on the board). URA reads stream health instead of `foreground_app`, which the measurement showed would have given an 18 h false "unhealthy". This is a goal-serving substitution, recorded in the plan, not drift. |
| Operator: "enabling new features like motion etc will be compromised" | Partly open by design: a KS-device input (e.g. a future `binary_sensor.<panel>_motion` on the ESPHome device) has no camera entity on its device, so it resolves `no_camera` and is NOT watched. The plan parks the `foreground_app` leg with exactly that revival trigger (§8). Acceptable, but the operator should know that adding KS motion to a room is the trigger. |
| Did a risk reduction change WHAT is delivered? | No. Exclude-only (no hold-on-dead) is the operator default. |

## Summary

| Severity | Found | Must fix |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 0 | 0 |
| LOW | 3 | fix in-cycle recommended (LOW-2 before S2) |

Bug classes: stale data source #7 (LOW-1), #63-adjacent view split (LOW-2), cosmetic (LOW-3). No new class for
`QUALITY_CONTEXT.md`.
