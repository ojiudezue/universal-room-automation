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

## Live validation (prospective; replace with a `Validated <date>` table after restart)
- **L1:** the log shows `FrigateEventIngress: subscribed frigate2/events` and `... subscribed frigate2/tracked_object_update` once per boot. No `frigate/events` or `frigate/tracked_object_update` subscription appears.
- **L2:** within an hour the exterior open-tracks sensor shows `frigate_ingress_mqtt_24h > 0` and `frigate_ingress_dedup_dropped > 0`, with `dedup_dropped ≈ bus_24h`. `dedup_dropped == 0` while `bus_24h > 0` means double-feed (INV-1 broken).
- **L3:** `frigate_events_24h` for back_yard, divided by the pre-deploy snapshot, is below 1.5. Take the snapshot of `frigate_bus_by_camera` before the restart.
- **L4 (portability drill, reversible):** disable the `frigate_events` bridge automation for 15 min. Perimeter alerts still carry Frigate snapshots, D2 records keep updating, `bus_24h` stops rising, and no WARN appears. Re-enable the automation afterwards.
- **L5:** an hour of log grep shows zero `FrigateEventIngress` exceptions, and 40/40 entries are loaded.
- **L6 (face bridge):** after the first named face, `sensor.universal_room_automation_persons_in_house` shows `frigate_face_msg_face_count > 0` and a non-null `frigate_face_last_latched`. Before this release the bridge never counted a face. `frigate_face_msg_retained_count` is small: 0, or the retained replay at boot.

Proven only in-suite: load-order permutations (mqtt late, Frigate late, HA-started), reload without orphan subscriptions, teardown during an in-flight subscribe, and orphan callbacks after an MQTT entry reload.
