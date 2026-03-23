"""Universal Room Automation integration."""
#
# Universal Room Automation v3.17.4
# Build: 2026-01-05
# File: __init__.py
# FIX v3.3.2: Added ENTRY_TYPE_ZONE handling so zone OptionsFlow becomes accessible
# FIX v3.2.8: PersonLocationSensor architectural fix - active state listeners
# FIX v3.2.8: Presence decay system with tracking_status states
# FIX v3.2.8: Path tracking with recent_path attribute
# FIX v3.2.6: Previous location bug - was reading from current dict instead of self.data
# FIX v3.2.6: OccupantCountSensor now counts real people instead of rooms
# FIX v3.2.6: Added diagnostic logging and sensors for person tracking
# NEW v3.2.6: Sensor renaming for clarity (Presence → Sensor Presence, etc.)
#

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.event import (
    async_track_time_interval,
    async_track_state_change_event,
)

from .const import (
    DOMAIN,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ROOM,
    ENTRY_TYPE_ZONE,  # v3.3.2: Import zone entry type
    ENTRY_TYPE_ZONE_MANAGER,  # v3.6.0: Zone manager entry type
    ENTRY_TYPE_COORDINATOR_MANAGER,  # v3.6.0: Coordinator manager entry type
    CONF_ENTRY_TYPE,
    CONF_INTEGRATION_ENTRY_ID,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_OUTSIDE_HUMIDITY_SENSOR,
    CONF_WEATHER_ENTITY,
    CONF_SOLAR_PRODUCTION_SENSOR,
    CONF_ELECTRICITY_RATE,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TARGET,
    CONF_NOTIFY_LEVEL,
    CONF_TRACKED_PERSONS,  # v3.2.0: Person tracking
    CONF_ZONE_NAME,  # v3.3.2: For zone entry logging
    CONF_ZONE,  # v3.3.5.4: For zone migration
    CONF_ZONE_ROOMS,  # v3.3.5.4: For zone migration
    CONF_ZONE_DESCRIPTION,  # v3.3.5.4: For zone migration
    CONF_CAMERA_PERSON_ENTITIES,  # v3.4.5: Interior camera migration
    CONF_EGRESS_CAMERAS,  # v3.5.0: Egress cameras
    CONF_PERIMETER_CAMERAS,  # v3.5.0: Perimeter cameras
    CONF_DOMAIN_COORDINATORS_ENABLED,  # v3.6.0: Domain coordinators
    SCAN_INTERVAL_CENSUS,  # v3.5.0: Census update interval
    DEFAULT_ELECTRICITY_RATE,
    NOTIFY_LEVEL_ERRORS,
    CONF_ENHANCED_CENSUS,  # v3.10.1: Enhanced census toggle
    CENSUS_EVENT_DEBOUNCE_SECONDS,  # v3.10.1: Event debounce
)
from .const import VERSION
from .coordinator import UniversalRoomCoordinator
from .database import UniversalRoomDatabase
from .person_coordinator import PersonTrackingCoordinator  # v3.2.0
from .camera_census import CameraIntegrationManager, PersonCensus  # v3.5.0
from .perimeter_alert import PerimeterAlertManager  # v3.5.1

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
]

# Platforms for integration entry (aggregation sensors + select for house state + switches)
INTEGRATION_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SWITCH,  # v3.6.0-c2.5: DomainCoordinatorsSwitch, CoordinatorEnabledSwitch
]


async def _migrate_zone_names_to_entries(hass: HomeAssistant, integration_entry: ConfigEntry) -> int:
    """Migrate zone names from room entries to proper zone config entries (v3.3.5.4).
    
    Previously, zones could be created by typing a new zone name during room setup.
    This created a zone NAME (string) stored in the room entry, but not a zone ENTRY.
    
    Going forward, zones must be proper config entries created via "Add new Zone".
    This migration auto-creates zone entries for any orphaned zone names.
    
    Returns the number of zone entries created.
    """
    # Collect all unique zone names from room entries
    zone_names_from_rooms: dict[str, list[str]] = {}  # zone_name -> [room_entry_ids]
    
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
            zone_name = config_entry.options.get(CONF_ZONE) or config_entry.data.get(CONF_ZONE)
            if zone_name:
                zone_name = zone_name.strip()
                if zone_name:
                    if zone_name not in zone_names_from_rooms:
                        zone_names_from_rooms[zone_name] = []
                    zone_names_from_rooms[zone_name].append(config_entry.entry_id)
    
    if not zone_names_from_rooms:
        _LOGGER.debug("No zone names found in room entries, skipping migration")
        return 0
    
    # Collect existing zone entries
    existing_zone_names: set[str] = set()
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
            zone_name = config_entry.data.get(CONF_ZONE_NAME, "").strip()
            if zone_name:
                existing_zone_names.add(zone_name.lower())
    
    # Create zone entries for any zone names without entries
    zones_created = 0
    for zone_name, room_entry_ids in zone_names_from_rooms.items():
        if zone_name.lower() not in existing_zone_names:
            _LOGGER.info("Migrating zone '%s' to config entry (linked to %d rooms)", zone_name, len(room_entry_ids))
            
            # Create the zone entry via config flow
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "zone_migration"},
                data={
                    CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE,
                    CONF_ZONE_NAME: zone_name,
                    CONF_ZONE_DESCRIPTION: f"Auto-migrated from room zone assignment",
                    CONF_ZONE_ROOMS: room_entry_ids,
                    CONF_INTEGRATION_ENTRY_ID: integration_entry.entry_id,
                }
            )
            
            if result.get("type") == "create_entry":
                zones_created += 1
                _LOGGER.info("✓ Created zone entry for '%s'", zone_name)
            else:
                _LOGGER.warning("Failed to create zone entry for '%s': %s", zone_name, result)
    
    if zones_created > 0:
        _LOGGER.info("Zone migration complete: created %d zone entries", zones_created)

    return zones_created


async def _migrate_room_cameras_to_integration(hass: HomeAssistant, integration_entry: ConfigEntry) -> int:
    """Migrate CONF_CAMERA_PERSON_ENTITIES from room entries to integration entry (v3.4.5).

    In v3.4.0–3.4.4, interior cameras were configured per room in the sensors
    step. Starting in v3.4.5, they are configured at the integration level in
    the camera_census step, with room mapping handled automatically via each
    camera's area assignment.

    This one-time migration:
      1. Scans all room config entries for CONF_CAMERA_PERSON_ENTITIES values.
      2. Collects and deduplicates all camera entity IDs found.
      3. Merges them into the integration config entry's CONF_CAMERA_PERSON_ENTITIES.
      4. Removes CONF_CAMERA_PERSON_ENTITIES from each room entry's options.

    Returns the number of camera entity IDs migrated.
    """
    # Collect all camera entity IDs from room entries
    collected_cameras: list[str] = []
    seen_ids: set[str] = set()
    room_entries_with_cameras: list[ConfigEntry] = []

    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
            continue
        merged = {**config_entry.data, **config_entry.options}
        room_cameras = merged.get(CONF_CAMERA_PERSON_ENTITIES, [])
        if room_cameras:
            room_entries_with_cameras.append(config_entry)
            for cam in room_cameras:
                if cam not in seen_ids:
                    collected_cameras.append(cam)
                    seen_ids.add(cam)

    if not collected_cameras:
        _LOGGER.debug("Camera migration: no room-level camera_person_entities found, skipping")
        return 0

    _LOGGER.info(
        "Camera migration: found %d camera entity IDs across %d room entries — merging into integration entry",
        len(collected_cameras),
        len(room_entries_with_cameras),
    )

    # Merge with any already present at integration level
    integration_merged = {**integration_entry.data, **integration_entry.options}
    existing_integration_cameras = integration_merged.get(CONF_CAMERA_PERSON_ENTITIES, [])
    existing_set = set(existing_integration_cameras)
    merged_cameras = list(existing_integration_cameras)
    for cam in collected_cameras:
        if cam not in existing_set:
            merged_cameras.append(cam)
            existing_set.add(cam)

    # Update integration entry options with merged cameras
    hass.config_entries.async_update_entry(
        integration_entry,
        options={**integration_entry.options, CONF_CAMERA_PERSON_ENTITIES: merged_cameras},
    )
    _LOGGER.info(
        "Camera migration: integration entry updated with %d indoor cameras: %s",
        len(merged_cameras),
        merged_cameras,
    )

    # Remove camera_person_entities from each room entry's options
    for room_entry in room_entries_with_cameras:
        updated_options = {
            k: v for k, v in room_entry.options.items()
            if k != CONF_CAMERA_PERSON_ENTITIES
        }
        hass.config_entries.async_update_entry(room_entry, options=updated_options)
        _LOGGER.info(
            "Camera migration: removed camera_person_entities from room entry '%s'",
            room_entry.data.get("room_name", room_entry.entry_id),
        )

    return len(collected_cameras)


