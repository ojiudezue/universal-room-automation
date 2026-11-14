# AUDIT: crossing-vision fast stage (P2-D8) frame sources

Run 2026-11-14 01:11-01:55 CST by ura-prober. Read-only, not committed. HVAC / presence STATE_OF_PLAY docs not read (no HVAC or presence logic touched; this is a frame-source timing probe). Context: `.claude/worktrees/builder-cv-fast/docs/reviews/code-review/v_cv_fast_stage_AB.md` (best-snapshot image updates 3-22 s after the person edge, 9/41 within 1 s).

Method: GET only, through the HA Frigate proxy (Bearer token from keychain, never printed). Frigate 2 instance `frigate-f2`, entry `01KM239Z8ZQWQTN1D9CV5JRA7V`, integration version 5.15.6 (`~/ha-config/custom_components/frigate/manifest.json`). No Frigate login, no llmvision call, no service call. WebSocket `frigate/events/get` (300 door person events, 3 days) and `frigate/events/subscribe` (live `frigate/events` MQTT payloads, `ws_api.py:337-361`, `ws_proxy.py`). Downloaded frames and clips deleted.

## Answer first

1. **A frame at an arbitrary past timestamp is NOT available through the HA Frigate proxy.** There is no snapshot-at-time route. The only recording route returns an MP4 clip (`views.py:245-266`, `RecordingProxyView`: `/api/frigate/{instance}/recording/{camera}/start/{s}/end/{e}` maps to Frigate `api/{camera}/start/{s}/end/{e}/clip.mp4`). The full route list is `views.py:123-134`; none serves a frame. (Frigate itself has a recordings frame endpoint, but HA does not proxy it, and I did not call Frigate directly.)
2. **Recording flush lag is the blocker: a frame at time T is fetchable only about 13 s later (p50 12.9 s, p90 16.1 s, max 17.0 s, n = 44; G6 faster, p50 9 s).** Recipe (a) (E-1, E, E+2 from recordings) is therefore complete at about E+15 s, not at the `new` message.
3. **`new` itself arrives late**: p50 E+1.2 s but p90 E+8.4 s (proxy, below). So E-1 is already 2 s to 10 s in the past when URA sees `new`.
4. **Thumbnail and live frame are instant but weak**: thumbnail 0.05-0.55 s, 175 px crop; live frame 0.02-0.1 s p50, full res. `snapshot.jpg` (event) is also instant (0.08-0.23 s) and full-res, but has a bounding box burned in.
5. **Recommendation: no delay-and-fetch-past-frames. Use recipe (b'), fired at `new`: live frame at 0 s + live frame at about 2 s + live frame at about 4 s (all `camera.*` entity proxy, latency under 0.1 s each), with the best snapshot kept ONLY when its entity `last_changed` is >= E (the guard the review already specified), else dropped.** Reason: it completes at about `new`+4 s (versus E+15 s for recordings), costs no new infrastructure, and the person is by definition in view at `new` (a person event only becomes `new` once the tracker has the object). Recipe (a) only helps if a pre-event baseline is wanted, and it needs ffmpeg plus local files. See the recipes table.
6. **Gap, disclosed:** no person event occurred on a door camera during the 43-minute live window (01:11-01:55, night; only cars and indoor people). Live `new` measurements are from one doorbell_lite **car** event; the person-specific checks (is the `new`-time thumbnail the person, does `clip.mp4` exist at `new`+1 s for a fresh event) are UNMEASURED. The listener design is reusable for a daytime rerun.

## 1. Frame at an arbitrary timestamp from recordings

Route: `~/ha-config/custom_components/frigate/views.py:245-266` (shown above). Also available: event clip `notifications/{event_id}/clip.mp4` (`views.py:343-344`), thumbnail (`:339-340`, `:269-286`), snapshot (`:341-342`, `:224-242`).

**Readiness lag** (poll every 0.5-1 s a 1 s window `[T0-0.5, T0+0.5]` with T0 = now; success = HTTP 200 and body > 1 kB; time from T0 to first success; n = 44 = 11 per camera):

| Camera | n | p50 | p90 | range |
|---|---|---|---|---|
| doorbell_lite | 11 | 13.1 | 14.4 | 6.8-16.4 |
| garage_a | 11 | 13.8 | 16.5 | 9.8-17.0 |
| front_door_aerial | 11 | 12.9 | 14.0 | 4.7-16.1 |
| madrone_g6_entry | 11 | 9.1 | 12.6 | 7.1-16.6 |
| pooled | 44 | 12.9 | 16.1 | 4.7-17.0 |

(Two later single reads with a 2 s window landed at 10.0 / 3.9 / 5.5 / 8.8 s, inside the same range.) The 10 s Frigate segment plus flush explains the shape; I did not read Frigate's recording code, so the mechanism is inferred, the numbers are measured.

**Fetch latency** once ready: p50 about 0.9 s (0.65-1.15 s) for a 1-4 s window, 2-6 MB per clip. One 21.7 s outlier on an old-event fetch (cold read), 1 of 6.

**What the clip contains (verified against the on-screen date stamp, doorbell_lite and madrone_g6_entry; garage_a / front_door_aerial stamps not legible in my crop, so unverified there):** the clip is cut **exactly at the requested end** (last frame within the same second as the end) but **starts early at a keyframe**: doorbell_lite requested start 01:52:14.8, first frame stamped 01:52:13; G6 requested 01:52:25.2, first frame 01:52:21. Keyframe interval is about 5 s (ffprobe keyframes at 0 and about 5 s on doorbell_lite and garage_a clips). Consequences: (i) a clip has no absolute timestamps (`format start_time` 0), so the offset of the wanted frame from the clip start is unknown; (ii) to get the frame at T, request `[T-1, T]` and take the LAST frame (`ffmpeg -sseof`), which is end-aligned and exact to about 1 s; (iii) llmvision `video_analyzer` keeps only I-frames (`media_handlers.py` add_video ffmpeg tail `select=eq(pict_type,I)`), so a 3 s clip yields about one keyframe, which is not the requested frame. Exact-frame extraction needs URA's own ffmpeg (availability inside the HA container: unverified).

## 2. Event thumbnail

- **Not in the `new` payload** (`thumb_in_payload` false; keys list has no `thumbnail`). Payload fields incl. `snapshot` frame_time, `has_snapshot`, `has_clip` (`live.jsonl`, 1 car `new` and 4 indoor `new`).
- Via proxy `/api/frigate/frigate-f2/notifications/{id}/thumbnail.jpg`: **HTTP 200 at `new`+0 s, 0.55 s latency (first fetch), then 0.04-0.31 s**; 4.9-5.0 kB. Content changed once between +0 s and +2 s (md5 differs), then stable to +15 s.
- It is a **175x175 crop of the tracked object** (viewed: the car, tight crop). So it is the triggering object, but at 175 px it is a poor counting input (no scene, no companions). Triggering PERSON: **unmeasured** (car event only).
- `new` timing context, from the live feed: the car `new` arrived E+10.8 s (re-detect of a parked car; recv 01:49:20.9 vs start 01:49:10.1); indoor person `new` arrived E+0.4 to E+9 s.
- Retrospective proxy for person `new` delay (binary_sensor `*_person_occupancy_2` on-edge minus Frigate event `start_time`, events with no other event within 20 s before, 131 door events over 3 days): p10 0.4 s, **p50 0.9 s, p90 8.4 s**, within 1 s 51 %. doorbell_lite 0.9 / 4.6 (n 42), garage_a 1.2 / 11.3 (49), aerial 1.3 / 7.0 (15), G6 1.8 / 18.5 (25). This is a proxy (occupancy edge, not the MQTT `new` message); it agrees with the live feed.
- The final best-snapshot frame is far from E: `snapshot_frame_time - start_time` over 238 door events: p10 0.3 s, p50 5.9 s, p90 49.1 s (aerial p50 15.2 s). So the best snapshot is by design a later, better frame, which is why it is stale at `new`.

## 3. Live frame (camera entity proxy, `/api/camera_proxy/camera.*`)

Entities (registry, `core.entity_registry`): `camera.doorbell_lite`, `camera.garage_a_2`, `camera.front_door_aerial`, `camera.madrone_g6_entry` (uid `01KM239Z8ZQWQTN1D9CV5JRA7V:camera:<cam>`; only garage_a carries `_2`).

10 sequential GETs each: p50 0.08 / 0.055 / 0.03 / 0.02 s, p90 0.10 / 0.07 / 0.06 / 0.08 s, max 0.69 s (G6). Sizes 100-540 kB. Live at `new`: 0.61 s (first), 0.11 s, 0.09 s. Freshness of the frame (age of the pixel data) is unmeasured; the stamp shows only second resolution. Frames at +0, +2, +4 s differed in md5 (distinct frames).

## 4. Candidate recipes (E = Frigate event `start_time`; N = URA sees `new` at about E+1.2 s p50, E+8.4 s p90)

| Recipe | Complete at | Readiness | Frames | Verdict |
|---|---|---|---|---|
| (a) recordings at E-1, E, E+2 | max(E+2, N) + about 13 s lag + about 1 s fetch = **about E+16 s** (p90 about E+19 s, max about E+20 s) | p50 about E+16 s, p90 about E+19 s | exact, but needs URA ffmpeg + local files; E-1 usually empty-handed (person not yet detected; D0b found pos-0 frame empty in 53 %) | reject for the fast stage; keep as the B-stage source |
| (b) thumbnail + live + live+2 s | N + 2 s = about E+3.2 s (p90 about E+10.4 s) | p50 E+3.2 s | thumbnail 175 px crop, no HA entity (needs a file) | thumbnail adds little over live frames |
| (b') live at N, N+2 s, N+4 s (+ guarded best snapshot) | **N+4 s = E+5.2 s p50, E+12.4 s p90** | n/a, instant | full-res, scene context, person in view at N by construction | **recommended** |
| (c) event `clip.mp4` | file served at N+1 s for the car (5.3 MB) but covers only already-flushed recordings; it is a growing file (5.3 MB at +1 s, 11 MB at +15, 16 MB at +25, 22 MB at +40) | for a fresh person event whether the first fetch contains the person: UNMEASURED | llmvision `video_file` keeps I-frames only | D0b already validated clip = 93 % exact count at 7.5 s p50 call time; use it for B, not F |

Delay question: **no delay is needed for (b')**; a delay only helps recordings, and at about 13 s it defeats the purpose of a fast stage. The operator's "discard the best snapshot if too late, use 3 snapshots around the event" is satisfied by (b') for after-event frames; "just before the event" frames are not obtainable inside the fast window (the recordings lag is 13 s), only from the already-evicted live stream. If a pre-event frame matters, take it from a URA-side ring (see below), which is not measured here.

## 5. llmvision input constraints (version 1.7.1, `~/ha-config/custom_components/llmvision/`)

- `image_file`: local path only, `os.path.exists` check (`media_handlers.py:579-595`); no URL.
- `image_entity`: reads `entity_picture` from the entity state, prepends the HA base URL and fetches (`:518-540`); domains `image` and `camera` only (`services.yaml:52-58`). Works for `camera.*` (live) and `image.*_person_2` (best snapshot). There is **no image_url** parameter in `image_analyzer` (services.yaml lists `image_file`, `image_entity`).
- `video_file`: local path or URL; a path starting with `/api` is HA-signed (5 min) and fetched (`add_video`, `:635-650`). The recording proxy path is therefore usable as `video_file` (clip.mp4 for the event path was proven in D0b); whether the recording route (no `.mp4` suffix) also works: UNVERIFIED (would need one llmvision call).
- What URA needs for non-entity frames (thumbnail, recording frames): write the bytes to a path under `/config` (for example `/config/www/...` or a URA data dir) and pass `image_file`, delete after the call. Privacy: frames sit on disk until deletion; keep the folder out of `/config/www` (that is publicly served at `/local/`), delete in `finally`, count leftovers in a trip-wire. Live-frame recipe (b') needs none of this.
- llmvision's own `stream_analyzer` (`record`, `media_handlers.py:267-440`) polls an `image_entity` repeatedly for a duration; it is the native form of recipe (b') but its parameters (interval, duration, frame cap) were not read in full here.

## Not measured / unverified

- Door **person** `new` event end-to-end (no event in the window). Needed: thumbnail content at `new`, `clip.mp4` content at `new`+1 s for a fresh event, whether `image.<cam>_person_2` updates relative to `new`. The listener (`/private/tmp/claude-501/frames_cvfast/listen.py`, scratch, outside the repo) logs all of these per event; rerun in daytime for about 30 min.
- Recording-clip end-alignment on garage_a and front_door_aerial; ffmpeg availability for URA in the HA container; live-frame pixel age; whether a Frigate segment boundary or camera type explains G6's faster flush (observed, not explained).
- The 13 s lag is for "first 200 on a 1 s window"; for G6 and doorbell_lite I confirmed by stamp that the returned clip reaches the requested end, for the other two cameras not.

## Evidence index

Events: `frigate/events/get` via HA websocket, 300 door person events 2026-11-11 to 11-14 (doorbell_lite 88, garage_a 78, G6 69, aerial 65). Live: `/private/tmp/claude-501/frames_cvfast/live.jsonl` (scratch, not in repo). History: `/api/history/period` for the four `binary_sensor.*_person_occupancy_2`. Code: `views.py:123-134, 224-286, 313-376`; `ws_api.py:164-215, 337-361`; llmvision `media_handlers.py:518-600, 610-660`; `services.yaml:44-58, 181-190`.
