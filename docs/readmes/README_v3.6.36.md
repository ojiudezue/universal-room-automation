# v3.6.36 — Fix BaseCoordinator device_info identifier mismatch

## Summary

Fixed device identifier word order in `BaseCoordinator.device_info` to match the
convention used by all sensor/binary_sensor platform code.

## Problem

`base.py` generated identifiers as `"coordinator_{id}"` (e.g., `"coordinator_safety"`),
but every sensor helper across all coordinators uses `"{id}_coordinator"` (e.g.,
`"safety_coordinator"`). If any future code called `coordinator.device_info`, it would
create an orphan device separate from the one sensors are grouped under.

Affected: Presence, Safety, Security, Music Following (all inherit from BaseCoordinator).
Not affected: Coordinator Manager and Notification Manager (override with their own matching identifiers).

## Fix

Changed `base.py` line 202 from `f"coordinator_{self.coordinator_id}"` to
`f"{self.coordinator_id}_coordinator"`.

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/base.py` | Device identifier word order fix |
| `quality/tests/test_domain_coordinators.py` | Updated test assertion to match |