async def _migrate_sensor_entity_ids(hass: HomeAssistant) -> int:
    """Migrate person-sensor unique_ids from old "occupant" names to "identified" names (v3.5.x).

    In v3.2.6 the friendly names of room and zone person sensors were updated
    (e.g. "Current Occupants" → "Identified People"), but the unique_ids were
    kept for backward compatibility.  This caused entity_ids that still said
    "current_occupants" / "occupant_count" to mismatch the visible friendly names.

    This one-time migration updates the unique_ids in the entity registry so that
    HA assigns new entity_ids consistent with the sensor names:

      Room sensors:
        {entry_id}_current_occupants   → {entry_id}_identified_people
        {entry_id}_occupant_count      → {entry_id}_identified_people_count
        {entry_id}_last_occupant       → {entry_id}_last_identified_person
        {entry_id}_last_occupant_time  → {entry_id}_last_identified_time

      Zone sensors:
        {DOMAIN}_zone_{zone}_current_occupants   → {DOMAIN}_zone_{zone}_identified_people
        {DOMAIN}_zone_{zone}_occupant_count      → {DOMAIN}_zone_{zone}_identified_people_count
        {DOMAIN}_zone_{zone}_last_occupant       → {DOMAIN}_zone_{zone}_last_identified_person
        {DOMAIN}_zone_{zone}_last_occupant_time  → {DOMAIN}_zone_{zone}_last_identified_time

    Returns the total number of entity unique_ids updated.
    """
    from homeassistant.helpers import entity_registry as er

    entity_registry = er.async_get(hass)
    renamed_count = 0

    # --- Room-level sensor migration ---
    # Room sensor unique_ids use the pattern: {entry_id}_{suffix}
    room_suffix_map = {
        "current_occupants": "identified_people",
        "occupant_count": "identified_people_count",
        "last_occupant": "last_identified_person",
        "last_occupant_time": "last_identified_time",
    }

    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
            continue
        entry_id = config_entry.entry_id
        room_name = config_entry.data.get("room_name", entry_id)

        for old_suffix, new_suffix in room_suffix_map.items():
            old_unique_id = f"{entry_id}_{old_suffix}"
            new_unique_id = f"{entry_id}_{new_suffix}"

            entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, old_unique_id)
            if entity_id is None:
                continue  # Already migrated or never existed

            # Check that the target unique_id doesn't already exist
            if entity_registry.async_get_entity_id("sensor", DOMAIN, new_unique_id) is not None:
                _LOGGER.debug(
                    "Sensor migration: target unique_id '%s' already exists, skipping '%s'",
                    new_unique_id,
                    old_unique_id,
                )
                continue

            entity_registry.async_update_entity(entity_id, new_unique_id=new_unique_id)
            renamed_count += 1
            _LOGGER.warning(
                "Sensor migration: renamed entity '%s' (room '%s') unique_id "
                "'%s' → '%s'. Update any external automations referencing the old entity_id.",
                entity_id,
                room_name,
                old_suffix,
                new_suffix,
            )

    # --- Zone-level sensor migration ---
    # Zone sensor unique_ids use the pattern: {DOMAIN}_zone_{zone_name}_{suffix}
    zone_suffix_map = {
        "current_occupants": "identified_people",
        "occupant_count": "identified_people_count",
        "last_occupant": "last_identified_person",
        "last_occupant_time": "last_identified_time",
    }

    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ZONE:
            continue
        zone_name = config_entry.data.get(CONF_ZONE_NAME, "")
        if not zone_name:
            continue

        for old_suffix, new_suffix in zone_suffix_map.items():
            old_unique_id = f"{DOMAIN}_zone_{zone_name}_{old_suffix}"
            new_unique_id = f"{DOMAIN}_zone_{zone_name}_{new_suffix}"

            entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, old_unique_id)
            if entity_id is None:
                continue  # Already migrated or never existed

            # Check that the target unique_id doesn't already exist
            if entity_registry.async_get_entity_id("sensor", DOMAIN, new_unique_id) is not None:
                _LOGGER.debug(
                    "Sensor migration: target unique_id '%s' already exists, skipping '%s'",
                    new_unique_id,
                    old_unique_id,
                )
                continue

            entity_registry.async_update_entity(entity_id, new_unique_id=new_unique_id)
            renamed_count += 1
            _LOGGER.warning(
                "Sensor migration: renamed entity '%s' (zone '%s') unique_id "
                "'%s' → '%s'. Update any external automations referencing the old entity_id.",
                entity_id,
                zone_name,
                old_suffix,
                new_suffix,
            )

    if renamed_count > 0:
        _LOGGER.info(
            "Sensor migration complete: updated %d entity unique_ids from 'occupant' to 'identified' naming",
            renamed_count,
        )

    return renamed_count


async def _migrate_zones_to_zone_manager(hass: HomeAssistant, integration_entry: ConfigEntry) -> None:
    """Migrate individual zone config entries to a single Zone Manager entry (v3.6.0).

    Creates a Zone Manager config entry containing all zone data, then removes
    the individual zone config entries to eliminate duplicate UI groups.
    """
    # Check if Zone Manager entry already exists
    for ce in hass.config_entries.async_entries(DOMAIN):
        if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
            _LOGGER.debug("Zone Manager entry already exists, skipping migration")
            return

    # Collect zone data from individual zone entries
    zones_data: dict[str, dict] = {}
    zone_entries_to_remove: list[ConfigEntry] = []

    for ce in hass.config_entries.async_entries(DOMAIN):
        if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
            zone_name = (ce.data.get(CONF_ZONE_NAME) or ce.options.get(CONF_ZONE_NAME, "")).strip()
            if not zone_name:
                continue
            merged = {**ce.data, **ce.options}
            zones_data[zone_name] = {
                CONF_ZONE_DESCRIPTION: merged.get(CONF_ZONE_DESCRIPTION, ""),
                CONF_ZONE_ROOMS: merged.get(CONF_ZONE_ROOMS, []),
            }
            # Copy any zone-specific options (media player, etc.)
            from .const import CONF_ZONE_PLAYER_ENTITY, CONF_ZONE_PLAYER_MODE
            if merged.get(CONF_ZONE_PLAYER_ENTITY):
                zones_data[zone_name][CONF_ZONE_PLAYER_ENTITY] = merged[CONF_ZONE_PLAYER_ENTITY]
            if merged.get(CONF_ZONE_PLAYER_MODE):
                zones_data[zone_name][CONF_ZONE_PLAYER_MODE] = merged[CONF_ZONE_PLAYER_MODE]

            zone_entries_to_remove.append(ce)

    # Create Zone Manager entry via config flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "zone_manager_migration"},
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE_MANAGER,
            CONF_INTEGRATION_ENTRY_ID: integration_entry.entry_id,
            "zones": zones_data,
        },
    )

    if result.get("type") == "create_entry":
        _LOGGER.info(
            "Zone Manager entry created with %d zones: %s",
            len(zones_data),
            list(zones_data.keys()),
        )

        # Remove old zone devices from the integration entry's device registry
        from homeassistant.helpers import device_registry as dr
        dev_reg = dr.async_get(hass)

        # Remove Zone Manager device from integration entry (will be recreated under ZM entry)
        zm_device = dev_reg.async_get_device(identifiers={(DOMAIN, "zone_manager")})
        if zm_device:
            dev_reg.async_remove_device(zm_device.id)

        # Remove zone devices (will be recreated under ZM entry)
        for zone_name in zones_data:
            zone_device = dev_reg.async_get_device(identifiers={(DOMAIN, f"zone_{zone_name}")})
            if zone_device:
                dev_reg.async_remove_device(zone_device.id)

        # Remove individual zone config entries
        for ce in zone_entries_to_remove:
            await hass.config_entries.async_remove(ce.entry_id)
            _LOGGER.info("Removed legacy zone entry: %s", ce.title)
    else:
        _LOGGER.error("Failed to create Zone Manager entry: %s", result)


