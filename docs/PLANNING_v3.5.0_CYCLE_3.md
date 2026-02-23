# PLANNING: v3.5.0 Cycle 3 — Camera Integration & Census Core

**Version:** 1.4
**Date:** 2026-02-23
**Parent:** PLANNING_v3_5_0_Camera_Intelligence.md (original vision)
**Status:** Ready for Implementation
**Supersedes:** Original v3.5.0 scope is split across Cycles 3-4-6. This document covers Cycle 3 only.
**Changelog:**
- v1.4 — Dual census zones: house census (interior) vs property census (exterior). Egress cameras are the boundary between them. Added property census sensors.
- v1.3 — Split egress cameras from perimeter cameras. Egress (doorbells, door cams) at integration level — NOT room occupancy (delivery noise). Three-tier config: room interior, egress, perimeter.
- v1.2 — Added config flow UI (room-level camera entities, integration-level perimeter cameras), motion/mmWave as transit co-signal, graceful degradation for no-camera setups
- v1.1 — Added actual camera inventory from HA instance (23 cameras confirmed), real entity patterns for Frigate and UniFi Protect discovery

---

## OVERVIEW

Cycle 3 delivers the camera integration foundation and house census engine. This is the first of three cycles that implement the v3.5.0 Camera Intelligence vision.

**What ships:**

- Camera discovery for Frigate and UniFi Protect (dual-platform)
- Cross-validation between platforms (fast Frigate AI + reliable UniFi)
- Person counting: known (face-recognized) vs unidentified (guests)
- Cross-correlation: camera face IDs vs BLE IRK phone tracking
- Core census sensors (6 enabled, 4 disabled-by-default)

**What does NOT ship (deferred to later cycles):**

- Camera to BLE cross-correlation for room-level fusion (Cycle 4 / v3.5.1)
- Zone person aggregation and guest detection alerts (Cycle 4 / v3.5.1)
- Perimeter intruder alerting with time/location patterns (Cycle 4 / v3.5.1)
- Transit path validation and phone-left-behind detection (Cycle 6 / v3.5.2)
- Unidentified face storage and labeling UI (future)

---

## HARDWARE CONTEXT

### Camera Topology (23 cameras)

| Category | Coverage | Purpose |
|---|---|---|
| Egress cameras | Front doorbell, garage doorbell, Trackmix cam, etc. | Every entry/exit point. See everyone who enters or leaves. |
| Perimeter cameras | Ring the house at non-egress points | Catch persons who don't use doors. Intruder detection. |
| Shared space cameras | Living room, kitchen, hallways, stairs, etc. | Census counting + face recognition. Cross-correlation checkpoints for BLE to face matching. |

**Key architectural fact:** No cameras in bedrooms or bathrooms. Every known person must transit through a shared space, making shared space cameras the cross-correlation points.

### Actual Camera Inventory (from HA, 2026-02-23)

**Shared space / interior cameras (census + face recognition):**

| Camera | HA Entity Prefix | Location |
|--------|-----------------|----------|
| Family Room | `family_room` | Shared space — census |
| Playroom | `playroom` | Shared space — census |
| Foyer Fisheye | `foyer_fisheye` | Entry/transit — census checkpoint |
| Upstairs Hall | `upstairs_hall` | Transit corridor |
| Staircase / Garage Hallway | `staircase` | Transit corridor (Frigate: `Camera_Frigate_GarageHallway`, Protect: `Camera_Protect_GarageHallway`) |
| Stairs Top | `stairs_top` | Transit corridor |
| Master Hallway | `master_hallway` | Transit corridor |
| G3 Instant Study A | `g3_instant_study_a` | Shared space |

**Egress cameras (entry/exit tracking):**

| Camera | HA Entity Prefix | Location |
|--------|-----------------|----------|
| Madrone G6 Entry | `madrone_g6_entry` | Front door (also has package camera) |
| Garage Doorbell Lite | `doorbell_lite` | Garage entry |
| Garage A | `garage_a` | Garage A (also has doorbell person sensor) |
| Garage B | `garage_b` | Garage B |

