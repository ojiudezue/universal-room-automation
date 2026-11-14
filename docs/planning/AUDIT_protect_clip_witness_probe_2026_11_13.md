# AUDIT: Protect as a second clip witness for door crossings (read-only probe)

Card: NVR-WITNESS-CONSOLIDATION-1 (`docs/planning/kanban.data.yaml:34807`). Probe run 2026-11-13 18:08-18:25 CST (`date`: Fri Nov 13 18:08:12 CST 2026; HA 2026.11.1 per `/api/config`). Read-only: HA REST GETs with the HA token, `ssh ha` read-only sqlite, local source reads. No llmvision call, no state-changing service, no Protect/Frigate login. Process count 651 at start.

HVAC/presence STATE_OF_PLAY docs were NOT read: this is a camera/identity probe, covered by the identity manual domain, and no HVAC/presence claim is made.

## Answer first

Protect clip access is easy: one authenticated HA GET returns an mp4, by event id or by camera + time range. A Protect event id is published on `event.*_smart_detection`. llmvision can take the clip through its existing `video_file` path, but nobody has tested it with a Protect URL. The hard part is the agreement layer, not the clip fetch. Two of the three existing Frigate-vs-Protect rules have a coverage hole or use fixed windows. The garage_a Protect leg appears to feed the transit rule zero times in 14 days.

## Q1 Clip access

Installed HA core on the ha host is not reachable (`ssh ha` is a SSH add-on; no `homeassistant` python module, no docker socket). Source read from the Mac venv copy, HA 2026.2.3: `/Users/okosisi/Code/universal-room-automation/.venv-ha/lib/python*/site-packages/homeassistant/components/unifiprotect/`. Live core is 2026.11.1, so every claim below is **also verified by a live GET** against 2026.11.1 where noted. The `event.*` entity source was read from upstream `dev` (WebFetch of raw.githubusercontent.com .../unifiprotect/event.py), because the venv version lacks it.

Video proxy routes (`views.py`):
- By time range, `views.py:275`: `GET /api/unifiprotect/video/{nvr_id}/{camera_id}/{start}/{end}` returns `Content-Type: video/mp4` (`views.py:~300`). `start`/`end` go through `datetime.fromisoformat` (400 on failure).
- By event, `views.py:332`: `GET /api/unifiprotect/video/{nvr_id}/{event_id}`. It calls `data.api.get_event`, and returns **400 "Event is still ongoing"** if `event.start` or `event.end` is None (`views.py:~345`). So a clip by event id only exists after the Protect event ends.
- Thumbnail, `views.py:180`: `/api/unifiprotect/thumbnail/{nvr_id}/{event_id}`. Snapshot at a time, `views.py:222`: `/api/unifiprotect/snapshot/{nvr_id}/{camera_id}/{timestamp}`.
- Auth: `ProtectProxyView.requires_auth = True` (`views.py:141`). HA signed paths (`authSig`, `http/auth.py:36,175-228`) are accepted on the same request path.
- `nvr_id` accepts either the Protect NVR id or the HA **config entry id** (`views.py:147-153`, `_get_data_or_404`). Live: unifiprotect entry id `01K1SBX7CWG96MAGXTQMFRS5EW` (`.storage/core.config_entries`), "Phalanax NVR Pro". It worked as `nvr_id`.
- `camera_id` accepts the Protect camera id OR an HA **camera entity_id** (`views.py:156-175`: falls back to entity registry -> device MAC -> `get_device_from_mac`). So URA needs no Protect UUID; `camera.front_door_aerial_high_resolution_channel` works.
- media-source form (`media_source.py:194-228`): `media-source://unifiprotect/{nvr_id}:event:{event_id}` resolves to the same proxy URL.