async def _ensure_coordinator_manager_entry(hass: HomeAssistant, integration_entry: ConfigEntry) -> None:
    """Ensure a Coordinator Manager config entry exists (v3.6.0).

    Creates the entry if it doesn't exist. Coordinator sensors will be
    set up via this entry instead of the integration entry.
    Also migrates existing coordinator entities from the integration entry
    to the new Coordinator Manager entry to avoid unique_id conflicts.
    """
    for ce in hass.config_entries.async_entries(DOMAIN):
        if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
            _LOGGER.debug("Coordinator Manager entry already exists")
            return

    # Remove Coordinator Manager device from integration entry (will be recreated)
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er_mod
    dev_reg = dr.async_get(hass)
    ent_reg = er_mod.async_get(hass)

    cm_device = dev_reg.async_get_device(identifiers={(DOMAIN, "coordinator_manager")})
    if cm_device:
        dev_reg.async_remove_device(cm_device.id)

    # Remove old coordinator entity registrations so they can be recreated
    # under the new Coordinator Manager config entry
    coordinator_unique_ids = [
        f"{DOMAIN}_coordinator_manager",
        f"{DOMAIN}_house_state",
        f"{DOMAIN}_coordinator_summary",
    ]
    for uid in coordinator_unique_ids:
        entity = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
        if entity:
            ent_reg.async_remove(entity)
            _LOGGER.info("Removed old coordinator entity %s for re-creation under CM entry", entity)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "coordinator_manager_migration"},
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER,
            CONF_INTEGRATION_ENTRY_ID: integration_entry.entry_id,
        },
    )

    if result.get("type") == "create_entry":
        _LOGGER.info("Coordinator Manager entry created")
    else:
        _LOGGER.error("Failed to create Coordinator Manager entry: %s", result)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Universal Room Automation from a config entry."""
    
    # Initialize hass.data[DOMAIN] if needed
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    
    # MIGRATION: v2.x → v3.0.0
    if not entry.data.get(CONF_ENTRY_TYPE):
        _LOGGER.info("Detected v2.x entry '%s', migrating to v3.0.0", entry.title)
        await _migrate_to_v3(hass, entry)
    
    entry_type = entry.data.get(CONF_ENTRY_TYPE)
    
    if entry_type == ENTRY_TYPE_INTEGRATION:
        # Integration entry - store reference and set up aggregation sensors
        _LOGGER.info("Setting up Universal Room Automation integration entry")
        hass.data[DOMAIN]["integration"] = entry
        
        # v3.3.5.4: Migrate zone names to proper zone entries (run once)
        # v3.5.3: Check entry.data (durable) with fallback to entry.options (legacy)
        if not entry.data.get("zone_migration_done") and not entry.options.get("zone_migration_done"):
            try:
                zones_created = await _migrate_zone_names_to_entries(hass, entry)
                if zones_created >= 0:  # 0 = nothing to migrate, also counts as done
                    hass.config_entries.async_update_entry(
                        entry, data={**entry.data, "zone_migration_done": True}
                    )
                    if zones_created > 0:
                        _LOGGER.info("Zone migration created %d new zone entries", zones_created)
            except Exception as e:
                _LOGGER.error("Zone migration failed: %s", e)
                import traceback
                _LOGGER.error("Traceback: %s", traceback.format_exc())

        # v3.5.3: Clean up orphaned zone devices from pre-v3.3.5.6 or renamed zones
        try:
            from homeassistant.helpers import device_registry as dr
            dev_reg = dr.async_get(hass)
            active_zone_names = set()
            for ce in hass.config_entries.async_entries(DOMAIN):
                if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
                    zn = (ce.data.get(CONF_ZONE_NAME) or ce.options.get(CONF_ZONE_NAME, "")).strip()
                    if zn:
                        active_zone_names.add(zn.lower())

            for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
                for ident_domain, identifier in device.identifiers:
                    if ident_domain == DOMAIN and identifier.startswith("zone_"):
                        zone_name_from_id = identifier[5:]
                        if zone_name_from_id.lower() not in active_zone_names:
                            dev_reg.async_remove_device(device.id)
                            _LOGGER.info("Removed orphaned zone device: %s", identifier)
        except Exception as e:
            _LOGGER.warning("Zone orphan cleanup failed (non-fatal): %s", e)

        # v3.4.5: Migrate room-level camera_person_entities to integration level (run once)
        if not entry.options.get("camera_migration_done"):
            try:
                cameras_migrated = await _migrate_room_cameras_to_integration(hass, entry)
                # Re-read entry after potential update by migration
                entry = hass.config_entries.async_get_entry(entry.entry_id) or entry
                hass.config_entries.async_update_entry(
                    entry, options={**entry.options, "camera_migration_done": True}
                )
                if cameras_migrated > 0:
                    _LOGGER.info(
                        "Camera migration: moved %d camera entity IDs from room entries to integration entry",
                        cameras_migrated,
                    )
            except Exception as e:
                _LOGGER.error("Camera migration failed: %s", e)
                import traceback
                _LOGGER.error("Traceback: %s", traceback.format_exc())

        # v3.6.0: Migrate zone entries to Zone Manager entry and create manager entries
        if not entry.options.get("zone_manager_migration_done"):
            try:
                await _migrate_zones_to_zone_manager(hass, entry)
                entry = hass.config_entries.async_get_entry(entry.entry_id) or entry
                hass.config_entries.async_update_entry(
                    entry, options={**entry.options, "zone_manager_migration_done": True}
                )
            except Exception as e:
                _LOGGER.error("Zone manager migration failed: %s", e)
                import traceback
                _LOGGER.error("Traceback: %s", traceback.format_exc())

        # v3.6.0: Ensure Coordinator Manager entry exists
        if not entry.options.get("coordinator_manager_entry_done"):
            try:
                await _ensure_coordinator_manager_entry(hass, entry)
                entry = hass.config_entries.async_get_entry(entry.entry_id) or entry
                hass.config_entries.async_update_entry(
                    entry, options={**entry.options, "coordinator_manager_entry_done": True}
                )
            except Exception as e:
                _LOGGER.error("Coordinator manager entry creation failed: %s", e)

        # v3.5.x: Migrate person-sensor unique_ids from "occupant" to "identified" naming (run once)
        if not entry.options.get("sensor_naming_migration_done"):
            try:
                sensors_renamed = await _migrate_sensor_entity_ids(hass)
                # Re-read entry after options may have been updated by prior migrations
                entry = hass.config_entries.async_get_entry(entry.entry_id) or entry
                hass.config_entries.async_update_entry(
                    entry, options={**entry.options, "sensor_naming_migration_done": True}
                )
                if sensors_renamed > 0:
                    _LOGGER.info(
                        "Sensor naming migration: updated %d entity unique_ids to use 'identified' naming",
                        sensors_renamed,
                    )
            except Exception as e:
                _LOGGER.error("Sensor naming migration failed: %s", e)
                import traceback
                _LOGGER.error("Traceback: %s", traceback.format_exc())

        # v3.6.0-c2.9.2: Remove stale coordinator-level safety_alert entity
        # that collides with the room-level one in aggregation.py.
        # The coordinator sensor was renamed to _safety_coordinator_safety_alert.
        if not entry.options.get("safety_alert_dedup_done"):
            try:
                from homeassistant.helpers import entity_registry as er_mod
                ent_reg = er_mod.async_get(hass)
                stale_uid = f"{DOMAIN}_safety_alert"
                # Check if the stale unique_id is registered under a coordinator device
                stale_eid = ent_reg.async_get_entity_id(
                    "binary_sensor", DOMAIN, stale_uid
                )
                if stale_eid:
                    stale_entry = ent_reg.async_get(stale_eid)
                    # Only remove if it belongs to the safety_coordinator device
                    if stale_entry and stale_entry.device_id:
                        from homeassistant.helpers import device_registry as dr
                        dev_reg = dr.async_get(hass)
                        device = dev_reg.async_get(stale_entry.device_id)
                        if device and (DOMAIN, "safety_coordinator") in device.identifiers:
                            ent_reg.async_remove(stale_eid)
                            _LOGGER.info(
                                "Removed stale coordinator safety_alert entity %s (unique_id collision fix)",
                                stale_eid,
                            )
                entry = hass.config_entries.async_get_entry(entry.entry_id) or entry
                hass.config_entries.async_update_entry(
                    entry, options={**entry.options, "safety_alert_dedup_done": True}
                )
            except Exception as e:
                _LOGGER.debug("Safety alert dedup migration: %s", e)

        # Initialize database (shared across all rooms)
        if "database" not in hass.data[DOMAIN]:
            database = UniversalRoomDatabase(hass)
            if await database.initialize():
                hass.data[DOMAIN]["database"] = database
                _LOGGER.info("Database initialized successfully")
            else:
                _LOGGER.warning("Database initialization failed")
        
        # v3.2.0: Initialize person tracking coordinator if persons are configured
        # FIX v3.2.3.1: Read from options first (where UI saves), then fall back to data
        merged_config = {**entry.data, **entry.options}

        # v3.5.0: Initialize camera integration manager and person census
        # NOTE: Must init BEFORE transit validator (inside tracked_persons block)
        # which reads hass.data[DOMAIN]["camera_manager"] during async_init().
        # Kept outside tracked_persons block so cameras work without BLE persons.
        try:
            camera_manager = CameraIntegrationManager(hass)
            room_cameras = merged_config.get(CONF_CAMERA_PERSON_ENTITIES, [])
            egress_cameras = merged_config.get(CONF_EGRESS_CAMERAS, [])
            perimeter_cameras = merged_config.get(CONF_PERIMETER_CAMERAS, [])
            await camera_manager.async_discover(
                room_cameras=room_cameras,
                egress_cameras=egress_cameras,
                perimeter_cameras=perimeter_cameras,
            )
            hass.data[DOMAIN]["camera_manager"] = camera_manager

            census = PersonCensus(hass, camera_manager)
            hass.data[DOMAIN]["census"] = census

            # Periodic census updates
            async def _census_update_cb(_now):
                """Periodic callback for census updates."""
                try:
                    await census.async_update_census()
                except Exception as exc:
                    _LOGGER.error("Census periodic update failed: %s", exc)

            unsub_census = async_track_time_interval(
                hass, _census_update_cb, SCAN_INTERVAL_CENSUS
            )
            hass.data[DOMAIN]["unsub_census"] = unsub_census

            _LOGGER.info(
                "Camera census initialized with periodic updates (cameras discovered: %d, interval: %s)",
                len(camera_manager.get_all_frigate_cameras())
                + len(camera_manager.get_all_unifi_cameras()),
                SCAN_INTERVAL_CENSUS,
            )

            # v3.10.1: Event-driven census triggers (when enhanced census enabled)
            enhanced = merged_config.get(CONF_ENHANCED_CENSUS, True)
            if enhanced:
                import time as _time
                _last_event_census_time = 0.0

                async def _event_census_trigger(event):
                    """Trigger immediate census on detection event (debounced)."""
                    nonlocal _last_event_census_time
                    now = _time.monotonic()
                    if now - _last_event_census_time < CENSUS_EVENT_DEBOUNCE_SECONDS:
                        return
                    _last_event_census_time = now
                    try:
                        await census.async_update_census()
                    except Exception as exc:
                        _LOGGER.warning("Event-triggered census update failed: %s", exc)

                # Collect person detection entity IDs to watch
                _person_detection_entities = []
                for cam_info in camera_manager.get_all_frigate_cameras():
                    if cam_info.entity_id:
                        _person_detection_entities.append(cam_info.entity_id)
                for cam_info in camera_manager.get_all_unifi_cameras():
                    if cam_info.person_binary_sensor:
                        _person_detection_entities.append(cam_info.person_binary_sensor)

                unsub_event_listeners = []
                if _person_detection_entities:
                    unsub = async_track_state_change_event(
                        hass, _person_detection_entities, _event_census_trigger
                    )
                    unsub_event_listeners.append(unsub)

                # Watch Bermuda global device count for new BLE devices
                # Always register even if entity doesn't exist yet —
                # async_track_state_change_event will fire when it first appears
                unsub = async_track_state_change_event(
                    hass,
                    ["sensor.bermuda_global_total_device_count"],
                    _event_census_trigger,
                )
                unsub_event_listeners.append(unsub)

                hass.data[DOMAIN]["unsub_census_events"] = unsub_event_listeners
                _LOGGER.info(
                    "Enhanced census v2: watching %d detection entities + BLE count",
                    len(_person_detection_entities),
                )
        except Exception as e:
            _LOGGER.error("Failed to initialize camera census: %s", e)

        tracked_person_entities = merged_config.get(CONF_TRACKED_PERSONS, [])
        if tracked_person_entities:
            try:
                # Convert entity IDs to person names
                # Config flow returns ["person.oji", "person.ezinne"]
                # Coordinator expects ["Oji", "Ezinne"]
                tracked_persons = []
                for entity_id in tracked_person_entities:
                    if entity_id.startswith("person."):
                        # Extract name from entity_id (person.oji -> Oji)
                        person_name = entity_id.replace("person.", "").replace("_", " ").title()
                        tracked_persons.append(person_name)
                    else:
                        # Already a name, just title case it
                        tracked_persons.append(entity_id.replace("_", " ").title())
                
                # UPDATE the entry.data directly so aggregation.py also sees person names
                hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_TRACKED_PERSONS: tracked_persons}
                )
                
                # Now create coordinator with the updated entry
                person_coordinator = PersonTrackingCoordinator(hass, entry)
                await person_coordinator.async_config_entry_first_refresh()
                hass.data[DOMAIN]["person_coordinator"] = person_coordinator
                _LOGGER.info("Person tracking coordinator initialized for %d persons: %s", len(tracked_persons), tracked_persons)
                
                # v3.3.0: Initialize cross-room coordination components
                try:
                    from .transitions import TransitionDetector
                    from .pattern_learning import PatternLearner
                    from .music_following import MusicFollowing
                    
                    # Get database reference
                    database = hass.data[DOMAIN].get("database")
                    
                    # Initialize transition detector
                    _LOGGER.debug("Initializing TransitionDetector...")
                    transition_detector = TransitionDetector(
                        hass,
                        person_coordinator,
                        database
                    )
                    await transition_detector.async_init()
                    hass.data[DOMAIN]["transition_detector"] = transition_detector
                    _LOGGER.info("✓ TransitionDetector initialized successfully")
                    
                    # Initialize pattern learner
                    _LOGGER.debug("Initializing PatternLearner...")
                    pattern_learner = PatternLearner(hass, database)
                    hass.data[DOMAIN]["pattern_learner"] = pattern_learner
                    _LOGGER.info("✓ PatternLearner initialized successfully")
                    
                    # Initialize music following
                    _LOGGER.debug("Initializing MusicFollowing...")
                    music_following = MusicFollowing(
                        hass,
                        merged_config,
                        transition_detector
                    )
                    await music_following.async_init()
                    hass.data[DOMAIN]["music_following"] = music_following
                    _LOGGER.info("✓ MusicFollowing initialized successfully")
                    
                    # Enable music following for all tracked persons by default
                    for person_name in tracked_persons:
                        music_following.enable_for_person(person_name)

                    # v3.5.2: Transit validation and egress direction tracking
                    # NOTE: camera_manager + census init moved before tracked_persons
                    # block (v3.6.33) so they're always available.
                    try:
                        from .transit_validator import TransitValidator, EgressDirectionTracker

                        transit_validator = TransitValidator(hass)
                        await transit_validator.async_init()
                        hass.data[DOMAIN]["transit_validator"] = transit_validator

                        # Wire validator into transition detector
                        transition_detector.set_transit_validator(transit_validator)

                        egress_tracker = EgressDirectionTracker(hass)
                        await egress_tracker.async_init()
                        hass.data[DOMAIN]["egress_tracker"] = egress_tracker

                        _LOGGER.info("Transit validation and egress direction tracking initialized")
                    except Exception as e:
                        _LOGGER.warning(
                            "Transit validation init failed — sensor predictions will work "
                            "without camera enrichment: %s",
                            e,
                        )

                except ImportError as e:
                    _LOGGER.warning("Cross-room coordination modules not available: %s", e)
                except Exception as e:
                    _LOGGER.error("Failed to initialize cross-room coordination: %s", e)
                    import traceback
                    _LOGGER.error("Traceback: %s", traceback.format_exc())

            except Exception as e:
                _LOGGER.error("Failed to initialize person tracking coordinator: %s", e)
                import traceback
                _LOGGER.error("Traceback: %s", traceback.format_exc())
        else:
            _LOGGER.info("No tracked persons configured, skipping person coordinator")

        # v3.5.1: Initialize perimeter alert manager
        try:
            perimeter_alert_manager = PerimeterAlertManager(hass)
            await perimeter_alert_manager.async_setup()
            hass.data[DOMAIN]["perimeter_alert_manager"] = perimeter_alert_manager
            _LOGGER.info(
                "Perimeter alert manager initialized (active: %s)",
                perimeter_alert_manager.is_active,
            )
        except Exception as e:
            _LOGGER.error("Failed to initialize perimeter alert manager: %s", e)

        # v3.6.0: Initialize domain coordinator manager if enabled
        # NOTE: Zone Manager and Coordinator Manager devices are now registered
        # under their own config entries (not under the integration entry).
        # This prevents duplicate display on the integration page.
        if merged_config.get(CONF_DOMAIN_COORDINATORS_ENABLED, False):
            try:
                from .domain_coordinators.manager import CoordinatorManager
                from .const import (
                    CONF_SLEEP_START_HOUR,
                    CONF_SLEEP_END_HOUR,
                    CONF_GEOFENCE_ENTITIES,
                    CONF_WATER_SHUTOFF_VALVE,
                    CONF_EMERGENCY_LIGHT_ENTITIES,
                    CONF_PRESENCE_ENABLED,
                    CONF_SAFETY_ENABLED,
                    CONF_SECURITY_ENABLED,
                    CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED,
                    DEFAULT_SLEEP_START_HOUR,
                    DEFAULT_SLEEP_END_HOUR,
                )

                # v3.6.0-c2.1: Read coordinator settings from CM entry options.
                # Settings are stored in the CM entry by the coordinator config steps.
                # Fall back to integration merged_config for backward compatibility.
                cm_config: dict = {}
                for ce in hass.config_entries.async_entries(DOMAIN):
                    if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                        cm_config = {**ce.data, **ce.options}
                        break

                coordinator_manager = CoordinatorManager(hass)

                # v3.6.0-c1: Register Presence Coordinator
                if cm_config.get(CONF_PRESENCE_ENABLED, True):
                    from .domain_coordinators.presence import PresenceCoordinator
                    presence = PresenceCoordinator(
                        hass,
                        sleep_start_hour=int(cm_config.get(
                            CONF_SLEEP_START_HOUR,
                            merged_config.get(
                                CONF_SLEEP_START_HOUR, DEFAULT_SLEEP_START_HOUR
                            ),
                        )),
                        sleep_end_hour=int(cm_config.get(
                            CONF_SLEEP_END_HOUR,
                            merged_config.get(
                                CONF_SLEEP_END_HOUR, DEFAULT_SLEEP_END_HOUR
                            ),
                        )),
                    )
                    coordinator_manager.register_coordinator(presence)
                else:
                    _LOGGER.info("Presence Coordinator disabled via config")

                # v3.6.0-c2: Register Safety Coordinator
                if cm_config.get(CONF_SAFETY_ENABLED, True):
                    from .domain_coordinators.safety import SafetyCoordinator
                    safety = SafetyCoordinator(
                        hass,
                        water_shutoff_valve=cm_config.get(CONF_WATER_SHUTOFF_VALVE),
                        emergency_lights=cm_config.get(
                            CONF_EMERGENCY_LIGHT_ENTITIES, []
                        ),
                    )
                    coordinator_manager.register_coordinator(safety)
                else:
                    _LOGGER.info("Safety Coordinator disabled via config")

                # v3.6.0-c3: Register Security Coordinator
                if cm_config.get(CONF_SECURITY_ENABLED, True):
                    from .domain_coordinators.security import SecurityCoordinator
                    from .const import (
                        CONF_SECURITY_LOCK_ENTITIES,
                        CONF_SECURITY_GARAGE_ENTITIES,
                        CONF_SECURITY_ENTRY_SENSORS,
                        CONF_SECURITY_LIGHT_ENTITIES,
                        CONF_SECURITY_CAMERA_ENTITIES,
                        CONF_SECURITY_CAMERA_RECORDING,
                        CONF_SECURITY_CAMERA_RECORD_DURATION,
                        CONF_SECURITY_ALARM_PANEL,
                        CONF_SECURITY_AUTO_FOLLOW,
                        CONF_SECURITY_LOCK_CHECK_INTERVAL,
                        CONF_SECURITY_DELEGATE_LIGHTS_TO_NM,
                    )
                    security = SecurityCoordinator(
                        hass,
                        lock_entities=cm_config.get(CONF_SECURITY_LOCK_ENTITIES, []),
                        garage_entities=cm_config.get(CONF_SECURITY_GARAGE_ENTITIES, []),
                        entry_sensors=cm_config.get(CONF_SECURITY_ENTRY_SENSORS, []),
                        security_lights=cm_config.get(CONF_SECURITY_LIGHT_ENTITIES, []),
                        camera_entities=cm_config.get(CONF_SECURITY_CAMERA_ENTITIES, []),
                        camera_recording_enabled=cm_config.get(
                            CONF_SECURITY_CAMERA_RECORDING, False
                        ),
                        camera_record_duration=int(cm_config.get(
                            CONF_SECURITY_CAMERA_RECORD_DURATION, 30
                        )),
                        alarm_panel_entity=cm_config.get(CONF_SECURITY_ALARM_PANEL),
                        auto_follow_house_state=cm_config.get(
                            CONF_SECURITY_AUTO_FOLLOW, False
                        ),
                        lock_check_interval=int(cm_config.get(
                            CONF_SECURITY_LOCK_CHECK_INTERVAL, 30
                        )),
                        delegate_lights_to_nm=cm_config.get(
                            CONF_SECURITY_DELEGATE_LIGHTS_TO_NM, True
                        ),
                    )
                    coordinator_manager.register_coordinator(security)
                else:
                    _LOGGER.info("Security Coordinator disabled via config")

                # v3.6.24: Register Music Following Coordinator
                if cm_config.get(CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED, True):
                    from .domain_coordinators.music_following import (
                        MusicFollowingCoordinator,
                    )
                    from .const import (
                        CONF_MF_COOLDOWN_SECONDS,
                        CONF_MF_HIGH_CONFIDENCE_DISTANCE,
                        CONF_MF_PING_PONG_WINDOW,
                        CONF_MF_VERIFY_DELAY,
                        CONF_MF_UNJOIN_DELAY,
                        CONF_MF_POSITION_OFFSET,
                        CONF_MF_MIN_CONFIDENCE,
                        DEFAULT_MF_COOLDOWN_SECONDS,
                        DEFAULT_MF_HIGH_CONFIDENCE_DISTANCE,
                        DEFAULT_MF_PING_PONG_WINDOW,
                        DEFAULT_MF_VERIFY_DELAY,
                        DEFAULT_MF_UNJOIN_DELAY,
                        DEFAULT_MF_POSITION_OFFSET,
                        DEFAULT_MF_MIN_CONFIDENCE,
                    )
                    mf_coordinator = MusicFollowingCoordinator(
                        hass,
                        cooldown_seconds=int(cm_config.get(
                            CONF_MF_COOLDOWN_SECONDS, DEFAULT_MF_COOLDOWN_SECONDS
                        )),
                        ping_pong_window=int(cm_config.get(
                            CONF_MF_PING_PONG_WINDOW, DEFAULT_MF_PING_PONG_WINDOW
                        )),
                        verify_delay=int(cm_config.get(
                            CONF_MF_VERIFY_DELAY, DEFAULT_MF_VERIFY_DELAY
                        )),
                        unjoin_delay=int(cm_config.get(
                            CONF_MF_UNJOIN_DELAY, DEFAULT_MF_UNJOIN_DELAY
                        )),
                        position_offset=int(cm_config.get(
                            CONF_MF_POSITION_OFFSET, DEFAULT_MF_POSITION_OFFSET
                        )),
                        min_confidence=float(cm_config.get(
                            CONF_MF_MIN_CONFIDENCE, DEFAULT_MF_MIN_CONFIDENCE
                        )),
                        high_confidence_distance=float(cm_config.get(
                            CONF_MF_HIGH_CONFIDENCE_DISTANCE, DEFAULT_MF_HIGH_CONFIDENCE_DISTANCE
                        )),
                    )
                    coordinator_manager.register_coordinator(mf_coordinator)
                else:
                    _LOGGER.info("Music Following Coordinator disabled via config")

                # v3.7.0-E1: Register Energy Coordinator
                from .const import CONF_ENERGY_ENABLED
                if cm_config.get(CONF_ENERGY_ENABLED, False):
                    from .domain_coordinators.energy import EnergyCoordinator
                    from .domain_coordinators.energy_const import (
                        CONF_ENERGY_RESERVE_SOC,
                        CONF_ENERGY_DECISION_INTERVAL,
                        CONF_ENERGY_EVSE_A_ENTITY,
                        CONF_ENERGY_EVSE_B_ENTITY,
                        CONF_ENERGY_L1_CHARGER_ENTITIES,
                        CONF_ENERGY_WEATHER_ENTITY,
                        CONF_ENERGY_SOLAR_CLASSIFICATION_MODE,
                        CONF_ENERGY_SOLAR_THRESHOLD_EXCELLENT,
                        CONF_ENERGY_SOLAR_THRESHOLD_GOOD,
                        CONF_ENERGY_SOLAR_THRESHOLD_MODERATE,
                        CONF_ENERGY_SOLAR_THRESHOLD_POOR,
                        DEFAULT_RESERVE_SOC,
                        DEFAULT_DECISION_INTERVAL_MINUTES,
                        DEFAULT_L1_CHARGER_ENTITIES,
                        SOLAR_CLASS_MODE_AUTOMATIC,
                    )
                    energy_entity_config = {}
                    # Pull any energy config from cm_config (entities + E6 options)
                    for key in cm_config:
                        if key.startswith("energy_"):
                            energy_entity_config[key] = cm_config[key]

                    # Weather entity: use EC config, fall back to house entry
                    if CONF_ENERGY_WEATHER_ENTITY not in energy_entity_config:
                        integration = hass.data.get(DOMAIN, {}).get("integration")
                        if integration:
                            house_weather = (
                                integration.options.get(CONF_WEATHER_ENTITY)
                                or integration.data.get(CONF_WEATHER_ENTITY)
                            )
                            if house_weather:
                                energy_entity_config[CONF_ENERGY_WEATHER_ENTITY] = house_weather

                    # EVSE config — EVChargerController expects nested dicts
                    # with at minimum a "power" key per charger
                    from .domain_coordinators.energy_pool import DEFAULT_EVSE_ENTITIES
                    evse_config = {}
                    for evse_id, defaults in DEFAULT_EVSE_ENTITIES.items():
                        evse_config[evse_id] = dict(defaults)
                    # Override power entities from user config
                    evse_a_power = cm_config.get(CONF_ENERGY_EVSE_A_ENTITY)
                    if evse_a_power:
                        evse_config["garage_a"]["power"] = evse_a_power
                    evse_b_power = cm_config.get(CONF_ENERGY_EVSE_B_ENTITY)
                    if evse_b_power:
                        evse_config["garage_b"]["power"] = evse_b_power

                    # Smart plug entities
                    smart_plug_entities = cm_config.get(
                        CONF_ENERGY_L1_CHARGER_ENTITIES,
                        DEFAULT_L1_CHARGER_ENTITIES,
                    )

                    # Solar classification config
                    solar_mode = cm_config.get(
                        CONF_ENERGY_SOLAR_CLASSIFICATION_MODE,
                        SOLAR_CLASS_MODE_AUTOMATIC,
                    )
                    custom_solar_thresholds = None
                    if solar_mode == "custom":
                        custom_solar_thresholds = {
                            "excellent": float(cm_config.get(CONF_ENERGY_SOLAR_THRESHOLD_EXCELLENT, 100.0)),
                            "good": float(cm_config.get(CONF_ENERGY_SOLAR_THRESHOLD_GOOD, 80.0)),
                            "moderate": float(cm_config.get(CONF_ENERGY_SOLAR_THRESHOLD_MODERATE, 50.0)),
                            "poor": float(cm_config.get(CONF_ENERGY_SOLAR_THRESHOLD_POOR, 30.0)),
                        }

                    energy = EnergyCoordinator(
                        hass,
                        reserve_soc=int(cm_config.get(
                            CONF_ENERGY_RESERVE_SOC, DEFAULT_RESERVE_SOC
                        )),
                        decision_interval=int(cm_config.get(
                            CONF_ENERGY_DECISION_INTERVAL,
                            DEFAULT_DECISION_INTERVAL_MINUTES,
                        )),
                        entity_config=energy_entity_config or None,
                        evse_config=evse_config,
                        smart_plug_entities=smart_plug_entities,
                        solar_classification_mode=solar_mode,
                        custom_solar_thresholds=custom_solar_thresholds,
                    )
                    coordinator_manager.register_coordinator(energy)
                else:
                    _LOGGER.info("Energy Coordinator disabled via config")

                # v3.8.0-H1: Register HVAC Coordinator
                from .const import CONF_HVAC_ENABLED
                if cm_config.get(CONF_HVAC_ENABLED, False):
                    from .domain_coordinators.hvac import HVACCoordinator
                    from .domain_coordinators.hvac_const import (
                        CONF_HVAC_MAX_SLEEP_OFFSET,
                        CONF_HVAC_COMPROMISE_MINUTES,
                        CONF_HVAC_AC_RESET_TIMEOUT,
                        CONF_HVAC_FAN_ACTIVATION_DELTA,
                        CONF_HVAC_FAN_HYSTERESIS,
                        CONF_HVAC_FAN_MIN_RUNTIME,
                        CONF_HVAC_ARRESTER_ENABLED,
                        CONF_HVAC_VACANCY_GRACE_MINUTES,
                        CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
                        CONF_HVAC_MAX_OCCUPANCY_HOURS,
                        CONF_PERSON_PREFERRED_ZONES,
                        DEFAULT_MAX_SLEEP_OFFSET,
                        DEFAULT_COMPROMISE_MINUTES,
                        DEFAULT_AC_RESET_TIMEOUT,
                        DEFAULT_FAN_ACTIVATION_DELTA,
                        DEFAULT_FAN_HYSTERESIS,
                        DEFAULT_FAN_MIN_RUNTIME,
                        DEFAULT_ARRESTER_ENABLED,
                        DEFAULT_VACANCY_GRACE_MINUTES,
                        DEFAULT_VACANCY_GRACE_CONSTRAINED,
                        DEFAULT_MAX_OCCUPANCY_HOURS,
                    )
                    # v3.17.0: Parse person_preferred_zones JSON dict
                    import json as _json
                    _raw_pzm = cm_config.get(CONF_PERSON_PREFERRED_ZONES, "{}")
                    if isinstance(_raw_pzm, str):
                        try:
                            _person_zone_map = _json.loads(_raw_pzm)
                        except (ValueError, TypeError):
                            _person_zone_map = {}
                    elif isinstance(_raw_pzm, dict):
                        _person_zone_map = _raw_pzm
                    else:
                        _person_zone_map = {}

                    hvac = HVACCoordinator(
                        hass,
                        max_sleep_offset=float(cm_config.get(
                            CONF_HVAC_MAX_SLEEP_OFFSET, DEFAULT_MAX_SLEEP_OFFSET
                        )),
                        compromise_minutes=int(cm_config.get(
                            CONF_HVAC_COMPROMISE_MINUTES, DEFAULT_COMPROMISE_MINUTES
                        )),
                        ac_reset_timeout=int(cm_config.get(
                            CONF_HVAC_AC_RESET_TIMEOUT, DEFAULT_AC_RESET_TIMEOUT
                        )),
                        fan_activation_delta=float(cm_config.get(
                            CONF_HVAC_FAN_ACTIVATION_DELTA, DEFAULT_FAN_ACTIVATION_DELTA
                        )),
                        fan_hysteresis=float(cm_config.get(
                            CONF_HVAC_FAN_HYSTERESIS, DEFAULT_FAN_HYSTERESIS
                        )),
                        fan_min_runtime=int(cm_config.get(
                            CONF_HVAC_FAN_MIN_RUNTIME, DEFAULT_FAN_MIN_RUNTIME
                        )),
                        arrester_enabled=bool(cm_config.get(
                            CONF_HVAC_ARRESTER_ENABLED, DEFAULT_ARRESTER_ENABLED
                        )),
                        vacancy_grace=int(cm_config.get(
                            CONF_HVAC_VACANCY_GRACE_MINUTES, DEFAULT_VACANCY_GRACE_MINUTES
                        )),
                        vacancy_grace_constrained=int(cm_config.get(
                            CONF_HVAC_VACANCY_GRACE_CONSTRAINED, DEFAULT_VACANCY_GRACE_CONSTRAINED
                        )),
                        max_occupancy_hours=int(cm_config.get(
                            CONF_HVAC_MAX_OCCUPANCY_HOURS, DEFAULT_MAX_OCCUPANCY_HOURS
                        )),
                        person_zone_map=_person_zone_map,
                    )
                    coordinator_manager.register_coordinator(hvac)
                else:
                    _LOGGER.info("HVAC Coordinator disabled via config")

                # v3.6.29: Register Notification Manager
                from .const import CONF_NM_ENABLED
                if cm_config.get(CONF_NM_ENABLED, False):
                    from .domain_coordinators.notification_manager import (
                        NotificationManager,
                    )
                    nm = NotificationManager(hass, cm_config)
                    coordinator_manager.set_notification_manager(nm)
                else:
                    _LOGGER.info("Notification Manager disabled via config")

                await coordinator_manager.async_start()
                hass.data[DOMAIN]["coordinator_manager"] = coordinator_manager
                _LOGGER.info("Domain Coordinator Manager initialized and started")
            except Exception as e:
                _LOGGER.error("Failed to initialize Coordinator Manager: %s", e)
                import traceback
                _LOGGER.error("Traceback: %s", traceback.format_exc())
        else:
            _LOGGER.warning(
                "Domain coordinators NOT enabled. "
                "Set domain_coordinators_enabled=True in integration options. "
                "merged_config keys: %s",
                list(merged_config.keys()),
            )

        # v3.6.0-c1: Register house state services
        await _async_register_presence_services(hass)

        # v3.6.0-c2: Register safety services
        await _async_register_safety_services(hass)

        # v3.6.0-c3: Register security services
        await _async_register_security_services(hass)

        # v3.6.29: Register notification manager services
        await _async_register_notification_services(hass)

        # Set up aggregation sensors (sensor and binary_sensor platforms)
        # These will be registered via the platform files
        await hass.config_entries.async_forward_entry_setups(entry, INTEGRATION_PLATFORMS)
        
        # v3.2.5: Add update listener to reload entry when options change
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        
        # v3.9.4: Register URA Dashboard panel (panel_custom with auth passthrough)
        import os
        frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
        if os.path.isdir(frontend_path):
            try:
                from homeassistant.components.http import StaticPathConfig
                panel_url = f"/{DOMAIN}_panel"
                await hass.http.async_register_static_paths(
                    [StaticPathConfig(panel_url, frontend_path, False)]
                )
                from homeassistant.components import panel_custom
                await panel_custom.async_register_panel(
                    hass,
                    webcomponent_name="ura-dashboard-panel",
                    frontend_url_path="ura-dashboard",
                    sidebar_title="URA",
                    sidebar_icon="mdi:home-automation",
                    module_url=f"{panel_url}/ura-panel.js",
                    embed_iframe=False,
                    require_admin=False,
                    config={},
                )
                _LOGGER.info("URA Dashboard panel registered at /ura-dashboard")
            except Exception as exc:
                _LOGGER.warning("Failed to register URA Dashboard panel: %s", exc)

        # v3.12.0: Register URA Dashboard v3 panel (separate sidebar entry)
        frontend_v3_path = os.path.join(os.path.dirname(__file__), "frontend-v3")
        if os.path.isdir(frontend_v3_path):
            try:
                from homeassistant.components.http import StaticPathConfig
                panel_v3_url = f"/{DOMAIN}_panel_v3"
                await hass.http.async_register_static_paths(
                    [StaticPathConfig(panel_v3_url, frontend_v3_path, False)]
                )
                from homeassistant.components import panel_custom
                await panel_custom.async_register_panel(
                    hass,
                    webcomponent_name="ura-dashboard-panel-v3",
                    frontend_url_path="ura-dashboard-v3",
                    sidebar_title="URA Dashboard",
                    sidebar_icon="mdi:view-dashboard",
                    module_url=f"{panel_v3_url}/ura-panel-v3.js",
                    embed_iframe=False,
                    require_admin=False,
                    config={},
                )
                _LOGGER.info("URA Dashboard v3 panel registered at /ura-dashboard-v3")
            except Exception as exc:
                _LOGGER.warning("Failed to register URA Dashboard v3 panel: %s", exc)

        _LOGGER.info("Integration entry setup complete with aggregation sensors")
        return True
    
    # =========================================================================
    # v3.6.0: Zone Manager entry handling
    # =========================================================================
    if entry_type == ENTRY_TYPE_ZONE_MANAGER:
        _LOGGER.info("Setting up Zone Manager entry")

        # Register Zone Manager device under THIS config entry (not integration)
        from homeassistant.helpers import device_registry as dr
        dev_reg = dr.async_get(hass)
        dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "zone_manager")},
            name="URA: Zone Manager",
            manufacturer="Universal Room Automation",
            model="Zone Manager",
            sw_version=VERSION,
        )

        # v3.6.0-c2.1: Clean up orphaned zone devices with slugified identifiers.
        # Prior to this fix, select.py used zone_slug (lowercased+underscored) for
        # device identifiers while aggregation.py used raw zone names, creating
        # duplicate "Unnamed device" entries. Remove any zone_<slug> devices that
        # don't match a zone_<RawName> pattern.
        try:
            merged_zm = {**entry.data, **entry.options}
            raw_zone_ids = {f"zone_{zn}" for zn in merged_zm.get("zones", {})}
            for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
                for ident_domain, identifier in device.identifiers:
                    if (
                        ident_domain == DOMAIN
                        and identifier.startswith("zone_")
                        and identifier != "zone_manager"
                        and identifier not in raw_zone_ids
                    ):
                        dev_reg.async_remove_device(device.id)
                        _LOGGER.info(
                            "Removed orphaned slugified zone device: %s", identifier
                        )
        except Exception as e:
            _LOGGER.warning("Zone slug cleanup failed (non-fatal): %s", e)

        # Store zone data reference for music_following and other lookups
        if "zones" not in hass.data[DOMAIN]:
            hass.data[DOMAIN]["zones"] = {}
        hass.data[DOMAIN]["zone_manager_entry"] = entry

        # Forward sensor/binary_sensor platforms — zone sensors created here
        await hass.config_entries.async_forward_entry_setups(entry, INTEGRATION_PLATFORMS)

        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        _LOGGER.info("Zone Manager entry setup complete")
        return True

    # =========================================================================
    # v3.6.0: Coordinator Manager entry handling
    # =========================================================================
    if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:
        _LOGGER.info("Setting up Coordinator Manager entry")

        # Register Coordinator Manager device under THIS config entry
        from homeassistant.helpers import device_registry as dr
        dev_reg = dr.async_get(hass)
        dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

        # Forward sensor/binary_sensor platforms — coordinator sensors created here
        await hass.config_entries.async_forward_entry_setups(entry, INTEGRATION_PLATFORMS)

        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        _LOGGER.info("Coordinator Manager entry setup complete")
        return True

    # =========================================================================
    # v3.3.2: Legacy zone entry handling (deprecated — migrated to Zone Manager)
    # =========================================================================
    if entry_type == ENTRY_TYPE_ZONE:
        zone_name = entry.data.get(CONF_ZONE_NAME, "Unknown")
        _LOGGER.warning(
            "Legacy zone entry '%s' found — should have been migrated to Zone Manager. "
            "Skipping setup; zone sensors are now managed by the Zone Manager entry.",
            zone_name,
        )
        return True
    
    # Room entry - normal setup
    _LOGGER.info(
        "Setting up Universal Room Automation for room: %s",
        entry.data.get("room_name")
    )
    
    # Initialize database (shared across all rooms)
    if "database" not in hass.data[DOMAIN]:
        database = UniversalRoomDatabase(hass)
        if await database.initialize():
            hass.data[DOMAIN]["database"] = database
            _LOGGER.info("Database initialized successfully")
        else:
            _LOGGER.warning("Database initialization failed")
    
    # Create coordinator
    coordinator = UniversalRoomCoordinator(hass, entry)
    
    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()
    
    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator
    
    # v3.2.5: Add update listener to reload entry when options change
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    
    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    _LOGGER.info(
        "Successfully set up Universal Room Automation for room: %s",
        entry.data.get("room_name")
    )
    
    return True


async def _migrate_to_v3(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate a v2.x entry to v3.0.0 format.
    
    v2.x: Single entry with all room config
    v3.0.0: Integration entry + Room entries
    
    Migration:
    1. Create new integration entry with defaults
    2. Convert current entry to room entry
    """
    _LOGGER.info("Starting migration from v2.x to v3.0.0")
    
    # Check if integration entry already exists
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
            _LOGGER.info("Integration entry already exists, skipping creation")
            # Just update current entry to be a room
            new_data = dict(entry.data)
            new_data[CONF_ENTRY_TYPE] = ENTRY_TYPE_ROOM
            new_data[CONF_INTEGRATION_ENTRY_ID] = e.entry_id
            hass.config_entries.async_update_entry(entry, data=new_data)
            return
    
    # Create new integration entry with defaults
    _LOGGER.info("Creating new integration entry")
    integration_entry = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "migration"},
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
            CONF_OUTSIDE_TEMP_SENSOR: entry.data.get(CONF_OUTSIDE_TEMP_SENSOR),
            CONF_OUTSIDE_HUMIDITY_SENSOR: entry.data.get(CONF_OUTSIDE_HUMIDITY_SENSOR),
            CONF_WEATHER_ENTITY: entry.data.get(CONF_WEATHER_ENTITY),
            CONF_SOLAR_PRODUCTION_SENSOR: entry.data.get(CONF_SOLAR_PRODUCTION_SENSOR),
            CONF_ELECTRICITY_RATE: entry.data.get(CONF_ELECTRICITY_RATE, DEFAULT_ELECTRICITY_RATE),
            CONF_NOTIFY_SERVICE: entry.data.get(CONF_NOTIFY_SERVICE),
            CONF_NOTIFY_TARGET: entry.data.get(CONF_NOTIFY_TARGET),
            CONF_NOTIFY_LEVEL: entry.data.get(CONF_NOTIFY_LEVEL, NOTIFY_LEVEL_ERRORS),
        }
    )
    
    # Update current entry to be a room entry
    # Find integration entry ID
    integration_entry_id = None
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
            integration_entry_id = e.entry_id
            break
    
    new_data = dict(entry.data)
    new_data[CONF_ENTRY_TYPE] = ENTRY_TYPE_ROOM
    if integration_entry_id:
        new_data[CONF_INTEGRATION_ENTRY_ID] = integration_entry_id
    
    hass.config_entries.async_update_entry(entry, data=new_data)
    
    _LOGGER.info("Migration complete: entry '%s' converted to room entry", entry.title)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE)
    
    if entry_type == ENTRY_TYPE_INTEGRATION:
        # Unload aggregation platforms
        unload_ok = await hass.config_entries.async_unload_platforms(entry, INTEGRATION_PLATFORMS)
        
        # Clean up person tracking
        if "person_coordinator" in hass.data[DOMAIN]:
            del hass.data[DOMAIN]["person_coordinator"]
        
        # Clean up cross-room coordination
        for key in ["transition_detector", "pattern_learner", "music_following"]:
            if key in hass.data[DOMAIN]:
                del hass.data[DOMAIN][key]

        # v3.5.0: Clean up camera census
        unsub_census = hass.data[DOMAIN].pop("unsub_census", None)
        if unsub_census:
            unsub_census()
        # v3.10.1: Clean up event-driven census listeners
        for unsub in hass.data[DOMAIN].pop("unsub_census_events", []):
            unsub()
        for key in ["camera_manager", "census"]:
            if key in hass.data[DOMAIN]:
                del hass.data[DOMAIN][key]

        # v3.5.1: Tear down perimeter alert manager
        perimeter_alert_manager = hass.data[DOMAIN].get("perimeter_alert_manager")
        if perimeter_alert_manager:
            await perimeter_alert_manager.async_teardown()
            del hass.data[DOMAIN]["perimeter_alert_manager"]

        # v3.5.2: Tear down transit validator and egress tracker
        transit_validator = hass.data[DOMAIN].get("transit_validator")
        if transit_validator:
            await transit_validator.async_teardown()
            del hass.data[DOMAIN]["transit_validator"]

        egress_tracker = hass.data[DOMAIN].get("egress_tracker")
        if egress_tracker:
            await egress_tracker.async_teardown()
            del hass.data[DOMAIN]["egress_tracker"]

        # v3.6.0: Tear down domain coordinator manager
        coordinator_manager = hass.data[DOMAIN].get("coordinator_manager")
        if coordinator_manager:
            await coordinator_manager.async_stop()
            del hass.data[DOMAIN]["coordinator_manager"]

        if "integration" in hass.data[DOMAIN]:
            del hass.data[DOMAIN]["integration"]

        return unload_ok
    
    # v3.6.0: Handle Zone Manager entry unload
    if entry_type == ENTRY_TYPE_ZONE_MANAGER:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, INTEGRATION_PLATFORMS)
        if "zone_manager_entry" in hass.data.get(DOMAIN, {}):
            del hass.data[DOMAIN]["zone_manager_entry"]
        return unload_ok

    # v3.6.0: Handle Coordinator Manager entry unload
    if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, INTEGRATION_PLATFORMS)
        return unload_ok

    # v3.3.2: Handle legacy zone entry unload (deprecated)
    if entry_type == ENTRY_TYPE_ZONE:
        return True
    
    # Room entry - unload platforms and remove coordinator
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # v3.12.0: Explicitly clean up coordinator listeners.
        # async_will_remove_from_hass is an Entity lifecycle method — never
        # called on DataUpdateCoordinator. Without this, state and signal
        # listener unsub handles leak on every entry reload.
        coordinator = hass.data[DOMAIN].get(entry.entry_id)
        if coordinator is not None:
            state_listeners = getattr(coordinator, "_unsub_state_listeners", [])
            for unsub in state_listeners:
                unsub()
            state_listeners.clear()
            signal_listeners = getattr(coordinator, "_unsub_signal_listeners", [])
            for unsub in signal_listeners:
                unsub()
            signal_listeners.clear()
            debounce_unsub = getattr(coordinator, "_debounce_refresh_unsub", None)
            if debounce_unsub is not None:
                debounce_unsub()
                coordinator._debounce_refresh_unsub = None
            del hass.data[DOMAIN][entry.entry_id]

    return unload_ok


