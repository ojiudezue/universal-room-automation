# v3.6.32 — Census Person Sensor Resolution Fix

## Summary

Fixed a critical bug in `CameraIntegrationManager.resolve_camera_entity()` where
the entity resolution matched ALL binary sensors on a Frigate/UniFi device by
platform alone, instead of requiring person-specific entity ID suffixes. This caused
motion sensors (`_motion_2`), sound sensors (`_bark_sound`, `_speech_sound`), and
generic occupancy sensors (`_all_occupancy`) to be counted as person detections.

## Problem

The exterior census consistently reported 8-11 persons on property when the actual
count was 0. Outdoor IR motion sensors (`binary_sensor.*_motion_2`) are nearly
always ON, inflating the count. The same bug affected interior census computation
where non-person binary sensors on Frigate devices were treated as person detections.

## Root Cause

In `camera_census.py` `resolve_camera_entity()`, the matching logic used OR:

```python
# BUG: platform match alone includes ALL binary sensors on the device
if platform == CAMERA_PLATFORM_FRIGATE or bs_id.endswith("_person_occupancy"):
```

This matched every Frigate binary sensor (motion, sound, all_occupancy) not just
person-specific ones.

## Fix

Changed to suffix-first matching that requires person-specific entity ID patterns:

- `_person_occupancy` → Frigate person detection
- `_person_detected` → UniFi Protect / Reolink / Dahua person detection
- Reolink/Dahua fallback: platform match AND "person" in entity name

## Files Changed

| File | Change |
|------|--------|
| `camera_census.py` | Fixed `resolve_camera_entity()` matching logic |
| `const.py` | Version bump to 3.6.32 |

## Testing

- 686 tests pass
- Verified via Jinja template: 10 person-specific sensors on exterior cameras, all OFF = 0 count (correct)
- Previous buggy resolution included ~80 binary sensors across exterior cameras
