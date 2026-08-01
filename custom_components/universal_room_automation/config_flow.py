"""Config flow for Universal Room Automation v3.6.24."""
# v4.5.2 D1: PEP 563 deferred annotation evaluation. See automation.py
# for rationale.
from __future__ import annotations

#
# Universal Room Automation vv4.5.0.4
# Build: 2026-01-05
# File: config_flow.py
# v3.3.3: Added manage_zones to integration options menu
# v3.3.3: Zone configuration accessible from integration entry
# v3.3.1: Added music_following and zone_media options steps
# v3.3.1: Fixed person_tracking missing from strings.json
# v3.2.4: CONF_SCANNER_AREAS replaces CONF_PHONE_TRACKER for person tracking
#

import asyncio
import json
import logging
import re
import uuid
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers import entity_registry as er
from homeassistant.const import CONF_NAME

try:  # Bathroom-exhaust intelligence cycle: hoisted from function-local so the
    # cycle_b test harness (which strips HA mocks after config_flow import)
    # doesn't ModuleNotFoundError when async_step_climate is later invoked
    # under a torn-down mock tree. Pre-existing `fan_recheck_advanced` section
    # uses still import it function-local; keep that pattern there.
    from homeassistant.data_entry_flow import section as _ha_section
except Exception:  # noqa: BLE001 — tests may mock without data_entry_flow
    def _ha_section(schema, options=None):  # type: ignore[no-redef]
        return schema

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
    CONF_OCCUPANCY_DEBOUNCE,
    # v4.7.2 D4: Per-room guest designation
    CONF_ROOM_IS_GUEST_ROOM,
    CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN,
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_CLOSET,
    ROOM_TYPE_BATHROOM,
    ROOM_TYPE_MEDIA_ROOM,
    ROOM_TYPE_GARAGE,
    ROOM_TYPE_UTILITY,
    ROOM_TYPE_COMMON_AREA,
    ROOM_TYPE_GENERIC,
    ROOM_TYPE_INFRASTRUCTURE,
    DEFAULT_OCCUPANCY_TIMEOUT,
    DEFAULT_OCCUPANCY_DEBOUNCE,
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
    CONF_WHOLE_HOUSE_POWER_SENSORS,
    CONF_WHOLE_HOUSE_ENERGY_SENSORS,
    CONF_ZONE_POWER_SENSORS,
    CONF_ZONE_ENERGY_SENSORS,
    CONF_HOUSE_DEVICE_POWER_SENSORS,
    CONF_HOUSE_DEVICE_ENERGY_SENSORS,
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
    CONF_DISABLE_CAMERA_PRESENCE,  # v4.7.16 D4: per-room camera-presence opt-out
    CONF_ROOM_CAMERAS,  # 2026-08-01 room-camera fusion cycle (D1)
    DEFAULT_DISABLE_CAMERA_PRESENCE,
    CONF_DOOR_SENSORS,
    CONF_DOOR_TYPE,
    CONF_WINDOW_SENSORS,
    CONF_IS_EGRESS_WINDOW,
    DEFAULT_IS_EGRESS_WINDOW,
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
    # Fan-noise mitigation D1: per-room adjacency for the Layer-1 BLE
    # corroboration ladder. Empty list is safe (L2 simply does not
    # fire; L1 + L3 still work).
    CONF_ADJACENT_ROOMS,
    # Fan-noise Mode-2 (room-tier fan-pause + clean recheck) per-room
    # opt-ins. Master + each room default OFF; operator pins the
    # rooms where Mode-2 is the live failure mode (Exercise + Jaya +
    # Ziri first).
    CONF_ROOM_FAN_RECHECK_ENABLED,
    DEFAULT_ROOM_FAN_RECHECK_ENABLED,
    CONF_FAN_RECHECK_L2_ALLOWED,
    DEFAULT_FAN_RECHECK_L2_ALLOWED,
    CONF_FAN_RECHECK_TRUST_SENSORS_OK,
    DEFAULT_FAN_RECHECK_TRUST_SENSORS_OK,
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
    CONF_FLAP_SENSITIVITY,
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_LIGHT_BRIGHTNESS_PCT,
    CONF_LIGHT_TRANSITION_ON,
    CONF_LIGHT_TRANSITION_OFF,
    CONF_EXIT_COVER_ACTION,
    CONF_SUNRISE_OFFSET,
    CONF_SUNSET_OFFSET,
    CONF_TIMED_CLOSE_ENABLED,
    CONF_COVER_HVAC_MANAGED,
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
    # Climate & Fans
    CONF_CLIMATE_ENTITY,
    CONF_HVAC_COORDINATION_ENABLED,
    CONF_TARGET_TEMP_COOL,
    CONF_TARGET_TEMP_HEAT,
    CONF_COMFORT_FAN_AWAY_VETO_ENABLED,
    DEFAULT_COMFORT_FAN_AWAY_VETO_ENABLED,
    CONF_FAN_CONTROL_ENABLED,
    CONF_FAN_TEMP_THRESHOLD,
    CONF_FAN_SPEED_LOW_TEMP,
    CONF_FAN_SPEED_MED_TEMP,
    CONF_FAN_SPEED_HIGH_TEMP,
    CONF_HUMIDITY_FAN_THRESHOLD,
    CONF_HUMIDITY_FAN_TIMEOUT,
    CONF_HUMIDITY_FAN_MAX_RUNTIME,
    DEFAULT_TARGET_TEMP_COOL,
    DEFAULT_TARGET_TEMP_HEAT,
    DEFAULT_FAN_TEMP_THRESHOLD,
    DEFAULT_FAN_SPEED_LOW,
    DEFAULT_FAN_SPEED_MED,
    DEFAULT_FAN_SPEED_HIGH,
    DEFAULT_HUMIDITY_THRESHOLD,
    DEFAULT_HUMIDITY_FAN_TIMEOUT,
    DEFAULT_HUMIDITY_FAN_MAX_RUNTIME,
    # Bathroom-exhaust intelligence cycle
    CONF_HUMIDITY_FAN_CONTROL_ENABLED,
    DEFAULT_HUMIDITY_FAN_CONTROL_ENABLED,
    CONF_WET_ROOM,
    CONF_HUMIDITY_FAN_SPIKE_ENABLED,
    CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT,
    CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S,
    CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE,
    HUMIDITY_FAN_SPIKE_MODE_EMA,
    HUMIDITY_FAN_SPIKE_MODE_WINDOW_MIN,
    DEFAULT_HUMIDITY_FAN_SPIKE_DELTA_PCT,
    DEFAULT_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S,
    DEFAULT_HUMIDITY_FAN_SPIKE_BASELINE_MODE,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S,
    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S,
    DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S,
    DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S,
    DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S,
    # Sleep protection
    CONF_SLEEP_PROTECTION_ENABLED,
    CONF_SLEEP_START_HOUR,
    CONF_SLEEP_END_HOUR,
    CONF_SLEEP_BYPASS_MOTION,
    CONF_SLEEP_BLOCK_COVERS,
    CONF_FAN_SLEEP_POLICY,
    DEFAULT_FAN_SLEEP_POLICY,
    DEFAULT_SLEEP_START,
    DEFAULT_SLEEP_END,
    DEFAULT_SLEEP_BYPASS_COUNT,
    # Energy
    CONF_POWER_SENSORS,
    CONF_ENERGY_SENSOR,
    CONF_ENERGY_SENSORS,
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
    CONF_ZONE_IS_OUTDOOR,  # v5.7.0 WS-A4
    DEFAULT_ZONE_IS_OUTDOOR,  # v5.7.0 WS-A4
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
    # v5.10.0 D11: per-room speaker loudness calibration.
    CONF_ROOM_MEDIA_VOLUME_SCALE,
    DEFAULT_ROOM_MEDIA_VOLUME_SCALE,
    MIN_ROOM_MEDIA_VOLUME_SCALE,
    MAX_ROOM_MEDIA_VOLUME_SCALE,
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
    CONF_CENSUS_DIVERGENCE_DOWNGRADE,
    DEFAULT_CENSUS_DIVERGENCE_DOWNGRADE,
    # v3.5.1: Perimeter Alerting
    CONF_PERIMETER_ALERT_HOURS_START,
    CONF_PERIMETER_ALERT_HOURS_END,
    CONF_PERIMETER_ALERT_NOTIFY_SERVICE,
    CONF_PERIMETER_ALERT_NOTIFY_TARGET,
    DEFAULT_PERIMETER_ALERT_START,
    DEFAULT_PERIMETER_ALERT_END,
    CONF_EXTERIOR_SNAPSHOT_OFFSET_S,
    DEFAULT_EXTERIOR_SNAPSHOT_OFFSET_S,
    MIN_EXTERIOR_SNAPSHOT_OFFSET_S,
    MAX_EXTERIOR_SNAPSHOT_OFFSET_S,
    # v3.5.2: Face Recognition
    CONF_FACE_RECOGNITION_ENABLED,
    # v3.10.0: Automation Chaining
    CONF_AUTOMATION_CHAINS,
    AUTOMATION_CHAIN_TRIGGERS_M1,
    # v3.12.0: M2 Coordinator Signal Triggers
    CHAIN_GROUP_OCCUPANCY,
    CHAIN_GROUP_LIGHT,
    CHAIN_GROUP_HOUSE_STATE,
    CHAIN_GROUP_COORDINATOR,
    # v3.12.0: M3 AI NL Rules
    CONF_AI_RULES,
    CONF_AI_RULE_TRIGGER,
    CONF_AI_RULE_PERSON,
    CONF_AI_RULE_DESCRIPTION,
    AI_RULE_TRIGGER_OPTIONS,
    AI_RULE_PARSING_PROMPT,
    CONF_AUTO_DEVICES,
    CONF_MANUAL_DEVICES,
    # v3.10.1: Census v2
    CONF_ENHANCED_CENSUS,
    CONF_CENSUS_HOLD_INTERIOR,
    CONF_CENSUS_HOLD_EXTERIOR,
    CONF_CENSUS_BLE_CANCEL_ENABLED,
    DEFAULT_CENSUS_BLE_CANCEL_ENABLED,
    DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES,
    DEFAULT_CENSUS_HOLD_EXTERIOR_MINUTES,
    CONF_GUEST_VLAN_SSID,
    DEFAULT_GUEST_VLAN_SSID,
    # v4.6.3 D10: Per-coordinator anomaly sensitivity dropdowns
    # Note: CONF_ENERGY_ANOMALY_SENSITIVITY removed — energy uses cross-check
    # detection (separate path), not AnomalyDetector.  See C7 fix.
    CONF_PRESENCE_ANOMALY_SENSITIVITY,
    CONF_SAFETY_ANOMALY_SENSITIVITY,
    CONF_HVAC_ANOMALY_SENSITIVITY,
    CONF_SECURITY_ANOMALY_SENSITIVITY,
    CONF_MUSIC_ANOMALY_SENSITIVITY,
    DEFAULT_ANOMALY_SENSITIVITY,
    ANOMALY_SENSITIVITY_OPTIONS,
)


# =============================================================================
# Zone Delete Flow — module-level confirm-name gate (extracted for test authority)
# =============================================================================
def _check_zone_confirm_name(typed: str | None, zone_name: str) -> bool:
    """Return True if operator-typed input matches the zone name.

    Extracted from ``async_step_zone_delete_confirm`` so BOTH the
    production step AND the test suite call the SAME helper (fix-up T3
    / C-CRIT-3: a hand-copied inline predicate is un-testable — a
    silent inline mutation of the compare would leave the suite green).

    Comparison rules (fix-up C-LOW-3):
      - ``None`` inputs never match
      - Whitespace-trim both sides
      - Case-fold both sides (case-insensitive)
      - NFC-normalize both sides so pre-composed vs decomposed
        Unicode (e.g. combining accents) is treated as equal

    The confirm gate is defensive — a mismatch is safe (form re-renders
    with an error), a false-positive match is destructive (zone gets
    deleted). Keep the predicate conservative.
    """
    import unicodedata
    if typed is None or not isinstance(zone_name, str):
        return False
    left = unicodedata.normalize("NFC", str(typed)).strip().casefold()
    right = unicodedata.normalize("NFC", zone_name).strip().casefold()
    return bool(left) and left == right


# =============================================================================
# Bathroom-exhaust intelligence cycle — climate-fans form validation
# =============================================================================
def _validate_climate_fans_form(user_input: dict) -> str | None:
    """Cross-field validation for the "Climate & Fans" step.

    Returns a translation-key suitable error string for `errors["base"]`, or
    None if the form is valid. Validates:
      D8 — comfort-range low ≤ high (low > high is rejected; low == high
            is a legal degenerate range with zero in-range band).
      D5 — presence-runtime cap ≤ humidity-fan max-runtime.
    """
    heat = user_input.get(CONF_TARGET_TEMP_HEAT)
    cool = user_input.get(CONF_TARGET_TEMP_COOL)
    if heat is not None and cool is not None:
        try:
            if float(heat) > float(cool):
                return "comfort_range_inverted"
        except (TypeError, ValueError):
            pass
    cap_s = user_input.get(CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S)
    max_runtime = user_input.get(CONF_HUMIDITY_FAN_MAX_RUNTIME)
    if cap_s is not None and max_runtime is not None:
        try:
            if int(cap_s) > int(max_runtime):
                return "presence_runtime_cap_above_max"
        except (TypeError, ValueError):
            pass
    return None


# =============================================================================
# v4.7.5 — Zone name validation
# =============================================================================
# The canonical merge in hvac_zones.py:788 produces labels of the form
# `"<existing> + <new>"` joined by the literal `" + "`. The lazy canonical
# resolution in energy.py splits merged labels back on `" + "`. A real zone
# name containing the literal `" + "` substring would collide with the
# separator (Bug Class #47 sub-class). Reject at config-flow validate time.
_ZONE_NAME_PLUS_SEPARATOR_RE = re.compile(r"\s\+\s")


# =============================================================================
# v4.7.5 — Option C auto-mirror: per-step MIRROR_KEYS_*
#
# When two house zones share a thermostat (e.g., "Entertainment" and "Master
# Suite" both → climate.studyb_zone_1), saving a per-zone editor form mirrors
# the *shared-thermostat-tied* fields to the sibling house zones. Per-house
# zone-only fields (rooms, media, persons, cameras) are intentionally NOT
# mirrored — Entertainment has different rooms than Master Suite.
#
# Mirror sets are deliberately scoped per step. See PLANNING_v4.7.5 §D4 for
# the rationale. Any new shared-thermostat-tied CONF added later MUST be
# enumerated here AND its editor step MUST call _auto_mirror_to_siblings.
#
# Imported lazily inside the helper to avoid bumping module-load cost.
# =============================================================================

# zone_rooms: NONE — CONF_ZONE_ROOMS is per-house-zone by design.
MIRROR_KEYS_ZONE_ROOMS: frozenset[str] = frozenset()

# zone_media: NONE — media_player + mode are per-house-zone.
MIRROR_KEYS_ZONE_MEDIA: frozenset[str] = frozenset()

# zone_persons: NONE — per-house-zone (bedrooms have different sleepers).
MIRROR_KEYS_ZONE_PERSONS: frozenset[str] = frozenset()

# zone_cameras: NONE — per-house-zone.
MIRROR_KEYS_ZONE_CAMERAS: frozenset[str] = frozenset()

# zone_hvac: thermostat + AC ramp fields tie to the shared physical equipment.
# Note: CONF_HVAC_AC_LOAD_SENSOR/CONF_HVAC_AC_RAMP_ZONE_ENABLED are imported
# lazily inside the step body; the string keys are the persisted names.
MIRROR_KEYS_ZONE_HVAC: frozenset[str] = frozenset({
    "zone_thermostat",
    "hvac_ac_load_sensor",
    "hvac_ac_ramp_zone_enabled",
    "zone_vacancy_sweep_enabled",  # tied to thermostat-level cooling decisions
})

# zone_energy: physical AC sub-circuit power/energy sensors are tied to the
# same thermostat's load.
MIRROR_KEYS_ZONE_ENERGY: frozenset[str] = frozenset({
    "zone_power_sensors",
    "zone_energy_sensors",
})