async def _async_register_presence_services(hass: HomeAssistant) -> None:
    """Register house state services for HA automations.

    Services:
    - universal_room_automation.set_house_state: Set house state override
    - universal_room_automation.clear_house_state_override: Clear override
    """
    import voluptuous as vol

    async def handle_set_house_state(call):
        """Handle set_house_state service call."""
        state = call.data.get("state", "auto")
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        presence = manager.coordinators.get("presence")
        if presence is not None:
            presence.set_house_state_override(state)
        else:
            # Direct state machine control if Presence not registered
            from .domain_coordinators.house_state import HouseState
            if state == "auto":
                manager.house_state_machine.clear_override()
            else:
                try:
                    manager.house_state_machine.set_override(HouseState(state))
                except ValueError:
                    _LOGGER.warning("Invalid house state: %s", state)

    async def handle_clear_override(call):
        """Handle clear_house_state_override service call."""
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        presence = manager.coordinators.get("presence")
        if presence is not None:
            presence.set_house_state_override("auto")
        else:
            manager.house_state_machine.clear_override()

    # Only register once
    if not hass.services.has_service(DOMAIN, "set_house_state"):
        hass.services.async_register(
            DOMAIN,
            "set_house_state",
            handle_set_house_state,
            schema=vol.Schema({
                vol.Required("state"): vol.In([
                    "auto", "away", "arriving", "home_day", "home_evening",
                    "home_night", "sleep", "waking", "guest", "vacation",
                ]),
            }),
        )
        hass.services.async_register(
            DOMAIN,
            "clear_house_state_override",
            handle_clear_override,
            schema=vol.Schema({}),
        )
        _LOGGER.info("Registered house state services")


