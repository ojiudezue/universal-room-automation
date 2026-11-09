# AUDIT: why SNAP-1 tier 1 (`frigate_event`) never succeeds

Card: PERIMETER-FRIGATE-SNAPSHOT-CAPTURE-NEVER-1. Read-only probe, 2026-11-08 ~23:00 CST. Nothing changed.
No STATE_OF_PLAY doc read: this is perimeter alerting, not HVAC or presence.

## Answer (short)

1. **Root cause (high confidence): the tier-1 download goes to the external URL, which times out from the HA host.**
   - `_http_get_bytes` calls `self._absolutize(url_path)` (perimeter_alert.py:3903-3908).
   - `_absolutize` prefers `hass.config.external_url` over `internal_url` (perimeter_alert.py:3350-3373, `external_url` at :3363).
   - Live `external_url` is `https://haos.phalanxmadrone.com:8123`. `internal_url` is `http://192.168.13.13:8123` (`GET /api/config`).
   - The Frigate GET has a 2 s timeout (`PERIMETER_SNAPSHOT_HTTP_TIMEOUT_S = 2`, const.py:3021) inside a 3 s whole-capture budget (`PERIMETER_SNAPSHOT_CAPTURE_BUDGET_S = 3`, const.py:3017).
   - From the HA host over ssh, the same snapshot path returned:
     - external host: `000`, timeout after 6 s
     - `http://127.0.0.1:8123`: `200`, 75,499 B, 0.052 s
     - `http://192.168.13.13:8123`: `200`, 75,499 B, 0.036 s
   - The hostname resolves to a Cloudflare IPv6 address (2606:4700:3030::6815:462e). My Mac also timed out at 10 s on the external URL.
   - Every tier-1 attempt therefore fails, and the code falls through to `live_grab`. This matches the symptom: all 1,825 files in `/media/ura/snapshots` match the live-grab name shape `<cam>_<epoch10>_<hex6>.jpg`, and none match the Frigate shape `<cam>_<eventid>.jpg` (`ssh ha ls`, grep -v of the live-grab pattern returned nothing).
2. **Tier-1 inputs are otherwise healthy.**
   - The `frigate_events` bridge is firing.
   - The event id is usually on the bus at about the time of the edge.
   - The proxy URL resolves for the Frigate-2 instance id `frigate-f2`.
3. **Secondary design gap.** Tier 1 reads the id cache once, at the edge, with no wait or retry. In about 39% of alerts the edge lands before the bus `new` message, so the cache is empty. Fixing the URL alone would leave roughly 40% of alerts on live-grab.
4. **Not a timing problem for real people.** In my 9-alert sample, every alert where Frigate saw a real person also had that person in the live grab. The "empty" frames were detections on non-person clutter (see section 6).

## 1. Code path read (producer and consumer)

- **Producer of the event id:** `_on_frigate_event` (perimeter_alert.py:926-961).
  - It lowercases the camera name, keeps only label `person`, ignores `end` messages, and stores `_frigate_last_event_id[cam_key] = (id, utcnow)`.
  - The `frigate_events` listener is registered at :963.
- **Consumer, tier 1:** `_try_capture_frigate_event` (:3759-3845).
  - It reads the cache once.
  - It requires age < `FRIGATE_SNAPSHOT_ID_TTL_S` (120 s, const.py:2977).
  - It builds candidate URLs.
  - If `_frigate_instance_ids` is non-empty, only instance-scoped URLs are tried. The default URL is skipped on purpose (F4, :3790-3806).
  - It then calls `_http_get_bytes`.
- **Capture precedence:** `_capture_precedence` (:3721-3757) walks `("frigate_event", "protect_thumb", "live_grab")`. `protect_thumb` is hard-skipped. A `None` from tier 1 falls to `live_grab`.
- **Timing:** `_maybe_start_edge_capture` runs at the sensor rising edge (call at :4206, defined :3506). The result is consumed by `_await_edge_capture` (:3577) from `_async_handle_perimeter_trigger` (:1611) and the vehicle path (:3196).
  - Tier 1 is evaluated once, in that edge task.
- **Instance discovery:** `_discover_frigate_instance_ids` (:3479-3498) reads `hass.data["frigate"][entry]["config"]["mqtt"]["client_id"]`.
  - I could not read the live value of `_frigate_instance_ids`.
  - Inferred as `frigate-f2`: the one existing automation URL on the host uses `api/frigate/frigate-f2/`, and that id returns 200.
  - If discovery returned `[]` instead, the default URL would be tried. That URL also returns 200 internally, so the conclusion holds either way.
- **Legacy URL builder:** `_resolve_snapshot_url_and_delay` (:2033-2095) builds `/api/frigate/notifications/<id>/snapshot.jpg`, with no instance id. It works internally (200). That is the NM URL fallback, not a SNAP-1 capture.

## 2. Is an event_id captured at edge time?

