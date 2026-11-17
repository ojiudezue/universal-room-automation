# DRAFT: HOUSE-AVG-SENSORS-1 (house-average indoor temperature and humidity)

Status: built on branch `feat/house-avg-sensors` and waiting for review. Not deployed. Rename to `README_v<version>.md` when it ships.

## What changed

Two new whole-house sensors on the "Universal Room Automation" (Whole House) device:

| Entity (expected id) | unique_id | Unit | Device class |
|---|---|---|---|
| `sensor.universal_room_automation_house_avg_temperature` | `universal_room_automation_house_avg_temperature` | °F | temperature, measurement |
| `sensor.universal_room_automation_house_avg_humidity` | `universal_room_automation_house_avg_humidity` | % | humidity, measurement |

Confirm the actual entity ids in the registry after the restart. The slug comes from the device name plus the entity name.

Each sensor averages room readings and leaves out:
- **infrastructure rooms** (room type "Infrastructure (Always-On Equipment)", or the room's infrastructure switch is on), and
- **outdoor rooms**, meaning rooms whose zone has "Outdoor zone" turned on.

Classification comes from `room_classification.get_room_classification`, the same accessor the room classification attribute uses. Rooms are never picked by name.

Attributes (display only): `rooms_included` (rooms that supplied a reading) and `rooms_excluded` (names of the rooms left out).

The existing unfiltered getters `_get_house_avg_temp` / `_get_house_avg_humidity` are unchanged, so Temp Delta Outside, Humidity Delta Outside, HVAC Direction and the DB snapshot behave as before.

## Operator config needed (no code)

The live config was read on 2026-11-17. **AV Closet** is already `infrastructure`, so it is excluded. **Study A Closet** is `closet`, the same type as the clothing closets, so it is still included. To exclude it, set Study A Closet's room type to "Infrastructure (Always-On Equipment)" in its options, or turn on its infrastructure switch. Infrastructure also changes that room's other behaviour (always-on equipment semantics and its menu), so check that this is what you want. **Patio** is in the zone "Outside" (outdoor), so it is excluded. Garage A and Garage B (`garage`) are still included. If they should be left out, that is a follow-up decision.

## Post-deploy steps (attended session / operator, not the build)

1. Check that both entities exist and have numeric states.
2. Point the v8 dashboard weather card at the new entity ids instead of `sensor.house_indoor_temperature` / `sensor.house_indoor_humidity`.
3. After the card has been moved, delete the two template helpers:
   - `01M6SKV8XWBQ255247672EM8QZ`
   - `01M6SKV9GS5E8M0XF89K79RWHH`

   Before deleting, grep the dashboards and automations for other consumers of those helpers.

## Live acceptance criteria

- **Live:** `sensor.universal_room_automation_house_avg_temperature` is numeric, and `rooms_excluded` contains `AV Closet` and `Patio` (plus `Study A Closet` if it was reclassified).
- **Live:** the humidity sensor has the same `rooms_excluded` list.
- **Live (discriminating):** the new temperature differs from the `house_avg_temp` attribute on Temp Delta Outside whenever AV Closet or Patio reads differently from the indoor mean. Under the unfiltered failure the two values would be identical.
- **Live:** `rooms_included` equals the number of non-excluded rooms that have a temperature reading.
- **Live:** no errors from `aggregation` in the log after the restart.

## Tests

`quality/tests/test_house_avg_sensors.py` (10 tests). Each exclusion conjunct, the whole filter and both registrations were mutation-drilled RED.
