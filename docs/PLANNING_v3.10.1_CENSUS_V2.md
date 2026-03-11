# PLANNING v3.10.1 — Census v2: Event-Driven Sensor Fusion

**Version:** v3.10.1
**Date:** 2026-03-11
**Status:** Planning
**Type:** Standalone maintenance release (separate from AI Automation v3.10.0 cycle)
**Parent plans:** None. AI Automation cycle (M2: coordinator signal triggers) resumes at v3.10.2 after this ships.
**Estimated effort:** ~8 hours

---

## OVERVIEW

The camera census currently polls every 30s from raw camera binary sensor states. Frigate person_occupancy sensors flip on/off within 20-30 seconds, so the census often misses detections entirely. When it catches them, the count decays instantly on the next poll cycle.

**Observed failure modes:**
- `persons_in_house` briefly hit 4 (caught a guest!), then dropped to 3 after 60 seconds
- Exterior sensor flapped 0→1→0→1→2→1→0 twenty times in 2 hours with someone by the pool
- `unidentified_count` is always 0 because `max(0, camera_total - identified_count)` requires cameras to see more people than BLE identifies — mathematically impossible when BLE tracks 3 and cameras see 1-2

**Root causes:**
1. No hold/decay — count evaporates instantly when camera stops detecting
2. Wrong formula — comparing point-in-time camera snapshot vs always-on BLE tracking
3. Polling-only — 30s poll misses 20s detection windows
4. No guest signal — WiFi VLAN devices and Frigate face recognition unused

## CAMERA ARCHITECTURE

Same physical cameras feed multiple AI stacks:

```
Physical cameras → Frigate NVR    → person_count, person_active_count, face_recognition
                → UniFi Protect   → person_detected (binary + event_score confidence)
                → Reolink NVR     → own detection (study B porch PTZ)
                → Armcrest/Dahua  → basic motion only (pool experiment)
```

Cross-validation compares two AI models analyzing the same video feed. Never sum counts across stacks (would double-count). Frigate is primary (numeric count + face ID), UniFi confirms.

---

## DESIGN: THREE-LAYER ARCHITECTURE

### Layer 1: Event-Driven Triggers

Instead of only polling every 30s, register `async_track_state_change` listeners:

| Signal | Entity Pattern | Trigger | Purpose |
|--------|---------------|---------|---------|
| Person detected | `binary_sensor.*_person_occupancy` off→on | Immediate census | Camera sees someone |
| Face recognized | `sensor.frigate_*_last_camera` value change | Immediate census | Frigate identifies WHO |
| New BLE device | `sensor.bermuda_global_total_device_count` increment | Immediate census | Never-before-seen device |
| WiFi connects | `device_tracker.unifi_*` not_home→home | Immediate census | Device joins network |
| BLE phone arrives | `device_tracker.*_bermuda_tracker` not_home→home | Immediate census | Known person arrives |

The 30s baseline poll remains as fallback. Event listeners add immediate reactivity.

**Debouncing:** Multiple detection events within 5s trigger only one census recalculation (avoid stampede when person walks past 3 cameras).

### Layer 2: Person Classification (replaces current formula)

**Current (broken):**
```python
unidentified = max(0, camera_total - len(ble_persons))  # always 0
```

**New — separate "recognized" from "seen":**

```python
# RECOGNIZED: Frigate face-matched within last 30 min + BLE tracked persons
recognized_by_face = {
    person for person in known_persons
    if sensor.frigate_{person}_last_camera != "Unknown"
    and last_changed within 30 min
}
recognized = recognized_by_face | set(ble_home_persons)

# SEEN BUT UNRECOGNIZED: cameras detecting persons whose face is unknown
unrecognized_camera_detections = sum(
    person_count for camera in interior_cameras
    if camera.person_count > 0
    and camera.last_recognized_face in ("Unknown", "None", "no_match", "")
    and no recognized person's last_camera == this camera
)

# WIFI GUEST FLOOR: phones on guest VLAN (persistent for multi-day stays)
wifi_guests = count(
    device_trackers where state=home
    AND essid == guest_vlan_ssid  # "Revel" / configurable
    AND oui in PHONE_MANUFACTURERS  # Apple, Samsung, OnePlus, Google, etc.
)

# FINAL COUNT
identified = len(recognized)
unidentified = max(unrecognized_camera_detections, wifi_guests)
total = identified + unidentified
```

