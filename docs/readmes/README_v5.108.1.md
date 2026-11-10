# v5.108.1: Frigate events straight from MQTT, and the face bridge on the live prefix

Cards: `PERIMETER-FRIGATE-MQTT-DIRECT-1`, `FRIGATE-FACE-BRIDGE-DEAD-PREFIX-1`.
Plan: `docs/planning/PLANNING_frigate_mqtt_direct_2026_11.md` rev 2 (D0 GO: `AUDIT_frigate_mqtt_d0_day_2026_11_09.md`).
Tier 2-DB (operator-elevated): three framing-disjoint reviews (A normaliser + dedup, B lifecycle/async, C per-site mutation), then live L1-L5.

## What changes

**URA no longer needs a house automation to hear Frigate.** Perimeter alerts and the exterior track linker used to get Frigate events only from the `frigate_events` bus event, which an automation in `automations.yaml` fires from `frigate2/events`. A house without that automation got no Frigate snapshots, event cache or track linking. Both now register on one `FrigateEventIngress` (`frigate_ingress.py`), which:
- listens to the `frigate_events` bus as before, and subscribes to `<prefix>/events` for every running Frigate entry;
- reads the prefix from the running Frigate integration (`hass.data["frigate"][entry_id]["config"]["mqtt"]["topic_prefix"]`), never from a literal or the config entry;
- feeds each consumer each message once. A per-event-id latch lets the first source family own the event, and drops the other family's copies while the owner was heard within 30 s. Here MQTT arrives first (D0: bus ≤ 44 ms behind), so the bus becomes the fallback;
- skips retained MQTT messages (stale on subscribe);
- keeps mqtt a soft dependency: no manifest change. It subscribes again when mqtt loads, when Frigate loads, when HA has started, and every 300 s. The add-only rule means a subscription is never dropped because Frigate is briefly unloaded.

