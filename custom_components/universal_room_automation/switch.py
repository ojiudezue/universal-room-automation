"""Switch platform for Universal Room Automation."""
#
# Universal Room Automation v3.18.3
# Build: 2026-01-02
# File: switch.py
#

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_DOMAIN_COORDINATORS_ENABLED,
    CONF_ENERGY_ENABLED,
    CONF_ENTRY_TYPE,
    CONF_HVAC_ENABLED,
    CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED,
    CONF_NM_ENABLED,
    CONF_PRESENCE_ENABLED,
    CONF_SAFETY_ENABLED,
    CONF_SECURITY_ENABLED,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_INTEGRATION,
    VERSION,
)
from .coordinator import UniversalRoomCoordinator
from .entity import UniversalRoomEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Universal Room Automation switches."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE)

    # v3.6.0-c2.4: Integration entry — master coordinators toggle
    if entry_type == ENTRY_TYPE_INTEGRATION:
        async_add_entities([DomainCoordinatorsSwitch(hass, entry)])
        return

    # v3.6.0-c2.4: CM entry — per-coordinator toggles
    if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:
        async_add_entities([
            CoordinatorEnabledSwitch(
                hass, entry,
                coordinator_id="presence",
                conf_key=CONF_PRESENCE_ENABLED,
                name="Presence Coordinator",
                icon="mdi:account-group",
                device_id="presence_coordinator",
                device_name="URA: Presence Coordinator",
                device_model="Presence Coordinator",
            ),
            CoordinatorEnabledSwitch(
                hass, entry,
                coordinator_id="safety",
                conf_key=CONF_SAFETY_ENABLED,
                name="Safety Coordinator",
                icon="mdi:shield-check",
                device_id="safety_coordinator",
                device_name="URA: Safety Coordinator",
                device_model="Safety Coordinator",
            ),
            CoordinatorEnabledSwitch(
                hass, entry,
                coordinator_id="security",
                conf_key=CONF_SECURITY_ENABLED,
                name="Security Coordinator",
                icon="mdi:shield-lock",
                device_id="security_coordinator",
                device_name="URA: Security Coordinator",
                device_model="Security Coordinator",
            ),
            CoordinatorEnabledSwitch(
                hass, entry,
                coordinator_id="music_following",
                conf_key=CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED,
                name="Music Following Coordinator",
                icon="mdi:music-note",
                device_id="music_following_coordinator",
                device_name="URA: Music Following Coordinator",
                device_model="Music Following Coordinator",
            ),
            # v3.7.0: Energy Coordinator
            CoordinatorEnabledSwitch(
                hass, entry,
                coordinator_id="energy",
                conf_key=CONF_ENERGY_ENABLED,
                name="Energy Coordinator",
                icon="mdi:flash",
                device_id="energy_coordinator",
                device_name="URA: Energy Coordinator",
                device_model="Energy Coordinator",
            ),
            # v3.8.0: HVAC Coordinator
            CoordinatorEnabledSwitch(
                hass, entry,
                coordinator_id="hvac",
                conf_key=CONF_HVAC_ENABLED,
                name="HVAC Coordinator",
                icon="mdi:thermostat",
                device_id="hvac_coordinator",
                device_name="URA: HVAC Coordinator",
                device_model="HVAC Coordinator",
            ),
            # v3.6.29: Notification Manager
            CoordinatorEnabledSwitch(
                hass, entry,
                coordinator_id="notification_manager",
                conf_key=CONF_NM_ENABLED,
                name="Notification Manager",
                icon="mdi:bell-ring",
                device_id="notification_manager",
                device_name="URA: Notification Manager",
                device_model="Notification Manager",
            ),
            # v3.15.3: NM messaging kill switch
            NMMessagingSuppressSwitch(hass, entry),
            # v3.6.37: Security → NM light delegation toggle
            SecurityDelegateLightsSwitch(hass),
            # v3.7.6: Energy Observation Mode toggle
            EnergyObservationModeSwitch(hass, entry),
            # v3.9.0: HVAC transparency switches
            HVACOverrideArresterSwitch(hass, entry),
            HVACACResetSwitch(hass, entry),
            HVACObservationModeSwitch(hass, entry),
            # v3.17.0: Zone Intelligence toggle
            HVACZoneIntelligenceSwitch(hass, entry),
            # v3.18.2: Zone Sweep toggle
            HVACZoneSweepSwitch(hass, entry),
        ])
        return

    # Room entry — standard room switches
    if entry.entry_id not in hass.data.get(DOMAIN, {}):
        return
    coordinator: UniversalRoomCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        AutomationSwitch(coordinator),
        OverrideOccupiedSwitch(coordinator),
        OverrideVacantSwitch(coordinator),
        ClimateAutomationSwitch(coordinator),
        CoverAutomationSwitch(coordinator),
        ManualModeSwitch(coordinator),
    ]

    async_add_entities(entities)
    _LOGGER.info(
        "Set up %d switches for room: %s",
        len(entities),
        entry.data.get("room_name")
    )


