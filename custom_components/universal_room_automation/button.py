"""Button platform for Universal Room Automation."""
#
# Universal Room Automation v3.15.3
# Build: 2026-01-04
# File: button.py
#

import json
import logging
from datetime import datetime
from pathlib import Path

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TARGET,
)
from .coordinator import UniversalRoomCoordinator
from .entity import UniversalRoomEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Universal Room Automation buttons."""
    from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_COORDINATOR_MANAGER

    # v3.6.29: Coordinator Manager entry — NM acknowledge button
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
        async_add_entities([NMAcknowledgeButton(hass, entry)])
        return

    if entry.entry_id not in hass.data.get(DOMAIN, {}):
        return
    coordinator: UniversalRoomCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = [
        ReloadRoomButton(coordinator),
        ExportDataButton(coordinator),
        ClearDatabaseButton(coordinator),
        RefreshPredictionsButton(coordinator),
        OptimizeNowButton(coordinator),
        ConfigDumpButton(coordinator),
    ]
    
    async_add_entities(entities)
    _LOGGER.info(
        "Set up %d buttons for room: %s",
        len(entities),
        entry.data.get("room_name")
    )


class ConfigDumpButton(UniversalRoomEntity, ButtonEntity):
    """Button to dump current configuration for debugging."""

    _attr_icon = "mdi:file-document-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "dump_config", "Dump Config")

    @property
    def available(self) -> bool:
        """Button is always available."""
        return True

    async def async_press(self) -> None:
        """Handle button press - dump configuration to JSON file."""
        room_name = self.coordinator.entry.data.get("room_name", "Unknown")
        entry = self.coordinator.entry
        
        # Create diagnostics directory if it doesn't exist
        diagnostics_dir = Path(self.hass.config.config_dir) / "custom_components" / "universal_room_automation" / "diagnostics"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_room_name = room_name.lower().replace(" ", "_")
        filename = f"{safe_room_name}_config_{timestamp}.json"
        filepath = diagnostics_dir / filename
        
        # Build comprehensive config dump
        config_dump = {
            "timestamp": timestamp,
            "room_name": room_name,
            "entry_id": entry.entry_id,
            "integration_version": "3.2.8",
            
            # Entry data (initial configuration)
            "entry_data": dict(entry.data),
            
            # Entry options (user overrides)
            "entry_options": dict(entry.options),
            
            # Merged config (what coordinator uses)
            "merged_config": {**entry.data, **entry.options},
            
            # Coordinator state with data values
            "coordinator_state": {
                "data_available": bool(self.coordinator.data),
                "data_keys": list(self.coordinator.data.keys()) if self.coordinator.data else [],
                "data_values": dict(self.coordinator.data) if self.coordinator.data else {},
                "last_update_success": self.coordinator.last_update_success,
                "update_interval_seconds": self.coordinator.update_interval.total_seconds() if self.coordinator.update_interval else None,
            },
            
            # Automation state
            "automation_state": {
                "last_trigger_source": self.coordinator._last_trigger_source,
                "last_trigger_entity": self.coordinator._last_trigger_entity,
                "last_trigger_time": self.coordinator._last_trigger_time.isoformat() if self.coordinator._last_trigger_time else None,
                "last_action_description": self.coordinator._last_action_description,
                "last_action_entity": self.coordinator._last_action_entity,
                "last_action_type": self.coordinator._last_action_type,
                "last_action_time": self.coordinator._last_action_time.isoformat() if self.coordinator._last_action_time else None,
                "last_motion_time": self.coordinator._last_motion_time.isoformat() if self.coordinator._last_motion_time else None,
                "last_occupied_time": self.coordinator._last_occupied_time.isoformat() if self.coordinator._last_occupied_time else None,
                "last_occupied_state": self.coordinator._last_occupied_state,
            },
            
            # Entity registry info (which entities belong to this room)
            "registered_entities": await self._get_registered_entities(),
            
            # Highlight overrides (options that differ from data)
            "active_overrides": {
                key: {
                    "new_value": entry.options[key],
                    "original_value": entry.data.get(key)
                }
                for key in entry.options
                if key in entry.data and entry.options[key] != entry.data[key]
            }
        }
        
        # Write JSON file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(config_dump, f, indent=2, default=str)
        
        # Log brief summary to HA logs
        _LOGGER.info(
            "Config dump created for %s: %s (%d bytes)",
            room_name,
            filepath,
            filepath.stat().st_size
        )
        
        # Create persistent notification with file path
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"Config Dump: {room_name}",
                "message": f"Configuration saved to:\n`{filepath}`\n\nFile size: {filepath.stat().st_size:,} bytes",
                "notification_id": f"ura_config_dump_{entry.entry_id}",
            },
        )
        
        _LOGGER.info("=" * 80)
        _LOGGER.info("✅ CONFIG DUMP COMPLETE")
        _LOGGER.info("   Room: %s", room_name)
        _LOGGER.info("   File: %s", filepath)
        _LOGGER.info("   Size: %d bytes", filepath.stat().st_size)
        _LOGGER.info("=" * 80)
    
    async def _get_registered_entities(self) -> dict:
        """Get all entities registered for this room."""
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        
        # Find all entities for this config entry
        entities = []
        for entity in entity_registry.entities.values():
            if entity.config_entry_id == self.coordinator.entry.entry_id:
                entities.append({
                    "entity_id": entity.entity_id,
                    "unique_id": entity.unique_id,
                    "platform": entity.platform,
                    "device_id": entity.device_id,
                    "name": entity.name,
                    "original_name": entity.original_name,
                    "disabled": entity.disabled,
                    "disabled_by": entity.disabled_by,
                    "entity_category": entity.entity_category,
                    "has_entity_name": entity.has_entity_name,
                })
        
        # Find devices for this config entry
        devices = []
        for device in device_registry.devices.values():
            if self.coordinator.entry.entry_id in device.config_entries:
                devices.append({
                    "device_id": device.id,
                    "name": device.name,
                    "name_by_user": device.name_by_user,
                    "manufacturer": device.manufacturer,
                    "model": device.model,
                    "sw_version": device.sw_version,
                    "disabled": device.disabled,
                    "disabled_by": device.disabled_by,
                })
        
        return {
            "entities": entities,
            "entity_count": len(entities),
            "devices": devices,
            "device_count": len(devices),
        }


class ReloadRoomButton(UniversalRoomEntity, ButtonEntity):
    """Button to reload room configuration."""

    _attr_icon = "mdi:reload"

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "reload_room", "Reload Room")

    @property
    def available(self) -> bool:
        """Button is always available."""
        return True

    async def async_press(self) -> None:
        """Handle button press - reload config entry to refresh configuration."""
        _LOGGER.info(
            "Reload Room button pressed for room: %s",
            self.coordinator.entry.data.get("room_name")
        )
        
        # Reload the config entry - refreshes all settings from options
        await self.hass.config_entries.async_reload(self.coordinator.entry.entry_id)


class ExportDataButton(UniversalRoomEntity, ButtonEntity):
    """Button to export room data."""

    _attr_icon = "mdi:export"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "export_data", "Export Data")

    @property
    def available(self) -> bool:
        """Button available if database exists."""
        return DOMAIN in self.hass.data and "database" in self.hass.data[DOMAIN]

    async def async_press(self) -> None:
        """Handle button press - export data to CSV and JSON."""
        room_name = self.coordinator.entry.data.get("room_name")
        _LOGGER.info("Export data button pressed for room: %s", room_name)
        
        database = self.hass.data[DOMAIN].get("database")
        if not database:
            _LOGGER.error("Database not available for export")
            return
        
        try:
            import csv
            
            # Get recent data
            data = await database.get_recent_data(self.coordinator.entry.entry_id, limit=500)
            counts = await database.get_table_counts(self.coordinator.entry.entry_id)
            
            # Create export directory
            import os
            export_dir = self.hass.config.path("www")
            os.makedirs(export_dir, exist_ok=True)
            
            timestamp_str = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            room_slug = room_name.lower().replace(' ', '_')
            
            # === CSV Export ===
            # Occupancy events CSV
            occ_csv = os.path.join(export_dir, f"{room_slug}_occupancy_{timestamp_str}.csv")
            with open(occ_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'event_type', 'trigger_source', 'duration_seconds'])
                for row in data["occupancy"]:
                    writer.writerow(row)
            
            # Environmental data CSV
            env_csv = os.path.join(export_dir, f"{room_slug}_environmental_{timestamp_str}.csv")
            with open(env_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'temperature_f', 'humidity_pct', 'illuminance_lux', 'occupied'])
                for row in data["environmental"]:
                    writer.writerow(row)
            
            # Energy snapshots CSV
            energy_csv = os.path.join(export_dir, f"{room_slug}_energy_{timestamp_str}.csv")
            with open(energy_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'power_watts', 'occupied', 'lights_on', 'fans_on', 'switches_on', 'covers_open'])
                for row in data["energy"]:
                    writer.writerow(row)
            
            # === JSON Export (comprehensive) ===
            import json
            export_data = {
                "room_name": room_name,
                "export_time": datetime.utcnow().isoformat(),
                "total_records": counts,
                "occupancy_events": [
                    {
                        "timestamp": row[0],
                        "event_type": row[1],
                        "trigger_source": row[2],
                        "duration": row[3]
                    } for row in data["occupancy"]
                ],
                "environmental_data": [
                    {
                        "timestamp": row[0],
                        "temperature": row[1],
                        "humidity": row[2],
                        "illuminance": row[3],
                        "occupied": row[4]
                    } for row in data["environmental"]
                ],
                "energy_snapshots": [
                    {
                        "timestamp": row[0],
                        "power_watts": row[1],
                        "occupied": row[2],
                        "lights_on": row[3],
                        "fans_on": row[4],
                        "switches_on": row[5],
                        "covers_open": row[6]
                    } for row in data["energy"]
                ]
            }
            
            json_file = os.path.join(export_dir, f"{room_slug}_complete_{timestamp_str}.json")
            with open(json_file, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            _LOGGER.info("Data exported: %s CSV files + 1 JSON", len(data))
            
            # Send notification if configured
            notify_service = self.coordinator.entry.data.get(CONF_NOTIFY_SERVICE)
            notify_target = self.coordinator.entry.data.get(CONF_NOTIFY_TARGET)
            
            if notify_service:
                notification_data = {
                    "message": f"Exported {sum(counts.values())} records for {room_name}\n"
                              f"CSV: occupancy, environmental, energy\n"
                              f"JSON: complete dataset",
                    "title": "Room Data Export Complete",
                    "data": {
                        "occupancy_csv": f"/local/{os.path.basename(occ_csv)}",
                        "environmental_csv": f"/local/{os.path.basename(env_csv)}",
                        "energy_csv": f"/local/{os.path.basename(energy_csv)}",
                        "json_file": f"/local/{os.path.basename(json_file)}",
                        "total_records": sum(counts.values())
                    }
                }
                
                # Add target if specified
                if notify_target:
                    notification_data["target"] = notify_target
                
                await self.hass.services.async_call(
                    "notify",
                    notify_service,
                    notification_data
                )
        except Exception as e:
            _LOGGER.error("Error exporting data: %s", e)


class ClearDatabaseButton(UniversalRoomEntity, ButtonEntity):
    """Button to clear old database entries."""

    _attr_icon = "mdi:database-remove"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "clear_database", "Clear Database")

    @property
    def available(self) -> bool:
        """Button is always available."""
        return True

    async def async_press(self) -> None:
        """Handle button press - clear old database entries."""
        _LOGGER.info(
            "Clear database button pressed for room: %s",
            self.coordinator.entry.data.get("room_name")
        )
        
        # TODO: Implement database cleanup
        # For now, just log
        _LOGGER.warning("Database cleanup not yet implemented")


class RefreshPredictionsButton(UniversalRoomEntity, ButtonEntity):
    """Button to refresh prediction calculations."""

    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "refresh_predictions", "Refresh Predictions")

    @property
    def available(self) -> bool:
        """Button is always available."""
        return True

    async def async_press(self) -> None:
        """Handle button press - recalculate predictions."""
        _LOGGER.info(
            "Refresh predictions button pressed for room: %s",
            self.coordinator.entry.data.get("room_name")
        )
        
        # Force coordinator refresh
        await self.coordinator.async_request_refresh()


class OptimizeNowButton(UniversalRoomEntity, ButtonEntity):
    """Button to generate optimization report."""

    _attr_icon = "mdi:chart-line"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "optimize_now", "Optimize Now")

    @property
    def available(self) -> bool:
        """Button is always available."""
        return True

    async def async_press(self) -> None:
        """Handle button press - generate optimization recommendations."""
        _LOGGER.info(
            "Optimize now button pressed for room: %s",
            self.coordinator.entry.data.get("room_name")
        )
        
        # TODO: Implement optimization analysis
        # For now, just log
        _LOGGER.warning("Optimization analysis not yet implemented")


# ============================================================================
# v3.6.29: Notification Manager Acknowledge Button
# ============================================================================


class NMAcknowledgeButton(ButtonEntity):
    """Button to acknowledge an active CRITICAL alert.

    Entity: button.ura_notification_acknowledge
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-check"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_notification_acknowledge"
        self._attr_name = "Acknowledge Alert"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "notification_manager")},
            name="URA: Notification Manager",
            manufacturer="Universal Room Automation",
            model="Notification Manager",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def available(self) -> bool:
        """Button is available when NM is active."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        return nm is not None

    async def async_press(self) -> None:
        """Handle button press — acknowledge the active alert."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm:
            await nm.async_acknowledge()
            _LOGGER.info("Alert acknowledged via dashboard button")
        else:
            _LOGGER.warning("Notification Manager not available")
