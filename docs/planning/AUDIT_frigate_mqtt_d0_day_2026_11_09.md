# AUDIT: Frigate MQTT direct, D0 daytime capture (2026-11-09 08:00-10:00 CST)

Plan: `PLANNING_frigate_mqtt_direct_2026_11.md` rev 2, D0 (read in full, plus the overnight `AUDIT_frigate_mqtt_d0_2026_11.md`). Supersedes the overnight NO-GO ("sample insufficient").
Capture: websocket `subscribe_events frigate_events` plus `mqtt/subscribe` on `frigate/#`, `frigate2/#`, `frigate2/events`, `+/events`, `frigate2/tracked_object_update`, read-only. Source: scratchpad `d0_day.json` (354,764 records, 08:00:00.58 to 10:00:00.51 CST per `d0_day.start`/`d0_day.end`), analysis scripts `d0day_an.py`, `d0day_an2.py`. Probe done 2026-11-09 ~14:10 CST.

## Verdict: GO on the D0 gate (both gate conditions met)

- (a) normalised equality: 1881/1881 = 100%, 0 near-misses, 0 unpaired either side.
- (b) TTL: max bus lag 44.3 ms, so `max(10, 3 x 0.044) = 10`; the provisional 30 s default satisfies it.
Caveats are below (queue-overflow condition not stressed; latency clock resolution).

## Gate answers

1. **Rates (`frigate2/events`, 120.0 min).** 1881 msgs = 15.7/min: `new` 133, `update` 1618, `end` 130. Peak 8 msgs in one second. Per-10-min: 17 to 392. Labels: person 1592, car 289. 13 cameras, `family_room` 1155. `frigate/events`: 0 msgs. Also `frigate2/tracked_object_update` 78 (`face` 75, `lpr` 3).
2. **`frigate/` (Frigate 1) is retained-only.** 557 msgs, all `retain_burst` (first 0.28 s of the subscription), 0 after that, over ~2 h; topics are only `state` (510), `snapshot` (46) and `available`=`online` (1, stale retained). Zero `events` or `tracked_object_update`. Supports FRIGATE-FACE-BRIDGE-DEAD-PREFIX-1. Live corroboration: the Frigate config entry (`.storage/core.config_entries`, "Frigate 2") has no `topic_prefix`/`mqtt_topic_prefix`/`mqtt_topic` key in data or options (data keys: password, url, username, validate_ssl), so `_resolve_frigate_topic_prefix` (`camera_census.py:5280-5299`) returns None and the bridge subscribes to literal `frigate/tracked_object_update` (`:5258-5259`) while `frigate2/tracked_object_update` carried 75 face messages (`{"type":"face","name":"Jaya","score":1.0,"id","camera","timestamp"}`). The INFO log line itself could not be read (`ha core logs` returns no matching line), so the subscribed topic is inferred from code plus config, not read from the log.
3. **Payload fields.** All present in 1881/1881 `after` dicts: `id`, `camera`, `label`, `sub_label`, `current_zones`, `entered_zones`, `has_snapshot`, `has_clip`, `start_time`, `end_time`, `score`, `top_score`, `frame_time`. Shapes the normaliser must respect: `sub_label` is `null` (1543) or a **list `[name, score]`** (338, e.g. `["Jaya", 0.997]`), never a plain string; `end_time` is null except on `end` (130/130 set); `current_zones` non-empty in 158 msgs (person on a zone: 36); `has_snapshot` false in 147; `snapshot` is a metadata dict, not an image; `recognized_license_plate` null in all 1881. Top-level keys `before`/`after`/`type` always present; 0 id-less messages (expect 0: met).
4. **Ownership and duplicates.** No event id occurs under two prefixes (`frigate` carries no events), so cross-prefix duplication is unexercised, not disproven. Across sources (MQTT vs bus) every one of 1881 messages reached the client MQTT-first (bus-first = 0), so under the latch MQTT owns every id, as the plan predicts. Each of 133 ids has exactly one `new`; 130 have `new..end`, 3 were still open at capture end. Max gap between messages of one id 70.5 s (p99 60.7 s), longer than the 30 s TTL; per plan rev 2 H2 that is harmless (only bus lag behind MQTT sizes the TTL). Max id lifetime 4612 s (a long-lived object).
5. **Latency.** MQTT to bus twin (both arrival times on one client clock, so skew-free): min 0.0 ms, p50 0.1 ms, p95 0.3 ms, p99 0.6 ms, **max 44.3 ms**; 0 negative. MQTT to HA entity (different topic: the Frigate integration's own `frigate2/family_room/person/active` message to `sensor.family_room_person_active_count_2` recorder `last_updated_ts`, 89 changes): p50 3 ms, p95 17 ms, max 25 ms, min -12 ms. The Mac-to-HA clock offset (+0.103 s) was estimated from `time_fired` vs arrival, so entity figures carry roughly +/-15 ms; treat as "tens of ms at most". Not measured: MQTT `new` to a URA consumer's state change (no consumer reads the events topic yet); `kitchen_panel` and `family_room_all_occupancy_2` entity pairs did not match by name/state, skipped.

## Plan D0 items 1-6 mapped

| Plan item | Result |
|---|---|
| 1 pairing and dict equality | 1881/1881 paired by `(id,type,frame_time)`, 100% dict-equal under the plan's `before`/`after`/`type` normalisation |
| 2 MQTT to bus latency | max 44.3 ms, p95 0.3 ms |
| 3 on MQTT, missing from bus | 0 (bus extras also 0); no queue overflow observed |
| 4 max per-id gap | 70.5 s (informational) |
| 5 F1 subscribe topic | topic side confirmed dead; log line unread; see answer 2 |
| 6 id-less | 0 |

## Not proven
- The automation queue `max: 25` overflow was not stressed: peak was 8 msgs/s. Item 3 = 0 is a daytime two-hour result under moderate load, not a burst test (a multi-camera storm could differ).
- `lpr` and `face` appear on `frigate2/tracked_object_update` but those are not `events`; the `sub_label` list shape is the only face signal on the events topic.

## Fixture
A candidate (not committed here) was built at `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/fixture_candidate.json`: 16 MQTT/bus pairs from 3 complete events (person on zoned camera 7 msgs, person with face `sub_label` 3 msgs, car on zoned camera 6 msgs), same `{_meta, pairs:[{mqtt_payload, bus_data}]}` shape as the committed overnight fixture plus a `case` key. Scan: 0 URLs, 0 IPv4 strings, 0 base64-like runs, 0 "token"/"password"; payloads are unmodified. It is ~104 KB (larger than the 10-20 message intent because of `path_data`/`score_history`). The probe was read-only so the committed fixture `quality/tests/fixtures/frigate_events_mqtt_live.json` remains the overnight 5-pair version until the orchestrator copies the candidate in.
