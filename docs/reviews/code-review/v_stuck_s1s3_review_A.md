# Review A: stuck-sensor truth S3a / S3b / S1 (correctness, edge cases, config boundaries)

Branch `feature/stuck-sensor-s1-s3`, diff `c67b8a78...HEAD` (4 commits). Read-only pass, no pytest (framing C owns that).
Presence state of play, SENSOR_FLEET_CLASSES and HVAC §9.3 were part of the brief. This pass checked the diff against the code and did not re-read those docs in depth.

## Verdict: SHIP (no CRITICAL, HIGH or MEDIUM findings; two LOWs and one operator note)

## Findings

| # | Sev | Site | Finding / failing input |
|---|-----|------|-------------------------|
| A-1 | LOW | coordinator.py:2508-2514 | An off followed by unavailable is one gap, but the overwrite rule treats it as two. Repro (motion-class ZV): off at t0, unavailable at t0+8 s, on at t0+16 s. `_p22_off_since` is overwritten to t0+8, so the gap reads 8 s < 10 and the run is kept, even though nothing was `on` for 16 s. If the input keeps flipping between off and unavailable, the run never pops. The failure mode is over-exclusion of a sensor that is already misbehaving, which is the safe direction, so this is LOW. Fix: overwrite only when the previous tick read `on`, i.e. when the not-on stretch is new. |
| A-2 | LOW | coordinator.py:2414-2439 | `derive_capability`, the `{**data, **options}` merge and `resolve_sensor_family` (cached) run for every input on every tick. That is cheap, but each lookup is O(rooms × inputs) per tick and could be cached per entry. Perf only. |
| A-3 | NOTE | _nm_cycle_a.py:85-126 | Live, the integration entry has `chatter_mode=act` and the CM entry has no value, so this deploy moves every room from shadow to ACT. This is the intended fix (plan §S3a), but chatter quarantine will act for the first time. Put it in front of the operator at the checkpoint. |

## Cleared

- **S1 boundaries.** Both branches use `>= tol` (lines 2493, 2501, 2513), so an off of 9 s keeps the run, 10 s pops or restarts it, and 11 s pops or restarts it. The two branches agree, and this matches the knob doc ("shorter than this does not end the run").
- **Sub-tick offs.** The bound is `on.lc − last_on_tick`. Because the event-driven refresh has a 2 s rate limit with a trailing refresh (coordinator.py:1647-1663), an off is almost always seen. A missed off is bounded by about 2 s and below 10, so the run is kept. The only case that restarts the run is an `on` edge that arrives 10 s or more after the last tick with an unseen off between them. That is the conservative behaviour the plan states (§S1 lines 158-160).
- **Unavailable vs off.** Both go through the not-on branch. A missing state keeps the tick of first sight (`setdefault`-equivalent via `.get(sensor, now)`), which is correct because a missing state has no `last_changed`.
- **Restart.** `_p22_*` are RAM-only. With a restored run and an `on` input, `off_since` and `prev_lc` are None, so the run is kept, as on develop. The new-run stamp at `on.last_changed` is stated in plan line 152. After a room reload, a motion-class input that has really been on for more than 4 h is therefore excluded at boot-settle instead of 4 h later. That is the truthful reading and the plan states it.
- **Tolerance 0 path.** Byte-identical to develop (lines 2465-2481). The only change is a dedup (`seen`), which is idempotent.
- **Still-holder exemption.** Radar families, the mmwave/bed/camera/BLE kinds and an override to a still-holder kind all get 0. An override to motion on a radar device also gets 0, because the radar family is not in `P22_MOTION_CLASS_FAMILIES`. An unknown family gets 0, and so does any exception. The gate uses the registry family via `resolve_sensor_family`, with no name test.
- **S3b.** `FAMILY_BY_MODEL_TOKEN` holds only `ms600`. In the live `core.device_registry`, the only models whose first token changes under the new `[\s\-_]` split are `ms600-un` ×3, which are the intended target. `msl430-un`, `mss105-un`, `mss115-us` and `mss315-us` tokenise to keys that are not in the map, so they stay unknown. The golden fixture agrees.
- **S3a precedence.** The order is a valid integration value, then a valid CM value, then the default. Invalid strings are skipped. An exception returns the default and is not cached. `select.current_option` uses the same resolver, so the select and the rooms cannot disagree.
- **Cache invalidation.** The cache is flushed on a select write (select.py:1046), at the top of the integration update listener before any subset check (`__init__.py:8927`), on a CM listener flush (`__init__.py:8825`, which calls `invalidate_knob_cache()` with no argument and therefore clears the chatter cache), and at CM setup (`__init__.py:5097`). The new no-reload key is correct: the room resolver is the only room-side reader (grep of `CONF_CHATTER_MODE` across the package), and it re-reads after each flush.
- **`_sensor_on_since` consumers.** The readers are coordinator.py:2408, 2617, 2679, 3927 and sensor.py:2530, 2601. Semantics are unchanged: the dict still holds the run start, and on the motion-class path runs start up to one poll earlier, as stated. No trust consumer changes beyond what the plan states.