**Perimeter cameras (intruder detection):**

| Camera | HA Entity Prefix | Location |
|--------|-----------------|----------|
| Front Door Aerial | `front_door_aerial` | Front elevated view |
| Front Side PTZ | `front_side_ptz` | Front side pan-tilt-zoom |
| Rear PTZ | `rear_ptz` | Rear yard |
| Back Yard | `back_yard` | Backyard |
| Hot Tub | `hot_tub` | Pool/patio area |
| Pool Equipment | `pool_equipment` | Pool equipment area |
| Utilities PTZ | `utilities_ptz` | Utility side |
| G5 Bullet | `g5_bullet` | Perimeter |
| ArmCrest | `armcrest` | Perimeter |
| ArmCrestASH41B | `armcrestash41b` | Perimeter |
| ReolinkStudyBPorchPTZ | `reolinkstudybporchptz` | Porch/perimeter |

**Entity patterns confirmed from HA:**

| Platform | Person Detected | Person Count | Person Occupancy |
|----------|----------------|-------------|-----------------|
| **UniFi Protect** | `binary_sensor.{name}_person_detected` | — | — |
| **Frigate** | — | `sensor.{name}_person_count` | `binary_sensor.{name}_person_occupancy` |
| **Both** | via device grouping | `sensor.{name}_person_active_count` (Frigate) | — |

**Zone groups already exist:** `binary_sensor.binarygroup_camera_persondetected_zone1` and `zone3` — indicating pre-existing HA groupings for camera person detection by zone.

### Dual Platform Strategy

| Platform | Strength | Role |
|---|---|---|
| Frigate | Fast AI detection, built-in person/face models | Primary detection — fires first, immediate occupancy signal |
| UniFi Protect | Reliable, lower false-positive rate | Confirmation — validates Frigate detection, boosts confidence |

Both platforms run in parallel on the same cameras. Cross-validation runs until user picks a winner. The architecture supports single-platform gracefully (one source = medium confidence, both = high confidence opportunity).

### Person Identification Sources

| Source | What it identifies | Existing? |
|---|---|---|
| BLE IRK (Bermuda) | Family members by phone | Yes — v3.2.0+ |
| Frigate face recognition | Known persons by face | Yes — Available |
| UniFi Protect face recognition | Known persons by face | Yes — Available |

**Person taxonomy:**

- **Known person** — Family member. Identified by BLE IRK + face recognition. Always tracked.
- **Guest** — Invited visitor. No stored face, no phone. Census shows as unidentified. Future: store face for labeling.
- **Intruder** — Uninvited. Detected on perimeter at odd times. Distinguished by time/location pattern (Cycle 4).

---

## IMPLEMENTATION

### New File: `camera_census.py`

Single new module containing all Cycle 3 logic (~400-500 lines).

#### Class: `CameraIntegrationManager`

Discovers and manages camera entities from Frigate and UniFi Protect.

```python
class CameraIntegrationManager:
    """Discover and manage camera entities from Frigate and UniFi Protect."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._frigate_cameras: dict[str, CameraInfo] = {}   # area_id -> CameraInfo
        self._unifi_cameras: dict[str, CameraInfo] = {}     # area_id -> CameraInfo

    async def async_discover(self) -> None:
        """Discover camera entities via entity registry."""
        # 1. Find all camera.* entities
        # 2. Check integration: frigate or unifiprotect
        # 3. Map each camera to its HA area (room)
        # 4. Find associated person detection binary_sensors
        # 5. Find associated person count sensors (if available)

    def get_cameras_for_area(self, area_id: str) -> list[CameraInfo]:
        """Get all cameras (both platforms) covering a given area."""

    def get_platform_for_camera(self, entity_id: str) -> str:
        """Return 'frigate' or 'unifiprotect'."""
```

**Discovery approach:**

- Use HA entity registry to find `camera.*` entities
- Check `platform` field for "frigate" or "unifiprotect"
- Use entity's `area_id` to map camera to room
- Find associated `binary_sensor.*_person` (Frigate) or `binary_sensor.*_person_detected` (UniFi)
- Find associated `sensor.*_person_count` if available