Consumer bodies are unchanged apart from reading `data` instead of `event.data`. If the ingress fails to build, each consumer falls back to its own bus listener (today's path).

**Face bridge fixed.** The census face-name MQTT bridge read a topic prefix from the Frigate config entry. No such key exists, so it fell back to the literal `frigate`, which is retired Frigate-1 and carries only stale retained messages. The fast face latch has therefore heard nothing since August. It now registers `<prefix>/tracked_object_update` on the same ingress, so it uses the same runtime prefix (`frigate2` here) for every Frigate entry, and it skips retained messages. If the ingress is absent, it subscribes directly to each discovered prefix. There is no literal fallback in either path.

**Synthetic face legs need a non-face arrival to demote (review B-M1).** The face latch leg is now marked synthetic. When the egress producer's two-camera 0.9 holds only with a synthetic leg, the bus event still carries 0.9 and adds `identity_synthetic_corroborated: true`. Perimeter D10.5 then demotes a dual-role door alert only with a same-person non-face arrival edge within 120 s (reason `egress_synthetic+<source>`). A live two-camera 0.9 demotes as before.

**D2 warning.** "Frigate legs rose N times with ZERO frigate_events messages" now fires only when MQTT and the bus are both silent, and it names the MQTT topics.

## Knobs (all rung 1, `const.py`, read at call time)
| Knob | Default | Why |
|---|---|---|
| `FRIGATE_INGRESS_MQTT_ENABLED` | `True` | Kill switch. False = no `<prefix>/events` subscription; bus only (pre-cycle). The face topic stays subscribed. |
| `FRIGATE_INGRESS_SOURCE_LATCH_TTL_S` | `30` | Silence before the other source may take over an event id; also the failover dead time. D0 gate `max(10, 3 × 44 ms) = 10`; 30 keeps headroom for an unmeasured burst. |
| `FRIGATE_INGRESS_SOURCE_LATCH_TTL_FLOOR_S` | `10` | Clamp floor for the TTL (no disable value). |
| `FRIGATE_INGRESS_LATCH_MAX` | `2000` | Memory bound on the latch. |
| `FRIGATE_INGRESS_RECONCILE_S` | `300` | Periodic add-only prefix re-discovery; 0 = timer off. |

## Diagnostics (display only)
On the exterior open-tracks diagnostic sensor (next to `frigate_bus_by_camera`): `frigate_ingress_prefixes`, `frigate_ingress_mqtt_24h`, `frigate_ingress_bus_24h` (received per source, before dedup), `frigate_ingress_dedup_dropped`, `frigate_ingress_mqtt_bad_payload`, `frigate_ingress_mqtt_retained_skipped`, `frigate_ingress_idless`. On `sensor.universal_room_automation_persons_in_house`: `frigate_face_msg_retained_count`.

## Files
- NEW `frigate_ingress.py`: ingress, prefix discovery, normaliser, setup/teardown helpers.
- `perimeter_alert.py`, `exterior_track_linker.py`: register through `register_frigate_consumer`. Perimeter also gets the D2 WARN rewording and the diagnostics merge.
- `camera_census.py`: face bridge on the ingress, retained skip; `_resolve_frigate_topic_prefix` deleted (dead and wrong).
- `__init__.py`: ingress created before the census / perimeter / linker; torn down after them.
- `const.py`, `sensor.py` (one attribute).
- Docs: plan (build resolutions, §10 D0), `IDENTITY_FUSION_CAMERAS_MANUAL.md` §1.3 / §4.5 / §6, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` header.

## Tests
`quality/tests/test_frigate_ingress.py` (37), plus additions to `test_perimeter_fp_gates.py` (5), `test_exterior_track_linker.py` (1) and `test_frigate_face_name_bridge.py` (4). The replay tests run the D0 live fixture through bus-only and through both sources, and require identical consumer sequences and identical perimeter caches with arrival stamps excluded. 41 per-site source mutations each turn a named test red. The table is in the build report.

## Validated 2026-11-10 (restart 01:02 CST, read at 01:03-01:14 CST; house in SLEEP, so no person/face traffic)
| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Subscribe log lines for `frigate2/events` and `frigate2/tracked_object_update`, none for `frigate/*` | PENDING (log not readable) | INFO log lines are not reachable (HA system_log holds WARNING+ only; `docker logs`/`ha core logs` denied). Indirect: `frigate_ingress_prefixes = ["frigate2"]` (only the runtime prefix; no `frigate`) and `frigate_ingress_mqtt_24h` 29 -> 139 -> 142, so the `/events` subscription is live. The `tracked_object_update` subscription is unproven (see L6). |
| L2 | `mqtt_24h > 0`, `dedup_dropped > 0`, `dedup_dropped ≈ bus_24h` | PASS | 01:04: mqtt 29, bus 0, dropped 0 (bridge automation reloaded 07:02:56Z). 01:14: mqtt 139, bus 103, dedup_dropped 103 (equal); 01:15: 142 / 106 / 106. bad_payload 0, idless 0, retained_skipped 0. Double-feed absent. |
| L3 | back_yard `frigate_events_24h` / pre snapshot < 1.5 | PENDING | `frigate_bus_by_camera` is `{}` (perimeter counts only person-label events, perimeter_alert.py:960-966; none overnight). Pre snapshot (`.claude/scratch/v5108_1_pre_snapshot.txt`, truncated) held madrone_g6_entry 9, sonoffwindow 16, no back_yard row. Re-check after daytime person traffic. |
| L4 | Portability drill (disable bridge automation 15 min) | NOT RUN | Needs a state change; out of read-only scope. Bridge automation state `on`. |
| L5 | Zero ingress exceptions, 40/40 entries loaded | PASS (partial) | system_log (50 entries) has no ERROR and nothing from `frigate_ingress`/`FrigateEventIngress`; only pre-existing WARNINGs (boot sensor-unavailable holds, deprecated `async_get_device`). URA entities unavailable: 162/423 at 07:02:51Z, 27/531 at 07:03:26Z. Entry count 40/40 not checked (config_entries API not reachable). |
| L6 | Face bridge counts a face; `retained_count` small | PENDING | `persons_in_house` attrs: `frigate_face_msg_seen_count` 0, `face_count` 0, `last_latched` null, `retained_count` 0. Zero `tracked_object_update` messages in about 12 min of night traffic, so the topic subscription is neither confirmed nor refuted. Re-read after a named face. |

Other: `unlinked_events_by_camera` {"g5_bullet": 1}; one open vehicle track (car, circling) on the diagnostic, so the exterior linker is receiving MQTT-sourced events.

Proven only in-suite: load-order permutations (mqtt late, Frigate late, HA-started), reload without orphan subscriptions, teardown during an in-flight subscribe, and orphan callbacks after an MQTT entry reload.
