"""Button platform for Universal Room Automation."""
#
# Universal Room Automation vv5.6.0
# Build: 2026-01-04
# File: button.py
#
from __future__ import annotations

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
from homeassistant.helpers.event import async_call_later

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
            # v4.6.2 D5: acknowledge all unacknowledged routine shift events
            AcknowledgeRoutineChangesButton(hass, entry),
            # v4.6.3 D13: anomaly subsystem diagnostic dump button
            AnomalyDiagnosticDumpButton(hass, entry),
            VacuumDatabaseButton(hass, entry),  # supervised one-time DB VACUUM (manual only)
            # v4.7.x D3: admin force-charge override for EVSE TOU pause
            EVSEForceChargeButton(hass, entry),
            # Reset Presence Timers — single options-save → single reload.
            # Lives on the HVAC Coordinator device (slot 51, tail of the
            # 47-50 presence-timer cluster).
            ResetPresenceTimersButton(hass, entry),
            # Pillar B (Phase 5) D4: four buttons on the URA: Optimization
            # Coordinator device. Confirm / Cancel form the confirm-guard
            # pair around an L2+ escalation; Reset strips optimizer
            # CONF_* keys; Run Cycle Now triggers an out-of-band cycle.
            OptimizerConfirmEscalationButton(hass, entry),
            OptimizerCancelEscalationButton(hass, entry),
            OptimizerResetSettingsButton(hass, entry),
            OptimizerRunCycleNowButton(hass, entry),
        ]
        # v4.5.11: 3 buttons per AC zone (force_nudge / cancel_nudge /
        # clear_lockout). Discovers zones from Zone Manager entries — same
        # pattern as number.py per-zone kWh threshold sliders.
        # v4.5.21: pass 1-based zone_index so the Controls-cluster Force/
        # Cancel buttons get linearly-growing numeric prefixes (20/22 ->
        # 30/32 -> 40/42). `iter_canonical_hvac_zones` provides a stable
        # iteration order that pins these prefixes across restarts.
        for zone_index, zone_spec in enumerate(_discover_ac_zones(hass), start=1):
            cm_entities.append(
                _make_ac_ramp_button(
                    hass, entry, zone_spec, "force_nudge", zone_index,
                )
            )
            cm_entities.append(
                _make_ac_ramp_button(
                    hass, entry, zone_spec, "cancel_nudge", zone_index,
                )
            )
            # v4.7.9 D1: per-zone force_ac_reset button (Controls cluster,
            # offset 4) — manual entry point into the hard-reset escalation.
            cm_entities.append(
                _make_ac_ramp_button(
                    hass, entry, zone_spec, "force_ac_reset", zone_index,
                )
            )
            cm_entities.append(
                _make_ac_ramp_button(
                    hass, entry, zone_spec, "clear_lockout", zone_index,
                )
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

    async def async_added_to_hass(self) -> None:
        """Subscribe to SIGNAL_NM_READY to re-evaluate availability after boot.

        v4.6.9: NMAcknowledgeButton was permanently unavailable at first boot
        because hass.data[DOMAIN]["notification_manager"] was never set (latent
        bug) and nothing triggered a re-evaluation after NM registered.
        """
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_READY
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_READY, self._handle_ready)
        )

    @callback
    def _handle_ready(self) -> None:
        """Re-evaluate availability once NM is registered."""
        self.async_schedule_update_ha_state()

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

    async def async_added_to_hass(self) -> None:
        """Subscribe to SIGNAL_BAYESIAN_READY to re-evaluate availability after boot.

        v4.6.9: ClearBayesianBeliefsButton was greyed out at first boot because
        nothing triggered a re-evaluation of available after the predictor registered.
        """
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_BAYESIAN_READY
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_BAYESIAN_READY, self._handle_ready)
        )

    @callback
    def _handle_ready(self) -> None:
        """Re-evaluate availability once Bayesian predictor is registered."""
        self.async_schedule_update_ha_state()

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


