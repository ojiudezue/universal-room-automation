# AUDIT — HA-Side Alerting Reconciliation vs URA SecC / Perimeter / NM

**Date:** 2026-08-06 (read-only audit; no config changes made)
**Motivation:** The F1-sunset audit (`AUDIT_frigate1_sunset.md` §1b) found 14 F1
`*_person_occupancy` references in the live `automations.yaml` plus camera groups in
`packages/zone_monitoring.yaml` — an alerting layer OUTSIDE URA that the
exterior-track-linker cycle's institutional inventory (`PLANNING_exterior_track_linking.md`)
did not cover. Lens: the Writer-B pattern (`AUDIT_writer_b_removal_study.md`) — a superseded
bespoke layer running in parallel with its coordinator successor.

**Evidence base:** live `/config/automations.yaml` (8,259 lines), `packages/zone_monitoring.yaml`,
`packages/upzone_zone2_package.yaml`, `packages/back_hallway_hvac.yaml`, `groups.yaml` (empty —
camera groups are UI helpers), `scripts.yaml` (one mobile notify, no camera refs); live
enabled-state + `last_triggered` for every `automation.*` entity via template render
2026-08-07 04:41 UTC; `input_boolean.zone{1,3}_monitoring_active` both **on**.

**URA-side successors referenced:** `perimeter_alert.py` + NM (`exterior_person` hazard,
default alert window 23:00–05:00, 5-min cooldown `PERIMETER_ALERT_COOLDOWN_SECONDS`,
const.py:1165-1173; WhatsApp/iMessage channels with snapshot support,
`notification_manager.py:1608-1611`), `security.py` delegate, camera census /
`camera_resolver` cross-host corroboration, URA HVAC zone machinery + arrester,
v5.16.0 guest latch.

---

## 1. Per-automation table