# ============================================================================
# v3.6.0-c2.4: Domain Coordinators Master Toggle
# ============================================================================


class DomainCoordinatorsSwitch(SwitchEntity):
    """Master switch to enable/disable the domain coordinator system.

    Entity: switch.ura_domain_coordinators
    Device: Universal Room Automation (integration device)

    When turned off, the CoordinatorManager is not created on next reload
    and all coordinator sensors show default/unavailable values.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:robot"
    _attr_name = "Domain Coordinators"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_domain_coordinators_enabled"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "integration")},
            name="Universal Room Automation",
            manufacturer="Universal Room Automation",
            model="Whole House",
            sw_version=VERSION,
        )

    @property
    def is_on(self) -> bool:
        """Return True if domain coordinators are enabled."""
        merged = {**self._entry.data, **self._entry.options}
        return merged.get(CONF_DOMAIN_COORDINATORS_ENABLED, False)

    async def async_turn_on(self, **kwargs) -> None:
        """Enable domain coordinators."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_DOMAIN_COORDINATORS_ENABLED: True},
        )
        await self.hass.config_entries.async_reload(self._entry.entry_id)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable domain coordinators."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_DOMAIN_COORDINATORS_ENABLED: False},
        )
        await self.hass.config_entries.async_reload(self._entry.entry_id)


# ============================================================================
# v3.6.0-c2.4: Per-Coordinator Enable/Disable Toggle
# ============================================================================