class ResetPresenceTimersButton(ButtonEntity):
    """Reset the four HVAC presence-timer Numbers to factory defaults.

    Slot 51 on the URA: HVAC Coordinator device card — parked right after
    the 47-50 presence-timer cluster it resets:
        47 · Zone Entry Dwell (minutes)
        48 · Zone Vacancy Delay (minutes)
        49 · Zone Vacancy Delay · Energy-Saving (minutes)
        50 · Max Zone Occupied Time (hours)

    Behaviour:
      1. Live-attr push to ``hvac._*`` (guarded) so the next decision cycle
         sees defaults immediately.
      2. Single ``async_update_entry`` carrying ALL four defaults so the
         CM reload happens once, not four times.

    Bug Class #46 analysis: ``async_press`` is a runtime user action, NOT
    on the setup path — the standard CM options-save reload is the same
    one a config-form save triggers.

    Entity: button.ura_hvac_coordinator_reset_presence_timers
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-refresh"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_reset_presence_timers"
        self._attr_name = "51 · Reset Presence Timers"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_hvac(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    async def async_press(self) -> None:
        from .domain_coordinators.hvac_const import (
            CONF_HVAC_VACANCY_GRACE_MINUTES,
            DEFAULT_VACANCY_GRACE_MINUTES,
            CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
            DEFAULT_VACANCY_GRACE_CONSTRAINED,
            CONF_HVAC_MAX_OCCUPANCY_HOURS,
            DEFAULT_MAX_OCCUPANCY_HOURS,
            CONF_HVAC_ZONE_ENTRY_DWELL,
            DEFAULT_ZONE_ENTRY_DWELL_MINUTES,
        )
        defaults = {
            CONF_HVAC_VACANCY_GRACE_MINUTES: DEFAULT_VACANCY_GRACE_MINUTES,
            CONF_HVAC_VACANCY_GRACE_CONSTRAINED: DEFAULT_VACANCY_GRACE_CONSTRAINED,
            CONF_HVAC_MAX_OCCUPANCY_HOURS: DEFAULT_MAX_OCCUPANCY_HOURS,
            CONF_HVAC_ZONE_ENTRY_DWELL: DEFAULT_ZONE_ENTRY_DWELL_MINUTES,
        }
        # Live-attr push so the next HVAC decision cycle picks defaults
        # up immediately; the writeback below persists them across the
        # ensuing CM reload.
        hvac = self._get_hvac()
        if hvac is not None:
            hvac._vacancy_grace = DEFAULT_VACANCY_GRACE_MINUTES
            hvac._vacancy_grace_constrained = DEFAULT_VACANCY_GRACE_CONSTRAINED
            hvac._max_occupancy_hours = DEFAULT_MAX_OCCUPANCY_HOURS
            hvac._zone_entry_dwell = DEFAULT_ZONE_ENTRY_DWELL_MINUTES
        # Single options-save → single reload, not four cascading ones.
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, **defaults},
        )
        _LOGGER.info("Presence timers reset to defaults")


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
        # v4.5.21: device-page ordering experiment — `label` carries the
        # bare entity name. The numeric prefix is computed at construction
        # time from (cluster, zone_index) so per-zone buttons grow linearly
        # (zone 1=20/22, zone 2=30/32, zone 3=40/42 in the Controls
        # cluster). `clear_lockout` uses a fixed CONFIG-cluster prefix (95)
        # regardless of zone.
        "label": "Force AC Nudge",
        "icon": "mdi:thermometer-chevron-up",
        "method": "force_nudge",
        "category": None,  # primary user-facing action
        # Controls cluster, even prefix (force = base, cancel = base + 2)
        "cluster": "controls",
        "action_offset": 0,
    },
    "cancel_nudge": {
        "label": "Cancel AC Nudge",
        "icon": "mdi:cancel",
        "method": "cancel_nudge",
        "category": None,
        "cluster": "controls",
        "action_offset": 2,
    },
    # v4.7.9 D1: bridges the (Nudge=OFF, Reset=ON) cell of the v4.7.7
    # decouple matrix — when soft-nudge auto-detection is gated off the
    # hard-reset escalation has no entry point. This manual button calls
    # `OverrideArrester.force_ac_reset` which mirrors `force_nudge` and
    # delegates to `_perform_hard_reset_escalation`. The A3 guard inside
    # the escalation cleanly no-ops when _ac_reset_enabled is False
    # (helper text documents the requirement). Controls cluster, prefix
    # offset 4 -> zone 1 = 24, zone 2 = 34, zone 3 = 44 (sits immediately
    # after each zone's `cancel_nudge` button at offset 2).
    "force_ac_reset": {
        "label": "Force AC Reset",
        "icon": "mdi:hvac-off",
        "method": "force_ac_reset",
        "category": None,  # primary user-facing action
        "cluster": "controls",
        "action_offset": 4,
    },
    "clear_lockout": {
        "label": "Clear AC Ramp Lockout",
        "icon": "mdi:lock-reset",
        "method": "clear_zone_lockout",
        "category": EntityCategory.CONFIG,
        # CONFIG cluster: fixed prefix 95 shared across per-zone instances.
        "cluster": "config",
        "fixed_prefix": 95,
    },
}


def _ac_ramp_prefix(spec: dict, zone_index: int) -> int:
    """Compute the numeric device-page-ordering prefix for a ramp button.

    Controls-cluster Force/Cancel buttons grow linearly per zone:
      zone_index=1 -> Force=20, Cancel=22
      zone_index=2 -> Force=30, Cancel=32
      zone_index=3 -> Force=40, Cancel=42
    CONFIG-cluster Clear Lockout uses a fixed prefix (95) for all zones.
    """
    if "fixed_prefix" in spec:
        return int(spec["fixed_prefix"])
    return 10 + zone_index * 10 + int(spec.get("action_offset", 0))


def _make_ac_ramp_button(
    hass: HomeAssistant,
    entry: ConfigEntry,
    zone_spec: dict,
    action: str,
    zone_index: int = 1,
) -> "_ACRampButton":
    """Construct one button entity for a (zone, action) pair.

    `zone_index` is 1-based and drives the Controls-cluster numeric prefix.
    """
    spec = _AC_RAMP_BUTTON_SPECS[action]
    prefix = _ac_ramp_prefix(spec, zone_index)
    prefixed_label = f"{prefix:02d} · {spec['label']}"
    return _ACRampButton(
        hass=hass,
        entry=entry,
        zone_id=zone_spec["zone_id"],
        zone_name=zone_spec["zone_name"],
        climate_entity=zone_spec["climate_entity"],
        action=action,
        label=prefixed_label,
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
        # v4.7.9 A-M1/C-M1 fix-up: surface strings.json helper text for the
        # force_ac_reset variant. Without _attr_translation_key the
        # `entity.button.hvac_force_ac_reset` entry in strings.json /
        # translations/en.json is unreachable. Only the force_ac_reset
        # action has a strings entry today; other actions (force_nudge,
        # cancel_nudge, clear_lockout) intentionally use _attr_name only.
        if action == "force_ac_reset":
            self._attr_translation_key = "hvac_force_ac_reset"
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
        self._attr_name = "90 · AC Ramp Diagnostic Dump"
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


# ============================================================================
# v4.6.2 D5 — Acknowledge Routine Changes Button
# ============================================================================


class AcknowledgeRoutineChangesButton(ButtonEntity):
    """Acknowledge all unacknowledged routine-shift events house-wide.

    Entity: button.ura_coordinator_manager_acknowledge_routine_changes
    Device: URA: Coordinator Manager

    Press → sets recovery_at=now on every unacknowledged bayesian.routine_shift
    row in anomaly_log. Dispatches SIGNAL_ROUTINE_STATUS_UPDATE so D5 sensors
    immediately reflect the cleared state.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:check-circle-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_acknowledge_routine_changes"
        self._attr_name = "Acknowledge Routine Changes"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to SIGNAL_DATABASE_READY to re-evaluate availability after boot.

        v4.6.9: AcknowledgeRoutineChangesButton was greyed out at first boot
        because nothing triggered a re-evaluation after the database registered.
        """
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_DATABASE_READY
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_DATABASE_READY, self._handle_ready)
        )

    @callback
    def _handle_ready(self) -> None:
        """Re-evaluate availability once the database is registered."""
        self.async_schedule_update_ha_state()

    @property
    def available(self) -> bool:
        """Available when the database is reachable."""
        return self.hass.data.get(DOMAIN, {}).get("database") is not None

    async def async_press(self) -> None:
        """Mark all unacknowledged routine shifts as recovered, then refresh sensors."""
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            _LOGGER.warning("AcknowledgeRoutineChangesButton: database not available")
            return
        try:
            rows_updated = await database.acknowledge_all_routine_shifts()
            _LOGGER.info(
                "Routine changes acknowledged: %d events cleared", rows_updated
            )
        except Exception as e:
            _LOGGER.warning(
                "AcknowledgeRoutineChangesButton: acknowledge failed: %s",
                e, exc_info=True,
            )
            return

        # Refresh D5 sensors immediately — function-local import (Bug Class #34)
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        from .domain_coordinators.signals import SIGNAL_ROUTINE_STATUS_UPDATE
        async_dispatcher_send(self.hass, SIGNAL_ROUTINE_STATUS_UPDATE)


# =============================================================================
# v4.6.3 D13 — Anomaly Subsystem Diagnostic Dump Button
# =============================================================================


class AnomalyDiagnosticDumpButton(ButtonEntity):
    """Dump recent anomaly_log rows + baselines to a single ERROR log line.

    Entity: button.ura_coordinator_manager_anomaly_diagnostic_dump
    Device: URA: Coordinator Manager
    Category: DIAGNOSTIC

    On press: queries the last 50 anomaly_log rows, per-coordinator baseline
    counts, write queue depth, and ActivityLogger dedup cache size.  Writes
    a single ERROR-level log line so the dump is grep-friendly and visible
    in the HA Logbook.  No files written — log-only approach per D13 spec.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:bug-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION

        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_anomaly_diagnostic_dump"
        self._attr_name = "90 · Anomaly Subsystem Diagnostic Dump"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to SIGNAL_DATABASE_READY to re-evaluate availability after boot.

        v4.6.9: AnomalyDiagnosticDumpButton was greyed out at first boot
        because nothing triggered a re-evaluation after the database registered.
        """
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_DATABASE_READY
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_DATABASE_READY, self._handle_ready)
        )

    @callback
    def _handle_ready(self) -> None:
        """Re-evaluate availability once the database is registered."""
        self.async_schedule_update_ha_state()

    @property
    def available(self) -> bool:
        return self.hass.data.get(DOMAIN, {}).get("database") is not None

    async def async_press(self) -> None:
        """Build and emit anomaly subsystem dump."""
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            _LOGGER.warning("AnomalyDiagnosticDumpButton: database not available")
            return

        dump: dict = {}

        # 1. Recent 50 anomaly_log rows
        # v4.7.12 fix-up (Review A A3 + Review C C-M3 convergent): widened
        # the discriminator column to COALESCE(anomaly_type, event_class,
        # 'point_in_time') so the diagnostic dump still reads the right
        # value once v5.0 drops event_class. Key in the dump dict stays
        # "event_class" for back-compat with any operator tooling that
        # parses the diagnostic JSON; the value is the canonical
        # discriminator either way.
        try:
            async with database._db_read() as db:
                cursor = await db.execute(
                    """SELECT id, timestamp, coordinator_id, metric_name,
                              severity,
                              COALESCE(anomaly_type, event_class, 'point_in_time'),
                              recovery_at
                       FROM anomaly_log
                       ORDER BY timestamp DESC LIMIT 50"""
                )
                rows = await cursor.fetchall()
                dump["recent_50"] = [
                    {
                        "id": r[0], "timestamp": r[1], "coordinator": r[2],
                        "type": r[3], "severity": r[4],
                        "event_class": r[5], "recovery_at": r[6],
                    }
                    for r in rows
                ]

                # 2. Per-coordinator row counts (last 24 h + all time)
                from homeassistant.util import dt as dt_util  # noqa: PLC0415
                from datetime import timedelta  # noqa: PLC0415
                cutoff_24h = (dt_util.utcnow() - timedelta(hours=24)).isoformat()
                cursor = await db.execute(
                    """SELECT coordinator_id, COUNT(*) as total_all,
                              SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) as last_24h
                       FROM anomaly_log GROUP BY coordinator_id""",
                    (cutoff_24h,),
                )
                dump["per_coordinator"] = {
                    r[0]: {"total": r[1], "last_24h": r[2]}
                    for r in await cursor.fetchall()
                }
        except Exception as e:
            dump["db_error"] = str(e)

        # 3. Write queue depth
        try:
            dump["write_queue_depth"] = database._write_queue.qsize()
            dump["db_stats"] = database._db_stats
        except Exception:
            dump["write_queue_depth"] = "unavailable"

        # 4. ActivityLogger dedup cache size
        try:
            al = self.hass.data.get(DOMAIN, {}).get("activity_logger")
            if al is not None:
                dump["activity_logger_dedup_cache_size"] = len(al._dedup_cache)
            else:
                dump["activity_logger_dedup_cache_size"] = "not_loaded"
        except Exception:
            dump["activity_logger_dedup_cache_size"] = "error"

        # 5. AnomalyDetector baseline counts per coordinator
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is not None and hasattr(manager, "get_anomaly_summary"):
                dump["anomaly_summary"] = manager.get_anomaly_summary()
        except Exception:
            pass

        _LOGGER.error(
            "URA ANOMALY DIAGNOSTIC DUMP: %s",
            json.dumps(dump, default=str, indent=None),
        )


# =============================================================================
# DB space-reclamation — supervised one-time activation VACUUM button
# =============================================================================


class VacuumDatabaseButton(ButtonEntity):
    """One-time SUPERVISED full VACUUM that activates INCREMENTAL auto_vacuum.

    Entity: button.ura_coordinator_manager_vacuum_database
    Device: URA: Coordinator Manager
    Category: CONFIG

    Press ONCE, supervised, at low activity. This triggers a full ``VACUUM``
    that rewrites the entire DB file and takes an EXCLUSIVE lock for minutes on
    a large (~900 MB) DB — it briefly blocks all DB access, so it is a manual
    operator action and is DELIBERATELY NOT wired into the nightly 2:30
    maintenance schedule (the v5.0.0 write-flood incident is why automatic
    blocking DB ops are off-limits).

    After this runs once, the DB is in INCREMENTAL auto_vacuum mode and the
    nightly bounded ``incremental_vacuum`` op reclaims freed pages cheaply
    thereafter. The DAO backs up the DB to ``<db>.prevacuum.bak`` before the
    VACUUM and verifies integrity afterward.

    The DAO guards against concurrent runs; the button additionally guards
    against re-entrant presses and logs loudly.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:database-cog"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION

        self.hass = hass
        self._entry = entry
        self._running = False
        self._attr_unique_id = f"{DOMAIN}_vacuum_database"
        # Visible name kept mere-mortal-friendly (operator 2026-06-19); the
        # unique_id / entity_id interior identity is unchanged.
        self._attr_name = "Optimize Database Storage"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        """Re-evaluate availability once the database registers (boot)."""
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_DATABASE_READY
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DATABASE_READY, self._handle_ready
            )
        )

    @callback
    def _handle_ready(self) -> None:
        self.async_schedule_update_ha_state()

    @property
    def available(self) -> bool:
        return self.hass.data.get(DOMAIN, {}).get("database") is not None

    async def async_press(self) -> None:
        """Run the one-time supervised activation VACUUM."""
        if self._running:
            _LOGGER.warning(
                "Vacuum Database button: a VACUUM is already running — "
                "ignoring re-entrant press"
            )
            return
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            _LOGGER.warning("Vacuum Database button: database not available")
            return
        self._running = True
        _LOGGER.warning(
            "Vacuum Database button pressed — starting SUPERVISED one-time "
            "full VACUUM (exclusive lock, minutes). This is a manual op and "
            "is NOT part of the nightly schedule."
        )
        try:
            result = await database.vacuum_full_supervised()
        except Exception as err:
            _LOGGER.error("Vacuum Database button: VACUUM raised %s", err)
            result = {"status": "error", "error": str(err)}
        finally:
            self._running = False
        _LOGGER.warning("Vacuum Database button: result = %s", result)
        try:
            await self.hass.services.async_call(
                "persistent_notification", "create",
                {
                    "title": "URA Database Vacuum",
                    "message": (
                        f"Supervised VACUUM finished: `{result.get('status')}`.\n"
                        f"Size: {result.get('size_mb_before')} MB → "
                        f"{result.get('size_mb_after')} MB.\n"
                        f"Integrity: {result.get('integrity_check')}.\n"
                        f"Backup: `{result.get('backup_path')}`"
                    ),
                    "notification_id": "ura_vacuum_database",
                },
                blocking=False,
            )
        except Exception as err:
            _LOGGER.warning(
                "Vacuum Database button: notification failed: %s", err
            )


