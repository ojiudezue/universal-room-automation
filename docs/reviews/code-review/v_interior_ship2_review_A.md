# Interior vision ship 2 — Review A (correctness + privacy + edge cases)

Branch `feature/interior-vision-ship2` @ 0bc751d8, diff `develop...HEAD`. Tier 2-DB, framing A. Read first, completely:
`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`; plan §9.D3 / §8.
Identity model: this ship consumes F4 (named interior face sightings) and F1/BLE placement, and produces an F4-unnamed
description; the reply is notification class (naming bar 0.75).

## Findings

| # | Sev | Class | Where | Finding |
|---|---|---|---|---|
| A-M1 | MEDIUM | Identity: consumer policy not applied (plan/ship-1 parity) | `person_sighting.py:1066-1072` (`_describe_target` face fallback) | The face fallback takes the newest fresh interior sighting of the slug with no `census_would_veto` filter and no confidence floor. Ship 1's named rule filters `not s.census_would_veto` (`person_sighting.py:1460-1461`), and the reply names the person (notification class, bar 0.75, manual §5.5(b)). Repro: Oji abroad (`person.oji_udezue` = not_home, BLE no room), Jaya's face labelled "Oji" on the Family Room camera (the 10-24 shape) → sighting emitted with `census_would_veto=True` → operator sends `describe oji` → reply "Oji Udezue was last seen in Family Room 1 min ago." plus a description of that room. Fix: add `and not s.census_would_veto` (and `s.confidence >= CONSUMER_CLASS_MIN_CONFIDENCE["notification"]`) to the loop. |
| A-L1 | LOW | Numbers get knobs / privacy | `person_sighting.py:893` | First names shorter than 3 chars are not scrubbed (`len(w) >= 3` inline literal). A resident "Al Smith": "Al is cooking" survives the scrub (slug and display name are still scrubbed). Name the threshold as a rung-1 const; consider scrubbing all first names and accepting the false positives. |
| A-L2 | LOW | Restart-reset budget | `interior_vision.py:327-328, 389-396` | `calls_today` / `cost_today` are RAM; each restart / CM reload resets them, so the daily call and cost caps are per process, not per day (crossing vision rehydrates its counter from DB rows, P3-D5). Cost exposure is small (0.0003/call) but the cap's stated meaning is wrong. Rehydrate from today's `interior_description` rows or document. |
| A-L3 | LOW | Staged file orphan on cancel | `interior_vision.py:486, 580-581` | If teardown cancels `_run` while `_write_stage` runs in the executor, `files` in `_run` is still `[]` (assignment happens after the await), the thread finishes writing, and nothing deletes the still until the next setup sweep. On a CM reload the new setup's sweep can race the still-running write and miss it; the file then lives until the next restart. Bounded, but it is a family frame on disk under the config dir (Samba-shared, in backups). Option: have `_stage_dewarped` record paths on `self` before the write and unstage them in teardown / sweep after the executor completes. |
| A-L4 | LOW | Kill switch after scheduling | `notification_manager.py:4812-4813`, `_send_reply` | The answer is sent through `_send_reply`, which does not re-check `_messaging_suppressed`; a messaging kill flipped during the 3-60 s call still delivers the description. Re-check the kill in the `_reply` closure. |
| A-L5 | LOW | Stage filename collision | `interior_vision.py:579` | Stamp = `now` to the ms; two concurrent dewarp calls finishing in the same ms share `iv_<stamp>_<i>.jpg`, and one call's unstage deletes the other's frames (or one room's frame goes out under another room's prompt if two 360 groups exist). Not reachable today (one 360 group, per-requester cooldown, default operator only). Add the group key or a uuid to the name. |
| A-L6 | LOW | Doc vs test | README draft / state-of-play line 22 | Claims the remap matches ffmpeg "within MAE < 1 grey level"; measured MAE is 1.05-1.24 (test bound 2.0). Correct the text. |
| A-L7 | LOW | Copy | `notification_manager.py:4797` | "Please wait a minute" is fixed text for the `INTERIOR_DESCRIBE_NM_COOLDOWN_S` knob; derive it from the knob. Also `deque(maxlen=50)` latency window (`interior_vision.py:337`) is an inline number. |

## Cleared (holds because ...)

