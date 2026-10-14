# AUDIT — Study A Wi-Fi CSI motion sensor (ESPectre, read-only)

**Date:** 2026-10-14. Read-only investigation, no HA config changed.

## Device review

Device: **"ESPectre Test"** (HA device_id `ea145af9dbb30c467cd586864761f816`), ESPHome 2026.9.1,
firmware `espectre-test` by manufacturer `oji`, MAC `54:32:04:0b:4d:7c`. Firmware project is
**ESPectre** (`github.com/francescopace/espectre — verified 2026-10-14`, GPLv3) — a Wi-Fi CSI motion-sensing SDK with an
ESPHome frontend.

**Critical finding: the device carries NO area assignment.** `area_id` is `null` on both the
device and every one of its 26 entities. Its name — "ESPectre Test" — is still the factory/test
name, not renamed to Study A. It is physically in Study A (per the task) but **not registered
there in HA**, and nothing in its entity naming ties it to the room.

**Entities (26 total):** `binary_sensor.espectre_test_motion_detected` (device_class `motion`,
the primary output), `binary_sensor.espectre_test_calibration_active`,
`sensor.espectre_test_movement_score`, 9 `CSI_*_rate` diagnostic sensors (accepted/admitted/
callback/filtered/missing_slot/excess/stale/out_of_order, pkt/s or slot/s),
`sensor.espectre_test_csi_temporal_occupancy` (0–100, currently 66.0), `sensor.espectre_test_
generator_rate`, `sensor.espectre_test_wifi_channel` (= 1), `sensor.espectre_test_wifi_rssi`
(= -60 dBm), `update.espectre_test_firmware` (2026.9.1, up to date), `switch.espectre_test_
sensing_enabled` (on).

**Tunables exposed (all live, all currently set):**
- `number.espectre_test_threshold` = 0.5 (range 0–1, step 0.01)
- `number.espectre_test_motion_on_hits` = 4, `number.espectre_test_motion_off_hits` = 3 (debounce hit-counts, range 1–20)
- `select.espectre_test_detection_profile` = `high_accuracy` (other option: `lightweight`)
- `select.espectre_test_csi_traffic_source` = `ping` (other options: `dns`, `dns_tcp`, `external`) — it is actively pinging to generate CSI-bearing traffic, not sniffing ambient frames
- `button.espectre_test_recalibrate`, `button.espectre_test_refresh_diagnostics`

**History (recorder, ~25h since install, 2026-10-13 00:16 → 2026-10-14 01:20):** the first ~8
hours were a rolling `unknown`/`unavailable` flap (18 unavailable + 13 unknown events) while the
device settled — consistent with calibration/traffic-generator warm-up, not a wiring fault.
After 08:03 it stabilized to real `on`/`off`: **118 on-edges / 124 off-edges over the following
~17.3h window ≈ 6.8 on-transitions/hour**, average on-dwell **≈31 s**, duty cycle **≈5.8% on-time**.
This is rapid-blip motion behavior, not sustained holds.