#### Class: `PersonCensus`

Dual-zone census engine. Tracks people inside the house and on the property separately.

**Two census zones:**

| Zone | Sources | What it counts |
|---|---|---|
| **House** | Interior room cameras + BLE | People inside the house |
| **Property** | Perimeter + egress cameras | People outside but on the property (yard, driveway, porch, pool) |

Egress cameras are the **boundary** between zones. When someone crosses an egress point, they move from property → house or house → property. The delta (property - house) tells you how many people are outside.

```python
class PersonCensus:
    """Dual-zone person census: house (interior) and property (exterior)."""

    def __init__(
        self,
        hass: HomeAssistant,
        camera_manager: CameraIntegrationManager,
    ) -> None:
        self.hass = hass
        self._camera_manager = camera_manager
        self._house_census: CensusZoneResult | None = None
        self._property_census: CensusZoneResult | None = None

    async def async_update_census(self) -> FullCensusResult:
        """Calculate both census zones from all sources."""
        # House census:
        # 1. Get interior camera person counts per room (both platforms)
        # 2. Cross-validate Frigate vs UniFi counts per room
        # 3. Get face-recognized persons from interior cameras
        # 4. Get BLE-tracked persons from person_coordinator
        # 5. Cross-correlate: face IDs <-> BLE IRK IDs
        # 6. Calculate house: identified, unidentified (guests), total
        #
        # Property census:
        # 7. Get person detection from egress + perimeter cameras
        # 8. Calculate property: detected persons outside the house
        # 9. Combine: total_on_property = house + property exterior

    def _cross_validate_platforms(
        self, frigate_count: int, unifi_count: int
    ) -> tuple[int, str]:
        """Cross-validate person counts between platforms.

        Returns (best_count, confidence):
          both agree      -> (count, "high")
          close (+-1)     -> (max, "medium")
          disagree (>1)   -> (max, "low")
          single source   -> (count, "medium")
          no source       -> (0, "none")
        """

    def _cross_correlate_persons(
        self,
        face_ids: set[str],       # Persons identified by face
        ble_ids: set[str],        # Persons identified by BLE IRK
        camera_total: int,        # Total persons seen by cameras
    ) -> CensusZoneResult:
        """Cross-correlate face recognition with BLE tracking.

        known_persons = face_ids | ble_ids  (union -- identified by either)
        identified_count = len(known_persons)
        unidentified_count = max(0, camera_total - identified_count)  # guests
        total = identified_count + unidentified_count
        """
```

#### Dataclasses

```python
@dataclass
class CensusZoneResult:
    """Result for a single census zone (house or property)."""
    zone: str                       # "house" or "property"
    identified_count: int           # Known persons (face or BLE)
    identified_persons: list[str]   # List of person IDs
    unidentified_count: int         # Unknown persons (camera sees, can't identify)
    total_persons: int              # identified + unidentified
    confidence: str                 # "high", "medium", "low", "none"
    source_agreement: str           # "both_agree", "close", "disagree", "single_source"
    frigate_count: int              # Raw Frigate count (if applicable)
    unifi_count: int                # Raw UniFi count (if applicable)
    timestamp: datetime             # When census was taken

@dataclass
class FullCensusResult:
    """Combined house + property census."""
    house: CensusZoneResult         # People inside the house
    property_exterior: CensusZoneResult  # People outside on property
    total_on_property: int          # house.total + property_exterior.total
    ble_persons: list[str]          # BLE-tracked person IDs (house only)
    face_persons: list[str]         # Face-recognized person IDs (all zones)
    persons_outside: int            # property_exterior.total (convenience)
    timestamp: datetime             # When census was taken
```

### Modified File: `__init__.py`

Add initialization of `CameraIntegrationManager` and `PersonCensus` in the integration setup sequence, after `person_coordinator`:

```python
# After person_coordinator init:
camera_manager = CameraIntegrationManager(hass)
await camera_manager.async_discover()
hass.data[DOMAIN]["camera_manager"] = camera_manager

census = PersonCensus(hass, camera_manager)
hass.data[DOMAIN]["census"] = census
```