- **NM parse ordering / swallowing:** branch at `notification_manager.py:4118` runs after echo rail 1 (`:4087`) and the messaging kill (`:4107`), before `RESPONSE_COMMANDS` / safe-word / diag. No `RESPONSE_COMMANDS` key starts with `describe ` (grep); the prefix needs the trailing space, so a bare `describe` still falls through to the table. Only `imessage` / `whatsapp`; pushover and companion untouched. The describe replies ("Not available.", "No camera in X.", descriptions) never start with `describe `, and they go through the echo-recorded send path, so no self-trigger loop.
- **Injection:** the target string never reaches the prompt. `_describe_target` resolves it to a URA room name or a tracked slug; the prompt's `{room}` is the matched room entry name (`interior_vision.py:109-115`). The raw target is only echoed back to the requester in the "I don't know ..." refusal.
- **Access:** `person_id is None` returns with no reply and no call (`:4771-4773`); `describe_access` returns (False, False) for a falsy requester; unknown mode falls back to operator; operator = `CONF_NM_SECURITY_ACK_PERSONS` else first NM person via the factored `_operator_person_entities` (security-ack behaviour unchanged: same list, same membership test). Denied → "Not available." with no presence call.
- **Cooldown:** check and stamp are separated only by sync code (`request_room_description` is sync), so two quick requests cannot both pass. Stamped on scheduled only (refusals are free; acceptable).
- **Caps before await:** `calls_today` / `cost_today` reserved in `_describe` (`interior_vision.py:451-452`) before the task is created; switch, kill, call cap, cost cap all re-read at call time; 0 on either cap = no call; describe exempt from the sampling reserve only.
- **Frigate still LIVE gate:** `_still_source_live` needs the still camera state real AND one of the Frigate device's own person sensors LIVE by `member_liveness` (stream view None, real state, not watchdog-discounted); fails closed when the group has no Frigate member.
- **Privacy flags:** `analyze_crossing_images` hard-codes `store_in_timeline` / `use_memory` False, `include_filename` False; `call_model` always passes `expose_images=False` on both routes. Plan D0(f) measured 0 files under `/media/llmvision/snapshots` with `expose_images` False (I could not read llmvision source here; relying on that measurement).
- **Name scrub:** whole word, case-insensitive, `_` / space variants of slug and display name, plus first and last names ≥ 3 chars; possessives work (`Oji's` → `a person's`, the `'` is a non-word boundary). Applied to every free-text field (what, where, context, mood, energy) before the record and the DB row are built.
- **Mood:** recorded on the record and memory row when the knob is on; reply carries it only when `reply_affect` = `include_affect and record_affect`, and `include_affect` is True only for `operator_affect` with an operator requester. Diagnostics never include affect.
- **BLE target:** placement needs `get_person_confidence >= CONSUMER_CLASS_MIN_CONFIDENCE["notification"]` (0.75) and an exact room match; face fallback window `INTERIOR_ROOM_FACE_FRESH_S` (300 s) — see A-M1 for the missing veto.
- **Dewarp lens by registry:** `_lens_entity` matches `platform == "unifiprotect"`, domain `sensor`, enabled, device in the group, `translation_key == "lens_type"` (or unique id suffix when no translation key); no entity-name test. Last real reading survives unavailable.
- **Remap correctness (independently verified):** regenerated ffmpeg 9 v360 references for the four fixture views plus an unseen compound view (30, -10, 75): fixtures byte-identical to fresh ffmpeg output; MAE 1.05-1.24, p99 6-8 inside the circle. Outside-circle pixels are black.
- **Dewarp failure fallback:** any exception in `_stage_dewarped` (fetch, decode, write) → counted `dewarp_failed`, raw still entity sent; `_write_stage` deletes partial files on a write error.
- **Staged files deleted:** `finally` in `_run` unstages on success, error and CancelledError (one cancel); undeletable → `interior_frames_left` HIGH; setup sweep deletes `iv_*` leftovers. Residual A-L3.
- **Memory row:** attrs carry text fields only, no frame, no path, no requester.
- **Knobs:** every behavioural number in the new code is a named const or Number, except A-L1 / A-L7.

## Verdict

**FIX-REQUIRED** — must fix A-M1 (one-line filter; add a test with a vetoed fresh face that must not place the person).
LOWs A-L1..A-L7 are cheap and should go in the same fix-up pass.

| Severity | Found |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 1 |
| LOW | 7 |