async def _async_register_safety_services(hass: HomeAssistant) -> None:
    """Register safety test service for HA automations.

    Services:
    - universal_room_automation.test_safety_hazard: Trigger test hazard
    """
    import voluptuous as vol

    async def handle_test_safety_hazard(call):
        """Handle test_safety_hazard service call."""
        hazard_type = call.data.get("hazard_type", "smoke")
        location = call.data.get("location", "test")
        severity = call.data.get("severity", "medium")
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        safety = manager.coordinators.get("safety")
        if safety is not None:
            await safety.handle_test_hazard(hazard_type, location, severity)
        else:
            _LOGGER.warning("Safety coordinator not available for test hazard")

    # Only register once
    if not hass.services.has_service(DOMAIN, "test_safety_hazard"):
        hass.services.async_register(
            DOMAIN,
            "test_safety_hazard",
            handle_test_safety_hazard,
            schema=vol.Schema({
                vol.Required("hazard_type"): vol.In([
                    "smoke", "fire", "water_leak", "flooding",
                    "carbon_monoxide", "high_co2", "high_tvoc",
                    "freeze_risk", "overheat", "hvac_failure",
                    "high_humidity", "low_humidity",
                ]),
                vol.Required("location"): str,
                vol.Optional("severity", default="medium"): vol.In([
                    "critical", "high", "medium", "low",
                ]),
            }),
        )
        _LOGGER.info("Registered safety test service")