# ============================================================================
# v4.7.x D3: EVSE Force-Charge Admin Override Button
# ============================================================================


class EVSEForceChargeButton(ButtonEntity):
    """Admin override button that opens a 30-min EV force-charge window.

    Entity: button.ura_energy_coordinator_evse_force_charge_30min
    Device: URA: Energy Coordinator

    v4.7.6 D3.5: Override URA's solar-aware EV gating for the next 30
    minutes. Use this when an EVSE is marked self-modulating (URA re-pauses
    every cycle) but you need it to charge now regardless of solar or
    battery state. Resets automatically after the window expires; press
    again to extend.

    v4.7.6 fix-up C-M4: To configure each EVSE's or L1 plug's
    `self_modulates` flag, edit the URA Coordinator Manager entry →
    Configure → Energy Coordinator step. Per-EVSE and per-plug
    BooleanSelectors appear there for every configured device.

    Pressing this button opens a 30-minute window during which URA's TOU
    pause logic is bypassed for all EVSEs.  The override is intentionally
    an admin button (not a switch) to require deliberate action.

    Idempotent: pressing while an override is already active replaces the
    window (extends from now, not additive).

    Auto-expires: URA resumes enforcing TOU pause on the next decision cycle
    after the 30-minute window elapses.  No HA-side bypass is possible
    without this button — D1's strict re-pause enforces this.

    Bug Class #35: wired to SIGNAL_ENERGY_ENTITIES_UPDATE so the button
    availability reflects live EC state.
    Bug Class #38: dispatcher unsub tracked via async_on_remove.
    Bug Class #23: NM notification gated by observation mode in energy.py.
    Bug Class #11/#21: override-until stored as UTC-aware datetime.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:ev-station"
    _OVERRIDE_MINUTES = 30

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION

        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_evse_force_charge_30min"
        self._attr_name = "EVSE Force-Charge 30 min"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_energy(self):
        """Return the EnergyCoordinator instance or None."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    async def async_added_to_hass(self) -> None:
        """Subscribe to EC-ready and energy-update signals.

        v4.7.x D3 + Bug Class #35: availability re-evaluated when EC
        registers (SIGNAL_ENERGY_COORDINATOR_READY) and after each decision
        cycle (SIGNAL_ENERGY_ENTITIES_UPDATE).
        """
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import (
            SIGNAL_ENERGY_COORDINATOR_READY,
            SIGNAL_ENERGY_ENTITIES_UPDATE,
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ENERGY_COORDINATOR_READY, self._handle_ready
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ENERGY_ENTITIES_UPDATE, self._handle_ready
            )
        )

    @callback
    def _handle_ready(self) -> None:
        """Re-evaluate availability when EC becomes ready."""
        self.async_schedule_update_ha_state()

    @property
    def available(self) -> bool:
        """Available when the Energy Coordinator is running."""
        return self._get_energy() is not None

    async def async_press(self) -> None:
        """Open (or extend) the 30-minute force-charge override window.

        Actions on press:
        1. Compute expiry as utcnow() + 30 min (UTC-aware, Bug Class #11/#21).
        2. Call ev_controller.set_force_charge_override(until).
        3. Send NM info notification: "EV force-charge window opened until HH:MM."
        4. Log info with expiry ISO string.

        Idempotent: replaces existing window rather than stacking.
        """
        from datetime import timedelta
        from homeassistant.util import dt as dt_util

        energy = self._get_energy()
        if energy is None:
            _LOGGER.warning("EVSEForceChargeButton: Energy Coordinator not available")
            return

        now_utc = dt_util.utcnow()
        until_utc = now_utc + timedelta(minutes=self._OVERRIDE_MINUTES)

        # Write to the EV controller (D1/D3 integration point)
        energy.ev_controller.set_force_charge_override(until_utc)

        # Convert to local time for human-readable notification
        until_local = dt_util.as_local(until_utc)
        until_str = until_local.strftime("%H:%M")

        _LOGGER.info(
            "EVSE force-charge override opened until %s (UTC: %s)",
            until_str,
            until_utc.isoformat(),
        )

        # NM notification — Bug Class #23: gated by observation mode.
        # _send_nm_alert itself does not gate obs mode; button must check.
        try:
            if not energy._observation_mode:
                await energy._send_nm_alert(
                    title="EV Force-Charge Override Active",
                    message=(
                        f"EV force-charge window opened until {until_str}. "
                        f"Mid-peak rates apply. Override auto-expires in "
                        f"{self._OVERRIDE_MINUTES} min."
                    ),
                    severity="low",
                )
            else:
                _LOGGER.debug(
                    "EVSEForceChargeButton: NM notification suppressed (observation mode)"
                )
        except Exception:
            _LOGGER.debug(
                "EVSEForceChargeButton: NM notification failed (non-fatal)",
                exc_info=True,
            )