class CoordinatorEnabledSwitch(SwitchEntity):
    """Enable/disable an individual domain coordinator.

    Entity: switch.ura_{coordinator_id}_coordinator_enabled
    Device: The coordinator's own device

    Stores the enabled state in the CM entry's options. Takes effect
    on next integration reload.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator_id: str,
        conf_key: str,
        name: str,
        icon: str,
        device_id: str,
        device_name: str,
        device_model: str,
    ) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._coordinator_id = coordinator_id
        self._conf_key = conf_key
        self._attr_unique_id = f"{DOMAIN}_{coordinator_id}_coordinator_enabled"
        self._attr_name = f"Enabled"
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Universal Room Automation",
            model=device_model,
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool:
        """Return True if this coordinator is enabled."""
        merged = {**self._entry.data, **self._entry.options}
        return merged.get(self._conf_key, True)

    async def async_turn_on(self, **kwargs) -> None:
        """Enable this coordinator."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, self._conf_key: True},
        )
        # Reload the integration entry to re-register the coordinator
        for ce in self.hass.config_entries.async_entries(DOMAIN):
            if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                await self.hass.config_entries.async_reload(ce.entry_id)
                break

    async def async_turn_off(self, **kwargs) -> None:
        """Disable this coordinator."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, self._conf_key: False},
        )
        for ce in self.hass.config_entries.async_entries(DOMAIN):
            if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                await self.hass.config_entries.async_reload(ce.entry_id)
                break


class EnergyObservationModeSwitch(SwitchEntity):
    """Toggle Energy Coordinator observation mode.

    When ON: All sensors compute normally, but no control actions are executed.
    When OFF (default): Normal operation — sensors + actions.

    Entity: switch.ura_energy_observation_mode
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:eye-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_energy_observation_mode"
        self._attr_name = "Observation Mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_energy(self):
        """Get the energy coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("energy")

    @property
    def is_on(self) -> bool:
        """Return True if observation mode is active."""
        energy = self._get_energy()
        if energy is None:
            return False
        return energy.observation_mode

    async def async_turn_on(self, **kwargs) -> None:
        """Enable observation mode."""
        energy = self._get_energy()
        if energy is not None:
            energy.observation_mode = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable observation mode."""
        energy = self._get_energy()
        if energy is not None:
            energy.observation_mode = False
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Only available when energy coordinator is active."""
        return self._get_energy() is not None


class HVACOverrideArresterSwitch(SwitchEntity, RestoreEntity):
    """Toggle HVAC Override Arrester.

    When ON (default): Arrester detects manual overrides and reverts/compromises.
    When OFF: Passive mode — overrides are tracked for diagnostics but not reverted.

    Entity: switch.ura_hvac_override_arrester
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-alert"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_override_arrester"
        self._attr_name = "Override Arrester"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_hvac(self):
        """Get the HVAC coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    @property
    def is_on(self) -> bool:
        """Return True if override arrester is enabled."""
        hvac = self._get_hvac()
        if hvac is None:
            return True  # default on
        return hvac.override_arrester.enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable override arrester."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.override_arrester.enabled = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable override arrester (passive mode)."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.override_arrester.enabled = False
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            hvac = self._get_hvac()
            if hvac is not None:
                hvac.override_arrester.enabled = last_state.state == "on"

    @property
    def available(self) -> bool:
        """Only available when HVAC coordinator is active."""
        return self._get_hvac() is not None


class HVACACResetSwitch(SwitchEntity, RestoreEntity):
    """Toggle HVAC AC Reset.

    When ON (default): Stuck cooling/heating cycles are detected and
    the thermostat is cycled off briefly to reset the compressor.
    When OFF: AC reset detection is disabled. The thermostat's own
    hardware safety limits still protect the compressor.

    Entity: switch.ura_hvac_ac_reset
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:refresh-circle"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_reset"
        self._attr_name = "AC Reset"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_hvac(self):
        """Get the HVAC coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    @property
    def is_on(self) -> bool:
        """Return True if AC reset is enabled."""
        hvac = self._get_hvac()
        if hvac is None:
            return True  # default on
        return hvac.override_arrester.ac_reset_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable AC reset."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.override_arrester.ac_reset_enabled = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable AC reset."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.override_arrester.ac_reset_enabled = False
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            hvac = self._get_hvac()
            if hvac is not None:
                hvac.override_arrester.ac_reset_enabled = last_state.state == "on"

    @property
    def available(self) -> bool:
        """Only available when HVAC coordinator is active."""
        return self._get_hvac() is not None


class HVACObservationModeSwitch(SwitchEntity, RestoreEntity):
    """Toggle HVAC Coordinator observation mode.

    When ON: Sensors and diagnostics compute normally, but no HVAC actions
    are executed (no preset changes, no fan/cover control, no AC resets).
    When OFF (default): Normal operation.

    Entity: switch.ura_hvac_observation_mode
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:eye-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_observation_mode"
        self._attr_name = "HVAC Observation Mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_hvac(self):
        """Get the HVAC coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    @property
    def is_on(self) -> bool:
        """Return True if HVAC observation mode is active."""
        hvac = self._get_hvac()
        if hvac is None:
            return False
        return hvac.observation_mode

    async def async_turn_on(self, **kwargs) -> None:
        """Enable HVAC observation mode."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.observation_mode = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable HVAC observation mode."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.observation_mode = False
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            hvac = self._get_hvac()
            if hvac is not None:
                hvac.observation_mode = last_state.state == "on"

    @property
    def available(self) -> bool:
        """Only available when HVAC coordinator is active."""
        return self._get_hvac() is not None


class HVACZoneIntelligenceSwitch(SwitchEntity, RestoreEntity):
    """Toggle HVAC Zone Intelligence features.

    When ON (default): Zone Intelligence active — vacancy management, duty cycle
    enforcement, stale sensor failsafe, solar banking, pre-arrival routing,
    zone presence state machine. Finer HVAC control.
    When OFF: System-managed — thermostats manage their own ramp. URA only sets
    presets based on house state. No per-zone vacancy/duty/failsafe overrides.

    Entity: switch.ura_hvac_zone_intelligence
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:brain"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_zone_intelligence"
        self._attr_name = "Zone Intelligence"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_hvac(self):
        """Get the HVAC coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    @property
    def is_on(self) -> bool:
        """Return True if Zone Intelligence is enabled."""
        hvac = self._get_hvac()
        if hvac is None:
            return True  # default on
        return hvac.zone_intelligence_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable Zone Intelligence (finer HVAC control)."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.zone_intelligence_enabled = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable Zone Intelligence (system-managed ramp)."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.zone_intelligence_enabled = False
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            hvac = self._get_hvac()
            if hvac is not None:
                hvac.zone_intelligence_enabled = last_state.state == "on"

    @property
    def available(self) -> bool:
        """Only available when HVAC coordinator is active."""
        return self._get_hvac() is not None