### Modified File: `sensor.py`

Add census sensors. These are integration-level sensors (not per-room).

**Enabled by default (8 entities):**

| Entity | Entity ID | State | Key Attributes |
|---|---|---|---|
| Total Persons in House | `sensor.ura_persons_in_house` | int (e.g., 6) | identified_count, unidentified_count, confidence |
| Identified Persons in House | `sensor.ura_identified_persons_in_house` | int (e.g., 4) | person_list (JSON), ble_confirmed, face_confirmed |
| Unidentified Persons in House | `sensor.ura_unidentified_persons_in_house` | int (e.g., 2) | — |
| Persons on Property (exterior) | `sensor.ura_persons_on_property` | int (e.g., 3) | — people outside but on property |
| Total Persons on Property | `sensor.ura_total_persons_on_property` | int (e.g., 9) | house + exterior combined |
| Unexpected Person Detected | `binary_sensor.ura_unexpected_person_detected` | on/off | on when unidentified > 0 AND all BLE persons accounted for |
| Per-Room Camera Person Detected | `binary_sensor.{room}_camera_person_detected` | on/off | source (frigate/unifi/both), count |
| Zone Person Count | `sensor.{zone}_person_count` | int | identified_list, unidentified_count |

**Disabled by default (4 entities):**

| Entity | Entity ID | Why disabled |
|---|---|---|
| Census Confidence | `sensor.ura_census_confidence` | Diagnostic — for tuning |
| Zone Identified Persons | `sensor.{zone}_identified_persons` | Nice for dashboards |
| Per-Room Camera Person Count | `sensor.{room}_camera_person_count` | Noisy |
| Census Validation Age | `sensor.ura_census_validation_age` | Diagnostic for staleness |

**Warehoused for later cycles (do not implement yet):**

| Entity | Target Cycle |
|---|---|
| `sensor.ura_persons_entered_today` | Cycle 6 (v3.5.2) |
| `sensor.ura_persons_exited_today` | Cycle 6 (v3.5.2) |
| `sensor.ura_last_person_entry` | Cycle 6 (v3.5.2) |
| `sensor.ura_last_person_exit` | Cycle 6 (v3.5.2) |
| `binary_sensor.ura_census_mismatch` | Cycle 6 (v3.5.2) |
| `sensor.{zone}_unidentified_count` | Cycle 6 (v3.5.2) |

### Modified File: `const.py`

Add constants:

```python
# v3.5.0 Camera Census
CONF_CAMERA_PERSON_ENTITIES: Final = "camera_person_entities"  # room-level interior cameras
CONF_EGRESS_CAMERAS: Final = "egress_cameras"                  # integration-level door cameras
CONF_PERIMETER_CAMERAS: Final = "perimeter_cameras"            # integration-level yard/fence cameras
CONF_CAMERA_PLATFORM: Final = "camera_platform"

# Census update interval
SCAN_INTERVAL_CENSUS: Final = timedelta(seconds=30)

# Camera platform identifiers
CAMERA_PLATFORM_FRIGATE: Final = "frigate"
CAMERA_PLATFORM_UNIFI: Final = "unifiprotect"

# Census confidence levels
CENSUS_CONFIDENCE_HIGH: Final = "high"
CENSUS_CONFIDENCE_MEDIUM: Final = "medium"
CENSUS_CONFIDENCE_LOW: Final = "low"
CENSUS_CONFIDENCE_NONE: Final = "none"

# Cross-validation agreement
CENSUS_AGREEMENT_BOTH: Final = "both_agree"
CENSUS_AGREEMENT_CLOSE: Final = "close"
CENSUS_AGREEMENT_DISAGREE: Final = "disagree"
CENSUS_AGREEMENT_SINGLE: Final = "single_source"
```

### Modified File: `database.py`

Add census snapshots table:

