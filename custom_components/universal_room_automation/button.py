"""Button platform for Universal Room Automation."""
#
# Universal Room Automation vv4.5.16
# Build: 2026-01-04
# File: button.py
#

import json
import logging
from datetime import datetime
from pathlib import Path

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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

    # v3.6.29: Coordinator Manager entry — NM acknowledge button + B1 clear button
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
        cm_entities: list[ButtonEntity] = [
            NMAcknowledgeButton(hass, entry),
            ClearBayesianBeliefsButton(hass, entry),
            # v4.5.12 D10: diagnostic dump button (house-wide, on HVAC device)
            HVACACRampDiagnosticDumpButton(hass, entry),
        ]
        # v4.5.11: 3 buttons per AC zone (force_nudge / cancel_nudge /
        # clear_lockout). Discovers zones from Zone Manager entries — same
        # pattern as number.py per-zone kWh threshold sliders.
        for zone_spec in _discover_ac_zones(hass):
            cm_entities.append(
                _make_ac_ramp_button(hass, entry, zone_spec, "force_nudge")
            )
            cm_entities.append(
                _make_ac_ramp_button(hass, entry, zone_spec, "cancel_nudge")
            )
            cm_entities.append(
                _make_ac_ramp_button(hass, entry, zone_spec, "clear_lockout")
            )
        async_add_entities(cm_entities)
        return

    if entry.entry_id not in hass.data.get(DOMAIN, {}):
        return
    coordinator: UniversalRoomCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = [
        ReloadRoomButton(coordinator),
        ExportDataButton(coordinator),
        RefreshPredictionsButton(coordinator),
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


# ============================================================================
# v4.0.0-B1: Bayesian Predictor — Clear & Reinitialize button
# ============================================================================


class ClearBayesianBeliefsButton(ButtonEntity):
    """Button to clear Bayesian beliefs and re-initialize from priors.

    Entity: button.ura_clear_bayesian_beliefs
    Device: URA: Coordinator Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:brain"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_clear_bayesian_beliefs"
        self._attr_name = "Clear Bayesian Beliefs"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    @property
    def available(self) -> bool:
        """Button is available when Bayesian predictor is active."""
        predictor = self.hass.data.get(DOMAIN, {}).get("bayesian_predictor")
        return predictor is not None

    async def async_press(self) -> None:
        """Handle button press — clear beliefs and reinitialize from priors."""
        predictor = self.hass.data.get(DOMAIN, {}).get("bayesian_predictor")
        if predictor:
            await predictor.clear_and_reinitialize()
            _LOGGER.info("Bayesian beliefs cleared and reinitialized via button")
        else:
            _LOGGER.warning("Bayesian predictor not available")


# ============================================================================
# v4.5.11: AC Ramp-Down per-zone buttons (force_nudge / cancel / clear_lockout)
# ============================================================================


def _discover_ac_zones(hass: HomeAssistant) -> list[dict]:
    """Enumerate canonical HVAC zones for per-zone button registration.

    v4.5.13.1: thin wrapper around `iter_canonical_hvac_zones` so all
    per-zone platform setup paths share identical dedup + zone_id
    derivation logic. Bug Class #36 prevention.

    The earlier in-place version had two issues we needed to retire:
      1. Used `thermostat.replace("climate.","")...` for zone_id, which
         produced different ids than ZoneManager runtime (`zone_N`),
         creating cross-platform inconsistency.
      2. Did not surface the merged display name when two home zones
         shared a thermostat.
    """
    from .domain_coordinators.hvac_zones import iter_canonical_hvac_zones
    return iter_canonical_hvac_zones(hass)


_AC_RAMP_BUTTON_SPECS: dict[str, dict] = {
    "force_nudge": {
        "label": "Force AC Nudge",
        "icon": "mdi:thermometer-chevron-up",
        "method": "force_nudge",
        "category": None,  # primary user-facing action
    },
    "cancel_nudge": {
        "label": "Cancel AC Nudge",
        "icon": "mdi:cancel",
        "method": "cancel_nudge",
        "category": None,
    },
    "clear_lockout": {
        "label": "Clear AC Ramp Lockout",
        "icon": "mdi:lock-reset",
        "method": "clear_zone_lockout",
        "category": EntityCategory.CONFIG,
    },
}


def _make_ac_ramp_button(
    hass: HomeAssistant,
    entry: ConfigEntry,
    zone_spec: dict,
    action: str,
) -> "_ACRampButton":
    """Construct one button entity for a (zone, action) pair."""
    spec = _AC_RAMP_BUTTON_SPECS[action]
    return _ACRampButton(
        hass=hass,
        entry=entry,
        zone_id=zone_spec["zone_id"],
        zone_name=zone_spec["zone_name"],
        climate_entity=zone_spec["climate_entity"],
        action=action,
        label=spec["label"],
        icon=spec["icon"],
        method_name=spec["method"],
        category=spec["category"],
    )


class _ACRampButton(ButtonEntity):
    """Per-zone AC ramp-down control button.

    Routes to OverrideArrester methods via the HVAC coordinator. Single
    class parameterized by action keeps the device-UI grouping tight
    (3 buttons × N zones all live on the HVAC Coordinator device).
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        entry: ConfigEntry,
        zone_id: str,
        zone_name: str,
        climate_entity: str,
        action: str,
        label: str,
        icon: str,
        method_name: str,
        category: EntityCategory | None,
    ) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION

        self.hass = hass
        self._entry = entry
        self._zone_id = zone_id
        # Store climate_entity for the runtime call to OverrideArrester
        # methods — OverrideArrester._resolve_zone matches by either
        # zone_id (its own scheme) or climate_entity. Passing the climate
        # entity sidesteps the local-vs-coord zone_id naming drift.
        self._climate_entity = climate_entity
        self._action = action
        self._method_name = method_name
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_ramp_{action}_{zone_id}"
        self._attr_name = f"{label} ({zone_name})"
        self._attr_icon = icon
        if category is not None:
            self._attr_entity_category = category
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_arrester(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        hvac = manager.coordinators.get("hvac") if hasattr(manager, "coordinators") else None
        return getattr(hvac, "_override_arrester", None) if hvac else None

    @property
    def available(self) -> bool:
        return self._get_arrester() is not None

    async def async_added_to_hass(self) -> None:
        """v4.5.11.3: Subscribe to SIGNAL_HVAC_ENTITIES_UPDATE so `available`
        is re-evaluated on every HVAC decision cycle.

        Without this, buttons that initialized BEFORE the HVAC coordinator's
        `_override_arrester` attribute was reachable would cache
        `available=False` permanently — HA's state machine never re-checks
        `available` on a Button entity unless something triggers a state
        update. Numbers self-refresh via their RestoreEntity + native_value
        path; buttons have no equivalent natural refresh.

        Result before the fix: buttons appear greyed-out in the UI after a
        restart, requiring a manual `homeassistant.update_entity` service
        call to clear. After the fix: buttons auto-recover within one
        decision cycle (≤5 min).
        """
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_HVAC_ENTITIES_UPDATE,
                self._handle_hvac_update,
            )
        )

    @callback
    def _handle_hvac_update(self, *_args, **_kwargs) -> None:
        """Re-evaluate `available` on each HVAC tick."""
        self.async_schedule_update_ha_state()

    async def async_press(self) -> None:
        arr = self._get_arrester()
        if arr is None:
            _LOGGER.warning(
                "AC ramp button %s (%s): OverrideArrester not available",
                self._action, self._zone_id,
            )
            return
        method = getattr(arr, self._method_name, None)
        if method is None:
            _LOGGER.error(
                "AC ramp button %s: method %s missing on arrester",
                self._action, self._method_name,
            )
            return
        try:
            # Pass climate_entity rather than local zone_id — arrester's
            # _resolve_zone bridges to the ZoneManager-owned zone_id.
            await method(self._climate_entity)
        except Exception as e:
            _LOGGER.error(
                "AC ramp button %s (%s) failed: %s",
                self._action, self._zone_id, e,
            )
        _LOGGER.info(
            "AC ramp button pressed: %s (zone=%s)",
            self._action, self._zone_id,
        )


