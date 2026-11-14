# Crossing vision shadow: Review B (signal chain, payload shape, lifecycle)

Branch `feature/crossing-vision-shadow` HEAD 18e3ba59. Base = merge-base with develop `6e03ec09` (verified, three-dot diff). Read-only review; no suite run, no mutation (Review C owns that).

Reading done first: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `docs/architecture/SENSOR_FLEET_CLASSES.md` were in scope (census/egress input), but this pass only touches the egress bus payload and does not assert anything about sensor classes.

## 1. `peak_person_count` on `ura_person_egress_event`

Producer: `transit_validator.py:2222-2235` samples once, before the bus fire at :2238, into the local `peak`. The same local goes to the bus (:2262) and to `log_entry_exit_event(peak_person_count=peak)` (:2355). There is no `await` between the new sample site and the old DB-write site (checked :2226-2345), so the sampled value is the same one develop wrote to the row. Ambiguous crossings: develop sampled nothing and wrote no row; the branch samples nothing and sends `None`. A sampler exception is still caught and falls back to `None`, so the row is never lost.

Listeners on develop, every one compared:

| Listener | file:line | Reads | Effect of the new key |
|---|---|---|---|
| Entry sensor | sensor.py:4772 / 4789-4806 | `.get` of direction, person_id, timestamp, egress_camera | none |
| Exit sensor | sensor.py:4903 / 4934-4940 | same | none |
| Last-entry sensor | sensor.py:5013 / 5018-5026 | same | none |
| Last-exit sensor | sensor.py:5063 / 5131-5139 | same | none |
| Perimeter alert | perimeter_alert.py:1006 → `_note_egress_identity` :4939-4956 | person_id, identity_confidence, egress_camera, timestamp, identity_synthetic_corroborated; stores a tuple, not the dict | none |
| Person sighting | person_sighting.py:151 / 453-484 | named `.get` only | none |
| Crossing vision (new) | crossing_vision.py:324 / 505-548 | `peak_person_count` via `_as_nonneg_int` | the intended consumer |

No listener iterates the payload, passes it through with `**`, or stores the dict. **Result: PASS.** The change only adds a key. Every listener behaves as before, and the bus value equals the DB value.

## 2. Async lifecycle

