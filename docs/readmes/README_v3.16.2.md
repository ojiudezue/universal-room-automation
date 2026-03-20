# URA v3.16.2 — WiFi Guest Phone Misidentification Fix

## Overview
Fixes persistent false-positive guest detection in census WiFi guest count. Family members' phones with separate UniFi device_tracker entities (not linked to their HA person entity) were being counted as guest phones, inflating `unidentified_count` and triggering incorrect guest mode transitions.

## Root Cause
`_get_wifi_guest_count()` excluded family phones by checking if the device_tracker entity_id was in the person entity's `device_trackers` list. But UniFi creates a separate device_tracker (e.g., `device_tracker.unifi_default_9c_b8_b4_9c_1c_52`) that isn't listed in the person entity — only the Companion App tracker is. The same physical phone was counted as both a family member AND a guest.

## Fix
Added two new exclusion layers to `_get_wifi_guest_count()`:

### Layer 1: Device Registry Expansion
For each person-linked tracker, looks up the HA device_id in the entity registry, then finds ALL sibling device_tracker entities on that device. If HA has merged the Companion App and UniFi devices (common when they share a WiFi MAC), the UniFi tracker is automatically discovered and excluded.

### Layer 2: MAC Cross-Reference
Collects MAC addresses from all family tracker entities that expose them. When scanning WiFi devices, checks if the candidate's MAC matches any family MAC. Catches cases where HA hasn't merged the devices but the MAC is visible.

## Impact
- `wifi_guest_floor` was persistently 1+ even with no guests, inflating `unidentified_count`
- Combined with v3.16.1 ARRIVING→GUEST fix, this resolves the full chain: bad guest count → bad state inference → stuck house state

## Changes
- `camera_census.py`: Device registry sibling expansion + MAC cross-reference in `_get_wifi_guest_count()`
- `quality/tests/test_census_v2.py`: 4 regression tests (sibling exclusion, MAC exclusion, case insensitivity, real guests still counted)

## Tests
1,116 passed (4 new), 16 pre-existing DB test failures (unrelated)
