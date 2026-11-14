# AUDIT: camera outage durations (sets the stream-health hold caps from data)

Read-only probe, 2026-11-14 (CST; recorder times below are UTC, CST = UTC-6). Operator: "I don't think the 4 hour has a real basis."
Did not read the HVAC/PRESENCE state-of-play docs in full (topic is camera health, not HVAC/presence ruling); read the PLANNING_camera_input_stream_health.md hold/exclude sections only.

## Method and limits
- Source: HA recorder SQLite, read-only (`ssh ha sqlite3 -readonly /config/home-assistant_v2.db`), table `states` joined to `states_meta`. The REST history API returned nothing before ~2026-11-06 20:56Z (purge boundary), so the DB was used directly. Earliest state row 2026-11-06 10:12Z, latest 2026-11-14 07:42Z. **Window = about 7.9 days.** The URA DB has no camera-health table (tables listed via `.tables`: nothing camera/stream/health/panel), so there is no longer history. Window is short; every p99 below is really "the one or two worst events".
- Outage = state `unavailable` (not `unknown`) on a `camera.*` entity. Open spans closed at the last row.
- Restart exclusion: 26 stop/start pairs from `events` (`homeassistant_stop`/`homeassistant_start`, 26 each, 11-06 20:55Z to 11-14 00:50Z, 143-420 s long). A span whose START is inside [stop-10 s, start+180 s] is dropped as a restart blip. Dropped: 392 KS panel-camera spans and 50 Frigate spans. Residual bias: a span that began just before a stop and persisted through it keeps its restart-inflated length (affects the 439-min and 39-hour spans below, both of which straddle HA restarts, so they are real upstream outages, not restart artefacts).
- Classes (registry platform + device): `ks_panel_camera` = esphome `camera.<panel>_panel_camera` on the Kiosk Satellite devices (7: study_a, kitchen, up_hallway, master, study_b, media_room, entry_way); `panel_frigate` = Frigate cameras on panels (3: `camera.study_a_panel`, `kitchen_panel`, `up_hallway_panel`; the other panels have no Frigate camera in the registry); `frigate_nvr` = the other 26 enabled Frigate-platform cameras; `protect` = unifiprotect, one channel per device (26 devices, medium channel preferred, else high), to avoid counting the same outage 3x.
- Scripts: `.claude/tmp/cam_an.py`, `.claude/tmp/cam_an2.py`; data `.claude/tmp/cam_states.txt`, `.claude/tmp/ha_restarts.txt`. Nothing else edited.

## Result 1: per class (restarts excluded; all durations in minutes)
| Class | n | p50 | p90 | p99 | max | <2 | <5 | <10 | <15 | <30 | <60 | <240 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ks_panel_camera (esphome) | 80 | 0.1 | 0.2 | 0.4 | 0.4 | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| panel_frigate (3 cams) | 30 | 0.8 | 8.7 | 1789 | 2340.5 | 80% | 87% | 90% | 90% | 90% | 93% | 93% |
| frigate_nvr (26 cams) | 375 | 0.8 | 6.0 | 438.5 | 438.5 | 81% | 87% | 94% | 94% | 94% | 94% | 94% |
| protect (26 devices) | 152 | 1.9 | 6.1 | 13.4 | 11,365 (open) | 50% | 83% | 93% | 99% | 99% | 99% | 99% |

Protect max 11,365 = `camera.g3_instant_high_resolution_channel`, unavailable the whole window (a permanently dead device, 1 span); excluding it Protect max is 13.4.
KS `*_panel_camera` is NOT the stream-health signal: during the 39-hour `up_hallway_panel` Frigate outage below, `camera.up_hallway_panel_camera` stayed `idle` throughout (rows 11-12 04:44Z to 11-13 23:59Z). The Frigate camera on the panel is the signal.

### What the Frigate spans are made of (n=405 Frigate spans, 25 start-clusters within 90 s)
- **15 fleet-wide events** (>=5 cameras unavailable together = Frigate server/MQTT/integration, not a camera): 394 spans. 14 of the 15 last <= 6.3 min (typical 0-1.3 min, three 1.3-6.3 min). One lasted **438.5 min** (2026-11-07 19:14Z = 13:14 CST, 25 cameras, spanning two HA restarts; ended 11-08 02:32Z).
- **11 isolated spans** (<5 cameras, i.e. one stream dying): p50 2.0, p90 39.0, max 2340.5; 45% <2, 73% <5, 82% <15, 91% <60.
- **Panel-Frigate isolated (5):** 5.3 (study_a 11-11 23:29Z), 4.6 (up_hallway 11-12 04:16Z), **2340.5 = 39.0 hours** (up_hallway 11-12 04:53Z to 11-13 19:53Z = 22:53 CST to 13:53 CST), 39.0 min (study_a 11-13 19:14Z, overlapped a fleet blip), 3.0 (up_hallway 11-14 07:33Z).
- **Nothing lasted between 6.3 and 39 min** in the window (gap), and nothing between 39 min and 438 min except the two upstream failures above.

