"""Universal Room Automation integration."""
#
# Universal Room Automation v3.4.1
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

from .const import (
    DOMAIN,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ROOM,
    ENTRY_TYPE_ZONE,  # v3.3.2: Import zone entry type
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
    DEFAULT_ELECTRICITY_RATE,
    NOTIFY_LEVEL_ERRORS,
)
from .coordinator import UniversalRoomCoordinator
from .database import UniversalRoomDatabase
from .person_coordinator import PersonTrackingCoordinator  # v3.2.0
from .camera_census import CameraIntegrationManager, PersonCensus  # v3.5.0

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
]

# Platforms for integration entry (aggregation sensors only)
INTEGRATION_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
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
        if not entry.options.get("zone_migration_done"):
            try:
                zones_created = await _migrate_zone_names_to_entries(hass, entry)
                if zones_created >= 0:  # 0 = nothing to migrate, also counts as done
                    hass.config_entries.async_update_entry(
                        entry, options={**entry.options, "zone_migration_done": True}
                    )
                    if zones_created > 0:
                        _LOGGER.info("Zone migration created %d new zone entries", zones_created)
            except Exception as e:
                _LOGGER.error("Zone migration failed: %s", e)
                import traceback
                _LOGGER.error("Traceback: %s", traceback.format_exc())
        
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
            await camera_manager.async_discover()
            hass.data[DOMAIN]["camera_manager"] = camera_manager

            census = PersonCensus(hass, camera_manager)
            hass.data[DOMAIN]["census"] = census
            _LOGGER.info(
                "Camera census initialized (cameras discovered: %d)",
                len(camera_manager.get_all_frigate_cameras())
                + len(camera_manager.get_all_unifi_cameras()),
            )
        except Exception as e:
            _LOGGER.error("Failed to initialize camera census: %s", e)

        # Set up aggregation sensors (sensor and binary_sensor platforms)
        # These will be registered via the platform files
        await hass.config_entries.async_forward_entry_setups(entry, INTEGRATION_PLATFORMS)
        
        # v3.2.5: Add update listener to reload entry when options change
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        
        _LOGGER.info("Integration entry setup complete with aggregation sensors")
        return True
    
    # =========================================================================
    # v3.3.2: Zone entry handling
    # =========================================================================
    if entry_type == ENTRY_TYPE_ZONE:
        # Zone entry - set up zone-level aggregation sensors + update listener
        zone_name = entry.data.get(CONF_ZONE_NAME, "Unknown")
        _LOGGER.info("Setting up zone entry: %s", zone_name)

        # Store zone entry reference (for music_following lookup)
        if "zones" not in hass.data[DOMAIN]:
            hass.data[DOMAIN]["zones"] = {}
        hass.data[DOMAIN]["zones"][entry.entry_id] = entry

        # v3.3.5.6: Forward sensor/binary_sensor platforms so zone entities
        # are registered under the zone config entry (not the integration entry)
        await hass.config_entries.async_forward_entry_setups(entry, INTEGRATION_PLATFORMS)

        # v3.3.2: Add update listener so OptionsFlow changes trigger reload
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))

        _LOGGER.info("Zone entry '%s' setup complete with zone sensors", zone_name)
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
        for key in ["camera_manager", "census"]:
            if key in hass.data[DOMAIN]:
                del hass.data[DOMAIN][key]

        if "integration" in hass.data[DOMAIN]:
            del hass.data[DOMAIN]["integration"]
        
        return unload_ok
    
    # v3.3.2: Handle zone entry unload
    if entry_type == ENTRY_TYPE_ZONE:
        # v3.3.5.6: Unload zone sensor/binary_sensor platforms
        unload_ok = await hass.config_entries.async_unload_platforms(entry, INTEGRATION_PLATFORMS)
        # Clean up zone entry reference
        if "zones" in hass.data[DOMAIN] and entry.entry_id in hass.data[DOMAIN]["zones"]:
            del hass.data[DOMAIN]["zones"][entry.entry_id]
        return unload_ok
    
    # Room entry - unload platforms and remove coordinator
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        if entry.entry_id in hass.data[DOMAIN]:
            del hass.data[DOMAIN][entry.entry_id]
    
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update - reload the entry."""
    await hass.config_entries.async_reload(entry.entry_id)
