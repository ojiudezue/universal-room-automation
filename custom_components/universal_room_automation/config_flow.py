"""Config flow for Universal Room Automation v3.6.24."""
#
# Universal Room Automation v3.9.0
# Build: 2026-01-05
# File: config_flow.py
# v3.3.3: Added manage_zones to integration options menu
# v3.3.3: Zone configuration accessible from integration entry
# v3.3.1: Added music_following and zone_media options steps
# v3.3.1: Fixed person_tracking missing from strings.json
# v3.2.4: CONF_SCANNER_AREAS replaces CONF_PHONE_TRACKER for person tracking
#

import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.const import CONF_NAME

_LOGGER = logging.getLogger(__name__)

from .const import (
    DOMAIN,
    # v3.0.0 Entry types
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ROOM,
    ENTRY_TYPE_ZONE,
    ENTRY_TYPE_ZONE_MANAGER,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    CONF_ENTRY_TYPE,
    CONF_INTEGRATION_ENTRY_ID,
    CONF_OVERRIDE_NOTIFICATIONS,
    # Basic setup
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
    CONF_AREA_ID,
    CONF_OCCUPANCY_TIMEOUT,
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_CLOSET,
    ROOM_TYPE_BATHROOM,
    ROOM_TYPE_MEDIA_ROOM,
    ROOM_TYPE_GARAGE,
    ROOM_TYPE_UTILITY,
    ROOM_TYPE_COMMON_AREA,
    ROOM_TYPE_GENERIC,
    DEFAULT_OCCUPANCY_TIMEOUT,
    ROOM_TYPE_TIMEOUTS,
    # Integration-level config
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_OUTSIDE_HUMIDITY_SENSOR,
    CONF_WEATHER_ENTITY,
    CONF_SOLAR_PRODUCTION_SENSOR,
    CONF_ELECTRICITY_RATE_SENSOR,
    # v3.2.0: Person tracking
    CONF_TRACKED_PERSONS,
    CONF_PERSON_DATA_RETENTION,
    CONF_TRANSITION_DETECTION_WINDOW,
    DEFAULT_PERSON_DATA_RETENTION,
    DEFAULT_TRANSITION_WINDOW,
    # v3.1.6: Energy setup
    CONF_SOLAR_EXPORT_SENSOR,
    CONF_GRID_IMPORT_SENSOR,
    CONF_GRID_IMPORT_SENSOR_2,
    CONF_BATTERY_LEVEL_SENSOR,
    CONF_WHOLE_HOUSE_POWER_SENSOR,
    CONF_WHOLE_HOUSE_ENERGY_SENSOR,
    CONF_DELIVERY_RATE,
    CONF_EXPORT_REIMBURSEMENT_RATE,
    DEFAULT_DELIVERY_RATE,
    DEFAULT_EXPORT_REIMBURSEMENT_RATE,
    # Sensors
    CONF_MOTION_SENSORS,
    CONF_MMWAVE_SENSORS,
    CONF_OCCUPANCY_SENSORS,
    CONF_PHONE_TRACKER,  # DEPRECATED in v3.2.4 - kept for migration
    CONF_SCANNER_AREAS,  # v3.2.4: Scanner areas for sparse scanner homes
    CONF_DOOR_SENSORS,
    CONF_DOOR_TYPE,
    CONF_WINDOW_SENSORS,
    CONF_TEMPERATURE_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_ILLUMINANCE_SENSOR,
    DOOR_TYPE_INTERIOR,
    DOOR_TYPE_EGRESS,
    # Devices
    CONF_LIGHTS,
    CONF_LIGHT_CAPABILITIES,
    CONF_FANS,
    CONF_HUMIDITY_FANS,
    CONF_COVERS,
    CONF_COVER_TYPE,
    CONF_AUTO_SWITCHES,
    CONF_MANUAL_SWITCHES,
    LIGHT_CAPABILITY_BASIC,
    LIGHT_CAPABILITY_BRIGHTNESS,
    LIGHT_CAPABILITY_FULL,
    COVER_TYPE_SHADE,
    COVER_TYPE_TILT,
    # v3.2.2.5: Night lights
    CONF_NIGHT_LIGHTS,
    CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    CONF_NIGHT_LIGHT_SLEEP_COLOR,
    CONF_NIGHT_LIGHT_DAY_BRIGHTNESS,
    CONF_NIGHT_LIGHT_DAY_COLOR,
    DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    DEFAULT_NIGHT_LIGHT_SLEEP_COLOR,
    DEFAULT_NIGHT_LIGHT_DAY_BRIGHTNESS,
    DEFAULT_NIGHT_LIGHT_DAY_COLOR,
    # Automation behavior
    CONF_ENTRY_LIGHT_ACTION,
    CONF_EXIT_LIGHT_ACTION,
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_LIGHT_BRIGHTNESS_PCT,
    CONF_LIGHT_TRANSITION_ON,
    CONF_LIGHT_TRANSITION_OFF,
    CONF_EXIT_COVER_ACTION,
    CONF_SUNRISE_OFFSET,
    CONF_SUNSET_OFFSET,
    CONF_TIMED_CLOSE_ENABLED,
    # v3.6.39: New cover config
    CONF_COVER_OPEN_MODE,
    COVER_OPEN_NONE,
    COVER_OPEN_ON_ENTRY,
    COVER_OPEN_AT_TIME,
    COVER_OPEN_ON_ENTRY_AFTER_TIME,
    COVER_OPEN_AT_TIME_OR_ON_ENTRY,
    CONF_COVER_OPEN_TIME_SOURCE,
    TIME_SOURCE_SUNRISE,
    TIME_SOURCE_SPECIFIC_HOUR,
    CONF_COVER_OPEN_HOUR,
    DEFAULT_COVER_OPEN_HOUR,
    CONF_COVER_CLOSE_TIME_SOURCE,
    TIME_SOURCE_SUNSET,
    CONF_COVER_CLOSE_HOUR,
    DEFAULT_COVER_CLOSE_HOUR,
    LIGHT_ACTION_NONE,
    LIGHT_ACTION_TURN_ON,
    LIGHT_ACTION_TURN_ON_IF_DARK,
    LIGHT_ACTION_TURN_OFF,
    LIGHT_ACTION_LEAVE_ON,
    COVER_ACTION_NONE,
    COVER_ACTION_ALWAYS,
    COVER_ACTION_AFTER_SUNSET,
    DEFAULT_DARK_THRESHOLD,
    DEFAULT_LIGHT_BRIGHTNESS,
    DEFAULT_LIGHT_TRANSITION_ON,
    DEFAULT_LIGHT_TRANSITION_OFF,
    DEFAULT_SUNRISE_OFFSET,
    DEFAULT_SUNSET_OFFSET,
    # Climate & HVAC
    CONF_CLIMATE_ENTITY,
    CONF_HVAC_COORDINATION_ENABLED,
    CONF_TARGET_TEMP_COOL,
    CONF_TARGET_TEMP_HEAT,
    CONF_FAN_CONTROL_ENABLED,
    CONF_FAN_TEMP_THRESHOLD,
    CONF_FAN_SPEED_LOW_TEMP,
    CONF_FAN_SPEED_MED_TEMP,
    CONF_FAN_SPEED_HIGH_TEMP,
    CONF_HUMIDITY_FAN_THRESHOLD,
    CONF_HUMIDITY_FAN_TIMEOUT,
    CONF_HVAC_EFFICIENCY_ALERTS,
    DEFAULT_TARGET_TEMP_COOL,
    DEFAULT_TARGET_TEMP_HEAT,
    DEFAULT_FAN_TEMP_THRESHOLD,
    DEFAULT_FAN_SPEED_LOW,
    DEFAULT_FAN_SPEED_MED,
    DEFAULT_FAN_SPEED_HIGH,
    DEFAULT_HUMIDITY_THRESHOLD,
    DEFAULT_HUMIDITY_FAN_TIMEOUT,
    # Sleep protection
    CONF_SLEEP_PROTECTION_ENABLED,
    CONF_SLEEP_START_HOUR,
    CONF_SLEEP_END_HOUR,
    CONF_SLEEP_BYPASS_MOTION,
    CONF_SLEEP_BLOCK_COVERS,
    DEFAULT_SLEEP_START,
    DEFAULT_SLEEP_END,
    DEFAULT_SLEEP_BYPASS_COUNT,
    # Energy
    CONF_POWER_SENSORS,
    CONF_ENERGY_SENSOR,
    CONF_ELECTRICITY_RATE,
    CONF_NOTIFY_DAILY_ENERGY,
    DEFAULT_ELECTRICITY_RATE,
    # Notifications
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TARGET,
    CONF_NOTIFY_LEVEL,
    NOTIFY_LEVEL_OFF,
    NOTIFY_LEVEL_ERRORS,
    NOTIFY_LEVEL_IMPORTANT,
    NOTIFY_LEVEL_ALL,
    # v3.1.0: Zone and shared space
    CONF_ZONE,
    CONF_ZONE_NAME,
    CONF_ZONE_ROOMS,
    CONF_ZONE_DESCRIPTION,
    CONF_ZONE_THERMOSTAT,
    CONF_SHARED_SPACE,
    CONF_SHARED_SPACE_AUTO_OFF_HOUR,
    CONF_SHARED_SPACE_WARNING,
    CONF_WATER_LEAK_SENSOR,
    CONF_ALERT_LIGHTS,
    CONF_ALERT_LIGHT_COLOR,
    ALERT_COLOR_AMBER,
    ALERT_COLOR_RED,
    ALERT_COLOR_BLUE,
    ALERT_COLOR_GREEN,
    ALERT_COLOR_WHITE,
    DEFAULT_SHARED_SPACE_AUTO_OFF_HOUR,
    # v3.3.1: Music following
    CONF_ROOM_MEDIA_PLAYER,
    CONF_MUSIC_FOLLOWING_ENABLED,
    CONF_ZONE_PLAYER_ENTITY,
    CONF_ZONE_PLAYER_MODE,
    ZONE_PLAYER_MODE_INDEPENDENT,
    ZONE_PLAYER_MODE_AGGREGATE,
    ZONE_PLAYER_MODE_FALLBACK,
    # v3.5.0: Camera Census
    CONF_CAMERA_PERSON_ENTITIES,
    CONF_EGRESS_CAMERAS,
    CONF_PERIMETER_CAMERAS,
    CONF_CENSUS_CROSS_VALIDATION,
    # v3.5.1: Perimeter Alerting
    CONF_PERIMETER_ALERT_HOURS_START,
    CONF_PERIMETER_ALERT_HOURS_END,
    CONF_PERIMETER_ALERT_NOTIFY_SERVICE,
    CONF_PERIMETER_ALERT_NOTIFY_TARGET,
    DEFAULT_PERIMETER_ALERT_START,
    DEFAULT_PERIMETER_ALERT_END,
    # v3.5.2: Face Recognition
    CONF_FACE_RECOGNITION_ENABLED,
)


class UniversalRoomAutomationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Universal Room Automation v3.0.0."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data = {}
        self._integration_data = None  # Stores integration config if creating first time
        self._energy_data = None  # Stores energy config
        self._integration_entry_id = None  # ID of existing integration entry

    def _find_integration_entry(self):
        """Find existing integration entry if one exists."""
        for entry in self._async_current_entries():
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                return entry
        return None

    def _find_zone_manager_entry(self):
        """Find the Zone Manager entry if one exists (v3.6.0)."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
                return entry
        return None

    async def async_step_user(self, user_input=None):
        """Entry point - routes to integration or entry type selection."""
        # Find existing integration entry
        integration_entry = self._find_integration_entry()
        
        if integration_entry:
            # Integration exists → Show entry type selection menu
            self._integration_entry_id = integration_entry.entry_id
            return await self.async_step_entry_type_select()
        else:
            # First time → Create integration first
            return await self.async_step_integration_config()
    
    async def async_step_entry_type_select(self, user_input=None):
        """Let user choose what type of entry to add."""
        return self.async_show_menu(
            step_id="entry_type_select",
            menu_options=["add_room", "add_zone", "add_coordinator"],
        )
    
    async def async_step_add_room(self, user_input=None):
        """Route to room setup."""
        return await self.async_step_room_setup()
    
    async def async_step_add_zone(self, user_input=None):
        """Route to zone setup."""
        return await self.async_step_zone_setup()
    
    async def async_step_add_coordinator(self, user_input=None):
        """Route to coordinator enable flow (v3.6.0).

        Domain coordinators are enabled via the integration options flow,
        not by creating a separate config entry.
        """
        return self.async_abort(reason="coordinator_use_options")
    
    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfigure flow - redirect to options flow."""
        # Reconfigure should use the options flow
        # This prevents the empty dialog issue
        return self.async_abort(reason="reconfigure_use_options")
    
    def _get_mobile_app_targets(self) -> list[dict]:
        """Get mobile_app notification targets as dropdown options."""
        targets = [{"label": "None", "value": ""}]
        
        if "notify" in self.hass.services.async_services():
            for service_name in self.hass.services.async_services()["notify"].keys():
                if service_name.startswith("mobile_app_"):
                    # Extract friendly name from mobile_app_xxx
                    device_name = service_name.replace("mobile_app_", "").replace("_", " ").title()
                    targets.append({
                        "label": device_name,
                        "value": f"notify.{service_name}"
                    })
        
        # If no mobile apps found, add generic option
        if len(targets) == 1:
            targets.append({"label": "No mobile apps found", "value": ""})
        
        return targets
    
    def _get_all_room_entries(self) -> list:
        """Get all room config entries."""
        return [
            entry for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM
        ]
    
    def _get_all_zone_entries(self) -> list:
        """Get all zone config entries."""
        return [
            entry for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE
        ]

    def _get_area_entities(self, area_id: str, domain: str, device_class: str | list[str] | None = None) -> list[str]:
        """Get entities in an area by domain, with device area_id fallback.

        v3.6.24: Area entity discovery for config UX pre-population.
        Uses entity_registry direct area_id first, then falls back to
        device_registry area_id (matching presence coordinator pattern).
        """
        if not area_id:
            return []

        from homeassistant.helpers import entity_registry as er, device_registry as dr

        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)

        # Normalize device_class to a set for matching
        if device_class is None:
            dc_set = None
        elif isinstance(device_class, str):
            dc_set = {device_class}
        else:
            dc_set = set(device_class)

        results = []
        for entry in ent_reg.entities.values():
            # Domain filter
            if entry.domain != domain:
                continue
            # Skip disabled/hidden entities
            if entry.disabled_by is not None:
                continue
            # Device class filter
            if dc_set is not None:
                if entry.original_device_class not in dc_set and entry.device_class not in dc_set:
                    continue
            # Area match: entity area_id first, then device area_id fallback
            entity_area = entry.area_id
            if not entity_area and entry.device_id:
                device = dev_reg.async_get(entry.device_id)
                if device:
                    entity_area = device.area_id
            if entity_area == area_id:
                results.append(entry.entity_id)

        return sorted(results)

    def _detect_light_capabilities(self, entity_ids: list[str]) -> str:
        """Auto-detect light capabilities from supported_features.

        v3.6.24: Reads supported_features from entity states.
        SUPPORT_COLOR (16) → full, SUPPORT_COLOR_TEMP (2) → brightness,
        SUPPORT_BRIGHTNESS (1) → brightness, else → basic.
        """
        if not entity_ids:
            return LIGHT_CAPABILITY_BASIC

        best = LIGHT_CAPABILITY_BASIC
        for eid in entity_ids:
            state = self.hass.states.get(eid)
            if state is None:
                continue
            features = state.attributes.get("supported_features", 0) or 0
            if features & 16:  # SUPPORT_COLOR
                return LIGHT_CAPABILITY_FULL  # Can't get better than full
            if features & 2:  # SUPPORT_COLOR_TEMP
                best = LIGHT_CAPABILITY_BRIGHTNESS
            elif features & 1 and best == LIGHT_CAPABILITY_BASIC:  # SUPPORT_BRIGHTNESS
                best = LIGHT_CAPABILITY_BRIGHTNESS
        return best

    async def async_step_integration_config(self, user_input=None):
        """Configure integration-level settings (global sensors, default notifications)."""
        if user_input is not None:
            # Store integration config for later
            self._integration_data = user_input
            # v3.1.6: Route to energy setup next
            return await self.async_step_energy_setup()
        
        # Get available notify services for default notifications
        notify_services = []
        if "notify" in self.hass.services.async_services():
            for service_name in self.hass.services.async_services()["notify"].keys():
                notify_services.append({
                    "label": f"notify.{service_name}",
                    "value": f"notify.{service_name}"
                })
        
        if not notify_services:
            notify_services.append({
                "label": "No notify services configured",
                "value": ""
            })
        
        notify_levels = [
            {"label": "Off", "value": NOTIFY_LEVEL_OFF},
            {"label": "Errors Only", "value": NOTIFY_LEVEL_ERRORS},
            {"label": "Important Events", "value": NOTIFY_LEVEL_IMPORTANT},
            {"label": "All Events", "value": NOTIFY_LEVEL_ALL},
        ]

        data_schema = vol.Schema({
            # Global Sensors
            vol.Optional(CONF_OUTSIDE_TEMP_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional(CONF_OUTSIDE_HUMIDITY_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
            ),
            vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            vol.Optional(CONF_SOLAR_PRODUCTION_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            # v3.2.0: Person Tracking
            vol.Optional(CONF_TRACKED_PERSONS, default=[]): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="person",
                    multiple=True
                )
            ),
            vol.Optional(CONF_PERSON_DATA_RETENTION, default=DEFAULT_PERSON_DATA_RETENTION): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=365,
                    step=1,
                    unit_of_measurement="days",
                    mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(CONF_TRANSITION_DETECTION_WINDOW, default=DEFAULT_TRANSITION_WINDOW): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=30,
                    max=300,
                    step=10,
                    unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.SLIDER
                )
            ),
            # Default electricity rate
            vol.Required(CONF_ELECTRICITY_RATE, default=DEFAULT_ELECTRICITY_RATE): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.01, max=1.00, step=0.01, 
                    unit_of_measurement="USD/kWh", 
                    mode=selector.NumberSelectorMode.BOX
                )
            ),
            # Default Notifications
            vol.Optional(CONF_NOTIFY_SERVICE): selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify_services, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_NOTIFY_TARGET): selector.SelectSelector(
                selector.SelectSelectorConfig(options=self._get_mobile_app_targets(), mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_NOTIFY_LEVEL, default=NOTIFY_LEVEL_ERRORS): selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify_levels, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
        })
        
        return self.async_show_form(
            step_id="integration_config",
            data_schema=data_schema,
        )

    async def async_step_energy_setup(self, user_input=None):
        """Configure integration-level energy sensors for predictions and tracking."""
        if user_input is not None:
            # Store energy config and merge with integration data
            self._energy_data = user_input
            return await self.async_step_add_first_room()
        
        data_schema = vol.Schema({
            # Solar/Grid sensors
            vol.Optional(CONF_SOLAR_EXPORT_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
            vol.Optional(CONF_GRID_IMPORT_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
            vol.Optional(CONF_GRID_IMPORT_SENSOR_2): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
            # Battery
            vol.Optional(CONF_BATTERY_LEVEL_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="battery")
            ),
            # Whole house monitoring
            vol.Optional(CONF_WHOLE_HOUSE_POWER_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Optional(CONF_WHOLE_HOUSE_ENERGY_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
            # Rates
            vol.Optional(CONF_DELIVERY_RATE, default=DEFAULT_DELIVERY_RATE): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.00, max=0.50, step=0.01,
                    unit_of_measurement="USD/kWh",
                    mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(CONF_EXPORT_REIMBURSEMENT_RATE, default=DEFAULT_EXPORT_REIMBURSEMENT_RATE): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.00, max=0.50, step=0.01,
                    unit_of_measurement="USD/kWh",
                    mode=selector.NumberSelectorMode.BOX
                )
            ),
        })
        
        return self.async_show_form(
            step_id="energy_setup",
            data_schema=data_schema,
        )

    async def async_step_add_first_room(self, user_input=None):
        """Redirect to post-integration setup menu."""
        return await self.async_step_post_integration_setup()

    async def async_step_post_integration_setup(self, user_input=None):
        """Show menu after integration setup - zone, room, or finish."""
        # First create the integration entry with both config and energy data
        if self._integration_data:
            combined_data = {
                CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
                **self._integration_data
            }
            # Merge energy data if present
            if self._energy_data:
                combined_data.update(self._energy_data)
            
            result = self.async_create_entry(
                title="🏠 Home",
                data=combined_data
            )
            self._integration_data = None  # Clear so we don't recreate
            self._energy_data = None
            return result
        
        # If we get here without integration_data, just show menu
        return self.async_show_menu(
            step_id="post_integration_setup",
            menu_options=["setup_zone", "skip_to_room", "finish"],
        )
    
    async def async_step_setup_zone(self, user_input=None):
        """Route to zone setup from post-integration menu."""
        return await self.async_step_zone_setup()
    
    async def async_step_skip_to_room(self, user_input=None):
        """Route to room setup from post-integration menu."""
        return await self.async_step_room_setup()
    
    async def async_step_finish(self, user_input=None):
        """Finish setup without adding anything else."""
        return self.async_abort(reason="not_supported")
    
    async def async_step_zone_setup(self, user_input=None):
        """Handle zone setup."""
        errors = {}
        
        if user_input is not None:
            zone_name = user_input.get(CONF_ZONE_NAME, "").strip()
            
            # Validate zone name
            if not zone_name:
                errors["base"] = "zone_name_exists"
            else:
                # Check for duplicate zone names
                existing_zones = self._get_existing_zones()
                if zone_name.lower() in [z.lower() for z in existing_zones]:
                    errors["base"] = "zone_name_exists"
            
            if not errors:
                # Get selected room entries and update their zone
                selected_rooms = user_input.get(CONF_ZONE_ROOMS, [])

                # Update each room's zone assignment
                for room_entry_id in selected_rooms:
                    room_entry = self.hass.config_entries.async_get_entry(room_entry_id)
                    if room_entry:
                        new_options = dict(room_entry.options)
                        new_options[CONF_ZONE] = zone_name
                        self.hass.config_entries.async_update_entry(
                            room_entry,
                            options=new_options
                        )

                # v3.6.0: Add zone to Zone Manager entry instead of creating new entry
                zone_manager_entry = self._find_zone_manager_entry()
                if zone_manager_entry:
                    merged = {**zone_manager_entry.data, **zone_manager_entry.options}
                    zones = {
                        k: dict(v) for k, v in merged.get("zones", {}).items()
                    }
                    zones[zone_name] = {
                        CONF_ZONE_DESCRIPTION: user_input.get(CONF_ZONE_DESCRIPTION, ""),
                        CONF_ZONE_ROOMS: selected_rooms,
                    }
                    self.hass.config_entries.async_update_entry(
                        zone_manager_entry,
                        options={**zone_manager_entry.options, "zones": zones},
                    )
                    # Reload the zone manager entry to pick up the new zone
                    self.hass.async_create_task(
                        self.hass.config_entries.async_reload(zone_manager_entry.entry_id)
                    )
                    return self.async_abort(reason="zone_added")
                else:
                    # Fallback: create legacy zone entry if no Zone Manager exists
                    return self.async_create_entry(
                        title=f"📍 {zone_name}",
                        data={
                            CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE,
                            CONF_ZONE_NAME: zone_name,
                            CONF_ZONE_DESCRIPTION: user_input.get(CONF_ZONE_DESCRIPTION, ""),
                            CONF_ZONE_ROOMS: selected_rooms,
                            CONF_INTEGRATION_ENTRY_ID: self._integration_entry_id or self._find_integration_entry().entry_id,
                        }
                    )
        
        # Get room entries for selection
        room_entries = self._get_all_room_entries()
        room_options = [
            {
                "label": entry.data.get(CONF_ROOM_NAME, entry.title),
                "value": entry.entry_id
            }
            for entry in room_entries
        ]
        
        # Build schema based on whether rooms exist
        schema_fields = {
            vol.Required(CONF_ZONE_NAME): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Optional(CONF_ZONE_DESCRIPTION): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
        }
        
        # Only add room selector if rooms exist
        if room_options:
            schema_fields[vol.Optional(CONF_ZONE_ROOMS)] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=room_options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN
                )
            )
        
        data_schema = vol.Schema(schema_fields)
        
        return self.async_show_form(
            step_id="zone_setup",
            data_schema=data_schema,
            errors=errors,
        )
    
    async def async_step_room_setup(self, user_input=None):
        """Handle room setup - basic room information."""
        errors = {}

        if user_input is not None:
            self._data.update(user_input)
            # Set default timeout based on room type if not explicitly set
            if CONF_OCCUPANCY_TIMEOUT not in user_input:
                room_type = user_input.get(CONF_ROOM_TYPE, ROOM_TYPE_GENERIC)
                self._data[CONF_OCCUPANCY_TIMEOUT] = ROOM_TYPE_TIMEOUTS.get(
                    room_type, DEFAULT_OCCUPANCY_TIMEOUT
                )
            return await self.async_step_sensors()

        room_types = [
            {"label": "Bedroom", "value": ROOM_TYPE_BEDROOM},
            {"label": "Closet", "value": ROOM_TYPE_CLOSET},
            {"label": "Bathroom", "value": ROOM_TYPE_BATHROOM},
            {"label": "Media Room / Entertainment", "value": ROOM_TYPE_MEDIA_ROOM},
            {"label": "Garage / Workshop", "value": ROOM_TYPE_GARAGE},
            {"label": "Utility Room", "value": ROOM_TYPE_UTILITY},
            {"label": "Common Area (Living/Dining)", "value": ROOM_TYPE_COMMON_AREA},
            {"label": "Generic Room", "value": ROOM_TYPE_GENERIC},
        ]
        
        # v3.3.5.3: Get existing zones from Zone config entries
        existing_zones = self._get_existing_zones()
        zone_options = [{"label": z, "value": z} for z in sorted(existing_zones)]

        # Build base schema
        schema_fields = {
            vol.Required(CONF_ROOM_NAME): selector.TextSelector(),
            vol.Required(CONF_ROOM_TYPE, default=ROOM_TYPE_GENERIC): selector.SelectSelector(
                selector.SelectSelectorConfig(options=room_types, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_AREA_ID): selector.AreaSelector(),
        }
        
        # v3.3.5.3: Only add zone selector if zones exist
        # To create a new zone, use "Add new Zone" from integration options menu
        if zone_options:
            schema_fields[vol.Optional(CONF_ZONE)] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=zone_options,
                    custom_value=False,  # Select existing only
                    mode=selector.SelectSelectorMode.DROPDOWN
                )
            )
        
        # Add remaining fields
        schema_fields.update({
            # v3.1.0: Shared space settings
            vol.Optional(CONF_SHARED_SPACE, default=False): selector.BooleanSelector(),
            vol.Optional(CONF_SHARED_SPACE_AUTO_OFF_HOUR, default=DEFAULT_SHARED_SPACE_AUTO_OFF_HOUR): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=23, step=1,
                    unit_of_measurement="hour (0-23)",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(CONF_SHARED_SPACE_WARNING, default=True): selector.BooleanSelector(),
            vol.Optional(
                CONF_OCCUPANCY_TIMEOUT,
                default=DEFAULT_OCCUPANCY_TIMEOUT
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=60,
                    max=3600,
                    unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        })
        
        data_schema = vol.Schema(schema_fields)

        return self.async_show_form(
            step_id="room_setup",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"name": "Basic room setup"},
        )
    
    def _get_existing_zones(self) -> set[str]:
        """Get existing zones from Zone Manager and legacy Zone config entries.

        v3.6.0: Reads zones from the Zone Manager entry first, then falls
        back to legacy individual zone config entries for backward compat.
        """
        zones = set()
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
                merged = {**entry.data, **entry.options}
                for zone_name in merged.get("zones", {}):
                    zones.add(zone_name)
            elif entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
                zone_name = entry.data.get(CONF_ZONE_NAME)
                if zone_name:
                    zones.add(zone_name)
        return zones

    async def async_step_sensors(self, user_input=None):
        """Handle sensor configuration."""
        errors = {}

        if user_input is not None:
            # Validate at least one occupancy detection method
            motion = user_input.get(CONF_MOTION_SENSORS, [])
            mmwave = user_input.get(CONF_MMWAVE_SENSORS, [])
            occupancy = user_input.get(CONF_OCCUPANCY_SENSORS, [])

            if not motion and not mmwave and not occupancy:
                errors["base"] = "no_occupancy_sensors"
            else:
                self._data.update(user_input)
                return await self.async_step_devices()

        door_types = [
            {"label": "Interior Door (room-to-room)", "value": DOOR_TYPE_INTERIOR},
            {"label": "Egress Door (exterior/security)", "value": DOOR_TYPE_EGRESS},
        ]

        # v3.6.24: Area pre-population for initial setup
        area_id = self._data.get(CONF_AREA_ID)
        area_binary = self._get_area_entities(area_id, "binary_sensor") if area_id else []
        area_sensors = self._get_area_entities(area_id, "sensor") if area_id else []

        # Filter binary_sensors by device class for pre-population
        area_motion = self._get_area_entities(area_id, "binary_sensor", "motion") if area_id else []
        area_occupancy = self._get_area_entities(area_id, "binary_sensor", "occupancy") if area_id else []
        area_temp = self._get_area_entities(area_id, "sensor", "temperature") if area_id else []
        area_humidity = self._get_area_entities(area_id, "sensor", "humidity") if area_id else []
        area_illuminance = self._get_area_entities(area_id, "sensor", "illuminance") if area_id else []
        area_door = self._get_area_entities(area_id, "binary_sensor", ["door", "opening"]) if area_id else []
        area_window = self._get_area_entities(area_id, "binary_sensor", ["window", "door", "opening", "garage_door"]) if area_id else []
        area_water = self._get_area_entities(area_id, "binary_sensor", ["moisture", "water_leak"]) if area_id else []

        data_schema = vol.Schema({
            vol.Optional(CONF_MOTION_SENSORS, default=area_motion or []): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Optional(CONF_MMWAVE_SENSORS, default=[]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Optional(CONF_OCCUPANCY_SENSORS, default=area_occupancy or []): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            # v3.2.4: Scanner areas for sparse scanner homes
            # Optional - only needed if BLE scanners are in different HA areas than the room
            vol.Optional(CONF_SCANNER_AREAS, default=[]): selector.AreaSelector(
                selector.AreaSelectorConfig(multiple=True)
            ),
            vol.Optional(CONF_TEMPERATURE_SENSOR, default=area_temp[0] if area_temp else vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional(CONF_HUMIDITY_SENSOR, default=area_humidity[0] if area_humidity else vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
            ),
            vol.Optional(CONF_ILLUMINANCE_SENSOR, default=area_illuminance[0] if area_illuminance else vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="illuminance")
            ),
            vol.Optional(CONF_DOOR_SENSORS, default=area_door[0] if area_door else vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", device_class=["door", "opening"])
            ),
            vol.Optional(CONF_DOOR_TYPE, default=DOOR_TYPE_INTERIOR): selector.SelectSelector(
                selector.SelectSelectorConfig(options=door_types, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_WINDOW_SENSORS, default=area_window[0] if area_window else vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", device_class=["window", "door", "opening", "garage_door"])
            ),
            # v3.1.0: Water leak sensor
            vol.Optional(CONF_WATER_LEAK_SENSOR, default=area_water[0] if area_water else vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", device_class=["moisture", "water_leak"])
            ),
        })

        return self.async_show_form(
            step_id="sensors",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"name": "Configure sensors - at least one occupancy sensor required"},
        )

    async def async_step_devices(self, user_input=None):
        """Handle device configuration.

        v3.6.24: Night light detail fields moved to conditional sub-step.
        Cover type moved to cover_behavior sub-step. Area pre-population added.
        """
        if user_input is not None:
            self._data.update(user_input)
            # v3.6.24: Conditional routing — night light detail if night lights selected
            if user_input.get(CONF_NIGHT_LIGHTS):
                return await self.async_step_night_light_detail()
            # v3.6.24: Skip to cover_behavior if covers, else automation_behavior
            if user_input.get(CONF_COVERS):
                return await self.async_step_cover_behavior()
            return await self.async_step_automation_behavior()

        # v3.6.24: Area pre-population
        area_id = self._data.get(CONF_AREA_ID)
        area_lights = self._get_area_entities(area_id, "light") if area_id else []
        area_fans = self._get_area_entities(area_id, "fan") if area_id else []
        area_covers = self._get_area_entities(area_id, "cover") if area_id else []
        area_switches = self._get_area_entities(area_id, "switch") if area_id else []

        # v3.6.24: Auto-detect light capabilities from area lights
        detected_cap = self._detect_light_capabilities(area_lights) if area_lights else LIGHT_CAPABILITY_BASIC

        light_capabilities = [
            {"label": "Basic On/Off Only", "value": LIGHT_CAPABILITY_BASIC},
            {"label": "Brightness Control", "value": LIGHT_CAPABILITY_BRIGHTNESS},
            {"label": "Brightness + Color", "value": LIGHT_CAPABILITY_FULL},
        ]

        data_schema = vol.Schema({
            vol.Optional(CONF_LIGHTS, default=area_lights or []): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["light", "switch"], multiple=True)
            ),
            vol.Optional(CONF_LIGHT_CAPABILITIES, default=detected_cap): selector.SelectSelector(
                selector.SelectSelectorConfig(options=light_capabilities, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            # v3.2.2.5: Night lights (subset of CONF_LIGHTS) — detail fields in sub-step
            vol.Optional(CONF_NIGHT_LIGHTS, default=[]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["light", "switch"], multiple=True)
            ),
            vol.Optional(CONF_FANS, default=area_fans or []): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="fan", multiple=True)
            ),
            vol.Optional(CONF_HUMIDITY_FANS, default=[]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="fan", multiple=True)
            ),
            vol.Optional(CONF_COVERS, default=area_covers or []): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="cover", multiple=True)
            ),
            vol.Optional(CONF_AUTO_SWITCHES, default=area_switches or []): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch", multiple=True)
            ),
            vol.Optional(CONF_MANUAL_SWITCHES, default=[]): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["switch", "light", "fan"],
                    multiple=True,
                )
            ),
        })

        return self.async_show_form(
            step_id="devices",
            data_schema=data_schema,
            description_placeholders={"name": "Select devices to control"},
        )

    async def async_step_night_light_detail(self, user_input=None):
        """Handle night light detail configuration.

        v3.6.24: Conditional sub-step — only shown when night lights are selected.
        """
        if user_input is not None:
            self._data.update(user_input)
            # Route to cover_behavior if covers selected, else automation_behavior
            if self._data.get(CONF_COVERS):
                return await self.async_step_cover_behavior()
            return await self.async_step_automation_behavior()

        data_schema = vol.Schema({
            vol.Optional(CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS, default=DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=100, mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="%")
            ),
            vol.Optional(CONF_NIGHT_LIGHT_SLEEP_COLOR, default=DEFAULT_NIGHT_LIGHT_SLEEP_COLOR): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1000, max=6500, mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="K")
            ),
            vol.Optional(CONF_NIGHT_LIGHT_DAY_BRIGHTNESS, default=DEFAULT_NIGHT_LIGHT_DAY_BRIGHTNESS): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=100, mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="%")
            ),
            vol.Optional(CONF_NIGHT_LIGHT_DAY_COLOR, default=DEFAULT_NIGHT_LIGHT_DAY_COLOR): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1000, max=6500, mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="K")
            ),
        })

        return self.async_show_form(
            step_id="night_light_detail",
            data_schema=data_schema,
            description_placeholders={"name": "Configure night light brightness and color"},
        )

    async def async_step_cover_behavior(self, user_input=None):
        """Handle cover automation behavior configuration.

        v3.6.24: Conditional sub-step — only shown when covers are selected.
        Cover fields extracted from automation_behavior for streamlined flow.
        """
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_automation_behavior()

        cover_types = [
            {"label": "Shades/Roller Blinds (Open/Close)", "value": COVER_TYPE_SHADE},
            {"label": "Venetian Blinds (Tilt)", "value": COVER_TYPE_TILT},
        ]

        # v3.6.39: New 5-mode cover open system
        cover_open_modes = [
            {"label": "None (Manual Only)", "value": COVER_OPEN_NONE},
            {"label": "On Entry (Any Time)", "value": COVER_OPEN_ON_ENTRY},
            {"label": "At Time (Scheduled)", "value": COVER_OPEN_AT_TIME},
            {"label": "On Entry After Time", "value": COVER_OPEN_ON_ENTRY_AFTER_TIME},
            {"label": "At Time or On Entry", "value": COVER_OPEN_AT_TIME_OR_ON_ENTRY},
        ]

        open_time_sources = [
            {"label": "Sunrise", "value": TIME_SOURCE_SUNRISE},
            {"label": "Specific Hour", "value": TIME_SOURCE_SPECIFIC_HOUR},
        ]

        cover_exit_actions = [
            {"label": "None (Leave As-Is)", "value": COVER_ACTION_NONE},
            {"label": "Always", "value": COVER_ACTION_ALWAYS},
            {"label": "After Sunset Only", "value": COVER_ACTION_AFTER_SUNSET},
        ]

        close_time_sources = [
            {"label": "Sunset", "value": TIME_SOURCE_SUNSET},
            {"label": "Specific Hour", "value": TIME_SOURCE_SPECIFIC_HOUR},
        ]

        data_schema = vol.Schema({
            vol.Optional(CONF_COVER_TYPE, default=COVER_TYPE_SHADE): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cover_types, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            # --- Open ---
            vol.Optional(CONF_COVER_OPEN_MODE, default=COVER_OPEN_NONE): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cover_open_modes, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_COVER_OPEN_TIME_SOURCE, default=TIME_SOURCE_SUNRISE): selector.SelectSelector(
                selector.SelectSelectorConfig(options=open_time_sources, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_COVER_OPEN_HOUR, default=DEFAULT_COVER_OPEN_HOUR): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=23, mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Optional(CONF_SUNRISE_OFFSET, default=DEFAULT_SUNRISE_OFFSET): selector.NumberSelector(
                selector.NumberSelectorConfig(min=-60, max=120, step=15, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)
            ),
            # --- Close ---
            vol.Optional(CONF_EXIT_COVER_ACTION, default=COVER_ACTION_NONE): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cover_exit_actions, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_TIMED_CLOSE_ENABLED, default=False): selector.BooleanSelector(),
            vol.Optional(CONF_COVER_CLOSE_TIME_SOURCE, default=TIME_SOURCE_SUNSET): selector.SelectSelector(
                selector.SelectSelectorConfig(options=close_time_sources, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_COVER_CLOSE_HOUR, default=DEFAULT_COVER_CLOSE_HOUR): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=23, mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Optional(CONF_SUNSET_OFFSET, default=DEFAULT_SUNSET_OFFSET): selector.NumberSelector(
                selector.NumberSelectorConfig(min=-60, max=120, step=15, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)
            ),
        })

        return self.async_show_form(
            step_id="cover_behavior",
            data_schema=data_schema,
            description_placeholders={"name": "Configure cover automation behavior"},
        )

    async def async_step_automation_behavior(self, user_input=None):
        """Handle automation behavior configuration.

        v3.6.24: Cover fields moved to cover_behavior sub-step.
        This step now only contains lighting automation fields.
        """
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_climate()

        light_entry_actions = [
            {"label": "None (Manual Control)", "value": LIGHT_ACTION_NONE},
            {"label": "Turn On Always", "value": LIGHT_ACTION_TURN_ON},
            {"label": "Smart (Only When Dark)", "value": LIGHT_ACTION_TURN_ON_IF_DARK},
        ]

        light_exit_actions = [
            {"label": "Turn Off", "value": LIGHT_ACTION_TURN_OFF},
            {"label": "Leave On", "value": LIGHT_ACTION_LEAVE_ON},
        ]

        data_schema = vol.Schema({
            vol.Optional(CONF_ENTRY_LIGHT_ACTION, default=LIGHT_ACTION_NONE): selector.SelectSelector(
                selector.SelectSelectorConfig(options=light_entry_actions, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_EXIT_LIGHT_ACTION, default=LIGHT_ACTION_TURN_OFF): selector.SelectSelector(
                selector.SelectSelectorConfig(options=light_exit_actions, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_ILLUMINANCE_THRESHOLD, default=DEFAULT_DARK_THRESHOLD): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=100, unit_of_measurement="lx", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_LIGHT_BRIGHTNESS_PCT, default=DEFAULT_LIGHT_BRIGHTNESS): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=100, unit_of_measurement="%", mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Optional(CONF_LIGHT_TRANSITION_ON, default=DEFAULT_LIGHT_TRANSITION_ON): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=10, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_LIGHT_TRANSITION_OFF, default=DEFAULT_LIGHT_TRANSITION_OFF): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=10, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
        })

        return self.async_show_form(
            step_id="automation_behavior",
            data_schema=data_schema,
            description_placeholders={"name": "Configure lighting automation behavior"},
        )

    async def async_step_climate(self, user_input=None):
        """Handle climate and HVAC configuration.

        v3.6.24: Fan speed fields moved to conditional fan_speeds sub-step.
        Area pre-population for climate entity added.
        """
        if user_input is not None:
            self._data.update(user_input)
            # v3.6.24: Conditional routing — fan speeds if fan control enabled
            if user_input.get(CONF_FAN_CONTROL_ENABLED):
                return await self.async_step_fan_speeds()
            return await self.async_step_sleep_protection()

        # v3.6.24: Area pre-population for climate entity
        area_id = self._data.get(CONF_AREA_ID)
        area_climate = self._get_area_entities(area_id, "climate") if area_id else []

        data_schema = vol.Schema({
            vol.Optional(CONF_CLIMATE_ENTITY, default=area_climate[0] if area_climate else vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Optional(CONF_HVAC_COORDINATION_ENABLED, default=False): selector.BooleanSelector(),
            vol.Optional(CONF_TARGET_TEMP_COOL, default=DEFAULT_TARGET_TEMP_COOL): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=90, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_TARGET_TEMP_HEAT, default=DEFAULT_TARGET_TEMP_HEAT): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=90, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_FAN_CONTROL_ENABLED, default=False): selector.BooleanSelector(),
            vol.Optional(CONF_FAN_TEMP_THRESHOLD, default=DEFAULT_FAN_TEMP_THRESHOLD): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=100, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_HUMIDITY_FAN_THRESHOLD, default=DEFAULT_HUMIDITY_THRESHOLD): selector.NumberSelector(
                selector.NumberSelectorConfig(min=30, max=80, unit_of_measurement="%", mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Optional(CONF_HUMIDITY_FAN_TIMEOUT, default=DEFAULT_HUMIDITY_FAN_TIMEOUT): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=3600, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_HVAC_EFFICIENCY_ALERTS, default=False): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="climate",
            data_schema=data_schema,
            description_placeholders={"name": "Configure climate and HVAC"},
        )

    async def async_step_fan_speeds(self, user_input=None):
        """Handle fan speed threshold configuration.

        v3.6.24: Conditional sub-step — only shown when fan control is enabled.
        """
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_sleep_protection()

        data_schema = vol.Schema({
            vol.Optional(CONF_FAN_SPEED_LOW_TEMP, default=DEFAULT_FAN_SPEED_LOW): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=100, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_FAN_SPEED_MED_TEMP, default=DEFAULT_FAN_SPEED_MED): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=100, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_FAN_SPEED_HIGH_TEMP, default=DEFAULT_FAN_SPEED_HIGH): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=100, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
        })

        return self.async_show_form(
            step_id="fan_speeds",
            data_schema=data_schema,
            description_placeholders={"name": "Configure fan speed temperature thresholds"},
        )

    async def async_step_sleep_protection(self, user_input=None):
        """Handle sleep protection configuration."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_energy()

        data_schema = vol.Schema({
            vol.Optional(CONF_SLEEP_PROTECTION_ENABLED, default=False): selector.BooleanSelector(),
            vol.Optional(CONF_SLEEP_START_HOUR, default=DEFAULT_SLEEP_START): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=23, mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Optional(CONF_SLEEP_END_HOUR, default=DEFAULT_SLEEP_END): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=23, mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Optional(CONF_SLEEP_BYPASS_MOTION, default=DEFAULT_SLEEP_BYPASS_COUNT): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=10, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_SLEEP_BLOCK_COVERS, default=True): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="sleep_protection",
            data_schema=data_schema,
            description_placeholders={"name": "Configure sleep protection. Submit unchanged to use defaults."},
        )

    async def async_step_energy(self, user_input=None):
        """Handle energy monitoring configuration."""
        errors = {}
        
        if user_input is not None:
            try:
                _LOGGER.debug("Energy config input: %s", user_input)
                
                # Handle power sensors list - ensure it's actually a list
                if CONF_POWER_SENSORS in user_input:
                    power_sensors = user_input[CONF_POWER_SENSORS]
                    if power_sensors and not isinstance(power_sensors, list):
                        power_sensors = [power_sensors]
                    user_input[CONF_POWER_SENSORS] = power_sensors if power_sensors else []
                
                # Clean up None/empty values
                cleaned_input = {}
                for key, value in user_input.items():
                    if value is not None and value != "":
                        cleaned_input[key] = value
                
                _LOGGER.debug("Cleaned energy input: %s", cleaned_input)
                
                self._data.update(cleaned_input)
                return await self.async_step_notifications()
                
            except Exception as err:
                _LOGGER.error("Error in energy config: %s", err, exc_info=True)
                errors["base"] = "unknown"

        # v3.6.24: Area pre-population for power/energy sensors
        area_id = self._data.get(CONF_AREA_ID)
        area_power = self._get_area_entities(area_id, "sensor", "power") if area_id else []
        area_energy = self._get_area_entities(area_id, "sensor", "energy") if area_id else []

        data_schema = vol.Schema({
            vol.Optional(CONF_POWER_SENSORS, default=area_power or vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
            ),
            vol.Optional(CONF_ENERGY_SENSOR, default=area_energy[0] if area_energy else vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
            vol.Optional(CONF_ELECTRICITY_RATE, default=DEFAULT_ELECTRICITY_RATE): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.01, max=1.00, step=0.01, unit_of_measurement="USD/kWh", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_NOTIFY_DAILY_ENERGY, default=False): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="energy",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"name": "Configure energy monitoring (optional). Submit unchanged to skip."},
        )

    async def async_step_notifications(self, user_input=None):
        """Handle notification configuration and create entries."""
        if user_input is not None:
            self._data.update(user_input)
            
            # If creating first room (integration_data exists), create integration entry first
            if self._integration_data is not None:
                # Create integration entry
                integration_result = await self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": "integration_create"},
                    data={
                        CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
                        **self._integration_data
                    }
                )
                # The integration entry gets created; we need to find its ID
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                        self._integration_entry_id = entry.entry_id
                        break
            
            # Create room entry linked to integration
            room_data = {
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_INTEGRATION_ENTRY_ID: self._integration_entry_id,
                **self._data
            }
            
            return self.async_create_entry(
                title=self._data[CONF_ROOM_NAME],
                data=room_data,
            )

        # Get available notify services
        notify_services = []
        if "notify" in self.hass.services.async_services():
            for service_name in self.hass.services.async_services()["notify"].keys():
                notify_services.append({
                    "label": f"notify.{service_name}",
                    "value": f"notify.{service_name}"
                })
        
        # If no services found, add helpful message
        if not notify_services:
            notify_services.append({
                "label": "No notify services configured",
                "value": ""
            })

        # Get mobile_app device targets from notify services
        notify_targets = [{"label": "None", "value": ""}]
        for service in notify_services:
            service_name = service["value"].replace("notify.", "")
            if service_name.startswith("mobile_app_"):
                device_name = service_name.replace("mobile_app_", "").replace("_", " ").title()
                notify_targets.append({
                    "label": device_name,
                    "value": service_name
                })
        # If no mobile_app services, at least show the service names
        if len(notify_targets) == 1:
            for service in notify_services:
                if service["value"]:
                    notify_targets.append({
                        "label": service["label"],
                        "value": service["value"].replace("notify.", "")
                    })

        notify_levels = [
            {"label": "Off", "value": NOTIFY_LEVEL_OFF},
            {"label": "Errors Only", "value": NOTIFY_LEVEL_ERRORS},
            {"label": "Important Events", "value": NOTIFY_LEVEL_IMPORTANT},
            {"label": "All Events", "value": NOTIFY_LEVEL_ALL},
        ]
        
        # v3.1.0: Alert light color presets
        alert_colors = [
            {"label": "Amber (Warning)", "value": ALERT_COLOR_AMBER},
            {"label": "Red (Critical)", "value": ALERT_COLOR_RED},
            {"label": "Blue (Info)", "value": ALERT_COLOR_BLUE},
            {"label": "Green (OK)", "value": ALERT_COLOR_GREEN},
            {"label": "White (Neutral)", "value": ALERT_COLOR_WHITE},
        ]

        data_schema = vol.Schema({
            vol.Optional(CONF_OVERRIDE_NOTIFICATIONS, default=False): selector.BooleanSelector(),
            vol.Optional(CONF_NOTIFY_SERVICE): selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify_services, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_NOTIFY_TARGET): selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify_targets, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_NOTIFY_LEVEL, default=NOTIFY_LEVEL_ERRORS): selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify_levels, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            # v3.1.0: Alert lights
            vol.Optional(CONF_ALERT_LIGHTS, default=[]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light", multiple=True)
            ),
            vol.Optional(CONF_ALERT_LIGHT_COLOR, default=ALERT_COLOR_AMBER): selector.SelectSelector(
                selector.SelectSelectorConfig(options=alert_colors, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
        })

        return self.async_show_form(
            step_id="notifications",
            data_schema=data_schema,
            description_placeholders={
                "name": "Configure notifications. Submit unchanged to use integration defaults."
            },
        )

    async def async_step_integration_create(self, user_input=None):
        """Handle internal integration entry creation."""
        if user_input is not None:
            return self.async_create_entry(
                title="Universal Room Automation",
                data=user_input,
            )
        return self.async_abort(reason="not_supported")

    async def async_step_migration(self, user_input=None):
        """Handle migration-triggered integration entry creation."""
        if user_input is not None:
            return self.async_create_entry(
                title="Universal Room Automation",
                data=user_input,
            )
        return self.async_abort(reason="migration_failed")

    async def async_step_zone_migration(self, user_input=None):
        """Handle zone migration - auto-create zone entries from zone names (v3.3.5.3)."""
        if user_input is not None:
            zone_name = user_input.get(CONF_ZONE_NAME, "Unknown Zone")
            return self.async_create_entry(
                title=f"📍 {zone_name}",
                data=user_input,
            )
        return self.async_abort(reason="migration_failed")

    async def async_step_zone_manager_migration(self, user_input=None):
        """Handle Zone Manager entry creation during migration (v3.6.0)."""
        if user_input is not None:
            return self.async_create_entry(
                title="URA: Zone Manager",
                data=user_input,
            )
        return self.async_abort(reason="migration_failed")

    async def async_step_coordinator_manager_migration(self, user_input=None):
        """Handle Coordinator Manager entry creation during migration (v3.6.0)."""
        if user_input is not None:
            return self.async_create_entry(
                title="URA: Coordinator Manager",
                data=user_input,
            )
        return self.async_abort(reason="migration_failed")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return UniversalRoomAutomationOptionsFlow(config_entry)


class UniversalRoomAutomationOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Universal Room Automation v3.3.3."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self._selected_zone_entry_id = None  # v3.3.3: Track zone selected from integration menu

    def _get_current(self, key, default=None):
        """Get current value from options with data fallback."""
        return self._config_entry.options.get(
            key, self._config_entry.data.get(key, default)
        )
    
    def _get_zone_entry(self):
        """Get the zone entry being configured (v3.3.3).

        Returns the selected zone entry if called from integration menu,
        or the current config entry if it's a zone entry itself.
        """
        if self._selected_zone_entry_id:
            return self.hass.config_entries.async_get_entry(self._selected_zone_entry_id)
        if self._config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
            return self._config_entry
        return None

    def _get_zm_zone_data(self) -> tuple | None:
        """Get zone data from Zone Manager entry by _selected_zone_name.

        v3.6.0-c2.3: Zones migrated from separate entries to ZM entry's zones dict.
        Returns (zm_entry, zone_name, zone_data) or None.
        """
        zone_name = getattr(self, "_selected_zone_name", None)
        if not zone_name:
            return None

        # Find ZM entry
        zm_entry = None
        if self._config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
            zm_entry = self._config_entry
        else:
            for ce in self.hass.config_entries.async_entries(DOMAIN):
                if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
                    zm_entry = ce
                    break
        if not zm_entry:
            return None

        merged = {**zm_entry.data, **zm_entry.options}
        zones = merged.get("zones", {})
        zone_data = zones.get(zone_name, {})
        return (zm_entry, zone_name, zone_data)

    async def async_step_init(self, user_input=None):
        """Show appropriate menu based on entry type."""
        entry_type = self._config_entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM)

        if entry_type == ENTRY_TYPE_INTEGRATION:
            # Integration options menu
            return self.async_show_menu(
                step_id="init",
                menu_options=[
                    "global_sensors",
                    "energy_sensors",
                    "person_tracking",  # v3.2.0
                    "default_notifications",
                    "camera_census",  # v3.5.0
                    "perimeter_alerting",  # v3.5.1
                    # v3.6.0-c2.4: domain_coordinators toggle moved to switch entity
                ],
            )
        elif entry_type == ENTRY_TYPE_ZONE_MANAGER:
            # v3.6.0: Zone Manager options menu
            return self.async_show_menu(
                step_id="init",
                menu_options=[
                    "manage_zones",
                ],
            )
        elif entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:
            # v3.6.0-c2.1: Coordinator Manager options menu
            # v3.6.0-c2.4: coordinator_toggles moved to switch entities
            return self.async_show_menu(
                step_id="init",
                menu_options=[
                    "coordinator_presence",
                    "coordinator_safety",
                    "coordinator_security",
                    "coordinator_energy",
                    "coordinator_hvac",
                    "coordinator_music_following",
                    "coordinator_notifications",
                ],
            )
        elif entry_type == ENTRY_TYPE_ZONE:
            # Legacy zone options menu (should be migrated)
            return self.async_show_menu(
                step_id="init",
                menu_options=[
                    "zone_rooms",
                    "zone_media",  # v3.3.1
                ],
            )
        else:
            # Room options menu
            return self.async_show_menu(
                step_id="init",
                menu_options=[
                    "basic_setup",
                    "sensors",
                    "devices",
                    "automation_behavior",
                    "climate",
                    "sleep_protection",
                    "music_following",  # v3.3.1
                    "energy",
                    "notifications",
                ],
            )

    # =========================================================================
    # INTEGRATION OPTIONS (for integration entry)
    # =========================================================================

    async def async_step_global_sensors(self, user_input=None):
        """Reconfigure global sensors (integration level)."""
        if user_input is not None:
            # FIX v3.2.3.1: Pass merged options directly to async_create_entry
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input}
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_OUTSIDE_TEMP_SENSOR,
                default=self._get_current(CONF_OUTSIDE_TEMP_SENSOR) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional(
                CONF_OUTSIDE_HUMIDITY_SENSOR,
                default=self._get_current(CONF_OUTSIDE_HUMIDITY_SENSOR) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
            ),
            vol.Optional(
                CONF_WEATHER_ENTITY,
                default=self._get_current(CONF_WEATHER_ENTITY) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            vol.Optional(
                CONF_SOLAR_PRODUCTION_SENSOR,
                default=self._get_current(CONF_SOLAR_PRODUCTION_SENSOR) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Required(
                CONF_ELECTRICITY_RATE,
                default=self._get_current(CONF_ELECTRICITY_RATE, DEFAULT_ELECTRICITY_RATE)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.01, max=1.00, step=0.01,
                    unit_of_measurement="USD/kWh",
                    mode=selector.NumberSelectorMode.BOX
                )
            ),
        })

        return self.async_show_form(
            step_id="global_sensors",
            data_schema=data_schema,
        )

    async def async_step_energy_sensors(self, user_input=None):
        """Reconfigure energy sensors for predictions and tracking (integration level)."""
        if user_input is not None:
            # FIX v3.2.3.1: Pass merged options directly to async_create_entry
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input}
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_SOLAR_EXPORT_SENSOR,
                default=self._get_current(CONF_SOLAR_EXPORT_SENSOR) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
            vol.Optional(
                CONF_GRID_IMPORT_SENSOR,
                default=self._get_current(CONF_GRID_IMPORT_SENSOR) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
            vol.Optional(
                CONF_GRID_IMPORT_SENSOR_2,
                default=self._get_current(CONF_GRID_IMPORT_SENSOR_2) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
            vol.Optional(
                CONF_BATTERY_LEVEL_SENSOR,
                default=self._get_current(CONF_BATTERY_LEVEL_SENSOR) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="battery")
            ),
            vol.Optional(
                CONF_WHOLE_HOUSE_POWER_SENSOR,
                default=self._get_current(CONF_WHOLE_HOUSE_POWER_SENSOR) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Optional(
                CONF_WHOLE_HOUSE_ENERGY_SENSOR,
                default=self._get_current(CONF_WHOLE_HOUSE_ENERGY_SENSOR) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
            vol.Optional(
                CONF_DELIVERY_RATE,
                default=self._get_current(CONF_DELIVERY_RATE, DEFAULT_DELIVERY_RATE)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.00, max=0.50, step=0.01,
                    unit_of_measurement="USD/kWh",
                    mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_EXPORT_REIMBURSEMENT_RATE,
                default=self._get_current(CONF_EXPORT_REIMBURSEMENT_RATE, DEFAULT_EXPORT_REIMBURSEMENT_RATE)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.00, max=0.50, step=0.01,
                    unit_of_measurement="USD/kWh",
                    mode=selector.NumberSelectorMode.BOX
                )
            ),
        })

        return self.async_show_form(
            step_id="energy_sensors",
            data_schema=data_schema,
        )
    
    def _get_mobile_app_targets(self) -> list[dict]:
        """Get mobile_app notification targets as dropdown options."""
        targets = [{"label": "None", "value": ""}]
        
        if "notify" in self.hass.services.async_services():
            for service_name in self.hass.services.async_services()["notify"].keys():
                if service_name.startswith("mobile_app_"):
                    device_name = service_name.replace("mobile_app_", "").replace("_", " ").title()
                    targets.append({
                        "label": device_name,
                        "value": f"notify.{service_name}"
                    })
        
        if len(targets) == 1:
            targets.append({"label": "No mobile apps found", "value": ""})
        
        return targets
    
    def _get_all_room_entries(self) -> list:
        """Get all room config entries."""
        return [
            entry for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM
        ]
    
    def _get_existing_zones(self) -> set[str]:
        """Get existing zones from Zone config entries (v3.3.5.3).
        
        Changed from reading zone names from room entries to reading
        from actual Zone config entries.
        """
        zones = set()
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
                zone_name = entry.data.get(CONF_ZONE_NAME)
                if zone_name:
                    zones.add(zone_name)
        return zones

    async def async_step_person_tracking(self, user_input=None):
        """Configure person tracking (integration level) - v3.2.0."""
        if user_input is not None:
            # FIX v3.2.3.1: Pass merged options directly to async_create_entry
            # Previously used async_update_entry + async_create_entry(data={}) which CLEARED options!
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input}
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_TRACKED_PERSONS,
                default=self._get_current(CONF_TRACKED_PERSONS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="person",
                    multiple=True
                )
            ),
            vol.Optional(
                CONF_PERSON_DATA_RETENTION,
                default=self._get_current(CONF_PERSON_DATA_RETENTION, DEFAULT_PERSON_DATA_RETENTION)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=365,
                    step=1,
                    unit_of_measurement="days",
                    mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_TRANSITION_DETECTION_WINDOW,
                default=self._get_current(CONF_TRANSITION_DETECTION_WINDOW, DEFAULT_TRANSITION_WINDOW)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=30,
                    max=300,
                    step=10,
                    unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.SLIDER
                )
            ),
        })

        return self.async_show_form(
            step_id="person_tracking",
            data_schema=data_schema,
            description_placeholders={
                "retention_info": "Set to 0 for infinite retention. Recommended: 90 days.",
                "window_info": "Time window to detect room transitions (default: 120 seconds)."
            }
        )

    async def async_step_camera_census(self, user_input=None):
        """Configure camera census (integration level) - v3.5.0.

        Allows selection of indoor, egress, and perimeter camera entities for
        the person census engine.

        Indoor cameras are mapped to rooms automatically using the camera
        entity's area assignment in the HA entity registry. Egress cameras
        cover exterior doors; perimeter cameras cover the yard/property.

        Migration: when loading defaults, any CONF_CAMERA_PERSON_ENTITIES
        previously stored on room config entries (v3.4.0–3.4.4) are merged
        into the integration-level default so existing configs are preserved.
        """
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input}
            )

        # Build default for indoor cameras: start from integration-level value,
        # then merge in any cameras still stored on room entries (migration path).
        interior_default = list(self._get_current(CONF_CAMERA_PERSON_ENTITIES, []))
        existing_ids = set(interior_default)
        for config_entry in self.hass.config_entries.async_entries(DOMAIN):
            if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                merged = {**config_entry.data, **config_entry.options}
                room_cameras = merged.get(CONF_CAMERA_PERSON_ENTITIES, [])
                for cam in room_cameras:
                    if cam not in existing_ids:
                        interior_default.append(cam)
                        existing_ids.add(cam)

        data_schema = vol.Schema({
            # Cross-validation toggle
            vol.Optional(
                CONF_CENSUS_CROSS_VALIDATION,
                default=self._get_current(CONF_CENSUS_CROSS_VALIDATION, True)
            ): selector.BooleanSelector(),
            # Indoor cameras: inside the house (mapped to rooms via area_id)
            vol.Optional(
                CONF_CAMERA_PERSON_ENTITIES,
                default=interior_default
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="camera",
                    multiple=True,
                )
            ),
            # Egress cameras: doors to outside (front door, back door, garage)
            vol.Optional(
                CONF_EGRESS_CAMERAS,
                default=self._get_current(CONF_EGRESS_CAMERAS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="camera",
                    multiple=True,
                )
            ),
            # Perimeter cameras: yard, driveway, fence line
            vol.Optional(
                CONF_PERIMETER_CAMERAS,
                default=self._get_current(CONF_PERIMETER_CAMERAS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="camera",
                    multiple=True,
                )
            ),
            # v3.5.2: Face recognition toggle (default False)
            vol.Optional(
                CONF_FACE_RECOGNITION_ENABLED,
                default=self._get_current(CONF_FACE_RECOGNITION_ENABLED, False),
            ): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="camera_census",
            data_schema=data_schema,
        )

    async def async_step_perimeter_alerting(self, user_input=None):
        """Configure perimeter intruder alerting (integration level) — v3.5.1.

        Sets alert hours, notification service, and notification target for
        the PerimeterAlertManager. Changes take effect after integration reload.
        """
        if user_input is not None:
            # v3.6.0-c2.1: Pass merged options through async_create_entry data.
            # Previously called async_update_entry then async_create_entry(data={})
            # which wiped options to {} on flow completion.
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input},
            )

        data_schema = vol.Schema({
            # Alert start hour (0–23)
            vol.Optional(
                CONF_PERIMETER_ALERT_HOURS_START,
                default=self._get_current(
                    CONF_PERIMETER_ALERT_HOURS_START,
                    DEFAULT_PERIMETER_ALERT_START,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=23,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            # Alert end hour (0–23)
            vol.Optional(
                CONF_PERIMETER_ALERT_HOURS_END,
                default=self._get_current(
                    CONF_PERIMETER_ALERT_HOURS_END,
                    DEFAULT_PERIMETER_ALERT_END,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=23,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            # Notify service
            vol.Optional(
                CONF_PERIMETER_ALERT_NOTIFY_SERVICE,
                default=self._get_current(CONF_PERIMETER_ALERT_NOTIFY_SERVICE, ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            # Notify target (optional)
            vol.Optional(
                CONF_PERIMETER_ALERT_NOTIFY_TARGET,
                default=self._get_current(CONF_PERIMETER_ALERT_NOTIFY_TARGET, ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
        })

        return self.async_show_form(
            step_id="perimeter_alerting",
            data_schema=data_schema,
        )

    async def async_step_domain_coordinators(self, user_input=None):
        """Configure domain coordinators toggle (integration level) — v3.6.0.

        Enables/disables the domain coordinator system. When enabled, the
        Coordinator Manager starts on next reload and a coordinator selector
        menu becomes available in future cycles.
        """
        from .const import CONF_DOMAIN_COORDINATORS_ENABLED

        if user_input is not None:
            # v3.6.0-c2.1: Pass merged options through async_create_entry data.
            # Previously called async_update_entry then async_create_entry(data={})
            # which wiped options to {} — domain_coordinators_enabled was never persisted.
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input},
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_DOMAIN_COORDINATORS_ENABLED,
                default=self._get_current(CONF_DOMAIN_COORDINATORS_ENABLED, False),
            ): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="domain_coordinators",
            data_schema=data_schema,
        )

    # =========================================================================
    # COORDINATOR MANAGER OPTIONS (for coordinator manager entry)
    # =========================================================================

    async def async_step_coordinator_presence(self, user_input=None):
        """Configure Presence Coordinator settings.

        v3.6.0-c2.1: Sleep hours and geofence entity selection.
        Settings stored in CM entry options, read by __init__.py during
        coordinator setup.
        """
        from .const import (
            CONF_SLEEP_START_HOUR,
            CONF_SLEEP_END_HOUR,
            CONF_GEOFENCE_ENTITIES,
            DEFAULT_SLEEP_START_HOUR,
            DEFAULT_SLEEP_END_HOUR,
        )

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input},
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_SLEEP_START_HOUR,
                default=self._get_current(
                    CONF_SLEEP_START_HOUR, DEFAULT_SLEEP_START_HOUR
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=23, step=1, mode="slider"
                )
            ),
            vol.Optional(
                CONF_SLEEP_END_HOUR,
                default=self._get_current(
                    CONF_SLEEP_END_HOUR, DEFAULT_SLEEP_END_HOUR
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=23, step=1, mode="slider"
                )
            ),
            vol.Optional(
                CONF_GEOFENCE_ENTITIES,
                default=self._get_current(CONF_GEOFENCE_ENTITIES, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="device_tracker", multiple=True
                )
            ),
        })

        return self.async_show_form(
            step_id="coordinator_presence",
            data_schema=data_schema,
        )

    async def async_step_coordinator_safety(self, user_input=None):
        """Configure Safety Coordinator settings.

        v3.6.0-c2.1: Water shutoff valve and emergency light entities.
        v3.6.0.3: Global safety device selectors for scoped discovery.
        """
        from .const import (
            CONF_WATER_SHUTOFF_VALVE,
            CONF_EMERGENCY_LIGHT_ENTITIES,
            CONF_GLOBAL_SMOKE_SENSORS,
            CONF_GLOBAL_LEAK_SENSORS,
            CONF_GLOBAL_AQ_SENSORS,
            CONF_GLOBAL_TEMP_SENSORS,
            CONF_GLOBAL_HUMIDITY_SENSORS,
        )

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input},
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_WATER_SHUTOFF_VALVE,
                description={"suggested_value": self._get_current(
                    CONF_WATER_SHUTOFF_VALVE
                )},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="valve")
            ),
            vol.Optional(
                CONF_EMERGENCY_LIGHT_ENTITIES,
                default=self._get_current(CONF_EMERGENCY_LIGHT_ENTITIES, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="light", multiple=True
                )
            ),
            # v3.6.0.3: Global safety device selectors
            vol.Optional(
                CONF_GLOBAL_SMOKE_SENSORS,
                default=self._get_current(CONF_GLOBAL_SMOKE_SENSORS, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="binary_sensor",
                    device_class=["smoke", "gas"],
                    multiple=True,
                )
            ),
            vol.Optional(
                CONF_GLOBAL_LEAK_SENSORS,
                default=self._get_current(CONF_GLOBAL_LEAK_SENSORS, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="binary_sensor",
                    device_class=["moisture"],
                    multiple=True,
                )
            ),
            vol.Optional(
                CONF_GLOBAL_AQ_SENSORS,
                default=self._get_current(CONF_GLOBAL_AQ_SENSORS, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class=["carbon_monoxide", "carbon_dioxide", "volatile_organic_compounds"],
                    multiple=True,
                )
            ),
            vol.Optional(
                CONF_GLOBAL_TEMP_SENSORS,
                default=self._get_current(CONF_GLOBAL_TEMP_SENSORS, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class=["temperature"],
                    multiple=True,
                )
            ),
            vol.Optional(
                CONF_GLOBAL_HUMIDITY_SENSORS,
                default=self._get_current(CONF_GLOBAL_HUMIDITY_SENSORS, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class=["humidity"],
                    multiple=True,
                )
            ),
        })

        return self.async_show_form(
            step_id="coordinator_safety",
            data_schema=data_schema,
        )

    async def async_step_coordinator_energy(self, user_input=None):
        """Configure Energy Coordinator settings.

        v3.7.0: Reserve SOC, bill cycle day, decision interval.
        v3.7.10: Entity selectors, solar classification mode.
        """
        from .domain_coordinators.energy_const import (
            CONF_ENERGY_RESERVE_SOC,
            CONF_ENERGY_BILL_CYCLE_DAY,
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
            DEFAULT_BILL_CYCLE_START_DAY,
            DEFAULT_DECISION_INTERVAL_MINUTES,
            SOLAR_CLASS_MODE_AUTOMATIC,
            SOLAR_CLASS_MODE_CUSTOM,
            CONF_ENERGY_LOAD_SHEDDING_ENABLED,
            CONF_ENERGY_LOAD_SHEDDING_THRESHOLD,
            CONF_ENERGY_LOAD_SHEDDING_SUSTAINED_MINUTES,
            CONF_ENERGY_LOAD_SHEDDING_MODE,
            CONF_ENERGY_CONSTRAINT_COAST_OFFSET,
            CONF_ENERGY_CONSTRAINT_PRECOOL_OFFSET,
            CONF_ENERGY_CONSTRAINT_PREHEAT_OFFSET,
            CONF_ENERGY_CONSTRAINT_SHED_OFFSET,
            CONF_ENERGY_PREHEAT_TEMP_THRESHOLD,
            DEFAULT_LOAD_SHEDDING_THRESHOLD_KW,
            DEFAULT_LOAD_SHEDDING_SUSTAINED_MINUTES,
            LOAD_SHEDDING_MODE_FIXED,
            LOAD_SHEDDING_MODE_AUTO,
            DEFAULT_CONSTRAINT_COAST_OFFSET,
            DEFAULT_CONSTRAINT_PRECOOL_OFFSET,
            DEFAULT_CONSTRAINT_PREHEAT_OFFSET,
            DEFAULT_CONSTRAINT_SHED_OFFSET,
            DEFAULT_PREHEAT_TEMP_THRESHOLD,
        )

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input},
            )

        # Weather entity default: inherit from house/integration entry if set
        weather_default = self._get_current(CONF_ENERGY_WEATHER_ENTITY)
        if not weather_default:
            integration = self.hass.data.get(DOMAIN, {}).get("integration")
            if integration:
                weather_default = (
                    integration.options.get(CONF_WEATHER_ENTITY)
                    or integration.data.get(CONF_WEATHER_ENTITY)
                )

        solar_mode = self._get_current(
            CONF_ENERGY_SOLAR_CLASSIFICATION_MODE, SOLAR_CLASS_MODE_AUTOMATIC
        )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_ENERGY_RESERVE_SOC,
                default=self._get_current(CONF_ENERGY_RESERVE_SOC, DEFAULT_RESERVE_SOC),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5, max=100, step=5,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_ENERGY_BILL_CYCLE_DAY,
                default=self._get_current(CONF_ENERGY_BILL_CYCLE_DAY, DEFAULT_BILL_CYCLE_START_DAY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=28, step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_ENERGY_DECISION_INTERVAL,
                default=self._get_current(CONF_ENERGY_DECISION_INTERVAL, DEFAULT_DECISION_INTERVAL_MINUTES),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=30, step=1,
                    unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_ENERGY_WEATHER_ENTITY,
                description={"suggested_value": weather_default},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            vol.Optional(
                CONF_ENERGY_EVSE_A_ENTITY,
                description={"suggested_value": self._get_current(CONF_ENERGY_EVSE_A_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Optional(
                CONF_ENERGY_EVSE_B_ENTITY,
                description={"suggested_value": self._get_current(CONF_ENERGY_EVSE_B_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Optional(
                CONF_ENERGY_L1_CHARGER_ENTITIES,
                default=self._get_current(CONF_ENERGY_L1_CHARGER_ENTITIES, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch", multiple=True)
            ),
            vol.Optional(
                CONF_ENERGY_SOLAR_CLASSIFICATION_MODE,
                default=solar_mode,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SOLAR_CLASS_MODE_AUTOMATIC, SOLAR_CLASS_MODE_CUSTOM],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_ENERGY_SOLAR_THRESHOLD_EXCELLENT,
                default=self._get_current(CONF_ENERGY_SOLAR_THRESHOLD_EXCELLENT, 100.0),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=300, step=1,
                    unit_of_measurement="kWh",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_ENERGY_SOLAR_THRESHOLD_GOOD,
                default=self._get_current(CONF_ENERGY_SOLAR_THRESHOLD_GOOD, 80.0),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=300, step=1,
                    unit_of_measurement="kWh",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_ENERGY_SOLAR_THRESHOLD_MODERATE,
                default=self._get_current(CONF_ENERGY_SOLAR_THRESHOLD_MODERATE, 50.0),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=300, step=1,
                    unit_of_measurement="kWh",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_ENERGY_SOLAR_THRESHOLD_POOR,
                default=self._get_current(CONF_ENERGY_SOLAR_THRESHOLD_POOR, 30.0),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=300, step=1,
                    unit_of_measurement="kWh",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            # v3.9.0: Load shedding config
            vol.Optional(
                CONF_ENERGY_LOAD_SHEDDING_ENABLED,
                default=self._get_current(CONF_ENERGY_LOAD_SHEDDING_ENABLED, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ENERGY_LOAD_SHEDDING_MODE,
                default=self._get_current(CONF_ENERGY_LOAD_SHEDDING_MODE, LOAD_SHEDDING_MODE_FIXED),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[LOAD_SHEDDING_MODE_FIXED, LOAD_SHEDDING_MODE_AUTO],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_ENERGY_LOAD_SHEDDING_THRESHOLD,
                default=self._get_current(CONF_ENERGY_LOAD_SHEDDING_THRESHOLD, DEFAULT_LOAD_SHEDDING_THRESHOLD_KW),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=20, step=0.5,
                    unit_of_measurement="kW",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_ENERGY_LOAD_SHEDDING_SUSTAINED_MINUTES,
                default=self._get_current(CONF_ENERGY_LOAD_SHEDDING_SUSTAINED_MINUTES, DEFAULT_LOAD_SHEDDING_SUSTAINED_MINUTES),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5, max=60, step=5,
                    unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            # v3.9.0: Constraint offset config
            vol.Optional(
                CONF_ENERGY_CONSTRAINT_COAST_OFFSET,
                default=self._get_current(CONF_ENERGY_CONSTRAINT_COAST_OFFSET, DEFAULT_CONSTRAINT_COAST_OFFSET),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=10, step=0.5,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_ENERGY_CONSTRAINT_PRECOOL_OFFSET,
                default=self._get_current(CONF_ENERGY_CONSTRAINT_PRECOOL_OFFSET, DEFAULT_CONSTRAINT_PRECOOL_OFFSET),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-5, max=0, step=0.5,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_ENERGY_CONSTRAINT_PREHEAT_OFFSET,
                default=self._get_current(CONF_ENERGY_CONSTRAINT_PREHEAT_OFFSET, DEFAULT_CONSTRAINT_PREHEAT_OFFSET),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=5, step=0.5,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_ENERGY_CONSTRAINT_SHED_OFFSET,
                default=self._get_current(CONF_ENERGY_CONSTRAINT_SHED_OFFSET, DEFAULT_CONSTRAINT_SHED_OFFSET),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=10, step=0.5,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_ENERGY_PREHEAT_TEMP_THRESHOLD,
                default=self._get_current(CONF_ENERGY_PREHEAT_TEMP_THRESHOLD, DEFAULT_PREHEAT_TEMP_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=20, max=60, step=1,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
        })

        return self.async_show_form(
            step_id="coordinator_energy",
            data_schema=data_schema,
        )

    async def async_step_coordinator_hvac(self, user_input=None):
        """Configure HVAC Coordinator settings.

        v3.8.6: Sleep offset, override compromise, fan tuning, cover entities.
        """
        from .domain_coordinators.hvac_const import (
            CONF_HVAC_MAX_SLEEP_OFFSET,
            CONF_HVAC_COMPROMISE_MINUTES,
            CONF_HVAC_AC_RESET_TIMEOUT,
            CONF_HVAC_FAN_ACTIVATION_DELTA,
            CONF_HVAC_FAN_HYSTERESIS,
            CONF_HVAC_FAN_MIN_RUNTIME,
            CONF_HVAC_COVER_ENTITIES,
            DEFAULT_MAX_SLEEP_OFFSET,
            DEFAULT_COMPROMISE_MINUTES,
            DEFAULT_AC_RESET_TIMEOUT,
            DEFAULT_FAN_ACTIVATION_DELTA,
            DEFAULT_FAN_HYSTERESIS,
            DEFAULT_FAN_MIN_RUNTIME,
            CONF_HVAC_ARRESTER_ENABLED,
            DEFAULT_ARRESTER_ENABLED,
        )

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input},
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_HVAC_MAX_SLEEP_OFFSET,
                default=self._get_current(CONF_HVAC_MAX_SLEEP_OFFSET, DEFAULT_MAX_SLEEP_OFFSET),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=5, step=0.5,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_HVAC_COMPROMISE_MINUTES,
                default=self._get_current(CONF_HVAC_COMPROMISE_MINUTES, DEFAULT_COMPROMISE_MINUTES),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5, max=120, step=5,
                    unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_HVAC_AC_RESET_TIMEOUT,
                default=self._get_current(CONF_HVAC_AC_RESET_TIMEOUT, DEFAULT_AC_RESET_TIMEOUT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5, max=30, step=1,
                    unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_HVAC_FAN_ACTIVATION_DELTA,
                default=self._get_current(CONF_HVAC_FAN_ACTIVATION_DELTA, DEFAULT_FAN_ACTIVATION_DELTA),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5, max=5, step=0.5,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_HVAC_FAN_HYSTERESIS,
                default=self._get_current(CONF_HVAC_FAN_HYSTERESIS, DEFAULT_FAN_HYSTERESIS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5, max=5, step=0.5,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_HVAC_FAN_MIN_RUNTIME,
                default=self._get_current(CONF_HVAC_FAN_MIN_RUNTIME, DEFAULT_FAN_MIN_RUNTIME),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=30, step=1,
                    unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_HVAC_COVER_ENTITIES,
                default=self._get_current(CONF_HVAC_COVER_ENTITIES, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="cover", multiple=True)
            ),
            # v3.9.0: Override arrester config
            vol.Optional(
                CONF_HVAC_ARRESTER_ENABLED,
                default=self._get_current(CONF_HVAC_ARRESTER_ENABLED, DEFAULT_ARRESTER_ENABLED),
            ): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="coordinator_hvac",
            data_schema=data_schema,
        )

    async def async_step_coordinator_security(self, user_input=None):
        """Configure Security Coordinator settings.

        v3.6.0-c3: Lock entities, garage doors, entry sensors, lights, cameras,
        alarm panel, auto-follow, lock check interval.
        """
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
        )

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input},
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_SECURITY_LOCK_ENTITIES,
                default=self._get_current(CONF_SECURITY_LOCK_ENTITIES, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="lock", multiple=True
                )
            ),
            vol.Optional(
                CONF_SECURITY_GARAGE_ENTITIES,
                default=self._get_current(CONF_SECURITY_GARAGE_ENTITIES, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="cover",
                    device_class=["garage"],
                    multiple=True,
                )
            ),
            vol.Optional(
                CONF_SECURITY_ENTRY_SENSORS,
                default=self._get_current(CONF_SECURITY_ENTRY_SENSORS, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="binary_sensor",
                    device_class=["door", "window", "opening"],
                    multiple=True,
                )
            ),
            vol.Optional(
                CONF_SECURITY_LIGHT_ENTITIES,
                default=self._get_current(CONF_SECURITY_LIGHT_ENTITIES, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="light", multiple=True
                )
            ),
            vol.Optional(
                CONF_SECURITY_CAMERA_ENTITIES,
                default=self._get_current(CONF_SECURITY_CAMERA_ENTITIES, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="camera", multiple=True
                )
            ),
            vol.Optional(
                CONF_SECURITY_CAMERA_RECORDING,
                default=self._get_current(CONF_SECURITY_CAMERA_RECORDING, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SECURITY_CAMERA_RECORD_DURATION,
                default=self._get_current(CONF_SECURITY_CAMERA_RECORD_DURATION, 30),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10, max=300, step=10, unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_SECURITY_ALARM_PANEL,
                description={"suggested_value": self._get_current(
                    CONF_SECURITY_ALARM_PANEL
                )},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="alarm_control_panel"
                )
            ),
            vol.Optional(
                CONF_SECURITY_AUTO_FOLLOW,
                default=self._get_current(CONF_SECURITY_AUTO_FOLLOW, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SECURITY_LOCK_CHECK_INTERVAL,
                default=self._get_current(CONF_SECURITY_LOCK_CHECK_INTERVAL, 30),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5, max=120, step=5, unit_of_measurement="minutes",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
        })

        return self.async_show_form(
            step_id="coordinator_security",
            data_schema=data_schema,
        )

    async def async_step_coordinator_music_following(self, user_input=None):
        """Configure Music Following Coordinator tuning parameters.

        v3.6.24: Cooldown, ping-pong window, verify delay, unjoin delay,
        position offset, and minimum confidence.
        """
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

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input},
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_MF_COOLDOWN_SECONDS,
                default=self._get_current(
                    CONF_MF_COOLDOWN_SECONDS, DEFAULT_MF_COOLDOWN_SECONDS
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=30, step=1, unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_MF_PING_PONG_WINDOW,
                default=self._get_current(
                    CONF_MF_PING_PONG_WINDOW, DEFAULT_MF_PING_PONG_WINDOW
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10, max=300, step=5, unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_MF_VERIFY_DELAY,
                default=self._get_current(
                    CONF_MF_VERIFY_DELAY, DEFAULT_MF_VERIFY_DELAY
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=10, step=1, unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_MF_UNJOIN_DELAY,
                default=self._get_current(
                    CONF_MF_UNJOIN_DELAY, DEFAULT_MF_UNJOIN_DELAY
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=15, step=1, unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_MF_POSITION_OFFSET,
                default=self._get_current(
                    CONF_MF_POSITION_OFFSET, DEFAULT_MF_POSITION_OFFSET
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=10, step=1, unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_MF_MIN_CONFIDENCE,
                default=self._get_current(
                    CONF_MF_MIN_CONFIDENCE, DEFAULT_MF_MIN_CONFIDENCE
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.1, max=1.0, step=0.05,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_MF_HIGH_CONFIDENCE_DISTANCE,
                default=self._get_current(
                    CONF_MF_HIGH_CONFIDENCE_DISTANCE, DEFAULT_MF_HIGH_CONFIDENCE_DISTANCE
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=3.0, max=20.0, step=0.5, unit_of_measurement="ft",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
        })

        return self.async_show_form(
            step_id="coordinator_music_following",
            data_schema=data_schema,
        )

    # =========================================================================
    # v3.6.29: Notification Manager Config Flow Steps
    # =========================================================================

    async def async_step_coordinator_notifications(self, user_input=None):
        """Configure Notification Manager channels.

        v3.6.29: Enable/disable channels, set severity thresholds, configure
        channel-specific settings (service names, speaker lists, lights).
        """
        from .const import (
            CONF_NM_PUSHOVER_ENABLED, CONF_NM_PUSHOVER_SEVERITY, CONF_NM_PUSHOVER_SERVICE,
            CONF_NM_COMPANION_ENABLED, CONF_NM_COMPANION_SEVERITY,
            CONF_NM_WHATSAPP_ENABLED, CONF_NM_WHATSAPP_SEVERITY,
            CONF_NM_TTS_ENABLED, CONF_NM_TTS_SEVERITY, CONF_NM_TTS_SPEAKERS,
            CONF_NM_LIGHTS_ENABLED, CONF_NM_LIGHTS_SEVERITY, CONF_NM_ALERT_LIGHTS,
            DEFAULT_NM_PUSHOVER_SEVERITY, DEFAULT_NM_COMPANION_SEVERITY,
            DEFAULT_NM_WHATSAPP_SEVERITY, DEFAULT_NM_TTS_SEVERITY,
            DEFAULT_NM_LIGHTS_SEVERITY,
        )

        if user_input is not None:
            # Store channel config and advance to persons step
            self._nm_pending = {**self._config_entry.options, **user_input}
            return await self.async_step_coordinator_notifications_persons()

        severity_options = [
            {"value": "LOW", "label": "Low"},
            {"value": "MEDIUM", "label": "Medium"},
            {"value": "HIGH", "label": "High"},
            {"value": "CRITICAL", "label": "Critical"},
        ]

        data_schema = vol.Schema({
            vol.Optional(
                CONF_NM_PUSHOVER_ENABLED,
                default=self._get_current(CONF_NM_PUSHOVER_ENABLED, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_NM_PUSHOVER_SEVERITY,
                default=self._get_current(CONF_NM_PUSHOVER_SEVERITY, DEFAULT_NM_PUSHOVER_SEVERITY),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=severity_options, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_NM_PUSHOVER_SERVICE,
                default=self._get_current(CONF_NM_PUSHOVER_SERVICE, "notify.pushover"),
            ): selector.TextSelector(),
            vol.Optional(
                CONF_NM_COMPANION_ENABLED,
                default=self._get_current(CONF_NM_COMPANION_ENABLED, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_NM_COMPANION_SEVERITY,
                default=self._get_current(CONF_NM_COMPANION_SEVERITY, DEFAULT_NM_COMPANION_SEVERITY),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=severity_options, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_NM_WHATSAPP_ENABLED,
                default=self._get_current(CONF_NM_WHATSAPP_ENABLED, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_NM_WHATSAPP_SEVERITY,
                default=self._get_current(CONF_NM_WHATSAPP_SEVERITY, DEFAULT_NM_WHATSAPP_SEVERITY),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=severity_options, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_NM_TTS_ENABLED,
                default=self._get_current(CONF_NM_TTS_ENABLED, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_NM_TTS_SEVERITY,
                default=self._get_current(CONF_NM_TTS_SEVERITY, DEFAULT_NM_TTS_SEVERITY),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=severity_options, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_NM_TTS_SPEAKERS,
                default=self._get_current(CONF_NM_TTS_SPEAKERS, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player", multiple=True)
            ),
            vol.Optional(
                CONF_NM_LIGHTS_ENABLED,
                default=self._get_current(CONF_NM_LIGHTS_ENABLED, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_NM_LIGHTS_SEVERITY,
                default=self._get_current(CONF_NM_LIGHTS_SEVERITY, DEFAULT_NM_LIGHTS_SEVERITY),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=severity_options, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_NM_ALERT_LIGHTS,
                default=self._get_current(CONF_NM_ALERT_LIGHTS, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light", multiple=True)
            ),
        })

        return self.async_show_form(
            step_id="coordinator_notifications",
            data_schema=data_schema,
        )

    async def async_step_coordinator_notifications_persons(self, user_input=None):
        """Configure per-person notification settings.

        v3.6.29: Person entity, channel credentials, delivery preference, digest times.
        """
        from .const import (
            CONF_NM_PERSONS,
            CONF_NM_PERSON_ENTITY, CONF_NM_PERSON_PUSHOVER_KEY,
            CONF_NM_PERSON_COMPANION_SERVICE, CONF_NM_PERSON_WHATSAPP_PHONE,
            CONF_NM_PERSON_DELIVERY_PREF, CONF_NM_PERSON_DIGEST_MORNING,
            CONF_NM_PERSON_DIGEST_EVENING_ENABLED, CONF_NM_PERSON_DIGEST_EVENING,
            NM_DELIVERY_IMMEDIATE, NM_DELIVERY_DIGEST, NM_DELIVERY_OFF,
        )

        if user_input is not None:
            # Store as a single-person entry in the persons list
            pending = getattr(self, "_nm_pending", {**self._config_entry.options})
            persons = list(pending.get(CONF_NM_PERSONS, []))
            person_entry = {
                CONF_NM_PERSON_ENTITY: user_input.get(CONF_NM_PERSON_ENTITY, ""),
                CONF_NM_PERSON_PUSHOVER_KEY: user_input.get(CONF_NM_PERSON_PUSHOVER_KEY, ""),
                CONF_NM_PERSON_COMPANION_SERVICE: user_input.get(CONF_NM_PERSON_COMPANION_SERVICE, ""),
                CONF_NM_PERSON_WHATSAPP_PHONE: user_input.get(CONF_NM_PERSON_WHATSAPP_PHONE, ""),
                CONF_NM_PERSON_DELIVERY_PREF: user_input.get(CONF_NM_PERSON_DELIVERY_PREF, NM_DELIVERY_IMMEDIATE),
                CONF_NM_PERSON_DIGEST_MORNING: user_input.get(CONF_NM_PERSON_DIGEST_MORNING, "08:00"),
                CONF_NM_PERSON_DIGEST_EVENING_ENABLED: user_input.get(CONF_NM_PERSON_DIGEST_EVENING_ENABLED, False),
                CONF_NM_PERSON_DIGEST_EVENING: user_input.get(CONF_NM_PERSON_DIGEST_EVENING, "18:00"),
            }
            # Replace existing entry for same person or add new
            entity_id = person_entry[CONF_NM_PERSON_ENTITY]
            persons = [p for p in persons if p.get(CONF_NM_PERSON_ENTITY) != entity_id]
            persons.append(person_entry)
            self._nm_pending = {**pending, CONF_NM_PERSONS: persons}
            # Advance to quiet hours
            return await self.async_step_coordinator_notifications_quiet()

        delivery_options = [
            {"value": NM_DELIVERY_IMMEDIATE, "label": "Immediate"},
            {"value": NM_DELIVERY_DIGEST, "label": "Daily Digest"},
            {"value": NM_DELIVERY_OFF, "label": "Off"},
        ]

        data_schema = vol.Schema({
            vol.Required(
                CONF_NM_PERSON_ENTITY,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="person")
            ),
            vol.Optional(
                CONF_NM_PERSON_PUSHOVER_KEY,
                default="",
            ): selector.TextSelector(),
            vol.Optional(
                CONF_NM_PERSON_COMPANION_SERVICE,
                default="",
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Optional(
                CONF_NM_PERSON_WHATSAPP_PHONE,
                default="",
            ): selector.TextSelector(),
            vol.Optional(
                CONF_NM_PERSON_DELIVERY_PREF,
                default=NM_DELIVERY_IMMEDIATE,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=delivery_options, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_NM_PERSON_DIGEST_MORNING,
                default="08:00",
            ): selector.TimeSelector(),
            vol.Optional(
                CONF_NM_PERSON_DIGEST_EVENING_ENABLED,
                default=False,
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_NM_PERSON_DIGEST_EVENING,
                default="18:00",
            ): selector.TimeSelector(),
        })

        return self.async_show_form(
            step_id="coordinator_notifications_persons",
            data_schema=data_schema,
        )

    async def async_step_coordinator_notifications_quiet(self, user_input=None):
        """Configure quiet hours settings.

        v3.6.29: House state toggle or manual time window.
        """
        from .const import (
            CONF_NM_QUIET_USE_HOUSE_STATE,
            CONF_NM_QUIET_MANUAL_START,
            CONF_NM_QUIET_MANUAL_END,
        )

        if user_input is not None:
            pending = getattr(self, "_nm_pending", {**self._config_entry.options})
            self._nm_pending = {**pending, **user_input}
            # Advance to cooldowns
            return await self.async_step_coordinator_notifications_cooldowns()

        data_schema = vol.Schema({
            vol.Optional(
                CONF_NM_QUIET_USE_HOUSE_STATE,
                default=self._get_current(CONF_NM_QUIET_USE_HOUSE_STATE, True),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_NM_QUIET_MANUAL_START,
                default=self._get_current(CONF_NM_QUIET_MANUAL_START, "22:00"),
            ): selector.TimeSelector(),
            vol.Optional(
                CONF_NM_QUIET_MANUAL_END,
                default=self._get_current(CONF_NM_QUIET_MANUAL_END, "07:00"),
            ): selector.TimeSelector(),
        })

        return self.async_show_form(
            step_id="coordinator_notifications_quiet",
            data_schema=data_schema,
        )

    async def async_step_coordinator_notifications_cooldowns(self, user_input=None):
        """Configure per-hazard-type cooldown durations.

        v3.6.29: Minutes before re-evaluating after ack.
        """
        from .const import (
            CONF_NM_COOLDOWN_SMOKE, CONF_NM_COOLDOWN_CO,
            CONF_NM_COOLDOWN_FLOODING, CONF_NM_COOLDOWN_WATER_LEAK,
            CONF_NM_COOLDOWN_FREEZE, CONF_NM_COOLDOWN_INTRUSION,
            CONF_NM_COOLDOWN_DEFAULT,
            DEFAULT_NM_COOLDOWN_SMOKE, DEFAULT_NM_COOLDOWN_CO,
            DEFAULT_NM_COOLDOWN_FLOODING, DEFAULT_NM_COOLDOWN_WATER_LEAK,
            DEFAULT_NM_COOLDOWN_FREEZE, DEFAULT_NM_COOLDOWN_INTRUSION,
            DEFAULT_NM_COOLDOWN_DEFAULT,
        )

        if user_input is not None:
            # Final step — merge all accumulated NM config and save
            pending = getattr(self, "_nm_pending", {**self._config_entry.options})
            final_data = {**pending, **user_input}
            return self.async_create_entry(
                title="",
                data=final_data,
            )

        cooldown_schema = {}
        for key, default in [
            (CONF_NM_COOLDOWN_SMOKE, DEFAULT_NM_COOLDOWN_SMOKE),
            (CONF_NM_COOLDOWN_CO, DEFAULT_NM_COOLDOWN_CO),
            (CONF_NM_COOLDOWN_FLOODING, DEFAULT_NM_COOLDOWN_FLOODING),
            (CONF_NM_COOLDOWN_WATER_LEAK, DEFAULT_NM_COOLDOWN_WATER_LEAK),
            (CONF_NM_COOLDOWN_FREEZE, DEFAULT_NM_COOLDOWN_FREEZE),
            (CONF_NM_COOLDOWN_INTRUSION, DEFAULT_NM_COOLDOWN_INTRUSION),
            (CONF_NM_COOLDOWN_DEFAULT, DEFAULT_NM_COOLDOWN_DEFAULT),
        ]:
            cooldown_schema[vol.Optional(
                key,
                default=self._get_current(key, default),
            )] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=60, step=1, unit_of_measurement="minutes",
                    mode=selector.NumberSelectorMode.BOX,
                )
            )

        return self.async_show_form(
            step_id="coordinator_notifications_cooldowns",
            data_schema=vol.Schema(cooldown_schema),
        )

    async def async_step_coordinator_toggles(self, user_input=None):
        """Enable/disable individual coordinators.

        v3.6.0-c2.1: Per-coordinator on/off toggles stored in CM entry options.
        """
        from .const import (
            CONF_PRESENCE_ENABLED,
            CONF_SAFETY_ENABLED,
            CONF_SECURITY_ENABLED,
        )

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input},
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_PRESENCE_ENABLED,
                default=self._get_current(CONF_PRESENCE_ENABLED, True),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SAFETY_ENABLED,
                default=self._get_current(CONF_SAFETY_ENABLED, True),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SECURITY_ENABLED,
                default=self._get_current(CONF_SECURITY_ENABLED, True),
            ): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="coordinator_toggles",
            data_schema=data_schema,
        )

    # =========================================================================
    # INTEGRATION OPTIONS (continued)
    # =========================================================================

    async def async_step_default_notifications(self, user_input=None):
        """Reconfigure default notifications (integration level)."""
        if user_input is not None:
            # FIX v3.2.3.1: Pass merged options directly to async_create_entry
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input}
            )

        # Get available notify services
        notify_services = []
        if "notify" in self.hass.services.async_services():
            for service_name in self.hass.services.async_services()["notify"].keys():
                notify_services.append({
                    "label": f"notify.{service_name}",
                    "value": f"notify.{service_name}"
                })
        
        if not notify_services:
            notify_services.append({
                "label": "No notify services configured",
                "value": ""
            })

        notify_levels = [
            {"label": "Off", "value": NOTIFY_LEVEL_OFF},
            {"label": "Errors Only", "value": NOTIFY_LEVEL_ERRORS},
            {"label": "Important Events", "value": NOTIFY_LEVEL_IMPORTANT},
            {"label": "All Events", "value": NOTIFY_LEVEL_ALL},
        ]

        data_schema = vol.Schema({
            vol.Optional(
                CONF_NOTIFY_SERVICE,
                default=self._get_current(CONF_NOTIFY_SERVICE) or vol.UNDEFINED
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify_services, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_NOTIFY_TARGET,
                default=self._get_current(CONF_NOTIFY_TARGET) or vol.UNDEFINED
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=self._get_mobile_app_targets(), mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_NOTIFY_LEVEL,
                default=self._get_current(CONF_NOTIFY_LEVEL, NOTIFY_LEVEL_ERRORS)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify_levels, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
        })

        return self.async_show_form(
            step_id="default_notifications",
            data_schema=data_schema,
        )

    async def async_step_manage_zones(self, user_input=None):
        """Select a zone to configure (v3.6.0 — reads from Zone Manager entry).

        Accessible from Zone Manager options menu.
        """
        errors = {}

        if user_input is not None:
            selected_zone = user_input.get("zone_name")
            if selected_zone:
                self._selected_zone_name = selected_zone
                return await self.async_step_zone_config_menu()
            else:
                errors["base"] = "no_zone_selected"

        # Read zones from Zone Manager entry (or from this entry if it IS the ZM)
        zone_options = []
        entry = self._config_entry
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
            merged = {**entry.data, **entry.options}
            zones_data = merged.get("zones", {})
            for zone_name in zones_data:
                zone_options.append({
                    "label": zone_name.title(),
                    "value": zone_name,
                })
        else:
            # Fallback: find Zone Manager entry
            for ce in self.hass.config_entries.async_entries(DOMAIN):
                if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
                    merged = {**ce.data, **ce.options}
                    for zone_name in merged.get("zones", {}):
                        zone_options.append({
                            "label": zone_name.title(),
                            "value": zone_name,
                        })
                    break

        if not zone_options:
            return self.async_abort(reason="no_zones_configured")

        data_schema = vol.Schema({
            vol.Required("zone_name"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=zone_options,
                    mode=selector.SelectSelectorMode.DROPDOWN
                )
            ),
        })

        return self.async_show_form(
            step_id="manage_zones",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_zone_config_menu(self, user_input=None):
        """Show zone configuration submenu after selecting a zone (v3.3.3).

        v3.6.0-c2.3: Support zones stored in Zone Manager entry (not legacy
        zone entries). Uses _selected_zone_name when available.
        """
        # v3.6.0-c2.3: Allow routing via _selected_zone_name (ZM flow)
        if not getattr(self, "_selected_zone_name", None):
            zone_entry = self._get_zone_entry()
            if not zone_entry:
                return self.async_abort(reason="zone_not_found")

        return self.async_show_menu(
            step_id="zone_config_menu",
            menu_options=[
                "zone_rooms",
                "zone_media",
                "zone_hvac",
            ],
        )

    # =========================================================================
    # ZONE OPTIONS (for zone entries)
    # =========================================================================

    async def async_step_zone_rooms(self, user_input=None):
        """Reconfigure zone - update name and rooms.

        v3.6.0-c2.3: Supports both legacy zone entries and ZM-stored zones.
        """
        # v3.6.0-c2.3: Try ZM flow first (zones stored in Zone Manager entry)
        zm_result = self._get_zm_zone_data()
        zone_entry = None if zm_result else self._get_zone_entry()
        if not zm_result and not zone_entry:
            return self.async_abort(reason="zone_not_found")

        if zm_result:
            zm_entry, orig_zone_name, zone_data = zm_result
            current_zone_name = orig_zone_name
            current_zone_desc = zone_data.get(CONF_ZONE_DESCRIPTION, "")
            current_zone_rooms = zone_data.get(CONF_ZONE_ROOMS, [])
        else:
            orig_zone_name = (
                zone_entry.data.get(CONF_ZONE_NAME)
                or zone_entry.options.get(CONF_ZONE_NAME, "")
            ).strip()
            current_zone_name = zone_entry.options.get(
                CONF_ZONE_NAME, zone_entry.data.get(CONF_ZONE_NAME, "")
            )
            current_zone_desc = zone_entry.options.get(
                CONF_ZONE_DESCRIPTION, zone_entry.data.get(CONF_ZONE_DESCRIPTION, "")
            )
            current_zone_rooms = zone_entry.options.get(
                CONF_ZONE_ROOMS, zone_entry.data.get(CONF_ZONE_ROOMS, [])
            )

        if user_input is not None:
            zone_name = user_input.get(CONF_ZONE_NAME, "").strip()
            selected_rooms = user_input.get(CONF_ZONE_ROOMS, [])
            old_zone_name = orig_zone_name if zm_result else current_zone_name

            # Update each selected room's zone assignment
            for room_entry_id in selected_rooms:
                room_entry = self.hass.config_entries.async_get_entry(room_entry_id)
                if room_entry and room_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                    new_options = dict(room_entry.options)
                    new_options[CONF_ZONE] = zone_name
                    self.hass.config_entries.async_update_entry(
                        room_entry, options=new_options
                    )

            # Clear zone from rooms that were removed
            removed_rooms = set(current_zone_rooms) - set(selected_rooms)
            for room_entry_id in removed_rooms:
                room_entry = self.hass.config_entries.async_get_entry(room_entry_id)
                if room_entry and room_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                    room_zone = room_entry.options.get(CONF_ZONE) or room_entry.data.get(CONF_ZONE)
                    if room_zone == old_zone_name:
                        new_options = dict(room_entry.options)
                        new_options[CONF_ZONE] = ""
                        self.hass.config_entries.async_update_entry(
                            room_entry, options=new_options
                        )

            # Remove old zone device on rename
            if old_zone_name and old_zone_name != zone_name:
                from homeassistant.helpers import device_registry as dr
                dev_reg = dr.async_get(self.hass)
                old_device = dev_reg.async_get_device(
                    identifiers={(DOMAIN, f"zone_{old_zone_name}")}
                )
                if old_device:
                    dev_reg.async_remove_device(old_device.id)

            if zm_result:
                # v3.6.0-c2.3: Update zone in ZM entry's zones dict
                merged = {**zm_entry.data, **zm_entry.options}
                # Deep copy inner dicts to avoid in-place mutation of
                # entry.options (async_update_entry skips save if equal).
                zones = {
                    k: dict(v) for k, v in merged.get("zones", {}).items()
                }
                # Remove old name key if renamed
                if old_zone_name != zone_name and old_zone_name in zones:
                    zones[zone_name] = zones.pop(old_zone_name)
                else:
                    zones.setdefault(zone_name, {})
                zones[zone_name][CONF_ZONE_DESCRIPTION] = user_input.get(
                    CONF_ZONE_DESCRIPTION, ""
                )
                zones[zone_name][CONF_ZONE_ROOMS] = selected_rooms
                self.hass.config_entries.async_update_entry(
                    zm_entry,
                    options={**zm_entry.options, "zones": zones},
                )
                self._selected_zone_name = zone_name
                return await self.async_step_zone_config_menu()
            elif self._selected_zone_entry_id:
                new_zone_options = {
                    **zone_entry.options,
                    CONF_ZONE_NAME: zone_name,
                    CONF_ZONE_DESCRIPTION: user_input.get(CONF_ZONE_DESCRIPTION, ""),
                    CONF_ZONE_ROOMS: selected_rooms,
                }
                self.hass.config_entries.async_update_entry(
                    zone_entry, options=new_zone_options
                )
                return await self.async_step_zone_config_menu()
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        **zone_entry.options,
                        CONF_ZONE_NAME: zone_name,
                        CONF_ZONE_DESCRIPTION: user_input.get(CONF_ZONE_DESCRIPTION, ""),
                        CONF_ZONE_ROOMS: selected_rooms,
                    },
                )

        # Get room entries for selection
        room_entries = self._get_all_room_entries()
        room_options = [
            {
                "label": entry.data.get(CONF_ROOM_NAME, entry.title),
                "value": entry.entry_id
            }
            for entry in room_entries
        ]
        
        # Build schema
        schema_fields = {
            vol.Required(
                CONF_ZONE_NAME,
                default=current_zone_name
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Optional(
                CONF_ZONE_DESCRIPTION,
                default=current_zone_desc
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
        }
        
        if room_options:
            schema_fields[vol.Optional(
                CONF_ZONE_ROOMS,
                default=current_zone_rooms
            )] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=room_options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN
                )
            )
        
        data_schema = vol.Schema(schema_fields)

        return self.async_show_form(
            step_id="zone_rooms",
            data_schema=data_schema,
        )

    async def async_step_zone_media(self, user_input=None):
        """Configure zone media player settings (v3.3.1, updated v3.3.3).

        v3.6.0-c2.3: Supports ZM-stored zones.
        """
        zm_result = self._get_zm_zone_data()
        zone_entry = None if zm_result else self._get_zone_entry()
        if not zm_result and not zone_entry:
            return self.async_abort(reason="zone_not_found")

        if zm_result:
            zm_entry, zone_name, zone_data = zm_result
            current_player = zone_data.get(CONF_ZONE_PLAYER_ENTITY)
            current_mode = zone_data.get(
                CONF_ZONE_PLAYER_MODE, ZONE_PLAYER_MODE_FALLBACK
            )
        else:
            current_player = zone_entry.options.get(
                CONF_ZONE_PLAYER_ENTITY,
                zone_entry.data.get(CONF_ZONE_PLAYER_ENTITY),
            )
            current_mode = zone_entry.options.get(
                CONF_ZONE_PLAYER_MODE,
                zone_entry.data.get(CONF_ZONE_PLAYER_MODE, ZONE_PLAYER_MODE_FALLBACK),
            )

        if user_input is not None:
            if zm_result:
                # v3.6.0-c2.3: Update zone media in ZM entry's zones dict
                merged = {**zm_entry.data, **zm_entry.options}
                zones = {
                    k: dict(v) for k, v in merged.get("zones", {}).items()
                }
                zones.setdefault(zone_name, {})
                zones[zone_name].update(user_input)
                self.hass.config_entries.async_update_entry(
                    zm_entry,
                    options={**zm_entry.options, "zones": zones},
                )
                return await self.async_step_zone_config_menu()
            elif self._selected_zone_entry_id:
                new_zone_options = {**zone_entry.options, **user_input}
                self.hass.config_entries.async_update_entry(
                    zone_entry, options=new_zone_options
                )
                return await self.async_step_zone_config_menu()
            else:
                return self.async_create_entry(
                    title="",
                    data={**zone_entry.options, **user_input},
                )

        # Define zone player mode options
        zone_player_modes = [
            {"label": "Fallback (Zone player first, then rooms)", "value": ZONE_PLAYER_MODE_FALLBACK},
            {"label": "Independent (Zone player only)", "value": ZONE_PLAYER_MODE_INDEPENDENT},
            {"label": "Aggregate (All room players)", "value": ZONE_PLAYER_MODE_AGGREGATE},
        ]

        data_schema = vol.Schema({
            vol.Optional(
                CONF_ZONE_PLAYER_ENTITY,
                default=current_player or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player")
            ),
            vol.Optional(
                CONF_ZONE_PLAYER_MODE,
                default=current_mode
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=zone_player_modes,
                    mode=selector.SelectSelectorMode.DROPDOWN
                )
            ),
        })

        return self.async_show_form(
            step_id="zone_media",
            data_schema=data_schema,
        )

    async def async_step_zone_hvac(self, user_input=None):
        """Configure zone thermostat (v3.6.23).

        Sets the climate entity that controls this zone's HVAC.
        Falls back to room traversal if not set.
        """
        zm_result = self._get_zm_zone_data()
        zone_entry = None if zm_result else self._get_zone_entry()
        if not zm_result and not zone_entry:
            return self.async_abort(reason="zone_not_found")

        if zm_result:
            zm_entry, zone_name, zone_data = zm_result
            current_thermostat = zone_data.get(CONF_ZONE_THERMOSTAT)
        else:
            current_thermostat = zone_entry.options.get(
                CONF_ZONE_THERMOSTAT,
                zone_entry.data.get(CONF_ZONE_THERMOSTAT),
            )

        if user_input is not None:
            if zm_result:
                merged = {**zm_entry.data, **zm_entry.options}
                # Deep copy zone dicts to avoid in-place mutation of
                # entry.options (which would make async_update_entry
                # think nothing changed and skip the save).
                zones = {
                    k: dict(v) for k, v in merged.get("zones", {}).items()
                }
                zones.setdefault(zone_name, {})
                zones[zone_name].update(user_input)
                self.hass.config_entries.async_update_entry(
                    zm_entry,
                    options={**zm_entry.options, "zones": zones},
                )
                return await self.async_step_zone_config_menu()
            elif self._selected_zone_entry_id:
                new_zone_options = {**zone_entry.options, **user_input}
                self.hass.config_entries.async_update_entry(
                    zone_entry, options=new_zone_options
                )
                return await self.async_step_zone_config_menu()
            else:
                return self.async_create_entry(
                    title="",
                    data={**zone_entry.options, **user_input},
                )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_ZONE_THERMOSTAT,
                default=current_thermostat or vol.UNDEFINED,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
        })

        return self.async_show_form(
            step_id="zone_hvac",
            data_schema=data_schema,
        )

    # =========================================================================
    # ROOM OPTIONS (for room entries)
    # =========================================================================

    async def async_step_basic_setup(self, user_input=None):
        """Reconfigure basic setup."""
        if user_input is not None:
            # FIX v3.2.3.1: Pass merged options directly to async_create_entry
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input}
            )

        room_types = [
            {"label": "Bedroom", "value": ROOM_TYPE_BEDROOM},
            {"label": "Closet", "value": ROOM_TYPE_CLOSET},
            {"label": "Bathroom", "value": ROOM_TYPE_BATHROOM},
            {"label": "Media Room / Entertainment", "value": ROOM_TYPE_MEDIA_ROOM},
            {"label": "Garage / Workshop", "value": ROOM_TYPE_GARAGE},
            {"label": "Utility Room", "value": ROOM_TYPE_UTILITY},
            {"label": "Common Area (Living/Dining)", "value": ROOM_TYPE_COMMON_AREA},
            {"label": "Generic Room", "value": ROOM_TYPE_GENERIC},
        ]
        
        # Get existing zones for combo selector
        existing_zones = self._get_existing_zones()
        zone_options = [{"label": z, "value": z} for z in sorted(existing_zones)]

        # Build schema - zone field as combo selector if zones exist
        schema_fields = {
            vol.Required(
                CONF_ROOM_NAME,
                default=self._get_current(CONF_ROOM_NAME)
            ): selector.TextSelector(),
            vol.Required(
                CONF_ROOM_TYPE,
                default=self._get_current(CONF_ROOM_TYPE, ROOM_TYPE_GENERIC)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=room_types, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_AREA_ID,
                default=self._get_current(CONF_AREA_ID)
            ): selector.AreaSelector(),
        }
        
        # Zone field - combo selector if zones exist, text selector otherwise
        current_zone = self._get_current(CONF_ZONE) or ""
        if zone_options:
            schema_fields[vol.Optional(
                CONF_ZONE,
                default=current_zone if current_zone else vol.UNDEFINED
            )] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=zone_options,
                    custom_value=False,
                    mode=selector.SelectSelectorMode.DROPDOWN
                )
            )
        else:
            schema_fields[vol.Optional(
                CONF_ZONE,
                default=current_zone if current_zone else vol.UNDEFINED
            )] = selector.TextSelector()
        
        # Shared space settings
        schema_fields.update({
            vol.Optional(
                CONF_SHARED_SPACE,
                default=self._get_current(CONF_SHARED_SPACE, False)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SHARED_SPACE_AUTO_OFF_HOUR,
                default=self._get_current(CONF_SHARED_SPACE_AUTO_OFF_HOUR, DEFAULT_SHARED_SPACE_AUTO_OFF_HOUR)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=23, step=1,
                    unit_of_measurement="hour (0-23)",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_SHARED_SPACE_WARNING,
                default=self._get_current(CONF_SHARED_SPACE_WARNING, True)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_OCCUPANCY_TIMEOUT,
                default=self._get_current(CONF_OCCUPANCY_TIMEOUT, DEFAULT_OCCUPANCY_TIMEOUT)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=3600, unit_of_measurement="seconds", mode=selector.NumberSelectorMode.BOX)
            ),
        })
        
        data_schema = vol.Schema(schema_fields)

        return self.async_show_form(
            step_id="basic_setup",
            data_schema=data_schema,
            description_placeholders={"name": "Reconfigure basic setup"},
        )

    async def async_step_sensors(self, user_input=None):
        """Reconfigure sensors."""
        errors = {}
        
        if user_input is not None:
            # Validate at least one occupancy detection method
            motion = user_input.get(CONF_MOTION_SENSORS, [])
            mmwave = user_input.get(CONF_MMWAVE_SENSORS, [])
            occupancy = user_input.get(CONF_OCCUPANCY_SENSORS, [])
            
            if not motion and not mmwave and not occupancy:
                errors["base"] = "no_occupancy_sensors"
            else:
                # FIX v3.2.3.1: Pass merged options directly to async_create_entry
                return self.async_create_entry(
                    title="",
                    data={**self._config_entry.options, **user_input}
                )

        door_types = [
            {"label": "Interior Door (room-to-room)", "value": DOOR_TYPE_INTERIOR},
            {"label": "Egress Door (exterior/security)", "value": DOOR_TYPE_EGRESS},
        ]

        data_schema = vol.Schema({
            vol.Optional(
                CONF_MOTION_SENSORS, 
                default=self._get_current(CONF_MOTION_SENSORS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Optional(
                CONF_MMWAVE_SENSORS, 
                default=self._get_current(CONF_MMWAVE_SENSORS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Optional(
                CONF_OCCUPANCY_SENSORS, 
                default=self._get_current(CONF_OCCUPANCY_SENSORS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            # v3.2.4: Scanner areas for sparse scanner homes
            vol.Optional(
                CONF_SCANNER_AREAS,
                default=self._get_current(CONF_SCANNER_AREAS, [])
            ): selector.AreaSelector(
                selector.AreaSelectorConfig(multiple=True)
            ),
            vol.Optional(
                CONF_TEMPERATURE_SENSOR, 
                default=self._get_current(CONF_TEMPERATURE_SENSOR) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional(
                CONF_HUMIDITY_SENSOR, 
                default=self._get_current(CONF_HUMIDITY_SENSOR) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
            ),
            vol.Optional(
                CONF_ILLUMINANCE_SENSOR, 
                default=self._get_current(CONF_ILLUMINANCE_SENSOR) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="illuminance")
            ),
            vol.Optional(
                CONF_DOOR_SENSORS, 
                default=self._get_current(CONF_DOOR_SENSORS) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", device_class=["door", "opening"])
            ),
            vol.Optional(
                CONF_DOOR_TYPE, 
                default=self._get_current(CONF_DOOR_TYPE, DOOR_TYPE_INTERIOR)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=door_types, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_WINDOW_SENSORS,
                default=self._get_current(CONF_WINDOW_SENSORS) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", device_class=["window", "door", "opening", "garage_door"])
            ),
            # v3.1.0: Water leak sensor
            vol.Optional(
                CONF_WATER_LEAK_SENSOR,
                default=self._get_current(CONF_WATER_LEAK_SENSOR) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", device_class=["moisture", "water_leak"])
            ),
        })

        return self.async_show_form(
            step_id="sensors",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"name": "Reconfigure sensors - at least one occupancy sensor required"},
        )

    async def async_step_devices(self, user_input=None):
        """Reconfigure devices."""
        if user_input is not None:
            # FIX v3.2.3.1: Pass merged options directly to async_create_entry
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input}
            )

        light_capabilities = [
            {"label": "Basic On/Off Only", "value": LIGHT_CAPABILITY_BASIC},
            {"label": "Brightness Control", "value": LIGHT_CAPABILITY_BRIGHTNESS},
            {"label": "Brightness + Color", "value": LIGHT_CAPABILITY_FULL},
        ]

        cover_types = [
            {"label": "Shades/Roller Blinds (Open/Close)", "value": COVER_TYPE_SHADE},
            {"label": "Venetian Blinds (Tilt)", "value": COVER_TYPE_TILT},
        ]

        data_schema = vol.Schema({
            vol.Optional(
                CONF_LIGHTS,
                default=self._get_current(CONF_LIGHTS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["light", "switch"], multiple=True)
            ),
            vol.Optional(
                CONF_LIGHT_CAPABILITIES,
                default=self._get_current(CONF_LIGHT_CAPABILITIES, LIGHT_CAPABILITY_BASIC)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=light_capabilities, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            # === v3.2.2.5: Night lights (subset of CONF_LIGHTS) ===
            vol.Optional(
                CONF_NIGHT_LIGHTS,
                default=self._get_current(CONF_NIGHT_LIGHTS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["light", "switch"], multiple=True)
            ),
            vol.Optional(
                CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
                default=self._get_current(CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS, DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=100, mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="%")
            ),
            vol.Optional(
                CONF_NIGHT_LIGHT_SLEEP_COLOR,
                default=self._get_current(CONF_NIGHT_LIGHT_SLEEP_COLOR, DEFAULT_NIGHT_LIGHT_SLEEP_COLOR)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1000, max=6500, mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="K")
            ),
            vol.Optional(
                CONF_NIGHT_LIGHT_DAY_BRIGHTNESS,
                default=self._get_current(CONF_NIGHT_LIGHT_DAY_BRIGHTNESS, DEFAULT_NIGHT_LIGHT_DAY_BRIGHTNESS)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=100, mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="%")
            ),
            vol.Optional(
                CONF_NIGHT_LIGHT_DAY_COLOR,
                default=self._get_current(CONF_NIGHT_LIGHT_DAY_COLOR, DEFAULT_NIGHT_LIGHT_DAY_COLOR)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1000, max=6500, mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="K")
            ),
            vol.Optional(
                CONF_FANS,
                default=self._get_current(CONF_FANS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="fan", multiple=True)
            ),
            vol.Optional(
                CONF_HUMIDITY_FANS,
                default=self._get_current(CONF_HUMIDITY_FANS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="fan", multiple=True)
            ),
            vol.Optional(
                CONF_COVERS,
                default=self._get_current(CONF_COVERS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="cover", multiple=True)
            ),
            vol.Optional(
                CONF_COVER_TYPE,
                default=self._get_current(CONF_COVER_TYPE, COVER_TYPE_SHADE)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cover_types, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_AUTO_SWITCHES,
                default=self._get_current(CONF_AUTO_SWITCHES, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch", multiple=True)
            ),
            vol.Optional(
                CONF_MANUAL_SWITCHES,
                default=self._get_current(CONF_MANUAL_SWITCHES, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["switch", "light", "fan"],
                    multiple=True,
                )
            ),
        })

        return self.async_show_form(
            step_id="devices",
            data_schema=data_schema,
            description_placeholders={"name": "Reconfigure devices"},
        )

    async def async_step_automation_behavior(self, user_input=None):
        """Reconfigure automation behavior."""
        if user_input is not None:
            # FIX v3.2.3.1: Pass merged options directly to async_create_entry
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input}
            )

        light_entry_actions = [
            {"label": "None (Manual Control)", "value": LIGHT_ACTION_NONE},
            {"label": "Turn On Always", "value": LIGHT_ACTION_TURN_ON},
            {"label": "Smart (Only When Dark)", "value": LIGHT_ACTION_TURN_ON_IF_DARK},
        ]

        light_exit_actions = [
            {"label": "Turn Off", "value": LIGHT_ACTION_TURN_OFF},
            {"label": "Leave On", "value": LIGHT_ACTION_LEAVE_ON},
        ]

        # v3.6.39: New 5-mode cover open system
        cover_open_modes = [
            {"label": "None (Manual Only)", "value": COVER_OPEN_NONE},
            {"label": "On Entry (Any Time)", "value": COVER_OPEN_ON_ENTRY},
            {"label": "At Time (Scheduled)", "value": COVER_OPEN_AT_TIME},
            {"label": "On Entry After Time", "value": COVER_OPEN_ON_ENTRY_AFTER_TIME},
            {"label": "At Time or On Entry", "value": COVER_OPEN_AT_TIME_OR_ON_ENTRY},
        ]

        open_time_sources = [
            {"label": "Sunrise", "value": TIME_SOURCE_SUNRISE},
            {"label": "Specific Hour", "value": TIME_SOURCE_SPECIFIC_HOUR},
        ]

        cover_exit_actions = [
            {"label": "None (Leave As-Is)", "value": COVER_ACTION_NONE},
            {"label": "Always", "value": COVER_ACTION_ALWAYS},
            {"label": "After Sunset Only", "value": COVER_ACTION_AFTER_SUNSET},
        ]

        close_time_sources = [
            {"label": "Sunset", "value": TIME_SOURCE_SUNSET},
            {"label": "Specific Hour", "value": TIME_SOURCE_SPECIFIC_HOUR},
        ]

        data_schema = vol.Schema({
            # Lighting
            vol.Optional(
                CONF_ENTRY_LIGHT_ACTION,
                default=self._get_current(CONF_ENTRY_LIGHT_ACTION, LIGHT_ACTION_NONE)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=light_entry_actions, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_EXIT_LIGHT_ACTION,
                default=self._get_current(CONF_EXIT_LIGHT_ACTION, LIGHT_ACTION_TURN_OFF)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=light_exit_actions, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_ILLUMINANCE_THRESHOLD,
                default=self._get_current(CONF_ILLUMINANCE_THRESHOLD, DEFAULT_DARK_THRESHOLD)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=100, unit_of_measurement="lx", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_LIGHT_BRIGHTNESS_PCT,
                default=self._get_current(CONF_LIGHT_BRIGHTNESS_PCT, DEFAULT_LIGHT_BRIGHTNESS)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=100, unit_of_measurement="%", mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Optional(
                CONF_LIGHT_TRANSITION_ON,
                default=self._get_current(CONF_LIGHT_TRANSITION_ON, DEFAULT_LIGHT_TRANSITION_ON)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=10, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_LIGHT_TRANSITION_OFF,
                default=self._get_current(CONF_LIGHT_TRANSITION_OFF, DEFAULT_LIGHT_TRANSITION_OFF)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=10, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            # --- Covers: Open ---
            vol.Optional(
                CONF_COVER_OPEN_MODE,
                default=self._get_current(CONF_COVER_OPEN_MODE, COVER_OPEN_NONE)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cover_open_modes, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_COVER_OPEN_TIME_SOURCE,
                default=self._get_current(CONF_COVER_OPEN_TIME_SOURCE, TIME_SOURCE_SUNRISE)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=open_time_sources, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_COVER_OPEN_HOUR,
                default=self._get_current(CONF_COVER_OPEN_HOUR, DEFAULT_COVER_OPEN_HOUR)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=23, mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Optional(
                CONF_SUNRISE_OFFSET,
                default=self._get_current(CONF_SUNRISE_OFFSET, DEFAULT_SUNRISE_OFFSET)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=-60, max=120, step=15, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)
            ),
            # --- Covers: Close ---
            vol.Optional(
                CONF_EXIT_COVER_ACTION,
                default=self._get_current(CONF_EXIT_COVER_ACTION, COVER_ACTION_NONE)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cover_exit_actions, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_TIMED_CLOSE_ENABLED,
                default=self._get_current(CONF_TIMED_CLOSE_ENABLED, False)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_COVER_CLOSE_TIME_SOURCE,
                default=self._get_current(CONF_COVER_CLOSE_TIME_SOURCE, TIME_SOURCE_SUNSET)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=close_time_sources, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_COVER_CLOSE_HOUR,
                default=self._get_current(CONF_COVER_CLOSE_HOUR, DEFAULT_COVER_CLOSE_HOUR)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=23, mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Optional(
                CONF_SUNSET_OFFSET,
                default=self._get_current(CONF_SUNSET_OFFSET, DEFAULT_SUNSET_OFFSET)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=-60, max=120, step=15, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)
            ),
        })

        return self.async_show_form(
            step_id="automation_behavior",
            data_schema=data_schema,
            description_placeholders={"name": "Reconfigure automation behavior"},
        )

    async def async_step_climate(self, user_input=None):
        """Reconfigure climate."""
        if user_input is not None:
            # v3.6.23: Auto-populate zone thermostat if room is in a zone
            climate_entity = user_input.get(CONF_CLIMATE_ENTITY)
            if climate_entity:
                room_zone = self._get_current(CONF_ZONE) or ""
                if room_zone:
                    zm_entry = self._find_zone_manager_entry()
                    if zm_entry:
                        merged = {**zm_entry.data, **zm_entry.options}
                        zones = {
                            k: dict(v)
                            for k, v in merged.get("zones", {}).items()
                        }
                        zone_cfg = zones.get(room_zone, {})
                        if not zone_cfg.get(CONF_ZONE_THERMOSTAT):
                            zone_cfg[CONF_ZONE_THERMOSTAT] = climate_entity
                            zones[room_zone] = zone_cfg
                            self.hass.config_entries.async_update_entry(
                                zm_entry,
                                options={**zm_entry.options, "zones": zones},
                            )

            # FIX v3.2.3.1: Pass merged options directly to async_create_entry
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input}
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_CLIMATE_ENTITY,
                default=self._get_current(CONF_CLIMATE_ENTITY) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Optional(
                CONF_HVAC_COORDINATION_ENABLED, 
                default=self._get_current(CONF_HVAC_COORDINATION_ENABLED, False)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_TARGET_TEMP_COOL,
                default=self._get_current(CONF_TARGET_TEMP_COOL, DEFAULT_TARGET_TEMP_COOL)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=90, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_TARGET_TEMP_HEAT,
                default=self._get_current(CONF_TARGET_TEMP_HEAT, DEFAULT_TARGET_TEMP_HEAT)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=90, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_FAN_CONTROL_ENABLED,
                default=self._get_current(CONF_FAN_CONTROL_ENABLED, False)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_FAN_TEMP_THRESHOLD,
                default=self._get_current(CONF_FAN_TEMP_THRESHOLD, DEFAULT_FAN_TEMP_THRESHOLD)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=100, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_FAN_SPEED_LOW_TEMP,
                default=self._get_current(CONF_FAN_SPEED_LOW_TEMP, DEFAULT_FAN_SPEED_LOW)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=100, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_FAN_SPEED_MED_TEMP,
                default=self._get_current(CONF_FAN_SPEED_MED_TEMP, DEFAULT_FAN_SPEED_MED)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=100, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_FAN_SPEED_HIGH_TEMP,
                default=self._get_current(CONF_FAN_SPEED_HIGH_TEMP, DEFAULT_FAN_SPEED_HIGH)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=100, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_HUMIDITY_FAN_THRESHOLD,
                default=self._get_current(CONF_HUMIDITY_FAN_THRESHOLD, DEFAULT_HUMIDITY_THRESHOLD)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=30, max=80, unit_of_measurement="%", mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Optional(
                CONF_HUMIDITY_FAN_TIMEOUT,
                default=self._get_current(CONF_HUMIDITY_FAN_TIMEOUT, DEFAULT_HUMIDITY_FAN_TIMEOUT)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=3600, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_HVAC_EFFICIENCY_ALERTS,
                default=self._get_current(CONF_HVAC_EFFICIENCY_ALERTS, False)
            ): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="climate",
            data_schema=data_schema,
            description_placeholders={"name": "Reconfigure climate"},
        )

    async def async_step_sleep_protection(self, user_input=None):
        """Reconfigure sleep protection."""
        if user_input is not None:
            # FIX v3.2.3.1: Pass merged options directly to async_create_entry
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input}
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_SLEEP_PROTECTION_ENABLED,
                default=self._get_current(CONF_SLEEP_PROTECTION_ENABLED, False)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SLEEP_START_HOUR,
                default=self._get_current(CONF_SLEEP_START_HOUR, DEFAULT_SLEEP_START)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=23, mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Optional(
                CONF_SLEEP_END_HOUR,
                default=self._get_current(CONF_SLEEP_END_HOUR, DEFAULT_SLEEP_END)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=23, mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Optional(
                CONF_SLEEP_BYPASS_MOTION,
                default=self._get_current(CONF_SLEEP_BYPASS_MOTION, DEFAULT_SLEEP_BYPASS_COUNT)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=10, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_SLEEP_BLOCK_COVERS,
                default=self._get_current(CONF_SLEEP_BLOCK_COVERS, True)
            ): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="sleep_protection",
            data_schema=data_schema,
            description_placeholders={"name": "Reconfigure sleep protection"},
        )

    async def async_step_music_following(self, user_input=None):
        """Configure room media player for music following (v3.3.1)."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input}
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_MUSIC_FOLLOWING_ENABLED,
                default=self._get_current(CONF_MUSIC_FOLLOWING_ENABLED, True)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ROOM_MEDIA_PLAYER,
                default=self._get_current(CONF_ROOM_MEDIA_PLAYER) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player")
            ),
        })

        return self.async_show_form(
            step_id="music_following",
            data_schema=data_schema,
        )

    async def async_step_energy(self, user_input=None):
        """Reconfigure energy monitoring."""
        if user_input is not None:
            # FIX v3.2.3.1: Pass merged options directly to async_create_entry
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input}
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_POWER_SENSORS, 
                default=self._get_current(CONF_POWER_SENSORS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
            ),
            vol.Optional(
                CONF_ENERGY_SENSOR, 
                default=self._get_current(CONF_ENERGY_SENSOR) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
            vol.Optional(
                CONF_ELECTRICITY_RATE, 
                default=self._get_current(CONF_ELECTRICITY_RATE, DEFAULT_ELECTRICITY_RATE)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.01, max=1.00, step=0.01, unit_of_measurement="USD/kWh", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_NOTIFY_DAILY_ENERGY, 
                default=self._get_current(CONF_NOTIFY_DAILY_ENERGY, False)
            ): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="energy",
            data_schema=data_schema,
            description_placeholders={"name": "Reconfigure energy monitoring"},
        )

    async def async_step_notifications(self, user_input=None):
        """Reconfigure notifications with override option."""
        if user_input is not None:
            # FIX v3.2.3.1: Pass merged options directly to async_create_entry
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input}
            )

        # Get available notify services
        notify_services = []
        if "notify" in self.hass.services.async_services():
            for service_name in self.hass.services.async_services()["notify"].keys():
                notify_services.append({
                    "label": f"notify.{service_name}",
                    "value": f"notify.{service_name}"
                })
        
        if not notify_services:
            notify_services.append({
                "label": "No notify services configured",
                "value": ""
            })

        # Get mobile_app device targets from notify services
        notify_targets = [{"label": "None", "value": ""}]
        for service in notify_services:
            service_name = service["value"].replace("notify.", "")
            if service_name.startswith("mobile_app_"):
                device_name = service_name.replace("mobile_app_", "").replace("_", " ").title()
                notify_targets.append({
                    "label": device_name,
                    "value": service_name
                })
        # If no mobile_app services, at least show the service names
        if len(notify_targets) == 1:
            for service in notify_services:
                if service["value"]:
                    notify_targets.append({
                        "label": service["label"],
                        "value": service["value"].replace("notify.", "")
                    })

        notify_levels = [
            {"label": "Off", "value": NOTIFY_LEVEL_OFF},
            {"label": "Errors Only", "value": NOTIFY_LEVEL_ERRORS},
            {"label": "Important Events", "value": NOTIFY_LEVEL_IMPORTANT},
            {"label": "All Events", "value": NOTIFY_LEVEL_ALL},
        ]

        # v3.1.0: Alert light colors
        alert_colors = [
            {"label": "Amber (Warning)", "value": ALERT_COLOR_AMBER},
            {"label": "Red (Critical)", "value": ALERT_COLOR_RED},
            {"label": "Blue (Info)", "value": ALERT_COLOR_BLUE},
            {"label": "Green (OK)", "value": ALERT_COLOR_GREEN},
            {"label": "White (Neutral)", "value": ALERT_COLOR_WHITE},
        ]

        data_schema = vol.Schema({
            vol.Optional(
                CONF_OVERRIDE_NOTIFICATIONS,
                default=self._get_current(CONF_OVERRIDE_NOTIFICATIONS, False)
            ): selector.BooleanSelector(),
            vol.Optional(CONF_NOTIFY_SERVICE): selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify_services, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_NOTIFY_TARGET): selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify_targets, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_NOTIFY_LEVEL, 
                default=self._get_current(CONF_NOTIFY_LEVEL, NOTIFY_LEVEL_ERRORS)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify_levels, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            # v3.1.0: Alert lights
            vol.Optional(
                CONF_ALERT_LIGHTS,
                default=self._get_current(CONF_ALERT_LIGHTS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light", multiple=True)
            ),
            vol.Optional(
                CONF_ALERT_LIGHT_COLOR,
                default=self._get_current(CONF_ALERT_LIGHT_COLOR, ALERT_COLOR_AMBER)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=alert_colors, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
        })

        return self.async_show_form(
            step_id="notifications",
            data_schema=data_schema,
            description_placeholders={
                "name": "Reconfigure notifications. Enable override to use room-specific settings instead of integration defaults."
            },
        )