async def _async_register_security_services(hass: HomeAssistant) -> None:
    """Register security services for HA automations.

    Services:
    - universal_room_automation.security_arm: Set armed state
    - universal_room_automation.security_disarm: Disarm
    - universal_room_automation.authorize_guest: Authorize a guest
    - universal_room_automation.add_expected_arrival: Add expected arrival
    """
    import voluptuous as vol

    async def handle_security_arm(call):
        """Handle security_arm service call."""
        armed_state = call.data.get("state", "armed_home")
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        security = manager.coordinators.get("security")
        if security is not None:
            await security.handle_arm(armed_state)
        else:
            _LOGGER.warning("Security coordinator not available for arm")

    async def handle_security_disarm(call):
        """Handle security_disarm service call."""
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        security = manager.coordinators.get("security")
        if security is not None:
            await security.handle_disarm()
        else:
            _LOGGER.warning("Security coordinator not available for disarm")

    async def handle_authorize_guest(call):
        """Handle authorize_guest service call."""
        person_name = call.data.get("person_name", "")
        expires_hours = call.data.get("expires_hours", 24)
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        security = manager.coordinators.get("security")
        if security is not None:
            security.handle_authorize_guest(person_name, expires_hours)
        else:
            _LOGGER.warning("Security coordinator not available for authorize_guest")

    async def handle_add_expected_arrival(call):
        """Handle add_expected_arrival service call."""
        person_id = call.data.get("person_id", "")
        window_minutes = call.data.get("window_minutes", 30)
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        security = manager.coordinators.get("security")
        if security is not None:
            security.handle_add_expected_arrival(person_id, window_minutes)
        else:
            _LOGGER.warning("Security coordinator not available for add_expected_arrival")

    if not hass.services.has_service(DOMAIN, "security_arm"):
        hass.services.async_register(
            DOMAIN,
            "security_arm",
            handle_security_arm,
            schema=vol.Schema({
                vol.Required("state"): vol.In([
                    "disarmed", "armed_home", "armed_away", "armed_vacation",
                ]),
            }),
        )

    if not hass.services.has_service(DOMAIN, "security_disarm"):
        hass.services.async_register(
            DOMAIN,
            "security_disarm",
            handle_security_disarm,
            schema=vol.Schema({}),
        )

    if not hass.services.has_service(DOMAIN, "authorize_guest"):
        hass.services.async_register(
            DOMAIN,
            "authorize_guest",
            handle_authorize_guest,
            schema=vol.Schema({
                vol.Required("person_name"): str,
                vol.Optional("expires_hours", default=24): vol.Coerce(float),
            }),
        )

    if not hass.services.has_service(DOMAIN, "add_expected_arrival"):
        hass.services.async_register(
            DOMAIN,
            "add_expected_arrival",
            handle_add_expected_arrival,
            schema=vol.Schema({
                vol.Required("person_id"): str,
                vol.Optional("window_minutes", default=30): vol.Coerce(int),
            }),
        )

    _LOGGER.info("Registered security services")


