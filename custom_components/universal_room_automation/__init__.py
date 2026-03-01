"""Universal Room Automation integration."""
#
# Universal Room Automation v3.6.0.6
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

from homeassistant.helpers.event import async_track_time_interval

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

        # v3.5.0: Initialize camera integration manager and person census
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
        except Exception as e:
            _LOGGER.error("Failed to initialize camera census: %s", e)

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

        # Set up aggregation sensors (sensor and binary_sensor platforms)
        # These will be registered via the platform files
        await hass.config_entries.async_forward_entry_setups(entry, INTEGRATION_PLATFORMS)
        
        # v3.2.5: Add update listener to reload entry when options change
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        
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
        if entry.entry_id in hass.data[DOMAIN]:
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


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update - reload the entry."""
    await hass.config_entries.async_reload(entry.entry_id)