```python
# In _create_tables():
cursor.execute("""
    CREATE TABLE IF NOT EXISTS census_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME NOT NULL,
        identified_count INTEGER NOT NULL,
        identified_persons TEXT,
        unidentified_count INTEGER NOT NULL,
        total_persons INTEGER NOT NULL,
        confidence TEXT,
        source_agreement TEXT,
        frigate_count INTEGER,
        unifi_count INTEGER,
        UNIQUE(timestamp)
    )
""")
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_census_timestamp
    ON census_snapshots(timestamp)
""")
```

Add methods:

```python
async def log_census(self, result: CensusResult) -> None:
    """Log a census snapshot."""

async def get_census_history(self, hours: int = 24) -> list[dict]:
    """Get census history for the last N hours."""

async def cleanup_census(self, retention_days: int = 90) -> int:
    """Delete census snapshots older than retention_days."""
```

---

## DISCOVERY DETAILS (Confirmed from HA Instance)

### Frigate Entity Patterns (actual)

Per camera, Frigate creates:
- `binary_sensor.{name}_person_occupancy` — person occupancy (device_class: occupancy, icon: mdi:home-outline)
- `sensor.{name}_person_count` — person count (unit: objects, icon: mdi:human)
- `sensor.{name}_person_active_count` — active person count

Example (Family Room):
- `binary_sensor.family_room_person_occupancy`
- `sensor.family_room_person_count`
- `sensor.family_room_person_active_count`

Discovery: Find `binary_sensor.*_person_occupancy` with device_class "occupancy" and icon "mdi:home-outline".

### UniFi Protect Entity Patterns (actual)

Per camera, UniFi Protect creates:
- `binary_sensor.{name}_person_detected` — person detected (on/off)
- Camera entities with resolution channels: `camera.{name}_high_resolution_channel`, `_medium_resolution_channel`, `_low_resolution_channel`

Example (Family Room):
- `binary_sensor.family_room_person_detected`
- `camera.family_room_high_resolution_channel`

