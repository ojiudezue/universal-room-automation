# AUDIT: Protect face-NAME interfaces — have we exhausted the paths? (read-only)

Probe 2026-11-13 18:53-19:20 CST (`date` = Fri Nov 13 18:53:10 CST 2026). Read-only; no Protect/Frigate login, no HA state-changing calls. HA REST GET only (token held in a variable, not printed). Process count 593 at start.
Docs read in full for this: `reference_protect_face_latency_async.md` (memory), `RESEARCH_protect_face_to_ha.md`, `AUDIT_frigate_door_face_2026_11_13.md`, `AUDIT_face_production_after_nov_fixes.md`. IDENTITY manual read only at §1 table, §1.1 Protect note, §2.3 (not the whole manual). PRESENCE state-of-play NOT read (this is an interface-research question, not a presence change).

## Answer (lead)
1. **Premise correction: URA has NO live Protect face-name path today.** Grep of `custom_components` for `matchedName|matched_name|get_events|get_event|uiprotect` finds no Protect poller. The Protect face leg is "KEEP + DOCUMENT, dead until parked D1-PROTECT-FACE-BRIDGE-ADDON-1" (`camera_resolver.py:247-250`, `camera_census.py:3365-3368`, manual §1.1). The only live face-name feed is Frigate (MQTT `<prefix>/tracked_object_update`, `camera_census.py:5249-5540`, `frigate_ingress.py:19,51`). So "polling cadence and lookback of the Protect face path" = none exists; the 40-80 s figure is a 2026-08-29 manual measurement (memory), not a production metric.
2. **180 s settle is not a Protect measurement.** `CROSSING_VISION_NAME_SETTLE_S` is a planned knob (180/660), "entry set to P2-D0 (viii) p99 + 30 s" (`PLANNING_crossing_vision.md:324`); P2-D0 (viii) "Protect name back-fill p99 at door cameras" (`:177`) is a probe not yet reported in the two AUDIT_crossing_vision_d0 docs (grep found no result). The constant does not exist in code yet.
3. **Protect face recognition is enabled on only two cameras** (Family Room, Madrone G6 Entry; manual §2.3 "Scope", verified 2026-08-28). Faster Protect names help only the G6 entry door. Frigate covers all door cameras (doorbell_lite, garage_a, G6 entry, front_door_aerial) but names only 10-29% of door person events, geometry-limited (`AUDIT_frigate_door_face_2026_11_13.md`).
4. **We have not exhausted the paths.** Three are unexplored or under-explored: (a) re-capture the Alarm Manager webhook body (last test returned `{}` in Aug; community reports a real payload), (b) use the HA unifiprotect `event.*_smart_detection` entity's `event_id` as an instant trigger plus a one-shot REST re-fetch through HA's already-authenticated client, (c) consume Frigate `tracked_object_update` per-attempt name earlier than `sub_label` (already done) and fuse with Protect.
5. **The public Protect Integration API will NOT help.** Confirmed by uiprotect issues #914 and #1154 (see below).

## Interface-by-interface