# ============================================================================
# v4.5.12 D10: Diagnostic dump button — exports last 7 days of AC ramp events
# ============================================================================
# Writes JSON to /config/ura_diagnostics/ac_ramp_<ISO_timestamp>.json so the
# user (or a future debugging session) can inspect the full event history
# offline. Reuses get_ac_ramp_events_recent() from slice 1's DB layer.
#
# Applies Bug Class #35 pattern: subscribes to SIGNAL_HVAC_ENTITIES_UPDATE in
# async_added_to_hass so `available` re-evaluates per HVAC tick. (For this
# button `available` is always True since it doesn't depend on the arrester
# being up — but the pattern is documented as the standard for ALL new
# buttons, so applying it consistently here.)


class HVACACRampDiagnosticDumpButton(ButtonEntity):
    """Press to dump the last 7 days of `ac_ramp_events` to a JSON file
    under `/config/ura_diagnostics/`. Fires a persistent_notification
    with the file path.

    Entity: button.ura_hvac_ac_ramp_diagnostic_dump
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:file-download-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION

        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_ramp_diagnostic_dump"
        self._attr_name = "AC Ramp Diagnostic Dump"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_db(self):
        return self.hass.data.get(DOMAIN, {}).get("database")

    @property
    def available(self) -> bool:
        # Always operable when the URA DB is available
        return self._get_db() is not None

    async def async_added_to_hass(self) -> None:
        """v4.5.11.3 / Bug Class #35: subscribe to SIGNAL_HVAC_ENTITIES_UPDATE
        so `available` re-evaluates per HVAC tick even though this button's
        dependency (the DB) is more stable than the arrester."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_hvac_update,
            )
        )

    @callback
    def _handle_hvac_update(self, *_a, **_kw) -> None:
        self.async_schedule_update_ha_state()

    async def async_press(self) -> None:
        db = self._get_db()
        if db is None:
            _LOGGER.warning(
                "AC ramp diagnostic dump: URA database not available"
            )
            return

        # Query last 7 days of events. Reuses the slice 1 method.
        try:
            events = await db.get_ac_ramp_events_recent(days=7)
        except Exception as e:
            _LOGGER.error(
                "AC ramp diagnostic dump: DB query failed: %s", e,
            )
            return

        # Build dump payload
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        diagnostics_dir = Path(self.hass.config.config_dir) / "ura_diagnostics"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        filepath = diagnostics_dir / f"ac_ramp_{timestamp}.json"

        # Pull aggregate context too (so the dump is self-contained for
        # offline analysis without needing the DB to interpret it)
        try:
            (
                kwh_total, evals_total, fp_total,
            ) = await db.get_ac_ramp_kwh_avoided(days=None)
        except Exception:
            kwh_total = evals_total = fp_total = 0

        payload = {
            "dump_metadata": {
                "generated_at": datetime.now().isoformat(),
                "window_days": 7,
                "event_count": len(events),
            },
            "aggregates": {
                "kwh_avoided_total": round(kwh_total, 3),
                "nudge_evaluations_total": evals_total,
                "false_positives_total": fp_total,
            },
            "events": events,
        }

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
        except Exception as e:
            _LOGGER.error(
                "AC ramp diagnostic dump: write to %s failed: %s",
                filepath, e,
            )
            return

        _LOGGER.info(
            "AC ramp diagnostic dump created: %s (%d events, %d bytes)",
            filepath, len(events), filepath.stat().st_size,
        )

        # User-visible notification with the file path
        try:
            await self.hass.services.async_call(
                "persistent_notification", "create",
                {
                    "title": "AC Ramp Diagnostic Dump",
                    "message": (
                        f"Wrote {len(events)} events to:\n`{filepath}`\n\n"
                        f"Size: {filepath.stat().st_size:,} bytes."
                    ),
                    "notification_id": "ura_ac_ramp_diagnostic_dump",
                },
                blocking=False,
            )
        except Exception as e:
            _LOGGER.warning(
                "AC ramp diagnostic dump notification failed: %s", e,
            )