Which entity carries the event id:
- `binary_sensor.<cam>_person_detected` carries `event_id` and `event_score` only while ON (`entity.py:337-342`, `_set_event_attrs`; cleared at event end, `binary_sensor.py:~641-646`). Live while OFF: `binary_sensor.doorbell_lite_person_detected` state off, attributes only `attribution`/`friendly_name` (2026-11-13T20:46:34Z). So history of this entity does not retain event ids once off.
- `event.<site>_<cam>_smart_detection` (newer, present in live registry for all four cameras, e.g. `event.front_porch_front_door_aerial_smart_detection`) fires per detected type with `event_id` and `smart_detect_types`, plus `event_source` (upstream event.py, `ProtectDeviceDetectionEventEntity._async_detection_event`). Live read: `event.front_porch_front_door_aerial_smart_detection` state `2026-11-13T21:31:50.743+00:00`, `event_type: person`, `event_id: 01a1d6d2-f03d-77a7-9ac0-d57257a62bc7`. **No end time or duration** is in the event data (upstream excerpt: only event_id, smart_detect_types, event_source). The event-entity state is the event start timestamp. Dedup is per (event id, type, event.type), 16 ids tracked.
- Event entity ids on the four door cameras (registry): `event.garage_a_garage_doorbell_lite_smart_detection` (doorbell_lite), `event.garage_a_garage_a_smart_detection`, `event.front_porch_front_door_aerial_smart_detection`, `event.front_porch_madrone_g6_entry_smart_detection`. The names embed an area slug that can change; resolve through device -> entity registry, never by name.

Live proxy probes (all with the HA token, body discarded, nothing saved):
| Request | Result |
|---|---|
| `GET /api/unifiprotect/thumbnail/01K1SBX7.../01a1d6d2-f03d-77a7-9ac0-d57257a62bc7` | 200 `image/jpeg` 53 499 B |
| `GET /api/unifiprotect/video/01K1SBX7.../01a1d6d2-...` (the person event above) | 200 `video/mp4` 11 017 506 B, 1.45 s |
| `GET .../video/01K1SBX7.../camera.front_door_aerial_high_resolution_channel/2026-11-13T21:31:40+00:00/2026-11-13T21:31:55+00:00` | 200 `video/mp4` 17 022 861 B, 0.65 s |
| same with `Z` suffix times | 200, same size |
| same event URL, no token | 401 |

`select.<cam>_recording_mode` = `always` on all four door cameras (live states, 2026-11-13). Continuous recording means a time-range clip exists even for crossings where Protect never raised a person event. Unverified: behaviour when `end` is within the last seconds (segment still being written), and Protect retention for the range route (the 7-day recorder window is not the NVR retention; see `sensor.*_oldest_recording`, not read).

## Q2 llmvision input (installed 1.7.1, `/Users/okosisi/ha-config/custom_components/llmvision`)

`services.yaml:138-215` `video_analyzer` fields: `provider`, `model`, `message`, `store_in_timeline`, `use_memory`, `video_file`, `event_id`, `max_frames` (1-10, default 3), `include_filename`.
- (a) Frigate event id only: yes. `event_id` is described "Frigate Event ID" (`services.yaml:189-194`). `media_handlers.py:932-936` turns each into `/api/frigate/notifications/<id>/clip.mp4`. It is Frigate-specific, with no instance id.
- (b) Local file path: yes. `video_file` "local paths or URLs", newline separated (`services.yaml:181-188`; `__init__.py:463-466`). Non-http paths go to ffmpeg directly (`media_handlers.py:707-722`).
- (c) URL: yes. Paths starting `/api` are signed with a 5-minute HA `authSig` and prefixed with the HA base URL (`media_handlers.py:629-642`). `media-source://` ids are passed to `async_process_play_media_url` (`:623-627`). I read HA's `browse_media.py:35-47`, which returns non-http(s) schemes unchanged, so a media-source id is **unverified and probably not resolved** here. Use the `/api/unifiprotect/video/...` path.
- (d) Camera entity stream: not in `video_analyzer`. That is a separate service, `stream_analyzer` (`__init__.py:756`), which records frames from entities.
- Could a Protect clip go through (b)/(c)? By code path yes: `video_file=/api/unifiprotect/video/<nvr>/<event_id>` (or the camera+range form) is signed, fetched with `session.get` to a temp file (`:661-673`, `_fetch :224-262`), then ffmpeg. The HA signed-path mechanism is generic (`http/auth.py:227`). **Not run**: the brief forbids llmvision calls (cost). The only prior art is the Frigate analogue, `AUDIT_crossing_vision_d0_2026_11_13.md:75` (200 in 7.8 s on a Frigate instance-scoped `clip.mp4` URL).
- Frame extraction: ffmpeg `-vf select=eq(pict_type\,I)` (keyframes only, `media_handlers.py:644-656`), mjpeg pipe, `-an -sn -dn`, 300 s timeout. There is no fixed time interval: frame spacing is the camera's keyframe (GOP) interval. First keyframe is always kept, the rest are the lowest-SSIM-versus-previous frames (`:864-880`), up to `max_frames`, then resized to `target_width`. Quirk (code read only, not exercised): the `if frame_counter >= max_frames: break` at `:822-823` breaks only the inner for-loop; the pipe keeps being read. Protect's GOP interval is unknown; a 15 s Protect high-res clip was 17 MB, so a 768 px resize happens after full-size decode.
- ffmpeg binary: the HA host's ssh add-on has none (`ssh ha 'which ffmpeg'` empty); the HA core container is a different filesystem, so this is **unverified**. Frigate clips already work through the same ffmpeg step (D0b 42/45), so it exists in the llmvision runtime.
- Implication: the crossing-vision plan's design (`PLANNING_crossing_vision.md:118-120`, Frigate `clip.mp4` URL) maps one-to-one to a Protect URL. Which camera/event the clip belongs to is the only new logic.

