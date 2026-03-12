# v3.10.3 — Census WiFi Guest Detection: Shared Network Filtering

**Hotfix release.** Fixes WiFi guest over-counting on shared entertainment networks.

## Problem

v3.10.2 counted all phones matching hostname prefixes on the Revel SSID as guests. But Revel is a shared entertainment network — family iPhones, iPads, Samsung TVs, HomePods, and WiiMs all share it. This caused over-counting (13 "guests" instead of 2).

## Fix: Three-Layer Guest Filtering

WiFi guest detection now uses three filters to distinguish actual guests from resident devices on a shared SSID:

### 1. Hostname Filter (existing)
Only phone hostnames count (iPhone, Galaxy, Pixel, etc.). Excludes TVs ("Samsung"), HomePods ("HomePod-*"), WiiMs ("WiiM*"), iPads ("iPad"), and IoT devices.

### 2. Person Exclusion (new)
Device trackers associated with tracked HA person entities are excluded. If `person.oji_udezue` has `device_tracker.ojis_iphone` in its `device_trackers` attribute, that phone is recognized as family and skipped.

### 3. Recency Filter (new)
Only phones whose `last_changed` is within the last 24 hours are counted. Resident devices that have been connected for days/weeks are excluded. Long-staying guests (>24h) are still caught by the camera `unrecognized_count` in the `max(camera_unrecognized, wifi_guests)` formula.

## New Constant

- `WIFI_GUEST_RECENCY_HOURS = 24` — configurable window for temporal guest detection

## Tests

13 new WiFi guest tests added (81 census v2 tests, 844 total).
New test coverage:
- Person exclusion (single, multiple family members, source attribute fallback)
- Recency filtering (old phone excluded, recent phone counted, boundary conditions)
- Full shared network scenario (TVs + HomePods + WiiMs + iPads + family phones + guest phones → only 2 guests)
- TV wake-from-sleep (hostname filter blocks regardless of recency)