Method: frigate_events from the HA recorder (`events` joined to `event_data`, 7 days), matched to the 275 `notification_log` audit rows (hazard `exterior_person`, message `[audit]`) by camera key. Sensor edges were taken from `states`.

- The recorder holds 72,708 `frigate_events` rows, latest 2026-11-09 04:46 UTC. The bus carries full `after` dicts with `id`, `label`, `camera`.
- Of 275 alerts in 7 days:
  - 194 (71%) have a Frigate person `new` event on the same camera within 120 s before the alert.
  - 14 have only a later event.
  - 67 (24%) have no Frigate event at all.
- The 67 are mostly alerts from non-Frigate sensors:
  - `rear_ptz`: 36 of 51 alerts have no Frigate event (the `_person_detected` leg).
  - `ptzcamreolinktmixpstudybporch` and `armcrestpooloverhead_smart_motion_human`: 9 alerts, zero Frigate events in the whole window.
  - Tier 1 cannot apply to these. They are always live grab.
- Edge versus bus `new` time, for the 193 alerts where both could be measured:
  - Median edge minus event: +0.01 s. Range -5.79 s to +108.8 s.
  - 75 alerts had the edge before the bus event (cache empty at the edge, so tier 1 returns `None` immediately).
  - 118 had the event first (cache populated, so tier 1 proceeds to the URL, which is where it dies).
- So for about 61% of Frigate-leg alerts the id was available and tier 1 still failed. That points at the HTTP leg, which section 4 confirms.
- Frigate's own latency: bus `new` minus `after.start_time` has median 1.72 s and p90 14.5 s over 4,294 person events. For `pool_equipment`, median is 10 s and p90 is 203 s. The edge is driven by `new`, so the best frame can come late on slow cameras. That cannot be fixed on the URA side.

## 3. Bridge automation

- `automation.frigate_mqtt_to_frigate_events_bridge_ura_snapshot_support`: state `on`, `last_triggered` 2026-11-09T04:46:01Z (REST `/api/states`). The sample was taken at about 04:59Z.
- Definition at /config/automations.yaml:6579-6594: MQTT triggers on `frigate/events` and `frigate2/events`, then fires `frigate_events` with `before`, `after`, `type`. `mode: queued`, `max: 25`.
- Payloads reaching the bus are well-formed.
- The bridge works. Its volume is 72k events per period, and the recorder run-book already records its roughly 900 rows/hr `last_triggered` churn (docs/planning/RUNBOOK_recorder_excludes.md:37).

## 4. URL probes (GET only, no auth header on the instance probes)

Event used: `1794184013.180881-ladhjn` (pool_equipment, 2026-11-09 00:27 CST).

| Probe | Result |
|---|---|
| `http://192.168.13.13:8123/api/frigate/frigate-f2/notifications/<id>/snapshot.jpg` | 200, 75,499 B, 0.057 s |
| `.../api/frigate/frigate/...` and `.../frigate2/...` | 404 (wrong instance ids) |
| `.../api/frigate/notifications/<id>/snapshot.jpg` (default) | 200, 75,499 B |
| `https://haos.phalanxmadrone.com:8123/...` (default and `frigate-f2`) from my Mac | timeout, 10 s |
| same external host from the HA host, instance URL | timeout, 6 s |
| `127.0.0.1:8123` and `192.168.13.13:8123` from the HA host | 200, about 0.04-0.05 s |

- The Frigate integration entry has `notification_proxy_enable: true` and `notification_proxy_expire_after_seconds: 0`. The notification proxy therefore allows unauthenticated requests (`custom_components/frigate/views.py:365-396`). URA's un-authed GET is fine on that axis.
- Only the hostname is bad.

## 5. Capture-failure reasons in logs

- Unknown. No capture-failure log was available.
  - `/config/home-assistant.log` is absent; only `.old`, `.1` (0 bytes) and `.fault` (0 bytes) exist.
  - `/api/error_log` returned 0 bytes.
  - `ha core logs` and journald are empty or unavailable over ssh.
  - All SNAP-1 failure branches log at DEBUG (:3730-3757 area, :3925 `_http_get_bytes`), which is likely not enabled.
- The ledger line `PerimeterSnapshot: wrote=... engine=...` is INFO and would have confirmed the engine split directly. I could not read it.
- The evidence above (all file names are live-grab shape, URL probes) stands in for it.
- Falsifier I could not run: a DEBUG log line `SNAP-1: http GET <external url> failed` from `_http_get_bytes`. Enabling DEBUG for `custom_components.universal_room_automation.perimeter_alert` for one alert would settle it. That is a state change, so I did not do it.
- Not verified: the 28 "no file" alerts. One sample row (hot_tub, 2026-11-08 12:57 CST) had no grab within 20 s, consistent with the in-flight collapse or budget path.

## 6. Sample: 9 recent alerts with a Frigate event, Frigate frame versus URA live grab

