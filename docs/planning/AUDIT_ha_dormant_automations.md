# AUDIT — HA dormant automations (CONSOL-1 §D0.5)

Date: 2026-08-11.
Source: `/Users/okosisi/ha-config/automations.yaml` (Samba mount) +
recorder DB `/homeassistant/home-assistant_v2.db` on live HA (SSH).
Gates: CONSOL-1 §D7 delete PR — a missing entry here → do NOT delete.

## Method

For each automation entity in `states_meta`, we read the MOST RECENT
state row (`s.state ∈ {"on","off"}`). An automation with `state = "off"`
is disabled at the entity level and cannot fire (Home Assistant sets the
entity `off` when the user turns the automation off). The plan's
30-day-last_triggered exclusion is therefore moot for disabled
automations — they physically cannot have triggered while off.

`last_triggered` is NOT extracted into `state_attributes.shared_attrs`
in this HA version (the `shared_attrs` blob carries only
`friendly_name` — verified against
`automation.doorbell_detection_whatsapp_alert`), so we fall back to
`state = off` AND the yaml body being intact as the dormant criterion.
Where an automation is currently `on` but plan §5 H5 flagged it as
dormant, we EXCLUDE it from the delete set here (defensive).

## The 12 H5 dormant automations (HVAC / presence / arrester / guest)

All 12 have `state = "off"` in the live recorder (verified 2026-08-11).
The yaml bodies remain intact in `automations.yaml`. None can fire.

| # | id | alias | category | state | Delete? |
|---|---|---|---|---|---|
| 1 | 1750918079582 | Zone 1 Motion-Based HVAC Control with Sleep Protection | HVAC | off | YES |
| 2 | 1750956584750 | Zone 2 Motion-Based HVAC Control with Smart Dwell Detection | HVAC | off | YES |
| 3 | 1756948521652 | Zone 2 Enhanced Motion-Based HVAC Controlv2 | HVAC | off | YES |
| 4 | 1757048728795 | Upstairs Zone Presence Tracker | presence | off | YES |
| 5 | 1757048975329 | Upstairs Zone Enhanced Motion-Based HVAC Control | HVAC | off | YES |
| 6 | 1757819142634 | Back Hallway - HVAC Arrester v10 (id A) | arrester | off | YES |
| 7 | 1757820899382 | Back Hallway - Complete HVAC Management v2 | HVAC | off | YES |
| 8 | 1757826206465 | Upstairs Zone - HVAC Arrester | arrester | off | YES |
| 9 | 1757888743591 | Back Hallway - HVAC Arrester v10 (id B — duplicate) | arrester | off | YES |
| 10 | (upzone_hvac_2_0_zone_2 in DB — id in yaml under packages) | Upzone HVAC 2.0 zone 2 | HVAC | off | YES (package file, see below) |
| 11 | (upzone_tracker_2_0_zone_2 in DB — id in yaml under packages) | Upzone Tracker 2.0 zone 2 | presence | off | YES (package file) |
| 12 | 1760930812814 | Back Hallway - Guest Detection System v1 | guest | off | YES |

Notes:
- Items 10 and 11 (`automation.upzone_hvac_2_0_zone_2`,
  `automation.upzone_tracker_2_0_zone_2`) originate from
  `packages/upzone_zone2_package.yaml`, not the top-level
  `automations.yaml`. Plan §D7 already names that package file for
  deletion; the entities disappear when the package file is removed.
- The double Back Hallway HVAC arrester (items 6 and 9) is a v10
  alias collision — both share the friendly alias but have distinct
  ids (`1757819142634` and `1757888743591`). Delete both; the third
  arrester entity `back_hallway_hvac_arrester2` (item — not counted;
  see below) is also `off` and should be captured by a broader
  Back-Hallway sweep (`packages/back_hallway_hvac.yaml`, named in
  plan §D7).

## Non-dormant flagged in nearby yaml (EXCLUDE from delete)

None of the H5 dormant candidates are currently `on`. No exclusions.

## Related out-of-H5 that are also `off` but out of scope

The recorder also shows the following automations `off`; they are OUT
of the H5 scope (CCA, adaptive-lighting, laundry, closet, guest room
child v1, etc.) and MUST NOT be swept in the D7 delete PR unless
independently listed:

game_room_cca, living_room_unmanaged_blinds_cca, study_b_cca,
jaya_room_cca, study_a_cca, kitchen_plugs_nighttime_energy_saving,
master_bath_toilet_closet_adaptive_lighting,
bond_pro_poe_port_auto_offline_power_cycle,
master_toilet_closet_integrated,
powder_plug_in_adaptive_lighting,
hourly_power_cycle_powerview_3_hubs_at_15_minutes_past_the_hour,
breakfast_blinds_cca, front_door_auto_relock_test,
master_bath_vanity_leds_adaptive_on_off,
master_bath_lights_off_after_no_occupancy,
master_closet_night_light_and_light_turn_off_automation,
master_closet_smart_light_control_robust,
office_leave_automation_2, office_arrive_automation_2,
living_room_smart_climate_and_light_control,
master_bedroom_light_energy_management,
master_bedroom_energy_lights_management_manual_lights,
landscape_lighting_control_2_with_retry_logic,
complete_outdoor_lighting_control_1,
smart_laundry_room_light_control, smart_laundry_room_control_v2,
jaya_s_room_automation_v1, upstairs_guest_room_automation,
down_guest_room_closet_automation,
butler_pantry_automation_v3_2_1,
master_bath_integrated_lighting_humidity_control,
phase_1_all_detections_dual_system,
phase_1_known_person_dual_system, back_hallway_hvac_arrester2.

`phase_1_all_detections_dual_system` and
`phase_1_known_person_dual_system` are H3/H4 (already in the D7 set).

## D0.4 — Doorbell live-side hotfix (OPERATOR-GATED)

Not executed. Per task: "do NOT touch the operator's doorbell
automation." Current live state (from D0 probe, unchanged as of this
audit): `automation.doorbell_detection_whatsapp_alert` = `on`,
llmvision service uses provider `01KHB0EV5AP8ANWQ7RWT30M2CC`
(gpt-5-mini default) with `max_tokens: 300` → silently returns empty
`response_text` on every call (reasoning-model tokens consume the
completion budget).

Impact on P2 parity: message-body enrichment quality cannot be
measured live against the doorbell automation as-is. Recommendation
for parity ledger: P2 measured against "last-known-good" gpt-4o-mini
enrichment produced by the URA adapter itself (D3), OR against a
manual side-by-side using a targeted operator hotfix (one-line
`max_tokens: 1500` OR add `model: gpt-4o-mini`). Documented; not
built.