Discovery: Find `binary_sensor.*_person_detected` (NOT `*_person_occupancy` — that's Frigate).

### Distinguishing Platforms

The same physical camera produces entities on both platforms. They share the same HA area but have different entity patterns:

```
Physical Camera: "Family Room" (HA Area: Family Room)

UniFi Protect:
  binary_sensor.family_room_person_detected        ← person detected
  camera.family_room_high_resolution_channel        ← video feed

Frigate:
  binary_sensor.family_room_person_occupancy        ← person occupancy
  sensor.family_room_person_count                   ← person count
  sensor.family_room_person_active_count            ← active count
```

Cross-validation: Frigate `person_count` = 3, UniFi `person_detected` = on. Use Frigate for count (it has the number), UniFi for presence confirmation (binary).

### Existing Zone Groups

HA already has zone-level binary sensor groups:
- `binary_sensor.binarygroup_camera_persondetected_zone1`
- `binary_sensor.binarygroup_camera_persondetected_zone3`

These aggregate per-zone camera person detection. The census engine can leverage these as a quick zone-level signal.

### Face Recognition Entities

Both platforms support face recognition. Need to discover:
- Frigate: `sensor.{name}_identified_faces` or event-based face identification
- UniFi Protect: Face group attributes on detection entities

**Action item for implementation:** Query a live camera entity's attributes during discovery to confirm the exact face recognition entity pattern. This may vary by Frigate/UniFi version.

---

## CROSS-CORRELATION LOGIC

### Camera to BLE Matching

```
BLE says: [John, Jane, Kid1, Kid2] are home (4 phones tracked)
Frigate says: 6 persons detected, recognizes [John, Jane, Kid1] faces
UniFi says: 6 persons detected, recognizes [John, Jane, Kid2] faces

Cross-correlation:
  face_ids = {John, Jane, Kid1, Kid2}  (union of both platforms)
  ble_ids = {John, Jane, Kid1, Kid2}   (from Bermuda)
  known_persons = face_ids | ble_ids = {John, Jane, Kid1, Kid2}
  identified_count = 4
  camera_total = 6 (cross-validated: both agree)
  unidentified_count = 6 - 4 = 2 guests
  total = 6
  confidence = "high" (platforms agree, BLE confirms faces)
```

### Confidence Rules

```
Both platforms agree on count AND faces match BLE  -> "high"
Both platforms agree on count, partial face match  -> "high"
Platforms within +-1 of each other                 -> "medium"
Platforms disagree by >1                           -> "low"
Only one platform available                        -> "medium"
No camera data, BLE only                           -> "low"
No data at all                                     -> "none"
```

---

## ADDENDUM A: CONFIGURATION & UI

### Camera entities belong in room config (sensor step)

Cameras are per-room, just like motion and mmWave sensors. The existing room config flow Step 2 (Sensors) already handles optional sensor types. Camera person detection entities are another optional sensor type.

**Add to config_flow.py room sensor step:**

```python
# New fields in Step 2 (Sensors):
CONF_CAMERA_PERSON_ENTITIES: Final = "camera_person_entities"  # list[str]

# In the sensor step schema:
vol.Optional(CONF_CAMERA_PERSON_ENTITIES): selector.EntitySelector(
    selector.EntitySelectorConfig(
        domain="binary_sensor",
        device_class="occupancy",
        multiple=True,
    )
)
```

Users select the camera person detection entities for each room (0, 1, or 2 for dual-platform). The `CameraIntegrationManager` reads these from room config instead of auto-discovering by area — this is more reliable and gives users explicit control.

**Auto-discovery is a fallback**, not the primary path. If a room has no `CONF_CAMERA_PERSON_ENTITIES` configured, the manager can optionally discover cameras by matching the room's HA area. But explicit config is preferred because:
- User knows which camera covers which room
- Some rooms may have cameras for a different purpose (baby monitor, not census)
- Perimeter cameras shouldn't auto-map to rooms

### Egress cameras at integration level

Egress cameras (doorbells, door-mounted cameras) watch entry/exit points. They do NOT feed room occupancy — most door activity is deliveries, solicitors, etc. that never enter the house. Counting them would create noise and false occupancy timeouts.

Egress cameras are consumed later for directional entry/exit tracking and access logging, not room-level person detection.

**Add to config_flow.py integration options:**

```python
CONF_EGRESS_CAMERAS: Final = "egress_cameras"  # list[str]

vol.Optional(CONF_EGRESS_CAMERAS): selector.EntitySelector(
    selector.EntitySelectorConfig(
        domain="binary_sensor",
        multiple=True,
    )
)
```

### Perimeter cameras at integration level

Perimeter cameras watch fence lines, yards, and non-door exterior areas. They're purely security — intruder detection via time/location patterns (consumed by Security Coordinator in v3.6.0).

**Add to config_flow.py integration options:**

```python
CONF_PERIMETER_CAMERAS: Final = "perimeter_cameras"  # list[str]

vol.Optional(CONF_PERIMETER_CAMERAS): selector.EntitySelector(
    selector.EntitySelectorConfig(
        domain="binary_sensor",
        multiple=True,
    )
)
```

### Config changes summary

| Config Level | New Field | Purpose | Feeds into |
|-------------|-----------|---------|------------|
| Room (sensor step) | `CONF_CAMERA_PERSON_ENTITIES` | Interior cameras — census + occupancy signal | Room coordinator, census engine |
| Integration | `CONF_EGRESS_CAMERAS` | Door cameras — entry/exit tracking only | Census entry/exit tracking (later cycle) |
| Integration | `CONF_PERIMETER_CAMERAS` | Yard/fence cameras — intruder detection only | Security Coordinator (v3.6.0) |

**Key design decision:** Egress cameras are separate from perimeter because they serve different future purposes. Egress tracks who enters/exits through doors. Perimeter tracks who shouldn't be there at all. The separation matters when the Security Coordinator distinguishes "guest arrived at front door" from "unknown person on east fence at 2am."

---

## ADDENDUM B: MOTION/MMWAVE AS TRANSIT CO-SIGNAL

Shared spaces (living room, kitchen, hallways) are URA rooms with motion and mmWave sensors. These sensors provide an anonymous transit timeline that already exists in v3.3.x:

```
Timeline:
  T+0s   Kitchen motion fires → coordinator: kitchen occupied
  T+5s   Kitchen motion clears
  T+8s   Hallway motion fires → TransitionDetector: kitchen → hallway
  T+12s  Living room motion fires → TransitionDetector: hallway → living room
  T+12s  Living room camera: 3 persons, 2 identified (John, Jane)
```

**What camera adds to existing motion/mmWave:**
- Motion says "someone is here" → Camera says "John and Jane are here, plus 1 guest"
- mmWave says "2 people present" → Camera cross-validates the count
- TransitionDetector says "someone went kitchen → living room" → Camera confirms WHO transited

**Implementation note:** The census engine does NOT need to build its own transit detection. It consumes:
1. Existing `ura_person_location_change` events (from person_coordinator)
2. Room coordinator occupancy state (from motion/mmWave)
3. Camera person detection and count (new)

The fusion happens in the room coordinator's `_async_update_data()`, where camera data becomes another weighted signal alongside motion (0.50), mmWave (0.60), BLE (0.70), and camera (0.85).

---

## ADDENDUM C: GRACEFUL DEGRADATION

Every feature must work without cameras. Camera data is an enhancement, not a requirement.

| Feature | With cameras | Without cameras |
|---------|-------------|----------------|
| **Room occupancy** | Motion + mmWave + BLE + camera (4 signals) | Motion + mmWave + BLE (3 signals, current behavior) |
| **Person count** | Camera count cross-validated with BLE | BLE count only (phones tracked) |
| **Guest detection** | Camera total minus identified = guests | Not available — BLE can't detect guests |
| **Face recognition** | Cross-correlate face IDs with BLE IDs | BLE-only identification |
| **Transit validation** | Camera confirms who transited | Motion timeline only (anonymous) |
| **Intruder detection** | Perimeter camera + time pattern | Not available |
| **Census confidence** | High (multi-source) | Low (BLE-only) |

**Code pattern:** Every method that reads camera data checks availability first:

```python
camera_entities = self._get_config(CONF_CAMERA_PERSON_ENTITIES, [])
if camera_entities:
    # Use camera data for enhanced census
    ...
else:
    # Fall back to BLE-only census
    ...
```

**No cameras configured = v3.3.x behavior.** The integration never errors or degrades because cameras are missing. Census sensors still exist but report BLE-only data with low confidence.

---

## FILES TO CREATE/MODIFY

| File | Action | Lines (est.) |
|---|---|---|
| `camera_census.py` | Create — CameraIntegrationManager + HousePersonCensus | ~400-500 |
| `config_flow.py` | Modify — add CONF_CAMERA_PERSON_ENTITIES to room sensor step, CONF_PERIMETER_CAMERAS to integration options | ~40 |
| `__init__.py` | Modify — add camera/census init | ~15 |
| `sensor.py` | Modify — add 10 census sensors | ~200 |
| `binary_sensor.py` | Modify — add unexpected person sensor | ~40 |
| `const.py` | Modify — add census + camera config constants | ~30 |
| `database.py` | Modify — add census table + methods | ~60 |

---

## VERIFICATION

1. Integration starts without cameras configured — census returns BLE-only data, confidence "low"
2. Frigate cameras discovered — person detection works, single-source confidence "medium"
3. Both platforms discovered — cross-validation active, confidence reflects agreement
4. Face recognition matches BLE tracking — identified_count correct
5. More camera persons than BLE persons — unidentified_count reflects guests
6. `sensor.ura_total_persons_home` updates every 30 seconds
7. Census snapshots logged to database, cleanup removes records older than 90 days
8. Disabled-by-default sensors don't appear unless user enables them

---

## DEPLOY

```bash
./scripts/deploy.sh "3.5.0" "Camera integration and dual-zone person census" "- Dual-platform camera discovery (Frigate + UniFi Protect)
- Cross-validation between platforms for person counting
- Person identification: face recognition <-> BLE IRK cross-correlation
- Dual-zone census: house (interior) + property (exterior) with separate counts
- Three-tier camera config: room interior, egress (doors), perimeter (yard/fence)
- 8 census entities (enabled) + 4 diagnostic entities (disabled by default)
- Census snapshot database with 90-day retention"
```