# ============================================================================
# Pillar B (Phase 5) D4: Optimization Coordinator admin buttons
# ============================================================================
#
# Four button entities on the URA: Optimization Coordinator device. None
# touch the DB directly — every action mutates `entry.options` via
# `async_update_entry` (the Pillar B suppress-allowlist keeps this from
# triggering a CM reload) or calls a coordinator runtime method.
#
# Pattern: modeled on `ResetPresenceTimersButton` (button.py:593) for the
# options-strip flow; on `EVSEForceChargeButton` (button.py:1308) for the
# coordinator-fetch + signal-driven availability flow.


_OPT_COORD_DEVICE_NAME = "URA: Optimization Coordinator"
_OPT_COORD_IDENT = "optimization_coordinator"


def _optimizer_device_info_button():
    """Return the OC device_info for button entities."""
    from homeassistant.helpers.device_registry import DeviceInfo
    from .const import VERSION
    return DeviceInfo(
        identifiers={(DOMAIN, _OPT_COORD_IDENT)},
        name=_OPT_COORD_DEVICE_NAME,
        manufacturer="Universal Room Automation",
        model="Optimization Coordinator",
        sw_version=VERSION,
        via_device=(DOMAIN, "coordinator_manager"),
    )


def _refresh_autonomy_select(hass: HomeAssistant) -> None:
    """Find the OptimizerAutonomyLevelSelect (if loaded) and refresh state.

    The select entity reads pending/committed values from entry.options.
    After mutating those keys we push a live state refresh so the UI
    reflects the commit/cancel WITHOUT waiting for a CM reload.
    Bug Class #14 (config staleness) — read-only sweep over hass.data.
    """
    try:
        from .select import OptimizerAutonomyLevelSelect  # local import: avoid cycle
    except Exception:  # noqa: BLE001
        return
    # Walk the integration's known platform registries via the entity
    # registry is heavy; the simpler portable approach is to dispatch a
    # signal the select listens to. The select also re-derives on next
    # config-entry update — so this is best-effort. Use the public
    # `hass.data[DOMAIN]['optimizer_autonomy_select']` slot if populated.
    sel = hass.data.get(DOMAIN, {}).get("optimizer_autonomy_select")
    if sel is None or not isinstance(sel, OptimizerAutonomyLevelSelect):
        return
    try:
        sel._refresh_from_options()
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Optimizer autonomy select refresh failed", exc_info=True)