## Q3 Coverage (entity registry `.storage/core.entity_registry`, platform == unifiprotect, none disabled for the entity named)

`door_groups` (URA config entry options): `doorbell_lite`->garage_a, `garage_a`->garage_a, `front_door_aerial`->front, `madrone_g6_entry`->front. `egress_cameras` option: `camera.madrone_g6_entry`, `camera.doorbell_lite`, `camera.front_door_aerial`, `camera.garage_a_2`.

| Door camera | Protect person sensor | Protect event entity | Protect camera entity | Frigate leg (platform frigate) |
|---|---|---|---|---|
| doorbell_lite (Protect device "Garage Doorbell Lite") | `binary_sensor.doorbell_lite_person_detected` | `event.garage_a_garage_doorbell_lite_smart_detection` | `camera.doorbell_lite_high_resolution_channel` | `binary_sensor.doorbell_lite_person_occupancy_2`, `sensor.doorbell_lite_person_count` |
| garage_a | `binary_sensor.garage_a_person_detected` | `event.garage_a_garage_a_smart_detection` | `camera.garage_a_high_resolution_channel` | `binary_sensor.garage_a_person_occupancy_2`, `sensor.garage_a_person_count` |
| front_door_aerial | `binary_sensor.front_door_aerial_person_detected` | `event.front_porch_front_door_aerial_smart_detection` | `camera.front_door_aerial_high_resolution_channel` | `..._person_occupancy_2`, `sensor.front_door_aerial_person_count` |
| madrone_g6_entry | `binary_sensor.madrone_g6_entry_person_detected` | `event.front_porch_madrone_g6_entry_smart_detection` | `camera.madrone_g6_entry_high_resolution_channel` | `..._person_occupancy_2`, `sensor.madrone_g6_entry_person_count` |

All four cameras have a Protect leg. Camera ids: Frigate bare legs are retired (memory `reference_frigate1_retired_2suffix_permanent`); the `_2` suffix is the live Frigate platform. Protect `person_detected` is in the registry for all four with `disabled_by: None`; `object_detected` is the disabled-by-integration one.

## Q4 Agreement from existing history

**Window caveat: 7 days, not 14.** `configuration.yaml:13` `recorder: purge_keep_days: 7`. Oldest history row 2026-11-06 13:27Z (`/api/history/period`, minimal_response). The DB table has 228 crossings since 2026-10-30 (14 d) but only 123 fall in the recorder window. Do not extrapolate 14 d from this.

Method: `person_entry_exit_events` read via `ssh ha sqlite3 -readonly` (the Samba mount refused `-readonly`). Timestamps are naive UTC (latest row 20:46:55 matched Protect/Frigate edges at 20:46:3xZ). The row timestamp is the **resolve time**, trigger + `EGRESS_ENTRY_WINDOW_SECONDS` 45 / `EGRESS_EXIT_WINDOW_SECONDS` 30 (`const.py:3315-3316`; edge offsets before the row cluster at 40-50 s, 63 of 123). So crossing time T was recovered by finding the trigger entity's own on-edge within 15 s of (row ts minus window). 73 of 123 rows anchored this way; 50 had no such edge and are **excluded** (reason unknown: unverified). "Fired" = binary sensor off->on, or count sensor 0->N. Frigate = occupancy_2 or count; Protect = person_detected. Scripts: scratchpad `w/an.py`, `w/an2.py` (not committed).