# zone_dynamic_preset: DPM drives the shared thermostat's setpoint. Only the
# 4 active knobs mirror to siblings.
# v5.11.x cleanup — bucket cells were UI-stripped in v4.7.18 D1; this drops
# them from sibling mirror too. Constants remain in energy_const.py for
# options-dict restore.
MIRROR_KEYS_ZONE_DPM: frozenset[str] = frozenset({
    "zone_dynamic_preset_enabled",
    "zone_dynamic_preset_offset",
    "zone_dynamic_preset_reset_offset_guest",
    "zone_dynamic_preset_sleep_enabled",
})


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
        
        # v4.2.0: Removed 6 dead fields (grid_import_sensor, grid_import_sensor_2,
        # solar_export_sensor, battery_level_sensor, delivery_rate,
        # export_reimbursement_rate) — all superseded by Envoy auto-derivation on CM
        # or TOU rate files. Constants kept for backward compat with stored configs.
        data_schema = vol.Schema({
            # Whole house monitoring (v4.1.0: multiple sensors)
            vol.Optional(CONF_WHOLE_HOUSE_POWER_SENSORS): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
            ),
            vol.Optional(CONF_WHOLE_HOUSE_ENERGY_SENSORS): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
            ),
            # Standalone device sensors (EV chargers, pool pumps, water heaters)
            vol.Optional(CONF_HOUSE_DEVICE_POWER_SENSORS): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
            ),
            vol.Optional(CONF_HOUSE_DEVICE_ENERGY_SENSORS): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
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
            elif _ZONE_NAME_PLUS_SEPARATOR_RE.search(zone_name):
                # v4.7.5 post-review (A-H3, Bug Class #47 sub-class): reject
                # ' + ' in zone names so the canonical merge label produced by
                # iter_canonical_hvac_zones (hvac_zones.py:788) — and the
                # `" + "` split fallback in energy.py — stay unambiguous.
                errors["base"] = "zone_name_contains_plus"
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
                        # v5.7.0 WS-A4: per-zone outdoor flag — excluded from
                        # the indoor-occupancy aggregation gating AWAY path β.
                        CONF_ZONE_IS_OUTDOOR: user_input.get(
                            CONF_ZONE_IS_OUTDOOR, DEFAULT_ZONE_IS_OUTDOOR
                        ),
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
                            # v5.7.0 WS-A4: persist on legacy zone entries too.
                            CONF_ZONE_IS_OUTDOOR: user_input.get(
                                CONF_ZONE_IS_OUTDOOR, DEFAULT_ZONE_IS_OUTDOOR
                            ),
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
            # v5.7.0 WS-A4: outdoor zone flag. Default False — only flip True
            # for zones whose occupancy should NOT count toward indoor presence
            # accounting (doorbell-camera "Outside", "Front Porch"). Outdoor
            # zones still surface in `any_zone_occupied` for non-presence
            # consumers; they are excluded from the WS-A2 path-β indoor guard
            # and the WS-A4 indoor-zone aggregation.
            vol.Optional(
                CONF_ZONE_IS_OUTDOOR,
                default=DEFAULT_ZONE_IS_OUTDOOR,
            ): selector.BooleanSelector(),
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
            {"label": "Infrastructure (Always-On Equipment)", "value": ROOM_TYPE_INFRASTRUCTURE},
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
            vol.Optional(
                CONF_OCCUPANCY_DEBOUNCE,
                default=DEFAULT_OCCUPANCY_DEBOUNCE
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=2000,
                    step=50,
                    unit_of_measurement="ms",
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
            # v4.7.16 D4: Per-room camera-presence opt-out
            vol.Optional(
                CONF_DISABLE_CAMERA_PRESENCE,
                default=DEFAULT_DISABLE_CAMERA_PRESENCE,
            ): selector.BooleanSelector(),
            # Room-camera fusion (2026-08-01): NEW key CONF_ROOM_CAMERAS.
            # Multi-select of ANY entity of/near a physical camera; the
            # resolver hops to the device and discovers per-integration
            # capabilities. Intentionally NO domain filter — plan D1 requires
            # accepting camera.*, binary_sensor.*, sensor.*, switch.*.
            # Distinct key from CONF_CAMERA_PERSON_ENTITIES so the v3.4.5
            # integration-migration does not eat it.
            vol.Optional(
                CONF_ROOM_CAMERAS,
                default=[],
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
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
            # v4.7.8 D1: Per-room egress flag. When True (default), this room's
            # window is treated as an egress (kid-can-forget) opening that
            # triggers the HVAC zone egress pause. Master switch on the HVAC
            # Coordinator device gates the whole feature.
            vol.Optional(
                CONF_IS_EGRESS_WINDOW,
                default=DEFAULT_IS_EGRESS_WINDOW,
            ): selector.BooleanSelector(),
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
                selector.EntitySelectorConfig(domain=["fan", "switch"], multiple=True)
            ),
            vol.Optional(CONF_HUMIDITY_FANS, default=[]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["fan", "switch"], multiple=True)
            ),
            # Fan-noise mitigation D1: per-room adjacency for the
            # Layer-1 BLE corroboration ladder. Rooms whose BLE
            # presence should be treated as "probably the same person
            # drifting" for fan-interference purposes (example:
            # bathroom <-> adjacent bedroom). Empty list is safe: L2
            # of the ladder simply does not fire and L1 + L3 still
            # work. Stored as a list of OTHER room config entry_ids.
            vol.Optional(CONF_ADJACENT_ROOMS, default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {
                            "label": e.data.get(CONF_ROOM_NAME, e.title),
                            "value": e.entry_id,
                        }
                        for e in self._get_all_room_entries()
                    ],
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            # Fan-noise Mode-2 per-room flags. The master kill switch
            # (CONF_FAN_RECHECK_ENABLED, default OFF) lives on the Presence
            # Coordinator; this trio is per-room. Mode-2 (room-tier fan-
            # pause + clean recheck) only fires when BOTH master AND
            # CONF_ROOM_FAN_RECHECK_ENABLED are True. Per-room defaults
            # are ON (DEFAULT_ROOM_FAN_RECHECK_ENABLED, DEFAULT_FAN_RECHECK_L2_ALLOWED,
            # DEFAULT_FAN_RECHECK_TRUST_SENSORS_OK all True) — opt-in still
            # gated by the master kill switch staying OFF until validated.
            vol.Optional(
                CONF_ROOM_FAN_RECHECK_ENABLED,
                default=DEFAULT_ROOM_FAN_RECHECK_ENABLED,
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_FAN_RECHECK_L2_ALLOWED,
                default=DEFAULT_FAN_RECHECK_L2_ALLOWED,
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_FAN_RECHECK_TRUST_SENSORS_OK,
                default=DEFAULT_FAN_RECHECK_TRUST_SENSORS_OK,
            ): selector.BooleanSelector(),
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
            # v4.5.9: HVAC solar-gain cover management opt-out (default ON)
            vol.Optional(CONF_COVER_HVAC_MANAGED, default=True): selector.BooleanSelector(),
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
        v3.20.1: Routes to init_automation_chaining instead of climate.
        """
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_init_automation_chaining()

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

    # =========================================================================
    # v3.20.1 D1: AUTOMATION CHAINING IN INITIAL ROOM SETUP
    # =========================================================================

    async def async_step_init_automation_chaining(self, user_input=None):
        """Automation chaining during initial room setup: choose trigger group."""
        return self.async_show_menu(
            step_id="init_automation_chaining",
            menu_options=[
                "init_chain_occupancy",
                "init_chain_light",
                "init_chain_house_state",
                "init_chain_coordinator",
                "init_chain_skip",
            ],
        )

    async def async_step_init_chain_skip(self, user_input=None):
        """Skip automation chaining and proceed to AI rules."""
        return await self.async_step_init_ai_rules()

    async def async_step_init_chain_occupancy(self, user_input=None):
        """Configure occupancy trigger automations during initial setup."""
        return await self._init_chain_trigger_step(
            "init_chain_occupancy", CHAIN_GROUP_OCCUPANCY, user_input,
        )

    async def async_step_init_chain_light(self, user_input=None):
        """Configure light level trigger automations during initial setup."""
        return await self._init_chain_trigger_step(
            "init_chain_light", CHAIN_GROUP_LIGHT, user_input,
        )

    async def async_step_init_chain_house_state(self, user_input=None):
        """Configure house state trigger automations during initial setup."""
        return await self._init_chain_trigger_step(
            "init_chain_house_state", CHAIN_GROUP_HOUSE_STATE, user_input,
        )

    async def async_step_init_chain_coordinator(self, user_input=None):
        """Configure coordinator signal trigger automations during initial setup."""
        return await self._init_chain_trigger_step(
            "init_chain_coordinator", CHAIN_GROUP_COORDINATOR, user_input,
        )

    async def _init_chain_trigger_step(
        self, step_id: str, triggers: list[str], user_input,
    ):
        """Shared handler for chain trigger sub-steps during initial setup.

        v3.20.1: Mirrors options flow _chain_trigger_step but stores in self._data.
        """
        if user_input is not None:
            # Merge with existing chains already set during this flow
            existing = self._data.get(CONF_AUTOMATION_CHAINS, {})
            updated = dict(existing)
            for trigger in triggers:
                key = f"chain_{trigger}"
                val = user_input.get(key, "")
                if val:
                    updated[trigger] = val
                else:
                    updated.pop(trigger, None)
            self._data[CONF_AUTOMATION_CHAINS] = updated
            # Return to chaining menu for more groups or skip
            return await self.async_step_init_automation_chaining()

        # Build automation entity dropdown options
        automation_entities = sorted(
            eid for eid in self.hass.states.async_entity_ids("automation")
        )
        options = [{"value": "", "label": "(none)"}]
        for eid in automation_entities:
            state = self.hass.states.get(eid)
            label = state.attributes.get("friendly_name", eid) if state else eid
            options.append({"value": eid, "label": label})

        current = self._data.get(CONF_AUTOMATION_CHAINS, {})

        data_schema = vol.Schema({
            vol.Optional(
                f"chain_{trigger}",
                default=current.get(trigger, ""),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
            for trigger in triggers
        })

        return self.async_show_form(
            step_id=step_id,
            data_schema=data_schema,
        )

    # =========================================================================
    # v3.20.1 D2: AI RULES IN INITIAL ROOM SETUP
    # =========================================================================

    async def async_step_init_ai_rules(self, user_input=None):
        """AI Rules menu during initial room setup: Add Rule / Skip."""
        return self.async_show_menu(
            step_id="init_ai_rules",
            menu_options=[
                "init_ai_rule_add",
                "init_ai_rules_skip",
            ],
        )

    async def async_step_init_ai_rules_skip(self, user_input=None):
        """Skip AI rules and proceed to climate."""
        return await self.async_step_climate()

    async def async_step_init_ai_rule_add(self, user_input=None):
        """Add a new AI rule during initial room setup.

        v3.20.1 D2 REVIEW FIX: Calls _parse_rule_with_ai() inline
        instead of using needs_parsing flag. If ai_task is unavailable,
        the rule is stored with empty actions and needs_parsing=True as fallback.
        """
        errors = {}

        if user_input is not None:
            trigger_type = user_input.get(CONF_AI_RULE_TRIGGER, "enter")
            person = user_input.get(CONF_AI_RULE_PERSON, "").strip()
            description = user_input.get(CONF_AI_RULE_DESCRIPTION, "").strip()

            if not description:
                errors["base"] = "ai_rule_empty_description"
            else:
                # v3.20.1 D2 REVIEW FIX: Try inline AI parsing first
                actions = None
                needs_parsing = False
                try:
                    actions = await self._parse_rule_with_ai_init(
                        description, trigger_type, person,
                    )
                except Exception:
                    _LOGGER.warning(
                        "ai_task unavailable during initial setup, deferring parse"
                    )

                if actions is not None:
                    # Validate parsed actions
                    valid, validation_errors = self._validate_parsed_actions_init(actions)
                    if not valid:
                        _LOGGER.warning(
                            "AI rule validation errors: %s", validation_errors,
                        )
                        errors["base"] = "ai_rule_validation_failed"
                    else:
                        from homeassistant.util import dt as dt_util
                        rule = {
                            "rule_id": uuid.uuid4().hex[:8],
                            "trigger_type": trigger_type,
                            "person": person,
                            "description": description,
                            "actions": actions,
                            "enabled": True,
                            "created_at": dt_util.utcnow().isoformat(),
                        }
                        existing_rules = list(self._data.get(CONF_AI_RULES, []))
                        existing_rules.append(rule)
                        self._data[CONF_AI_RULES] = existing_rules
                        return await self.async_step_init_ai_rules()
                elif "base" not in errors:
                    # ai_task not available — store with deferred parsing as fallback
                    rule = {
                        "rule_id": uuid.uuid4().hex[:8],
                        "trigger_type": trigger_type,
                        "person": person,
                        "description": description,
                        "actions": [],
                        "enabled": True,
                        "needs_parsing": True,
                    }
                    existing_rules = list(self._data.get(CONF_AI_RULES, []))
                    existing_rules.append(rule)
                    self._data[CONF_AI_RULES] = existing_rules
                    return await self.async_step_init_ai_rules()

        # Build trigger dropdown options with human-readable labels
        trigger_labels = {
            "enter": "Room Enter",
            "exit": "Room Exit",
            "lux_dark": "Room Gets Dark",
            "lux_bright": "Room Gets Bright",
            "house_state_away": "House Away",
            "house_state_arriving": "House Arriving",
            "house_state_home_day": "House Home Day",
            "house_state_home_evening": "House Home Evening",
            "house_state_home_night": "House Home Night",
            "house_state_sleep": "House Sleep",
            "house_state_waking": "House Waking",
            "house_state_guest": "House Guest",
            "house_state_vacation": "House Vacation",
            "energy_constraint": "Energy Constraint Change",
            "safety_hazard": "Safety Hazard Detected",
            "security_event": "Security Event",
        }
        trigger_options = [
            {"value": t, "label": trigger_labels.get(t, t)}
            for t in AI_RULE_TRIGGER_OPTIONS
        ]

        data_schema = vol.Schema({
            vol.Required(CONF_AI_RULE_TRIGGER, default="enter"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=trigger_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            # v3.20.1 D5: EntitySelector for person domain
            vol.Optional(CONF_AI_RULE_PERSON, default=vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="person")
            ),
            vol.Required(CONF_AI_RULE_DESCRIPTION, default=""): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.TEXT,
                    multiline=True,
                )
            ),
        })

        return self.async_show_form(
            step_id="init_ai_rule_add",
            data_schema=data_schema,
            errors=errors,
        )

    async def _parse_rule_with_ai_init(
        self,
        description: str,
        trigger_type: str,
        person: str,
    ) -> list[dict] | None:
        """Parse NL description via ai_task during initial setup.

        v3.20.1: Adapted from OptionsFlow._parse_rule_with_ai.
        Uses self._data instead of self._config_entry.
        """
        room_name = self._data.get(CONF_ROOM_NAME, "this room")
        room_entities = self._get_room_entities_for_prompt_init()

        trigger_label = {
            "enter": f"{person or 'someone'} enters the room",
            "exit": f"{person or 'someone'} leaves the room",
            "lux_dark": "the room gets dark",
            "lux_bright": "the room gets bright",
            "house_state_away": "the house transitions to Away",
            "house_state_arriving": "someone is arriving home",
            "house_state_home_day": "the house enters Home Day mode",
            "house_state_home_evening": "the house enters Home Evening mode",
            "house_state_home_night": "the house enters Home Night mode",
            "house_state_sleep": "the house enters Sleep mode",
            "house_state_waking": "the house enters Waking mode",
            "house_state_guest": "the house enters Guest mode",
            "house_state_vacation": "the house enters Vacation mode",
            "energy_constraint": "the energy constraint changes (peak, shed, coast)",
            "safety_hazard": "a safety hazard is detected (smoke, CO, water leak)",
            "security_event": "a security event occurs (entry alert, unknown person)",
        }.get(trigger_type, trigger_type)

        prompt = AI_RULE_PARSING_PROMPT.format(
            room_name=room_name,
            trigger_label=trigger_label,
            description=description,
            entities_json=json.dumps(room_entities, indent=2),
        )

        structure = {
            "actions": {
                "selector": {"object": {"multiple": True}},
                "description": (
                    "List of HA service calls. Each must have: "
                    "domain (string), service (string), "
                    "target (object with entity_id string or list), "
                    "data (object, may be empty {}). "
                    "Use color_temp_kelvin not color_temp. "
                    "Use brightness_pct (0-100) not brightness."
                ),
            }
        }

        result = await self.hass.services.async_call(
            "ai_task", "generate_data",
            {
                "task_name": "ura_parse_room_rule",
                "instructions": prompt,
                "structure": structure,
            },
            blocking=True,
            return_response=True,
        )

        if not result or not isinstance(result, dict):
            return None

        actions = result.get("data", {}).get("actions") if isinstance(result.get("data"), dict) else None
        if actions is None:
            actions = result.get("actions")
        if not isinstance(actions, list) or not actions:
            return None

        return actions

    def _get_room_entities_for_prompt_init(self) -> list[dict]:
        """Build entity list for AI context from initial setup data.

        v3.20.1: Adapted from OptionsFlow._get_room_entities_for_prompt.
        Uses self._data instead of self._config_entry.
        """
        entities = []
        seen = set()

        def add(entity_id: str) -> None:
            if entity_id in seen:
                return
            state = self.hass.states.get(entity_id)
            if not state:
                return
            seen.add(entity_id)
            entities.append({
                "entity_id": entity_id,
                "name": state.attributes.get("friendly_name", entity_id),
                "domain": entity_id.split(".")[0],
            })

        # Explicitly configured devices from self._data
        for key in (CONF_LIGHTS, CONF_FANS, CONF_AUTO_DEVICES, CONF_MANUAL_DEVICES,
                    CONF_COVERS, CONF_AUTO_SWITCHES, CONF_MANUAL_SWITCHES):
            for eid in self._data.get(key, []) or []:
                add(eid)

        if climate := self._data.get(CONF_CLIMATE_ENTITY):
            add(climate)

        # All entities in the room's HA area
        area_id = self._data.get(CONF_AREA_ID)
        if area_id:
            ent_reg = er.async_get(self.hass)
            for entity in ent_reg.entities.values():
                if entity.area_id == area_id and not entity.disabled:
                    add(entity.entity_id)

        return entities

    # v3.20.1: Domain allowlist for AI rule service calls (shared with OptionsFlow).
    _AI_RULE_ALLOWED_DOMAINS: set = {
        "light", "switch", "fan", "cover", "climate", "media_player",
        "lock", "scene", "automation", "input_boolean", "input_number",
        "input_select", "input_text", "number", "select", "button",
        "humidifier", "vacuum", "water_heater", "valve",
    }

    def _validate_parsed_actions_init(self, actions: list[dict]) -> tuple[bool, list[str]]:
        """Validate AI-parsed actions during initial setup.

        v3.20.1: Adapted from OptionsFlow._validate_parsed_actions.
        """
        errors = []
        for i, action in enumerate(actions):
            label = f"Action {i + 1}"
            if not isinstance(action, dict):
                errors.append(f"{label}: must be an object, got {type(action).__name__}")
                continue
            for key in ("domain", "service", "target"):
                if key not in action:
                    errors.append(f"{label}: missing '{key}'")
            domain = action.get("domain", "")
            if domain and domain not in self._AI_RULE_ALLOWED_DOMAINS:
                errors.append(f"{label}: domain '{domain}' is not allowed")
            target = action.get("target", {})
            if not isinstance(target, dict):
                errors.append(f"{label}: 'target' must be an object")
                target = {}
            entity_id = target.get("entity_id")
            if entity_id:
                eids = entity_id if isinstance(entity_id, list) else [entity_id]
                for eid in eids:
                    if not self.hass.states.get(eid):
                        errors.append(f"{label}: entity '{eid}' not found")
            if "data" in action and not isinstance(action["data"], dict):
                errors.append(f"{label}: 'data' must be an object")
        return len(errors) == 0, errors

    async def async_step_climate(self, user_input=None):
        """Handle "Climate & Fans" configuration (D7 rename).

        Fans-first information hierarchy (D5/D7/D8):
          1. Toggle #1 (HVAC-managed) / #2 (comfort) / #3 (humidity) + wet_room
          2. Humidity-fan controls (threshold, timeout, max-runtime)
          3. Presence-runtime triplet
          4. Collapsed advanced spike-baseline section
          5. Comfort-range pair + climate-entity fallback (DEMOTED to bottom)
        """
        section = _ha_section
        errors: dict[str, str] = {}
        if user_input is not None:
            # Flatten the collapsed advanced section back into top-level keys
            # so consumers read the same shape they always did.
            advanced = user_input.pop("humidity_fan_advanced", None)
            if isinstance(advanced, dict):
                user_input.update(advanced)
            climate_group = user_input.pop("climate_backstop", None)
            if isinstance(climate_group, dict):
                user_input.update(climate_group)
            # D5/D8 cross-field validation
            err = _validate_climate_fans_form(user_input)
            if err:
                errors["base"] = err
            else:
                # D4 default cascade: bathroom rooms get wet_room=True unless
                # operator explicitly overrode it.
                room_type = self._data.get(CONF_ROOM_TYPE)
                if (
                    CONF_WET_ROOM not in user_input
                    and room_type == ROOM_TYPE_BATHROOM
                ):
                    user_input[CONF_WET_ROOM] = True
                self._data.update(user_input)
                if user_input.get(CONF_FAN_CONTROL_ENABLED):
                    return await self.async_step_fan_speeds()
                return await self.async_step_sleep_protection()

        area_id = self._data.get(CONF_AREA_ID)
        area_climate = self._get_area_entities(area_id, "climate") if area_id else []
        room_type = self._data.get(CONF_ROOM_TYPE)
        wet_default = (room_type == ROOM_TYPE_BATHROOM)

        data_schema = vol.Schema({
            # --- Fans first ---
            vol.Optional(CONF_HVAC_COORDINATION_ENABLED, default=False): selector.BooleanSelector(),
            vol.Optional(CONF_FAN_CONTROL_ENABLED, default=False): selector.BooleanSelector(),
            # Comfort-fan house-AWAY veto (mmwave-corroboration Tier-3 D3).
            # Default ON — suppresses comfort-fan turn_on when house is
            # AWAY/VACATION and the room lacks trusted presence
            # (mmwave excluded). See const.py CONF_COMFORT_FAN_AWAY_VETO_ENABLED.
            vol.Optional(
                CONF_COMFORT_FAN_AWAY_VETO_ENABLED,
                default=DEFAULT_COMFORT_FAN_AWAY_VETO_ENABLED,
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_HUMIDITY_FAN_CONTROL_ENABLED,
                default=DEFAULT_HUMIDITY_FAN_CONTROL_ENABLED,
            ): selector.BooleanSelector(),
            vol.Optional(CONF_WET_ROOM, default=wet_default): selector.BooleanSelector(),
            vol.Optional(
                CONF_HUMIDITY_FAN_SPIKE_ENABLED, default=wet_default,
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED, default=wet_default,
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S,
                default=DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=600, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S,
                default=DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=300, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S,
                default=DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=3600, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_FAN_TEMP_THRESHOLD, default=DEFAULT_FAN_TEMP_THRESHOLD): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=100, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_HUMIDITY_FAN_THRESHOLD, default=DEFAULT_HUMIDITY_THRESHOLD): selector.NumberSelector(
                selector.NumberSelectorConfig(min=30, max=80, unit_of_measurement="%", mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Optional(CONF_HUMIDITY_FAN_TIMEOUT, default=DEFAULT_HUMIDITY_FAN_TIMEOUT): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=3600, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_HUMIDITY_FAN_MAX_RUNTIME, default=DEFAULT_HUMIDITY_FAN_MAX_RUNTIME): selector.NumberSelector(
                selector.NumberSelectorConfig(min=600, max=14400, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional("humidity_fan_advanced"): section(
                vol.Schema({
                    vol.Optional(
                        CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT,
                        default=DEFAULT_HUMIDITY_FAN_SPIKE_DELTA_PCT,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=3, max=30, unit_of_measurement="%", mode=selector.NumberSelectorMode.BOX)
                    ),
                    vol.Optional(
                        CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S,
                        default=DEFAULT_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=300, max=14400, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
                    ),
                    vol.Optional(
                        CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE,
                        default=DEFAULT_HUMIDITY_FAN_SPIKE_BASELINE_MODE,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"label": "EMA (adaptive average)", "value": HUMIDITY_FAN_SPIKE_MODE_EMA},
                                {"label": "Window minimum", "value": HUMIDITY_FAN_SPIKE_MODE_WINDOW_MIN},
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }),
                {"collapsed": True},
            ),
            # --- Climate backstop LAST (D8 demote) ---
            vol.Optional("climate_backstop"): section(
                vol.Schema({
                    vol.Optional(CONF_TARGET_TEMP_HEAT, default=DEFAULT_TARGET_TEMP_HEAT): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=60, max=90, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
                    ),
                    vol.Optional(CONF_TARGET_TEMP_COOL, default=DEFAULT_TARGET_TEMP_COOL): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=60, max=90, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
                    ),
                    vol.Optional(
                        CONF_CLIMATE_ENTITY,
                        default=area_climate[0] if area_climate else vol.UNDEFINED,
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="climate")
                    ),
                }),
                {"collapsed": False},
            ),
        })

        return self.async_show_form(
            step_id="climate",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"name": "Configure fans, then climate backstop"},
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
            vol.Optional(
                CONF_FAN_SLEEP_POLICY,
                default=DEFAULT_FAN_SLEEP_POLICY
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"label": "Turn off fans during sleep", "value": "off"},
                        {"label": "Reduce fan speed (low only)", "value": "reduce"},
                        {"label": "Normal fan operation", "value": "normal"},
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
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
            vol.Optional(CONF_ENERGY_SENSORS, default=area_energy or vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
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
        self._pending_delete_rule_id = None  # v3.12.0 M3: AI rule deletion tracking

    def _get_current(self, key, default=None):
        """Get current value from options with data fallback."""
        return self._config_entry.options.get(
            key, self._config_entry.data.get(key, default)
        )

    def _get_energy_sensors_default(self):
        """Get energy sensors default, migrating from singular to plural.

        v4.1.0: CONF_ENERGY_SENSORS (plural) replaces CONF_ENERGY_SENSOR.
        If only the old singular key exists, wrap its value in a list.
        """
        return self._get_multi_sensor_default(CONF_ENERGY_SENSORS, CONF_ENERGY_SENSOR)

    def _get_multi_sensor_default(self, plural_key, singular_key):
        """Get sensor list default, migrating singular → plural if needed.

        v4.1.0: Generic helper for upgrading single-sensor config keys
        to multi-sensor. Used for energy sensors and whole-house sensors.
        """
        # Try new plural key first
        plural = self._get_current(plural_key)
        if plural is not None:
            return plural if plural else vol.UNDEFINED

        # Fall back to old singular key and wrap in list
        singular = self._get_current(singular_key)
        if singular:
            return [singular]

        return vol.UNDEFINED
    
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

    def _find_zone_manager_entry(self):
        """Find the Zone Manager entry if one exists.

        v3.18.2: Added to OptionsFlow (was only on ConfigFlow).
        Needed by async_step_climate for zone thermostat auto-populate.
        """
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
                return entry
        return None

    # =====================================================================
    # v4.7.5 — Option C auto-mirror helpers (see PLANNING_v4.7.5 §D4)
    # =====================================================================

    def _get_shared_thermostat_siblings(
        self,
        zm_entry,
        zone_name: str,
    ) -> list[str]:
        """Return list of OTHER house-zone names that share zone_name's thermostat.

        v4.7.5 D4: Empty list when zone_name has no thermostat OR no siblings
        share it. Used by every zone editor to drive Option C auto-mirror, and
        by `async_step_zone_config_menu` to render the shared-thermostat banner.

        Reads RAW zones from `entry.options["zones"]` — never calls
        `iter_canonical_hvac_zones`. Per Lazy Canonical Resolution (Bug Class
        #46 mirror): UI surfaces compute sibling sets locally; the HVAC
        coordinator's thermostat-keyed merge stays runtime-only.
        """
        try:
            merged = {**zm_entry.data, **zm_entry.options}
            zones = merged.get("zones", {}) or {}
            target_thermostat = zones.get(zone_name, {}).get(
                CONF_ZONE_THERMOSTAT
            )
            if not target_thermostat:
                return []
            return [
                name
                for name, cfg in zones.items()
                if name != zone_name
                and cfg.get(CONF_ZONE_THERMOSTAT) == target_thermostat
            ]
        except Exception:  # noqa: BLE001 — siblings discovery is best-effort
            _LOGGER.debug(
                "v4.7.5 sibling lookup failed for zone=%s",
                zone_name, exc_info=True,
            )
            return []

    def _auto_mirror_to_siblings(
        self,
        zm_entry,
        saved_zone_name: str,
        saved_zone_data: dict,
        mirror_keys,
        *,
        old_thermostat: str | None = None,
        rename_from: str | None = None,
    ) -> list[str]:
        """v4.7.5 D4 Option C: mirror mirror_keys into shared-thermostat siblings.

        v4.7.5 post-review note (sync vs async): This helper is synchronous
        (`def`, not `async def`) because `async_update_entry` is itself sync
        despite the `async_` prefix. Callers MUST NOT prefix the invocation
        with `await` — doing so raises TypeError on a bool. See Reviewer B M1.

        Caller has constructed `saved_zone_data` for `saved_zone_name` and the
        helper folds the save + the sibling mirrors into a SINGLE
        `async_update_entry` call so the update_listener fires exactly once
        per user save. **The helper itself calls `async_update_entry`** — the
        caller MUST NOT call it separately before invoking the helper.

        Returns the list of sibling zone names that were mirrored to (for
        log + description_placeholder cue on the next render). Returns an empty
        list when mirror_keys is empty (per-house-zone fields like rooms or
        media) OR when zone has no thermostat OR has no siblings.

        `rename_from` (v4.7.5 post-review H1 fix): for `async_step_zone_rooms`
        (which renames the zone key), pass the OLD zone name. The helper pops
        the old key before writing the new one — keeping the rename atomic
        with the save in a single `async_update_entry` call.

        Unlink path (PLANNING_v4.7.5 §D4 "unlink" edge case):
            If `old_thermostat` differs from the new thermostat in
            `saved_zone_data`, the OLD sibling group is also mirrored to once
            (so they get the final pre-unlink state); the NEW sibling group is
            mirrored to going forward. Both groups are written within the SAME
            async_update_entry call (atomic — no double update_listener fire).

            **Reviewer B post-review safety check (M3):** Callers MUST NOT
            `await` any unrelated work between this call and returning a
            menu/form render — the scheduled reload task may begin at the next
            event-loop iteration and the rendered state should reflect the
            user's save.

        Bug Class #46 safety: this helper runs from options-flow handlers,
        AFTER bootstrap-2 has closed. Per QUALITY_CONTEXT.md Bug Class #46
        §"When async_update_entry IS safe" condition 2, options-flow callers
        are explicitly safe.
        """
        # v4.7.5 post-review (Reviewer B H3 sub-issue): if a thermostat
        # reassignment is in flight but the mirror_keys set doesn't carry
        # CONF_ZONE_THERMOSTAT, the unlink mirror won't be persisted to old
        # siblings via the saved_zone_data payload — warn loudly so future
        # contributors notice.
        if (
            old_thermostat
            and mirror_keys
            and CONF_ZONE_THERMOSTAT not in mirror_keys
            and saved_zone_data.get(CONF_ZONE_THERMOSTAT) != old_thermostat
        ):
            _LOGGER.warning(
                "v4.7.5: thermostat reassignment without CONF_ZONE_THERMOSTAT "
                "in mirror_keys — unlink semantics may be incomplete. "
                "saved_zone=%s mirror_keys=%s",
                saved_zone_name, sorted(mirror_keys),
            )

        merged = {**zm_entry.data, **zm_entry.options}
        # Deep copy zone dicts so we never mutate entry.options/data in place
        # (Bug Class #7 stale data source + async_update_entry no-op skip).
        zones = {k: dict(v) for k, v in merged.get("zones", {}).items()}

        # Rename support (H1 fix): pop old key BEFORE writing new key so the
        # saved zone lands at its renamed location.
        if rename_from and rename_from != saved_zone_name and rename_from in zones:
            zones[saved_zone_name] = zones.pop(rename_from)

        # 1. Persist the saved zone's own data (mirrors the per-step pattern
        # the editor steps already use; this helper centralises the write).
        zones.setdefault(saved_zone_name, {})
        zones[saved_zone_name].update(saved_zone_data)

        # 2. Compute new-thermostat sibling set from the saved zone's NEW
        # thermostat value (post-update). Use the freshly-written zones dict.
        new_thermostat = zones[saved_zone_name].get(CONF_ZONE_THERMOSTAT)

        def _siblings_for(t: str | None) -> list[str]:
            if not t:
                return []
            return [
                name
                for name, cfg in zones.items()
                if name != saved_zone_name and cfg.get(CONF_ZONE_THERMOSTAT) == t
            ]

        new_siblings = _siblings_for(new_thermostat) if mirror_keys else []

        # 3. Unlink: if old_thermostat differs, mirror to OLD siblings too
        # (one final write so old siblings reflect any intermediate-edit state
        # before the relationship breaks).
        old_siblings: list[str] = []
        if (
            mirror_keys
            and old_thermostat
            and old_thermostat != new_thermostat
        ):
            old_siblings = _siblings_for(old_thermostat)

        # 4. Build mirror payload: only the keys present in BOTH saved_zone_data
        # AND mirror_keys. Missing keys are tolerated (e.g., user didn't change
        # the bucket cells but did change the master toggle).
        mirror_payload = {
            k: saved_zone_data[k]
            for k in mirror_keys
            if k in saved_zone_data
        }

        all_mirrored: list[str] = []
        if mirror_payload:
            for sib in new_siblings:
                zones.setdefault(sib, {}).update(mirror_payload)
                all_mirrored.append(sib)
            for sib in old_siblings:
                # Old siblings that are NOT also in new_siblings (the unlink
                # case proper). If a zone is in both lists — e.g., thermostat
                # didn't actually move — we already wrote it above.
                if sib in new_siblings:
                    continue
                zones.setdefault(sib, {}).update(mirror_payload)
                all_mirrored.append(sib)

        # 5. ONE atomic async_update_entry: save + mirror in a single write.
        # update_listener fires exactly once (Reviewer B assertion).
        self.hass.config_entries.async_update_entry(
            zm_entry,
            options={**zm_entry.options, "zones": zones},
        )

        if all_mirrored:
            if old_siblings:
                _LOGGER.info(
                    "v4.7.5 unlink: zone=%s old_thermostat=%s new_thermostat=%s "
                    "mirrored_to_old=%s mirrored_to_new=%s mirror_keys=%s",
                    saved_zone_name, old_thermostat, new_thermostat,
                    old_siblings, new_siblings, sorted(mirror_payload.keys()),
                )
            else:
                _LOGGER.info(
                    "v4.7.5 auto-mirror: saved zone=%s thermostat=%s "
                    "mirror_keys=%s siblings=%s",
                    saved_zone_name, new_thermostat,
                    sorted(mirror_payload.keys()), new_siblings,
                )
        return all_mirrored

    def _get_zm_zone_data(self) -> tuple | None:
        """Get zone data from Zone Manager entry by _selected_zone_name.

        v3.6.0-c2.3: Zones migrated from separate entries to ZM entry's zones dict.
        Returns (zm_entry, zone_name, zone_data) or None.

        v4.7.5 D4 note: every editor step that calls this helper and writes
        shared-thermostat-tied fields MUST call _auto_mirror_to_siblings with
        the appropriate MIRROR_KEYS_* set. See PLANNING_v4.7.5 §D4 table.
        Per-house-zone fields (rooms, media, persons, cameras) MUST use the
        empty MIRROR_KEYS_* set so they DON'T mirror.
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
            # v3.22.0: signal_responses added for cross-coordinator signal config
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
                    # NM Cycle A-2 — rung-2 knobs for Cycle-A noise reduction.
                    "coordinator_notifications_volume",
                    # NM Cycle C-2 (2026-07-22) — per-person routing matrix,
                    # hazard overrides, DND-bypass, mute-default duration,
                    # and additive-only life-safety hazard extras.
                    "coordinator_notifications_routing",
                    "signal_responses",
                    # v4.7.34 Phase 1 D7: Optimization Coordinator options section
                    "coordinator_optimization",
                    # v5.21.0 fix-up (operator scope change 2026-07-17):
                    # BAEC folded INTO `coordinator_energy` as sibling sections
                    # of INCLEMENT_ADVANCED / cloud_verification (see the
                    # `baec` + `baec_advanced` sections in
                    # async_step_coordinator_energy). Standalone menu entry
                    # + async_step_coordinator_baec retired.
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
                    "options_lighting",   # v3.20.1 D3: split from automation_behavior
                    "options_covers",     # v3.20.1 D3: split from automation_behavior
                    "automation_chaining",  # v3.10.0
                    "ai_rules",  # v3.12.0: M3 AI NL Rules
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
        """Reconfigure energy sensors for predictions and tracking (integration level).

        v4.2.0: Removed 6 dead fields (grid_import, solar_export, battery_level,
        delivery_rate, export_reimbursement_rate). These were configured but never
        read — superseded by Envoy auto-derivation on CM or TOU rate files.
        """
        if user_input is not None:
            try:
                merged = {**self._config_entry.options, **user_input}
                _LOGGER.debug("energy_sensors save: entry_id=%s, merged_keys=%d",
                              self._config_entry.entry_id, len(merged))
                return self.async_create_entry(title="", data=merged)
            except Exception:
                _LOGGER.exception("energy_sensors save FAILED")
                raise

        data_schema = vol.Schema({
            vol.Optional(
                CONF_WHOLE_HOUSE_POWER_SENSORS,
                default=self._get_multi_sensor_default(
                    CONF_WHOLE_HOUSE_POWER_SENSORS, CONF_WHOLE_HOUSE_POWER_SENSOR)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
            ),
            vol.Optional(
                CONF_WHOLE_HOUSE_ENERGY_SENSORS,
                default=self._get_multi_sensor_default(
                    CONF_WHOLE_HOUSE_ENERGY_SENSORS, CONF_WHOLE_HOUSE_ENERGY_SENSOR)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
            ),
            vol.Optional(
                CONF_HOUSE_DEVICE_POWER_SENSORS,
                default=self._get_current(CONF_HOUSE_DEVICE_POWER_SENSORS, []) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
            ),
            vol.Optional(
                CONF_HOUSE_DEVICE_ENERGY_SENSORS,
                default=self._get_current(CONF_HOUSE_DEVICE_ENERGY_SENSORS, []) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
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
            # v3.10.1: Enhanced census v2
            vol.Optional(
                CONF_ENHANCED_CENSUS,
                default=self._get_current(CONF_ENHANCED_CENSUS, True),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_GUEST_VLAN_SSID,
                default=self._get_current(CONF_GUEST_VLAN_SSID, DEFAULT_GUEST_VLAN_SSID),
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Optional(
                CONF_CENSUS_HOLD_INTERIOR,
                default=self._get_current(
                    CONF_CENSUS_HOLD_INTERIOR, DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=60, step=1, unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            # H3 (2026-07-13): BLE-cancel kill switch. Default True
            # preserves current behavior; when False the per-area BLE
            # subtraction (Step 3 in _get_unrecognized_camera_count) is
            # skipped byte-identically to the pre-BLE-cancel behavior.
            vol.Optional(
                CONF_CENSUS_BLE_CANCEL_ENABLED,
                default=self._get_current(
                    CONF_CENSUS_BLE_CANCEL_ENABLED,
                    DEFAULT_CENSUS_BLE_CANCEL_ENABLED,
                ),
            ): selector.BooleanSelector(),
            # 2026-08-01 census fusion policy: divergence-aware downgrade.
            # Default True (min-wins on uncorroborated divergence → DISAGREE).
            # False = fire-axe restore to pre-cycle max-wins CLOSE behavior.
            vol.Optional(
                CONF_CENSUS_DIVERGENCE_DOWNGRADE,
                default=self._get_current(
                    CONF_CENSUS_DIVERGENCE_DOWNGRADE,
                    DEFAULT_CENSUS_DIVERGENCE_DOWNGRADE,
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_CENSUS_HOLD_EXTERIOR,
                default=self._get_current(
                    CONF_CENSUS_HOLD_EXTERIOR, DEFAULT_CENSUS_HOLD_EXTERIOR_MINUTES
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=30, step=1, unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
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
            # Exterior-person snapshot delay (D4). Delays the notification
            # dispatch on the LIVE fallback path so entity_picture is closer
            # to the detection moment. Ignored when a Frigate event_id
            # snapshot is available. 0 = no delay.
            vol.Optional(
                CONF_EXTERIOR_SNAPSHOT_OFFSET_S,
                default=self._get_current(
                    CONF_EXTERIOR_SNAPSHOT_OFFSET_S,
                    DEFAULT_EXTERIOR_SNAPSHOT_OFFSET_S,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_EXTERIOR_SNAPSHOT_OFFSET_S,
                    max=MAX_EXTERIOR_SNAPSHOT_OFFSET_S,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
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
        v4.6.2.2: Guest mode false-positive hardening knobs.
        Fan-noise Mode-2: master kill switch + 7 timing knobs for the
        room-tier fan-pause + clean recheck mechanism. Default OFF.
        Settings stored in CM entry options, read by __init__.py during
        coordinator setup.
        """
        from .const import (
            CONF_SLEEP_START_HOUR,
            CONF_SLEEP_END_HOUR,
            CONF_GEOFENCE_ENTITIES,
            DEFAULT_SLEEP_START_HOUR,
            DEFAULT_SLEEP_END_HOUR,
            CONF_GUEST_MODE_PERSISTENCE_SECONDS,
            CONF_GUEST_MODE_REQUIRE_CONFIDENCE,
            DEFAULT_GUEST_PERSISTENCE_SECONDS,
            DEFAULT_GUEST_REQUIRE_CONFIDENCE,
            # v5.7.0 WS-A3: LOST-admitted AWAY-veto grace + sleep exemption.
            CONF_LOST_AWAY_GRACE_MIN,
            DEFAULT_LOST_AWAY_GRACE_MIN,
            CONF_LOST_AWAY_SLEEP_EXEMPT,
            DEFAULT_LOST_AWAY_SLEEP_EXEMPT,
            CONF_FAN_RECHECK_ENABLED,
            DEFAULT_FAN_RECHECK_ENABLED,
            CONF_FAN_RECHECK_ARM_DELAY_S,
            DEFAULT_FAN_RECHECK_ARM_DELAY_S,
            CONF_FAN_RECHECK_SPINDOWN_S,
            DEFAULT_FAN_RECHECK_SPINDOWN_S,
            CONF_FAN_RECHECK_WINDOW_S,
            DEFAULT_FAN_RECHECK_WINDOW_S,
            CONF_FAN_RECHECK_COOLDOWN_S,
            DEFAULT_FAN_RECHECK_COOLDOWN_S,
            CONF_FAN_RECHECK_MAX_PER_HOUR,
            DEFAULT_FAN_RECHECK_MAX_PER_HOUR,
            CONF_FAN_RECHECK_HVAC_SUPPRESS_S,
            DEFAULT_FAN_RECHECK_HVAC_SUPPRESS_S,
            CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS,
            DEFAULT_FAN_RECHECK_MMWAVE_HISTORY_TICKS,
            DOMAIN,
        )

        # 7 fan-recheck timing knobs are wrapped in a collapsed "Advanced"
        # section below — hidden by default. HA's `section()` helper nests
        # the contained keys under a section key in `user_input`. Flatten
        # them back to top-level so the persisted entry.options keeps the
        # SAME shape as before (FanRecheckManager._timing_config reads
        # top-level CONF_FAN_RECHECK_*_S keys from CM entry.options).
        from homeassistant.data_entry_flow import section

        if user_input is not None:
            # Mirror the master flag into hass.data so FanRecheckManager
            # picks it up immediately without waiting for a reload.
            try:
                if CONF_FAN_RECHECK_ENABLED in user_input:
                    self.hass.data.setdefault(DOMAIN, {})[
                        "fan_recheck_master_enabled"
                    ] = bool(user_input[CONF_FAN_RECHECK_ENABLED])
            except Exception:  # noqa: BLE001 — best-effort mirror
                pass
            # Flatten the collapsed-section nest. The section key matches
            # the vol.Optional key used to wrap the 7 timing fields below
            # ("fan_recheck_advanced"). If the section is missing (operator
            # never expanded it on submit), the existing CM options values
            # are preserved as-is by the {…, **user_input} merge.
            advanced = user_input.pop("fan_recheck_advanced", None)
            if isinstance(advanced, dict):
                user_input = {**user_input, **advanced}
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
            # v4.6.2.2: Guest mode hardening knobs
            vol.Optional(
                CONF_GUEST_MODE_PERSISTENCE_SECONDS,
                default=self._get_current(
                    CONF_GUEST_MODE_PERSISTENCE_SECONDS,
                    DEFAULT_GUEST_PERSISTENCE_SECONDS,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=1800, step=30, unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_GUEST_MODE_REQUIRE_CONFIDENCE,
                default=self._get_current(
                    CONF_GUEST_MODE_REQUIRE_CONFIDENCE,
                    DEFAULT_GUEST_REQUIRE_CONFIDENCE,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["low", "medium", "high"],
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            # v5.7.0 WS-A3: LOST-admitted AWAY-veto grace window (minutes).
            # 0 = no grace (fires as soon as path-β denominator clears). The
            # 60-min default protects against transient BLE flap while the
            # phone is intermittently dropping off the scanner.
            vol.Optional(
                CONF_LOST_AWAY_GRACE_MIN,
                default=self._get_current(
                    CONF_LOST_AWAY_GRACE_MIN,
                    DEFAULT_LOST_AWAY_GRACE_MIN,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=240, step=5,
                    unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            # v5.7.0 WS-A3: sleep-exemption switch. When True (default),
            # path β is suppressed during SLEEP/HOME_NIGHT/WAKING regardless
            # of grace — protects a sleeping resident whose phone may die
            # overnight from being marked AWAY in the middle of the night.
            vol.Optional(
                CONF_LOST_AWAY_SLEEP_EXEMPT,
                default=self._get_current(
                    CONF_LOST_AWAY_SLEEP_EXEMPT,
                    DEFAULT_LOST_AWAY_SLEEP_EXEMPT,
                ),
            ): selector.BooleanSelector(),
            # v4.6.3 D10: Anomaly sensitivity
            vol.Optional(
                CONF_PRESENCE_ANOMALY_SENSITIVITY,
                default=self._get_current(
                    CONF_PRESENCE_ANOMALY_SENSITIVITY, DEFAULT_ANOMALY_SENSITIVITY
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "very_quiet", "label": "Very Quiet — only the loudest anomalies get flagged"},
                        {"value": "quiet", "label": "Quiet — fewer notifications, accepts more variability as normal"},
                        {"value": "normal", "label": "Normal — standard sensitivity, recommended for most homes"},
                        {"value": "sensitive", "label": "Sensitive — catches subtler anomalies, more notifications"},
                        {"value": "very_sensitive", "label": "Very Sensitive — flags small deviations; expect frequent advisories"},
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            # Fan-noise Mode-2 (room-tier fan-pause + clean recheck).
            # Master kill switch — default OFF; operator flips ON after
            # live validation. The 7 timing fields are nested inside a
            # COLLAPSED "Advanced (rarely change)" section below to keep
            # the coordinator step parsimonious — operator must expand
            # the section to see / edit them. On submit, the section
            # contents are flattened back to top-level entry.options
            # so FanRecheckManager._timing_config reads the SAME keys
            # it would have read pre-collapse.
            vol.Optional(
                CONF_FAN_RECHECK_ENABLED,
                default=self._get_current(
                    CONF_FAN_RECHECK_ENABLED, DEFAULT_FAN_RECHECK_ENABLED,
                ),
            ): selector.BooleanSelector(),
            vol.Optional("fan_recheck_advanced"): section(
                vol.Schema({
                    vol.Optional(
                        CONF_FAN_RECHECK_ARM_DELAY_S,
                        default=self._get_current(
                            CONF_FAN_RECHECK_ARM_DELAY_S,
                            DEFAULT_FAN_RECHECK_ARM_DELAY_S,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=30, max=300, step=15,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_FAN_RECHECK_SPINDOWN_S,
                        default=self._get_current(
                            CONF_FAN_RECHECK_SPINDOWN_S,
                            DEFAULT_FAN_RECHECK_SPINDOWN_S,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=15, max=90, step=5,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_FAN_RECHECK_WINDOW_S,
                        default=self._get_current(
                            CONF_FAN_RECHECK_WINDOW_S,
                            DEFAULT_FAN_RECHECK_WINDOW_S,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=30, max=180, step=15,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_FAN_RECHECK_COOLDOWN_S,
                        default=self._get_current(
                            CONF_FAN_RECHECK_COOLDOWN_S,
                            DEFAULT_FAN_RECHECK_COOLDOWN_S,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=600, max=7200, step=60,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_FAN_RECHECK_MAX_PER_HOUR,
                        default=self._get_current(
                            CONF_FAN_RECHECK_MAX_PER_HOUR,
                            DEFAULT_FAN_RECHECK_MAX_PER_HOUR,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=4, step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_FAN_RECHECK_HVAC_SUPPRESS_S,
                        default=self._get_current(
                            CONF_FAN_RECHECK_HVAC_SUPPRESS_S,
                            DEFAULT_FAN_RECHECK_HVAC_SUPPRESS_S,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=120, max=1800, step=30,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS,
                        default=self._get_current(
                            CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS,
                            DEFAULT_FAN_RECHECK_MMWAVE_HISTORY_TICKS,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=10, step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }),
                {"collapsed": True},
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
            # v4.6.3 D10: Anomaly sensitivity
            vol.Optional(
                CONF_SAFETY_ANOMALY_SENSITIVITY,
                default=self._get_current(
                    CONF_SAFETY_ANOMALY_SENSITIVITY, DEFAULT_ANOMALY_SENSITIVITY
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "very_quiet", "label": "Very Quiet — only the loudest anomalies get flagged"},
                        {"value": "quiet", "label": "Quiet — fewer notifications, accepts more variability as normal"},
                        {"value": "normal", "label": "Normal — standard sensitivity, recommended for most homes"},
                        {"value": "sensitive", "label": "Sensitive — catches subtler anomalies, more notifications"},
                        {"value": "very_sensitive", "label": "Very Sensitive — flags small deviations; expect frequent advisories"},
                    ],
                    mode=selector.SelectSelectorMode.LIST,
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
        v4.2.29: Validate envoy entity (V0-V4) on submit; reject save if
            user supplied an envoy entity that is missing/malformed/has
            missing critical derived entities.
        """
        from .domain_coordinators.energy_const import (
            CONF_ENERGY_ENVOY_ENTITY,
            CONF_ENERGY_RESERVE_SOC,
            CONF_ENERGY_BILL_CYCLE_DAY,
            CONF_ENERGY_DECISION_INTERVAL,
            CONF_ENERGY_EVSE_A_ENTITY,
            CONF_ENERGY_EVSE_B_ENTITY,
            CONF_ENERGY_EVSE_A_SPAN_BREAKER,
            CONF_ENERGY_EVSE_B_SPAN_BREAKER,
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
            # v3.11.0: Solar forecast entity selectors
            CONF_ENERGY_SOLCAST_TODAY_ENTITY,
            CONF_ENERGY_SOLCAST_REMAINING_ENTITY,
            CONF_ENERGY_SOLCAST_TOMORROW_ENTITY,
            # v3.11.0: Off-peak drain, arbitrage, EVSE management
            CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT,
            CONF_ENERGY_OFFPEAK_DRAIN_GOOD,
            CONF_ENERGY_OFFPEAK_DRAIN_MODERATE,
            CONF_ENERGY_OFFPEAK_DRAIN_POOR,
            DEFAULT_OFFPEAK_DRAIN_EXCELLENT,
            DEFAULT_OFFPEAK_DRAIN_GOOD,
            DEFAULT_OFFPEAK_DRAIN_MODERATE,
            DEFAULT_OFFPEAK_DRAIN_POOR,
            CONF_ENERGY_ARBITRAGE_ENABLED,
            CONF_ENERGY_ARBITRAGE_SOC_TARGET,
            DEFAULT_ARBITRAGE_SOC_TARGET,
            # v4.5.0 D2 / D7: peak buffer target (renamed) + multi-day horizon
            CONF_ENERGY_PEAK_BUFFER_TARGET,
            CONF_ENERGY_SOLCAST_DAY_3_ENTITY,
            CONF_ENERGY_MULTI_DAY_HORIZON_ENABLED,
            DEFAULT_PEAK_BUFFER_TARGET,
            CONF_ENERGY_EXCESS_SOLAR_ENABLED,
            CONF_ENERGY_EXCESS_SOLAR_SOC,
            CONF_ENERGY_EXCESS_SOLAR_KWH,
            DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD,
            DEFAULT_EXCESS_SOLAR_KWH_THRESHOLD,
            # v4.7.6 D3.2: fill-priority SOC threshold
            CONF_ENERGY_FILL_PRIORITY_SOC,
            DEFAULT_FILL_PRIORITY_SOC,
            CONF_ENERGY_GRID_IMPORT_CAP_ENABLED,
            CONF_ENERGY_GRID_IMPORT_CAP_KW,
            DEFAULT_GRID_IMPORT_CAP_KW,
            # v5.5.x cycle: arbitrage grid-import guard (enabled + kW).
            # NO DEFAULT_* imported here — design (c): kW has no default,
            # the form field renders blank, and cross-field validation
            # rejects enabled=True with a missing/blank kW.
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED,
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW,
            CONF_ENERGY_EV_BATTERY_DRAIN_SOC,
            DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD,
            # LKG wave 1 D2 — solar production upper-envelope nameplate.
            CONF_ENERGY_SOLAR_NAMEPLATE_W,
            DEFAULT_ENERGY_SOLAR_NAMEPLATE_W,
            # v4.7.x Cycle A: WeatherProviderManager ranked-list providers
            CONF_ENERGY_WEATHER_FALLBACK_1,
            CONF_ENERGY_WEATHER_FALLBACK_2,
            CONF_WEATHER_STALENESS_MAX_HOURS,
            CONF_WEATHER_DIVERGENCE_THRESHOLD_F,
            DEFAULT_WEATHER_STALENESS_MAX_HOURS,
            DEFAULT_WEATHER_DIVERGENCE_THRESHOLD_F,
            # Inclement-weather reserve cycle: 4 Primary + 3 Advanced knobs
            CONF_INCLEMENT_NWS_ALERTS_ENTITY,
            CONF_INCLEMENT_POWER_THREAT_EVENTS,
            CONF_INCLEMENT_WARN_MIN_SEVERITY,
            CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD,
            CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
            CONF_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT,
            CONF_INCLEMENT_CONDITION_CORROBORATION_MODE,
            DEFAULT_INCLEMENT_POWER_THREAT_EVENTS,
            DEFAULT_INCLEMENT_WARN_MIN_SEVERITY,
            DEFAULT_INCLEMENT_GRID_PRECHARGE_ON_HOLD,
            DEFAULT_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
            DEFAULT_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT,
            DEFAULT_INCLEMENT_CONDITION_CORROBORATION_MODE,
            INCLEMENT_ADVANCED_SECTION,
            # v5.15.x — Envoy write-verification cloud oracles
            CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY,
            CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
            CONF_ENERGY_CLOUD_STORAGE_MODE_ORACLE_ENTITY,
            CONF_ENERGY_CLOUD_BATTERY_SOC_FALLBACK_ENTITY,
            DEFAULT_CLOUD_RESERVE_ORACLE_ENTITY,
            DEFAULT_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
            DEFAULT_CLOUD_STORAGE_MODE_ORACLE_ENTITY,
            DEFAULT_CLOUD_BATTERY_SOC_FALLBACK_ENTITY,
            # v5.21.0 fix-up (SECOND OPERATOR ADDITION 2026-07-17) — D2
            # detection knobs promoted to rung-2 (operator-settable in the
            # cloud_verification section).
            CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP,
            CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN,
            CONF_ENERGY_CLOUD_LAG_ALERT_S,
            CONF_SOC_DIVERGENCE_THRESHOLD_PP as _D2_TH_DEFAULT,
            CONF_SOC_DIVERGENCE_DWELL_MIN as _D2_DWELL_DEFAULT,
            CONF_CLOUD_LAG_ALERT_S as _D2_LAG_DEFAULT,
        )
        from .const import CONF_OCCUPANCY_WEIGHTED_ENERGY
        from .domain_coordinators.energy_const import (
            CONF_ENERGY_CIRCUIT_EXTRA_ENTITIES,
            CONF_ENERGY_CIRCUIT_EXCLUDE_ENTITIES,
            CONF_ENERGY_CIRCUIT_AUTODISCOVER_SPAN,
            CONF_ENERGY_GENERATOR_ENTITY,
            CONF_ENERGY_GRID_IMPORT_ENTITY,
            CONF_ENERGY_GRID_EXPORT_ENTITY,
            CONF_ENERGY_UTILITY_METER_ENTITY,
            # v5.21.0 fix-up (operator scope change 2026-07-17) — BAEC folded
            # into this step as `baec` + `baec_advanced` sections.
            CONF_ENERGY_DP_ENABLE,
            CONF_ENERGY_DP_EVAL_DELAY_MIN,
            CONF_ENERGY_DP_MARGIN_MIN,
            CONF_ENERGY_DP_MUST_START_BY_MIN,
            CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A,
            CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B,
            CONF_ENERGY_DP_HOUSE_LOAD_SOURCE,
            CONF_DP_ENABLE as _BAEC_EN_DEFAULT,
            CONF_DP_EVAL_DELAY_MIN as _BAEC_EVAL_DEFAULT,
            CONF_DP_MARGIN_MIN as _BAEC_MARGIN_DEFAULT,
            CONF_DP_MUST_START_BY_MIN_PAST_MIDNIGHT as _BAEC_MUST_DEFAULT,
            CONF_DP_NEEDED_KWH_GARAGE_A as _BAEC_KWH_A_DEFAULT,
            CONF_DP_NEEDED_KWH_GARAGE_B_FALLBACK as _BAEC_KWH_B_DEFAULT,
            CONF_DP_HOUSE_LOAD_SOURCE as _BAEC_HLS_DEFAULT,
            DP_HOUSE_LOAD_SOURCES as _BAEC_HLS_SOURCES,
        )

        # v4.2.29: Validate envoy entity on submit (B3). Skipped when user
        # leaves the field empty — empty is allowed for installs not (yet)
        # using EC. When set, must pass V0–V2 + V4 (V3 logs warning only).
        from homeassistant.data_entry_flow import section  # noqa: F401 (used in schema)

        errors: dict[str, str] = {}
        if user_input is not None:
            from .domain_coordinators.energy_const import (
                validate_envoy_config,
                ENVOY_REQUIRED_DERIVED_KEYS,
                ENVOY_ERR_BASE_DERIVED_MISSING,
            )

            # Flatten the collapsed inclement "Advanced" section back to
            # top-level keys (mirrors the fan_recheck_advanced pattern). When
            # the operator never expanded it, the existing options are
            # preserved by the {**options, **user_input} merge below.
            _adv = user_input.pop(INCLEMENT_ADVANCED_SECTION, None)
            if isinstance(_adv, dict):
                user_input = {**user_input, **_adv}
            # v5.15.x fix-up C-CRIT-1 — flatten the collapsed
            # cloud_verification section back to top-level (mirrors the
            # inclement_advanced pattern). Without this, operator overrides
            # persist nested under options["cloud_verification"] which
            # neither _build_entity_map nor WriteVerifier._oracle_entity_for
            # read — runtime only sees flat energy_* keys.
            # Unset-vs-empty semantics:
            #   - key ABSENT from submission → falls to hard-coded default
            #     via the suggested_value re-populated on re-open
            #   - key present with value "" (operator explicitly cleared) →
            #     WriteVerifier treats "" as no oracle configured and
            #     DISABLES that surface (INFO log once).
            _cv = user_input.pop("cloud_verification", None)
            if isinstance(_cv, dict):
                for _k in (
                    CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY,
                    CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
                    CONF_ENERGY_CLOUD_STORAGE_MODE_ORACLE_ENTITY,
                    CONF_ENERGY_CLOUD_BATTERY_SOC_FALLBACK_ENTITY,
                    # v5.21.0 fix-up (SECOND OPERATOR ADDITION 2026-07-17) —
                    # D2 detection knobs live in the same section.
                    CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP,
                    CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN,
                    CONF_ENERGY_CLOUD_LAG_ALERT_S,
                ):
                    if _k in _cv:
                        user_input[_k] = _cv[_k]
            # v5.21.0 fix-up (operator scope change 2026-07-17): flatten
            # the BAEC visible + collapsed advanced sections back to
            # top-level `energy_dp_*` keys. Mirrors the inclement /
            # cloud_verification precedent immediately above so the CM
            # options-listener + `_EC_SETTER_DISPATCH` see the same flat
            # keys the retired standalone step used to write.
            _baec = user_input.pop("baec", None)
            if isinstance(_baec, dict):
                user_input = {**user_input, **_baec}
            _baec_adv = user_input.pop("baec_advanced", None)
            if isinstance(_baec_adv, dict):
                user_input = {**user_input, **_baec_adv}
            # Parse the multiline power-threat-events text into a list.
            _threat = user_input.get(CONF_INCLEMENT_POWER_THREAT_EVENTS)
            if isinstance(_threat, str):
                user_input[CONF_INCLEMENT_POWER_THREAT_EVENTS] = [
                    ln.strip() for ln in _threat.splitlines() if ln.strip()
                ]

            # v5.5.x cycle (c): cross-field validation — when the arbitrage
            # grid-import guard toggle is ON, the kW value is REQUIRED. No
            # silent finite default. Field-scoped error on the kw key
            # matches this step's existing error convention (per-field code
            # + `base` summary; see envoy validation below at :3368-3374).
            _guard_enabled = user_input.get(
                CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED
            )
            _guard_kw = user_input.get(CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW)
            if _guard_enabled and _guard_kw is None:
                errors[CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW] = (
                    "guard_kw_required_when_enabled"
                )
                errors.setdefault("base", "guard_kw_required_when_enabled")

            submitted_envoy = user_input.get(CONF_ENERGY_ENVOY_ENTITY) or ""
            if submitted_envoy:
                # Build the same energy_entity_config the runtime sees:
                # current options + this submission, narrowed to energy_* keys.
                merged = {**self._config_entry.options, **user_input}
                energy_entity_config = {
                    k: v for k, v in merged.items() if k.startswith("energy_")
                }
                result = validate_envoy_config(self.hass, energy_entity_config)

                if not result["ok"]:
                    # Map every failed field's error_code into the form errors
                    # dict. HA renders one error per field; we also attach a
                    # 'base' summary so the user sees the bigger picture.
                    for field, code in result["errors"].items():
                        errors[field] = code
                    if any(
                        k in result["errors"]
                        for k in ENVOY_REQUIRED_DERIVED_KEYS
                    ):
                        errors.setdefault("base", ENVOY_ERR_BASE_DERIVED_MISSING)
                elif result["warnings"]:
                    # V3: non-blocking — log only. The user's save proceeds.
                    for w in result["warnings"]:
                        _LOGGER.warning("Envoy config warning: %s", w)

            if not errors:
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

        # C-1 fix: inclement select dropdowns must render plain-English labels,
        # not raw internal keys. Same {label, value} SelectOptionDict pattern as
        # the DPM relax-ceiling dropdown (config_flow.py:4675) — values stay the
        # existing enum keys so what's stored is unchanged (enum consistency).
        _inclement_severity_options = [
            {"label": "Extreme — only catastrophic events", "value": "Extreme"},
            {"label": "Severe (recommended) — Severe + Extreme", "value": "Severe"},
            {"label": "Moderate — Moderate + Severe + Extreme", "value": "Moderate"},
            {"label": "Minor — any non-Unknown severity", "value": "Minor"},
        ]
        _inclement_corroboration_options = [
            {"label": "Any provider stormy", "value": "any"},
            {
                "label": "Majority of healthy providers (recommended)",
                "value": "majority",
            },
            {"label": "All providers stormy", "value": "unanimous"},
        ]

        # v4.7.6 fix-up C-H2: build the schema dict first (so we can append
        # per-plug self_modulates fields), then wrap in vol.Schema.
        _schema_dict = {
            # v4.0.12: Single Envoy entity picker — auto-derives all Envoy entities
            vol.Optional(
                CONF_ENERGY_ENVOY_ENTITY,
                description={"suggested_value": self._get_current(CONF_ENERGY_ENVOY_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
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
            # v4.7.x Cycle A: WeatherProviderManager — Secondary provider
            vol.Optional(
                CONF_ENERGY_WEATHER_FALLBACK_1,
                description={
                    "suggested_value": self._get_current(CONF_ENERGY_WEATHER_FALLBACK_1),
                },
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            # v4.7.x Cycle A: WeatherProviderManager — Tertiary provider
            vol.Optional(
                CONF_ENERGY_WEATHER_FALLBACK_2,
                description={
                    "suggested_value": self._get_current(CONF_ENERGY_WEATHER_FALLBACK_2),
                },
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            # v4.7.x Cycle A: Staleness limit (hours)
            vol.Optional(
                CONF_WEATHER_STALENESS_MAX_HOURS,
                default=self._get_current(
                    CONF_WEATHER_STALENESS_MAX_HOURS, DEFAULT_WEATHER_STALENESS_MAX_HOURS
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=24, step=1,
                    unit_of_measurement="h",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # v4.7.x Cycle A: Divergence threshold (°F)
            vol.Optional(
                CONF_WEATHER_DIVERGENCE_THRESHOLD_F,
                default=self._get_current(
                    CONF_WEATHER_DIVERGENCE_THRESHOLD_F, DEFAULT_WEATHER_DIVERGENCE_THRESHOLD_F
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=20, step=0.5,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # ── Inclement-weather reserve — Primary surface (4 knobs) ──────
            vol.Optional(
                CONF_INCLEMENT_NWS_ALERTS_ENTITY,
                description={
                    "suggested_value": self._get_current(CONF_INCLEMENT_NWS_ALERTS_ENTITY),
                },
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(
                CONF_INCLEMENT_POWER_THREAT_EVENTS,
                default="\n".join(self._get_current(
                    CONF_INCLEMENT_POWER_THREAT_EVENTS,
                    DEFAULT_INCLEMENT_POWER_THREAT_EVENTS,
                ) if isinstance(self._get_current(
                    CONF_INCLEMENT_POWER_THREAT_EVENTS,
                    DEFAULT_INCLEMENT_POWER_THREAT_EVENTS,
                ), list) else DEFAULT_INCLEMENT_POWER_THREAT_EVENTS),
            ): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
            vol.Optional(
                CONF_INCLEMENT_WARN_MIN_SEVERITY,
                default=self._get_current(
                    CONF_INCLEMENT_WARN_MIN_SEVERITY,
                    DEFAULT_INCLEMENT_WARN_MIN_SEVERITY,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_inclement_severity_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD,
                default=self._get_current(
                    CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD,
                    DEFAULT_INCLEMENT_GRID_PRECHARGE_ON_HOLD,
                ),
            ): selector.BooleanSelector(),
            # ── Inclement-weather reserve — Advanced subsection (3 knobs) ──
            # Grouped under a collapsed "Advanced" section (FIN-1). Flattened
            # back to top-level entry.options on submit (mirrors the
            # fan_recheck_advanced pattern) so the coordinator reads the same
            # top-level CONF_INCLEMENT_* keys.
            vol.Optional(INCLEMENT_ADVANCED_SECTION): section(
                vol.Schema({
                    vol.Optional(
                        CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
                        default=self._get_current(
                            CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
                            DEFAULT_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=100, step=5,
                            unit_of_measurement="%",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT,
                        default=self._get_current(
                            CONF_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT,
                            DEFAULT_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=30, step=1,
                            unit_of_measurement="%",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_INCLEMENT_CONDITION_CORROBORATION_MODE,
                        default=self._get_current(
                            CONF_INCLEMENT_CONDITION_CORROBORATION_MODE,
                            DEFAULT_INCLEMENT_CONDITION_CORROBORATION_MODE,
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_inclement_corroboration_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }),
                {"collapsed": True},
            ),
            # v3.11.0: Solar forecast entity selectors
            vol.Optional(
                CONF_ENERGY_SOLCAST_TODAY_ENTITY,
                description={"suggested_value": self._get_current(CONF_ENERGY_SOLCAST_TODAY_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(
                CONF_ENERGY_SOLCAST_TOMORROW_ENTITY,
                description={"suggested_value": self._get_current(CONF_ENERGY_SOLCAST_TOMORROW_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(
                CONF_ENERGY_SOLCAST_REMAINING_ENTITY,
                description={"suggested_value": self._get_current(CONF_ENERGY_SOLCAST_REMAINING_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
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
            # v5.12.0: SPAN breaker overrides for EVSE pause/resume — recover
            # from a SPAN-app breaker rename without a code deploy.
            vol.Optional(
                CONF_ENERGY_EVSE_A_SPAN_BREAKER,
                description={"suggested_value": self._get_current(CONF_ENERGY_EVSE_A_SPAN_BREAKER)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(
                CONF_ENERGY_EVSE_B_SPAN_BREAKER,
                description={"suggested_value": self._get_current(CONF_ENERGY_EVSE_B_SPAN_BREAKER)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
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
            # v3.11.0: Off-peak drain targets
            vol.Optional(
                CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT,
                default=self._get_current(CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT, DEFAULT_OFFPEAK_DRAIN_EXCELLENT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5, max=50, step=5,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_ENERGY_OFFPEAK_DRAIN_GOOD,
                default=self._get_current(CONF_ENERGY_OFFPEAK_DRAIN_GOOD, DEFAULT_OFFPEAK_DRAIN_GOOD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5, max=50, step=5,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_ENERGY_OFFPEAK_DRAIN_MODERATE,
                default=self._get_current(CONF_ENERGY_OFFPEAK_DRAIN_MODERATE, DEFAULT_OFFPEAK_DRAIN_MODERATE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10, max=60, step=5,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_ENERGY_OFFPEAK_DRAIN_POOR,
                default=self._get_current(CONF_ENERGY_OFFPEAK_DRAIN_POOR, DEFAULT_OFFPEAK_DRAIN_POOR),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=15, max=80, step=5,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # v4.5.0 D7: arbitrage gate is forecast-class only (no SOC
            # trigger). The lead-time live-tunable lives on the EC device
            # card (NumberMode.BOX) per the URA mirror pattern — NOT in
            # this form (memory: feedback_ura_mirror_pattern.md).
            vol.Optional(
                CONF_ENERGY_ARBITRAGE_ENABLED,
                default=self._get_current(CONF_ENERGY_ARBITRAGE_ENABLED, False),
            ): selector.BooleanSelector(),
            # v4.5.0 D2: renamed from CONF_ENERGY_ARBITRAGE_SOC_TARGET. The
            # migration helper in __init__.py copies legacy values forward
            # before this form is rendered, so existing users see their
            # saved value.
            vol.Optional(
                CONF_ENERGY_PEAK_BUFFER_TARGET,
                default=self._get_current(
                    CONF_ENERGY_PEAK_BUFFER_TARGET,
                    self._get_current(
                        CONF_ENERGY_ARBITRAGE_SOC_TARGET,
                        DEFAULT_PEAK_BUFFER_TARGET,
                    ),
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=50, max=100, step=5,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # v4.5.0 D3: multi-day Solcast lookback (D+2 awareness).
            # Default OFF during calibration cycle per Open Question #3.
            vol.Optional(
                CONF_ENERGY_MULTI_DAY_HORIZON_ENABLED,
                default=self._get_current(CONF_ENERGY_MULTI_DAY_HORIZON_ENABLED, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ENERGY_SOLCAST_DAY_3_ENTITY,
                description={"suggested_value": self._get_current(CONF_ENERGY_SOLCAST_DAY_3_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            # v3.11.0: Advanced EVSE management
            vol.Optional(
                CONF_ENERGY_EXCESS_SOLAR_ENABLED,
                default=self._get_current(CONF_ENERGY_EXCESS_SOLAR_ENABLED, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ENERGY_EXCESS_SOLAR_SOC,
                default=self._get_current(CONF_ENERGY_EXCESS_SOLAR_SOC, DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=80, max=100, step=1,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_ENERGY_EXCESS_SOLAR_KWH,
                default=self._get_current(CONF_ENERGY_EXCESS_SOLAR_KWH, DEFAULT_EXCESS_SOLAR_KWH_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=15, step=0.5,
                    unit_of_measurement="kWh",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # v4.7.6 D3.2: Fill-priority pause SOC threshold (turn-OFF side
            # of the EVSE solar-aware gate, companion to excess_solar_soc).
            vol.Optional(
                CONF_ENERGY_FILL_PRIORITY_SOC,
                default=self._get_current(CONF_ENERGY_FILL_PRIORITY_SOC, DEFAULT_FILL_PRIORITY_SOC),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=50, max=95, step=5,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # v4.7.6 D3.4: Per-EVSE self_modulates checkboxes are injected
            # dynamically below (one BooleanSelector per configured EVSE).
            # See the loop after `_schema_dict` is built. EVSEs whose key
            # is absent from `cm_config` will retain `source: "default"`
            # in EVPool.get_status() (mirrors C-M2 fix for L1 plugs).
            # v4.7.6 D6.4 / fix-up C-H2: Per-L1-plug self_modulates fields
            # are injected dynamically below (one BooleanSelector per
            # configured plug, suffixed `<plug_entity_id>_self_modulates`).
            # Plugs whose key is absent from `cm_config` will retain
            # `source: "default"` in SmartPlugController.get_status().
            # v4.0.18: Grid import cap
            vol.Optional(
                CONF_ENERGY_GRID_IMPORT_CAP_ENABLED,
                default=self._get_current(CONF_ENERGY_GRID_IMPORT_CAP_ENABLED, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ENERGY_GRID_IMPORT_CAP_KW,
                default=self._get_current(CONF_ENERGY_GRID_IMPORT_CAP_KW, DEFAULT_GRID_IMPORT_CAP_KW),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=3, max=20, step=0.5,
                    unit_of_measurement="kW",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # v5.5.x cycle: Arbitrage Grid-Charge Import Guard (default OFF,
            # NO kW default — design (c)). Mirrors the EV Grid Import Cap
            # pattern for the toggle; intentionally diverges on the kW: when
            # the operator turns the toggle ON, they MUST type a kW (their
            # DER breaker's continuous rating). No silent finite default
            # (the old hidden 12 kW guard was harming summer pre-charge —
            # we will not let a fresh enable silently re-impose any guess).
            #
            # Idiomatic blank render: `default=<stored> or vol.UNDEFINED`
            # (used elsewhere in this file, e.g. CONF_OUTSIDE_TEMP_SENSOR
            # at :2439). When no value is stored, the field renders blank.
            # Cross-field validation in async_step_coordinator_energy
            # rejects enabled=True with a missing/blank kW.
            vol.Optional(
                CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED,
                default=self._get_current(
                    CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED, False
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW,
                default=self._get_current(
                    CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW
                ) or vol.UNDEFINED,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=6, max=20, step=0.5,
                    unit_of_measurement="kW",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            # v4.2.17: EV battery drain SOC threshold
            vol.Optional(
                CONF_ENERGY_EV_BATTERY_DRAIN_SOC,
                default=self._get_current(CONF_ENERGY_EV_BATTERY_DRAIN_SOC, DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10, max=90, step=5,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # LKG wave 1 D2 — solar array nameplate for the production
            # upper-envelope. Rung-2 (config-flow) per operator ruling
            # 2026-07-23: per-install physical structure, set once at
            # commissioning. Default 19400 W = 19.4 kW = operator's
            # installed Enphase fleet theoretical maximum (NOT the
            # ~15 kW observed peak; the envelope must bound what the
            # array CAN do). Range: 1000-50000 W spans small residential
            # to large commercial. Live-tunable via options-flow (see
            # OPTIONS_RELOAD_SUPPRESS_KEYS in __init__.py — read fresh
            # every excess-solar tick).
            vol.Optional(
                CONF_ENERGY_SOLAR_NAMEPLATE_W,
                default=self._get_current(
                    CONF_ENERGY_SOLAR_NAMEPLATE_W,
                    DEFAULT_ENERGY_SOLAR_NAMEPLATE_W,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1000, max=50000, step=100,
                    unit_of_measurement="W",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            # v4.1.1 B4 L2: Occupancy-weighted prediction toggle
            vol.Optional(
                CONF_OCCUPANCY_WEIGHTED_ENERGY,
                default=self._get_current(CONF_OCCUPANCY_WEIGHTED_ENERGY, False),
            ): selector.BooleanSelector(),
            # v4.2.0: Circuit monitoring
            vol.Optional(
                CONF_ENERGY_CIRCUIT_EXTRA_ENTITIES,
                default=self._get_current(CONF_ENERGY_CIRCUIT_EXTRA_ENTITIES, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
            ),
            vol.Optional(
                CONF_ENERGY_CIRCUIT_EXCLUDE_ENTITIES,
                default=self._get_current(CONF_ENERGY_CIRCUIT_EXCLUDE_ENTITIES, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
            ),
            vol.Optional(
                CONF_ENERGY_CIRCUIT_AUTODISCOVER_SPAN,
                default=self._get_current(CONF_ENERGY_CIRCUIT_AUTODISCOVER_SPAN, True),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ENERGY_GENERATOR_ENTITY,
                description={"suggested_value": self._get_current(CONF_ENERGY_GENERATOR_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            # v4.2.0: Direct grid import/export sensors (e.g., Emporia mains)
            vol.Optional(
                CONF_ENERGY_GRID_IMPORT_ENTITY,
                description={"suggested_value": self._get_current(CONF_ENERGY_GRID_IMPORT_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Optional(
                CONF_ENERGY_GRID_EXPORT_ENTITY,
                description={"suggested_value": self._get_current(CONF_ENERGY_GRID_EXPORT_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            # v4.2.17: Utility company net energy meter
            vol.Optional(
                CONF_ENERGY_UTILITY_METER_ENTITY,
                description={"suggested_value": self._get_current(CONF_ENERGY_UTILITY_METER_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
            # Note: energy anomaly sensitivity dropdown removed (v4.6.3 C7 fix).
            # The energy coordinator uses cross-check anomaly detection (a distinct
            # path), not the z-score AnomalyDetector that the sensitivity multiplier
            # feeds into.  Exposing a setting that has no runtime effect is
            # misleading.  Re-introduce if an AnomalyDetector is added to energy.
        }
        # v4.7.6 fix-up C-M2: inject per-EVSE self_modulates checkbox
        # ONLY for EVSEs that have a configured power entity. Previously
        # `garage_a_self_modulates` AND `garage_b_self_modulates` were both
        # statically present even on single-EVSE installs, exposing a
        # meaningless toggle and stamping the absent EVSE as
        # `source: "explicit"` in evse_config sensor attr.
        # Field key shape: `<evse_logical_id>_self_modulates`. Absent keys
        # remain `source: "default"` in EVPool.get_status().
        _evse_logical_id_for_conf = {
            CONF_ENERGY_EVSE_A_ENTITY: "garage_a",
            CONF_ENERGY_EVSE_B_ENTITY: "garage_b",
        }
        for _conf_key, _evse_logical_id in _evse_logical_id_for_conf.items():
            if self._get_current(_conf_key):
                _field_key = f"{_evse_logical_id}_self_modulates"
                _schema_dict[
                    vol.Optional(
                        _field_key,
                        default=self._get_current(_field_key, False),
                    )
                ] = selector.BooleanSelector()
        # v4.7.6 fix-up C-H2: inject per-L1-plug self_modulates checkbox
        # for every plug already configured in CONF_ENERGY_L1_CHARGER_ENTITIES.
        # Field key shape: `<plug_entity_id>_self_modulates`. Absent keys
        # remain `source: "default"` in SmartPlugController.get_status().
        _configured_plugs = self._get_current(
            CONF_ENERGY_L1_CHARGER_ENTITIES, []
        ) or []
        for _plug_entity_id in _configured_plugs:
            _field_key = f"{_plug_entity_id}_self_modulates"
            _schema_dict[
                vol.Optional(
                    _field_key,
                    default=self._get_current(_field_key, False),
                )
            ] = selector.BooleanSelector()
        # v5.15.x — Envoy write-verification cloud oracle overrides.
        # Optional fields; empty/unset cleanly DISABLES that surface's
        # verification (logged once at INFO). Grouped as a collapsed
        # subsection mirroring the inclement_advanced section pattern.
        _schema_dict[
            vol.Optional("cloud_verification")
        ] = section(
            vol.Schema({
                vol.Optional(
                    CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY,
                    description={
                        "suggested_value": self._get_current(
                            CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY,
                            DEFAULT_CLOUD_RESERVE_ORACLE_ENTITY,
                        ),
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(
                    CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
                    description={
                        "suggested_value": self._get_current(
                            CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
                            DEFAULT_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
                        ),
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(
                    CONF_ENERGY_CLOUD_STORAGE_MODE_ORACLE_ENTITY,
                    description={
                        "suggested_value": self._get_current(
                            CONF_ENERGY_CLOUD_STORAGE_MODE_ORACLE_ENTITY,
                            DEFAULT_CLOUD_STORAGE_MODE_ORACLE_ENTITY,
                        ),
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="select")
                ),
                vol.Optional(
                    CONF_ENERGY_CLOUD_BATTERY_SOC_FALLBACK_ENTITY,
                    description={
                        "suggested_value": self._get_current(
                            CONF_ENERGY_CLOUD_BATTERY_SOC_FALLBACK_ENTITY,
                            DEFAULT_CLOUD_BATTERY_SOC_FALLBACK_ENTITY,
                        ),
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                # v5.21.0 fix-up (SECOND OPERATOR ADDITION 2026-07-17) —
                # D2 detection knobs (rung-2). Bounds sanity-checked
                # against the read sites in energy_battery.py:
                #  - threshold_pp: signed diff of two SOC %s → [0, 50]
                #    (a 50 pp gap is already so large that any wider
                #    range would be operator error; 0 disables detection
                #    per the kill-switch documented on the constant).
                #  - dwell_min: continuous-disagreement anti-flap window
                #    (0-60 min: matches operator experience with the
                #    inclement-hold dwell knobs).
                #  - lag_s: 30 min planner default already; expose 0-3600 s
                #    step 30 (10 minutes lower, 1 hour upper — matches
                #    Enphase cloud tick cadences; 0 disables the alert
                #    while leaving the age attribute visible).
                vol.Optional(
                    CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP,
                    default=self._get_current(
                        CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP,
                        _D2_TH_DEFAULT,
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=50, step=1,
                        unit_of_measurement="pp",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN,
                    default=self._get_current(
                        CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN,
                        _D2_DWELL_DEFAULT,
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=60, step=1,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_ENERGY_CLOUD_LAG_ALERT_S,
                    default=self._get_current(
                        CONF_ENERGY_CLOUD_LAG_ALERT_S,
                        _D2_LAG_DEFAULT,
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=3600, step=30,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }),
            options={"collapsed": True},
        )

        # v5.21.0 fix-up (operator scope change 2026-07-17) — Battery-Aware
        # EV Charging (BAEC / drain-precedence) folded into this step as a
        # sibling of INCLEMENT_ADVANCED_SECTION / cloud_verification. Visible
        # `baec` section holds the enable toggle + latest charge start;
        # collapsed `baec_advanced` holds the 4 tuning knobs + house-load
        # source dropdown. Flatten-on-save above pops both back to top-level
        # CONF_ENERGY_DP_* keys, so the CM listener + `_EC_SETTER_DISPATCH`
        # see the same shape they always have.
        _baec_house_load_labels = {
            "max_span_r1": "Safe blend (recommended)",
            "live_span": "Live meter only",
            "r1_base": "Modelled baseline only",
        }
        _baec_house_load_options = [
            {"value": v, "label": _baec_house_load_labels.get(v, v)}
            for v in _BAEC_HLS_SOURCES
        ]
        _schema_dict[vol.Optional("baec")] = section(
            vol.Schema({
                vol.Optional(
                    CONF_ENERGY_DP_ENABLE,
                    default=self._get_current(
                        CONF_ENERGY_DP_ENABLE, _BAEC_EN_DEFAULT,
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_ENERGY_DP_MUST_START_BY_MIN,
                    default=self._get_current(
                        CONF_ENERGY_DP_MUST_START_BY_MIN, _BAEC_MUST_DEFAULT,
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=24 * 60 - 1, step=15,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }),
            options={"collapsed": False},
        )
        _schema_dict[vol.Optional("baec_advanced")] = section(
            vol.Schema({
                vol.Optional(
                    CONF_ENERGY_DP_EVAL_DELAY_MIN,
                    default=self._get_current(
                        CONF_ENERGY_DP_EVAL_DELAY_MIN, _BAEC_EVAL_DEFAULT,
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=60, step=1,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_ENERGY_DP_MARGIN_MIN,
                    default=self._get_current(
                        CONF_ENERGY_DP_MARGIN_MIN, _BAEC_MARGIN_DEFAULT,
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=240, step=5,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A,
                    default=self._get_current(
                        CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A, _BAEC_KWH_A_DEFAULT,
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=120, step=0.5,
                        unit_of_measurement="kWh",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B,
                    default=self._get_current(
                        CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B, _BAEC_KWH_B_DEFAULT,
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=150, step=0.5,
                        unit_of_measurement="kWh",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_ENERGY_DP_HOUSE_LOAD_SOURCE,
                    default=self._get_current(
                        CONF_ENERGY_DP_HOUSE_LOAD_SOURCE, _BAEC_HLS_DEFAULT,
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_baec_house_load_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
            options={"collapsed": True},
        )
        data_schema = vol.Schema(_schema_dict)

        # v4.2.29: surface envoy validation errors per-field.
        return self.async_show_form(
            step_id="coordinator_energy",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_coordinator_hvac(self, user_input=None):
        """HVAC Coordinator submenu.

        v4.7.2 D1: Converted from form to menu to expose Dynamic Preset step.
        v4.7.3 D1: Added hvac_baseline_presets as a third menu option.
        Routes to: coordinator_hvac_settings (existing tuning form),
        hvac_dynamic_preset (Surface 1, v4.7.2 D1), or
        hvac_baseline_presets (new seasonal baseline editor, v4.7.3 D1).
        """
        return self.async_show_menu(
            step_id="coordinator_hvac",
            menu_options=[
                "coordinator_hvac_settings",
                "hvac_dynamic_preset",
                "hvac_baseline_presets",
            ],
        )

    async def async_step_coordinator_hvac_settings(self, user_input=None):
        """Configure HVAC Coordinator settings.

        v3.8.6: Sleep offset, override compromise, fan tuning, cover entities.
        v3.18.5: Person-to-zone mapping moved to per-zone zone_persons step.
        v4.7.2: Moved from async_step_coordinator_hvac (now a menu).
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
            CONF_HVAC_AC_RESET_ENABLED,
            DEFAULT_AC_RESET_ENABLED,
            CONF_HVAC_FAN_CONTROL_ENABLED,
            DEFAULT_FAN_CONTROL_ENABLED,
            CONF_ZONE_VACANCY_SWEEP_ENABLED,
            CONF_PRE_ARRIVAL_SOURCES,
            DEFAULT_PRE_ARRIVAL_SOURCES,
            CONF_HVAC_ZONE_ENTRY_DWELL,
            DEFAULT_ZONE_ENTRY_DWELL_MINUTES,
            # Presence-timer cluster — collapsed "presence_timing" section
            CONF_HVAC_VACANCY_GRACE_MINUTES,
            DEFAULT_VACANCY_GRACE_MINUTES,
            CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
            DEFAULT_VACANCY_GRACE_CONSTRAINED,
            CONF_HVAC_MAX_OCCUPANCY_HOURS,
            DEFAULT_MAX_OCCUPANCY_HOURS,
            # v4.5.9.2: occupancy-aware cover-close threshold
            CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA,
            DEFAULT_HVAC_OCCUPIED_COVER_CLOSE_DELTA,
            # v4.5.10: HVAC tunables (master + 9 thresholds)
            CONF_HVAC_SOLAR_GAIN_COVER_ENABLED,
            DEFAULT_HVAC_SOLAR_GAIN_COVER_ENABLED,
            CONF_HVAC_COVER_CLOSE_TEMP,
            DEFAULT_HVAC_COVER_CLOSE_TEMP,
            CONF_HVAC_COVER_OPEN_TEMP,
            DEFAULT_HVAC_COVER_OPEN_TEMP,
            CONF_HVAC_COVER_OVERRIDE_HOURS,
            DEFAULT_HVAC_COVER_OVERRIDE_HOURS,
            CONF_HVAC_SOLAR_BANK_FLOOR,
            DEFAULT_HVAC_SOLAR_BANK_FLOOR,
            CONF_HVAC_COVER_SOLAR_START_HOUR,
            DEFAULT_HVAC_COVER_SOLAR_START_HOUR,
            CONF_HVAC_COVER_SOLAR_END_HOUR,
            DEFAULT_HVAC_COVER_SOLAR_END_HOUR,
            CONF_HVAC_SOLAR_BANK_SOC_MIN,
            DEFAULT_HVAC_SOLAR_BANK_SOC_MIN,
            # v5.7.1: CONF_HVAC_SOLAR_BANK_ENABLED retired; replaced by
            # CONF_ENERGY_PRECOOL_ENABLED (operator master gate on the EC
            # device). The legacy options value migrates via
            # async_migrate_entry. See PLANNING_v5.7.x_energy_pre_cool_unification.md.
            CONF_ENERGY_PRECOOL_ENABLED,
            DEFAULT_ENERGY_PRECOOL_ENABLED,
            CONF_HVAC_PRE_CONDITIONING_ENABLED,
            DEFAULT_HVAC_PRE_CONDITIONING_ENABLED,
            CONF_HVAC_PRECOOL_FORECAST_HIGH,
            DEFAULT_HVAC_PRECOOL_FORECAST_HIGH,
            CONF_HVAC_PREHEAT_FORECAST_LOW,
            DEFAULT_HVAC_PREHEAT_FORECAST_LOW,
            COVER_HYSTERESIS_MIN_GAP,
        )

        # Import HA section helper for the collapsed "presence_timing" block.
        from homeassistant.data_entry_flow import section

        # v4.5.10: validation — Cover Open Temp must be at least
        # COVER_HYSTERESIS_MIN_GAP (3°F) below Cover Close Temp to
        # prevent solar-gain flapping. Reject the form save with an
        # error rather than silently accepting bad config.
        errors: dict[str, str] = {}
        # D5 (A-MED-1 fix): accumulate cross-field violations so both
        # surface in a single submit. Single-violation paths reuse the
        # existing per-violation key (byte-identical to pre-D5 behavior);
        # two-violation path uses the combined key.
        error_keys: list[str] = []
        if user_input is not None:
            # Flatten the collapsed "presence_timing" section BEFORE any
            # validation reads from user_input. Mirrors the fan_recheck
            # flatten pattern at config_flow.py:2893-2898.
            advanced = user_input.pop("presence_timing", None)
            if isinstance(advanced, dict):
                user_input = {**user_input, **advanced}

            close_temp = float(user_input.get(
                CONF_HVAC_COVER_CLOSE_TEMP, DEFAULT_HVAC_COVER_CLOSE_TEMP,
            ))
            open_temp = float(user_input.get(
                CONF_HVAC_COVER_OPEN_TEMP, DEFAULT_HVAC_COVER_OPEN_TEMP,
            ))
            if close_temp - open_temp < COVER_HYSTERESIS_MIN_GAP:
                error_keys.append("cover_temp_hysteresis_too_small")

            # Cross-field validation: energy-saving vacancy delay must not
            # exceed the normal vacancy delay (operator-coined constraint).
            # D5: no longer gated behind `if not errors:` — both checks
            # always run so a submit with BOTH violations surfaces both.
            grace = int(user_input.get(
                CONF_HVAC_VACANCY_GRACE_MINUTES,
                DEFAULT_VACANCY_GRACE_MINUTES,
            ))
            grace_constrained = int(user_input.get(
                CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
                DEFAULT_VACANCY_GRACE_CONSTRAINED,
            ))
            if grace_constrained > grace:
                error_keys.append("vacancy_grace_constrained_exceeds_normal")

            if error_keys:
                # A-MED-2 (Review A): the combined message names BOTH the
                # cover-hysteresis and vacancy-grace violations, so it MUST
                # only fire when BOTH specific keys are present. The prior
                # `len(error_keys) >= 2` gate would mis-fire if a future
                # third unrelated key was appended (combined message
                # would be shown even though one of its two named
                # violations wasn't actually triggered).
                have_cover = "cover_temp_hysteresis_too_small" in error_keys
                have_vacancy = "vacancy_grace_constrained_exceeds_normal" in error_keys
                if have_cover and have_vacancy:
                    # Two-violation case: dedicated combined message names
                    # BOTH violations clearly.
                    errors["base"] = "cover_and_vacancy_combined"
                else:
                    # Single-violation case (or future-third-key case):
                    # reuse the per-violation key so its translation is
                    # reused (byte-identical to pre-D5 single-violation
                    # behavior).
                    errors["base"] = error_keys[0]
            else:
                return self.async_create_entry(
                    title="",
                    data={**self._config_entry.options, **user_input},
                )

        # Build HVAC tuning schema
        schema_dict = {
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
            # v4.5.9.2: Per-house occupancy-aware solar-gain cover close
            # threshold. When a room is occupied, HVAC only closes its
            # covers if room temp is at least this many °F above the
            # zone's cooling setpoint. Prevents closing covers in an
            # occupied room that's still comfortable.
            vol.Optional(
                CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA,
                default=self._get_current(
                    CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA,
                    DEFAULT_HVAC_OCCUPIED_COVER_CLOSE_DELTA,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5, max=5, step=0.5,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # v4.5.10: Solar Cover Management master toggle. When OFF,
            # the entire CoverController feature is disabled — no closes,
            # no opens, regardless of per-room cover_hvac_managed settings.
            vol.Optional(
                CONF_HVAC_SOLAR_GAIN_COVER_ENABLED,
                default=self._get_current(
                    CONF_HVAC_SOLAR_GAIN_COVER_ENABLED,
                    DEFAULT_HVAC_SOLAR_GAIN_COVER_ENABLED,
                ),
            ): selector.BooleanSelector(),
            # v4.5.10: Solar-gain temperature thresholds (close/open).
            # Hysteresis: open must be at least COVER_HYSTERESIS_MIN_GAP
            # below close — enforced at form save time.
            vol.Optional(
                CONF_HVAC_COVER_CLOSE_TEMP,
                default=self._get_current(
                    CONF_HVAC_COVER_CLOSE_TEMP, DEFAULT_HVAC_COVER_CLOSE_TEMP,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=75, max=95, step=1,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_HVAC_COVER_OPEN_TEMP,
                default=self._get_current(
                    CONF_HVAC_COVER_OPEN_TEMP, DEFAULT_HVAC_COVER_OPEN_TEMP,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=70, max=90, step=1,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # v4.5.10: Manual override duration after a user touches a managed cover.
            vol.Optional(
                CONF_HVAC_COVER_OVERRIDE_HOURS,
                default=self._get_current(
                    CONF_HVAC_COVER_OVERRIDE_HOURS, DEFAULT_HVAC_COVER_OVERRIDE_HOURS,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5, max=24, step=0.5,
                    unit_of_measurement="hr",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            # v4.5.10: Solar banking floor (coolest setpoint banking will drive zones to).
            vol.Optional(
                CONF_HVAC_SOLAR_BANK_FLOOR,
                default=self._get_current(
                    CONF_HVAC_SOLAR_BANK_FLOOR, DEFAULT_HVAC_SOLAR_BANK_FLOOR,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=65, max=80, step=1,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # v4.5.10: Solar window hours (when HVAC watches for solar conditions).
            vol.Optional(
                CONF_HVAC_COVER_SOLAR_START_HOUR,
                default=self._get_current(
                    CONF_HVAC_COVER_SOLAR_START_HOUR, DEFAULT_HVAC_COVER_SOLAR_START_HOUR,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=6, max=14, step=1,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_HVAC_COVER_SOLAR_END_HOUR,
                default=self._get_current(
                    CONF_HVAC_COVER_SOLAR_END_HOUR, DEFAULT_HVAC_COVER_SOLAR_END_HOUR,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=14, max=20, step=1,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # v4.5.10: Solar banking battery threshold.
            vol.Optional(
                CONF_HVAC_SOLAR_BANK_SOC_MIN,
                default=self._get_current(
                    CONF_HVAC_SOLAR_BANK_SOC_MIN, DEFAULT_HVAC_SOLAR_BANK_SOC_MIN,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=80, max=100, step=1,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # v5.7.1 — Energy Saver Pre-Cool master enable (also exposed as
            # EC sub-switch "Energy Saver Pre-Cool"). Default ON. Runtime
            # toggle is the ECEnergyPreCoolSwitch on the EC device card; this
            # field only seeds the initial state at install. Operator-tunable
            # offset + scope live as separate EC entities (Number + Select);
            # the install schema only carries the enable flag.
            vol.Optional(
                CONF_ENERGY_PRECOOL_ENABLED,
                default=self._get_current(
                    CONF_ENERGY_PRECOOL_ENABLED, DEFAULT_ENERGY_PRECOOL_ENABLED,
                ),
            ): selector.BooleanSelector(),
            # HC Pre-Conditioning master enable (D1, parent gate for all
            # pre-conditioning branches). Default ON. Runtime toggle is
            # the HVACPreConditioningSwitch on the HC device card; this
            # field only seeds the initial state at install.
            vol.Optional(
                CONF_HVAC_PRE_CONDITIONING_ENABLED,
                default=self._get_current(
                    CONF_HVAC_PRE_CONDITIONING_ENABLED,
                    DEFAULT_HVAC_PRE_CONDITIONING_ENABLED,
                ),
            ): selector.BooleanSelector(),
            # v4.5.10: Pre-cool / pre-heat forecast triggers.
            vol.Optional(
                CONF_HVAC_PRECOOL_FORECAST_HIGH,
                default=self._get_current(
                    CONF_HVAC_PRECOOL_FORECAST_HIGH, DEFAULT_HVAC_PRECOOL_FORECAST_HIGH,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=80, max=100, step=1,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_HVAC_PREHEAT_FORECAST_LOW,
                default=self._get_current(
                    CONF_HVAC_PREHEAT_FORECAST_LOW, DEFAULT_HVAC_PREHEAT_FORECAST_LOW,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=20, max=50, step=1,
                    unit_of_measurement="°F",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # v4.0.15: Fan control toggle
            vol.Optional(
                CONF_HVAC_FAN_CONTROL_ENABLED,
                default=self._get_current(CONF_HVAC_FAN_CONTROL_ENABLED, DEFAULT_FAN_CONTROL_ENABLED),
            ): selector.BooleanSelector(),
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
            # v3.17.9: AC Reset toggle
            vol.Optional(
                CONF_HVAC_AC_RESET_ENABLED,
                default=self._get_current(CONF_HVAC_AC_RESET_ENABLED, DEFAULT_AC_RESET_ENABLED),
            ): selector.BooleanSelector(),
            # v3.18.2: Zone sweep toggle
            vol.Optional(
                CONF_ZONE_VACANCY_SWEEP_ENABLED,
                default=self._get_current(CONF_ZONE_VACANCY_SWEEP_ENABLED, True),
            ): selector.BooleanSelector(),
            # v3.18.6: Pre-arrival trigger sources
            vol.Optional(
                CONF_PRE_ARRIVAL_SOURCES,
                default=self._get_current(CONF_PRE_ARRIVAL_SOURCES, DEFAULT_PRE_ARRIVAL_SOURCES),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"label": "Geofence (Phone GPS)", "value": "geofence"},
                        {"label": "BLE (Bluetooth Proximity)", "value": "ble"},
                        {"label": "Camera Face Recognition", "value": "camera_face"},
                    ],
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            # Presence-timer cluster — collapsed "Advanced — presence
            # timing (rarely change)" section. Holds the 4 presence-timer
            # knobs (vacancy delay, energy-saving vacancy delay, zone entry
            # dwell, max occupied time). Section contents are flattened
            # back to top-level entry.options on save (see flatten block
            # at the top of this step). Cross-field validation enforces
            # energy-saving vacancy delay <= normal vacancy delay.
            vol.Optional("presence_timing"): section(
                vol.Schema({
                    vol.Optional(
                        CONF_HVAC_VACANCY_GRACE_MINUTES,
                        default=self._get_current(
                            CONF_HVAC_VACANCY_GRACE_MINUTES,
                            DEFAULT_VACANCY_GRACE_MINUTES,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=60, step=1,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
                        default=self._get_current(
                            CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
                            DEFAULT_VACANCY_GRACE_CONSTRAINED,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=60, step=1,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_HVAC_ZONE_ENTRY_DWELL,
                        default=self._get_current(
                            CONF_HVAC_ZONE_ENTRY_DWELL,
                            DEFAULT_ZONE_ENTRY_DWELL_MINUTES,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=15, step=1,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_HVAC_MAX_OCCUPANCY_HOURS,
                        default=self._get_current(
                            CONF_HVAC_MAX_OCCUPANCY_HOURS,
                            DEFAULT_MAX_OCCUPANCY_HOURS,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=24, step=1,
                            unit_of_measurement="h",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }),
                {"collapsed": True},
            ),
            # v4.6.3 D10: Anomaly sensitivity
            vol.Optional(
                CONF_HVAC_ANOMALY_SENSITIVITY,
                default=self._get_current(
                    CONF_HVAC_ANOMALY_SENSITIVITY, DEFAULT_ANOMALY_SENSITIVITY
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "very_quiet", "label": "Very Quiet — only the loudest anomalies get flagged"},
                        {"value": "quiet", "label": "Quiet — fewer notifications, accepts more variability as normal"},
                        {"value": "normal", "label": "Normal — standard sensitivity, recommended for most homes"},
                        {"value": "sensitive", "label": "Sensitive — catches subtler anomalies, more notifications"},
                        {"value": "very_sensitive", "label": "Very Sensitive — flags small deviations; expect frequent advisories"},
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        }

        data_schema = vol.Schema(schema_dict)

        return self.async_show_form(
            step_id="coordinator_hvac_settings",
            data_schema=data_schema,
            errors=errors,
        )

    # =========================================================================
    # v4.7.4 D1/D2: HVAC Coordinator → Dynamic Preset (Surface 1)
    # Per-zone editing STRIPPED — all per-zone config now lives on Surface 2
    # (Zone Manager → zone → Dynamic Preset). Surface 1 shows house-wide only.
    # D2: 5 tunables wrapped in collapsed "Advanced (rarely change)" section.
    # =========================================================================

    async def async_step_hvac_dynamic_preset(self, user_input=None):
        """HVAC Coordinator → Configure → Dynamic Preset (Surface 1, v4.7.4 D1).

        Reachable via: CM entry → Configure → HVAC → Dynamic Preset.

        v4.7.4 D1: Per-zone fields REMOVED from this surface.
        Surface 1 now shows house-wide settings only:
          - CONF_DYNAMIC_PRESET_ENABLED (master enable toggle, visible by default)
          - "Advanced (rarely change)" section (collapsed by default):
              CONF_DYNAMIC_PRESET_DELTA_COOL_MAX, _MILD_MAX, _HOT_MAX,
              CONF_DYNAMIC_PRESET_DWELL_MINUTES, CONF_DYNAMIC_PRESET_HYSTERESIS_F

        Per-zone settings live under Zone Manager → [zone] → Dynamic Preset.

        v4.7.2 sync invariant (per-zone validation + prefixed keys) is DROPPED —
        no longer applicable since Surface 1 has no per-zone fields. The
        test_v472_dpm_storage_roundtrip_both_surfaces test and related sync tests
        are removed accordingly (documented in v4.7.4 plan §4 D1).
        """
        import voluptuous as vol
        from .domain_coordinators.energy_const import (
            CONF_DYNAMIC_PRESET_ENABLED,
            CONF_DYNAMIC_PRESET_DWELL_MINUTES,
            CONF_DYNAMIC_PRESET_HYSTERESIS_F,
            # v4.7.17.2: new operator-facing knobs
            CONF_DPM_COOL_DAY_RELAX_F,
            CONF_DPM_HOT_DAY_TIGHTEN_F,
            DEFAULT_DPM_COOL_DAY_RELAX_F,
            DEFAULT_DPM_HOT_DAY_TIGHTEN_F,
            # v4.7.18 D4: heat-wave relax-ceiling mode dropdown
            CONF_DPM_RELAX_CEILING_MODE,
            DEFAULT_DPM_RELAX_CEILING_MODE,
            DPM_RELAX_CEILING_MODES,
        )

        if user_input is not None:
            # v4.7.17.2: bucket-boundary CONFs removed from form; validation
            # block dropped (no cross-field check needed when there are no
            # boundary fields). New knobs are independent.
            _adv = user_input.get("advanced", user_input)

            # v4.7.18 D4: validate dropdown value server-side (HA SelectSelector
            # validates only on the FE — guard against direct API edits).
            _raw_mode = user_input.get(
                CONF_DPM_RELAX_CEILING_MODE, DEFAULT_DPM_RELAX_CEILING_MODE,
            )
            ceiling_mode = (
                _raw_mode if _raw_mode in DPM_RELAX_CEILING_MODES
                else DEFAULT_DPM_RELAX_CEILING_MODE
            )

            # Store house-wide CONFs in CM entry options.
            cm_update = {
                CONF_DYNAMIC_PRESET_ENABLED: bool(
                    user_input.get(CONF_DYNAMIC_PRESET_ENABLED, False)
                ),
                # v4.7.17.2: new operator knobs (visible-by-default).
                CONF_DPM_COOL_DAY_RELAX_F: float(
                    user_input.get(
                        CONF_DPM_COOL_DAY_RELAX_F,
                        DEFAULT_DPM_COOL_DAY_RELAX_F,
                    )
                ),
                CONF_DPM_HOT_DAY_TIGHTEN_F: float(
                    user_input.get(
                        CONF_DPM_HOT_DAY_TIGHTEN_F,
                        DEFAULT_DPM_HOT_DAY_TIGHTEN_F,
                    )
                ),
                # v4.7.18 D4: relax-ceiling mode (Skip relax on hot days).
                CONF_DPM_RELAX_CEILING_MODE: ceiling_mode,
                CONF_DYNAMIC_PRESET_DWELL_MINUTES: int(
                    _adv.get(CONF_DYNAMIC_PRESET_DWELL_MINUTES,
                             user_input.get(CONF_DYNAMIC_PRESET_DWELL_MINUTES, 60))
                ),
                CONF_DYNAMIC_PRESET_HYSTERESIS_F: float(
                    _adv.get(CONF_DYNAMIC_PRESET_HYSTERESIS_F,
                             user_input.get(CONF_DYNAMIC_PRESET_HYSTERESIS_F, 2.0))
                ),
            }
            _LOGGER.info(
                "DPM Surface 1 saved house-wide settings (enabled=%s, "
                "relax_f=%.1f, tighten_f=%.1f, relax_ceiling_mode=%s)",
                cm_update[CONF_DYNAMIC_PRESET_ENABLED],
                cm_update[CONF_DPM_COOL_DAY_RELAX_F],
                cm_update[CONF_DPM_HOT_DAY_TIGHTEN_F],
                cm_update[CONF_DPM_RELAX_CEILING_MODE],
            )
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                options={**self._config_entry.options, **cm_update},
            )
            return self.async_create_entry(title="", data=self._config_entry.options)

        # Initial render.
        return self.async_show_form(
            step_id="hvac_dynamic_preset",
            data_schema=self._build_hvac_dynamic_preset_schema(None),
        )

    def _build_hvac_dynamic_preset_schema(self, current_data) -> "vol.Schema":
        """Build voluptuous schema for hvac_dynamic_preset (Surface 1, v4.7.4 D1/D2).

        v4.7.4 D1: House-wide only — NO per-zone fields.
        v4.7.4 D2: 5 tunables wrapped in collapsed "Advanced (rarely change)" section.
        v4.7.18 D4: New `relax_ceiling_mode` dropdown ("Skip relax on hot days") —
            5 options: auto / conservative_85 / moderate_90 / aggressive_95 / off.
        """
        import voluptuous as vol
        from homeassistant.data_entry_flow import section
        from .domain_coordinators.energy_const import (
            CONF_DYNAMIC_PRESET_ENABLED,
            CONF_DYNAMIC_PRESET_DWELL_MINUTES,
            CONF_DYNAMIC_PRESET_HYSTERESIS_F,
            # v4.7.17.2: new operator-facing knobs
            CONF_DPM_COOL_DAY_RELAX_F,
            CONF_DPM_HOT_DAY_TIGHTEN_F,
            DEFAULT_DPM_COOL_DAY_RELAX_F,
            DEFAULT_DPM_HOT_DAY_TIGHTEN_F,
            # v4.7.18 D4: heat-wave relax-ceiling mode dropdown
            CONF_DPM_RELAX_CEILING_MODE,
            DEFAULT_DPM_RELAX_CEILING_MODE,
            DPM_RELAX_CEILING_MODE_AUTO,
            DPM_RELAX_CEILING_MODE_CONSERVATIVE_85,
            DPM_RELAX_CEILING_MODE_MODERATE_90,
            DPM_RELAX_CEILING_MODE_AGGRESSIVE_95,
            DPM_RELAX_CEILING_MODE_OFF,
            DPM_RELAX_CEILING_MODES,
        )

        def _f_cm(key, default):
            if current_data and key in current_data:
                v = current_data[key]
            else:
                v = self._config_entry.options.get(key)
            return float(v) if v is not None else default

        def _b_cm(key, default):
            if current_data and key in current_data:
                v = current_data[key]
            else:
                v = self._config_entry.options.get(key)
            return bool(v) if v is not None else default

        def _s_cm(key, default):
            """v4.7.18 D4: string-typed fetch for the relax_ceiling_mode dropdown."""
            if current_data and key in current_data:
                v = current_data[key]
            else:
                v = self._config_entry.options.get(key)
            return str(v) if v is not None else default

        # v4.7.18 D4 + fix-up C-M2: relax-ceiling mode dropdown. Labels +
        # per-option descriptions both come verbatim from planning §3
        # ("Operator-approved labels + helper text — DO NOT paraphrase").
        # HA's SelectOptionDict only carries {label, value}; per-option
        # descriptions are concatenated into the label with an em-dash
        # separator (the URA-precedent path — no `translation_key` plumbing
        # exists elsewhere in this file). DPM_RELAX_CEILING_MODES tuple in
        # energy_const.py mirrors the 5 option values. Default `auto`.
        _ceiling_mode_options = [
            {
                "label": (
                    "Auto (recommended) — Self-tuning based on your local "
                    "climate history. Adjusts seasonally."
                ),
                "value": DPM_RELAX_CEILING_MODE_AUTO,
            },
            {
                "label": (
                    "Conservative — skip above 85°F — Tighter comfort margin."
                ),
                "value": DPM_RELAX_CEILING_MODE_CONSERVATIVE_85,
            },
            {
                "label": (
                    "Moderate — skip above 90°F — Sane fallback for most "
                    "climates."
                ),
                "value": DPM_RELAX_CEILING_MODE_MODERATE_90,
            },
            {
                "label": (
                    "Aggressive — skip above 95°F — More relaxation; accepts "
                    "heat-wave drift."
                ),
                "value": DPM_RELAX_CEILING_MODE_AGGRESSIVE_95,
            },
            {
                "label": (
                    "Off — no ceiling — Pure rolling-median behavior "
                    "(v4.7.17.2 default)."
                ),
                "value": DPM_RELAX_CEILING_MODE_OFF,
            },
        ]
        # Defensive: if entry.options holds a non-matching string (manual
        # edit / future migration drift), surface the default instead of
        # letting the dropdown's FE validator reject the render.
        _current_mode = _s_cm(
            CONF_DPM_RELAX_CEILING_MODE, DEFAULT_DPM_RELAX_CEILING_MODE,
        )
        if _current_mode not in DPM_RELAX_CEILING_MODES:
            _current_mode = DEFAULT_DPM_RELAX_CEILING_MODE

        # v4.7.17.2: Surface 1 now shows 3 visible fields by default
        # (master toggle + relax + tighten); Advanced collapsed section
        # holds {dwell, hysteresis} only. Bucket-boundary CONFs removed
        # from form per operator framing ("internal mechanics MUST NOT
        # be exposed as control knobs"); they remain in const for the
        # diagnostic classify_bucket() bucket-label sensor.
        # v4.7.18 D4 adds the `relax_ceiling_mode` dropdown adjacent to
        # the existing relax/tighten knobs (visible-by-default).
        return vol.Schema({
            vol.Optional(
                CONF_DYNAMIC_PRESET_ENABLED,
                default=_b_cm(CONF_DYNAMIC_PRESET_ENABLED, False),
            ): bool,
            vol.Optional(
                CONF_DPM_COOL_DAY_RELAX_F,
                default=_f_cm(CONF_DPM_COOL_DAY_RELAX_F, DEFAULT_DPM_COOL_DAY_RELAX_F),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            vol.Optional(
                CONF_DPM_HOT_DAY_TIGHTEN_F,
                default=_f_cm(CONF_DPM_HOT_DAY_TIGHTEN_F, DEFAULT_DPM_HOT_DAY_TIGHTEN_F),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            # v4.7.18 D4: "Skip relax on hot days" — named-bucket dropdown.
            vol.Optional(
                CONF_DPM_RELAX_CEILING_MODE,
                default=_current_mode,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_ceiling_mode_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            # v4.7.4 D2: "Advanced (rarely change)" section — collapsed by default.
            # v4.7.17.2: only dwell + hysteresis remain here.
            vol.Optional("advanced"): section(
                vol.Schema({
                    vol.Optional(
                        CONF_DYNAMIC_PRESET_DWELL_MINUTES,
                        default=int(_f_cm(CONF_DYNAMIC_PRESET_DWELL_MINUTES, 60)),
                    ): vol.All(vol.Coerce(int), vol.Range(min=15, max=240)),
                    vol.Optional(
                        CONF_DYNAMIC_PRESET_HYSTERESIS_F,
                        default=_f_cm(CONF_DYNAMIC_PRESET_HYSTERESIS_F, 2.0),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=5.0)),
                }),
                {"collapsed": True},
            ),
        })

    # v4.7.18 D2: `_validate_dynamic_preset_input` deleted.
    #
    # The shared helper validated per-zone bucket-cell ranges (cool/mild/hot/
    # extreme home_low/home_high pairs + sleep-below-floor checks). D1 of
    # this cycle stripped Surface 2's bucket cells (the runtime no longer
    # reads them — the median-driven mechanic supersedes operator-tuned
    # ranges). With no caller remaining in production code, the helper is
    # dead. Obsolete v4.7.2 / v4.7.4 AST tests that asserted its existence
    # or its call from Surface 2 have been removed alongside it. The
    # `customize_buckets` toggle and the inline `_buckets_raw`/`_sleep_raw`
    # extraction blocks were removed in D1.

    async def async_step_hvac_baseline_presets(self, user_input=None):
        """HVAC Coordinator → Configure → Baseline Presets (Seasonal).

        v4.7.3 D1: 24 numeric inputs (3 seasons × 4 presets × 2 dims).
        v4.7.4 D4: Restructured into 3 section blocks by season (Summer/Shoulder/Winter).
        Added "Reset all to defaults" option via _reset_all boolean field that routes
        to the hvac_baseline_presets_reset_confirm confirmation step.

        Sections:
          - Summer (Jun–Sep): home/sleep/away/vacation × cool_high + heat_low
          - Shoulder (Mar–May, Oct–Nov): same structure
          - Winter (Dec–Feb): same structure

        Reset: if user checks "_reset_all" and submits, navigate to reset_confirm step.
        """
        import voluptuous as vol
        from homeassistant.data_entry_flow import section
        from .domain_coordinators.hvac_const import (
            BASELINE_MIN_DEADBAND,
            CONF_HVAC_BASELINE_SUMMER_HOME_COOL,
            CONF_HVAC_BASELINE_SUMMER_HOME_HEAT,
            CONF_HVAC_BASELINE_SUMMER_SLEEP_COOL,
            CONF_HVAC_BASELINE_SUMMER_SLEEP_HEAT,
            CONF_HVAC_BASELINE_SUMMER_AWAY_COOL,
            CONF_HVAC_BASELINE_SUMMER_AWAY_HEAT,
            CONF_HVAC_BASELINE_SUMMER_VACATION_COOL,
            CONF_HVAC_BASELINE_SUMMER_VACATION_HEAT,
            CONF_HVAC_BASELINE_SHOULDER_HOME_COOL,
            CONF_HVAC_BASELINE_SHOULDER_HOME_HEAT,
            CONF_HVAC_BASELINE_SHOULDER_SLEEP_COOL,
            CONF_HVAC_BASELINE_SHOULDER_SLEEP_HEAT,
            CONF_HVAC_BASELINE_SHOULDER_AWAY_COOL,
            CONF_HVAC_BASELINE_SHOULDER_AWAY_HEAT,
            CONF_HVAC_BASELINE_SHOULDER_VACATION_COOL,
            CONF_HVAC_BASELINE_SHOULDER_VACATION_HEAT,
            CONF_HVAC_BASELINE_WINTER_HOME_COOL,
            CONF_HVAC_BASELINE_WINTER_HOME_HEAT,
            CONF_HVAC_BASELINE_WINTER_SLEEP_COOL,
            CONF_HVAC_BASELINE_WINTER_SLEEP_HEAT,
            CONF_HVAC_BASELINE_WINTER_AWAY_COOL,
            CONF_HVAC_BASELINE_WINTER_AWAY_HEAT,
            CONF_HVAC_BASELINE_WINTER_VACATION_COOL,
            CONF_HVAC_BASELINE_WINTER_VACATION_HEAT,
            DEFAULT_HVAC_BASELINE_SUMMER_HOME_COOL,
            DEFAULT_HVAC_BASELINE_SUMMER_HOME_HEAT,
            DEFAULT_HVAC_BASELINE_SUMMER_SLEEP_COOL,
            DEFAULT_HVAC_BASELINE_SUMMER_SLEEP_HEAT,
            DEFAULT_HVAC_BASELINE_SUMMER_AWAY_COOL,
            DEFAULT_HVAC_BASELINE_SUMMER_AWAY_HEAT,
            DEFAULT_HVAC_BASELINE_SUMMER_VACATION_COOL,
            DEFAULT_HVAC_BASELINE_SUMMER_VACATION_HEAT,
            DEFAULT_HVAC_BASELINE_SHOULDER_HOME_COOL,
            DEFAULT_HVAC_BASELINE_SHOULDER_HOME_HEAT,
            DEFAULT_HVAC_BASELINE_SHOULDER_SLEEP_COOL,
            DEFAULT_HVAC_BASELINE_SHOULDER_SLEEP_HEAT,
            DEFAULT_HVAC_BASELINE_SHOULDER_AWAY_COOL,
            DEFAULT_HVAC_BASELINE_SHOULDER_AWAY_HEAT,
            DEFAULT_HVAC_BASELINE_SHOULDER_VACATION_COOL,
            DEFAULT_HVAC_BASELINE_SHOULDER_VACATION_HEAT,
            DEFAULT_HVAC_BASELINE_WINTER_HOME_COOL,
            DEFAULT_HVAC_BASELINE_WINTER_HOME_HEAT,
            DEFAULT_HVAC_BASELINE_WINTER_SLEEP_COOL,
            DEFAULT_HVAC_BASELINE_WINTER_SLEEP_HEAT,
            DEFAULT_HVAC_BASELINE_WINTER_AWAY_COOL,
            DEFAULT_HVAC_BASELINE_WINTER_AWAY_HEAT,
            DEFAULT_HVAC_BASELINE_WINTER_VACATION_COOL,
            DEFAULT_HVAC_BASELINE_WINTER_VACATION_HEAT,
        )

        # All 24 CONF keys grouped by season for validation + schema building
        _SUMMER_ROWS = [
            (CONF_HVAC_BASELINE_SUMMER_HOME_COOL, CONF_HVAC_BASELINE_SUMMER_HOME_HEAT,
             DEFAULT_HVAC_BASELINE_SUMMER_HOME_COOL, DEFAULT_HVAC_BASELINE_SUMMER_HOME_HEAT),
            (CONF_HVAC_BASELINE_SUMMER_SLEEP_COOL, CONF_HVAC_BASELINE_SUMMER_SLEEP_HEAT,
             DEFAULT_HVAC_BASELINE_SUMMER_SLEEP_COOL, DEFAULT_HVAC_BASELINE_SUMMER_SLEEP_HEAT),
            (CONF_HVAC_BASELINE_SUMMER_AWAY_COOL, CONF_HVAC_BASELINE_SUMMER_AWAY_HEAT,
             DEFAULT_HVAC_BASELINE_SUMMER_AWAY_COOL, DEFAULT_HVAC_BASELINE_SUMMER_AWAY_HEAT),
            (CONF_HVAC_BASELINE_SUMMER_VACATION_COOL, CONF_HVAC_BASELINE_SUMMER_VACATION_HEAT,
             DEFAULT_HVAC_BASELINE_SUMMER_VACATION_COOL, DEFAULT_HVAC_BASELINE_SUMMER_VACATION_HEAT),
        ]
        _SHOULDER_ROWS = [
            (CONF_HVAC_BASELINE_SHOULDER_HOME_COOL, CONF_HVAC_BASELINE_SHOULDER_HOME_HEAT,
             DEFAULT_HVAC_BASELINE_SHOULDER_HOME_COOL, DEFAULT_HVAC_BASELINE_SHOULDER_HOME_HEAT),
            (CONF_HVAC_BASELINE_SHOULDER_SLEEP_COOL, CONF_HVAC_BASELINE_SHOULDER_SLEEP_HEAT,
             DEFAULT_HVAC_BASELINE_SHOULDER_SLEEP_COOL, DEFAULT_HVAC_BASELINE_SHOULDER_SLEEP_HEAT),
            (CONF_HVAC_BASELINE_SHOULDER_AWAY_COOL, CONF_HVAC_BASELINE_SHOULDER_AWAY_HEAT,
             DEFAULT_HVAC_BASELINE_SHOULDER_AWAY_COOL, DEFAULT_HVAC_BASELINE_SHOULDER_AWAY_HEAT),
            (CONF_HVAC_BASELINE_SHOULDER_VACATION_COOL, CONF_HVAC_BASELINE_SHOULDER_VACATION_HEAT,
             DEFAULT_HVAC_BASELINE_SHOULDER_VACATION_COOL, DEFAULT_HVAC_BASELINE_SHOULDER_VACATION_HEAT),
        ]
        _WINTER_ROWS = [
            (CONF_HVAC_BASELINE_WINTER_HOME_COOL, CONF_HVAC_BASELINE_WINTER_HOME_HEAT,
             DEFAULT_HVAC_BASELINE_WINTER_HOME_COOL, DEFAULT_HVAC_BASELINE_WINTER_HOME_HEAT),
            (CONF_HVAC_BASELINE_WINTER_SLEEP_COOL, CONF_HVAC_BASELINE_WINTER_SLEEP_HEAT,
             DEFAULT_HVAC_BASELINE_WINTER_SLEEP_COOL, DEFAULT_HVAC_BASELINE_WINTER_SLEEP_HEAT),
            (CONF_HVAC_BASELINE_WINTER_AWAY_COOL, CONF_HVAC_BASELINE_WINTER_AWAY_HEAT,
             DEFAULT_HVAC_BASELINE_WINTER_AWAY_COOL, DEFAULT_HVAC_BASELINE_WINTER_AWAY_HEAT),
            (CONF_HVAC_BASELINE_WINTER_VACATION_COOL, CONF_HVAC_BASELINE_WINTER_VACATION_HEAT,
             DEFAULT_HVAC_BASELINE_WINTER_VACATION_COOL, DEFAULT_HVAC_BASELINE_WINTER_VACATION_HEAT),
        ]
        _ALL_ROWS = _SUMMER_ROWS + _SHOULDER_ROWS + _WINTER_ROWS

        errors: dict[str, str] = {}

        if user_input is not None:
            # D4: "Reset all to defaults" checkbox triggers confirmation step.
            if user_input.get("_reset_all", False):
                return await self.async_step_hvac_baseline_presets_reset_confirm()

            # Extract section contents (HA may nest or flatten them)
            _summer_vals = user_input.get("summer_section", user_input)
            _shoulder_vals = user_input.get("shoulder_section", user_input)
            _winter_vals = user_input.get("winter_section", user_input)

            # Build a flat lookup for validation (merge sections + top-level)
            _flat = {**user_input}
            for _src in (_summer_vals, _shoulder_vals, _winter_vals):
                if isinstance(_src, dict):
                    _flat.update(_src)

            # Validate deadband: each cool_high must exceed heat_low + BASELINE_MIN_DEADBAND
            for cool_key, heat_key, _cd, _hd in _ALL_ROWS:
                cool_val = float(_flat.get(cool_key, 77))
                heat_val = float(_flat.get(heat_key, 70))
                if cool_val - heat_val < BASELINE_MIN_DEADBAND:
                    errors["base"] = "baseline_preset_invalid_deadband"
                    break

            if not errors:
                # Save: merge flat values (section-extracted) into entry.options
                save_vals = {k: v for k, v in _flat.items()
                             if not k.startswith("_") and k not in ("summer_section", "shoulder_section", "winter_section")}
                _LOGGER.info(
                    "HVAC baseline presets saved (section layout) to CM entry.options",
                )
                return self.async_create_entry(
                    title="",
                    data={**self._config_entry.options, **save_vals},
                )

        # Build schema — 24 NumberSelector fields grouped into 3 season sections.
        _COOL_MIN = 65
        _COOL_MAX = 95
        _HEAT_MIN = 55
        _HEAT_MAX = 80

        def _row_schema(rows: list) -> vol.Schema:
            row_dict = {}
            for cool_key, heat_key, cool_default, heat_default in rows:
                row_dict[vol.Optional(
                    cool_key,
                    default=self._get_current(cool_key, cool_default),
                )] = selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=_COOL_MIN, max=_COOL_MAX, step=1,
                        unit_of_measurement="°F",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
                row_dict[vol.Optional(
                    heat_key,
                    default=self._get_current(heat_key, heat_default),
                )] = selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=_HEAT_MIN, max=_HEAT_MAX, step=1,
                        unit_of_measurement="°F",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
            return vol.Schema(row_dict)

        data_schema = vol.Schema({
            # v4.7.4 D4: 3 season sections (collapsed: False — open by default so user sees all)
            vol.Optional("summer_section"): section(
                _row_schema(_SUMMER_ROWS), {"collapsed": False}
            ),
            vol.Optional("shoulder_section"): section(
                _row_schema(_SHOULDER_ROWS), {"collapsed": False}
            ),
            vol.Optional("winter_section"): section(
                _row_schema(_WINTER_ROWS), {"collapsed": False}
            ),
            # D4: "Reset all to defaults" trigger (unchecked by default)
            vol.Optional("_reset_all", default=False): bool,
        })

        return self.async_show_form(
            step_id="hvac_baseline_presets",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_hvac_baseline_presets_reset_confirm(self, user_input=None):
        """Confirmation gate before resetting all 24 baseline CONFs to defaults.

        v4.7.4 D4: One-click destructive action is confirmation-gated.
        If user_input is None (initial render), show the confirmation form.
        If user confirms (submit with any input), clear all 24 CONFs and close.
        """
        if user_input is not None:
            # User confirmed — clear all 24 baseline CONFs from CM entry.options
            from .domain_coordinators.hvac_const import (
                CONF_HVAC_BASELINE_SUMMER_HOME_COOL,
                CONF_HVAC_BASELINE_SUMMER_HOME_HEAT,
                CONF_HVAC_BASELINE_SUMMER_SLEEP_COOL,
                CONF_HVAC_BASELINE_SUMMER_SLEEP_HEAT,
                CONF_HVAC_BASELINE_SUMMER_AWAY_COOL,
                CONF_HVAC_BASELINE_SUMMER_AWAY_HEAT,
                CONF_HVAC_BASELINE_SUMMER_VACATION_COOL,
                CONF_HVAC_BASELINE_SUMMER_VACATION_HEAT,
                CONF_HVAC_BASELINE_SHOULDER_HOME_COOL,
                CONF_HVAC_BASELINE_SHOULDER_HOME_HEAT,
                CONF_HVAC_BASELINE_SHOULDER_SLEEP_COOL,
                CONF_HVAC_BASELINE_SHOULDER_SLEEP_HEAT,
                CONF_HVAC_BASELINE_SHOULDER_AWAY_COOL,
                CONF_HVAC_BASELINE_SHOULDER_AWAY_HEAT,
                CONF_HVAC_BASELINE_SHOULDER_VACATION_COOL,
                CONF_HVAC_BASELINE_SHOULDER_VACATION_HEAT,
                CONF_HVAC_BASELINE_WINTER_HOME_COOL,
                CONF_HVAC_BASELINE_WINTER_HOME_HEAT,
                CONF_HVAC_BASELINE_WINTER_SLEEP_COOL,
                CONF_HVAC_BASELINE_WINTER_SLEEP_HEAT,
                CONF_HVAC_BASELINE_WINTER_AWAY_COOL,
                CONF_HVAC_BASELINE_WINTER_AWAY_HEAT,
                CONF_HVAC_BASELINE_WINTER_VACATION_COOL,
                CONF_HVAC_BASELINE_WINTER_VACATION_HEAT,
            )
            _BASELINE_CONFS = [
                CONF_HVAC_BASELINE_SUMMER_HOME_COOL, CONF_HVAC_BASELINE_SUMMER_HOME_HEAT,
                CONF_HVAC_BASELINE_SUMMER_SLEEP_COOL, CONF_HVAC_BASELINE_SUMMER_SLEEP_HEAT,
                CONF_HVAC_BASELINE_SUMMER_AWAY_COOL, CONF_HVAC_BASELINE_SUMMER_AWAY_HEAT,
                CONF_HVAC_BASELINE_SUMMER_VACATION_COOL, CONF_HVAC_BASELINE_SUMMER_VACATION_HEAT,
                CONF_HVAC_BASELINE_SHOULDER_HOME_COOL, CONF_HVAC_BASELINE_SHOULDER_HOME_HEAT,
                CONF_HVAC_BASELINE_SHOULDER_SLEEP_COOL, CONF_HVAC_BASELINE_SHOULDER_SLEEP_HEAT,
                CONF_HVAC_BASELINE_SHOULDER_AWAY_COOL, CONF_HVAC_BASELINE_SHOULDER_AWAY_HEAT,
                CONF_HVAC_BASELINE_SHOULDER_VACATION_COOL, CONF_HVAC_BASELINE_SHOULDER_VACATION_HEAT,
                CONF_HVAC_BASELINE_WINTER_HOME_COOL, CONF_HVAC_BASELINE_WINTER_HOME_HEAT,
                CONF_HVAC_BASELINE_WINTER_SLEEP_COOL, CONF_HVAC_BASELINE_WINTER_SLEEP_HEAT,
                CONF_HVAC_BASELINE_WINTER_AWAY_COOL, CONF_HVAC_BASELINE_WINTER_AWAY_HEAT,
                CONF_HVAC_BASELINE_WINTER_VACATION_COOL, CONF_HVAC_BASELINE_WINTER_VACATION_HEAT,
            ]
            new_opts = {k: v for k, v in self._config_entry.options.items()
                        if k not in _BASELINE_CONFS}
            _LOGGER.info(
                "HVAC baseline presets RESET to defaults — cleared %d CONFs",
                len(_BASELINE_CONFS),
            )
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                options=new_opts,
            )
            return self.async_create_entry(title="", data=new_opts)

        # Initial render: show confirmation form (no fields — user just submits to confirm)
        import voluptuous as vol
        return self.async_show_form(
            step_id="hvac_baseline_presets_reset_confirm",
            data_schema=vol.Schema({}),
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
            # v4.6.3 D10: Anomaly sensitivity
            vol.Optional(
                CONF_SECURITY_ANOMALY_SENSITIVITY,
                default=self._get_current(
                    CONF_SECURITY_ANOMALY_SENSITIVITY, DEFAULT_ANOMALY_SENSITIVITY
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "very_quiet", "label": "Very Quiet — only the loudest anomalies get flagged"},
                        {"value": "quiet", "label": "Quiet — fewer notifications, accepts more variability as normal"},
                        {"value": "normal", "label": "Normal — standard sensitivity, recommended for most homes"},
                        {"value": "sensitive", "label": "Sensitive — catches subtler anomalies, more notifications"},
                        {"value": "very_sensitive", "label": "Very Sensitive — flags small deviations; expect frequent advisories"},
                    ],
                    mode=selector.SelectSelectorMode.LIST,
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
            # v5.10.0 D2: sleep + night suppression
            CONF_MF_SLEEP_SUPPRESS,
            CONF_MF_NIGHT_SUPPRESS_MODE,
            MF_NIGHT_MODES,
            DEFAULT_MF_COOLDOWN_SECONDS,
            DEFAULT_MF_HIGH_CONFIDENCE_DISTANCE,
            DEFAULT_MF_PING_PONG_WINDOW,
            DEFAULT_MF_VERIFY_DELAY,
            DEFAULT_MF_UNJOIN_DELAY,
            DEFAULT_MF_POSITION_OFFSET,
            DEFAULT_MF_MIN_CONFIDENCE,
            DEFAULT_MF_SLEEP_SUPPRESS,
            DEFAULT_MF_NIGHT_SUPPRESS_MODE,
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
            # v4.6.3 D10: Anomaly sensitivity
            vol.Optional(
                CONF_MUSIC_ANOMALY_SENSITIVITY,
                default=self._get_current(
                    CONF_MUSIC_ANOMALY_SENSITIVITY, DEFAULT_ANOMALY_SENSITIVITY
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "very_quiet", "label": "Very Quiet — only the loudest anomalies get flagged"},
                        {"value": "quiet", "label": "Quiet — fewer notifications, accepts more variability as normal"},
                        {"value": "normal", "label": "Normal — standard sensitivity, recommended for most homes"},
                        {"value": "sensitive", "label": "Sensitive — catches subtler anomalies, more notifications"},
                        {"value": "very_sensitive", "label": "Very Sensitive — flags small deviations; expect frequent advisories"},
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            # v5.10.0 D2: Sleep + night suppression. Defaults: ON /
            # dwell_only (the conservative option per critique §4).
            vol.Optional(
                CONF_MF_SLEEP_SUPPRESS,
                default=self._get_current(
                    CONF_MF_SLEEP_SUPPRESS, DEFAULT_MF_SLEEP_SUPPRESS,
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_MF_NIGHT_SUPPRESS_MODE,
                default=self._get_current(
                    CONF_MF_NIGHT_SUPPRESS_MODE, DEFAULT_MF_NIGHT_SUPPRESS_MODE,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "off", "label": "Off — follow music normally at night"},
                        {"value": "dwell_only", "label": "Own bedroom only — currently unwired; behaves as 'block all' + logs a warning until per-person bedroom mapping ships"},
                        {"value": "block_all", "label": "Block all — never transfer music at night"},
                    ],
                    mode=selector.SelectSelectorMode.LIST,
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
            CONF_NM_IMESSAGE_ENABLED, CONF_NM_IMESSAGE_SEVERITY,
            CONF_NM_TTS_ENABLED, CONF_NM_TTS_SEVERITY, CONF_NM_TTS_SPEAKERS,
            CONF_NM_LIGHTS_ENABLED, CONF_NM_LIGHTS_SEVERITY, CONF_NM_ALERT_LIGHTS,
            DEFAULT_NM_PUSHOVER_SEVERITY, DEFAULT_NM_COMPANION_SEVERITY,
            DEFAULT_NM_WHATSAPP_SEVERITY, DEFAULT_NM_IMESSAGE_SEVERITY,
            DEFAULT_NM_TTS_SEVERITY, DEFAULT_NM_LIGHTS_SEVERITY,
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
                CONF_NM_IMESSAGE_ENABLED,
                default=self._get_current(CONF_NM_IMESSAGE_ENABLED, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_NM_IMESSAGE_SEVERITY,
                default=self._get_current(CONF_NM_IMESSAGE_SEVERITY, DEFAULT_NM_IMESSAGE_SEVERITY),
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
            CONF_NM_PERSON_PUSHOVER_DEVICE,
            CONF_NM_PERSON_COMPANION_SERVICE, CONF_NM_PERSON_WHATSAPP_PHONE,
            CONF_NM_PERSON_IMESSAGE_HANDLE,
            CONF_NM_PERSON_DELIVERY_PREF, CONF_NM_PERSON_DIGEST_MORNING,
            CONF_NM_PERSON_DIGEST_EVENING_ENABLED, CONF_NM_PERSON_DIGEST_EVENING,
            CONF_NM_PERSON_DIGEST_CHANNELS, NM_DIGEST_CHANNELS,
            NM_DELIVERY_IMMEDIATE, NM_DELIVERY_DIGEST, NM_DELIVERY_OFF,
        )

        if user_input is not None:
            # Store as a single-person entry in the persons list
            pending = getattr(self, "_nm_pending", {**self._config_entry.options})
            persons = list(pending.get(CONF_NM_PERSONS, []))
            person_entry = {
                CONF_NM_PERSON_ENTITY: user_input.get(CONF_NM_PERSON_ENTITY, ""),
                CONF_NM_PERSON_PUSHOVER_KEY: user_input.get(CONF_NM_PERSON_PUSHOVER_KEY, ""),
                CONF_NM_PERSON_PUSHOVER_DEVICE: user_input.get(CONF_NM_PERSON_PUSHOVER_DEVICE, ""),
                CONF_NM_PERSON_COMPANION_SERVICE: user_input.get(CONF_NM_PERSON_COMPANION_SERVICE, ""),
                CONF_NM_PERSON_WHATSAPP_PHONE: user_input.get(CONF_NM_PERSON_WHATSAPP_PHONE, ""),
                CONF_NM_PERSON_IMESSAGE_HANDLE: user_input.get(CONF_NM_PERSON_IMESSAGE_HANDLE, ""),
                CONF_NM_PERSON_DELIVERY_PREF: user_input.get(CONF_NM_PERSON_DELIVERY_PREF, NM_DELIVERY_IMMEDIATE),
                CONF_NM_PERSON_DIGEST_MORNING: user_input.get(CONF_NM_PERSON_DIGEST_MORNING, "08:00"),
                CONF_NM_PERSON_DIGEST_EVENING_ENABLED: user_input.get(CONF_NM_PERSON_DIGEST_EVENING_ENABLED, False),
                CONF_NM_PERSON_DIGEST_EVENING: user_input.get(CONF_NM_PERSON_DIGEST_EVENING, "18:00"),
                CONF_NM_PERSON_DIGEST_CHANNELS: user_input.get(CONF_NM_PERSON_DIGEST_CHANNELS, []),
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
                CONF_NM_PERSON_PUSHOVER_DEVICE,
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
                CONF_NM_PERSON_IMESSAGE_HANDLE,
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
            vol.Optional(
                CONF_NM_PERSON_DIGEST_CHANNELS,
                default=[],
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(NM_DIGEST_CHANNELS),
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
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
            CONF_NM_SAFE_WORD,
            CONF_NM_SILENCE_DURATION,
            DEFAULT_NM_SILENCE_DURATION,
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
            vol.Optional(
                CONF_NM_SAFE_WORD,
                default=self._get_current(CONF_NM_SAFE_WORD, ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(
                CONF_NM_SILENCE_DURATION,
                default=self._get_current(CONF_NM_SILENCE_DURATION, DEFAULT_NM_SILENCE_DURATION),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=120, step=5, unit_of_measurement="min")
            ),
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

    async def async_step_coordinator_notifications_volume(self, user_input=None):
        """NM Cycle A-2 — rung-2 knobs for Cycle-A noise reduction.

        Groups: A1 tripped-breaker window+route, A3 lock dedup, A4 humidity
        ladder + swing, A5 CO2/TVOC + discovery blocklist, A2 optimizer
        HIGH allowlist. Defaults sourced from `const.py` `DEFAULT_*`; behavior
        with no options set is byte-identical to v5.24.0.

        All keys are in `OPTIONS_RELOAD_SUPPRESS_KEYS` and `_NO_LIVE_ATTR_KEYS`;
        saving here does NOT trigger a CM reload. Consumers read via
        `nm_cycle_a_knob(...)`, cached process-wide; the update-listener
        flushes the cache before the next tick.
        """
        from .const import (
            CONF_TRIPPED_BREAKER_ZERO_WINDOW_S,
            DEFAULT_TRIPPED_BREAKER_ZERO_WINDOW_S,
            CONF_TRIPPED_BREAKER_ROUTE_NM,
            DEFAULT_TRIPPED_BREAKER_ROUTE_NM,
            CONF_LOCK_UNAVAILABLE_DEDUP_S,
            DEFAULT_LOCK_UNAVAILABLE_DEDUP_S,
            CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT,
            DEFAULT_HUMIDITY_NORMAL_LOG_ONLY_PCT,
            CONF_HUMIDITY_NORMAL_MEDIUM_PCT,
            DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT,
            CONF_HUMIDITY_NORMAL_HIGH_PCT,
            DEFAULT_HUMIDITY_NORMAL_HIGH_PCT,
            CONF_HUMIDITY_SWING_DELTA_PCT,
            DEFAULT_HUMIDITY_SWING_DELTA_PCT,
            CONF_HUMIDITY_SWING_MIN_ABS_PCT,
            DEFAULT_HUMIDITY_SWING_MIN_ABS_PCT,
            CONF_CO2_LOG_ONLY_CEILING_PPM,
            DEFAULT_CO2_LOG_ONLY_CEILING_PPM,
            CONF_TVOC_ABSOLUTE_HIGH_PPB,
            DEFAULT_TVOC_ABSOLUTE_HIGH_PPB,
            CONF_TVOC_SUSTAINED_S,
            DEFAULT_TVOC_SUSTAINED_S,
            CONF_SAFETY_DISCOVERY_BLOCKLIST,
            DEFAULT_SAFETY_DISCOVERY_BLOCKLIST,
            CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
            DEFAULT_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
            OPTIMIZER_DIMENSIONS_ALL,
            CONF_STUCK_SIGNAL_NM_ENABLED,
            DEFAULT_STUCK_SIGNAL_NM_ENABLED,
        )

        # NM Cycle A-2 fix-up (A2, 2026-07-20): the humidity ladder must
        # remain monotonic (log_only <= medium <= high). A miskey (e.g.
        # medium=90, high=80) silently inverts the escalation logic in
        # safety.py. Enforce on save with a form re-render + errors dict.
        # NM Cycle A-2 fix-up (C-MED-1, 2026-07-20): drop any submitted
        # key whose value equals its DEFAULT_* (numeric-compared for
        # NumberSelector floats). This keeps unchanged fields OUT of the
        # persisted options so future const retunes reach deployments
        # (the "open form + save" gesture no longer freezes defaults).
        # Fields previously persisted then reset-to-default are REMOVED.
        _DEFAULTS = {
            CONF_TRIPPED_BREAKER_ZERO_WINDOW_S: DEFAULT_TRIPPED_BREAKER_ZERO_WINDOW_S,
            CONF_TRIPPED_BREAKER_ROUTE_NM: DEFAULT_TRIPPED_BREAKER_ROUTE_NM,
            CONF_LOCK_UNAVAILABLE_DEDUP_S: DEFAULT_LOCK_UNAVAILABLE_DEDUP_S,
            CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT: DEFAULT_HUMIDITY_NORMAL_LOG_ONLY_PCT,
            CONF_HUMIDITY_NORMAL_MEDIUM_PCT: DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT,
            CONF_HUMIDITY_NORMAL_HIGH_PCT: DEFAULT_HUMIDITY_NORMAL_HIGH_PCT,
            CONF_HUMIDITY_SWING_DELTA_PCT: DEFAULT_HUMIDITY_SWING_DELTA_PCT,
            CONF_HUMIDITY_SWING_MIN_ABS_PCT: DEFAULT_HUMIDITY_SWING_MIN_ABS_PCT,
            CONF_CO2_LOG_ONLY_CEILING_PPM: DEFAULT_CO2_LOG_ONLY_CEILING_PPM,
            CONF_TVOC_ABSOLUTE_HIGH_PPB: DEFAULT_TVOC_ABSOLUTE_HIGH_PPB,
            CONF_TVOC_SUSTAINED_S: DEFAULT_TVOC_SUSTAINED_S,
            CONF_SAFETY_DISCOVERY_BLOCKLIST: list(DEFAULT_SAFETY_DISCOVERY_BLOCKLIST),
            CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS:
                list(DEFAULT_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS),
            # Stuck-Signal Watchdog kill switch (v5.35.0).
            CONF_STUCK_SIGNAL_NM_ENABLED: DEFAULT_STUCK_SIGNAL_NM_ENABLED,
        }

        def _equals_default(key, submitted):
            expected = _DEFAULTS[key]
            # Numeric compare handles NumberSelector's float(85.0) == int(85).
            if isinstance(expected, (int, float)) and not isinstance(expected, bool):
                try:
                    return float(submitted) == float(expected)
                except (TypeError, ValueError):
                    return False
            if isinstance(expected, (list, tuple)):
                # Order-independent compare for both allowlist + blocklist.
                try:
                    return sorted(submitted) == sorted(expected)
                except TypeError:
                    return list(submitted) == list(expected)
            return submitted == expected

        errors: dict[str, str] = {}
        if user_input is not None:
            # (a) Coerce allowlist to lowercased list[str] BEFORE the equality
            # check so persisted lowercase never re-persists after a reopen.
            raw_allow = user_input.get(CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS)
            if isinstance(raw_allow, (list, tuple, set, frozenset)):
                user_input[CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS] = [
                    str(x).lower() for x in raw_allow
                ]
            if user_input.get(CONF_SAFETY_DISCOVERY_BLOCKLIST) is None:
                user_input[CONF_SAFETY_DISCOVERY_BLOCKLIST] = []

            # (b) Humidity ladder monotonicity (A2 fix-up).
            def _hget(k):
                if k in user_input:
                    try:
                        return float(user_input[k])
                    except (TypeError, ValueError):
                        return None
                return float(_DEFAULTS[k])
            low = _hget(CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT)
            med = _hget(CONF_HUMIDITY_NORMAL_MEDIUM_PCT)
            high = _hget(CONF_HUMIDITY_NORMAL_HIGH_PCT)
            if (low is not None and med is not None and high is not None
                    and not (low <= med <= high)):
                errors["base"] = "nm_a4_humidity_ladder_not_monotonic"

            if errors:
                # Re-render below with the submitted values re-defaulted.
                pass
            else:
                # (c) Drop keys whose value equals DEFAULT_*. This runs against
                # the (potentially normalized) `user_input`, so a re-opened form
                # saved untouched leaves the persisted-options gain at zero.
                new_opts = dict(self._config_entry.options)
                for key in _DEFAULTS:
                    if key in user_input and _equals_default(key, user_input[key]):
                        # Remove previously-persisted value that has been
                        # reset to default; do NOT re-persist.
                        new_opts.pop(key, None)
                    elif key in user_input:
                        new_opts[key] = user_input[key]
                return self.async_create_entry(title="", data=new_opts)

        allowlist_options = [
            {"value": v, "label": v} for v in OPTIMIZER_DIMENSIONS_ALL
        ]

        data_schema = vol.Schema({
            # --- A1: tripped-breaker ---
            vol.Optional(
                CONF_TRIPPED_BREAKER_ZERO_WINDOW_S,
                default=self._get_current(
                    CONF_TRIPPED_BREAKER_ZERO_WINDOW_S,
                    DEFAULT_TRIPPED_BREAKER_ZERO_WINDOW_S,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=7200, step=60,
                    unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_TRIPPED_BREAKER_ROUTE_NM,
                default=self._get_current(
                    CONF_TRIPPED_BREAKER_ROUTE_NM,
                    DEFAULT_TRIPPED_BREAKER_ROUTE_NM,
                ),
            ): selector.BooleanSelector(),
            # --- A3: lock dedup ---
            vol.Optional(
                CONF_LOCK_UNAVAILABLE_DEDUP_S,
                default=self._get_current(
                    CONF_LOCK_UNAVAILABLE_DEDUP_S,
                    DEFAULT_LOCK_UNAVAILABLE_DEDUP_S,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=604800, step=60,
                    unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            # --- A4: humidity ladder + swing ---
            vol.Optional(
                CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT,
                default=self._get_current(
                    CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT,
                    DEFAULT_HUMIDITY_NORMAL_LOG_ONLY_PCT,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=200, step=1,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_HUMIDITY_NORMAL_MEDIUM_PCT,
                default=self._get_current(
                    CONF_HUMIDITY_NORMAL_MEDIUM_PCT,
                    DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=200, step=1,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_HUMIDITY_NORMAL_HIGH_PCT,
                default=self._get_current(
                    CONF_HUMIDITY_NORMAL_HIGH_PCT,
                    DEFAULT_HUMIDITY_NORMAL_HIGH_PCT,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=200, step=1,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_HUMIDITY_SWING_DELTA_PCT,
                default=self._get_current(
                    CONF_HUMIDITY_SWING_DELTA_PCT,
                    DEFAULT_HUMIDITY_SWING_DELTA_PCT,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=100, step=1,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_HUMIDITY_SWING_MIN_ABS_PCT,
                default=self._get_current(
                    CONF_HUMIDITY_SWING_MIN_ABS_PCT,
                    DEFAULT_HUMIDITY_SWING_MIN_ABS_PCT,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=200, step=1,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            # --- A5: CO2 / TVOC / discovery blocklist ---
            vol.Optional(
                CONF_CO2_LOG_ONLY_CEILING_PPM,
                default=self._get_current(
                    CONF_CO2_LOG_ONLY_CEILING_PPM,
                    DEFAULT_CO2_LOG_ONLY_CEILING_PPM,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=10000, step=50,
                    unit_of_measurement="ppm",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_TVOC_ABSOLUTE_HIGH_PPB,
                default=self._get_current(
                    CONF_TVOC_ABSOLUTE_HIGH_PPB,
                    DEFAULT_TVOC_ABSOLUTE_HIGH_PPB,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=100000, step=50,
                    unit_of_measurement="ppb",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_TVOC_SUSTAINED_S,
                default=self._get_current(
                    CONF_TVOC_SUSTAINED_S,
                    DEFAULT_TVOC_SUSTAINED_S,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=86400, step=60,
                    unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_SAFETY_DISCOVERY_BLOCKLIST,
                default=list(self._get_current(
                    CONF_SAFETY_DISCOVERY_BLOCKLIST,
                    list(DEFAULT_SAFETY_DISCOVERY_BLOCKLIST),
                ) or []),
            ): selector.EntitySelector(
                # A3 fix-up (2026-07-20): safety discovery is not sensor-only
                # (breaker `binary_sensor`s, leak binaries, etc.) — accept both.
                selector.EntitySelectorConfig(
                    domain=["sensor", "binary_sensor"], multiple=True,
                )
            ),
            # --- A2: optimizer HIGH allowlist (empty by design) ---
            vol.Optional(
                CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
                default=list(self._get_current(
                    CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
                    list(DEFAULT_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS),
                ) or []),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=allowlist_options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            # --- Stuck-Signal Watchdog kill switch (v5.35.0) ---
            # Rung-2 knob per PLANNING_stuck_signal_watchdog.md: an
            # operator may want to silence stuck_signal NM emits during
            # a known-bad Frigate outage without a code push. Detection +
            # discount logic keeps running with this off; only NM is
            # suppressed.
            vol.Optional(
                CONF_STUCK_SIGNAL_NM_ENABLED,
                default=self._get_current(
                    CONF_STUCK_SIGNAL_NM_ENABLED,
                    DEFAULT_STUCK_SIGNAL_NM_ENABLED,
                ),
            ): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="coordinator_notifications_volume",
            data_schema=data_schema,
            errors=errors or None,
        )

    async def async_step_coordinator_notifications_routing(self, user_input=None):
        """NM Cycle C-2 (2026-07-22) — D1 routing UI + D2 life-safety extras.

        Authors the four Cycle-C CONF keys (routing matrix, hazard overrides,
        DND-bypass, mute-default duration) plus the D2 additive-only
        ``CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS`` knob. Mirrors the A-2 step's
        save-side contract (default-drop, options-clobber-safe merged
        writes, lowercase coercion, form re-render on validation error).

        All 5 keys are in ``_NO_LIVE_ATTR_KEYS`` + ``OPTIONS_RELOAD_SUPPRESS_KEYS``
        (via ``_NM_C_KEYS`` in ``__init__.py``); saving here does NOT
        trigger a CM reload. NM re-reads via ``_refresh_config`` +
        ``is_life_safety_hazard(...)`` reads via cached
        ``nm_cycle_a_knob`` (flushed by the CM update listener).

        The routing matrix / hazard-overrides / DND-bypass keys are
        persisted as dict/list shapes matching what the NM router already
        consumes (``notification_manager.py`` ``_route_for_recipient`` +
        ``_recipient_bypasses_dnd``). The per-person nested grid UX is
        deferred to a future cycle; this step's ObjectSelector surface
        lets the operator author the exact persisted shape (matches the
        service-YAML pattern for other object-shape options).
        """
        from .const import (
            CONF_NM_PERSON_ROUTING_MATRIX,
            CONF_NM_PERSON_HAZARD_OVERRIDES,
            CONF_NM_PERSON_DND_BYPASS_SEVERITIES,
            CONF_NM_MUTE_DEFAULT_DURATION_MINUTES,
            DEFAULT_NM_MUTE_DEFAULT_DURATION_MINUTES,
            CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS,
            DEFAULT_NM_EXTRA_LIFE_SAFETY_HAZARDS,
            NM_LIFE_SAFETY_HAZARDS,
            NM_CHANNELS_KNOWN,
        )
        from .domain_coordinators.safety import HazardType

        # D2 selector options: HazardType members NOT already in the base
        # rung-1 frozenset. Kill-switch: empty list = base only.
        extras_candidates = [
            {"value": t.value, "label": t.value}
            for t in HazardType
            if t.value not in NM_LIFE_SAFETY_HAZARDS
        ]

        # Cycle C valid severity vocabulary (mirrors the notifications step).
        _VALID_SEVERITIES = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})
        _VALID_CHANNELS = frozenset(NM_CHANNELS_KNOWN)

        _DEFAULTS = {
            CONF_NM_PERSON_ROUTING_MATRIX: {},
            CONF_NM_PERSON_HAZARD_OVERRIDES: {},
            CONF_NM_PERSON_DND_BYPASS_SEVERITIES: {},
            CONF_NM_MUTE_DEFAULT_DURATION_MINUTES:
                DEFAULT_NM_MUTE_DEFAULT_DURATION_MINUTES,
            CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS:
                list(DEFAULT_NM_EXTRA_LIFE_SAFETY_HAZARDS),
        }

        def _canonical(value):
            """Order-independent canonical form for dict/list compare."""
            if isinstance(value, dict):
                return tuple(sorted(
                    (str(k), _canonical(v)) for k, v in value.items()
                ))
            if isinstance(value, (list, tuple, set, frozenset)):
                try:
                    return tuple(sorted(_canonical(v) for v in value))
                except TypeError:
                    return tuple(_canonical(v) for v in value)
            return value

        def _equals_default(key, submitted):
            expected = _DEFAULTS[key]
            if isinstance(expected, (int, float)) and not isinstance(expected, bool):
                try:
                    return float(submitted) == float(expected)
                except (TypeError, ValueError):
                    return False
            return _canonical(submitted) == _canonical(expected)

        def _coerce_matrix(m):
            """Lowercase channel + hazard tokens; uppercase severities (Bug Class #22).

            Persisted shape:
                {person_id: {SEVERITY: {channel: bool}}}
            Router reads SEVERITY as ``severity.name.upper()`` and channel
            names against ``NM_CHANNELS_KNOWN`` (lowercase).
            """
            if not isinstance(m, dict):
                return {}
            out: dict = {}
            for person, sev_map in m.items():
                if not isinstance(sev_map, dict):
                    continue
                out[str(person)] = {}
                for sev, ch_map in sev_map.items():
                    sev_key = str(sev).upper()
                    if not isinstance(ch_map, dict):
                        continue
                    out[str(person)][sev_key] = {
                        str(ch).lower(): bool(v) for ch, v in ch_map.items()
                    }
            return out

        def _coerce_overrides(o):
            """Shape: {person_id: {hazard_type: {SEVERITY: {channel: bool}}}}."""
            if not isinstance(o, dict):
                return {}
            out: dict = {}
            for person, hz_map in o.items():
                if not isinstance(hz_map, dict):
                    continue
                out[str(person)] = {}
                for hz, sev_map in hz_map.items():
                    hz_key = str(hz).lower()
                    if not isinstance(sev_map, dict):
                        continue
                    out[str(person)][hz_key] = {}
                    for sev, ch_map in sev_map.items():
                        sev_key = str(sev).upper()
                        if not isinstance(ch_map, dict):
                            continue
                        out[str(person)][hz_key][sev_key] = {
                            str(ch).lower(): bool(v) for ch, v in ch_map.items()
                        }
            return out

        def _coerce_dnd(d):
            """Shape: {person_id: [SEVERITY, ...]}."""
            if not isinstance(d, dict):
                return {}
            out: dict = {}
            for person, sev_list in d.items():
                if not isinstance(sev_list, (list, tuple, set, frozenset)):
                    continue
                out[str(person)] = sorted({
                    str(s).upper() for s in sev_list
                })
            return out

        errors: dict[str, str] = {}
        if user_input is not None:
            # Coerce all matrix keys BEFORE default-drop so a re-opened
            # form saved untouched leaves persisted-options gain at zero.
            raw_matrix = user_input.get(CONF_NM_PERSON_ROUTING_MATRIX) or {}
            raw_overrides = user_input.get(CONF_NM_PERSON_HAZARD_OVERRIDES) or {}
            raw_dnd = user_input.get(CONF_NM_PERSON_DND_BYPASS_SEVERITIES) or {}
            matrix = _coerce_matrix(raw_matrix)
            overrides = _coerce_overrides(raw_overrides)
            dnd = _coerce_dnd(raw_dnd)
            # C-2 fix-up A5: silent coercion-drops are hostile. If a
            # top-level per-person value was non-dict (matrix/overrides)
            # or non-list (dnd), the coerce funcs quietly drop the row.
            # Surface it as a validation error so the operator sees the
            # broken submission instead of a phantom-successful save.
            def _dropped_top_level(raw_dict: object, expect_dict_values: bool) -> bool:
                if not isinstance(raw_dict, dict):
                    return False
                for _v in raw_dict.values():
                    ok = isinstance(_v, dict) if expect_dict_values else isinstance(
                        _v, (list, tuple, set, frozenset)
                    )
                    if not ok:
                        return True
                return False
            if (
                _dropped_top_level(raw_matrix, expect_dict_values=True)
                or _dropped_top_level(raw_overrides, expect_dict_values=True)
                or _dropped_top_level(raw_dnd, expect_dict_values=False)
            ):
                errors["base"] = "nm_c2_coercion_dropped_row"

            # D2 extras: lowercase, dedup, allowlist coercion.
            raw_extras = user_input.get(CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS)
            if isinstance(raw_extras, (list, tuple, set, frozenset)):
                extras_lower = [str(x).lower() for x in raw_extras]
                # Vocabulary-authority guard (Cycle-B A-CRIT-1 sibling):
                # extras must be canonical HazardType tokens AND must NOT
                # be in the base rung-1 frozenset (additive-only).
                valid_extras_tokens = {
                    t.value for t in HazardType
                    if t.value not in NM_LIFE_SAFETY_HAZARDS
                }
                bad = [x for x in extras_lower if x not in valid_extras_tokens]
                if bad:
                    errors["base"] = "nm_c2_extras_unknown_hazard"
                extras_coerced = sorted(set(extras_lower))
            else:
                extras_coerced = list(DEFAULT_NM_EXTRA_LIFE_SAFETY_HAZARDS)

            # Matrix-row completeness: every configured (person, severity)
            # row must reference a known channel (mixed unknown keys
            # re-render). All-false rows are the legal "silent" case.
            for person, sev_map in matrix.items():
                for sev, ch_map in sev_map.items():
                    if sev not in _VALID_SEVERITIES:
                        errors["base"] = "nm_c2_matrix_unknown_severity"
                    for ch in ch_map:
                        if ch not in _VALID_CHANNELS:
                            # C-2 fix-up A7: rename from
                            # ``nm_c2_matrix_row_incomplete`` — the true
                            # cause is an unknown channel token, mirror
                            # the overrides error-key vocabulary.
                            errors["base"] = "nm_c2_matrix_unknown_channel"

            # Overrides: same channel-vocabulary guard.
            for person, hz_map in overrides.items():
                for hz, sev_map in hz_map.items():
                    for sev, ch_map in sev_map.items():
                        if sev not in _VALID_SEVERITIES:
                            errors["base"] = "nm_c2_overrides_unknown_severity"
                        for ch in ch_map:
                            if ch not in _VALID_CHANNELS:
                                errors["base"] = "nm_c2_overrides_unknown_channel"

            # DND-bypass: severities must be canonical.
            for person, sev_list in dnd.items():
                for sev in sev_list:
                    if sev not in _VALID_SEVERITIES:
                        errors["base"] = "nm_c2_dnd_unknown_severity"

            # Mute duration bounds guard.
            try:
                mute_val = int(
                    user_input.get(
                        CONF_NM_MUTE_DEFAULT_DURATION_MINUTES,
                        DEFAULT_NM_MUTE_DEFAULT_DURATION_MINUTES,
                    )
                )
                if mute_val < 0 or mute_val > 1440:
                    errors["base"] = "nm_c2_mute_duration_out_of_range"
            except (TypeError, ValueError):
                errors["base"] = "nm_c2_mute_duration_invalid"
                mute_val = int(DEFAULT_NM_MUTE_DEFAULT_DURATION_MINUTES)

            if not errors:
                # Options-clobber-safe merged write (v3.2.3.1 trap):
                # start from full options dict, mutate ONLY our keys.
                # Number-persistence no-clobber: the mute-duration
                # Number entity (NMMuteDefaultDurationNumber) writes the
                # same CONF key on its setter; we route through the same
                # merged-dict pattern so neither surface loses writes.
                new_opts = dict(self._config_entry.options)
                coerced = {
                    CONF_NM_PERSON_ROUTING_MATRIX: matrix,
                    CONF_NM_PERSON_HAZARD_OVERRIDES: overrides,
                    CONF_NM_PERSON_DND_BYPASS_SEVERITIES: dnd,
                    CONF_NM_MUTE_DEFAULT_DURATION_MINUTES: mute_val,
                    CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS: extras_coerced,
                }
                for key, val in coerced.items():
                    if _equals_default(key, val):
                        new_opts.pop(key, None)
                    else:
                        new_opts[key] = val
                return self.async_create_entry(title="", data=new_opts)

        # Form render — object-shape defaults from persisted options.
        cur_matrix = self._get_current(CONF_NM_PERSON_ROUTING_MATRIX, {}) or {}
        cur_overrides = self._get_current(CONF_NM_PERSON_HAZARD_OVERRIDES, {}) or {}
        cur_dnd = self._get_current(CONF_NM_PERSON_DND_BYPASS_SEVERITIES, {}) or {}
        cur_mute = int(self._get_current(
            CONF_NM_MUTE_DEFAULT_DURATION_MINUTES,
            DEFAULT_NM_MUTE_DEFAULT_DURATION_MINUTES,
        ))
        cur_extras = list(self._get_current(
            CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS,
            list(DEFAULT_NM_EXTRA_LIFE_SAFETY_HAZARDS),
        ) or [])

        data_schema = vol.Schema({
            vol.Optional(
                CONF_NM_PERSON_ROUTING_MATRIX,
                default=cur_matrix,
            ): selector.ObjectSelector(),
            vol.Optional(
                CONF_NM_PERSON_HAZARD_OVERRIDES,
                default=cur_overrides,
            ): selector.ObjectSelector(),
            vol.Optional(
                CONF_NM_PERSON_DND_BYPASS_SEVERITIES,
                default=cur_dnd,
            ): selector.ObjectSelector(),
            vol.Optional(
                CONF_NM_MUTE_DEFAULT_DURATION_MINUTES,
                default=cur_mute,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=1440, step=1,
                    unit_of_measurement="minutes",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS,
                default=cur_extras,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=extras_candidates,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })

        return self.async_show_form(
            step_id="coordinator_notifications_routing",
            data_schema=data_schema,
            errors=errors or None,
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
    # v3.22.0: SIGNAL RESPONSE CONFIGURATION
    # =========================================================================

    async def async_step_signal_responses(self, user_input=None):
        """Configure cross-coordinator signal response toggles.

        v3.22.0: All toggles default OFF. Each controls whether a coordinator
        reacts to a specific cross-system signal (e.g., HVAC stopping fans
        on hazard, security unlocking doors on fire).
        """
        from .const import (
            CONF_HVAC_ON_HAZARD_STOP_FANS,
            CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS,
            CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED,
            CONF_ENERGY_ON_HAZARD_SHED_LOADS,
            CONF_MUSIC_ON_HAZARD_STOP,
            CONF_MUSIC_ON_ARRIVAL_START,
            CONF_MUSIC_ON_SECURITY_STOP,
        )

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, **user_input},
            )

        data_schema = vol.Schema({
            vol.Optional(
                CONF_HVAC_ON_HAZARD_STOP_FANS,
                default=self._get_current(CONF_HVAC_ON_HAZARD_STOP_FANS, False),
            ): selector.BooleanSelector(),
            # feature/freeze-floor: the "Emergency heat on freeze hazard" toggle
            # was removed here — the freeze response is now an unconditional,
            # HC-owned heat_cool LOW floor (FREEZE_FLOOR via the setpoint
            # chokepoint), not a single-mode-heat switch and not config-gated.
            # CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT remains in const.py (harmless;
            # avoids an options migration) but is no longer surfaced.
            vol.Optional(
                CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS,
                default=self._get_current(CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED,
                default=self._get_current(CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ENERGY_ON_HAZARD_SHED_LOADS,
                default=self._get_current(CONF_ENERGY_ON_HAZARD_SHED_LOADS, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_MUSIC_ON_HAZARD_STOP,
                default=self._get_current(CONF_MUSIC_ON_HAZARD_STOP, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_MUSIC_ON_ARRIVAL_START,
                default=self._get_current(CONF_MUSIC_ON_ARRIVAL_START, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_MUSIC_ON_SECURITY_STOP,
                default=self._get_current(CONF_MUSIC_ON_SECURITY_STOP, False),
            ): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="signal_responses",
            data_schema=data_schema,
        )

    # =========================================================================
    # v4.7.34 Phase 1 D7: Optimization Coordinator options section
    # =========================================================================

    async def async_step_coordinator_optimization(self, user_input=None):
        """Configure the URA Optimization Coordinator (autonomy matrix + caps).

        Pillar B (Phase 5) reshape: the 11-field flat form is grouped into
        three regions — Autonomy (top-level), `optimizer_guards`
        (collapsed safety guards), `optimizer_llm` (collapsed LLM tier).
        Both collapsed sections flatten back to top-level options on save
        so the chokepoint / LLM tier (which read `entry.options` fresh
        on every cycle) see the same flat key surface they do today.
        Parsimony: zero new CONF keys land here beyond the Pillar B
        confirm-guard key, which is operated via entity buttons (not the
        form).
        """
        from homeassistant.data_entry_flow import section
        from .const import (
            CONF_OPTIMIZER_AUTONOMY_LEVEL,
            CONF_OPTIMIZER_KILL_SWITCH,
            CONF_OPTIMIZER_CONFIDENCE_GATE,
            CONF_OPTIMIZER_RATE_CAP_PER_HOUR,
            CONF_OPTIMIZER_QUIET_HOURS_SOURCE,
            CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL,
            # v4.7.35 Phase 2 — LLM Tier-2 CM-options keys.
            CONF_OPTIMIZER_LLM_TASK_ENTITY,
            CONF_OPTIMIZER_LLM_TRIAGE_ENTITY,
            CONF_OPTIMIZER_LLM_SYSTEM_PROMPT,
            CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
            CONF_OPTIMIZER_SAFETY_DENY_ENTITIES,
            DEFAULT_OPTIMIZER_AUTONOMY_LEVEL,
            DEFAULT_OPTIMIZER_KILL_SWITCH,
            DEFAULT_OPTIMIZER_CONFIDENCE_GATE,
            DEFAULT_OPTIMIZER_RATE_CAP_PER_HOUR,
            DEFAULT_OPTIMIZER_QUIET_HOURS_SOURCE,
            DEFAULT_OPTIMIZER_LLM_TASK_ENTITY,
            DEFAULT_OPTIMIZER_LLM_TRIAGE_ENTITY,
            DEFAULT_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
            DEFAULT_OPTIMIZER_SAFETY_DENY_ENTITIES,
            OPTIMIZER_AUTONOMY_LEVELS,
            OPTIMIZER_QUIET_HOURS_SOURCES,
        )

        if user_input is not None:
            # Pillar B: flatten the two collapsed sections BEFORE persist
            # so the chokepoint / LLM tier readers see the same flat keys.
            flat = dict(user_input)
            guards = flat.pop("optimizer_guards", None)
            if isinstance(guards, dict):
                flat = {**flat, **guards}
            llm = flat.pop("optimizer_llm", None)
            if isinstance(llm, dict):
                flat = {**flat, **llm}
            # Pillar B (Phase 5) fix-up A-H1 / B-M2: the form is an
            # unguarded entry point that can directly set the autonomy
            # rung. A stale `CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL` from
            # an in-flight confirm-guard escalation MUST NOT survive a
            # direct form save — otherwise the operator would commit a
            # new level here while a stale pending value keeps the select
            # entity stuck in "pending_<other>" state. Strip it on save.
            merged_options = {**self._config_entry.options, **flat}
            merged_options.pop(CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL, None)
            # Push the select entity to refresh from the post-save
            # options so the UI leaves any `pending_*` state immediately
            # rather than waiting for the CM reload. Mirrors the slot used
            # by the Confirm / Cancel buttons.
            try:
                sel = (
                    self.hass.data.get(DOMAIN, {}).get(
                        "optimizer_autonomy_select",
                    )
                )
                if sel is not None and hasattr(sel, "_refresh_from_options"):
                    sel._refresh_from_options()
            except Exception:  # noqa: BLE001
                pass
            return self.async_create_entry(
                title="",
                data=merged_options,
            )

        # Autonomy rung labels (Pillar B D2): plain-English options carried
        # via the SelectSelector label/value pattern. Values are unchanged
        # so the existing CONF migration is a no-op.
        autonomy_options = [
            {"value": "advisory", "label": "Observe only — no actions"},
            {"value": "shadow",
             "label": "Shadow mode — predicted actions, no actuation (default)"},
            {"value": "reversible_device",
             "label": "Reversible devices only — lights, fans, HVAC setpoints"},
            {"value": "propose_config",
             "label": "Propose config changes — 30s veto window"},
            {"value": "immediate_config",
             "label": "Apply config changes immediately — ±20% clamp"},
            {"value": "unbounded",
             "label": "Unbounded — no allowlist, no clamp (NOT RECOMMENDED)"},
        ]
        quiet_options = [
            {"value": "reuse_nm",
             "label": "Use Notification Manager quiet hours"},
            {"value": "none", "label": "None — ignore quiet hours"},
        ]

        guards_schema = vol.Schema({
            vol.Optional(
                CONF_OPTIMIZER_CONFIDENCE_GATE,
                default=self._get_current(
                    CONF_OPTIMIZER_CONFIDENCE_GATE,
                    DEFAULT_OPTIMIZER_CONFIDENCE_GATE,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0, max=1.0, step=0.05,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_OPTIMIZER_RATE_CAP_PER_HOUR,
                default=self._get_current(
                    CONF_OPTIMIZER_RATE_CAP_PER_HOUR,
                    DEFAULT_OPTIMIZER_RATE_CAP_PER_HOUR,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=200, step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_OPTIMIZER_QUIET_HOURS_SOURCE,
                default=self._get_current(
                    CONF_OPTIMIZER_QUIET_HOURS_SOURCE,
                    DEFAULT_OPTIMIZER_QUIET_HOURS_SOURCE,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=quiet_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            # B-B2 fix-up: safety / security deny-list.
            vol.Optional(
                CONF_OPTIMIZER_SAFETY_DENY_ENTITIES,
                default=self._get_current(
                    CONF_OPTIMIZER_SAFETY_DENY_ENTITIES,
                    list(DEFAULT_OPTIMIZER_SAFETY_DENY_ENTITIES),
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[],
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })

        llm_schema = vol.Schema({
            vol.Optional(
                CONF_OPTIMIZER_LLM_TASK_ENTITY,
                default=self._get_current(
                    CONF_OPTIMIZER_LLM_TASK_ENTITY,
                    DEFAULT_OPTIMIZER_LLM_TASK_ENTITY,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=self._discover_ai_task_entities(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                )
            ),
            vol.Optional(
                CONF_OPTIMIZER_LLM_TRIAGE_ENTITY,
                default=self._get_current(
                    CONF_OPTIMIZER_LLM_TRIAGE_ENTITY,
                    DEFAULT_OPTIMIZER_LLM_TRIAGE_ENTITY,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    # A-HIGH-1 fix-up: empty string explicitly available
                    # so the operator can disable triage routing.
                    options=[""] + self._discover_ai_task_entities(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                )
            ),
            vol.Optional(
                CONF_OPTIMIZER_LLM_SYSTEM_PROMPT,
                default=self._get_current(
                    CONF_OPTIMIZER_LLM_SYSTEM_PROMPT, "",
                ),
            ): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
            vol.Optional(
                CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
                default=self._get_current(
                    CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
                    DEFAULT_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=500, step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        })

        data_schema = vol.Schema({
            vol.Optional(
                CONF_OPTIMIZER_AUTONOMY_LEVEL,
                default=self._get_current(
                    CONF_OPTIMIZER_AUTONOMY_LEVEL,
                    DEFAULT_OPTIMIZER_AUTONOMY_LEVEL,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=autonomy_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_OPTIMIZER_KILL_SWITCH,
                default=self._get_current(
                    CONF_OPTIMIZER_KILL_SWITCH,
                    DEFAULT_OPTIMIZER_KILL_SWITCH,
                ),
            ): selector.BooleanSelector(),
            vol.Optional("optimizer_guards"): section(
                guards_schema, {"collapsed": True},
            ),
            vol.Optional("optimizer_llm"): section(
                llm_schema, {"collapsed": True},
            ),
        })

        return self.async_show_form(
            step_id="coordinator_optimization",
            data_schema=data_schema,
        )

    # =========================================================================
    # v5.21.0 fix-up (operator scope change 2026-07-17): the standalone
    # `async_step_coordinator_baec` was folded INTO
    # `async_step_coordinator_energy` as sibling `baec` + `baec_advanced`
    # sections, mirroring the INCLEMENT_ADVANCED_SECTION / cloud_verification
    # precedent. Flatten-on-save at :3634-3644 restores flat CONF_ENERGY_DP_*
    # keys, so the CM options-listener + `_EC_SETTER_DISPATCH` see the same
    # shape they always have. The retired step body is deleted below.
    # =========================================================================

    def _discover_ai_task_entities(self) -> list[str]:
        """Return the list of `ai_task.*` entity_ids currently registered.

        Falls back to the default Claude entity when no AI Task
        integrations are installed, so the dropdown always has at least
        one option for the operator to select / override.
        """
        from .const import DEFAULT_OPTIMIZER_LLM_TASK_ENTITY
        entities: list[str] = []
        try:
            for state in self.hass.states.async_all():
                if state.entity_id.startswith("ai_task."):
                    entities.append(state.entity_id)
        except Exception:  # noqa: BLE001
            pass
        if DEFAULT_OPTIMIZER_LLM_TASK_ENTITY not in entities:
            entities.append(DEFAULT_OPTIMIZER_LLM_TASK_ENTITY)
        return sorted(set(entities))

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

        v4.7.5 D1+D2: Renders as a vertical menu (SelectSelectorMode.LIST) of
        RAW house zones from `entry.options["zones"]`. The canonical thermostat-
        keyed merge in `iter_canonical_hvac_zones` is a runtime-only concern for
        the HVAC coordinator — the picker MUST NEVER display the merged
        "Entertainment + Master Suite" label. See PLANNING_v4.7.5 §D2/D3 and
        QUALITY_CONTEXT.md "Lazy Canonical Resolution".

        When 2+ house zones share a thermostat, each gets a "(shared thermostat)"
        suffix as a quick-glance cue; the full sibling list + thermostat entity
        renders on `zone_config_menu` (D4 banner).
        """
        errors = {}

        if user_input is not None:
            selected_zone = user_input.get("zone_name")
            if selected_zone:
                self._selected_zone_name = selected_zone
                return await self.async_step_zone_config_menu()
            else:
                errors["base"] = "no_zone_selected"

        # v4.7.5 D2 lock-in: read RAW house zones. Do NOT import or call
        # iter_canonical_hvac_zones from this method. See AST regression
        # test test_v475_d2_picker_does_not_call_iter_canonical.
        zones_data: dict = {}
        entry = self._config_entry
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
            merged = {**entry.data, **entry.options}
            zones_data = merged.get("zones", {})
        else:
            # Fallback: find Zone Manager entry
            for ce in self.hass.config_entries.async_entries(DOMAIN):
                if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
                    merged = {**ce.data, **ce.options}
                    zones_data = merged.get("zones", {})
                    break

        # v4.7.5 D2: shared-thermostat suffix. Count thermostat occurrences
        # across the SAME zones dict — purely local computation, no merge call.
        thermostat_to_count: dict[str, int] = {}
        for _zname, _zcfg in zones_data.items():
            _t = _zcfg.get(CONF_ZONE_THERMOSTAT)
            if _t:
                thermostat_to_count[_t] = thermostat_to_count.get(_t, 0) + 1

        zone_options = []
        for zone_name, zone_cfg in zones_data.items():
            label = zone_name.title()
            _t = zone_cfg.get(CONF_ZONE_THERMOSTAT)
            if _t and thermostat_to_count.get(_t, 0) >= 2:
                label = f"{label} (shared thermostat)"
            zone_options.append({"label": label, "value": zone_name})

        if not zone_options:
            return self.async_abort(reason="no_zones_configured")

        # v4.7.5 D1: list-mode renders a vertical menu instead of a dropdown.
        # SelectSelectorMode is a StrEnum with exactly two members (LIST,
        # DROPDOWN); verified against HA core helpers.selector source.
        data_schema = vol.Schema({
            vol.Required("zone_name"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=zone_options,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        })

        return self.async_show_form(
            step_id="manage_zones",
            data_schema=data_schema,
            errors=errors,
        )

    def _render_shared_thermostat_banner(self, zone_name: str | None) -> str:
        """v4.7.5 D4 (post-review A-M2): render the shared-thermostat banner
        text for `zone_config_menu`.

        READ-ONLY HELPER. This method MUST stay side-effect-free: it only
        reads `entry.data` / `entry.options` and returns a formatted string.
        Do NOT extend with mutation (no `async_update_entry`, no dispatcher
        sends, no `hass.async_create_task`). The banner is rendered inside a
        try/except that swallows to `_LOGGER.debug` — any mutation in here
        would be silently lost on error. Bug Class #7 (Stale Data Source)
        guard: even though we only read, the safety contract is explicit so
        future maintainers do not accidentally introduce a derived-value
        write-back path.

        Args:
            zone_name: The selected zone name on the ZM flow, or None on the
                legacy zone-entry path (where the banner is intentionally
                empty — legacy entries have no sibling concept).

        Returns:
            A non-empty banner string (prefixed with two newlines so it
            renders below the static description) when the zone has at least
            one shared-thermostat sibling; empty string otherwise (including
            on any error — the menu render must never fail).
        """
        if zone_name is None:
            return ""
        try:
            zm_entry = self._find_zone_manager_entry()
            if zm_entry is None:
                return ""
            siblings = self._get_shared_thermostat_siblings(
                zm_entry, zone_name,
            )
            if not siblings:
                return ""
            merged = {**zm_entry.data, **zm_entry.options}
            zones = merged.get("zones", {})
            thermostat = zones.get(zone_name, {}).get(
                CONF_ZONE_THERMOSTAT, ""
            )
            sibling_text = ", ".join(siblings)
            return (
                f"\n\n**Shared thermostat:** This zone shares "
                f"thermostat `{thermostat}` with {sibling_text}. "
                "HVAC, energy, and Dynamic Preset settings saved "
                "here also apply to those zones automatically."
            )
        except Exception:  # noqa: BLE001 — never fail menu render
            _LOGGER.debug(
                "v4.7.5 banner derivation failed for zone=%s",
                zone_name, exc_info=True,
            )
            return ""

    async def async_step_zone_config_menu(self, user_input=None):
        """Show zone configuration submenu after selecting a zone (v3.3.3).

        v3.6.0-c2.3: Support zones stored in Zone Manager entry (not legacy
        zone entries). Uses _selected_zone_name when available.

        v4.7.5 D4: When the selected zone shares its thermostat with sibling
        house zones, render an Option C banner via description_placeholders
        explaining that HVAC/energy/DPM saves auto-mirror to those siblings.
        """
        # v3.6.0-c2.3: Allow routing via _selected_zone_name (ZM flow)
        # v4.7.5 post-review (Reviewer B H1 fix): make the legacy zone-entry
        # path control flow explicit. `zone_name` is only set on the ZM-flow
        # path; on the legacy `_get_zone_entry()` path it remains None and the
        # banner is intentionally skipped (legacy zone entries have no
        # shared-thermostat-sibling concept). The abort guard catches
        # zone_not_found on the legacy path.
        zone_name = getattr(self, "_selected_zone_name", None)
        zone_entry = None
        if not zone_name:
            zone_entry = self._get_zone_entry()
            if not zone_entry:
                return self.async_abort(reason="zone_not_found")

        # v4.7.5 D4 banner: detect shared-thermostat siblings, build placeholders.
        # v4.7.5 post-review (A-M2): banner rendering extracted into a dedicated
        # read-only helper. Keeping the derivation as a side-effect-free method
        # matches the surrounding `_build_*` / `_get_*` convention used in this
        # file and makes the read-only contract explicit at the call site (the
        # method takes no writable state and returns only a string).
        banner = self._render_shared_thermostat_banner(zone_name)

        return self.async_show_menu(
            step_id="zone_config_menu",
            menu_options=[
                "zone_rooms",
                "zone_media",
                "zone_hvac",
                "zone_energy",  # v4.1.0: Zone power/energy sensors
                "zone_persons",  # v3.18.5
                "zone_cameras",  # v3.19.0
                "zone_dynamic_preset",  # v4.7.1 Cycle B: Dynamic Preset per-zone config
                # Zone Delete Flow D1: last option, visually separated in strings.json.
                "zone_delete_confirm",
            ],
            description_placeholders={"banner": banner},
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
            # v5.7.0 WS-A4: per-zone outdoor flag.
            current_zone_is_outdoor = bool(zone_data.get(
                CONF_ZONE_IS_OUTDOOR, DEFAULT_ZONE_IS_OUTDOOR
            ))
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
            # v5.7.0 WS-A4: per-zone outdoor flag.
            current_zone_is_outdoor = bool(
                zone_entry.options.get(
                    CONF_ZONE_IS_OUTDOOR,
                    zone_entry.data.get(
                        CONF_ZONE_IS_OUTDOOR, DEFAULT_ZONE_IS_OUTDOOR
                    ),
                )
            )

        if user_input is not None:
            zone_name = user_input.get(CONF_ZONE_NAME, "").strip()
            selected_rooms = user_input.get(CONF_ZONE_ROOMS, [])
            old_zone_name = orig_zone_name if zm_result else current_zone_name

            # v4.7.5 post-review (A-H3): reject ' + ' in zone names so the
            # canonical merge separator stays unambiguous.
            if zone_name and _ZONE_NAME_PLUS_SEPARATOR_RE.search(zone_name):
                return self.async_show_form(
                    step_id="zone_rooms",
                    data_schema=vol.Schema({
                        vol.Required(CONF_ZONE_NAME, default=zone_name): str,
                        vol.Optional(CONF_ZONE_DESCRIPTION, default=current_zone_desc): str,
                        vol.Optional(CONF_ZONE_ROOMS, default=selected_rooms): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[],
                                multiple=True,
                                mode=selector.SelectSelectorMode.LIST,
                            )
                        ),
                    }),
                    errors={"base": "zone_name_contains_plus"},
                )

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
                # v3.6.0-c2.3: Update zone in ZM entry's zones dict.
                # v4.7.5 D4 (post-review H1 fix): route rooms through
                # _auto_mirror_to_siblings so the helper handles save + rename
                # atomically in ONE async_update_entry call. MIRROR_KEYS_ZONE_ROOMS
                # is empty by design (Entertainment has different rooms than
                # Master Suite) — helper is a no-op for the mirror itself, but
                # the centralized save path keeps the "one save = one
                # update_entry" invariant intact.
                rooms_payload = {
                    CONF_ZONE_DESCRIPTION: user_input.get(
                        CONF_ZONE_DESCRIPTION, ""
                    ),
                    CONF_ZONE_ROOMS: selected_rooms,
                    # v5.7.0 WS-A4: persist outdoor flag in ZM zones dict.
                    CONF_ZONE_IS_OUTDOOR: bool(user_input.get(
                        CONF_ZONE_IS_OUTDOOR, current_zone_is_outdoor
                    )),
                }
                self._auto_mirror_to_siblings(
                    zm_entry,
                    zone_name,
                    rooms_payload,
                    MIRROR_KEYS_ZONE_ROOMS,
                    rename_from=(
                        old_zone_name if old_zone_name != zone_name else None
                    ),
                )
                self._selected_zone_name = zone_name
                return await self.async_step_zone_config_menu()
            elif self._selected_zone_entry_id:
                new_zone_options = {
                    **zone_entry.options,
                    CONF_ZONE_NAME: zone_name,
                    CONF_ZONE_DESCRIPTION: user_input.get(CONF_ZONE_DESCRIPTION, ""),
                    CONF_ZONE_ROOMS: selected_rooms,
                    # v5.7.0 WS-A4: persist outdoor flag on legacy zone entries.
                    CONF_ZONE_IS_OUTDOOR: bool(user_input.get(
                        CONF_ZONE_IS_OUTDOOR, current_zone_is_outdoor
                    )),
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
                        # v5.7.0 WS-A4.
                        CONF_ZONE_IS_OUTDOOR: bool(user_input.get(
                            CONF_ZONE_IS_OUTDOOR, current_zone_is_outdoor
                        )),
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
            # v5.7.0 WS-A4: outdoor zone toggle on zone edit form.
            vol.Optional(
                CONF_ZONE_IS_OUTDOOR,
                default=current_zone_is_outdoor,
            ): selector.BooleanSelector(),
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
                # v4.7.5 D4: media is per-house-zone (MIRROR_KEYS_ZONE_MEDIA
                # is empty). Use the helper for save-path symmetry; mirror is
                # a no-op for media.
                self._auto_mirror_to_siblings(
                    zm_entry, zone_name, dict(user_input), MIRROR_KEYS_ZONE_MEDIA,
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

        # v4.5.11: AC ramp-down per-zone fields (ac_load_sensor for Span/
        # Emporia/etc. kW sensor; ac_ramp_zone_enabled for per-zone opt-out).
        from .domain_coordinators.hvac_const import (
            CONF_HVAC_AC_LOAD_SENSOR,
            CONF_HVAC_AC_RAMP_ZONE_ENABLED,
            DEFAULT_HVAC_AC_RAMP_ZONE_ENABLED,
        )

        if zm_result:
            zm_entry, zone_name, zone_data = zm_result
            current_thermostat = zone_data.get(CONF_ZONE_THERMOSTAT)
            current_ac_load_sensor = zone_data.get(CONF_HVAC_AC_LOAD_SENSOR, "")
            current_ac_ramp_enabled = zone_data.get(
                CONF_HVAC_AC_RAMP_ZONE_ENABLED,
                DEFAULT_HVAC_AC_RAMP_ZONE_ENABLED,
            )
        else:
            current_thermostat = zone_entry.options.get(
                CONF_ZONE_THERMOSTAT,
                zone_entry.data.get(CONF_ZONE_THERMOSTAT),
            )
            current_ac_load_sensor = zone_entry.options.get(
                CONF_HVAC_AC_LOAD_SENSOR,
                zone_entry.data.get(CONF_HVAC_AC_LOAD_SENSOR, ""),
            )
            current_ac_ramp_enabled = zone_entry.options.get(
                CONF_HVAC_AC_RAMP_ZONE_ENABLED,
                zone_entry.data.get(
                    CONF_HVAC_AC_RAMP_ZONE_ENABLED,
                    DEFAULT_HVAC_AC_RAMP_ZONE_ENABLED,
                ),
            )

        if user_input is not None:
            if zm_result:
                # v4.7.5 D4: HVAC fields tie to the shared thermostat. Auto-mirror
                # to sibling house zones (Option C). Capture the OLD thermostat
                # BEFORE the save so the unlink path (reassignment) can mirror
                # to the old sibling group one final time.
                old_thermostat = current_thermostat
                self._auto_mirror_to_siblings(
                    zm_entry, zone_name, dict(user_input),
                    MIRROR_KEYS_ZONE_HVAC,
                    old_thermostat=old_thermostat,
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

        # Schema build: keep existing thermostat field; add v4.5.11 fields.
        # ac_load_sensor accepts kW OR kWh sensors (we filter by device_class
        # at runtime — power preferred, but energy works if user only has
        # kWh totalizers).
        schema_fields: dict = {
            vol.Optional(
                CONF_ZONE_THERMOSTAT,
                default=current_thermostat or vol.UNDEFINED,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Optional(
                CONF_HVAC_AC_LOAD_SENSOR,
                default=current_ac_load_sensor or vol.UNDEFINED,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class=["power", "energy"],
                )
            ),
            vol.Optional(
                CONF_HVAC_AC_RAMP_ZONE_ENABLED,
                default=bool(current_ac_ramp_enabled),
            ): selector.BooleanSelector(),
        }

        return self.async_show_form(
            step_id="zone_hvac",
            data_schema=vol.Schema(schema_fields),
        )

    async def async_step_zone_energy(self, user_input=None):
        """Configure zone power/energy sensors (v4.1.0).

        Sets power and energy sensors for zone-level loads (HVAC circuits,
        subpanel meters) that aren't attributable to individual rooms.
        """
        zm_result = self._get_zm_zone_data()
        zone_entry = None if zm_result else self._get_zone_entry()
        if not zm_result and not zone_entry:
            return self.async_abort(reason="zone_not_found")

        if zm_result:
            zm_entry, zone_name, zone_data = zm_result
            current_power = zone_data.get(CONF_ZONE_POWER_SENSORS, [])
            current_energy = zone_data.get(CONF_ZONE_ENERGY_SENSORS, [])
            # v4.7.5 post-review (Reviewer B H3): capture old thermostat so the
            # unlink path can mirror to the previous sibling group one final
            # time if a thermostat reassignment is in flight in this session.
            current_thermostat = zone_data.get(CONF_ZONE_THERMOSTAT)
        else:
            current_power = zone_entry.options.get(
                CONF_ZONE_POWER_SENSORS,
                zone_entry.data.get(CONF_ZONE_POWER_SENSORS, []),
            )
            current_energy = zone_entry.options.get(
                CONF_ZONE_ENERGY_SENSORS,
                zone_entry.data.get(CONF_ZONE_ENERGY_SENSORS, []),
            )
            # Legacy entries don't carry shared-thermostat semantics.
            current_thermostat = None

        if user_input is not None:
            if zm_result:
                # v4.7.5 D4: zone power/energy sensors track the shared AC
                # sub-circuit; auto-mirror to sibling house zones.
                # v4.7.5 post-review (Reviewer B H3): pass old_thermostat so
                # the helper's unlink path mirrors energy data to the previous
                # sibling group when a thermostat reassignment happens during
                # this options-flow session.
                self._auto_mirror_to_siblings(
                    zm_entry, zone_name, dict(user_input),
                    MIRROR_KEYS_ZONE_ENERGY,
                    old_thermostat=current_thermostat,
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
                CONF_ZONE_POWER_SENSORS,
                default=current_power or vol.UNDEFINED,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
            ),
            vol.Optional(
                CONF_ZONE_ENERGY_SENSORS,
                default=current_energy or vol.UNDEFINED,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
            ),
        })

        return self.async_show_form(
            step_id="zone_energy",
            data_schema=data_schema,
        )

    async def async_step_zone_persons(self, user_input=None):
        """Configure primary persons for a zone.

        v3.18.5: Select person entities who primarily live in this zone.
        Used for pre-arrival HVAC pre-conditioning on geofence arrival.
        """
        from .domain_coordinators.hvac_const import CONF_ZONE_PERSONS

        # v3.6.0-c2.3: Try ZM flow first
        zm_result = self._get_zm_zone_data()
        zone_entry = None if zm_result else self._get_zone_entry()
        if not zm_result and not zone_entry:
            return self.async_abort(reason="zone_not_found")

        if zm_result:
            zm_entry, zone_name, zone_data = zm_result
            current_persons = zone_data.get(CONF_ZONE_PERSONS, [])

            if user_input is not None:
                # v4.7.5 D4: zone persons are per-house-zone (different
                # bedrooms have different sleepers). MIRROR_KEYS_ZONE_PERSONS
                # is empty so the helper is a no-op mirror; we use it for
                # save-path symmetry.
                _persons_payload = {
                    CONF_ZONE_PERSONS: user_input.get(CONF_ZONE_PERSONS, []),
                }
                self._auto_mirror_to_siblings(
                    zm_entry, zone_name, _persons_payload,
                    MIRROR_KEYS_ZONE_PERSONS,
                )
                return await self.async_step_zone_config_menu()

            data_schema = vol.Schema({
                vol.Optional(
                    CONF_ZONE_PERSONS,
                    default=current_persons,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="person",
                        multiple=True,
                    )
                ),
            })

            return self.async_show_form(
                step_id="zone_persons",
                data_schema=data_schema,
                description_placeholders={"zone_name": zone_name},
            )

        # Legacy zone entry fallback (shouldn't normally reach here)
        return self.async_abort(reason="zone_not_found")

    async def async_step_zone_cameras(self, user_input=None):
        """Configure zone cameras for face-confirmed arrivals.

        v3.19.0: Select person detection cameras in this zone's shared spaces.
        Face recognition from these cameras enables instant pre-arrival.
        """
        from .domain_coordinators.hvac_const import CONF_ZONE_CAMERAS

        zm_result = self._get_zm_zone_data()
        zone_entry = None if zm_result else self._get_zone_entry()
        if not zm_result and not zone_entry:
            return self.async_abort(reason="zone_not_found")

        if zm_result:
            zm_entry, zone_name, zone_data = zm_result
            current_cameras = zone_data.get(CONF_ZONE_CAMERAS, [])

            if user_input is not None:
                # v4.7.5 D4: zone cameras are per-house-zone (different
                # camera coverage per physical room). MIRROR_KEYS_ZONE_CAMERAS
                # is empty so the helper is a no-op mirror.
                _cameras_payload = {
                    CONF_ZONE_CAMERAS: user_input.get(CONF_ZONE_CAMERAS, []),
                }
                self._auto_mirror_to_siblings(
                    zm_entry, zone_name, _cameras_payload,
                    MIRROR_KEYS_ZONE_CAMERAS,
                )
                return await self.async_step_zone_config_menu()

            data_schema = vol.Schema({
                vol.Optional(
                    CONF_ZONE_CAMERAS,
                    default=current_cameras,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="binary_sensor",
                        device_class=["occupancy", "motion"],
                        multiple=True,
                    )
                ),
            })

            return self.async_show_form(
                step_id="zone_cameras",
                data_schema=data_schema,
                description_placeholders={"zone_name": zone_name},
            )

        return self.async_abort(reason="zone_not_found")

    async def async_step_zone_dynamic_preset(self, user_input=None):
        """Configure Dynamic Preset per-zone options (v4.7.1 Cycle B / v4.7.4 D3).

        v4.7.4 D3: Simplified Surface 2 default view. Bucket cells now live in
        collapsed sections (section-collapse pattern) to reduce visible knob count.

        Default-visible fields (3 settings + 2 section expanders):
        - zone_dynamic_preset_enabled (master toggle for this zone)
        - zone_dynamic_preset_offset (offset °F)
        - zone_dynamic_preset_reset_offset_guest (reset offset under guest mode)
        - zone_dynamic_preset_customize_buckets section (collapsed by default)
        - zone_dynamic_preset_sleep_enabled + sleep cells section (collapsed)

        When "Customize Bucket Ranges" section is expanded: 8 home-preset cells.
        When "Sleep Preset Ranges" section is expanded: sleep_enabled toggle + 8 cells.
        Bucket cells omitted from form when customize_buckets=False (derived at runtime).

        v4.7.5 D3 — REPLACES the v4.7.x C/H2 canonical-remap.
            The earlier hack called `iter_canonical_hvac_zones` to remap
            `_selected_zone_name` from a raw house zone ("Master Suite") to
            the canonical merged label ("Entertainment + Master Suite"), so
            DPM data was persisted under the canonical key the EC evaluation
            loop reads. v4.7.5 replaces this with:
              1. Save DPM data under the RAW house zone (whatever the picker
                 selected); mirror to sibling house zones via D4 auto-mirror.
              2. Read-side: the EC evaluation loop in energy.py resolves a
                 canonical merged name back to its constituent raw house
                 zones (see Lazy Canonical Resolution in QUALITY_CONTEXT.md).
            Per D3, this method MUST NOT import or call
            `iter_canonical_hvac_zones`. Locked by AST regression
            test_v475_d3_no_canonical_in_config_flow.
        """
        # v4.7.4.2 + v4.7.4.3: The dead selector import block was removed.
        # HA 2026.5.4+ moved selectors to homeassistant.helpers.selector;
        # the old homeassistant.components.selector path raises ModuleNotFoundError.
        # All selector imports in this file use homeassistant.helpers.selector.
        # Tombstone: do NOT reintroduce the old import path.
        # Regression guard: quality/tests/test_v4742_dead_import_removed.py
        import voluptuous as vol
        # v5.11.x cleanup: only the 4 active DPM CONF keys are imported.
        # The 17 vestigial bucket-cell + customize_buckets constants were
        # UI-stripped in v4.7.18 D1 and are no longer read at this call
        # site. Constants remain defined in energy_const.py so existing
        # entry.options rows carrying those keys survive a restart
        # (data-safe strip).
        from .domain_coordinators.energy_const import (
            CONF_ZONE_DYNAMIC_PRESET_ENABLED,
            CONF_ZONE_DYNAMIC_PRESET_OFFSET,
            CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST,
            CONF_ZONE_DYNAMIC_PRESET_SLEEP_ENABLED,
            MIN_DEADBAND,
        )

        MIN_TEMP = 60.0
        MAX_TEMP = 90.0
        SLEEP_FLOOR = 74.0

        # v4.7.5 D3: NO canonical remap here. _selected_zone_name is the raw
        # house zone the user picked in async_step_manage_zones (e.g.,
        # "Master Suite"). DPM saves persist under that raw key; siblings
        # receive identical data via D4 auto-mirror; the EC evaluation loop
        # resolves canonical→constituent at read time (Lazy Canonical
        # Resolution — see QUALITY_CONTEXT.md). This method must not import
        # `iter_canonical_hvac_zones` — enforced by test_v475_d3.
        zm_result = self._get_zm_zone_data()
        if not zm_result:
            return self.async_abort(reason="zone_not_found")

        zm_entry, zone_name, zone_data = zm_result
        # v4.7.5 post-review (B-H3): unlink-path old_thermostat for DPM.
        current_thermostat = zone_data.get(CONF_ZONE_THERMOSTAT)

        if user_input is not None:
            # v4.7.18 D1: Surface 2 schema collapsed to 4 top-level fields
            # (enabled, offset, reset_guest, sleep_enabled). The bucket-cell
            # sections and `customize_buckets` toggle are stripped — bucket
            # cells in entry.options are preserved (data-safe) but no longer
            # editable on this surface. Validation reduces to the validator
            # function's enabled-only stub (D2). Cross-field bucket validation
            # is no longer reachable because there are no bucket fields.
            # v4.7.18 fix-up B-L1: dead `errors`/`async_show_form` branch
            # removed — no codepath populates `errors` under the 4-field
            # shape, so the error-render branch was unreachable. Voluptuous
            # coercion failures still surface via HA's data-entry-flow
            # plumbing.
            # zone_update is a straight copy of user_input (4 scalar fields;
            # no nested dicts to flatten now that the section blocks are gone).
            zone_update = {k: v for k, v in user_input.items()
                           if not isinstance(v, dict)}
            _LOGGER.info(
                "DPM Surface 2 saved zone=%s (v4.7.18 D1: 4-field surface)",
                zone_name,
            )
            self._auto_mirror_to_siblings(
                zm_entry, zone_name, zone_update, MIRROR_KEYS_ZONE_DPM,
                old_thermostat=current_thermostat,
            )
            return await self.async_step_zone_config_menu()

        # Initial render: use zone_data as defaults
        # v5.11.x cleanup: render call reduced to the 4 active conf_keys.
        return self.async_show_form(
            step_id="zone_dynamic_preset",
            data_schema=self._build_dynamic_preset_schema(
                zone_data, zone_data,
                MIN_TEMP, MAX_TEMP,
                conf_enabled=CONF_ZONE_DYNAMIC_PRESET_ENABLED,
                conf_offset=CONF_ZONE_DYNAMIC_PRESET_OFFSET,
                conf_reset_guest=CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST,
                conf_sleep_enabled=CONF_ZONE_DYNAMIC_PRESET_SLEEP_ENABLED,
            ),
            description_placeholders={"zone_name": zone_name},
        )

    # =========================================================================
    # Zone Delete Flow (D1/D2) — remove a zone from the ZM zones dict, sweep
    # entity/device registry, purge zone-keyed DB rows, unassign rooms.
    # =========================================================================

    def _get_zone_entity_unique_id_prefixes(
        self, zone_name: str, zone_id: str | None,
    ) -> tuple[list[str], list[str]]:
        """Return (name-keyed, id-keyed) unique_id prefixes for a zone.

        Zone Delete Flow D2: single source of truth for the entity registry
        sweep. Enumerated from grep of the live source per the plan's
        institutional-context §2. Any new zone unique_id must extend one of
        these lists — the D3 post-sweep tripwire logs a WARNING if any
        registry entity survives, catching missed patterns.
        """
        from homeassistant.util import slugify
        zslug = slugify(zone_name)
        # Name-keyed prefixes:
        #   - {DOMAIN}_zone_{zone_name}_  → aggregation.py 3539..5587
        #     (13 unique_ids: _occupied, _anyone, _safety_alert, _avg_temp,
        #     _avg_humidity, _temp_delta, _humidity_delta, _total_power,
        #     _energy_today, _energy_cost_today, _cost_per_hour, _active_rooms,
        #     _identified_people, _last_identified_person, _last_identified_time)
        #   - {DOMAIN}_zone_{zslug}_       → aggregation.py:5619
        #     `_zone_{zone_slug}_presence_status` (the single slug-keyed
        #     entity — verified by grep of `zone_{zone_slug}` and
        #     `_zone_{zslug}_` in the source). Fix-up R11: prefix is NOT
        #     dead, exactly one entity family matches — keep AND document.
        #   - {DOMAIN}_{zslug}_presence_mode → select.py:297
        name_prefixes = [
            f"{DOMAIN}_zone_{zone_name}_",
            f"{DOMAIN}_zone_{zslug}_",
            f"{DOMAIN}_{zslug}_presence_mode",
        ]
        id_prefixes: list[str] = []
        if zone_id:
            # Id-keyed HVAC family (button/number/binary_sensor/sensor).
            id_prefixes = [
                f"{DOMAIN}_hvac_ac_ramp_start_{zone_id}",
                f"{DOMAIN}_hvac_ac_ramp_stop_{zone_id}",
                f"{DOMAIN}_hvac_ac_ramp_reset_{zone_id}",
                f"{DOMAIN}_hvac_ac_kwh_threshold_{zone_id}",
                f"{DOMAIN}_hvac_zone_{zone_id}_",
                f"{DOMAIN}_hvac_coordinator_{zone_id}_status",
                f"{DOMAIN}_hvac_zone_preset_{zone_id}",
                f"{DOMAIN}_hvac_ac_ramp_state_{zone_id}",
                f"{DOMAIN}_hvac_ac_ramp_last_action_{zone_id}",
                f"{DOMAIN}_hvac_ac_ramp_kwh_rate_{zone_id}",
                f"{DOMAIN}_dynamic_preset_active_bucket_{zone_id}",
                f"{DOMAIN}_dynamic_preset_range_{zone_id}",
            ]
        return name_prefixes, id_prefixes

    def _resolve_zone_id_for_delete(
        self, zone_name: str, has_thermostat: bool = False,
    ) -> tuple[str | None, str]:
        """Reverse-map zone_name → zone_id via live HVAC ZoneManager.

        Returns ``(zone_id, status)`` where status is one of:
          - ``"resolved"``    — found; zone_id is a real ``zone_N``.
          - ``"husk"``        — no thermostat configured; None is
                                the correct answer.
          - ``"coord_down"``  — thermostat IS configured but HVAC
                                coordinator/ZM unavailable; caller
                                MUST treat this as an ERROR and abort
                                (fix-up R7 / A-MED-2 — silently
                                degrading a thermostat-carrying zone to
                                the husk path would skip id-keyed table
                                purge and leak rows).
          - ``"unknown"``     — thermostat configured but no matching
                                zone_id in ZoneManager (e.g. zone
                                thermostat not yet discovered). Same
                                caller contract as ``coord_down``.
        """
        # Fix-up B-HIGH-2 (activate deliberately): the legacy
        # ``hass.data[DOMAIN]["hvac_coordinator"]`` slot is NOT populated
        # in prod — canonical lookup is via
        # ``CoordinatorManager.coordinators["hvac"]`` (see
        # ``domain_coordinators/optimization.py:346-360``, "CM is
        # authoritative"; ``switch.py:510`` for the pattern). Before this
        # fix, every delete resolved (None, "husk") → D3 snapshot was a
        # live no-op, and a thermostat-carrying delete would abort at R7
        # (``coord_down``) — which is why the collision never surfaced
        # via this path in prior deploys. Fixing the lookup ACTIVATES
        # real zone_id resolution for future deletes (id-keyed purge will
        # actually run). This is safe now because the D1 guard (post
        # fix-up Fix 1) protects shared-thermostat zones from mis-prune;
        # this is the plan's intended end-state.
        try:
            domain_data = self.hass.data.get(DOMAIN, {}) or {}
            hvac = None
            cm = domain_data.get("coordinator_manager")
            if cm is not None:
                coords = getattr(cm, "coordinators", None) or {}
                hvac = coords.get("hvac")
            if hvac is None:
                # Legacy slot fallback (empty in prod; kept for tests).
                hvac = domain_data.get("hvac_coordinator")
            if hvac is None:
                return (None, "coord_down" if has_thermostat else "husk")
            zm = getattr(hvac, "zone_manager", None) or getattr(hvac, "_zone_manager", None)
            if zm is None:
                return (None, "coord_down" if has_thermostat else "husk")
            for zid, zs in zm.zones.items():
                zname = getattr(zs, "zone_name", "") or ""
                if zname == zone_name:
                    return (zid, "resolved")
                if " + " in zname and zone_name in [p.strip() for p in zname.split(" + ")]:
                    return (zid, "resolved")
            return (None, "unknown" if has_thermostat else "husk")
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "zone_id resolve failed for zone=%s", zone_name, exc_info=True,
            )
            return (None, "coord_down" if has_thermostat else "husk")

    async def _summarize_zone_deletion(
        self, zone_name: str,
    ) -> dict[str, Any]:
        """Read-only pre-delete summary for the confirm screen.

        Returns keys: n_entities, n_rooms, n_db_rows, n_tables,
        room_entry_ids, thermostat_entity, zone_id, resolve_status,
        is_legacy, is_shared_thermostat.

        Fix-up R6 / A-HIGH-2: ``n_db_rows`` is now the REAL sum of
        rows across the six zone-keyed tables via the new
        ``async_count_zone_rows`` DAO — not a table-count. This lets
        the confirm screen tell the operator the truth.
        """
        from homeassistant.helpers import entity_registry as er
        er_reg = er.async_get(self.hass)

        # Find zone config.
        zone_cfg: dict[str, Any] = {}
        is_legacy = False
        zm_entry = self._find_zone_manager_entry()
        if zm_entry is not None:
            merged = {**zm_entry.data, **zm_entry.options}
            zone_cfg = (merged.get("zones", {}) or {}).get(zone_name, {}) or {}
        else:
            is_legacy = True
        thermostat = zone_cfg.get(CONF_ZONE_THERMOSTAT)
        has_therm = bool(thermostat)
        zone_id, resolve_status = self._resolve_zone_id_for_delete(
            zone_name, has_thermostat=has_therm,
        )

        # Shared-thermostat detection (fix-up A-MED-4): another zone in
        # the ZM dict has the SAME thermostat entity ⇒ deleting this
        # zone shrinks the canonical "A + B" pair to a single zone.
        is_shared_thermostat = False
        if has_therm and zm_entry is not None:
            merged = {**zm_entry.data, **zm_entry.options}
            for other_name, other_cfg in (merged.get("zones", {}) or {}).items():
                if other_name == zone_name:
                    continue
                if (other_cfg or {}).get(CONF_ZONE_THERMOSTAT) == thermostat:
                    is_shared_thermostat = True
                    break

        name_prefixes, id_prefixes = self._get_zone_entity_unique_id_prefixes(
            zone_name, zone_id,
        )
        n_entities = 0
        try:
            for ent in er_reg.entities.values():
                if ent.platform != DOMAIN:
                    continue
                uid = ent.unique_id or ""
                if any(uid.startswith(p) for p in name_prefixes):
                    n_entities += 1
                    continue
                if id_prefixes and any(uid.startswith(p) for p in id_prefixes):
                    n_entities += 1
        except Exception:  # noqa: BLE001
            _LOGGER.debug("entity count failed", exc_info=True)

        # Room reassignment count
        room_entry_ids: list[str] = []
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                rz = entry.options.get(CONF_ZONE) or entry.data.get(CONF_ZONE)
                if rz == zone_name:
                    room_entry_ids.append(entry.entry_id)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("room count failed", exc_info=True)

        # Real DB row counts (fix-up R6 / A-HIGH-2 / C-LOW-2).
        n_db_rows = 0
        n_tables = 3 + (3 if zone_id else 0)  # 3 name-keyed + optional 3 id-keyed
        try:
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db is not None:
                counts = await db.async_count_zone_rows(zone_name, zone_id)
                n_db_rows = sum(counts.values())
        except Exception:  # noqa: BLE001
            _LOGGER.debug("db count failed", exc_info=True)

        return {
            "n_entities": n_entities,
            "n_rooms": len(room_entry_ids),
            "n_db_rows": n_db_rows,
            "n_tables": n_tables,
            "room_entry_ids": room_entry_ids,
            "thermostat_entity": thermostat,
            "zone_id": zone_id,
            "resolve_status": resolve_status,
            "is_legacy": is_legacy,
            "is_shared_thermostat": is_shared_thermostat,
        }

    async def async_step_zone_delete_confirm(self, user_input=None):
        """Zone Delete Flow D1: confirm screen with real counts + typed name.

        Plain-language wording, no config-key jargon. Menu wording rule:
        "Remove this zone?" title, plain English body, "cannot be undone"
        stated once. Requires typing the zone name to prevent fat-fingering.
        """
        zone_name = getattr(self, "_selected_zone_name", None)
        if not zone_name:
            return self.async_abort(reason="zone_not_found")

        # Legacy ENTRY_TYPE_ZONE entry: refuse and point to HA native delete
        # (D2 assertion: never reload the parent entry).
        zm_entry = self._find_zone_manager_entry()
        if zm_entry is None:
            return self.async_abort(reason="zone_delete_legacy_use_native")

        # Fix-up A-MED-4: if a legacy ENTRY_TYPE_ZONE entry with the SAME
        # name coexists with the ZM entry, warn — the ZM options mutation
        # will not clean it up, and after the ZM zone is gone the legacy
        # entry may confuse discovery. Non-fatal; delete proceeds.
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
                if entry.data.get(CONF_ZONE_NAME, "") == zone_name:
                    _LOGGER.warning(
                        "Zone delete: legacy ENTRY_TYPE_ZONE entry with same "
                        "name '%s' coexists (entry_id=%s). ZM delete will not "
                        "touch it; delete it manually if unused.",
                        zone_name, entry.entry_id,
                    )

        summary = await self._summarize_zone_deletion(zone_name)

        # Fix-up R7 / A-MED-2: thermostat present but zone_id unresolvable
        # is an ERROR, not a husk fall-through. Silently degrading to husk
        # here would skip id-keyed table purge for a real thermostat zone.
        if summary["resolve_status"] in ("coord_down", "unknown") and (
            summary.get("thermostat_entity")
        ):
            _LOGGER.warning(
                "Zone delete refused: thermostat=%r configured but zone_id "
                "unresolvable (status=%s). HVAC coordinator may be down or "
                "the thermostat entity was not discovered. Try again after "
                "HA/URA stabilizes.",
                summary.get("thermostat_entity"), summary["resolve_status"],
            )
            return self.async_abort(reason="zone_delete_hvac_not_ready")

        errors: dict[str, str] = {}

        if user_input is not None:
            typed = user_input.get("confirm_zone_name")
            if not _check_zone_confirm_name(typed, zone_name):
                errors["base"] = "confirm_name_mismatch"
            else:
                await self._delete_zone(zm_entry, zone_name, precomputed=summary)
                return self.async_abort(reason="zone_removed")

        placeholders = {
            "zone_name": zone_name,
            "n_entities": str(summary["n_entities"]),
            "n_rooms": str(summary["n_rooms"]),
            "n_db_rows": str(summary["n_db_rows"]),
            "n_tables": str(summary["n_tables"]),
        }
        return self.async_show_form(
            step_id="zone_delete_confirm",
            data_schema=vol.Schema({
                vol.Required("confirm_zone_name"): str,
            }),
            description_placeholders=placeholders,
            errors=errors,
        )

    async def _delete_zone(
        self, zm_entry, zone_name: str,
        precomputed: dict[str, Any] | None = None,
    ) -> None:
        """Zone Delete Flow D2: atomic zone removal helper.

        Ordering (per plan §D2 + review fix-ups):
          0. Safety assertion — never reload parent entry.
          1. Acquire per-hass ``zm_options_lock`` (R10 / B-MED-2) — an
             options RMW must not race a concurrent delete or add.
          2. Snapshot (zone_cfg, thermostat, zone_id, room list). Reuses
             ``precomputed`` when the caller already ran ``_summarize``
             (fix-up A-LOW-1 — avoids double scan).
          3. Entity registry sweep (name-keyed + id-keyed patterns).
          4. Device registry removal (identifier zone_{zone_name}) —
             guarded by "no foreign entities remain" check
             (fix-up A-MED-5).
          5. Room reassignment: single ``async_update_entry`` call
             mutating BOTH ``data`` AND ``options`` (fix-up R3 /
             A-HIGH-1 / Bug Class #14). CONF_ZONE writes are covered
             by the ROOM suppress-allowlist (fix-up R2) so this does
             NOT storm per-room reloads.
          6. DB purge via ``async_delete_zone_data`` DAO (BEFORE the
             tripwire so BEFORE the reload-triggering options mutation
             — fix-up A-LOW-3 places the tripwire before the mutation).
          7. Post-sweep tripwire WARNING for any surviving matches
             (BEFORE options mutation so the tripwire sees pre-reload
             state, not a reload-window transient).
          8. Options mutation LAST (single ``async_update_entry``): the
             ZM entry's update-listener (``_async_update_listener``,
             __init__.py:4694) schedules the reload — DO NOT re-add an
             explicit ``async_create_task(async_reload(...))`` here
             (fix-up R1 / B-CRIT-1).
          9. Dispatch ``SIGNAL_ZM_ZONES_UPDATED`` so HVAC + presence
             prune their in-memory zone state AND rewrite the HVAC
             zone-state store (else next boot RESURRECTS the zone via
             hvac.py:503 ``restore_state_snapshot`` — fix-up R4 /
             B-HIGH-1 + B-HIGH-2).
        """
        from homeassistant.helpers import (
            device_registry as dr,
            entity_registry as er,
            dispatcher,
        )
        from .domain_coordinators.signals import SIGNAL_ZM_ZONES_UPDATED

        # Step 0: SAFETY — never operate on non-ZM entry.
        assert zm_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER, (
            "Zone Delete Flow: refusing to operate on non-ZM entry — "
            "legacy ENTRY_TYPE_ZONE must use HA native delete"
        )

        # Step 1: reentrancy lock (fix-up R10 / B-MED-2).
        lock_bag = self.hass.data.setdefault(DOMAIN, {})
        lock = lock_bag.get("zm_options_lock")
        if lock is None:
            import asyncio as _asyncio
            lock = _asyncio.Lock()
            lock_bag["zm_options_lock"] = lock
        if lock.locked():
            _LOGGER.warning(
                "Zone delete for %r contending with another ZM options RMW "
                "— serializing", zone_name,
            )
        async with lock:
            # D3: capture confirm-time zone_id snapshot from the locked
            # body so the dispatch payload uses the SAME value the
            # summary logged, not a post-mutation re-resolve.
            confirm_time_zone_id = await self._delete_zone_locked(
                zm_entry, zone_name, precomputed,
            )
            # Post-hoc row count sanity (fix-up A-MED-1). Any survivor
            # row for the deleted zone is a WARNING — the DAO reported
            # 0 by construction, so a non-zero here is either a race,
            # a schema drift, or a missed column.
            try:
                db = self.hass.data.get(DOMAIN, {}).get("database")
                if db is not None:
                    # Fix-up A-MED-2 / B-MED-1: reuse confirm-time snapshot
                    # rather than re-resolving post-mutation (the ZM entry
                    # has already been rewritten + reloaded; a second
                    # resolve is prone to drift and cost a lookup).
                    post = await db.async_count_zone_rows(
                        zone_name, confirm_time_zone_id,
                    )
                    lingering = sum(post.values())
                    if lingering:
                        _LOGGER.warning(
                            "Zone delete post-purge sanity: %d rows still "
                            "reference zone=%r (per-table=%s)",
                            lingering, zone_name, post,
                        )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("post-purge sanity failed", exc_info=True)

        # Step 9: dispatch AFTER the lock is released so subscribers can
        # take their own hass.data locks without deadlocking on ours.
        # D3: use confirm-time snapshot rather than re-resolving.
        try:
            dispatcher.async_dispatcher_send(
                self.hass, SIGNAL_ZM_ZONES_UPDATED,
                {"deleted_zone_name": zone_name, "deleted_zone_id": confirm_time_zone_id},
            )
            _LOGGER.info(
                "Zone delete signal dispatched: zone=%r zone_id=%r",
                zone_name, confirm_time_zone_id,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "SIGNAL_ZM_ZONES_UPDATED dispatch failed for zone=%r",
                zone_name, exc_info=True,
            )

    async def _delete_zone_locked(
        self, zm_entry, zone_name: str,
        precomputed: dict[str, Any] | None,
    ) -> str | None:
        """Body of ``_delete_zone`` executed under ``zm_options_lock``.

        Split so the lock scope is obvious and so the tripwire /
        post-hoc counts run inside the lock but the dispatcher fire
        happens outside (see caller).
        """
        from homeassistant.helpers import (
            device_registry as dr,
            entity_registry as er,
        )

        # Step 2: snapshot (reuse precomputed if the caller ran summary).
        summary = precomputed or await self._summarize_zone_deletion(zone_name)
        zone_id = summary["zone_id"]
        room_entry_ids: list[str] = summary["room_entry_ids"]
        _LOGGER.info(
            "Zone delete starting: zone=%r zone_id=%r resolve=%s "
            "entities=%d rooms=%d db_rows=%d shared_thermostat=%s",
            zone_name, zone_id, summary.get("resolve_status"),
            summary["n_entities"], summary["n_rooms"], summary["n_db_rows"],
            summary.get("is_shared_thermostat"),
        )

        # Step 3: entity registry sweep.
        er_reg = er.async_get(self.hass)
        name_prefixes, id_prefixes = self._get_zone_entity_unique_id_prefixes(
            zone_name, zone_id,
        )
        removed = 0
        try:
            for ent in list(er_reg.entities.values()):
                if ent.platform != DOMAIN:
                    continue
                uid = ent.unique_id or ""
                if any(uid.startswith(p) for p in name_prefixes) or (
                    id_prefixes and any(uid.startswith(p) for p in id_prefixes)
                ):
                    try:
                        er_reg.async_remove(ent.entity_id)
                        removed += 1
                    except Exception:  # noqa: BLE001
                        _LOGGER.debug(
                            "entity_registry remove failed for %s",
                            ent.entity_id, exc_info=True,
                        )
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "Entity registry sweep raised for zone=%r", zone_name,
                exc_info=True,
            )
        _LOGGER.info("Zone delete: removed %d entity registry entries", removed)

        # Step 4: device registry — guarded (fix-up A-MED-5).
        try:
            dev_reg = dr.async_get(self.hass)
            dev = dev_reg.async_get_device(
                identifiers={(DOMAIN, f"zone_{zone_name}")}
            )
            if dev is not None:
                # Refuse removal if any foreign-platform entity is still
                # bound to this device (e.g. an operator's HA scene/
                # automation attached an entity to this zone device).
                # Skipping is safer than nuking third-party wiring.
                foreign = [
                    e.entity_id for e in er_reg.entities.values()
                    if getattr(e, "device_id", None) == dev.id
                    and e.platform != DOMAIN
                ]
                if foreign:
                    _LOGGER.warning(
                        "Zone delete: device %s has %d foreign-platform "
                        "entity(ies) still bound (%s) — skipping device "
                        "removal to avoid orphaning third-party entities.",
                        dev.id, len(foreign), foreign[:5],
                    )
                else:
                    dev_reg.async_remove_device(dev.id)
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "Device registry remove failed for zone=%r", zone_name,
                exc_info=True,
            )

        # Step 5: reassign rooms (fix-up R3 / A-HIGH-1 / Bug Class #14).
        # Clear CONF_ZONE from BOTH ``data`` AND ``options`` in a SINGLE
        # ``async_update_entry`` call so the production read predicate
        # ``.options.get(CONF_ZONE) or .data.get(CONF_ZONE)`` returns
        # falsy. Clearing only ``options`` leaves a stale zone name in
        # ``data`` and the read expression still returns it.
        for room_entry_id in room_entry_ids:
            try:
                room_entry = self.hass.config_entries.async_get_entry(
                    room_entry_id
                )
                if room_entry is None:
                    continue
                if room_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                new_data = dict(room_entry.data)
                new_options = dict(room_entry.options)
                new_data[CONF_ZONE] = ""
                new_options[CONF_ZONE] = ""
                self.hass.config_entries.async_update_entry(
                    room_entry,
                    data=new_data,
                    options=new_options,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "Room reassignment failed for %s", room_entry_id,
                    exc_info=True,
                )

        # Step 6: DB purge via new DAO.
        try:
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db is not None:
                await db.async_delete_zone_data(zone_name, zone_id)
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "DB purge failed for zone=%r zone_id=%r", zone_name, zone_id,
                exc_info=True,
            )

        # Step 7: post-sweep tripwire BEFORE the reload-triggering options
        # mutation (fix-up A-LOW-3). Any survivor here indicates a missed
        # unique_id pattern; the reload-window would otherwise re-populate
        # transient state and mask the tripwire.
        try:
            survivors: list[str] = []
            for ent in er_reg.entities.values():
                if ent.platform != DOMAIN:
                    continue
                uid = ent.unique_id or ""
                if any(uid.startswith(p) for p in name_prefixes) or (
                    id_prefixes and any(uid.startswith(p) for p in id_prefixes)
                ):
                    survivors.append(ent.entity_id)
            if survivors:
                _LOGGER.warning(
                    "Zone delete tripwire: %d registry entities survived "
                    "sweep for zone=%r — missed unique_id pattern? %s",
                    len(survivors), zone_name, survivors[:10],
                )
        except Exception:  # noqa: BLE001
            pass

        # Step 8: options mutation LAST (single call). The ZM entry's
        # update-listener (__init__.py:4694) sees a non-suppressed change
        # and schedules an untracked ``async_reload`` (line 4814).
        # DO NOT re-add an explicit ``async_create_task(async_reload(...))``
        # here — reload is triggered by _async_update_listener via
        # ``async_update_entry`` (fix-up R1 / B-CRIT-1: the pre-review
        # build fired it twice → concurrent reload race).
        merged = {**zm_entry.data, **zm_entry.options}
        current_zones = merged.get("zones", {}) or {}
        new_zones = {k: v for k, v in current_zones.items() if k != zone_name}
        self.hass.config_entries.async_update_entry(
            zm_entry,
            options={**zm_entry.options, "zones": new_zones},
        )

        # D3: return confirm-time zone_id snapshot for dispatch.
        return zone_id

    def _build_dynamic_preset_schema(
        self, source_data: dict, current_data: dict,
        min_temp: float, max_temp: float,
        *,
        conf_enabled: str,
        conf_offset: str,
        conf_reset_guest: str,
        conf_sleep_enabled: str,
    ) -> "vol.Schema":
        """Build the voluptuous schema for zone_dynamic_preset step (Surface 2).

        v4.7.18 D1 stripped the 16 per-bucket cells (8 home + 8 sleep) AND
        the customize_buckets toggle from the rendered form. v5.11.x
        cleanup removes them from the signature too — the schema now
        collapses to the 4 fields that drive runtime behavior:
          - conf_enabled        (zone enable)
          - conf_offset         (per-zone offset °F)
          - conf_reset_guest    (reset offset when guest mode active)
          - conf_sleep_enabled  (apply sleep-window pinning)

        Bucket cells remain in entry.options (data preserved — strip is
        UI-only). The CONF constants remain defined in energy_const.py
        for options-dict restore compatibility.

        source_data: zone_data from ZM entry (persisted values)
        current_data: user_input on re-render (or source_data on first load)
        """
        import voluptuous as vol
        CONF_ENABLED = conf_enabled
        CONF_OFFSET = conf_offset
        CONF_RESET_GUEST = conf_reset_guest
        CONF_SLEEP_ENABLED = conf_sleep_enabled

        def _f(key, default):
            v = current_data.get(key, source_data.get(key))
            return float(v) if v is not None else default

        def _b(key, default):
            v = current_data.get(key, source_data.get(key))
            return bool(v) if v is not None else default

        # v4.7.18 D1: schema collapses to 4 top-level fields. The
        # customize_buckets_section + sleep_section blocks are removed
        # along with the 16 cells they wrapped. _customize_buckets_value
        # (v4.7.4.3 lazy derivation) deleted with them — dead code under
        # the new shape.
        return vol.Schema({
            vol.Optional(CONF_ENABLED, default=_b(CONF_ENABLED, False)): bool,
            vol.Optional(CONF_OFFSET, default=_f(CONF_OFFSET, 0.0)): vol.All(
                vol.Coerce(float), vol.Range(min=0.0, max=3.0)
            ),
            vol.Optional(CONF_RESET_GUEST, default=_b(CONF_RESET_GUEST, True)): bool,
            vol.Optional(
                CONF_SLEEP_ENABLED,
                default=_b(CONF_SLEEP_ENABLED, False),
            ): bool,
        })

    # =========================================================================
    # ROOM OPTIONS (for room entries)
    # =========================================================================

    async def async_step_basic_setup(self, user_input=None):
        """Reconfigure basic setup."""
        if user_input is not None:
            # FIX v3.2.3.1: Pass merged options directly to async_create_entry
            try:
                merged = {**self._config_entry.options, **user_input}
                _LOGGER.debug(
                    "basic_setup save: entry_id=%s, options_keys=%d, input_keys=%d, merged_keys=%d",
                    self._config_entry.entry_id,
                    len(self._config_entry.options),
                    len(user_input),
                    len(merged),
                )
                return self.async_create_entry(
                    title="",
                    data=merged,
                )
            except Exception:
                _LOGGER.exception("basic_setup save FAILED")
                raise

        room_types = [
            {"label": "Bedroom", "value": ROOM_TYPE_BEDROOM},
            {"label": "Closet", "value": ROOM_TYPE_CLOSET},
            {"label": "Bathroom", "value": ROOM_TYPE_BATHROOM},
            {"label": "Media Room / Entertainment", "value": ROOM_TYPE_MEDIA_ROOM},
            {"label": "Garage / Workshop", "value": ROOM_TYPE_GARAGE},
            {"label": "Utility Room", "value": ROOM_TYPE_UTILITY},
            {"label": "Common Area (Living/Dining)", "value": ROOM_TYPE_COMMON_AREA},
            {"label": "Generic Room", "value": ROOM_TYPE_GENERIC},
            {"label": "Infrastructure (Always-On Equipment)", "value": ROOM_TYPE_INFRASTRUCTURE},
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
        # v3.20.1 D4: Conditional fields — detail fields only shown when toggle is on
        schema_fields[vol.Optional(
            CONF_SHARED_SPACE,
            default=self._get_current(CONF_SHARED_SPACE, False)
        )] = selector.BooleanSelector()

        if self._get_current(CONF_SHARED_SPACE, False):
            schema_fields[vol.Optional(
                CONF_SHARED_SPACE_AUTO_OFF_HOUR,
                default=self._get_current(CONF_SHARED_SPACE_AUTO_OFF_HOUR, DEFAULT_SHARED_SPACE_AUTO_OFF_HOUR)
            )] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=23, step=1,
                    unit_of_measurement="hour (0-23)",
                    mode=selector.NumberSelectorMode.BOX,
                )
            )
            schema_fields[vol.Optional(
                CONF_SHARED_SPACE_WARNING,
                default=self._get_current(CONF_SHARED_SPACE_WARNING, True)
            )] = selector.BooleanSelector()

        schema_fields[vol.Required(
            CONF_OCCUPANCY_TIMEOUT,
            default=self._get_current(CONF_OCCUPANCY_TIMEOUT, DEFAULT_OCCUPANCY_TIMEOUT)
        )] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=60, max=3600, unit_of_measurement="seconds", mode=selector.NumberSelectorMode.BOX)
        )

        schema_fields[vol.Optional(
            CONF_OCCUPANCY_DEBOUNCE,
            default=self._get_current(CONF_OCCUPANCY_DEBOUNCE, DEFAULT_OCCUPANCY_DEBOUNCE)
        )] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=2000, step=50,
                unit_of_measurement="ms",
                mode=selector.NumberSelectorMode.BOX,
            )
        )

        # v4.7.2 D4: Per-room guest designation fields
        schema_fields[vol.Optional(
            CONF_ROOM_IS_GUEST_ROOM,
            default=self._get_current(CONF_ROOM_IS_GUEST_ROOM, False),
        )] = selector.BooleanSelector()

        schema_fields[vol.Optional(
            CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN,
            default=self._get_current(CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN, 30),
        )] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=5, max=240, step=5,
                unit_of_measurement="min",
                mode=selector.NumberSelectorMode.BOX,
            )
        )

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
                try:
                    merged = {**self._config_entry.options, **user_input}
                    # v5.37.0/v5.37.1: explicit-clear control for the otherwise
                    # unclearable optional single-entity selectors (temperature,
                    # humidity, illuminance, water_leak). An optional
                    # EntitySelector with a current-value default is
                    # UNCLEARABLE (empty submissions rejected; omitting the key
                    # refills the default — true in the HA UI too). We write an
                    # explicit EMPTY options override (not a pop): consumers
                    # merge {**data, **options}, values may also live in
                    # entry.data, and an empty options value wins the merge and
                    # is falsy at every `if <sensor>:` guard.
                    clear_map = {
                        "temperature": CONF_TEMPERATURE_SENSOR,
                        "humidity": CONF_HUMIDITY_SENSOR,
                        "illuminance": CONF_ILLUMINANCE_SENSOR,
                        "water_leak": CONF_WATER_LEAK_SENSOR,
                    }
                                  # Precedence: a field selected for CLEAR wins over a new pick
                                  # made in the SAME submit (explicit clear beats accidental leftover).
                    for choice in merged.pop("clear_sensor_fields", []) or []:
                        conf_key = clear_map.get(choice)
                        if conf_key:
                            merged[conf_key] = ""
                    _LOGGER.debug("sensors save: entry_id=%s, merged_keys=%d",
                                  self._config_entry.entry_id, len(merged))
                    return self.async_create_entry(title="", data=merged)
                except Exception:
                    _LOGGER.exception("sensors save FAILED")
                    raise

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
            # v4.7.16 D4: Per-room camera-presence opt-out
            vol.Optional(
                CONF_DISABLE_CAMERA_PRESENCE,
                default=self._get_current(
                    CONF_DISABLE_CAMERA_PRESENCE, DEFAULT_DISABLE_CAMERA_PRESENCE
                ),
            ): selector.BooleanSelector(),
            # Room-camera fusion (2026-08-01): NEW key CONF_ROOM_CAMERAS
            # (mirrors initial-setup step).
            vol.Optional(
                CONF_ROOM_CAMERAS,
                default=self._get_current(CONF_ROOM_CAMERAS, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
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
            # v4.7.8 D1: Per-room egress flag (see initial install for rationale).
            vol.Optional(
                CONF_IS_EGRESS_WINDOW,
                default=self._get_current(CONF_IS_EGRESS_WINDOW, DEFAULT_IS_EGRESS_WINDOW),
            ): selector.BooleanSelector(),
            # v3.1.0: Water leak sensor
            vol.Optional(
                CONF_WATER_LEAK_SENSOR,
                default=self._get_current(CONF_WATER_LEAK_SENSOR) or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", device_class=["moisture", "water_leak"])
            ),
            # v5.37.0/v5.37.1: single multi-select to clear otherwise
            # UNCLEARABLE optional single-entity selectors on this step. An
            # optional EntitySelector with a current-value default rejects
            # empty submissions AND refills on key omission (true in the HA
            # UI too); checking a value here writes an explicit EMPTY
            # options override (see save handler above). List fields (motion,
            # mmwave, occupancy, scanner areas, door, window) are clearable
            # natively and are NOT included here.
            vol.Optional(
                "clear_sensor_fields", default=[],
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"label": "Clear Temperature Sensor", "value": "temperature"},
                        {"label": "Clear Humidity Sensor", "value": "humidity"},
                        {"label": "Clear Illuminance Sensor", "value": "illuminance"},
                        {"label": "Clear Water-Leak Sensor", "value": "water_leak"},
                    ],
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
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
            try:
                merged = {**self._config_entry.options, **user_input}
                _LOGGER.debug("devices save: entry_id=%s, merged_keys=%d",
                              self._config_entry.entry_id, len(merged))
                return self.async_create_entry(title="", data=merged)
            except Exception:
                _LOGGER.exception("devices save FAILED")
                raise

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
                selector.EntitySelectorConfig(domain=["fan", "switch"], multiple=True)
            ),
            vol.Optional(
                CONF_HUMIDITY_FANS,
                default=self._get_current(CONF_HUMIDITY_FANS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["fan", "switch"], multiple=True)
            ),
            # Fan-noise mitigation D1: per-room adjacency (Layer-2 of
            # the BLE corroboration ladder). Round-trips through
            # reconfigure so operators can populate it incrementally
            # after install. Empty list is safe.
            vol.Optional(
                CONF_ADJACENT_ROOMS,
                default=self._get_current(CONF_ADJACENT_ROOMS, [])
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {
                            "label": e.data.get(CONF_ROOM_NAME, e.title),
                            "value": e.entry_id,
                        }
                        for e in self._get_all_room_entries()
                        if e.entry_id != self._config_entry.entry_id
                    ],
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            # Fan-noise Mode-2 per-room flags. Round-trip through
            # reconfigure so operators can flip per-room after install.
            # Per-room defaults are ON for all three (room-fan-recheck,
            # L2-allowed, trust-sensors-ok); the master kill switch
            # (default OFF) lives on the Presence Coordinator options step.
            vol.Optional(
                CONF_ROOM_FAN_RECHECK_ENABLED,
                default=self._get_current(
                    CONF_ROOM_FAN_RECHECK_ENABLED,
                    DEFAULT_ROOM_FAN_RECHECK_ENABLED,
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_FAN_RECHECK_L2_ALLOWED,
                default=self._get_current(
                    CONF_FAN_RECHECK_L2_ALLOWED,
                    DEFAULT_FAN_RECHECK_L2_ALLOWED,
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_FAN_RECHECK_TRUST_SENSORS_OK,
                default=self._get_current(
                    CONF_FAN_RECHECK_TRUST_SENSORS_OK,
                    DEFAULT_FAN_RECHECK_TRUST_SENSORS_OK,
                ),
            ): selector.BooleanSelector(),
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

    # =========================================================================
    # v3.20.1 D3: SPLIT OPTIONS — options_lighting + options_covers
    # =========================================================================

    async def async_step_options_lighting(self, user_input=None):
        """Reconfigure lighting automation behavior (v3.20.1 D3: split from automation_behavior).

        6 fields -- lighting only.
        """
        if user_input is not None:
            try:
                # v5.8.0 D2.12: flatten the collapsed reconcile_advanced section
                # back to a top-level CONF_FLAP_SENSITIVITY key (mirrors the
                # fan_recheck_advanced flatten pattern) so the reconciler reads
                # the same key it would read pre-collapse.
                advanced = user_input.pop("reconcile_advanced", None)
                if isinstance(advanced, dict):
                    user_input = {**user_input, **advanced}
                merged = {**self._config_entry.options, **user_input}
                _LOGGER.debug(
                    "options_lighting save: entry_id=%s, options_keys=%d, input_keys=%d, merged_keys=%d",
                    self._config_entry.entry_id,
                    len(self._config_entry.options),
                    len(user_input),
                    len(merged),
                )
                return self.async_create_entry(
                    title="",
                    data=merged,
                )
            except Exception:
                _LOGGER.exception("options_lighting save FAILED")
                raise

        light_entry_actions = [
            {"label": "None (Manual Control)", "value": LIGHT_ACTION_NONE},
            {"label": "Turn On Always", "value": LIGHT_ACTION_TURN_ON},
            {"label": "Smart (Only When Dark)", "value": LIGHT_ACTION_TURN_ON_IF_DARK},
        ]

        flap_sensitivity_options = [
            {"label": "Relaxed (fewer false quarantines)", "value": "relaxed"},
            {"label": "Normal (default)", "value": "normal"},
            {"label": "Aggressive (quarantine flaky devices sooner)", "value": "aggressive"},
        ]

        light_exit_actions = [
            {"label": "Turn Off", "value": LIGHT_ACTION_TURN_OFF},
            {"label": "Leave On", "value": LIGHT_ACTION_LEAVE_ON},
        ]

        data_schema = vol.Schema({
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
            # v5.8.0 D2.12: reconcile-on-return flap-sensitivity as a named-bucket
            # dropdown in a collapsed section. NO per-knob Number entities
            # ("Configurability Clarity" + "Number Fields = Form Fields" rules).
            vol.Optional("reconcile_advanced"): _ha_section(
                vol.Schema({
                    vol.Optional(
                        CONF_FLAP_SENSITIVITY,
                        default=self._get_current(CONF_FLAP_SENSITIVITY, "normal"),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=flap_sensitivity_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }),
                {"collapsed": True},
            ),
        })

        return self.async_show_form(
            step_id="options_lighting",
            data_schema=data_schema,
            description_placeholders={"name": "Reconfigure lighting automation"},
        )

    async def async_step_options_covers(self, user_input=None):
        """Reconfigure cover automation behavior (v3.20.1 D3: split from automation_behavior).

        10 fields -- covers only.
        """
        if user_input is not None:
            try:
                merged = {**self._config_entry.options, **user_input}
                _LOGGER.debug(
                    "options_covers save: entry_id=%s, options_keys=%d, input_keys=%d, merged_keys=%d",
                    self._config_entry.entry_id,
                    len(self._config_entry.options),
                    len(user_input),
                    len(merged),
                )
                return self.async_create_entry(
                    title="",
                    data=merged,
                )
            except Exception:
                _LOGGER.exception("options_covers save FAILED")
                raise

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
            vol.Optional(
                CONF_COVER_TYPE,
                default=self._get_current(CONF_COVER_TYPE, COVER_TYPE_SHADE)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cover_types, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            # --- Open ---
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
            # --- Close ---
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
            # v4.5.9: HVAC solar-gain cover management opt-out (default ON)
            vol.Optional(
                CONF_COVER_HVAC_MANAGED,
                default=self._get_current(CONF_COVER_HVAC_MANAGED, True)
            ): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="options_covers",
            data_schema=data_schema,
            description_placeholders={"name": "Reconfigure cover automation"},
        )

    async def async_step_climate(self, user_input=None):
        """Reconfigure "Climate & Fans" (D7 rename + D5/D8 demote)."""
        section = _ha_section
        errors: dict[str, str] = {}
        if user_input is not None:
            advanced = user_input.pop("humidity_fan_advanced", None)
            if isinstance(advanced, dict):
                user_input.update(advanced)
            climate_group = user_input.pop("climate_backstop", None)
            if isinstance(climate_group, dict):
                user_input.update(climate_group)
            err = _validate_climate_fans_form(user_input)
            if err:
                errors["base"] = err
                # fall through to redisplay form
            # v3.6.23: Auto-populate zone thermostat if room is in a zone
            # v3.18.0: Deferred ZM update to avoid reload race condition
            pending_zm_update = None
            climate_entity = user_input.get(CONF_CLIMATE_ENTITY)
            if not errors and climate_entity:
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
                            pending_zm_update = (
                                zm_entry,
                                {**zm_entry.options, "zones": zones},
                            )

            if not errors:
                try:
                    merged = {**self._config_entry.options, **user_input}
                    _LOGGER.debug("climate save: entry_id=%s, merged_keys=%d",
                                  self._config_entry.entry_id, len(merged))
                    result = self.async_create_entry(title="", data=merged)
                except Exception:
                    _LOGGER.exception("climate save FAILED")
                    raise

                # v3.18.0: Fire ZM update after room entry is saved
                if pending_zm_update:
                    zm_entry_ref, zm_options = pending_zm_update

                    async def _deferred_zm_update():
                        await asyncio.sleep(2)
                        self.hass.config_entries.async_update_entry(
                            zm_entry_ref,
                            options=zm_options,
                        )

                    self.hass.async_create_task(_deferred_zm_update())

                return result

        room_type = self._get_current(CONF_ROOM_TYPE)
        wet_default = bool(
            self._get_current(
                CONF_WET_ROOM,
                room_type == ROOM_TYPE_BATHROOM,
            )
        )

        data_schema = vol.Schema({
            # --- Fans first ---
            vol.Optional(
                CONF_HVAC_COORDINATION_ENABLED,
                default=self._get_current(CONF_HVAC_COORDINATION_ENABLED, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_FAN_CONTROL_ENABLED,
                default=self._get_current(CONF_FAN_CONTROL_ENABLED, False),
            ): selector.BooleanSelector(),
            # Comfort-fan house-AWAY veto (mmwave-corroboration Tier-3 D3).
            vol.Optional(
                CONF_COMFORT_FAN_AWAY_VETO_ENABLED,
                default=self._get_current(
                    CONF_COMFORT_FAN_AWAY_VETO_ENABLED,
                    DEFAULT_COMFORT_FAN_AWAY_VETO_ENABLED,
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_HUMIDITY_FAN_CONTROL_ENABLED,
                default=self._get_current(
                    CONF_HUMIDITY_FAN_CONTROL_ENABLED,
                    DEFAULT_HUMIDITY_FAN_CONTROL_ENABLED,
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_WET_ROOM, default=wet_default,
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_HUMIDITY_FAN_SPIKE_ENABLED,
                default=self._get_current(CONF_HUMIDITY_FAN_SPIKE_ENABLED, wet_default),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED,
                default=self._get_current(
                    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED, wet_default,
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S,
                default=self._get_current(
                    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S,
                    DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=600, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S,
                default=self._get_current(
                    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S,
                    DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=300, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S,
                default=self._get_current(
                    CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S,
                    DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=3600, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_FAN_TEMP_THRESHOLD,
                default=self._get_current(CONF_FAN_TEMP_THRESHOLD, DEFAULT_FAN_TEMP_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=100, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_FAN_SPEED_LOW_TEMP,
                default=self._get_current(CONF_FAN_SPEED_LOW_TEMP, DEFAULT_FAN_SPEED_LOW),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=100, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_FAN_SPEED_MED_TEMP,
                default=self._get_current(CONF_FAN_SPEED_MED_TEMP, DEFAULT_FAN_SPEED_MED),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=100, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_FAN_SPEED_HIGH_TEMP,
                default=self._get_current(CONF_FAN_SPEED_HIGH_TEMP, DEFAULT_FAN_SPEED_HIGH),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=100, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_HUMIDITY_FAN_THRESHOLD,
                default=self._get_current(CONF_HUMIDITY_FAN_THRESHOLD, DEFAULT_HUMIDITY_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=30, max=80, unit_of_measurement="%", mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Optional(
                CONF_HUMIDITY_FAN_TIMEOUT,
                default=self._get_current(CONF_HUMIDITY_FAN_TIMEOUT, DEFAULT_HUMIDITY_FAN_TIMEOUT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=3600, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_HUMIDITY_FAN_MAX_RUNTIME,
                default=self._get_current(CONF_HUMIDITY_FAN_MAX_RUNTIME, DEFAULT_HUMIDITY_FAN_MAX_RUNTIME),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=600, max=14400, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional("humidity_fan_advanced"): section(
                vol.Schema({
                    vol.Optional(
                        CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT,
                        default=self._get_current(
                            CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT,
                            DEFAULT_HUMIDITY_FAN_SPIKE_DELTA_PCT,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=3, max=30, unit_of_measurement="%", mode=selector.NumberSelectorMode.BOX)
                    ),
                    vol.Optional(
                        CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S,
                        default=self._get_current(
                            CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S,
                            DEFAULT_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=300, max=14400, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
                    ),
                    vol.Optional(
                        CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE,
                        default=self._get_current(
                            CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE,
                            DEFAULT_HUMIDITY_FAN_SPIKE_BASELINE_MODE,
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"label": "EMA (adaptive average)", "value": HUMIDITY_FAN_SPIKE_MODE_EMA},
                                {"label": "Window minimum", "value": HUMIDITY_FAN_SPIKE_MODE_WINDOW_MIN},
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }),
                {"collapsed": True},
            ),
            # --- Climate backstop LAST (D8 demote) ---
            vol.Optional("climate_backstop"): section(
                vol.Schema({
                    vol.Optional(
                        CONF_TARGET_TEMP_HEAT,
                        default=self._get_current(CONF_TARGET_TEMP_HEAT, DEFAULT_TARGET_TEMP_HEAT),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=60, max=90, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
                    ),
                    vol.Optional(
                        CONF_TARGET_TEMP_COOL,
                        default=self._get_current(CONF_TARGET_TEMP_COOL, DEFAULT_TARGET_TEMP_COOL),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=60, max=90, unit_of_measurement="°F", mode=selector.NumberSelectorMode.BOX)
                    ),
                    vol.Optional(
                        CONF_CLIMATE_ENTITY,
                        default=self._get_current(CONF_CLIMATE_ENTITY) or vol.UNDEFINED,
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="climate")
                    ),
                }),
                {"collapsed": False},
            ),
        })

        return self.async_show_form(
            step_id="climate",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"name": "Reconfigure climate & fans"},
        )

    async def async_step_sleep_protection(self, user_input=None):
        """Reconfigure sleep protection."""
        if user_input is not None:
            try:
                merged = {**self._config_entry.options, **user_input}
                _LOGGER.debug("sleep_protection save: entry_id=%s, merged_keys=%d",
                              self._config_entry.entry_id, len(merged))
                return self.async_create_entry(title="", data=merged)
            except Exception:
                _LOGGER.exception("sleep_protection save FAILED")
                raise

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
            vol.Optional(
                CONF_FAN_SLEEP_POLICY,
                default=self._get_current(CONF_FAN_SLEEP_POLICY, DEFAULT_FAN_SLEEP_POLICY)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"label": "Turn off fans during sleep", "value": "off"},
                        {"label": "Reduce fan speed (low only)", "value": "reduce"},
                        {"label": "Normal fan operation", "value": "normal"},
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })

        return self.async_show_form(
            step_id="sleep_protection",
            data_schema=data_schema,
            description_placeholders={"name": "Reconfigure sleep protection"},
        )

    async def async_step_music_following(self, user_input=None):
        """Configure room media player for music following (v3.3.1)."""
        if user_input is not None:
            try:
                merged = {**self._config_entry.options, **user_input}
                _LOGGER.debug("music_following save: entry_id=%s, merged_keys=%d",
                              self._config_entry.entry_id, len(merged))
                return self.async_create_entry(title="", data=merged)
            except Exception:
                _LOGGER.exception("music_following save FAILED")
                raise

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
            # v5.10.0 D11: per-room speaker loudness calibration. Applied
            # only on cross-platform generic transfers (Sonos ↔ WiiM etc.
            # where absolute volume levels aren't directly comparable).
            vol.Optional(
                CONF_ROOM_MEDIA_VOLUME_SCALE,
                default=self._get_current(
                    CONF_ROOM_MEDIA_VOLUME_SCALE,
                    DEFAULT_ROOM_MEDIA_VOLUME_SCALE,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_ROOM_MEDIA_VOLUME_SCALE,
                    max=MAX_ROOM_MEDIA_VOLUME_SCALE,
                    step=0.05,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
        })

        return self.async_show_form(
            step_id="music_following",
            data_schema=data_schema,
        )

    async def async_step_energy(self, user_input=None):
        """Reconfigure energy monitoring."""
        if user_input is not None:
            try:
                merged = {**self._config_entry.options, **user_input}
                _LOGGER.debug("energy save: entry_id=%s, merged_keys=%d",
                              self._config_entry.entry_id, len(merged))
                return self.async_create_entry(title="", data=merged)
            except Exception:
                _LOGGER.exception("energy save FAILED")
                raise

        data_schema = vol.Schema({
            vol.Optional(
                CONF_POWER_SENSORS, 
                default=self._get_current(CONF_POWER_SENSORS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
            ),
            vol.Optional(
                CONF_ENERGY_SENSORS,
                default=self._get_energy_sensors_default()
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
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
            try:
                merged = {**self._config_entry.options, **user_input}
                _LOGGER.debug("notifications save: entry_id=%s, merged_keys=%d",
                              self._config_entry.entry_id, len(merged))
                return self.async_create_entry(title="", data=merged)
            except Exception:
                _LOGGER.exception("notifications save FAILED")
                raise

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

        # v3.20.1 D4: Conditional fields — override detail fields only when toggle is on
        schema_fields = {
            vol.Optional(
                CONF_OVERRIDE_NOTIFICATIONS,
                default=self._get_current(CONF_OVERRIDE_NOTIFICATIONS, False)
            ): selector.BooleanSelector(),
        }

        if self._get_current(CONF_OVERRIDE_NOTIFICATIONS, False):
            schema_fields[vol.Optional(CONF_NOTIFY_SERVICE)] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify_services, mode=selector.SelectSelectorMode.DROPDOWN)
            )
            schema_fields[vol.Optional(CONF_NOTIFY_TARGET)] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify_targets, mode=selector.SelectSelectorMode.DROPDOWN)
            )
            schema_fields[vol.Optional(
                CONF_NOTIFY_LEVEL,
                default=self._get_current(CONF_NOTIFY_LEVEL, NOTIFY_LEVEL_ERRORS)
            )] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify_levels, mode=selector.SelectSelectorMode.DROPDOWN)
            )

        # v3.1.0: Alert lights (always visible — not part of override)
        schema_fields[vol.Optional(
            CONF_ALERT_LIGHTS,
            default=self._get_current(CONF_ALERT_LIGHTS, [])
        )] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="light", multiple=True)
        )
        schema_fields[vol.Optional(
            CONF_ALERT_LIGHT_COLOR,
            default=self._get_current(CONF_ALERT_LIGHT_COLOR, ALERT_COLOR_AMBER)
        )] = selector.SelectSelector(
            selector.SelectSelectorConfig(options=alert_colors, mode=selector.SelectSelectorMode.DROPDOWN)
        )

        data_schema = vol.Schema(schema_fields)

        return self.async_show_form(
            step_id="notifications",
            data_schema=data_schema,
            description_placeholders={
                "name": "Reconfigure notifications. Enable override to use room-specific settings instead of integration defaults."
            },
        )

    # =========================================================================
    # v3.10.0/v3.12.0: AUTOMATION CHAINING (M1 + M2)
    # =========================================================================

    async def async_step_automation_chaining(self, user_input=None):
        """Automation chaining: choose trigger group to configure."""
        return self.async_show_menu(
            step_id="automation_chaining",
            menu_options=[
                "chain_occupancy",
                "chain_light",
                "chain_house_state",
                "chain_coordinator",
            ],
        )

    async def async_step_chain_occupancy(self, user_input=None):
        """Configure occupancy trigger automations (enter/exit)."""
        return await self._chain_trigger_step(
            "chain_occupancy", CHAIN_GROUP_OCCUPANCY, user_input,
        )

    async def async_step_chain_light(self, user_input=None):
        """Configure light level trigger automations (lux_dark/lux_bright)."""
        return await self._chain_trigger_step(
            "chain_light", CHAIN_GROUP_LIGHT, user_input,
        )

    async def async_step_chain_house_state(self, user_input=None):
        """Configure house state trigger automations."""
        return await self._chain_trigger_step(
            "chain_house_state", CHAIN_GROUP_HOUSE_STATE, user_input,
        )

    async def async_step_chain_coordinator(self, user_input=None):
        """Configure coordinator signal trigger automations."""
        return await self._chain_trigger_step(
            "chain_coordinator", CHAIN_GROUP_COORDINATOR, user_input,
        )

    async def _chain_trigger_step(
        self, step_id: str, triggers: list[str], user_input,
    ):
        """Shared handler for chain trigger sub-steps.

        Preserves bindings from other trigger groups when saving.
        """
        if user_input is not None:
            # Merge with existing chains from other groups
            existing = self._config_entry.options.get(
                CONF_AUTOMATION_CHAINS,
                self._config_entry.data.get(CONF_AUTOMATION_CHAINS, {}),
            )
            updated = dict(existing)
            for trigger in triggers:
                key = f"chain_{trigger}"
                val = user_input.get(key, "")
                if val:
                    updated[trigger] = val
                else:
                    updated.pop(trigger, None)
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, CONF_AUTOMATION_CHAINS: updated},
            )

        # Build automation entity dropdown options
        automation_entities = sorted(
            eid for eid in self.hass.states.async_entity_ids("automation")
        )
        options = [{"value": "", "label": "(none)"}]
        for eid in automation_entities:
            state = self.hass.states.get(eid)
            label = state.attributes.get("friendly_name", eid) if state else eid
            options.append({"value": eid, "label": label})

        current = self._config_entry.options.get(
            CONF_AUTOMATION_CHAINS,
            self._config_entry.data.get(CONF_AUTOMATION_CHAINS, {}),
        )

        data_schema = vol.Schema({
            vol.Optional(
                f"chain_{trigger}",
                default=current.get(trigger, ""),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
            for trigger in triggers
        })

        return self.async_show_form(
            step_id=step_id,
            data_schema=data_schema,
        )

    # =========================================================================
    # v3.12.0 M3: AI NL RULES — CONFIG FLOW STEPS
    # =========================================================================

    async def async_step_ai_rules(self, user_input=None):
        """AI Rules menu: Add Rule / View Rules / Back."""
        return self.async_show_menu(
            step_id="ai_rules",
            menu_options=[
                "ai_rule_add",
                "ai_rule_list",
            ],
        )

    async def async_step_ai_rule_add(self, user_input=None):
        """Add a new AI rule by describing it in natural language."""
        errors = {}

        if user_input is not None:
            trigger_type = user_input.get(CONF_AI_RULE_TRIGGER, "enter")
            person = user_input.get(CONF_AI_RULE_PERSON, "").strip()
            description = user_input.get(CONF_AI_RULE_DESCRIPTION, "").strip()

            if not description:
                errors["base"] = "ai_rule_empty_description"
            else:
                # Parse with AI
                actions = await self._parse_rule_with_ai(description, trigger_type, person)
                if actions is None:
                    errors["base"] = "ai_parse_failed"
                else:
                    # Validate parsed actions
                    valid, validation_errors = self._validate_parsed_actions(actions)
                    if not valid:
                        _LOGGER.warning(
                            "AI rule validation errors: %s", validation_errors,
                        )
                        errors["base"] = "ai_rule_validation_failed"
                    else:
                        # Build the rule dict
                        from homeassistant.util import dt as dt_util
                        rule = {
                            "rule_id": uuid.uuid4().hex[:8],
                            "trigger_type": trigger_type,
                            "person": person,
                            "description": description,
                            "actions": actions,
                            "enabled": True,
                            "created_at": dt_util.utcnow().isoformat(),
                        }

                        # Store in options
                        existing_rules = list(
                            self._config_entry.options.get(
                                CONF_AI_RULES,
                                self._config_entry.data.get(CONF_AI_RULES, []),
                            )
                        )
                        existing_rules.append(rule)

                        return self.async_create_entry(
                            title="",
                            data={
                                **self._config_entry.options,
                                CONF_AI_RULES: existing_rules,
                            },
                        )

        # Build trigger dropdown options with human-readable labels
        trigger_labels = {
            "enter": "Room Enter",
            "exit": "Room Exit",
            "lux_dark": "Room Gets Dark",
            "lux_bright": "Room Gets Bright",
            "house_state_away": "House Away",
            "house_state_arriving": "House Arriving",
            "house_state_home_day": "House Home Day",
            "house_state_home_evening": "House Home Evening",
            "house_state_home_night": "House Home Night",
            "house_state_sleep": "House Sleep",
            "house_state_waking": "House Waking",
            "house_state_guest": "House Guest",
            "house_state_vacation": "House Vacation",
            "energy_constraint": "Energy Constraint Change",
            "safety_hazard": "Safety Hazard Detected",
            "security_event": "Security Event",
        }
        trigger_options = [
            {"value": t, "label": trigger_labels.get(t, t)}
            for t in AI_RULE_TRIGGER_OPTIONS
        ]

        data_schema = vol.Schema({
            vol.Required(CONF_AI_RULE_TRIGGER, default="enter"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=trigger_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            # v3.20.1 D5: EntitySelector for person domain
            vol.Optional(CONF_AI_RULE_PERSON, default=vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="person")
            ),
            vol.Required(CONF_AI_RULE_DESCRIPTION, default=""): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.TEXT,
                    multiline=True,
                )
            ),
        })

        return self.async_show_form(
            step_id="ai_rule_add",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_ai_rule_list(self, user_input=None):
        """List existing AI rules — select one to delete."""
        if user_input is not None:
            selected_rule_id = user_input.get("selected_rule")
            if selected_rule_id:
                self._pending_delete_rule_id = selected_rule_id
                return await self.async_step_ai_rule_delete()
            # No selection, go back
            return await self.async_step_ai_rules()

        existing_rules = self._config_entry.options.get(
            CONF_AI_RULES,
            self._config_entry.data.get(CONF_AI_RULES, []),
        )

        if not existing_rules:
            # No rules — show empty form that returns to menu
            return self.async_show_form(
                step_id="ai_rule_list",
                data_schema=vol.Schema({}),
                description_placeholders={"rules_summary": "No AI rules configured."},
            )

        # Build rule options for selection
        rule_options = []
        for rule in existing_rules:
            label = (
                f"[{rule.get('trigger_type', '?')}] "
                f"{rule.get('description', 'No description')[:60]}"
            )
            if rule.get("person"):
                label += f" (person: {rule['person']})"
            if not rule.get("enabled", True):
                label += " [DISABLED]"
            rule_options.append({
                "value": rule.get("rule_id", ""),
                "label": label,
            })

        summary_lines = []
        for i, rule in enumerate(existing_rules, 1):
            status = "enabled" if rule.get("enabled", True) else "disabled"
            summary_lines.append(
                f"{i}. [{rule.get('trigger_type', '?')}] "
                f"{rule.get('description', '')[:50]} ({status})"
            )
        rules_summary = "\n".join(summary_lines) if summary_lines else "No rules."

        data_schema = vol.Schema({
            vol.Optional("selected_rule"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=rule_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })

        return self.async_show_form(
            step_id="ai_rule_list",
            data_schema=data_schema,
            description_placeholders={"rules_summary": rules_summary},
        )

    async def async_step_ai_rule_delete(self, user_input=None):
        """Confirm and delete an AI rule."""
        rule_id = getattr(self, "_pending_delete_rule_id", None)

        if user_input is not None:
            if user_input.get("confirm_delete") and rule_id:
                existing_rules = list(
                    self._config_entry.options.get(
                        CONF_AI_RULES,
                        self._config_entry.data.get(CONF_AI_RULES, []),
                    )
                )
                updated_rules = [
                    r for r in existing_rules if r.get("rule_id") != rule_id
                ]
                self._pending_delete_rule_id = None
                return self.async_create_entry(
                    title="",
                    data={
                        **self._config_entry.options,
                        CONF_AI_RULES: updated_rules,
                    },
                )
            # Not confirmed — go back
            self._pending_delete_rule_id = None
            return await self.async_step_ai_rules()

        # Find rule details for confirmation
        existing_rules = self._config_entry.options.get(
            CONF_AI_RULES,
            self._config_entry.data.get(CONF_AI_RULES, []),
        )
        rule_desc = "Unknown rule"
        for rule in existing_rules:
            if rule.get("rule_id") == rule_id:
                rule_desc = rule.get("description", rule_id)[:80]
                break

        data_schema = vol.Schema({
            vol.Required("confirm_delete", default=False): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="ai_rule_delete",
            data_schema=data_schema,
            description_placeholders={"rule_description": rule_desc},
        )

    # =========================================================================
    # v3.12.0 M3: AI RULE PARSING & VALIDATION HELPERS
    # =========================================================================

    async def _parse_rule_with_ai(
        self,
        description: str,
        trigger_type: str,
        person: str,
    ) -> list[dict] | None:
        """Parse NL description into service call list via ai_task.generate_data."""
        room_name = self._get_current(CONF_ROOM_NAME, "this room")
        room_entities = await self._get_room_entities_for_prompt()

        trigger_label = {
            "enter": f"{person or 'someone'} enters the room",
            "exit": f"{person or 'someone'} leaves the room",
            "lux_dark": "the room gets dark",
            "lux_bright": "the room gets bright",
            "house_state_away": "the house transitions to Away",
            "house_state_arriving": "someone is arriving home",
            "house_state_home_day": "the house enters Home Day mode",
            "house_state_home_evening": "the house enters Home Evening mode",
            "house_state_home_night": "the house enters Home Night mode",
            "house_state_sleep": "the house enters Sleep mode",
            "house_state_waking": "the house enters Waking mode",
            "house_state_guest": "the house enters Guest mode",
            "house_state_vacation": "the house enters Vacation mode",
            "energy_constraint": "the energy constraint changes (peak, shed, coast)",
            "safety_hazard": "a safety hazard is detected (smoke, CO, water leak)",
            "security_event": "a security event occurs (entry alert, unknown person)",
        }.get(trigger_type, trigger_type)

        prompt = AI_RULE_PARSING_PROMPT.format(
            room_name=room_name,
            trigger_label=trigger_label,
            description=description,
            entities_json=json.dumps(room_entities, indent=2),
        )

        structure = {
            "actions": {
                "selector": {"object": {"multiple": True}},
                "description": (
                    "List of HA service calls. Each must have: "
                    "domain (string), service (string), "
                    "target (object with entity_id string or list), "
                    "data (object, may be empty {}). "
                    "Use color_temp_kelvin not color_temp. "
                    "Use brightness_pct (0-100) not brightness."
                ),
            }
        }

        try:
            result = await self.hass.services.async_call(
                "ai_task", "generate_data",
                {
                    "task_name": "ura_parse_room_rule",
                    "instructions": prompt,
                    "structure": structure,
                },
                blocking=True,
                return_response=True,
            )
        except Exception as err:
            _LOGGER.error("ai_task failed during rule parsing: %s", err)
            return None

        if not result or not isinstance(result, dict):
            return None

        # ai_task may nest data under "data" key or return flat
        actions = result.get("data", {}).get("actions") if isinstance(result.get("data"), dict) else None
        if actions is None:
            actions = result.get("actions")
        if not isinstance(actions, list) or not actions:
            return None

        return actions

    async def _get_room_entities_for_prompt(self) -> list[dict]:
        """Build entity list for AI context from room config + HA area."""
        entities = []
        seen = set()

        def add(entity_id: str) -> None:
            if entity_id in seen:
                return
            state = self.hass.states.get(entity_id)
            if not state:
                return
            seen.add(entity_id)
            entities.append({
                "entity_id": entity_id,
                "name": state.attributes.get("friendly_name", entity_id),
                "domain": entity_id.split(".")[0],
            })

        # Explicitly configured devices
        for key in (CONF_LIGHTS, CONF_FANS, CONF_AUTO_DEVICES, CONF_MANUAL_DEVICES,
                    CONF_COVERS, CONF_AUTO_SWITCHES, CONF_MANUAL_SWITCHES):
            for eid in self._get_current(key, []) or []:
                add(eid)

        if climate := self._get_current(CONF_CLIMATE_ENTITY):
            add(climate)

        # All entities in the room's HA area
        area_id = self._get_current(CONF_AREA_ID)
        if area_id:
            ent_reg = er.async_get(self.hass)
            for entity in ent_reg.entities.values():
                if entity.area_id == area_id and not entity.disabled:
                    add(entity.entity_id)

        return entities

    # v3.12.0: Domain allowlist for AI rule service calls.
    _AI_RULE_ALLOWED_DOMAINS: set = {
        "light", "switch", "fan", "cover", "climate", "media_player",
        "lock", "scene", "automation", "input_boolean", "input_number",
        "input_select", "input_text", "number", "select", "button",
        "humidifier", "vacuum", "water_heater", "valve",
    }

    def _validate_parsed_actions(self, actions: list[dict]) -> tuple[bool, list[str]]:
        """Validate AI-parsed actions. Entity existence + domain allowlist + structure checks."""
        errors = []
        for i, action in enumerate(actions):
            label = f"Action {i + 1}"
            if not isinstance(action, dict):
                errors.append(f"{label}: must be an object, got {type(action).__name__}")
                continue
            for key in ("domain", "service", "target"):
                if key not in action:
                    errors.append(f"{label}: missing '{key}'")
            # Domain allowlist check — reject dangerous domains at config time
            domain = action.get("domain", "")
            if domain and domain not in self._AI_RULE_ALLOWED_DOMAINS:
                errors.append(f"{label}: domain '{domain}' is not allowed")
            target = action.get("target", {})
            if not isinstance(target, dict):
                errors.append(f"{label}: 'target' must be an object")
                target = {}
            entity_id = target.get("entity_id")
            if entity_id:
                eids = entity_id if isinstance(entity_id, list) else [entity_id]
                for eid in eids:
                    if not self.hass.states.get(eid):
                        errors.append(f"{label}: entity '{eid}' not found")
            if "data" in action and not isinstance(action["data"], dict):
                errors.append(f"{label}: 'data' must be an object")
        return len(errors) == 0, errors
