# DRAFT README — Zone and House dialog wording (slice A)

Cards: ZONE-DIALOGS-CLEANUP-1 + HOUSE-DIALOGS-CLEANUP-1 (slice A = D1, D3, D5).
Plan: `docs/planning/PLANNING_zone_house_dialog_cleanup.md`.
Branch: `feature/zone-house-wording`. Version: set at deploy (PATCH).

## What changed (wording only, no behaviour change)

**Raw-key bugs fixed** (the form showed the internal key name):
- House > Perimeter Alerting: all 9 fields now labelled (vehicle hours, AI descriptions, snapshot delay). The description now says it is about vehicles.
- House > Camera Census: `known_face_guests`, `egress_identity_failsafe_strict`, `auto_enable_person_detection` now labelled.
- Zone > Name and rooms: `zone_is_outdoor` now shows "Outdoor zone".
- House > Person Tracking: `person_data_retention_days` now labelled (string key renamed to match the schema key).

**Dead strings removed:** 6 energy fields retired in v4.2.0, the 4 retired `perimeter_alert_*` fields, the `manage_zones` form fields (it is a menu now).

**Label-style pass:** shorter labels, plain helpers of 220 characters or fewer, no version tags, no "DPM" / "RAW" / entity ids. Zone menu: "Name and rooms", "Thermostat", "Person sensors" (O3), "Weather comfort".

**Restart notices:** Global Sensors, Energy Sensors, Person Tracking and Default Notifications say "Saving briefly restarts URA." Camera Census says "Some changes here briefly restart URA." Zone Thermostat says "Zones sharing this thermostat get the same settings."

**CM menu:** "Alert noise" and "Who gets which alerts". The volume description loses "Rung-2 controls (NM Cycle A-2)" and "Fields left at defaults do not persist". The HVAC weather-preset description says "Weather comfort" instead of "DPM".

**Code:** `async_step_person_tracking` drops two unused `description_placeholders`. Nothing else.

## Not done in this slice
- D2 + D4 (Simple/Advanced markers, camera_census reorder, dead-field hiding): slice B, waits for `feature/room-trimmed-menu` (`advanced_hint`, `_adv`).
- O4 (House "Default Notifications" relabelled as room alert fallback): left for an operator decision. Only the restart notice was added.
- HVAC-VACANCY-SWEEP-KNOB-UNWIRED-1: out of scope (behaviour), needs carding.

## Tests
- New `quality/tests/test_zone_house_dialog_strings.py` (94 cases): label + helper for every rendered zone/house field in both files, no orphan field strings, no jargon, zone and CM menu labels, restart notices, CM descriptions.
- `test_dpm_cleanup_and_labels.py`: allow-list extended for the intentionally removed keys.
- Mutation drills: re-inserting "(v4.5.11)" fails `test_no_jargon_in_zone_house_strings[zone_hvac]`; restoring a `perimeter_alert_notify_service` string fails `test_zone_house_strings_have_no_orphan_field_labels[perimeter_alerting]`.

## Live validation (to fill in after restart)
- Zone Manager > any zone > Name and rooms: outdoor toggle reads "Outdoor zone".
- House > Perimeter Alerting: 9 readable labels, no raw keys.
- House > Camera Census: no raw keys; "Smarter counting" without "(v2)".
- CM > Configure: rows "Alert noise" and "Who gets which alerts".