class HVACZoneSweepSwitch(SwitchEntity, RestoreEntity):
    """Toggle HVAC zone vacancy sweep.

    When ON (default): HVAC coordinator turns off lights and fans in zones
    after they become vacant (after grace period expires).
    When OFF: Vacancy sweeps are skipped — lights/fans remain as-is.

    v3.18.2: Provides UI visibility and runtime control over vacancy sweeps.

    Entity: switch.ura_hvac_zone_sweep
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:broom"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._is_on = True  # Default on
        self._attr_unique_id = f"{DOMAIN}_hvac_zone_sweep"
        self._attr_name = "Zone Sweep"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_hvac(self):
        """Get the HVAC coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    def _update_zones(self) -> None:
        """Push sweep enabled/disabled to all zone states."""
        hvac = self._get_hvac()
        if hvac is None:
            return
        zm = hvac.zone_manager
        if zm is None:
            return
        for zone in zm.zones.values():
            zone.vacancy_sweep_enabled = self._is_on

    @property
    def is_on(self) -> bool:
        """Return True if zone vacancy sweep is enabled."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Enable zone vacancy sweeps."""
        self._is_on = True
        self._update_zones()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable zone vacancy sweeps."""
        self._is_on = False
        self._update_zones()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._is_on = last_state.state == "on"
        self._update_zones()

    @property
    def extra_state_attributes(self) -> dict:
        """Expose sweep count as an attribute."""
        hvac = self._get_hvac()
        if hvac is None:
            return {}
        return {
            "sweeps_today": hvac.vacancy_sweeps_today,
        }

    @property
    def available(self) -> bool:
        """Only available when HVAC coordinator is active."""
        return self._get_hvac() is not None


class NMMessagingSuppressSwitch(SwitchEntity, RestoreEntity):
    """Kill switch for NM outbound messaging.

    When ON: All outbound notifications are suppressed. Active alerts are
    cancelled. The NM itself stays running for monitoring/diagnostics.
    When OFF (default): Normal notification delivery.

    Uses RestoreEntity to persist state across HA restarts — if the user
    engages the kill switch, it stays engaged after restart.

    Entity: switch.ura_nm_messaging_suppressed
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-cancel"
    _attr_entity_category = EntityCategory.CONFIG

    _MAX_SYNC_RETRIES = 18  # 18 × 10s = 3 minutes max wait for NM

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._is_on = False  # Self-contained state — survives NM not yet ready
        self._sync_retries = 0
        self._sync_unsub = None  # Cancel handle for deferred sync timer
        self._attr_unique_id = f"{DOMAIN}_nm_messaging_suppressed"
        self._attr_name = "Messaging Suppressed"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "notification_manager")},
            name="URA: Notification Manager",
            manufacturer="Universal Room Automation",
            model="Notification Manager",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    async def async_added_to_hass(self) -> None:
        """Restore state on startup and sync to NM when available."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state == "on":
            self._is_on = True
            _LOGGER.info("Restored messaging suppression flag from previous state")
            # Try to sync to NM immediately (may not exist yet)
            await self._sync_to_nm()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel any pending sync timer on teardown."""
        if self._sync_unsub:
            self._sync_unsub()
            self._sync_unsub = None

    async def _sync_to_nm(self) -> None:
        """Push local state to NM. Retries with bounded attempts."""
        nm = self._get_nm()
        if nm is None:
            self._sync_retries += 1
            if self._sync_retries > self._MAX_SYNC_RETRIES:
                _LOGGER.warning(
                    "NM not available after %d retries — giving up sync "
                    "(switch state preserved locally, will sync on next toggle)",
                    self._sync_retries,
                )
                return
            # NM not ready — schedule a deferred sync
            from homeassistant.helpers.event import async_call_later

            async def _deferred_sync(_now=None):
                self._sync_unsub = None
                await self._sync_to_nm()

            self._sync_unsub = async_call_later(self.hass, 10, _deferred_sync)
            _LOGGER.debug(
                "NM not ready, deferring sync (attempt %d/%d)",
                self._sync_retries, self._MAX_SYNC_RETRIES,
            )
            return
        self._sync_retries = 0
        if self._is_on and not nm.messaging_suppressed:
            await nm.async_suppress_messaging()
            _LOGGER.info("Synced messaging suppression to NM")
        elif not self._is_on and nm.messaging_suppressed:
            await nm.async_resume_messaging()
            _LOGGER.info("Synced messaging resume to NM")

    def _get_nm(self):
        """Get the notification manager instance."""
        return self.hass.data.get(DOMAIN, {}).get("notification_manager")

    @property
    def is_on(self) -> bool:
        """Return True if messaging is suppressed (self-contained state)."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Suppress all outbound messaging."""
        self._is_on = True
        nm = self._get_nm()
        if nm is not None:
            await nm.async_suppress_messaging()
        else:
            self._sync_retries = 0
            await self._sync_to_nm()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Resume outbound messaging."""
        self._is_on = False
        nm = self._get_nm()
        if nm is not None:
            await nm.async_resume_messaging()
        else:
            self._sync_retries = 0
            await self._sync_to_nm()
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Always available — state is self-contained, NM synced when ready."""
        return True