Per camera, anchored crossings, +-10 s / +-30 s of T:
| Camera | n | both | Frigate only | Protect only | neither |
|---|---|---|---|---|---|
| doorbell_lite | 32 | 19 / 24 | 8 / 4 | 5 / 4 | 0 / 0 |
| garage_a | 18 | 16 / 18 | 2 / 0 | 0 / 0 | 0 / 0 |
| front_door_aerial | 4 | 4 / 4 | 0 / 0 | 0 / 0 | 0 / 0 |
| madrone_g6_entry | 19 | 7 / 8 | 10 / 10 | 2 / 1 | 0 / 0 |
| ALL | 73 | 46 / 54 | 20 / 14 | 7 / 5 | 0 / 0 |

"Neither" is 0 by construction (T is anchored to one platform's own edge); it cannot show crossings with no detection at all. The 50 un-anchored rows are the part that could hide a "neither".
- Protect would add coverage for 7/73 (9.6 %) crossings at +-10 s, 5/73 (6.8 %) at +-30 s, where Frigate raised nothing near T. Small, uneven (doorbell_lite only plus 1-2 on madrone).
- madrone_g6_entry is the one-sided camera: Frigate fires, Protect does not (10 of 19 crossings). Over all edges, madrone Protect fired 37 times vs Frigate occupancy 67 in 7 d, and 38 of 67 Frigate edges had no Protect edge within +-30 s. Whether this is Protect missing real people or Frigate false positives is **unverified** (no ground truth was pulled).
- Independent of crossings (all edges, 7 d, occupancy_2 vs person_detected, +-30 s): doorbell_lite Frigate 107 (22 w/o Protect) / Protect 85 (10 w/o Frigate); garage_a 93 (21) / 85 (15); front_door_aerial 35 (6) / 37 (10); madrone 67 (38) / 37 (7).
- Cross-check via the DB's own confidence column (14 d, 0.9 = two platforms within 10 s, `transit_validator.py:2165-2170`): doorbell_lite 51/76 at 0.9, front_door_aerial 13/28, madrone 14/53, **garage_a 0/71**.
- **Finding: the garage_a Protect leg does not reach `_count_platforms_fired`.** `binary_sensor.garage_a_person_detected` fired 85 times in 7 d and sat within +-10 s of 16 of 18 anchored Frigate-triggered crossings, yet no garage_a row in 14 d is 0.9 and none has a Protect trigger entity (`egress_camera` values for garage_a: only `..._person_occupancy_2` and `sensor.garage_a_person_count`). If it were subscribed, those 16 would have scored 0.9. Cause unverified (candidates: the resolver does not fuse `camera.garage_a_2` with the Protect device; `resolve_operator_declaration`, `camera_resolver.py:836-868`, not traced further). Falsifier: any row with `egress_camera = binary_sensor.garage_a_person_detected` or confidence 0.9 on garage_a (none found).

## Q5 Existing Frigate-vs-Protect rule sites

| Site | Window | "Agree" means | Cameras |
|---|---|---|---|
| `camera_census.py:2330` `_cross_validate_platforms` (counts, not time) | none: compares the current census snapshot counts | both > 0: Frigate count wins, tag BOTH. One zero: uncorroborated higher reading downgraded to min (0, DISAGREE) via `_apply_divergence_downgrade` (`:2395-2416`) if `CONF_CENSUS_DIVERGENCE_DOWNGRADE`, else CLOSE | per census zone, all platforms; "binary platform" = Protect/Reolink/Dahua summed |
| `transit_validator.py:2689` `_count_platforms_fired` | +-10 s (hardcoded `<= 10`, `:2705`) of the egress timestamp (the trigger time, not row time) | >= 2 distinct platform tags among `_recent_egress_events` with the same camera stem; confidence 0.9 vs 0.8 (direction ambiguous 0.4/0.3), `transit_validator.py:2165-2170` | the four `egress_cameras` only; stem via `camera_census.py:1009-1046`, which strips `_N` and person suffixes |
| `perimeter_alert.py:4780` `_apply_single_source_gate` + `perimeter_fp_gates.py:16` `nvr_family` | look-back `_SOLE_FIRE_WINDOW_S = 60` (`perimeter_alert.py:2276`), plus forward settle `PERIMETER_SS_SETTLE_S = 8` (`const.py:2636`); agreement tracker pair window = the same 60 s (`:459-461`) | other NVR family fired in the window, plus per-camera agreement rate >= 0.6 over >= 20 samples (`const.py:2637-2638`), first alert only; otherwise demote severity | `perimeter_cameras` (12 cameras), NOT the door cameras; `nvr_family`: engine tag prefix frigate/protect |

Platform-guess check for `_count_platforms_fired` (`:2700-2710`): substring test `"_person_occupancy" in entity_id or "_person_count" in entity_id` -> frigate; `"_person_detected"` -> unifi; anything else counts as its own platform. For the door cameras' actual entities this classification is correct: `binary_sensor.*_person_occupancy_2` contains `_person_occupancy` (frigate), `sensor.*_person_count` (frigate), `binary_sensor.*_person_detected` (unifi). `_person_active_count_2` would not match either test and would count as a third platform, but that sensor is in the Frigate registry (`sensor.*_person_active_count_2`) and I found no evidence it is subscribed (the DB `egress_camera` column shows only occupancy_2, person_detected and person_count, 228 rows). Unverified: the live subscription list itself (not exposed; read via DB trigger values only). The real problem is coverage (garage_a above), not the suffix guess.

Other Frigate-vs-Protect comparison sites found by `grep -rli protect | xargs grep -li frigate` over the component, with the ones that actually compare:
- `transit_validator.py:125-159` `egress_identity_tier_labelled`: face legs from different engines on the SAME camera share a `base_stem` (`:2020-2023` comment), so same-camera Frigate+Protect is BOOST (`FACE_MATCH_CORRELATED_BOOST`), not HIGH. HIGH needs two different physical cameras. Face window `FACE_MATCH_WINDOW_S = 60` (`const.py:3347`).
- `domain_coordinators/security_lock_regime.py:1262`: a comment about camera_face arrival, no Frigate-vs-Protect comparison found (grep for protect/frigate/engine returned only that line and `:2078`).
- `perimeter_alert.py` D3 zone-agreement gate (`:4740-4770`) is Frigate-only (entered_zones); no Protect counterpart.
- `camera_resolver.py` / `camera_census.py:resolve_cross_platform_sensors` (`:808+`): the resolver that decides which Protect sibling is bound to which Frigate camera (see the garage_a finding).
No evidence of any shared helper: three different windows (none / 10 s / 60 s) and three different meanings of "agree".

## Verdict: MODERATE

Easy to fetch, moderate to make it a trustworthy second witness.
- Easy: clip by event id or camera+range is one authenticated GET (Q1 live 200s), continuous recording is `always`, llmvision accepts a signed `/api` URL (Q2 by code), all four door cameras have a Protect leg (Q3).
- Moderate: the agreement data is thin and uneven (7 d, 73 anchored crossings, 6.8-9.6 % Protect-only coverage gain), three rule sites use incompatible windows, and the garage_a Protect leg is evidently not wired into the transit rule.

Three biggest unknowns:
1. **Why garage_a Protect never reaches `_count_platforms_fired`** (0 of 71 crossings in 14 d at 0.9, no Protect-trigger rows). A shared witness layer inherits this hole unless the cause is found (resolver fusion vs subscription).
2. **llmvision on a Protect clip is untested**: whether the `/api/unifiprotect/video/...` URL decodes and yields usable keyframes (Protect GOP interval and codec unknown; 17 MB for a 15 s range), and whether a still-open Protect event (400 on the by-event route; no end time on `event.*_smart_detection`) forces the range route with a guessed end.
3. **Ground truth for Protect-vs-Frigate disagreement**: madrone_g6_entry shows 10 of 19 Frigate-only crossings and 38 of 67 Frigate edges without Protect. Which NVR is right is unmeasured, and 50 of 123 crossings could not be time-anchored, so "neither" is unmeasured.