**Key insight:** WiFi guest floor has NO decay. Phone on guest VLAN = guest is here. Phone disconnects = guest left. This naturally handles multi-day stays — the phone IS the persistence signal.

**Returning guests:** A device that was seen last week and reconnects to the guest VLAN is immediately counted. No "new device" requirement — any device that "lights up" (not_home → home) on the guest VLAN counts as a present guest.

**Guests in camera-free rooms (bedrooms, bathrooms):** Interior cameras are only in shared spaces (playroom, family room, hallway, foyer, staircase). A guest napping 4 hours in a guest bedroom or sleeping overnight is invisible to cameras. The WiFi guest floor is the ONLY signal that persists through these extended stays. `unidentified = max(camera_unrecognized, wifi_guests)` ensures the WiFi floor maintains the count even with zero camera activity.

### BLE Role for Guests

BLE plays a **supplementary arrival signal** role, not a persistence role:

**What BLE provides:**
- `bermuda_global_total_device_count` increment = brand new BLE device first seen (guest's phone broadcasting). Triggers immediate census recalculation.
- Temporal correlation: new BLE device + camera unrecognized person within ±60s = high confidence visitor arrival.

**What BLE cannot provide:**
- Room-level tracking for guest phones — modern phones use rotating MAC addresses, defeating persistent BLE identity.
- Persistent guest count — unlike WiFi (stable DHCP lease per SSID), BLE MACs rotate every ~15 min. A guest phone looks like a new device every rotation.
- Returning guest recognition via BLE — same guest's phone generates a new random MAC each visit.

**Signal hierarchy for guest detection:**
1. **WiFi guest VLAN** — primary persistence signal (stable, no rotation, multi-day)
2. **Frigate face recognition** — "Unknown" face = guest on camera (point-in-time, needs hold/decay)
3. **BLE device count** — arrival event boost only (corroborates camera detection, not persistent)

**Visitors who never connect to WiFi** (delivery person, neighbor): Detected by camera + face "Unknown" only. BLE total_device_count increment may corroborate. Hold/decay provides 15-min persistence. These visitors have no WiFi or BLE persistence — camera hold is the only anchor.

### Layer 3: Hold/Decay

Camera-based detections get a hold period so counts don't flap:

```
Interior house:   15 min hold → then -1 per 5 min decay
Exterior property: 5 min hold → then instant drop
WiFi guest floor:  no decay (persistent while phone connected)
```

**Implementation:**
```python
# In PersonCensus.__init__
self._peak_house_camera_count: int = 0
self._peak_house_timestamp: datetime | None = None
self._peak_property_count: int = 0
self._peak_property_timestamp: datetime | None = None

# In async_update_census() — after calculating fresh counts
def _apply_hold_decay(self, fresh_count: int, zone: str, now: datetime) -> int:
    """Apply hold/decay to camera-based count."""
    if zone == "house":
        hold_seconds = CENSUS_HOLD_INTERIOR_SECONDS  # 900 (15 min)
        peak = self._peak_house_camera_count
        peak_ts = self._peak_house_timestamp
    else:
        hold_seconds = CENSUS_HOLD_EXTERIOR_SECONDS  # 300 (5 min)
        peak = self._peak_property_count
        peak_ts = self._peak_property_timestamp

    # Update peak if fresh count is higher
    if fresh_count >= peak:
        peak = fresh_count
        peak_ts = now
        # Update stored values
        ...

    # Within hold window: use peak
    if peak_ts and (now - peak_ts).total_seconds() < hold_seconds:
        return peak

    # After hold: decay (interior: -1 per 5 min; exterior: instant drop)
    if zone == "house" and peak_ts:
        elapsed_after_hold = (now - peak_ts).total_seconds() - hold_seconds
        decay_steps = int(elapsed_after_hold / CENSUS_DECAY_STEP_SECONDS)  # 300
        return max(fresh_count, peak - decay_steps)

    return fresh_count
```

---

## TEMPORAL CROSS-CORRELATION

When a camera detects an unrecognized person, check for corroborating signals:

```python
# Within ±60s of camera detection:
#   BLE total_device_count incremented  → HIGH confidence visitor
#   WiFi device connected on guest VLAN → HIGH confidence guest
#   Neither                             → MEDIUM confidence (delivery person, phone not discoverable)

# WiFi guest device connects, no camera:
#   → LOW confidence guest (phone connected but person not in camera FOV)

# Camera sees recognized face:
#   → identified person confirmed, no guest signal
```

**Delivery person scenario:**
1. Front door camera → person_occupancy ON → immediate census
2. Frigate face: "Unknown" → unidentified = 1
3. BLE total_device_count may bump (phone broadcasts BLE ads even without WiFi)
4. 15-min hold → count persists after person leaves camera FOV
5. No WiFi reconnection → count decays after 15+5 min

**Multi-day guest scenario:**
1. Guest phone connects to "Revel" WiFi → device_tracker home → immediate census
2. WiFi guest floor = 1 (persistent, no decay)
3. Guest walks past cameras → face "Unknown" → cross-correlates with WiFi → high confidence
4. Guest sleeps → WiFi may disconnect briefly → camera hold (15 min) bridges gap
5. Morning: phone reconnects → WiFi floor resumes immediately
6. Guest leaves day 3 → phone disconnects → WiFi floor drops → guest gone

**Returning guest (was here last week):**
1. Phone reconnects to "Revel" → device_tracker not_home → home
2. WiFi guest floor = 1 immediately (no "new device" check needed)
3. Same as multi-day guest from here

**Guest napping in bedroom (4 hours, no cameras):**
1. Guest arrives → phone on "Revel" → wifi_guest_floor = 1
2. Guest walks past hallway camera → face "Unknown" → camera confirms unidentified
3. Guest goes to guest bedroom, closes door → cameras see nothing
4. Camera hold expires after 15 min → unrecognized_camera_detections drops to 0
5. But `unidentified = max(0, wifi_guests=1)` → count stays at 1 for entire nap
6. Guest wakes 4 hours later, walks past camera → camera confirms again
7. WiFi floor never dropped — guest was counted the whole time

**Guest sleeping overnight:**
1. Same as nap scenario but 8+ hours
2. Phone may disconnect from WiFi during deep sleep → UniFi marks not_home after ~5 min
3. WiFi guest floor drops to 0 temporarily (acceptable — everyone is asleep)
4. Phone reconnects in morning → WiFi floor immediately resumes
5. Alternative: some phones maintain WiFi during sleep → floor never drops

---

## PHONE MANUFACTURER FILTERING

WiFi guest VLAN includes IoT devices. Filter by OUI (manufacturer):

```python
PHONE_MANUFACTURERS: Final = frozenset({
    "Apple, Inc.",
    "Samsung Electronics Co.,Ltd",
    "Google, Inc.",
    "OnePlus Technology (Shenzhen) Co., Ltd",
    "Huawei Technologies Co.,Ltd",
    "Xiaomi Communications Co Ltd",
    "Motorola Mobility LLC, a Lenovo Company",
    "LG Electronics",
    "Sony Mobile Communications Inc",
    "OPPO",
    "vivo Mobile Communication Co., Ltd.",
    "Nothing Technology Limited",
    "Fairphone",
})

# IoT manufacturers to EXCLUDE (not phones)
# "Espressif Inc.", "Shelly", "Meross", "Tuya", etc.
# We use an allowlist (PHONE_MANUFACTURERS) not a blocklist
```

---

## CONSTANTS

```python
# v3.10.1: Census v2
CENSUS_HOLD_INTERIOR_SECONDS: Final = 900   # 15 minutes
CENSUS_HOLD_EXTERIOR_SECONDS: Final = 300   # 5 minutes
CENSUS_DECAY_STEP_SECONDS: Final = 300      # -1 person per 5 min after hold
CENSUS_EVENT_DEBOUNCE_SECONDS: Final = 5    # Debounce rapid detection events
CENSUS_FACE_RECOGNITION_WINDOW: Final = 1800  # 30 min — how long a face match stays "active"

CONF_GUEST_VLAN_SSID: Final = "guest_vlan_ssid"
DEFAULT_GUEST_VLAN_SSID: Final = ""  # Empty = auto-detect via is_guest flag

CONF_ENHANCED_CENSUS: Final = "enhanced_census"
CONF_CENSUS_HOLD_INTERIOR: Final = "census_hold_interior"
CONF_CENSUS_HOLD_EXTERIOR: Final = "census_hold_exterior"

PHONE_MANUFACTURERS: Final = frozenset({...})  # See above
```

---

## CONFIG FLOW: CENSUS SETTINGS

New step in integration OptionsFlow (alongside existing camera config):

```python
async def async_step_census_settings(self, user_input=None):
    """Configure enhanced census settings."""
    # Fields:
    schema = vol.Schema({
        vol.Required("enhanced_census", default=True): bool,        # Master toggle
        vol.Optional("guest_vlan_ssid", default=""): str,           # "Revel" or empty=auto
        vol.Required("census_hold_interior", default=15): vol.All(  # Minutes
            vol.Coerce(int), vol.Range(min=1, max=60)
        ),
        vol.Required("census_hold_exterior", default=5): vol.All(   # Minutes
            vol.Coerce(int), vol.Range(min=1, max=30)
        ),
    })
```

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| Enhanced census | Toggle | On | — | Enable event-driven census, hold/decay, WiFi guest floor. Off = original v3.10.0 behavior. |
| Guest WiFi network | Text | *(empty)* | — | SSID name (e.g., "Revel"). Empty = auto-detect via `is_guest` flag. |
| Interior hold (min) | Number | 15 | 1–60 | How long to hold interior person count after last camera detection. |
| Exterior hold (min) | Number | 5 | 1–30 | How long to hold exterior person count after last camera detection. |

---

## SENSOR ATTRIBUTES (new on existing sensors)

**`sensor.ura_persons_in_house`** — new attributes:
| Attribute | Type | Description |
|-----------|------|-------------|
| `wifi_guest_floor` | int | Phones on guest VLAN right now |
| `camera_unrecognized` | int | Cameras seeing unknown faces |
| `peak_held` | bool | Whether count is held from a previous peak |
| `peak_age_minutes` | int | How old the held peak is |
| `face_recognized_persons` | list | Who Frigate has face-matched recently |
| `enhanced_census` | bool | Whether v2 is active |

**`sensor.ura_persons_on_property_exterior`** — new attributes:
| Attribute | Type | Description |
|-----------|------|-------------|
| `peak_held` | bool | Whether exterior count is held |
| `peak_age_minutes` | int | Age of held peak |

All existing attributes unchanged. New attributes default to 0/false/[] when enhanced census is disabled.

---

## REVIEW PROTOCOL (3 parallel reviews)

| Review | Scope | Files | Checks |
|--------|-------|-------|--------|
| Review 1: Census Core | Domain logic | `camera_census.py`, `const.py` | Hold/decay correctness, edge cases (None, 0, negative), WiFi guest filtering, face recognition window, cross-correlation timing, backward compat when disabled |
| Review 2: Census Integration | Event wiring | `__init__.py`, `const.py` | Event listener registration/cleanup, debounce, async safety, signal dispatch, unload cleanup, no leaked listeners |
| Review 3: UI/Config | Config flow | `config_flow.py`, `strings.json`, `translations/en.json` | OptionsFlow pattern, `.get()` defaults for all new keys, strings/en.json sync, range validation, backward compat for entries without new keys |

Fix all CRITICAL and HIGH issues before deploy. Re-run tests after fixes.

---

## FILES CHANGED

| File | Changes | Size |
|------|---------|------|
| `camera_census.py` | Hold/decay state vars, `_apply_hold_decay()`, rewrite `_cross_correlate_persons()`, add `_get_unrecognized_camera_persons()`, `_get_wifi_guest_count()`, `_get_recognized_by_face()` | Large |
| `__init__.py` | Register event listeners (person_occupancy, frigate face, BLE count, WiFi device_tracker), debounced census trigger callback | Medium |
| `const.py` | Hold/decay constants, CONF_GUEST_VLAN_SSID, PHONE_MANUFACTURERS | Small |
| `config_flow.py` | Census Settings step: enable toggle, guest VLAN SSID, interior hold timer, exterior hold timer | Small |
| `strings.json` | Guest VLAN label + description | Small |
| `translations/en.json` | Mirror | Small |
| `quality/tests/test_census_v2.py` | 35-45 tests (hold/decay, seen vs recognized, WiFi floor, cross-correlation, event triggers) | Medium |

---

## IMPLEMENTATION ORDER

1. **Constants** — add all new constants to const.py
2. **Hold/decay** — add state vars and `_apply_hold_decay()` to camera_census.py
3. **Person classification** — rewrite `_cross_correlate_persons()`, add face recognition + WiFi guest helpers
4. **Event listeners** — register state change listeners in __init__.py with debounce
5. **Config flow** — Census Settings step: enable toggle, guest VLAN SSID, hold timers (interior + exterior)
6. **Strings/translations** — labels for new config step
7. **Tests** — comprehensive test coverage
8. **Review (3 parallel reviews):**
   - Review 1 (Census Core): camera_census.py changes — hold/decay, person classification, WiFi guest, event handling. Against QUALITY_CONTEXT.md bug classes.
   - Review 2 (Census Integration): __init__.py event listeners, const.py, signal flow, backward compat.
   - Review 3 (UI/Config): config_flow.py, strings.json, translations/en.json — OptionsFlow pattern, .get() defaults, strings sync.
9. **Fix all CRITICAL/HIGH issues** from reviews, re-run tests
10. **Deploy**

---

## VERIFICATION

1. Person by pool → exterior cameras detect → exterior count = 1, holds for 5 min after person leaves FOV
2. Guest in playroom → Frigate face "Unknown" → unidentified = 1, holds 15 min
3. Guest phone on "Revel" WiFi → wifi_guest_floor = 1 (persistent)
4. Household member recognized by Frigate → identified, not guest
5. Delivery person at front door → detected, face unknown → unidentified = 1, decays after 15+5 min
6. Camera detection off→on → census recalculates immediately (not waiting for 30s poll)
7. Guest leaves after 3 days → phone disconnects from WiFi → guest count drops
8. Same guest returns next week → phone reconnects to Revel → immediately counted
9. Multiple guests → each phone on Revel = separate count in wifi_guest_floor
10. Person in camera-free room → WiFi floor maintains count even without camera confirmation
11. Guest naps 4 hours in bedroom (no camera) → WiFi floor holds unidentified=1 entire time
12. Guest sleeps overnight → WiFi may drop briefly when phone sleeps → resumes on morning reconnect
13. BLE total_device_count increments + camera sees unknown person within 60s → high confidence visitor
14. IoT device on Revel VLAN (Shelly, ESP) → filtered out by OUI allowlist, not counted as guest

---

## RISK MITIGATION

| Risk | Mitigation |
|------|------------|
| Event listener stampede (person walks past 5 cameras) | 5s debounce on census recalculation |
| False WiFi guests (IoT on guest VLAN) | Phone manufacturer allowlist (OUI filtering) |
| Frigate face recognition unreliable | WiFi guest floor as independent signal; face is supplementary |
| Hold period too long (false positives) | Configurable via constants, 15 min default conservative |
| BLE total_device_count noisy (fluctuates ±10/min) | Only trigger on increment (new device), not fluctuation |
| Guest phone sleeps at night | WiFi reconnects quickly on wake; 15 min camera hold bridges brief gaps |
| Multiple AI stacks see same person | Cross-validation already handles this — Frigate count is primary |
