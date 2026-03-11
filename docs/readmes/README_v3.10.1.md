# v3.10.1 — Census v2: Event-Driven Sensor Fusion

**Standalone maintenance release.** Fixes camera census under-counting guests and over-aggressive decay. Introduces three-layer sensor fusion (cameras + WiFi VLAN + face recognition) with hold/decay stabilization and event-driven triggers.

## Problem Solved

Camera census was unable to detect guests:
- `unidentified = max(0, camera_total - ble_identified)` always yielded 0 because BLE tracks 3 family members stably while cameras only see 1-2 at any moment
- No hold period — Frigate detections last 20-30s but census polls every 30s, causing count drops between polls
- Exterior sensor flapped 20 times in 2 hours with no hold window
- No differentiation between "people seen" and "people recognized" by face recognition
- Guests in bedrooms (no cameras) were invisible

## What's New

### Three-Layer Sensor Fusion
1. **Camera layer** — Frigate person detection with face recognition freshness check (30-min window). Differentiates recognized faces from unknown persons (guest signal).
2. **WiFi VLAN layer** — Guest phones on configured SSID (e.g., "Revel") detected via OUI phone manufacturer filtering. Persistent while phone is connected — no decay. Handles multi-day guest stays and overnight bedroom scenarios.
3. **BLE layer** — Bermuda device count arrival signal. Used for event triggering, not persistence (phone MAC rotation defeats tracking).

### New Census Formula
```
unidentified = max(camera_unrecognized, wifi_guests)
total = identified_persons + held_unidentified
```
Uses the higher of camera-seen-unrecognized and WiFi-guest-floor, so guests in camera-free rooms (bedrooms) are still counted via WiFi.

### Hold/Decay Stabilization
- **Interior hold**: 15 min (configurable 1-60). Peak person count held during window, then gradual decay (-1 per 5 min) to prevent false count drops.
- **Exterior hold**: 5 min (configurable 1-30). Peak held, then instant drop after expiry.
- Hold timers exposed in config flow UI.

### Event-Driven Triggers
- `async_track_state_change_event` listeners on all Frigate/UniFi person detection entities + Bermuda BLE count
- 5-second debounce prevents stampede from multiple simultaneous detections
- Census sensors subscribe to `SIGNAL_CENSUS_UPDATED` for immediate push (no 30s poll delay)
- Bermuda listener registers unconditionally (works even if Bermuda loads after URA)

### Config Flow
4 new fields in Camera Census settings:
- **Enhanced Census (v2)** — Toggle (default: enabled)
- **Guest WiFi SSID** — Text field for guest VLAN SSID
- **Interior Hold** — 1-60 minutes (default: 15)
- **Exterior Hold** — 1-30 minutes (default: 5)

### New Sensor Attributes (persons_in_house)
- `wifi_guest_floor` — Number of guest phones on WiFi VLAN
- `camera_unrecognized` — Cameras seeing unrecognized faces
- `peak_held` — Whether count is being held above fresh camera count
- `peak_age_minutes` — How long the peak has been held
- `face_recognized_persons` — List of face-matched person IDs
- `enhanced_census` — Whether v2 is active

## Review Fixes Applied

Issues found during 3 parallel staff-engineer code reviews:

- **C1 (CRITICAL):** Fixed timezone mismatch — `datetime.now()` replaced with `dt_util.utcnow()` for correct face recognition window comparison against HA's UTC-aware `last_changed`
- **C2 (CRITICAL):** Fixed person name format inconsistency — face recognition now returns slug format (`oji_udezue`) matching BLE person_id, preventing double-counting in union
- **H1 (HIGH):** Added asyncio.Lock on `async_update_census()` to prevent concurrent state mutation from overlapping periodic + event triggers
- **H2 (HIGH):** Added face recognition freshness check to `_get_unrecognized_camera_count` — stale matches (>30 min) treated as unknown
- **H3 (HIGH):** Fixed `_apply_enhanced_property_census` total_persons invariant: `total = identified_count + held_count`
- **H4 (HIGH):** Event-triggered census failure logging raised from DEBUG to WARNING
- **H5 (HIGH):** Bermuda BLE listener registered unconditionally (handles late-loading integration)
- **H6 (HIGH):** Census sensors subscribe to `SIGNAL_CENSUS_UPDATED` for immediate push updates

## Tests

62 new tests in `quality/tests/test_census_v2.py`:
- Hold/decay mechanics (13 tests)
- Unrecognized camera count with freshness (11 tests)
- WiFi guest VLAN detection (10 tests)
- Face recognized person names (6 tests)
- Enhanced house census (6 tests)
- Enhanced property census (3 tests)
- Config toggle (5 tests)
- Edge cases (8 tests)

Total: 825 tests passing.