Classification: **(a) DUPLICATES** a URA path · **(b) CONFLICTS/races** with URA ·
**(c) COMPLEMENTS** (URA doesn't do it) · **(d) DORMANT** (disabled / dead entities).
Timestamps are `last_triggered` (UTC) at audit time.

### automations.yaml

| Automation | Trigger surface | Class | Enabled / last_triggered | F1-sunset exposure |
|---|---|---|---|---|
| Doorbell Detection WhatsApp Alert | Protect `doorbell_lite` + `front_door_aerial` `*_person/vehicle/animal_detected` → llmvision + `whatsapp.send_message` | **(a)+(b)** duplicates URA perimeter NM exterior_person (WhatsApp + snapshot); own queue (max 10), NO cooldown → double-paging inside the 23:00–05:00 NM window | **ON**, 2026-08-07 01:39 (fires daily) | None (Protect sensors) |
| Phase 1: All Detections — Dual System (AI) | **All 14 F1 `*_person_occupancy`** + UniFi event entities → dual snapshots + llmvision + 2× WhatsApp per event | (a) full duplicate of URA perimeter alerting, now **(d)** | **OFF** since 2026-02-18 | **HIGH — sole live-config holder of the 14 F1 base person sensors + 4 F1 cameras** |
| Phase 1: Known Person — Dual System | UniFi `*_last_identified_person` (already dead in registry) + Frigate `*_last_recognized_face` incl. **3 F1 face sensors** (front_side/rear/utilities_ptz) → 2× WhatsApp | (a)/(d) — disabled; face-alert function has no URA successor yet (note for exterior-person-escalation planning) | **OFF** since 2026-02-17 | **MEDIUM — 3 F1 face sensors; several triggers already dead pre-sunset** |
| G6 Doorbell Analysis (blueprint `balloob/ai-camera-analysis`) | `binary_sensor.madrone_g6_entry_motion_2` (F2) → AI notify | (c) partial complement (AI description) but a 3rd pager on the entry path alongside Doorbell-WhatsApp + NM | **ON**, 2026-08-07 04:21 | None (F2 `_2` sensor) |
| Frigate MQTT → `frigate_events` bridge (URA snapshot support) | MQTT `frigate/events` + `frigate2/events` → HA event bus | **(c)** — URA-owned infrastructure (v5.44.0), KEEP | **ON**, firing continuously | Benign — `frigate/` leg goes silent post-sunset; leave both topics |
| Zone 1 Motion-Based HVAC Control w/ Sleep Protection | `binarygroup_camera_persondetected_zone1` + motion group → climate + notify | (a) duplicates URA HVAC zones/presence; now (d) | **OFF** since 2025-09-11 | None (Protect group) |
| Zone 2 Motion-Based HVAC Control w/ Smart Dwell | `persondetected_zone3`, `stairs_top_person_detected` → climate + notify | (a)/(d) | **OFF** since 2025-09-04 | None |
| Zone 2 Enhanced Motion-Based HVAC Controlv2 | same zone-3 camera groups | (a)/(d) | **OFF** since 2025-09-05 | None |
| Upstairs Zone Presence Tracker | `persondetected_zone3` ×3 triggers | (a) duplicates URA zone occupancy; (d) | **OFF** since 2025-10-23 | None |
| Upstairs Zone Enhanced Motion-Based HVAC Control | zone-3 groups | (a)/(d) | **OFF** since 2026-06-07 | None |
| Upstairs Zone — HVAC Arrester | climate watchdog | (a) duplicates URA arrester; (d) | **OFF** since 2026-06-08 | None |
| Back Hallway — HVAC Arrester v10 (**two copies** in yaml) | climate watchdog | (a)/(d) | both **OFF** (one never triggered) | None |
| Back Hallway — Complete HVAC Management v2 | `camera_protect_garagehallway_person_detected` + presence → climate | (a)/(d) | **OFF** since 2026-06-08 | None |
| UpZone • Tracker 2.0 / • HVAC 2.0 (`upzone_zone2_package.yaml`) | zone-3 camera groups | (a)/(d) | both **OFF** | None |
| Back Hallway — Guest Detection System v1 | mmWave presence + `back_hallway_guest_detected` → `notify.MadroneHAPushover` | (a) duplicates URA guest detection (v5.16.0 guest latch); (d) | **OFF**, never triggered | None |

### packages/zone_monitoring.yaml (ALL its automations are ON)

| Automation | Trigger surface | Class | Enabled / last_triggered | F1 exposure |
|---|---|---|---|---|
| Zone 1 Motion Event Counter | `binarygroup_camera_motion_zone1` → counter + **mobile push per event** | **(b)** live parallel pager (interior camera motion → phone, 24/7, gated only by `zone1_monitoring_active`=on) | **ON**, 2026-08-07 04:40 | None (Protect) |
| Zone 1 Person Event Counter | `binarygroup_camera_persondetected_zone1` → counter + push per event | **(b)** | **ON**, 2026-08-07 04:34 | None |
| Zone 3 Motion Event Counter | `binarygroup_camera_motion_zone3` | **(b)** | **ON**, 2026-08-07 04:28 | None |
| Zone 3 Person Event Counter | `binarygroup_camera_persondetected_zone3` | **(b)** | **ON**, 2026-08-07 04:27 | None |
| Zone 1 / Zone 3 Inactivity Alert | `sensor.zone{1,3}_minutes_since_activity` > 45 → "Consider HVAC away mode?" push | (a) duplicates URA zone-vacancy/HVAC-away logic; effectively (d) | **ON** but `last_triggered: None` (numeric_state edge never crossing while armed) | None |
| Multi-Zone Daily Summary | 22:00 daily → push | (a)-ish diagnostics duplicate (URA census/diagnostics cover activity accounting) | **ON**, fires nightly | None |
| Multi-Zone Reset Daily Counters | midnight | support for the above | **ON** | None |

The package also defines 8 template sensors, 4 counters, 2 input_booleans, 4 utility_meters —
all solely in service of the above notifications; the F1-sunset audit already confirmed they
consume Protect `*_person_detected` only and survive the sunset.

**Counts:** DUPLICATES (a): **17** (14 dormant + Doorbell-WhatsApp + inactivity/summary
overlap) · CONFLICTS live (b): **5** (Doorbell-WhatsApp double-page + 4 zone event-counter
pagers) · COMPLEMENTS (c): **2** (Frigate bridge — keep; G6 Doorbell Analysis — partial) ·
DORMANT (d): **14** automations disabled (12 HVAC/presence/guest + the 2 Phase-1 dual-system).
No automation actuates sirens; no alarm-panel/armed-state references exist anywhere in the
live automation config. Camera-person **actuation** is limited to the dormant HVAC set (climate)
— no lighting actuates on camera person sensors.

## 2. Double-paging verdict

**CONFIRMED for the front-door/garage egress path.** Three live pagers can fire on one
person at the front door: (1) URA perimeter NM `exterior_person` (WhatsApp/iMessage w/
snapshot, 23:00–05:00 window, 5-min cooldown), (2) "Doorbell Detection WhatsApp Alert"
(same WhatsApp number 14258299520, 24/7, per-event, queued max 10, no cooldown), and
(3) G6 Doorbell Analysis AI notify on the Madrone entry camera. Inside the NM alert window
this is guaranteed duplicate WhatsApp paging with no shared cooldown; outside the window the
HA-side automation is currently the *only* perimeter pager — i.e. it is both a duplicate AND
load-bearing daytime coverage. Separately, the four zone_monitoring event counters push a
mobile notification on **every** interior camera motion/person event (firing many times per
hour at audit time) — a pure legacy monitoring layer with no URA integration.

## 3. F1-sunset exposure list (automation layer)

- `Phase 1: All Detections — Dual System (AI)` — all 14 F1 `binary_sensor.<cam>_person_occupancy`
  + 4 F1 `camera.*` refs. **Disabled → sunset breaks nothing live.**
- `Phase 1: Known Person — Dual System` — `sensor.{front_side,rear,utilities}_ptz_last_recognized_face`
  (F1) + already-dead `*_last_identified_person` / `event.front_door_aerial_person`. Disabled.
- Frigate bridge `frigate/events` topic — goes silent post-sunset, harmless (F2 leg remains).
- Everything else (Doorbell-WhatsApp, zone_monitoring, groups) is Protect-sourced → survives.

**Net: no ENABLED HA automation breaks at F1 sunset.** The 14-sensor exposure flagged in the
sunset audit lives entirely in the two disabled Phase-1 automations.

## 4. Writer-B-pattern verdict

**YES — this is the Writer-B shape, twice over.**
1. The Phase-1 dual-system pair and the ~14 dormant HVAC/presence/guest automations are the
   pre-URA bespoke layer, already switched off as URA absorbed each function but never
   deleted — dead code in the live config that resurrects on an accidental toggle and (for
   Phase-1) pins the F1 entity surface.
2. The **live** parallel alerters — Doorbell-WhatsApp and the four zone_monitoring per-event
   pagers — are exactly "a superseded bespoke writer running alongside its coordinator
   successor": same channel (WhatsApp / mobile push), own cooldown-free cadence, no knowledge
   of NM's routing, dedup, or alert-hours policy.

## 5. Recommendations

1. **RETIRE (delete):** both Phase-1 dual-system automations (dormant 6 months, F1-bound —
   deleting them zeroes the automation-layer F1 exposure); the 12 dormant HVAC/presence/
   arrester/guest automations incl. the duplicated Back Hallway arrester copy and the two
   UpZone 2.0 package automations; `Back Hallway — Guest Detection System v1`.
2. **MIGRATE into NM, then retire:** `Doorbell Detection WhatsApp Alert`. Its two deltas over
   URA perimeter NM are (i) 24/7 coverage vs the 23:00–05:00 window and (ii) LLM-vision image
   description + vehicle/animal classes on the two doorbell cameras. Extend perimeter NM
   (daytime tier / per-camera alert-hours override, optional llmvision enrichment) before
   disabling — otherwise daytime front-door paging is lost. Until migrated, it stays as the
   known double-pager inside the NM window.
3. **RETIRE zone_monitoring per-event notifications now** (turn `zone{1,3}_monitoring_active`
   off, or strip the notify actions): interior camera event push-per-event is monitoring
   noise URA's census/substrate diagnostics supersede. Decide separately whether the
   counters/template sensors earn their keep; if not, retire the whole package (+ its
   counters, utility_meters, input_booleans).
4. **KEEP:** Frigate MQTT bridge (URA-owned, both topics). **KEEP-with-decision:** G6 Doorbell
   Analysis — either fold AI description into the NM migration (rec 2) and retire, or keep as
   the single entry-camera enrichment pager and dedupe against NM.
5. **Follow-up for `PLANNING_exterior_person_escalation.md`:** the Known-Person (face) alert
   function has no URA successor; if facial-recognition paging is wanted back, it belongs in
   perimeter NM, not a revived Phase-1 automation.

*Audit is read-only; no live config was modified. All retirements above are operator
decisions to execute in a separate pass.*