### 1. uiprotect releases since 16.6.1
- Exists: yes, much newer. HA core dev manifest pins `uiprotect==25.0.2` (https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/unifiprotect/manifest.json). Releases: v23.6.0 (2026-10-19) ... v25.0.0 (2026-10-26), v25.0.1 (11-05), v25.0.2 (11-06) (https://github.com/uilibs/uiprotect/releases). v25.0.0 notes: removal of private camera/chime settings, nothing on face/matched_name/thumbnails/websocket (https://github.com/uilibs/uiprotect/releases/tag/v25.0.0). Releases between 16.6.1 and 23.6.0 NOT read (page lists 10 at a time) — unknown whether any touched face metadata.
- Does the websocket now carry the name? **No evidence of it.** Discussion #442: maintainer's capture of `subscribe/events` shows `add` (smartDetectTypes ["face"]) then `update` adding "person"; neither message has a name; "no other REST method" found (May 2025). 2026-10-04 update there: uiprotect now uses the official Integration API in hybrid or API-key-only modes (https://github.com/uilibs/uiprotect/discussions/442). 2026-08-29 live measurement in memory (websocket "no name yet" at 26 s, REST re-query at ~82 s has `matchedName`) is consistent.
- Data location: private REST event record, `metadata.detected_thumbnails[*].group.matched_name` (`RESEARCH_protect_face_to_ha.md` §2). Client methods verified in source: `get_events_raw(start,end,limit,types,smart_detect_types,...)` at `GET /proxy/protect/api/events`, `get_event(event_id)`, `get_event_thumbnail` (https://raw.githubusercontent.com/uilibs/uiprotect/main/src/uiprotect/api.py). Private calls need a username/password client, not API-key-only (`PublicOnlyModeError`).
- Latency: 40-80 s (the AI queue, not the transport; no library change moves it).
- Effort: n/a. URA uses it: no.
- Verdict: nothing new to gain from the library alone.

### 2. HA core unifiprotect (live HA 2026.11.1, GET /api/config)
- Exists as face entity: **no.** `event.<cam>_smart_detection` has `event_types` incl. `face` but attributes only `event_id`, `smart_detect_types`, `event_source` (live read: `event.living_room_family_room_smart_detection` attrs, 2026-11-14T00:54:35Z UTC; `event.front_porch_madrone_g6_entry_smart_detection`). Core `event.py` (dev) fires per detected type and dispatches updates, dedupes on (event id, type, event type); the only `matched_name`/`detected_thumbnails` use is the vehicle entity (license plate). Docs: "smart detection event reports which type, not the richer recognized metadata" (https://www.home-assistant.io/integrations/unifiprotect/). Open feature request unresolved (https://community.home-assistant.io/t/expose-face-recognition-from-unifi-protect-integration/753747).
- Polling interval: not set in `data.py` (passed by constructor); events are websocket push, "no REST re-fetch of events" in `data.py`. IoT class `local_push`.
- **Creative reuse (unexplored):** the entity gives an `event_id` within about a second of the raw face event, and `ProtectData.api` (type `UFPConfigEntry = ConfigEntry[ProtectData]`, `entry.runtime_data.api`) is the already-authenticated uiprotect client. URA could, on that entity's state change with `face` in `smart_detect_types`, schedule re-fetches (`api.get_event(event_id)`) at e.g. +20/40/60/90 s and read `metadata.detected_thumbnails`. No URA-held credentials (satisfies the no-credential rule), event-id-exact (no timestamp-window guessing), stamps to true detection time. Risks: reaching into another integration's `runtime_data` (private-ish API, version churn; `data.py` in 25.x supports a public-only mode where private calls raise), and the name still lands only when Protect finishes (40-80 s). This shrinks the polling cost and lookback guesswork, not the latency. Unverified: whether this install's entry is private/hybrid (needs user/pass) or API-key-only.
- Effort: M. Latency: same 40-80 s, but exact and gap-free. URA uses it: no.

### 3. UniFi Protect public Integration API (API key) + events websocket
- Exists: yes (`/v1/subscribe/events`), but **does not carry face names.** uiprotect #914: live capture of a full face-event lifecycle had `"metadata": null` on every frame; OpenAPI 7.1.75 smart-detect schema has no matched-name field, no event-detail endpoint; labeled `public-api-gap`, no Ubiquiti reply, closed "not planned" 2026-08-17 and folded into #1154 (https://github.com/uilibs/uiprotect/issues/914, https://github.com/uilibs/uiprotect/issues/1154). #1154 also lists no event thumbnail endpoint (#924).
- Latency: n/a. Effort: n/a. Dead end until Ubiquiti extends it. Re-check trigger: a Protect release note adding smart-detect metadata to the public schema.

### 4. Protect Alarm Manager (Face trigger + webhook action)
- Exists: yes. Alarm Manager supports Face triggers; webhook action POSTs to any URL (help.ui.com articles 25478744592023 and 27721287753239; community: `trigger.json.alarm.triggers[0].value == 'Boris'`, `key: face_known | face_of_interest`, nested `group.name`, https://community.home-assistant.io/t/unifi-protect-custom-webhook-vs-home-assistant-trigger/847025). Webhook sender: `unifiprotect.trigger_alarm_webhook` is the reverse direction (HA to Protect), irrelevant here.
- **On this install it returned `{}`** (manual §2.3, live crossing 2026-08-28 07:27:28; `ura_kp_face_probe`). Not re-tested since. Possible causes NOT ruled out: rule trigger type, listener reading `trigger.json` while body is another content-type (a raw capture via `trigger.data`/`webhook.site` was never done per the files read), or firmware difference. This is the single cheapest unexplored item.
- Latency: community reports the webhook fires at the END of the smart detection ("when the face leaves the frame"), so likely no faster than REST back-fill and possibly later; UNVERIFIED on this NVR. Benefit is push (no polling) and the name directly.
- Effort: S to re-probe (one raw capture), M to wire. URA uses it: receiving side wired only (`automation.ura_kp_face_webhook_probe`, manual §2.3). Hovborg/unifi-protect-bridge (HACS) is a packaged version of the same mechanism (51 commits, release ~0.2.22, last-commit date not shown, no latency figures; https://github.com/Hovborg/unifi-protect-bridge); inherits the same end-of-event timing.

### 5. Thumbnail metadata / AI Key queue
- Exists: names ride `detected_thumbnails` (item 1); thumbnails fetched via `get_event_thumbnail(thumbnail_id)` (`events/{id}/thumbnail`). Queue: AI Key ~1000 detections/hr, local (memory, UniFi AI Key FAQ; not re-verified today). No documented knob to prioritize. Levers are marginal: dedicated AI processor, do not saturate the queue, enrolment quality (Jaya/Ezinne not enrolled in Protect as of 2026-08-28, manual §2.3). The enrolment gap, not latency, is the larger Protect loss (many crossings match an unnamed `face_###` cluster).
- Latency gain: none; effort S (operator enrols/merges clusters). URA uses: no.

### 6. Frigate (F2 on 0.18.2 per `AUDIT_frigate_door_face_2026_11_13.md`; memory's 0.17.2 is older)
- **Already used.** MQTT `<prefix>/tracked_object_update`, `type=="face"`, name latched with TTL `FACE_NAME_LATCH_TTL_S` (`camera_census.py:5463-5540`, `const.py:3621-3633`); retained messages skipped; sentinel names dropped. Live health on 2026-11-13 00:56 UTC: 191 face messages seen since last restart, 21 dropped (`AUDIT_face_production_after_nov_fixes.md` §2).
- What Frigate exposes (docs 0.18, https://docs.frigate.video/integrations/mqtt): `tracked_object_update` face payload `{id, name|null, score (running weighted avg), camera, timestamp}` published after EVERY recognition attempt regardless of threshold; `frigate/events` after.sub_label is the debounced name (weighted by face area; one high score alone does not promote); `frigate/reviews` data.sub_labels. Face-recognition knobs: `min_faces` (default 1), `recognition_threshold` 0.9, `unknown_score` 0.8, `min_area` 750 px, `model_size` small/large (large needs GPU/NPU) (https://docs.frigate.video/configuration/face_recognition).
- Latency: **UNKNOWN, not measured.** Docs imply per-attempt during the track (seconds), far below Protect. No file I read measures event-start to first named message. Recommend a one-shot probe: join Frigate events (`start_time`) to the first `tracked_object_update` named message per event id (the message has `id`, so no time-window guess). I did not run it (broker/Frigate login out of scope).
- Limits are coverage, not latency: named rate door cameras 26% / 29% / 10% (71% of G6 events are tiny street boxes; 30% on usable boxes) / 14%; top-down garage_a and front_door_aerial; Ezinne 8 names vs Jaya 63; wrong names score 0.9-1.0 (Ojini ghost). Score cannot separate right from wrong (`AUDIT_frigate_door_face_2026_11_13.md`).
- Gap I can see in code: the bridge latches `name` and `ts` but the message carries event `id` and `score` (running average); whether URA uses `id` to dedupe per object or `score` to weight confidence was not checked here (`camera_census.py:5540+` not read past the latch). Candidate refinement, UNVERIFIED.

### 7. Creative / fusion
- **Frigate + Protect fusion.** The framework exists (`FACE_MATCH_CORRELATED_BOOST` 0.75, manual line 826; two-engine legs in `_resolve_face_legs`). Protect only adds value on G6 entry (and Family Room interior). Treat Protect as a corroborator that arrives late, never the gate.
- **BLE/phone pre-identity at the door.** Exists as F5 (arrival) and the BLE crossing producer (`_register_ble_transition_listeners`, per CLAUDE.md prior-art note and `PLANNING_census_ble_over_face.md`); faster than any camera name when the phone is carried (Frigate is also contradicted by phones: 19/41 candidates tracker-fault per `AUDIT_egress_history_labels`). Not a face interface; a separate fact class (F5). No new work implied by this audit.
- **Vision-LLM witness** (crossing vision P2) is the name-independent path; separate arc, already planned.
- **Door-camera quality for Frigate** (second angled camera, G6 `min_area`, Ezinne/Jaya door-angle training crops): the largest lever on coverage (`AUDIT_frigate_door_face_2026_11_13.md` steps 1-8). Operator/homelab, not URA code.
- **Interior-then-exit fusion** is how most names already arrive (84.7% of named faces from interior cameras, `AUDIT_face_production_after_nov_fixes.md` §4): a name seen inside 1-2 min after entry back-fills an entry via the 300 s `FACE_MATCH_ENTRY_WINDOW_AFTER_S` (`const.py:3387-3390`). This already tolerates a 40-80 s Protect lag.

## What would disprove the main claims
- "No live Protect path in URA": a registered consumer of `get_events`/`detected_thumbnails` outside `custom_components` (e.g. an HA automation or the `unifi-protect` MCP-driven script) feeding `sensor.*_face_recognized`. Check: live `sensor.*_face_recognized*` entities; none checked in this probe — UNVERIFIED beyond code grep.
- "Webhook is a dead end": one raw capture of the POST body at the HA webhook (headers + body) showing a populated `alarm.triggers` list.
- "Public API carries no name": a newer OpenAPI schema (>7.1.75) with smart-detect metadata.

## Ranked table
| # | Interface | Exists | Expected latency | Effort | Recommendation |
|---|---|---|---|---|---|
| 1 | Frigate `tracked_object_update` face (already live) + door-camera quality/enrolment | Yes, live (`camera_census.py:5249`) | seconds (UNMEASURED; probe event-id join) | S probe; homelab for cameras/training | **Keep as primary; measure start-to-first-name now.** Coverage, not latency, is the cap |
| 2 | Alarm Manager Face webhook re-capture (raw body) | Yes; returned `{}` 2026-08-28 | likely end-of-event (UNVERIFIED); push, no poll | S probe, M wire | **Re-probe once** (capture raw POST); proceed only if name present and p99 beats REST |
| 3 | HA `event.*_smart_detection` `event_id` trigger + REST `api.get_event` via HA's client | Yes (entity live; `runtime_data.api` per core `data.py`) | 40-80 s but exact, gap-free | M | **Build only if G6-entry Protect names are needed**; exact-id join beats polling windows. Verify the entry is private/hybrid first |
| 4 | Polling `get_events_raw` (URA-owned client or HACS bridge) | Yes (`api.py`) | 40-80 s plus poll jitter | M-L (creds, lifecycle) | Park (= parked D1-PROTECT-FACE-BRIDGE-ADDON-1); item 3 dominates it |
| 5 | Protect enrolment/clusters (Jaya, Ezinne; merge `face_###`) | Yes (Protect app) | none | S operator | Do alongside item 3; raises Protect yield on two cameras |
| 6 | uiprotect >16.6.1 websocket name push | No (#442, #914) | n/a | n/a | Drop |
| 7 | Public Integration API events | Yes, no name field (#914/#1154) | n/a | n/a | Drop; revive on Ubiquiti schema change |
| 8 | HA core face entity / upstream PR | No (request open) | n/a | L, outside control | Drop for planning |
| 9 | hardware: AI Key / dedicated AI processor | Yes | marginal | $ | Only if queue saturation is shown (not measured) |

## 3 most promising paths
1. **Measure Frigate first-name latency and per-attempt behaviour at the four door cameras** (join `frigate/events` id to first named `tracked_object_update`). This is the one interface that can be fast, already ingests, and its true latency is unmeasured. Pair with the Frigate door-camera/training actions already handed to homelab.
2. **Re-capture the Alarm Manager webhook raw body.** One probe, zero code; if populated it is a push path with the name inline and replaces polling for Protect.
3. **HA entity `event_id` + REST re-fetch through HA's authenticated client**, scoped to G6 entry (and Family Room), only if the webhook fails or is late. Gives exact event join without extra credentials; does not speed the name.

## Sources
- https://github.com/uilibs/uiprotect/discussions/442
- https://github.com/uilibs/uiprotect/issues/914
- https://github.com/uilibs/uiprotect/issues/1154
- https://github.com/uilibs/uiprotect/releases ; /releases/tag/v25.0.0
- https://raw.githubusercontent.com/uilibs/uiprotect/main/src/uiprotect/api.py (get_events_raw, get_event, get_event_thumbnail)
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/unifiprotect/{manifest.json,event.py,data.py}
- https://www.home-assistant.io/integrations/unifiprotect/
- https://docs.frigate.video/integrations/mqtt ; https://docs.frigate.video/configuration/face_recognition
- https://community.home-assistant.io/t/unifi-protect-custom-webhook-vs-home-assistant-trigger/847025
- https://github.com/Hovborg/unifi-protect-bridge
- In-repo: `docs/planning/RESEARCH_protect_face_to_ha.md`, `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` (§1, §2.3), `docs/planning/PLANNING_crossing_vision.md:177,324`, `AUDIT_frigate_door_face_2026_11_13.md`, `AUDIT_face_production_after_nov_fixes.md`.

## Not verified / limits
- Never reached: `get_event_smart_detect_track` and uiprotect releases between 16.6.1 and 23.6.0 (face-related changes unknown); Protect firmware release notes; AI Key queue figures (taken from memory).
- Frigate event-start-to-name latency: no measurement exists in the files read; I did not query the broker or Frigate.
- Whether this install's HA unifiprotect entry holds user/pass (private/hybrid) or API key only: not checked (would require reading config entry data; forbidden for keys).
