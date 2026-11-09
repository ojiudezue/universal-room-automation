# AUDIT: Frigate MQTT direct, D0 probe (run 2026-11-09 00:15-00:40 CDT)

Plan: PLANNING_frigate_mqtt_direct_2026_11.md rev 2, D0. Read-only websocket capture (mqtt/subscribe + subscribe_events, HA token from keychain, no broker creds, no publishes). Scripts: scratchpad d0_capture.py / d0_analyze.py. Fixture: quality/tests/fixtures/frigate_events_mqtt_live.json.

## Verdict: NO-GO on the gate as written (sample insufficient), no contradicting evidence

Only 5 events messages (one car event id) occurred in 25 min overnight. Equality and lag are consistent with the plan but statistically near-empty; no person on a zoned camera, no burst.

## Results
1. Topic: Frigate2 events are on `frigate2/events` (5 msgs; also seen via `+/events`, same 5). Nothing arrived on `frigate/events` (subscribed explicitly and via `+/events`) in the window. `frigate2/tracked_object_update` carried 9 msgs, all `type: lpr` (license-plate), none face. Nothing on `frigate/tracked_object_update`. So the dead-prefix card is SUPPORTED for the topic side (frigate/* silent, frigate2/* live); the actual subscribe topic (INFO line "frigate-face bridge: subscribed to %s") could NOT be read: `ha core logs` returned nothing, journalctl absent on ha host, docker denied. Not confirmed from the log; code at camera_census.py:5258-5259 falls back to `frigate` when the resolver returns falsy. Also no face-type message seen, so face traffic during the window is unproven either way.
2. Exact match: 5/5 normalised MQTT messages (plan mapping) == bus twin as dicts. 0 near-misses, 0 unmatched, 0 bad payloads, 0 bus extras.
3. Bus lag behind MQTT: both arrived in the same websocket read tick, <1 ms apart for all 5 (p50/p95/max all ~0; resolution limited to my client clock). Max <1 ms. TTL gate max(10, 3x<1ms)=10; provisional 30 satisfies it, but only on an idle system.
4. Id-less messages: 0 of 5.
5. Queue drops (max 25): none observed; peak 2 MQTT msgs/sec. The condition was never stressed, so this is unmeasured, not disproven.

## Gap to close before treating gate as met
Re-run during daytime/busy traffic (person on a zoned camera, multiple cameras) for 30+ min; the capture script is reusable (`d0_capture.py <secs> <out.json>`, then `d0_analyze.py`). The committed fixture has no person sample and no new/update/end spread beyond one id (plan asked 10-20 msgs).