**Comparison vs Study A's existing occupancy sensors:** Study A's only presence witness is a
Hobeian ZG-204ZK 24 GHz presence radar (`binary_sensor.study_a_presence`, "Study A Sensor
Presence", device_class `occupancy`) — a confirmed presence-class sensor per
`SENSOR_FLEET_CLASSES.md`. Over the common ~16.4h window (987 1-min samples), the CSI motion bit
agreed with the radar only **61.3%** of the time; in **371/987 samples (37.6%)** the CSI sensor
read OFF while the radar read ON (room occupied, person still — radar holds, CSI drops); only 11
samples showed the reverse. This is exactly the motion-class signature (drops a still person) and
is the dominant disagreement direction — not noise in both directions.

Study A also has a do-not-use InvisOutlet occupancy entity (`binary_sensor.study_a_invisoutlet_
study_a_occupancy`, operator-ruled unreliable 2026-10-11) and `binary_sensor.study_a_occupied`
(URA's computed room state, which already reflects the radar).

**Wi-Fi link:** `sensor.espectre_test_wifi_rssi` = -60 dBm, `sensor.espectre_test_wifi_channel` =
1 — stable link, nothing anomalous. CSI accepted-rate ≈99.6 pkt/s, admitted-rate ≈66 pkt/s
(diagnostic-only, no alarms).

## Class verdict — TODAY

**Motion-class, not presence-class**, by capability (per `SENSOR_FLEET_CLASSES.md`'s rule: class
by "holds a still person," never by name/hope). Evidence: 31 s average hold, 5.8% duty cycle, and
37.6%-of-samples disagreement with the confirmed presence radar in exactly the direction a
motion-only sensor would produce (drops still occupancy the radar correctly holds). It is wired as
a bare ESPHome `device_class: motion` binary_sensor — HA itself classifies it as motion.

## Config-entries check

Study A's URA room entry (`01KAAHJG9BHAP2VDTEYWDWZTA7`) options:
```
motion_sensors    = []
presence_sensors  = ['binary_sensor.mmwave_zigbee_studya_presence']   # the ZK radar
occupancy_sensors = []
```
**The CSI entity is not wired into Study A's URA room config anywhere** (not in
`motion_sensors`, `presence_sensors`, or `occupancy_sensors`). Confirmed by direct read of
`core.config_entries` (Samba mount reachable, no SSH fallback needed). Even if it were added,
`SENSOR_FLEET_CLASSES.md` Rule 3 (class by capability) would require filing it under
`motion_sensors`, and the `sensor_capability.py` override (`CONF_SENSOR_CAPABILITIES`) would need
an explicit entry since ESPHome devices aren't in `FAMILY_BY_MODEL_ID`.

## Gaps vs becoming presence-class

1. No still/breathing-detection firmware feature in the installed 2026.9.1 build — only a
   binary motion classifier (threshold + hit-count debounce) is exposed.
2. No area assignment — can't even be offered as a room sensor via the options-flow area
   picker until registered in Study A.
3. No ground-truth validation run (recalibration logged on 2026-10-13 at 08:0x but no documented
   before/after false-hold measurement, unlike the operator's 2026-10-11 Study A ZK radar
   re-tune, which had one).
4. 8-hour post-flash settle/flap period — needs characterizing before trusting first-boot
   behavior in any automation.

## Honest outlook — WiFi CSI still-presence

The physical principle: CSI captures per-subcarrier amplitude/phase of the multipath wireless
channel; human movement perturbs multipath and shows up as CSI variance, so motion sensing is
well-established on commodity ESP32 hardware (survey:
[WiFi Sensing with Channel State Information: A Survey](https://dl.acm.org/doi/pdf/10.1145/3310194)).
Still/breathing detection relies on the much weaker 0.2–0.5 Hz chest-wall modulation riding on top
of that noise floor — research prototypes (e.g. the RuView ESP32 "WiFi DensePose" project, and
[UNVERIFIED — fork not checked by orchestrator] PeterkoCZ91's `esphome-wifi-csi` fork of ESPectre, which explicitly adds breathing-rate detection
via multi-node ML fusion) demonstrate it is *possible*, but typically need either multiple
synchronized nodes, dedicated fixed transmitters, or heavier ML than a single ESP32 + ping-traffic
rig runs today. ESPectre's own public roadmap/`LITERATURE.md` and project description position it
as a motion detector with a research track toward more, not a shipped still-presence feature in
the mainline firmware. The installed firmware here (2026.9.1) exposes no breathing/stillness
tunables — only threshold + hit-count motion debounce — consistent with "motion-only, today."

Known CSI failure modes documented in the literature and this house's own fan-noise work: HVAC/fan
airflow and channel/power-control changes are explicitly named failure sources (search results
above; URA's own measured ZK/ZX fan-susceptibility data in `SENSOR_FLEET_CLASSES.md` shows even
*presence-class* radar is fan-susceptible — CSI, being even more sensitive to multipath, should be
assumed at least as vulnerable, pending measurement). Furniture rearrangement changes the
multipath map and typically needs recalibration; 2.4 GHz congestion and AP channel changes degrade
accuracy; a single-node self-ping design (as configured here) lacks the fixed independent
transmitter that most research still-detection setups use.

**Versus mmWave presence radar (ZK/ZX, URA's current presence-class fleet):** mmWave radar is a
mature, purpose-built RF sensor with dedicated hardware doing Doppler/micro-motion detection —
it already holds still people in this house (ZK/ZX measured). CSI repurposes a communication
radio for sensing as a side effect, which is why it is cheaper (a $5-10 ESP32 vs. a $15-25
Zigbee radar) and avoids a dedicated RF sensing device, but trades away purpose-built sensitivity.
Privacy profile is similar (neither is a camera); coverage is comparable (single-room, RF-based).
On the current evidence, mmWave remains the better buy for presence; CSI is cheaper for coarse
motion and worth tracking as the OSS ecosystem (ESPectre and its forks) matures toward
still-detection.

## Recommended next steps

1. **Do not wire the CSI entity into Study A's URA config yet.** If/when it is, file it under
   `motion_sensors` (per capability, not under `presence_sensors`) and register the device to the
   Study A area first.
2. **Run a short, cheap A/B measurement** (per `feedback_measure_before_build`): co-log the CSI
   motion bit against the ZK radar for a full week including fan-on/fan-off and furniture-static
   periods, before any firmware/config tuning — the 25h sample here already shows the drop-while-
   occupied signature but a longer window would nail down fan-interference specifically.
3. **Track ESPectre upstream + the `PeterkoCZ91/esphome-wifi-csi` breathing-rate fork** as the
   revival trigger for a presence-class reclassification — do not build or test still-detection
   logic until that firmware ships a documented breathing/stillness feature.
4. **Assign the device to the Study A area in HA** (cosmetic/registry hygiene; read-only here, so
   not done) so it at least becomes discoverable in the options-flow entity picker for future
   consideration.
5. **No action needed on URA code or config today** — config-first check confirms there is
   nothing to "turn on": the entity isn't referenced anywhere in Study A's room options.