class SecurityDelegateLightsSwitch(SwitchEntity, RestoreEntity):
    """Toggle whether Security Coordinator delegates light control to Notification Manager.

    When ON (default): Security alerts send NotificationAction with hazard_type,
    and NM handles light patterns (intruder flash, investigate, etc.).
    When OFF: Security directly controls configured security lights via ServiceCallAction.

    Entity: switch.ura_security_delegate_lights_to_nm
    Device: Security Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:lightbulb-auto"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self.hass = hass
        self._attr_unique_id = f"{DOMAIN}_security_delegate_lights_to_nm"
        self._attr_name = "Delegate Lights to NM"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "security_coordinator")},
            name="URA: Security Coordinator",
            manufacturer="Universal Room Automation",
            model="Security Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        self._is_on = True

    @property
    def is_on(self) -> bool:
        """Return True if light delegation to NM is enabled."""
        return self._is_on

    async def async_added_to_hass(self) -> None:
        """Restore state and sync to coordinator."""
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._is_on = last_state.state == "on"
        self._sync_to_coordinator()

    async def async_turn_on(self, **kwargs) -> None:
        """Enable NM light delegation."""
        self._is_on = True
        self._sync_to_coordinator()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable NM light delegation (use direct light control)."""
        self._is_on = False
        self._sync_to_coordinator()
        self.async_write_ha_state()

    def _sync_to_coordinator(self) -> None:
        """Push current state to the SecurityCoordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        security = manager.coordinators.get("security")
        if security is not None:
            security.delegate_lights_to_nm = self._is_on


class AutomationSwitch(UniversalRoomEntity, SwitchEntity, RestoreEntity):
    """Switch to enable/disable room automation."""

    _attr_icon = "mdi:home-automation"

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "automation", "Automation")
        self._attr_is_on = True  # Default to enabled

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on automation."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("Automation enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off automation."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Automation disabled for room: %s", self.coordinator.entry.data.get("room_name"))


class OverrideOccupiedSwitch(UniversalRoomEntity, SwitchEntity):
    """Switch to override room as occupied."""

    _attr_icon = "mdi:account-check"

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "override_occupied", "Override Occupied")
        self._attr_is_on = False

    async def async_turn_on(self, **kwargs) -> None:
        """Force room to occupied state."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("Override occupied enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Remove occupied override."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Override occupied disabled for room: %s", self.coordinator.entry.data.get("room_name"))


class OverrideVacantSwitch(UniversalRoomEntity, SwitchEntity):
    """Switch to override room as vacant."""

    _attr_icon = "mdi:account-off"

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "override_vacant", "Override Vacant")
        self._attr_is_on = False

    async def async_turn_on(self, **kwargs) -> None:
        """Force room to vacant state."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("Override vacant enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Remove vacant override."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Override vacant disabled for room: %s", self.coordinator.entry.data.get("room_name"))


class ClimateAutomationSwitch(UniversalRoomEntity, SwitchEntity, RestoreEntity):
    """Switch to enable/disable climate-specific automation."""

    _attr_icon = "mdi:thermostat-auto"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "climate_automation", "Climate Automation")
        self._attr_is_on = True  # Default to enabled

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"

    @property
    def available(self) -> bool:
        """Switch is always available."""
        return True

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on climate automation."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("Climate automation enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off climate automation."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Climate automation disabled for room: %s", self.coordinator.entry.data.get("room_name"))


class CoverAutomationSwitch(UniversalRoomEntity, SwitchEntity, RestoreEntity):
    """Switch to enable/disable cover automation."""

    _attr_icon = "mdi:window-shutter-auto"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "cover_automation", "Cover Automation")
        self._attr_is_on = True  # Default to enabled

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"

    @property
    def available(self) -> bool:
        """Switch is always available."""
        return True

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on cover automation."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("Cover automation enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off cover automation."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Cover automation disabled for room: %s", self.coordinator.entry.data.get("room_name"))


class ManualModeSwitch(UniversalRoomEntity, SwitchEntity, RestoreEntity):
    """Switch to force manual control mode."""

    _attr_icon = "mdi:hand-back-right"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "manual_mode", "Manual Mode")
        self._attr_is_on = False  # Default to disabled

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"

    @property
    def available(self) -> bool:
        """Switch is always available."""
        return True

    async def async_turn_on(self, **kwargs) -> None:
        """Enable manual mode (disables all automation)."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("Manual mode enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Disable manual mode (allows automation)."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Manual mode disabled for room: %s", self.coordinator.entry.data.get("room_name"))