How chosen: the most recent alerts that have a matched Frigate event id and a live-grab file within 20 s, at most 2 per camera. They were not selected for being "empty". A tenth row had no grab file.

Method: Frigate frame via `GET http://192.168.13.13:8123/api/frigate/frigate-f2/notifications/<id>/snapshot.jpg`; live grab from `/media/ura/snapshots`. Both were viewed. Frigate frames carry the detection box.

| # | Camera | Frigate frame (boxed object, score) | Live grab | Reading |
|---|---|---|---|---|
| 0 | pool_equipment | box on hose and pipe on the floor, 52% | same clutter, no person | FP on static clutter |
| 1 | front_side_ptz | man with yellow bucket at the car, 82% | person at the car door | REAL; grab got him |
| 2 | utilities_ptz | tiny person on distant path, 74% | tiny figure at the same spot | REAL, small and far; grab got him |
| 3 | back_yard | tiny box at the fence line top-right, ~60% | empty lawn | no visible person; likely FP |
| 4 | back_yard | same fence-edge box, ~60% | empty lawn | no visible person; likely FP |
| 5 | g5_bullet | person in orange, top-right, far | orange figure visible | REAL, far; grab got him |
| 6 | hot_tub | box on patio chairs, 74% | no person | FP on furniture |
| 7 | pool_equipment | same hose and pipe box, 59% | no person | FP on static clutter (repeat of #0) |
| 8 | rear_ptz | tiny box on path edge, 65% | no person visible | ambiguous (tiny); possibly a distant person |

Tally: 3 clearly real, 5 detections on nothing person-like, 1 ambiguous.
- The live grab contained the person in all 3 real cases. In the 5 clutter cases the Frigate event frame also has no person, so the empty frame is correct, not late.
- Event metadata from the recorder `end` or `update` messages: `false_positive: False`, scores 0.60-0.84, `entered_zones: []` on all 9. Frigate does not flag these as false positives.
- Caveat: n=9, recent and not random. It does not support a rate. It is consistent with the 52-image visual review in docs/planning/AUDIT_perimeter_fp_street_noise_2026_11.md.

## 7. Falsification attempts

- "Event id missing at edge is the cause": refuted for about 61% of alerts. The id was on the bus first, and tier 1 still never produced a file.
- "Proxy or instance id wrong": refuted. `frigate-f2` returns 200 internally. The default URL also returns 200.
- "Bridge not firing": refuted. `last_triggered` is minutes old, and 72k bus rows are in the recorder.
- "Auth required on the proxy": refuted. Anonymous GETs return 200 internally. Options have the proxy enabled with no expiry.
- Not yet confirmed from inside the HA process: the external URL fails there too. The ssh shell shares the host network, and the same timeout appeared from two vantage points, but it is an inference.

## 8. Recommended fix (nothing applied)

- **A (small, the actual bug):** `_http_get_bytes` for tier 1 should use an internal/loopback base. Prefer `internal_url`, else `http://127.0.0.1:<port>`, not `_absolutize`. Keep `_absolutize` for URLs handed to external channels (Pushover, WhatsApp). Config-first check: setting HA `external_url` to a LAN-reachable host would also work, but it would break the external channels that need a public URL, so it is not a substitute.
- **B (design):** retry tier 1 inside the budget when the cache is empty. For example, wait up to about 1.5 s for a `frigate_events` `new` message on that camera, or read the cache again at consume time.
  - Marginal-benefit note: A alone should capture about 61% of Frigate-leg alerts (the 118 event-first alerts). B adds the remaining roughly 39%, at the cost of a delay on a security page. Do A first and measure before building B.
- **C (stale-id hazard, note for review):** `_frigate_last_event_id` stays valid for 120 s and is not cleared on `end`. Once A makes tier 1 live, a quick second walk-past on the same camera could fetch the previous event's frame. Review the TTL against `new` id changes, and prefer the id from the most recent `new`.
- **D (consequence):** the card's "D6 enforce can never fire" holds only while tier 1 fails. After A, alert images from Frigate legs would be Frigate event frames, which already carry the box the VLM gate and operator need.
- 24% of alerts have no Frigate event at all (non-Frigate sensors). Those will stay live-grab by design.

## Sources

- perimeter_alert.py:926-964, 1611, 2033-2095, 3196, 3479-3498, 3519-3640, 3721-3845, 3903-3935, 4363-4375
- const.py:2971-3022
- /config/automations.yaml:6579-6594
- /config/custom_components/frigate/views.py:313-396
- HA recorder (`/config/home-assistant_v2.db`, read-only): `events`/`event_data` for `frigate_events`, `states` for sensor edges
- URA DB (`/config/universal_room_automation/data/universal_room_automation.db`, read-only): `notification_log`
- Live REST `/api/config`, `/api/states`
- Scratch sheets: /private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/sheetA.jpg, sheetB.jpg, sheetC.jpg