| # | SEV | Site | Finding |
|---|---|---|---|
| B1 | MEDIUM (outside URA; fix by documenting) | perimeter_enrichment.py:380 `asyncio.wait_for(..., 90)`; crossing_vision.py:360-367 teardown cancel | When the wait times out, or teardown cancels after its 5 s gather, the `CancelledError` goes into llmvision's handler. In llmvision `media_handlers.py:662-843` the temp clip (`NamedTemporaryFile(delete=False)`) is removed only on the normal path, at :840-845. That removal is not in a `finally`, and the handler never kills the ffmpeg subprocess (:701/735) on cancel. A cancel during fetch or ffmpeg therefore leaks one temp `.mp4` and leaves ffmpeg running until its pipe closes. How likely: a timeout is rare (D0b p99 17.8 s against a 90 s bound). The teardown cancel happens on every unload or reload that lands during a call; at about 14 calls a day of under 20 s each, that is low. Also, the comment in const.py ("wait_for cancels llmvision's handler in place") states the cancel but not the leak. Ask: note the leak in the const comment / IDENTITY manual and card an upstream llmvision fix (a `try/finally` around the temp file plus `process.kill()`). Not a ship blocker for a shadow producer. |
| B2 | LOW | crossing_vision.py:375 `hass.async_create_task` | The task is tracked by hass. On HA stop (no entry unload), core waits for tracked tasks, so a call in flight can hold up shutdown by up to 90 s. Use `hass.async_create_background_task(coro, name=...)` for `_run`; the row writes can stay as they are. |
| B3 | LOW | crossing_vision.py:323-337 `async_setup` | If `register_frigate_consumer` or `async_track_time_interval` raises after the bus listener was appended, `async_setup_crossing_vision` (:933-938) logs the error, but `cv` is never stored and its `_unsubs` are never called. The bus listener then leaks for the life of the process. Fix: on exception, `await cv.async_teardown()` before logging. |
| B4 | LOW | crossing_vision.py:577 | `self._calls_today + self._pending()` counts a `calling` request twice: `_calls_today` is incremented at :716 while the status is already `calling`. The cap trips up to MAX_CONCURRENT (2) calls early. This errs on the safe side, so it costs nothing, but the counter does not match `calls`. Fix: count only `status == "waiting"` in this sum. |
| — | holds | crossing_vision.py:339-368 | Teardown sets the latch first (`_torn_down`), unsubscribes the bus, ingress consumer and trip-wire interval, cancels every per-request `async_call_later` (:349-355), clears `_waiting_by_event`, then gathers for at most 5 s and cancels whatever remains. `_record` stops spawning row writes once torn down (:812), and `_spawn` closes the coroutine (:371-373). |
| — | holds | crossing_vision.py:654-665, 597-605 | No double fire: `_fire_request` cancels the timer, pops the waiter, and acts only on `waiting` → `calling`. The `end` callback and the timer race safely. `finally: status = "done"` (:758-759) always releases the concurrency slot, including on cancel. |
| — | holds | crossing_vision.py:705-715 | INV-OFF is read again at call time. A kill flag set between the gate and the call returns `None`, and the counters are rolled back (:732-736). |
| — | holds | crossing_vision.py:932 | Setup tears down any earlier instance first, so a partial reload cannot leave two producers. Unload tears down before the Frigate ingress (__init__.py:5908-5913). |
| — | holds | __init__.py:7423, 7734 | `crossing_vision_daily_calls` is in both `_NO_LIVE_ATTR_KEYS` and `OPTIONS_RELOAD_SUPPRESS_KEYS`, so the Number's options write-back (number.py `async_set_native_value`) does not reload the CM. |
| — | holds | switch.py `CrossingVisionShadowSwitch.async_added_to_hass` | Restore turns the switch on only when the last state was exactly `"on"`, which satisfies Bug Class #52. The flag lives in hass.data, so it survives an integration reload. |
| — | accepted by plan (F7) | crossing_vision.py:273-276 | The daily cap is counted in RAM, so each restart can allow one more full cap that day. This is documented in const and in the Number docstring. |
| — | holds | crossing_vision.py:836-838 | The trip-wire tick is `@callback`, runs through the tracked `_spawn`, and its interval unsub is in `_unsubs`. `fire_stuck_signal` adds its own once-per-day dedup. |

## 3. Credentials

There is no key, token or Frigate credential anywhere in `crossing_vision.py` or the new code in `perimeter_enrichment.py` (grep came back empty). The clip reference is the HA-relative `/api/frigate/<instance>/notifications/<id>/clip.mp4` (crossing_vision.py:685), or a bare `event_id`, from which llmvision builds the same `/api/frigate/notifications/...` path (llmvision media_handlers.py:934). llmvision signs `/api` paths with `async_sign_path` and a 5-minute expiry (media_handlers.py:630-636), then fetches the clip through HA's Frigate proxy. Both the event id and the instance id must pass `_sanitize_snapshot_token` before they go into the path (:674, :683), so a crafted id cannot inject a path. With two or more Frigate entries and no resolved instance, the reference is `no_clip_url` and no request is made (:686-692). **PASS.**

## Summary

| Severity | Found | Must fix |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 1 (B1, upstream leak on cancel) | document + upstream card |
| LOW | 3 (B2, B3, B4) | recommended in-cycle (each 1-5 LoC) |

Bug classes: B1 resource leak on cancellation (upstream); B2 untracked/blocking task at shutdown; B3 setup/unload symmetry; B4 #63 coincidental-equality-style double count.

**Verdict: SHIP.** No CRITICAL or HIGH findings. The payload change only adds a key and is safe for every listener on develop. Fix B2-B4 in the fix-up pass, and record B1 (doc note and llmvision upstream card).
