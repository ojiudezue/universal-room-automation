# AUDIT: Frigate face-name latency at the 4 door cameras (read-only measurement)

Run Fri Nov 13 2026 18:57-19:02 CST (`date`), process count 602 at start. Read-only: HA GET/websocket read + recorder SELECT. HA token only from keychain into a variable, never printed. No Frigate login, no service calls, no API keys read. Docs read: `AUDIT_protect_face_name_interfaces_2026_11_13.md` (full), `AUDIT_crossing_vision_d0_2026_11_13.md` (grep for how events were fetched). HVAC/presence STATE_OF_PLAY not read (measurement only, no behavior change).

## Answer (lead)
- The 180 s settle is about 3x the measured strict p99 (<= 56 s). Strict (one-to-one attribution) latency from event start to first name: p50 2-8 s, p90 10-25 s, p99 17-50 s, max 55 s, over all four cameras. See table.
- A name DOES sometimes appear after 60 s, but only under ambiguous attribution (see Caveats): 12 of 77 matched named events have the first same-name face message 60-283 s after start, concentrated in back-to-back event bursts (front_door_aerial 2026-11-13 ~13:42, doorbell_lite ~04:xx). I cannot prove these belong to the earlier event, or to the next.
- Named share is low and coverage, not latency, is the limit: 18-30% of door person events carry a `sub_label` (agrees with `AUDIT_frigate_door_face_2026_11_13.md` 10-29%).
- Recommended `CROSSING_VISION_NAME_SETTLE_S`: **90 s** if the crossing consumer can tolerate misses of the burst tail, **120 s** to cover the lenient p90 on every camera except front_door_aerial; do not go below 60 s. Details below.

## Method (exactly what I used)
1. Events: HA websocket `frigate/events/get` (`instance_id=frigate-f2`, `cameras=[cam]`, `labels=[person]`, `after`=now-8d, `limit=5000`), read-only (`/Users/okosisi/ha-config/custom_components/frigate/ws_api.py:163-178`). The REST proxy has no events route (`/api/frigate/frigate-f2/api/events` -> 404; the integration's `views.py` only proxies snapshot/thumbnail/clips/notifications/vod/go2rtc), so the earlier D0 events must have come this way too. Result: doorbell_lite 137, garage_a 124, front_door_aerial 85, madrone_g6_entry 101 person events, start 2026-11-05 19:04 to 2026-11-13 14:11. `sub_label` non-null = Frigate's final debounced name. Events carry `start_time`/`end_time`, `data.sub_label_score`, but NO timestamp for when the name was set.
2. Name arrival time: recorder rows of `sensor.<cam>_last_recognized_face_2` (read via `ssh ha sqlite3 -readonly /config/home-assistant_v2.db`, tables `states` + `states_meta`, `last_updated_ts`). Producer: `FrigateRecognizedFaceSensor` (`custom_components/frigate/sensor.py:1051-1112`) subscribes to `<prefix>/tracked_object_update`, `type=="face"`, sets `_state = data["name"]` on EVERY per-attempt message and clears to "None" after 60 s of silence. So a state change to a name = the first face message with that name, but a repeat of the same name within 60 s writes no new row (only `last_reported_ts`). Row counts since 2026-11-06 ~09:03 CST: 509 rows over the 4 cameras (states: None 102, Unknown 136, Jaya 70, Oji 17, Ojini 5, Ezinne 2, Ziri 1, unavailable 176). Door sensors' recorder history starts 2026-11-06 (doorbell_lite 09:03, the other three 14:56 after an unavailable blip), so events before that were excluded from the join.
3. Join rule (strict, headline): each recorded name row (excluding None/unavailable) is assigned to the latest event on the same camera with `start_time <= row_ts`, kept only if `row_ts <= that event's end_time + 60 s`. Latency = row_ts - event.start_time for the first row whose name equals the event's `sub_label` (case-insensitive). Lenient (upper-bound view): first same-name row anywhere in [start-1, end+60], no one-event assignment.
4. Error bound: the face MQTT message carries the event `id`, but the HA sensor discards it, so the join is by time only. Row timestamps are HA receipt time (MQTT, local LAN, expected sub-second skew vs Frigate clock; not measured, I assumed NTP-sane clocks and saw latencies as low as 0.4 s and one -0.7 s on front_door_aerial, so skew is <= ~1 s). Strict assignment can mis-attribute when two events overlap or start within a minute of each other (a name row goes to the later event; the earlier event looks unmatched). It cannot create a latency below the true one for the same event unless the previous event had the same name, so the strict figures are biased FAST by dropping the burst/overlap cases (see "unmeasurable").
Scripts and raw pulls (not in repo): `.../scratchpad/w/{ws.py,an3.py,an5.py,fs.txt,events.json}`.

## Results per camera
Event totals are over the 8-day pull; the named share is within the recorder window (since 11-06). "Strict" = join rule 3. "Lenient" = join rule 3 lenient variant.

| camera | person events | named (sub_label) | named share | strict n matched | strict p50 | p90 | p99 | max | lenient p50 / p90 / p99 / max (n) |
|---|---|---|---|---|---|---|---|---|---|
| doorbell_lite | 137 (129 in window) | 29 (26 in window) | 20% | 19 | 6.5 s | 16.5 s | 50.1 s | 55.5 s | 8.6 / 52.7 / 87.1 / 90.7 (22) |
| garage_a | 124 (116) | 35 | 30% | 24 | 5.4 s | 13.0 s | 18.8 s | 20.4 s | 6.6 / 16.3 / 28.4 / 28.6 (27) |
| front_door_aerial | 85 (79) | 15 (14) | 18% | 7 | 8.4 s | 24.9 s | 26.5 s | 26.7 s | 16.1 / 171.7 / 199.0 / 200.6 (12) |
| madrone_g6_entry | 101 (96) | 21 (20) | 21% | 11 | 2.3 s | 10.7 s | 16.7 s | 17.3 s | 3.8 / 26.6 / 120.7 / 136.4 (16) |
| all four | 447 | 100 | ~22% | 61 | ~5 s | ~17 s | ~50 s | 55.5 s | 7.6 / 31.1 / 190.1 / 200.6 (77) |

Small-n warning: front_door_aerial strict n=7, madrone strict n=11; percentiles above p90 there are essentially the max.

Unnamed events with a face message at all (a name or `Unknown` row inside the event window): 1, 2, 1, 2 for the four cameras (strict join). So a door event is almost never "faced but unnamed"; it is mostly "no face message". (The 136 `Unknown` rows are mostly not inside door events; this was not broken down.)

### What was NOT measurable (named events with no row of their own)
Of 100 named events, 61 yield a strict latency. The other 39 split roughly (an4 categories) into: (B) 11 where the same name was already latched by a prior event within 60 s (garage_a 8, doorbell 1, fda 1, g6 1; true latency unknown but small, name pre-existed); (C) 6 where the only same-name row is more than 60 s after the event end (doorbell 124/99/97 s after start, g6 152-210 s, fda 109-117 s); the rest unassignable under the strict rule because a neighboring event claimed the row. Dropping B and some of the overlap cases biases the strict table fast; the lenient columns show what including them does.

## Does a name ever land after 60 s?
Evidence says yes, with attribution unproven:
- doorbell_lite 2026-11-10 (epoch 1794418250 window): two Jaya-named events (starts +39 s and +64 s) ended by +74 s; the first and only Jaya row appears at +163 s (99 s and 124 s after those starts). No other event named Jaya in between. This is the cleanest long-tail case I found; either Frigate's face worker was lagging ~100 s, or the HA sensor missed the earlier messages. The recorder row has `last_reported` +46 s later (repeat refresh), consistent with real messages continuing after.
- front_door_aerial 2026-11-13 ~13:44: seven overlapping Jaya events (1-6 min long) and the first Jaya row 200 s after the first of them; with that much overlap the row cannot be tied to one event.
- madrone_g6_entry 2026-11-13: Jaya rows at +136/+145/+152 s after two Jaya events 188 s and 43 s long.
Falsifier I could not run: the face message's `id` (object id) vs event id. A URA-side or MQTT capture of `tracked_object_update` with `id` and arrival time would settle it (the audit's recommended probe). The HA sensor does not retain the id, so the recorder cannot.