async def _async_register_notification_services(hass: HomeAssistant) -> None:
    """Register notification manager services.

    Services:
    - universal_room_automation.acknowledge_notification: Ack active alert
    - universal_room_automation.test_notification: Send test notification
    """
    import voluptuous as vol

    async def handle_acknowledge_notification(call):
        """Handle acknowledge_notification service call."""
        nm = hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm:
            await nm.async_acknowledge()
        else:
            _LOGGER.warning("Notification Manager not available for acknowledge")

    async def handle_test_notification(call):
        """Handle test_notification service call."""
        severity = call.data.get("severity", "MEDIUM")
        channel = call.data.get("channel")
        nm = hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm:
            await nm.async_test_notification(severity=severity, channel=channel)
        else:
            _LOGGER.warning("Notification Manager not available for test")

    if not hass.services.has_service(DOMAIN, "acknowledge_notification"):
        hass.services.async_register(
            DOMAIN,
            "acknowledge_notification",
            handle_acknowledge_notification,
            schema=vol.Schema({}),
        )

    if not hass.services.has_service(DOMAIN, "test_notification"):
        hass.services.async_register(
            DOMAIN,
            "test_notification",
            handle_test_notification,
            schema=vol.Schema({
                vol.Optional("severity", default="MEDIUM"): vol.In([
                    "LOW", "MEDIUM", "HIGH", "CRITICAL",
                ]),
                vol.Optional("channel"): str,
            }),
        )

    # C4b: test_inbound service
    async def handle_test_inbound(call):
        """Handle test_inbound service call."""
        nm = hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm:
            text = call.data.get("text", "status")
            channel = call.data.get("channel", "companion")
            response = await nm._process_inbound_reply(None, channel, text)
            _LOGGER.info("Test inbound response: %s", response)

    if not hass.services.has_service(DOMAIN, "test_inbound"):
        hass.services.async_register(
            DOMAIN,
            "test_inbound",
            handle_test_inbound,
            schema=vol.Schema({
                vol.Required("text"): str,
                vol.Optional("channel", default="companion"): vol.In([
                    "companion", "whatsapp", "pushover", "imessage",
                ]),
            }),
        )

    _LOGGER.info("Registered notification manager services")


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update - reload the entry."""
    await hass.config_entries.async_reload(entry.entry_id)