## Result 2: before vs after the KS watchdog (2026-11-14 03:20Z = 21:20 CST 11-13)
Post window is only 03:20Z to 07:42Z = **4.4 h**, so no rate comparison is possible (pre = 7.5 days, post = 0.18 days). Post counts: ks_panel_camera 9 spans (max 0.4 min), panel_frigate 1 (up_hallway 3.0 min at 07:33Z, recovered by 07:36Z without a 39-hour tail), frigate_nvr 0, protect 0 non-open. Pre: ks 71, panel_frigate 29, frigate_nvr 375, protect 152. Verdict: unknown whether the watchdog changed outage length. Per the brief it cold-restarts after 2 bad checks (about 4 min); the 3.0-min post-watchdog span is consistent with it but one sample proves nothing. The 39-hour pre-watchdog outage is exactly the tail the watchdog is meant to cut.

## Result 3: review D-L4 (what do Frigate person sensors do when the camera dies)
Observed in the recorder (`camera.<panel>` unavailable vs `binary_sensor.<panel>_person_occupancy`, `sensor.<panel>_person_count`, `..._person_active_count`):
- **Per-camera stream death (Frigate server up): sensors FREEZE at their last value; they are not set off/0 and not made unavailable.** Evidence: study_a 11-11 23:29:40Z to 23:35:00Z, occupancy/count rows show no change during the span (value `off`/0 held); up_hallway 11-14 07:33:15Z to 07:36:16Z, same (off/0 held); up_hallway 11-12 04:16:38Z to 04:21:12Z, same.
- **Worst case: frozen `on`.** up_hallway: occupancy turned `on` / count 1 at 11-12 04:52:21Z; the camera went unavailable at 04:53:09Z (48 s later); occupancy then **stayed `on` with no change for 14 h 4 min** until the HA restart at 18:55Z (first change 18:56:38Z `unavailable`, then `off`), while the camera stayed unavailable another 25 h. That is the phantom-hold shape in the planning doc.
- **Frigate-wide loss (MQTT/server down): sensors go `unavailable`, but about 78 s AFTER the camera.** study_a 11-07: camera unavailable 19:14:13Z, occupancy and count `unavailable` 19:15:31Z, both back at 02:32:44Z (11-08).
- **After an HA restart the sensors re-read `off`/0** even if the camera entity is still unavailable (up_hallway 11-12 18:57:00Z `off` while the camera stayed unavailable until 11-13 19:53Z). So a restart un-freezes a frozen `on`, and a stream-dead camera then reports a believable-looking `off`.
- Conclusion: a stream-health gate keyed on `camera.<panel>` unavailable is necessary (sensor state alone gives no hint); the `unavailable` sensor case is already no-opinion, the frozen case is the one that needs the cap/release. Falsifier checked: if sensors reliably went off/unavailable with the camera, the 14-h frozen `on` row sequence would not exist; it does.

## Recommendation
Nothing in the data supports 4 hours: every outage that is a stream or server hiccup ended within 6.3 min; the next-longest were a 39 min and then two true upstream failures of 439 min and 39 h.
- **Zone hold cap `CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S` = 15 min (900 s).** Covers 100% of the 14 non-catastrophic fleet events (max 6.3) and 82% (9 of 11) of isolated stream deaths (all of those up to 5.3 min) with 2x margin; also covers the watchdog first cycle (about 4 min) plus panel boot. Because there is no outage between 6.3 and 39 min, 15, 20 and 30 min cover the same set; pick the smallest, because a frozen `on` is the failure and every extra minute of hold is a minute of phantom occupancy.
- **Census hold cap = 10 min (600 s)**, not 30. It covers 94% of Frigate fleet spans and 82% isolated; 30 min buys zero extra outages in this window. Operator can still choose 30 but the data gives it no basis either.
- **Release, do not hold, beyond the cap:** the 439-min fleet outage (Frigate/MQTT down) and the 39-h up_hallway panel stream death are real failures; past the cap these must release (zone and census) and notify. Same for `camera.g3_instant_high_resolution_channel` (Protect, dead the whole window).
- Caveats: n=11 isolated spans over 7.9 days; the cap rests on two long events and a handful of short ones. If the watchdog now keeps panel outages at about 4 min, the cap could shrink further, but there is no post-watchdog data yet (4.4 h). Re-measure after 7 days of post-watchdog data (one-shot query, not a soak).
- Knob placement (CLAUDE.md ladder): both are policy numbers an operator may tune by observation, so Number-entity or options rung; kill-switch semantics (0 = release immediately) to be documented on the knob.