## What the settle should be
- Producer for the number: URA reads names from the same `tracked_object_update` face messages (`camera_census.py:5249-5540`, per the interfaces audit), so a settle wait must be keyed to when a face message for the crossing's event can still arrive, not to Frigate's sub_label on the event.
- Strict p99 = 50 s (doorbell) / max 55.5 s over 61 events. Lenient p90 = 52.7 s doorbell, 171.7 s front_door_aerial (burst-contaminated).
- Proposal: 60 s covers every strict observation (max 55.5 s) but misses the 99 s and 124 s doorbell cases and the 136-152 s g6 cases above. 120 s would catch the 99 s case but not the 124 s one or the g6/front_door_aerial tail, so no value under ~210 s captures the whole ambiguous tail, and that tail's attribution is unproven. **Default 90 s** (strict p99 50-56 s plus ~60% margin; same order as the Protect 40-80 s experience). Accept missing the rare 100-280 s burst tail and let late names back-fill through the existing 300 s `FACE_MATCH_ENTRY_WINDOW_AFTER_S` path (`const.py:3387-3390`, as cited in the interfaces audit) instead of lengthening the vision wait. 120 s is the alternative if the card prefers fewer tail misses. There is no measured case for 180 s as a default. Per Numbers-Get-Knobs it stays a knob; this report is the evidence for its entry.
- Garage_a is the best behaved camera (p99 18.8 s strict, 28.6 s lenient); front_door_aerial and doorbell_lite carry the tail. A per-camera value is not justified by n.

## Caveats
- Join is by time, not id (above). Burst clustering (events seconds apart, same person, overlapping) is common at doorbell_lite, front_door_aerial, g6; those are exactly the cases where attribution fails.
- Sensor writes only on state change: same-name messages within 60 s are invisible, so the FIRST message of a burst is measured and later events in the burst are not. This makes strict results optimistic.
- Names counted are Frigate's: right name is not checked (Ojini ghost, wrong names at 0.9+ per the Frigate door-face audit); this is arrival time of a name, not accuracy. 5 `Ojini` and 1 `Ziri` rows exist (not verified as errors).
- The sensor only publishes when Frigate publishes a face attempt; whether Frigate delays attempts (queue) vs HA/MQTT delays is not separable from recorder data.
- 8-day window, one house, 100 named events; the windows differ per camera (sensor history starts 11-06).
- "Share that gets a name at all": `sub_label` non-null on the event. A name could be latched in the sensor with no event sub_label (4 rare cases), not counted as named.
- I did not check URA's own latch/attach timing (`camera_census.py` latch `ts`): `person_entry_exit_events` has only `timestamp, person_id, event_type, direction, egress_camera, confidence, peak_person_count` (schema read via ssh), no face timing, and no URA table stores per-message face times.
- Not queried: Frigate/MQTT broker directly (out of scope).

## Reproduce
`ws.py` (HA websocket `frigate/events/get`), then `ssh ha "sqlite3 -readonly /config/home-assistant_v2.db"` selecting `states.state,last_updated_ts,last_reported_ts` for the four `sensor.*_last_recognized_face_2` entity_ids; scripts `an3.py` (strict) / `an5.py` (lenient) / `an4.py` (categories) in the session scratchpad.