class _OptimizerCMButtonBase(ButtonEntity):
    """Common base for the four OC buttons.

    Availability push (v5.3.4 live finding): these buttons derive
    ``available`` from CM entry.options (pending-escalation key, kill
    switch), but nothing pushed a state write after options changed —
    Confirm/Cancel stayed greyed out indefinitely after the operator
    staged an escalation. Each button now subscribes to the entry's
    update listener and rewrites its own state on ANY CM options change
    (stage / cancel / confirm / kill / form save), so availability flips
    immediately.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_device_info = _optimizer_device_info_button()

    async def async_added_to_hass(self) -> None:
        """Subscribe to CM entry updates for push-based availability.

        Boot-staleness corner (v5.3.5 live finding): availability also
        depends on hass.data state (optimizer registered — matters for
        Run Cycle Now), which is NOT an options change — at boot the button
        can be added before the optimizer registers and then never
        re-evaluate. Two bounded one-shot refreshes (30s/180s) cover the
        coordinator-registration window; both cancelled with the entity.
        """
        await super().async_added_to_hass()
        self.async_on_remove(
            self._entry.add_update_listener(self._async_entry_updated)
        )
        for delay in (30, 180):
            self.async_on_remove(
                async_call_later(self.hass, delay, self._delayed_refresh)
            )

    @callback
    def _delayed_refresh(self, _now) -> None:
        """One-shot post-boot availability re-evaluation."""
        self.async_write_ha_state()

    async def _async_entry_updated(self, _hass, _entry) -> None:
        """CM options changed — re-evaluate availability immediately."""
        self.async_write_ha_state()

    def _get_optimizer(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        try:
            return manager.coordinators.get("optimization")
        except Exception:  # noqa: BLE001
            return None


class OptimizerConfirmEscalationButton(_OptimizerCMButtonBase):
    """Commit a staged `optimizer_pending_autonomy_level` to the real key.

    Entity: button.ura_optimizer_confirm_escalation
    Device: URA: Optimization Coordinator

    Behaviour:
      - Reads ``optimizer_pending_autonomy_level`` from CM entry.options.
      - Writes it onto ``optimizer_autonomy_level`` AND strips the pending
        key in the same `async_update_entry` call (one CM diff event).
      - No-op when no pending key exists.
    """

    _attr_icon = "mdi:check-bold"
    _attr_translation_key = "optimizer_confirm_escalation"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_optimizer_confirm_escalation"
        self._attr_name = "Confirm Escalation"

    @property
    def available(self) -> bool:
        from .const import CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL
        opts = self._entry.options or {}
        return CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL in opts and bool(
            opts.get(CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL)
        )

    async def async_press(self) -> None:
        from .const import (
            CONF_OPTIMIZER_AUTONOMY_LEVEL,
            CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL,
            OPTIMIZER_AUTONOMY_LEVELS,
        )
        opts = dict(self._entry.options or {})
        pending = opts.get(CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL)
        if pending is None:
            _LOGGER.debug(
                "OptimizerConfirmEscalation: no pending escalation, no-op",
            )
            return
        if pending not in OPTIMIZER_AUTONOMY_LEVELS:
            # Pillar B fix-up A-M6: an invalid / garbage pending value
            # (manual config edit, schema drift) self-heals by stripping
            # the bad key + WARNing. Old behaviour was a silent no-op
            # that left Confirm permanently "lit" with nothing to commit.
            _LOGGER.warning(
                "OptimizerConfirmEscalation: invalid pending value %r — "
                "stripping (self-heal)",
                pending,
            )
            opts.pop(CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL, None)
            try:
                self.hass.config_entries.async_update_entry(
                    self._entry, options=opts,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "OptimizerConfirmEscalation: self-heal write failed",
                    exc_info=True,
                )
            _refresh_autonomy_select(self.hass)
            return
        # Atomic commit + strip in a single options update.
        opts[CONF_OPTIMIZER_AUTONOMY_LEVEL] = pending
        opts.pop(CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL, None)
        try:
            self.hass.config_entries.async_update_entry(
                self._entry, options=opts,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "OptimizerConfirmEscalation: options write failed",
                exc_info=True,
            )
            return
        _LOGGER.info(
            "Optimizer autonomy escalation CONFIRMED → %s", pending,
        )
        _refresh_autonomy_select(self.hass)


class OptimizerCancelEscalationButton(_OptimizerCMButtonBase):
    """Strip the staged pending key without committing.

    Entity: button.ura_optimizer_cancel_escalation
    Device: URA: Optimization Coordinator
    """

    _attr_icon = "mdi:close-circle-outline"
    _attr_translation_key = "optimizer_cancel_escalation"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_optimizer_cancel_escalation"
        self._attr_name = "Cancel Escalation"

    @property
    def available(self) -> bool:
        from .const import CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL
        opts = self._entry.options or {}
        return CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL in opts and bool(
            opts.get(CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL)
        )

    async def async_press(self) -> None:
        from .const import CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL
        opts = dict(self._entry.options or {})
        if CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL not in opts:
            return
        opts.pop(CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL, None)
        try:
            self.hass.config_entries.async_update_entry(
                self._entry, options=opts,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "OptimizerCancelEscalation: options write failed",
                exc_info=True,
            )
            return
        _LOGGER.info("Optimizer autonomy escalation CANCELLED")
        _refresh_autonomy_select(self.hass)


# Optimizer CONF_* keys this button strips (everything except the kill
# switch — preserving the kill switch on accidental Reset is the safety
# contract; engaging Kill should be sticky until the operator releases it).
# Pillar B fix-up A-L10: use the CONF_* constants instead of string
# literals so a future rename of a CONF token surfaces here at import
# time rather than as a silent miss in the reset sweep.
def _build_optimizer_reset_keys() -> tuple[str, ...]:
    from .const import (
        CONF_OPTIMIZER_AUTONOMY_LEVEL,
        CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL,
        CONF_OPTIMIZER_DIMENSION_AUTONOMY,
        CONF_OPTIMIZER_CONFIDENCE_GATE,
        CONF_OPTIMIZER_RATE_CAP_PER_HOUR,
        CONF_OPTIMIZER_QUIET_HOURS_SOURCE,
        CONF_OPTIMIZER_LLM_TASK_ENTITY,
        CONF_OPTIMIZER_LLM_TRIAGE_ENTITY,
        CONF_OPTIMIZER_LLM_SYSTEM_PROMPT,
        CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
        CONF_OPTIMIZER_SAFETY_DENY_ENTITIES,
    )
    return (
        CONF_OPTIMIZER_AUTONOMY_LEVEL,
        CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL,
        CONF_OPTIMIZER_DIMENSION_AUTONOMY,
        CONF_OPTIMIZER_CONFIDENCE_GATE,
        CONF_OPTIMIZER_RATE_CAP_PER_HOUR,
        CONF_OPTIMIZER_QUIET_HOURS_SOURCE,
        CONF_OPTIMIZER_LLM_TASK_ENTITY,
        CONF_OPTIMIZER_LLM_TRIAGE_ENTITY,
        CONF_OPTIMIZER_LLM_SYSTEM_PROMPT,
        CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
        CONF_OPTIMIZER_SAFETY_DENY_ENTITIES,
    )


_OPTIMIZER_RESET_KEYS: tuple[str, ...] = _build_optimizer_reset_keys()


class OptimizerResetSettingsButton(_OptimizerCMButtonBase):
    """Strip all optimizer CONF_* keys from entry.options (preserves kill switch).

    Entity: button.ura_optimizer_reset_settings
    Device: URA: Optimization Coordinator

    Preserves ``optimizer_kill_switch`` so an accidental tap can't release
    a tripped kill (operator must explicitly turn the kill switch OFF).
    """

    _attr_icon = "mdi:backup-restore"
    _attr_translation_key = "optimizer_reset_settings"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_optimizer_reset_settings"
        self._attr_name = "Reset Optimizer Settings"

    async def async_press(self) -> None:
        opts = dict(self._entry.options or {})
        removed = []
        for key in _OPTIMIZER_RESET_KEYS:
            if key in opts:
                opts.pop(key, None)
                removed.append(key)
        if not removed:
            _LOGGER.info("Optimizer Reset: no optimizer keys to strip")
            return
        try:
            self.hass.config_entries.async_update_entry(
                self._entry, options=opts,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "OptimizerResetSettings: options write failed",
                exc_info=True,
            )
            return
        _LOGGER.info(
            "Optimizer settings reset to defaults; stripped %d keys "
            "(kill switch preserved)",
            len(removed),
        )
        _refresh_autonomy_select(self.hass)


class OptimizerRunCycleNowButton(_OptimizerCMButtonBase):
    """Trigger an out-of-band optimizer cycle.

    Entity: button.ura_optimizer_run_cycle_now
    Device: URA: Optimization Coordinator

    Calls ``coord.run_cycle()`` directly. The Optimization Coordinator is
    NOT a DataUpdateCoordinator (it runs via a 5-min interval that calls
    ``run_cycle()`` at optimization.py:658); there is no
    ``async_request_refresh`` method. The reentrancy guard inside
    ``run_cycle`` itself protects manual-press-vs-interval (and tick-vs-tick)
    overlap. Debounced to one press per 30s. Unavailable when kill switch
    is ON (the cycle would be a no-op).
    """

    _attr_icon = "mdi:refresh"
    _attr_translation_key = "optimizer_run_cycle_now"
    _DEBOUNCE_SECONDS = 30.0

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_optimizer_run_cycle_now"
        self._attr_name = "Run Cycle Now"
        # None sentinel, NOT 0.0: monotonic() can start near zero (process
        # start on some builds; time-since-boot on HA OS right after a host
        # reboot), and a 0.0 sentinel would swallow the FIRST press for
        # _DEBOUNCE_SECONDS in that window.
        self._last_press: float | None = None

    @property
    def available(self) -> bool:
        from .const import CONF_OPTIMIZER_KILL_SWITCH
        if self._get_optimizer() is None:
            return False
        opts = self._entry.options or {}
        return not bool(opts.get(CONF_OPTIMIZER_KILL_SWITCH, False))

    async def async_press(self) -> None:
        import time as _time
        now = _time.monotonic()
        if (
            self._last_press is not None
            and now - self._last_press < self._DEBOUNCE_SECONDS
        ):
            _LOGGER.info(
                "OptimizerRunCycleNow: debounced (last press %.1fs ago, "
                "min interval %.1fs)",
                now - self._last_press, self._DEBOUNCE_SECONDS,
            )
            return
        self._last_press = now
        coord = self._get_optimizer()
        if coord is None:
            _LOGGER.debug(
                "OptimizerRunCycleNow: no optimization coordinator loaded",
            )
            return
        try:
            # OptimizationCoordinator is not a DataUpdateCoordinator —
            # call the public ``run_cycle`` entry point directly. The
            # reentrancy guard inside run_cycle handles
            # manual-press-vs-interval overlap.
            await coord.run_cycle()
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "OptimizerRunCycleNow: run_cycle raised",
                exc_info=True,
            )
            return
        _LOGGER.info("Optimizer cycle requested manually via Run Cycle Now")
