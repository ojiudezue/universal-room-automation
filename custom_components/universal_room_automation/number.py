"""Number platform for Universal Room Automation."""
#
# Universal Room Automation vv5.8.0
# Build: 2026-01-02
# File: number.py
#
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import UnitOfTemperature, UnitOfTime, PERCENTAGE

from .const import (
    DOMAIN,
    CONF_ENTRY_TYPE,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    CONF_BAYESIAN_CELL_STALENESS_DAYS,
    # D6 (Phase 1 Optimizer): per-room comfort slider option keys.
    # Seed-from-options + options write-back closes the v1 plan
    # Appendix-A orphan (entities existed RAM-only; now persistent).
    CONF_COMFORT_TEMP_MIN,
    CONF_COMFORT_TEMP_MAX,
    CONF_COMFORT_HUMIDITY_MAX,
    COMFORT_TEMP_MIN,
    COMFORT_TEMP_MAX,
    COMFORT_HUMIDITY_MAX,
    DEFAULT_OCCUPANCY_TIMEOUT,
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
    """Set up Universal Room Automation number entities."""
    # v4.2.2: Coordinator Manager entry gets HVAC number entities
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
        entities = [
            ZoneEntryDwellNumber(hass, entry),
            # Presence-timer cluster — entry.options is the SOLE source of
            # truth (no RestoreEntity). Live-attr push happens BEFORE the
            # writeback so the next HVAC decision cycle picks up the new
            # value immediately; writeback persists across restart/reload.
            VacancyGraceMinutesNumber(hass, entry),
            VacancyGraceConstrainedNumber(hass, entry),
            MaxOccupancyHoursNumber(hass, entry),
            # v4.2.10: Off-peak drain target numbers
            OffPeakDrainNumber(hass, entry, "excellent", 10, 5, 50),
            OffPeakDrainNumber(hass, entry, "good", 15, 5, 60),
            OffPeakDrainNumber(hass, entry, "moderate", 20, 5, 70),
            OffPeakDrainNumber(hass, entry, "poor", 30, 5, 80),
            # v4.5.0 D2: Peak buffer target replaces arbitrage_target slider.
            # The arbitrage_trigger slider is removed entirely — the gate is
            # now forecast-class only (no SOC trigger).
            PeakBufferTargetNumber(hass, entry, 80, 30, 95),
            # v4.5.0 D2: live-tunable charge lead time (NumberMode.BOX, not
            # slider — user has slider fatigue; minute-precision values are
            # easier to type than drag). Hard min 120 (physics floor + safety).
            ArbitrageChargeLeadTimeNumber(hass, entry),
            # v4.3.3: EV battery drain SOC slider
            EVBatteryDrainSOCNumber(hass, entry, 50),
            # v4.7.6 D3.2: EV fill-priority SOC slider — when SOC below this
            # and solar forecast healthy, pause EVSEs so battery fills first.
            FillPrioritySOCNumber(hass, entry, 80),
            # v4.7.6.1 D1: Excess-solar SOC slider — when SOC above this AND
            # solar surplus available, URA turns EVSEs ON even during off-peak
            # pause. Live-tunable companion to FillPrioritySOCNumber.
            ExcessSolarSOCNumber(hass, entry, 95),
            # v4.7.8 D2: Egress Window HVAC Pause threshold + resume-delay
            # sliders on the HVAC Coordinator device.
            HVACEgressPauseThresholdNumber(hass, entry, 3),
            HVACEgressResumeDelayNumber(hass, entry, 1),
            # Fan-noise mitigation D1: Layer-1 silent gate hold duration.
            # Lives on the Presence Coordinator device. Pushes operator
            # changes into ``PresenceCoordinator._fan_interference_hold_s``
            # via ``set_fan_interference_hold_s``.
            FanInterferenceHoldNumber(hass, entry),
            # Fan-noise Mode-2: 7 timing knobs moved to collapsed
            # options-flow section; runtime Numbers deleted.
            # v4.6.2 D3: Bayesian cell staleness window (default 14 days)
            BayesianCellStalenessNumber(hass, entry),
            # v4.6.2 D6: routine notification tunables
            RoutineEventCooldownDaysNumber(hass, entry),
            RoutineEventMinSeverityNumber(hass, entry),
            RoutineRegimeBaselineWindowNumber(hass, entry),
            RoutineRegimeRecentWindowNumber(hass, entry),
            # v4.7.1 Cycle B: Dynamic Preset runtime tunables
            DynamicPresetDwellMinutesNumber(hass, entry),
            DynamicPresetHysteresisFNumber(hass, entry),
            # v5.7.1: Energy Saver Pre-Cool Offset (EC device).
            # Operator-configurable per-cycle setpoint offset (default -2°F).
            EnergyPreCoolOffsetNumber(hass, entry),
        ]
        # v4.5.10: 7 HVAC tunable Number entities on the HVAC Coordinator device.
        # Each is a runtime slider; form values seed install-time only,
        # then RestoreEntity-backed slider is the source of truth.
        for cls in _build_hvac_v4510_numbers():
            entities.append(cls(hass, entry))
        # v4.5.11: 6 house-wide AC ramp-down tunables + 1 per-zone kWh
        # rate threshold per AC zone. The per-zone count varies with
        # configured zones (3 for the canonical 2x3-ton + 1x4-ton install).
        for cls in _build_hvac_v4511_numbers():
            entities.append(cls(hass, entry))
        for zone_spec in _discover_ac_zones(hass):
            # v4.5.13.1.1: helper returns 5 keys (zone_id, zone_name,
            # climate_entity, ac_load_sensor, ramp_zone_enabled); the
            # threshold factory only accepts the first 3. Filter here
            # to keep the factory's signature minimal and stable.
            cls = _hvac_zone_kwh_threshold_factory(
                zone_id=zone_spec["zone_id"],
                zone_name=zone_spec["zone_name"],
                climate_entity=zone_spec["climate_entity"],
            )
            entities.append(cls(hass, entry))
        async_add_entities(entities)
        _LOGGER.info("Set up %d CM number entities", len(entities))
        return

    if entry.entry_id not in hass.data.get(DOMAIN, {}):
        return

    coordinator: UniversalRoomCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        TimeoutOverrideNumber(coordinator),
        ComfortTempMinNumber(coordinator),
        ComfortTempMaxNumber(coordinator),
        ComfortHumidityMaxNumber(coordinator),
    ]

    async_add_entities(entities)
    _LOGGER.info(
        "Set up %d number entities for room: %s",
        len(entities),
        entry.data.get("room_name")
    )


class TimeoutOverrideNumber(UniversalRoomEntity, NumberEntity):
    """Number entity for temporary occupancy timeout override."""

    _attr_icon = "mdi:timer-cog"
    _attr_native_min_value = 60
    _attr_native_max_value = 3600
    _attr_native_step = 30
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, "timeout_override", "Timeout Override")
        self._attr_native_value = coordinator.entry.data.get("occupancy_timeout", DEFAULT_OCCUPANCY_TIMEOUT)

    @property
    def native_value(self) -> float:
        """Return current timeout value."""
        return self.coordinator._occupancy_timeout

    @property
    def available(self) -> bool:
        """Number is always available."""
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Set new timeout value."""
        self.coordinator._occupancy_timeout = int(value)
        self.async_write_ha_state()
        _LOGGER.info(
            "Timeout override set to %d seconds for room: %s",
            int(value),
            self.coordinator.entry.data.get("room_name")
        )


class ComfortTempMinNumber(UniversalRoomEntity, NumberEntity):
    """Number entity for minimum comfort temperature."""

    _attr_icon = "mdi:thermometer-low"
    _attr_native_min_value = 60
    _attr_native_max_value = 80
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, "comfort_temp_min", "Comfort Temperature Min")
        # D6: seed-from-options. Precedence — entry.options → entry.data
        # → module constant fallback. Options write-back IS the
        # persistence (Bug Class #46 sole-source pattern); no
        # RestoreEntity needed.
        entry = coordinator.entry
        opts = getattr(entry, "options", {}) or {}
        data = getattr(entry, "data", {}) or {}
        if CONF_COMFORT_TEMP_MIN in opts and opts[CONF_COMFORT_TEMP_MIN] is not None:
            self._value = float(opts[CONF_COMFORT_TEMP_MIN])
        elif CONF_COMFORT_TEMP_MIN in data and data[CONF_COMFORT_TEMP_MIN] is not None:
            self._value = float(data[CONF_COMFORT_TEMP_MIN])
        else:
            self._value = COMFORT_TEMP_MIN

    @property
    def native_value(self) -> float:
        """Return current minimum comfort temperature."""
        return self._value

    @property
    def available(self) -> bool:
        """Number is always available."""
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Set new minimum comfort temperature."""
        self._value = value
        # D6: write back to entry.options (sole-source-of-truth pattern,
        # Bug Class #46). Survives restart without RestoreEntity.
        entry = self.coordinator.entry
        try:
            options = {**(entry.options or {}), CONF_COMFORT_TEMP_MIN: value}
            self.coordinator.hass.config_entries.async_update_entry(
                entry, options=options,
            )
        except Exception as exc:  # noqa: BLE001 — never crash UI write
            _LOGGER.debug(
                "Comfort temp min options write-back failed: %s", exc,
                exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info(
            "Comfort temp min set to %.1f°F for room: %s",
            value,
            self.coordinator.entry.data.get("room_name")
        )


class ComfortTempMaxNumber(UniversalRoomEntity, NumberEntity):
    """Number entity for maximum comfort temperature."""

    _attr_icon = "mdi:thermometer-high"
    _attr_native_min_value = 65
    _attr_native_max_value = 85
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, "comfort_temp_max", "Comfort Temperature Max")
        # D6: seed-from-options.
        entry = coordinator.entry
        opts = getattr(entry, "options", {}) or {}
        data = getattr(entry, "data", {}) or {}
        if CONF_COMFORT_TEMP_MAX in opts and opts[CONF_COMFORT_TEMP_MAX] is not None:
            self._value = float(opts[CONF_COMFORT_TEMP_MAX])
        elif CONF_COMFORT_TEMP_MAX in data and data[CONF_COMFORT_TEMP_MAX] is not None:
            self._value = float(data[CONF_COMFORT_TEMP_MAX])
        else:
            self._value = COMFORT_TEMP_MAX

    @property
    def native_value(self) -> float:
        """Return current maximum comfort temperature."""
        return self._value

    @property
    def available(self) -> bool:
        """Number is always available."""
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Set new maximum comfort temperature."""
        self._value = value
        # D6: write-back to entry.options.
        entry = self.coordinator.entry
        try:
            options = {**(entry.options or {}), CONF_COMFORT_TEMP_MAX: value}
            self.coordinator.hass.config_entries.async_update_entry(
                entry, options=options,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "Comfort temp max options write-back failed: %s", exc,
                exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info(
            "Comfort temp max set to %.1f°F for room: %s",
            value,
            self.coordinator.entry.data.get("room_name")
        )


class ComfortHumidityMaxNumber(UniversalRoomEntity, NumberEntity):
    """Number entity for maximum comfort humidity."""

    _attr_icon = "mdi:water-percent"
    _attr_native_min_value = 40
    _attr_native_max_value = 70
    _attr_native_step = 5
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, "comfort_humidity_max", "Comfort Humidity Max")
        # D6: seed-from-options.
        entry = coordinator.entry
        opts = getattr(entry, "options", {}) or {}
        data = getattr(entry, "data", {}) or {}
        if CONF_COMFORT_HUMIDITY_MAX in opts and opts[CONF_COMFORT_HUMIDITY_MAX] is not None:
            self._value = float(opts[CONF_COMFORT_HUMIDITY_MAX])
        elif CONF_COMFORT_HUMIDITY_MAX in data and data[CONF_COMFORT_HUMIDITY_MAX] is not None:
            self._value = float(data[CONF_COMFORT_HUMIDITY_MAX])
        else:
            self._value = COMFORT_HUMIDITY_MAX

    @property
    def native_value(self) -> float:
        """Return current maximum comfort humidity."""
        return self._value

    @property
    def available(self) -> bool:
        """Number is always available."""
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Set new maximum comfort humidity."""
        self._value = value
        # D6: write-back to entry.options.
        entry = self.coordinator.entry
        try:
            options = {**(entry.options or {}), CONF_COMFORT_HUMIDITY_MAX: value}
            self.coordinator.hass.config_entries.async_update_entry(
                entry, options=options,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "Comfort humidity max options write-back failed: %s", exc,
                exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info(
            "Comfort humidity max set to %.0f%% for room: %s",
            value,
            self.coordinator.entry.data.get("room_name")
        )


class ZoneEntryDwellNumber(NumberEntity):
    """Configurable zone entry dwell time on HVAC Coordinator device.

    Minutes a zone must be occupied before switching from away to home preset.
    Prevents HVAC flapping when someone briefly transits through a zone.
    Only applies when the house is already occupied.

    Entity: number.ura_hvac_coordinator_zone_entry_dwell
    v4.2.2
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-sand"
    _attr_native_min_value = 0
    _attr_native_max_value = 15
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    # Operator decision: BOX (not slider). All four presence-timer Numbers
    # in the 47-50 cluster are precise minute/hour values; BOX is easier to
    # land on than a slider on a tablet.
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        from homeassistant.helpers.device_registry import DeviceInfo
        from .domain_coordinators.hvac_const import (
            DEFAULT_ZONE_ENTRY_DWELL_MINUTES,
            CONF_HVAC_ZONE_ENTRY_DWELL,
        )
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_zone_entry_dwell"
        self._attr_name = "47 · Zone Entry Dwell (minutes)"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        config = {**entry.data, **entry.options}
        self._value = int(config.get(
            CONF_HVAC_ZONE_ENTRY_DWELL, DEFAULT_ZONE_ENTRY_DWELL_MINUTES,
        ))

    def _get_hvac(self):
        """Get the HVAC coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    @property
    def native_value(self) -> float:
        """Return current dwell value."""
        return self._value

    @property
    def available(self) -> bool:
        """Only available when HVAC coordinator is active."""
        return self._get_hvac() is not None

    async def async_set_native_value(self, value: float) -> None:
        """Set new dwell value — takes effect on next HVAC decision cycle.

        Persistence pattern (Bug Class #32 fix): entry.options is the SOLE
        source of truth. Live-attr push happens BEFORE writeback so the
        decision-cycle reader picks up the value on the very next tick;
        the writeback persists it across restarts and reloads.

        Reload-window note (review B-M1): the writeback below triggers an
        untracked CM reload. If a prior save's reload is mid-flight, the
        live-attr push here may write into a soon-to-be-discarded hvac
        instance — harmless: the rebuilt coordinator re-seeds the same attr
        from entry.options (__init__.py CM setup), so the value converges.
        """
        from .domain_coordinators.hvac_const import CONF_HVAC_ZONE_ENTRY_DWELL
        self._value = int(value)
        hvac = self._get_hvac()
        if hvac is not None:
            hvac._zone_entry_dwell = int(value)
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_HVAC_ZONE_ENTRY_DWELL: int(value)},
        )
        self.async_write_ha_state()
        _LOGGER.info("Zone entry dwell set to %d minutes", int(value))


class VacancyGraceMinutesNumber(NumberEntity):
    """Configurable Zone Vacancy Delay (minutes) on HVAC Coordinator device.

    Minutes a zone must stay empty before HVAC backs off to Away preset.

    Entity: number.ura_hvac_coordinator_vacancy_grace
    Device: URA: HVAC Coordinator

    entry.options is the SOLE source of truth (no RestoreEntity).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-sand"
    _attr_native_min_value = 0
    _attr_native_max_value = 60
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .domain_coordinators.hvac_const import (
            CONF_HVAC_VACANCY_GRACE_MINUTES,
            DEFAULT_VACANCY_GRACE_MINUTES,
        )
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_vacancy_grace_minutes"
        self._attr_name = "48 · Zone Vacancy Delay (minutes)"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        config = {**entry.data, **entry.options}
        self._value = int(config.get(
            CONF_HVAC_VACANCY_GRACE_MINUTES, DEFAULT_VACANCY_GRACE_MINUTES,
        ))

    def _get_hvac(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return self._get_hvac() is not None

    async def async_set_native_value(self, value: float) -> None:
        from .domain_coordinators.hvac_const import (
            CONF_HVAC_VACANCY_GRACE_MINUTES,
            CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
            DEFAULT_VACANCY_GRACE_CONSTRAINED,
        )
        new_value = int(value)
        self._value = new_value
        hvac = self._get_hvac()
        if hvac is not None:
            hvac._vacancy_grace = new_value
        # Invariant (review HIGH-1): energy-saving delay must stay <= normal.
        # If lowering the normal delay below the persisted energy-saving
        # delay, clamp the latter down in the SAME writeback so the pair is
        # never left inverted.
        options = {**self._entry.options, CONF_HVAC_VACANCY_GRACE_MINUTES: new_value}
        config = {**self._entry.data, **self._entry.options}
        constrained = int(config.get(
            CONF_HVAC_VACANCY_GRACE_CONSTRAINED, DEFAULT_VACANCY_GRACE_CONSTRAINED,
        ))
        if constrained > new_value:
            options[CONF_HVAC_VACANCY_GRACE_CONSTRAINED] = new_value
            if hvac is not None:
                hvac._vacancy_grace_constrained = new_value
            _LOGGER.info(
                "Energy-saving zone vacancy delay clamped from %d to %d "
                "minutes to stay <= new normal delay",
                constrained, new_value,
            )
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self.async_write_ha_state()
        _LOGGER.info("Zone vacancy delay set to %d minutes", new_value)


class VacancyGraceConstrainedNumber(NumberEntity):
    """Energy-saving Zone Vacancy Delay (minutes) on HVAC Coordinator device.

    Shorter delay used while the house is in an energy-coast/shed regime.
    Must be <= the normal Zone Vacancy Delay.

    Entity: number.ura_hvac_coordinator_vacancy_grace_constrained
    Device: URA: HVAC Coordinator

    entry.options is the SOLE source of truth (no RestoreEntity).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-sand"
    _attr_native_min_value = 0
    _attr_native_max_value = 60
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .domain_coordinators.hvac_const import (
            CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
            DEFAULT_VACANCY_GRACE_CONSTRAINED,
        )
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_vacancy_grace_constrained"
        self._attr_name = "49 · Zone Vacancy Delay · Energy-Saving (minutes)"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        config = {**entry.data, **entry.options}
        self._value = int(config.get(
            CONF_HVAC_VACANCY_GRACE_CONSTRAINED, DEFAULT_VACANCY_GRACE_CONSTRAINED,
        ))

    def _get_hvac(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return self._get_hvac() is not None

    async def async_set_native_value(self, value: float) -> None:
        from .domain_coordinators.hvac_const import (
            CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
            CONF_HVAC_VACANCY_GRACE_MINUTES,
            DEFAULT_VACANCY_GRACE_MINUTES,
        )
        # Invariant (review HIGH-1): energy-saving delay must be <= normal
        # delay, else the HVAC energy_constrained branch (hvac.py) waits
        # LONGER to back off during the very regime it should throttle. The
        # config-flow form enforces this, but a direct number.set_value can't
        # — clamp here so the entity path can't violate it.
        config = {**self._entry.data, **self._entry.options}
        normal = int(config.get(
            CONF_HVAC_VACANCY_GRACE_MINUTES, DEFAULT_VACANCY_GRACE_MINUTES,
        ))
        new_value = min(int(value), normal)
        if new_value != int(value):
            _LOGGER.info(
                "Energy-saving zone vacancy delay clamped from %d to %d "
                "minutes (must be <= normal delay of %d)",
                int(value), new_value, normal,
            )
        self._value = new_value
        hvac = self._get_hvac()
        if hvac is not None:
            hvac._vacancy_grace_constrained = new_value
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_HVAC_VACANCY_GRACE_CONSTRAINED: new_value},
        )
        self.async_write_ha_state()
        _LOGGER.info(
            "Zone vacancy delay (energy-saving) set to %d minutes", new_value,
        )


class MaxOccupancyHoursNumber(NumberEntity):
    """Max Zone Occupied Time (hours) on HVAC Coordinator device.

    If a zone reads continuously occupied this long, HVAC stops trusting
    the presence signal as stuck.

    Entity: number.ura_hvac_coordinator_max_occupancy_hours
    Device: URA: HVAC Coordinator

    entry.options is the SOLE source of truth (no RestoreEntity).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-alert-outline"
    _attr_native_min_value = 1
    _attr_native_max_value = 24
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .domain_coordinators.hvac_const import (
            CONF_HVAC_MAX_OCCUPANCY_HOURS,
            DEFAULT_MAX_OCCUPANCY_HOURS,
        )
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_max_occupancy_hours"
        self._attr_name = "50 · Max Zone Occupied Time (hours)"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        config = {**entry.data, **entry.options}
        self._value = int(config.get(
            CONF_HVAC_MAX_OCCUPANCY_HOURS, DEFAULT_MAX_OCCUPANCY_HOURS,
        ))

    def _get_hvac(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return self._get_hvac() is not None

    async def async_set_native_value(self, value: float) -> None:
        from .domain_coordinators.hvac_const import CONF_HVAC_MAX_OCCUPANCY_HOURS
        self._value = int(value)
        hvac = self._get_hvac()
        if hvac is not None:
            hvac._max_occupancy_hours = int(value)
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_HVAC_MAX_OCCUPANCY_HOURS: int(value)},
        )
        self.async_write_ha_state()
        _LOGGER.info("Max zone occupied time set to %d hours", int(value))


class OffPeakDrainNumber(NumberEntity):
    """Configurable off-peak battery drain target on Energy Coordinator device.

    SOC% to drain to overnight based on tomorrow's solar forecast quality.
    v4.2.10: Exposes config-flow-only values as runtime-adjustable numbers.

    Part 2 (post-v4.7.26): entry.options is the SOLE source of truth (no
    RestoreEntity). The setter calls `energy.set_offpeak_drain(quality, value)`
    BEFORE `async_update_entry`, then writes state. Restart re-seeds via
    `__init__`'s `{**entry.data, **entry.options}` read. The CM reload
    listener's allowlist suppresses full-CM-reload on these CONF keys; the
    `apply_in_place` dispatch branch invokes the same setter so form-path
    edits land identically to entity-path edits.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:battery-arrow-down-outline"
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry,
        quality: str, default: int, min_val: int, max_val: int,
    ) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self.hass = hass
        self._entry = entry
        self._quality = quality
        self._attr_unique_id = f"{DOMAIN}_energy_offpeak_drain_{quality}"
        self._attr_name = f"Off-Peak Drain {quality.title()}"
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # Read initial value from config entry
        from .domain_coordinators.energy_const import (
            CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT,
            CONF_ENERGY_OFFPEAK_DRAIN_GOOD,
            CONF_ENERGY_OFFPEAK_DRAIN_MODERATE,
            CONF_ENERGY_OFFPEAK_DRAIN_POOR,
        )
        conf_map = {
            "excellent": CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT,
            "good": CONF_ENERGY_OFFPEAK_DRAIN_GOOD,
            "moderate": CONF_ENERGY_OFFPEAK_DRAIN_MODERATE,
            "poor": CONF_ENERGY_OFFPEAK_DRAIN_POOR,
        }
        config = {**entry.data, **entry.options}
        self._value = config.get(conf_map.get(quality, ""), default)

    def _get_energy(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return self._get_energy() is not None

    async def async_added_to_hass(self) -> None:
        """Push the seeded value into the live coordinator if reachable.

        No RestoreEntity. The constructor already seeded `self._value` from
        `{**entry.data, **entry.options}`; this pass mirrors the seed into
        the EC setter so the coordinator is in sync at first availability.
        """
        await super().async_added_to_hass()
        energy = self._get_energy()
        if energy is not None:
            try:
                energy.set_offpeak_drain(self._quality, int(self._value))
            except Exception:  # noqa: BLE001 — coord may be mid-init
                _LOGGER.debug(
                    "OffPeakDrain seed-push deferred (%s)", self._quality,
                )

    async def async_set_native_value(self, value: float) -> None:
        self._value = int(value)
        # Live-attr push via EC setter BEFORE async_update_entry so the
        # next decision cycle picks up the new value even if the listener
        # is still in flight. Setter calls _check_threshold_ladder() too.
        energy = self._get_energy()
        if energy is not None:
            energy.set_offpeak_drain(self._quality, int(value))
        # Persist into entry.options (sole source of truth for restart-
        # restore + reload-suppression diff).
        try:
            from .domain_coordinators.energy_const import (
                CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT,
                CONF_ENERGY_OFFPEAK_DRAIN_GOOD,
                CONF_ENERGY_OFFPEAK_DRAIN_MODERATE,
                CONF_ENERGY_OFFPEAK_DRAIN_POOR,
            )
            conf_map = {
                "excellent": CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT,
                "good": CONF_ENERGY_OFFPEAK_DRAIN_GOOD,
                "moderate": CONF_ENERGY_OFFPEAK_DRAIN_MODERATE,
                "poor": CONF_ENERGY_OFFPEAK_DRAIN_POOR,
            }
            conf_key = conf_map.get(self._quality)
            if conf_key is not None:
                self.hass.config_entries.async_update_entry(
                    self._entry,
                    options={**self._entry.options, conf_key: int(value)},
                )
        except Exception:  # noqa: BLE001 — best-effort persist
            _LOGGER.debug(
                "OffPeakDrain options-writeback failed (%s)", self._quality,
                exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info("Off-peak drain %s set to %d%%", self._quality, int(value))


class PeakBufferTargetNumber(NumberEntity):
    """Configurable peak buffer target on Energy Coordinator device.

    v4.5.0 D2: replaces the v4.3.0 ArbitrageSOCNumber(role="target") slider.
    Renamed for clarity — this is the SOC the strategy holds in reserve
    for the upcoming high-rate window. The v4.3.0 ArbitrageSOCNumber
    (role="trigger") is removed entirely; v4.5.0's arbitrage gate is
    forecast-class only (no SOC trigger).

    Render mode stays SLIDER (consistent with existing % SOC sliders).

    Part 2 (post-v4.7.26): entry.options is the SOLE source of truth (no
    RestoreEntity). The setter calls `energy.set_peak_buffer_target(value)`
    BEFORE `async_update_entry`, then writes state. Restart re-seeds via
    `__init__`'s `{**entry.data, **entry.options}` read.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:battery-charging-100"
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry,
        default: int, min_val: int, max_val: int,
    ) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_energy_peak_buffer_target"
        self._attr_name = "Peak Buffer Target"
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # v4.5.0 D2 migration ergonomics: initial seed reads the new key
        # first, falling back to the legacy key. The migration helper in
        # __init__.py copies the old value to the new key during setup
        # so most installs hit the new key directly.
        from .domain_coordinators.energy_const import (
            CONF_ENERGY_PEAK_BUFFER_TARGET,
            CONF_ENERGY_ARBITRAGE_SOC_TARGET,
        )
        config = {**entry.data, **entry.options}
        self._value = int(config.get(
            CONF_ENERGY_PEAK_BUFFER_TARGET,
            config.get(CONF_ENERGY_ARBITRAGE_SOC_TARGET, default),
        ))

    def _get_energy(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return self._get_energy() is not None

    def _push_to_coordinator(self) -> bool:
        """Push current slider value into EnergyCoordinator."""
        energy = self._get_energy()
        if energy is None:
            return False
        energy.set_peak_buffer_target(self._value)
        return True

    async def async_added_to_hass(self) -> None:
        """Push the seeded value into EC; deferred-retry on cross-entry race.

        No RestoreEntity. Constructor seeded `self._value` from
        `{**entry.data, **entry.options}`. v4.3.0 C3 retry-on-signal handles
        the cross-entry init race when EC isn't yet registered at first add.
        """
        await super().async_added_to_hass()

        if not self._push_to_coordinator():
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            from .domain_coordinators.signals import SIGNAL_ENERGY_ENTITIES_UPDATE
            unsub_holder: list = []

            @callback
            def _on_energy_tick(*_args, **_kwargs):
                if self._push_to_coordinator() and unsub_holder:
                    unsub_holder[0]()
                    _LOGGER.debug(
                        "Peak buffer target slider pushed to EC after deferred ready"
                    )

            unsub_holder.append(
                async_dispatcher_connect(
                    self.hass, SIGNAL_ENERGY_ENTITIES_UPDATE, _on_energy_tick,
                )
            )
            self.async_on_remove(unsub_holder[0])

    async def async_set_native_value(self, value: float) -> None:
        self._value = int(value)
        # Live-attr push BEFORE async_update_entry (setter also runs
        # _check_threshold_ladder).
        self._push_to_coordinator()
        try:
            from .domain_coordinators.energy_const import (
                CONF_ENERGY_PEAK_BUFFER_TARGET,
            )
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **self._entry.options,
                    CONF_ENERGY_PEAK_BUFFER_TARGET: int(value),
                },
            )
        except Exception:  # noqa: BLE001 — best-effort persist
            _LOGGER.debug(
                "PeakBufferTarget options-writeback failed", exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info("Peak buffer target set to %d%%", int(value))


class ArbitrageChargeLeadTimeNumber(NumberEntity):
    """Configurable arbitrage charge lead time on Energy Coordinator device.

    v4.5.0 D2. Minutes before the next high-rate transition that the
    charge window opens. Default 360 (6 h) biases earlier-start so
    same-day target windows benefit from intraday Solcast updates
    accumulated since sunrise.

    Render mode is BOX (not slider — user has slider fatigue; minute-
    precision values are easier to type than drag on a 0–720 track).
    Hard minimum 120 min — full charge from reserve_soc=10% to
    peak_buffer_target=80% ≈ 84 min at 20 kW × 0.9 RTE; 120 gives ~36 min
    margin against Enphase stalls / breaker hiccups. Hard maximum 720 min.

    Part 2 (post-v4.7.26): entry.options is the SOLE source of truth (no
    RestoreEntity). Setter calls `energy.set_arbitrage_charge_lead_time`
    BEFORE async_update_entry. Restart re-seeds via `__init__` config read.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-cog"
    _attr_native_step = 15
    _attr_native_unit_of_measurement = "min"
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry,
    ) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        from .domain_coordinators.energy_const import (
            CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
            DEFAULT_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
            MIN_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
            MAX_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
        )
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_energy_arbitrage_charge_lead_time_min"
        self._attr_name = "Arbitrage Charge Lead Time"
        self._attr_native_min_value = MIN_ARBITRAGE_CHARGE_LEAD_TIME_MIN
        self._attr_native_max_value = MAX_ARBITRAGE_CHARGE_LEAD_TIME_MIN
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        config = {**entry.data, **entry.options}
        seed = int(config.get(
            CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
            DEFAULT_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
        ))
        # Defensive clamp at seed time — should never fire if frontend
        # respects native_min/max, but coord setter does it as backstop.
        self._value = max(
            MIN_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
            min(MAX_ARBITRAGE_CHARGE_LEAD_TIME_MIN, seed),
        )

    def _get_energy(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return self._get_energy() is not None

    def _push_to_coordinator(self) -> bool:
        energy = self._get_energy()
        if energy is None:
            return False
        energy.set_arbitrage_charge_lead_time(self._value)
        return True

    async def async_added_to_hass(self) -> None:
        """Push seeded value to EC; deferred-retry on cross-entry race."""
        await super().async_added_to_hass()

        if not self._push_to_coordinator():
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            from .domain_coordinators.signals import SIGNAL_ENERGY_ENTITIES_UPDATE
            unsub_holder: list = []

            @callback
            def _on_energy_tick(*_args, **_kwargs):
                if self._push_to_coordinator() and unsub_holder:
                    unsub_holder[0]()
                    _LOGGER.debug(
                        "Arbitrage charge lead time pushed to EC after deferred ready"
                    )

            unsub_holder.append(
                async_dispatcher_connect(
                    self.hass, SIGNAL_ENERGY_ENTITIES_UPDATE, _on_energy_tick,
                )
            )
            self.async_on_remove(unsub_holder[0])

    async def async_set_native_value(self, value: float) -> None:
        self._value = int(value)
        # Live-attr push (setter clamps + logs).
        self._push_to_coordinator()
        try:
            from .domain_coordinators.energy_const import (
                CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
            )
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **self._entry.options,
                    CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN: int(value),
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "ArbitrageChargeLeadTime options-writeback failed",
                exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info("Arbitrage charge lead time set to %d min", int(value))


class EVBatteryDrainSOCNumber(NumberEntity):
    """Configurable EV battery-drain pause SOC threshold on EC device (v4.3.3).

    Exposes the previously config-flow-only `energy_ev_battery_drain_soc` value
    as a runtime-adjustable slider. When EV charging is in progress AND the
    house battery is discharging > 100W AND SOC < this threshold, the EVSE is
    paused (see `EVChargerController.determine_battery_drain_actions`).

    Part 2 (post-v4.7.26): entry.options is the SOLE source of truth (no
    RestoreEntity). Setter calls `energy.set_ev_battery_drain_soc(value)`
    BEFORE async_update_entry. Restart re-seeds via `__init__` config read.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:car-battery"
    _attr_native_step = 5
    _attr_native_min_value = 5
    _attr_native_max_value = 95
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, default: int,
    ) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_energy_ev_battery_drain_soc"
        # v4.7.6.1 D2: friendly-name update — frames as the deep floor in the
        # Pause/Resume/Floor trio. unique_id pinned for entity_id stability.
        self._attr_name = "EV Drain-Protection SOC Floor"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        from .domain_coordinators.energy_const import (
            CONF_ENERGY_EV_BATTERY_DRAIN_SOC,
        )
        config = {**entry.data, **entry.options}
        self._value = int(config.get(CONF_ENERGY_EV_BATTERY_DRAIN_SOC, default))

    def _get_energy(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return self._get_energy() is not None

    def _push_to_coordinator(self) -> bool:
        """Push current slider value into EnergyCoordinator. Returns True
        if EC was reachable and accepted the value, else False."""
        energy = self._get_energy()
        if energy is None:
            return False
        energy.set_ev_battery_drain_soc(self._value)
        return True

    async def async_added_to_hass(self) -> None:
        """Push seeded value to EC; deferred-retry on cross-entry race."""
        await super().async_added_to_hass()

        if not self._push_to_coordinator():
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            from .domain_coordinators.signals import SIGNAL_ENERGY_ENTITIES_UPDATE
            # v4.7.6 fix-up B-M7: double-unsub guard.
            unsub_holder: list = []
            unsubbed = [False]

            def _safe_unsub() -> None:
                if unsubbed[0]:
                    return
                if unsub_holder:
                    unsubbed[0] = True
                    unsub_holder[0]()

            @callback
            def _on_energy_tick(*_args, **_kwargs):
                if self._push_to_coordinator() and unsub_holder and not unsubbed[0]:
                    _safe_unsub()
                    _LOGGER.debug(
                        "EV battery drain SOC slider pushed to EC after deferred ready",
                    )

            unsub_holder.append(
                async_dispatcher_connect(
                    self.hass, SIGNAL_ENERGY_ENTITIES_UPDATE, _on_energy_tick,
                )
            )
            self.async_on_remove(_safe_unsub)

    async def async_set_native_value(self, value: float) -> None:
        self._value = int(value)
        self._push_to_coordinator()
        try:
            from .domain_coordinators.energy_const import (
                CONF_ENERGY_EV_BATTERY_DRAIN_SOC,
            )
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **self._entry.options,
                    CONF_ENERGY_EV_BATTERY_DRAIN_SOC: int(value),
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "EVBatteryDrainSOC options-writeback failed", exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info("EV battery drain SOC threshold set to %d%%", int(value))


class FillPrioritySOCNumber(NumberEntity):
    """Configurable EV fill-priority pause SOC threshold on EC device (v4.7.6 D3.2).

    When the home battery SOC < this AND remaining solar forecast >= the
    excess-solar kWh threshold, URA pauses any EVSE (or L1 plug) that is on
    so the battery fills before the EV draws solar surplus.

    Companion to `excess_solar_soc` (default 95) which is the turn-ON
    threshold; this is the turn-OFF (pause) threshold. The middle band
    (default 80–95) lets EVs charge on the normal TOU schedule without
    solar-aware interference.

    Part 2 (post-v4.7.26): entry.options is the SOLE source of truth (no
    RestoreEntity). Setter calls `energy.set_fill_priority_soc(value)`
    BEFORE async_update_entry.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:battery-arrow-up"
    _attr_native_step = 5
    _attr_native_min_value = 50
    _attr_native_max_value = 95
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, default: int = 80,
    ) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_energy_fill_priority_soc"
        # v4.7.6.1 D2: friendly-name update — frames the lower (pause-until)
        # bound of the asymmetric SOC band. unique_id pinned for stability.
        self._attr_name = "Pause EV Until Battery SOC"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        from .domain_coordinators.energy_const import (
            CONF_ENERGY_FILL_PRIORITY_SOC,
        )
        config = {**entry.data, **entry.options}
        self._value = int(config.get(CONF_ENERGY_FILL_PRIORITY_SOC, default))

    def _get_energy(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return self._get_energy() is not None

    def _push_to_coordinator(self) -> bool:
        energy = self._get_energy()
        if energy is None:
            return False
        energy.set_fill_priority_soc(self._value)
        return True

    async def async_added_to_hass(self) -> None:
        """Push seeded value to EC; deferred-retry on cross-entry race."""
        await super().async_added_to_hass()
        if not self._push_to_coordinator():
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            from .domain_coordinators.signals import SIGNAL_ENERGY_ENTITIES_UPDATE
            unsub_holder: list = []
            unsubbed = [False]

            def _safe_unsub() -> None:
                if unsubbed[0]:
                    return
                if unsub_holder:
                    unsubbed[0] = True
                    unsub_holder[0]()

            @callback
            def _on_energy_tick(*_a, **_kw):
                if self._push_to_coordinator() and unsub_holder and not unsubbed[0]:
                    _safe_unsub()

            unsub_holder.append(
                async_dispatcher_connect(
                    self.hass, SIGNAL_ENERGY_ENTITIES_UPDATE, _on_energy_tick,
                )
            )
            self.async_on_remove(_safe_unsub)

    async def async_set_native_value(self, value: float) -> None:
        self._value = int(value)
        self._push_to_coordinator()
        try:
            from .domain_coordinators.energy_const import (
                CONF_ENERGY_FILL_PRIORITY_SOC,
            )
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **self._entry.options,
                    CONF_ENERGY_FILL_PRIORITY_SOC: int(value),
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "FillPrioritySOC options-writeback failed", exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info("Fill priority SOC threshold set to %d%%", int(value))


class ExcessSolarSOCNumber(NumberEntity):
    """Configurable excess-solar EV turn-ON SOC threshold on EC device (v4.7.6.1 D1).

    When the home battery SOC >= this AND solar surplus is available, URA
    turns EVSEs/L1 plugs ON even during off-peak pause so the surplus is
    consumed rather than exported. Companion to FillPrioritySOCNumber
    (default 80) — together the pair forms an asymmetric dead band: pause
    EV until SOC reaches 80, resume EV when SOC reaches 95.

    Part 2 (post-v4.7.26): entry.options is the SOLE source of truth (no
    RestoreEntity). Setter calls `energy.set_excess_solar_soc(value)` BEFORE
    async_update_entry. The natural ordering invariant
    `fill_priority_soc < excess_solar_soc` (pause-until below, resume-at
    above) is NOT enforced today in either entity-setter or config_flow;
    this retrofit preserves that posture pending an operator-decision
    cycle (see Part 2 planning doc / D7 backlog).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:battery-arrow-down"
    _attr_native_step = 1
    _attr_native_min_value = 80
    _attr_native_max_value = 100
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, default: int = 95,
    ) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_energy_excess_solar_soc"
        # v4.7.6.1 D2: friendly-name framed as the resume (upper) bound of
        # the asymmetric SOC dead band.
        self._attr_name = "Resume EV at Battery SOC"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        from .domain_coordinators.energy_const import (
            CONF_ENERGY_EXCESS_SOLAR_SOC,
        )
        config = {**entry.data, **entry.options}
        self._value = int(config.get(CONF_ENERGY_EXCESS_SOLAR_SOC, default))

    def _get_energy(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return self._get_energy() is not None

    def _push_to_coordinator(self) -> bool:
        energy = self._get_energy()
        if energy is None:
            return False
        energy.set_excess_solar_soc(self._value)
        return True

    async def async_added_to_hass(self) -> None:
        """Push seeded value to EC; deferred-retry on cross-entry race."""
        await super().async_added_to_hass()
        if not self._push_to_coordinator():
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            from .domain_coordinators.signals import SIGNAL_ENERGY_ENTITIES_UPDATE
            unsub_holder: list = []
            unsubbed = [False]

            def _safe_unsub() -> None:
                if unsubbed[0]:
                    return
                if unsub_holder:
                    unsubbed[0] = True
                    unsub_holder[0]()

            @callback
            def _on_energy_tick(*_a, **_kw):
                if self._push_to_coordinator() and unsub_holder and not unsubbed[0]:
                    _safe_unsub()

            unsub_holder.append(
                async_dispatcher_connect(
                    self.hass, SIGNAL_ENERGY_ENTITIES_UPDATE, _on_energy_tick,
                )
            )
            self.async_on_remove(_safe_unsub)

    async def async_set_native_value(self, value: float) -> None:
        self._value = int(value)
        self._push_to_coordinator()
        try:
            from .domain_coordinators.energy_const import (
                CONF_ENERGY_EXCESS_SOLAR_SOC,
            )
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **self._entry.options,
                    CONF_ENERGY_EXCESS_SOLAR_SOC: int(value),
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "ExcessSolarSOC options-writeback failed", exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info("EV excess-solar SOC threshold set to %d%%", int(value))


# ===========================================================================
# v4.6.2 D3 — Bayesian cell staleness window (Coordinator Manager device)
# ===========================================================================


class BayesianCellStalenessNumber(NumberEntity):
    """Days of inactivity after which a Bayesian cell is considered stale.

    v4.6.2 D3: PersonLikelyNextRoomSensor checks this before the frequency
    learner fallback. If the cell has had no person_visits observations within
    this many days AND geofence says away, the sensor returns "away_typical"
    instead of "unknown". Covers school/work absences, seasonal transitions,
    vacations.

    Default 14 — two weeks captures most school/work-week patterns without
    being so long it suppresses the detector during genuine routine changes.
    Range 7-90 covers one-week to three-month transitions.

    Part 2 (post-v4.7.26): entry.options is the SOLE source of truth (no
    RestoreEntity). The PersonLikelyNextRoomSensor consumer reads this
    value via entity-state lookup; the option write keeps that aligned
    via the listener's reload-suppression apply path.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"
    _attr_native_min_value = 7
    _attr_native_max_value = 90
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        from homeassistant.helpers.device_registry import DeviceInfo
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_bayesian_cell_staleness_days"
        self._attr_name = "Bayesian Cell Staleness Days"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )
        config = {**entry.data, **entry.options}
        self._value = int(config.get(CONF_BAYESIAN_CELL_STALENESS_DAYS, 14))

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Persist new staleness window via entry.options."""
        self._value = int(value)
        try:
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **self._entry.options,
                    CONF_BAYESIAN_CELL_STALENESS_DAYS: int(value),
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "BayesianCellStaleness options-writeback failed", exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info("Bayesian cell staleness window set to %d days", int(value))


# ===========================================================================
# v4.6.2 D6 — Routine notification + algorithm tunable Number entities
# ===========================================================================
# Four Number entities on the Coordinator Manager device.
#
# Part 2 (post-v4.7.26): entry.options is the SOLE source of truth (no
# RestoreEntity). Consumers (NotificationManager, RegimeDetector) read
# these values via entity-state lookup AND from `cm_opts.get(CONF_…)`
# fallbacks (notification_manager.py:2358-2379, regime_detector.py:122-127),
# so the setter's option write is sufficient — no live-attr push is needed.
# The CM reload-suppression apply path marks Routine CONFs as "applied"
# (analogous to DPM dwell) so the snapshot advances without a full reload.
#
# Two advanced window tunables are entity_registry_enabled_default=False so
# they don't clutter the device page but are accessible when needed.


class _RoutineNumberBase(NumberEntity):
    """Shared base for D6 routine Number entities.

    Subclasses declare class-level _attr_* values and provide:
      _conf_key   — key in entry.options / const.py CONF_*
      _default    — fallback if no entry option and no restored state
      _log_label  — human-readable name for _LOGGER.info

    Part 2 doctrine: entry.options is the SOLE source of truth (no
    RestoreEntity). The setter persists via async_update_entry; the CM
    reload-suppression apply path advances the snapshot for these keys
    without triggering a full reload.
    """

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = True  # may be overridden in subclass

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self.hass = hass
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )
        merged = {**entry.data, **entry.options}
        self._value: int = int(merged.get(self._conf_key, self._default))

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Persist new value via entry.options (options = sole source of truth)."""
        self._value = int(value)
        try:
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **self._entry.options,
                    self._conf_key: int(value),
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Routine Number options-writeback failed (%s)", self._conf_key,
                exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info("%s set to %d", self._log_label, int(value))


class RoutineEventCooldownDaysNumber(_RoutineNumberBase):
    """Per-cell cooldown before re-notifying in event mode (days).

    Default 30. Range 1-365. Prevents alert fatigue for slowly-changing cells.
    Read by NotificationManager at dispatch time.
    """

    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 1
    _attr_native_max_value = 365
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _conf_key = "routine_event_cooldown_days"
    _default = 30
    _log_label = "Routine event cooldown days"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._conf_key = "routine_event_cooldown_days"
        self._default = 30
        self._log_label = "Routine event cooldown days"
        super().__init__(hass, entry)
        from .const import DOMAIN
        self._attr_unique_id = f"{DOMAIN}_routine_event_cooldown_days"
        self._attr_name = "Routine Event Cooldown Days"


class RoutineEventMinSeverityNumber(_RoutineNumberBase):
    """Minimum severity floor for event-mode notifications.

    v4.6.6: Maps to AnomalySeverity IntEnum (now 5 buckets):
      0=INFO, 1=WARNING (default), 2=ADVISORY, 3=ALERT, 4=CRITICAL.
    Events with severity < floor are silently dropped even in event mode.

    v4.6.6 review B-B1: max_value was 2 pre-v4.6.6. After the IntEnum
    expanded from 3 to 5 buckets, CRITICAL moved from 2 → 4. A user who
    previously set the floor to 2 ("CRITICAL only") would silently begin
    receiving ADVISORY+ALERT+CRITICAL events post-deploy. Bumped max to 4
    so CRITICAL-only is reachable; v4.6.6 also auto-migrates any stored
    value of 2 to 4 to preserve original user intent (see _migrate_seed
    below).
    """

    _attr_icon = "mdi:alert-circle-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 4
    _attr_native_step = 1
    _attr_native_unit_of_measurement = None
    _conf_key = "routine_event_min_severity"
    _default = 1
    _log_label = "Routine event min severity"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._conf_key = "routine_event_min_severity"
        self._default = 1
        self._log_label = "Routine event min severity"
        # v4.6.6 B-B1: one-shot seed migration. If the entry options have a
        # stored value of 2 (was "CRITICAL only" pre-v4.6.6), promote it to 4
        # (new CRITICAL) so the user gets the volume they originally chose.
        # Stored 0 and 1 still mean INFO and WARNING; stored 3 or 4 are new
        # values that can only come from a post-v4.6.6 user action.
        try:
            stored = entry.options.get("routine_event_min_severity")
            if stored == 2:
                hass.config_entries.async_update_entry(
                    entry,
                    options={**entry.options, "routine_event_min_severity": 4},
                )
        except Exception:
            # Non-fatal — fall back to defaults if anything in the options
            # surface is misshapen. RestoreEntity will load the new value
            # next cycle.
            pass
        super().__init__(hass, entry)
        from .const import DOMAIN
        self._attr_unique_id = f"{DOMAIN}_routine_event_min_severity"
        self._attr_name = "Routine Event Min Severity"


class RoutineRegimeBaselineWindowNumber(_RoutineNumberBase):
    """Baseline observation window for JS-divergence algorithm (days).

    Default 56 (8 weeks). Range 28-180. Advanced tunable; disabled by default
    so it does not appear on the CM device page unless explicitly enabled.
    Consumed by RegimeDetector._window_days() at run_nightly time.
    """

    _attr_icon = "mdi:calendar-range"
    _attr_native_min_value = 28
    _attr_native_max_value = 180
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_entity_registry_enabled_default = False  # advanced tunable
    _conf_key = "routine_regime_baseline_window_days"
    _default = 56
    _log_label = "Regime baseline window days"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._conf_key = "routine_regime_baseline_window_days"
        self._default = 56
        self._log_label = "Regime baseline window days"
        super().__init__(hass, entry)
        from .const import DOMAIN
        self._attr_unique_id = f"{DOMAIN}_routine_regime_baseline_window_days"
        self._attr_name = "Regime Baseline Window Days"


class RoutineRegimeRecentWindowNumber(_RoutineNumberBase):
    """Recent observation window for JS-divergence algorithm (days).

    Default 14 (2 weeks). Range 3-56. Advanced tunable; disabled by default.
    Consumed by RegimeDetector._window_days() at run_nightly time.
    """

    _attr_icon = "mdi:calendar-today"
    _attr_native_min_value = 3
    _attr_native_max_value = 56
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_entity_registry_enabled_default = False  # advanced tunable
    _conf_key = "routine_regime_recent_window_days"
    _default = 14
    _log_label = "Regime recent window days"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._conf_key = "routine_regime_recent_window_days"
        self._default = 14
        self._log_label = "Regime recent window days"
        super().__init__(hass, entry)
        from .const import DOMAIN
        self._attr_unique_id = f"{DOMAIN}_routine_regime_recent_window_days"
        self._attr_name = "Regime Recent Window Days"


# ===========================================================================
# v4.5.10 — HVAC Coordinator runtime tunables (Number entities)
# ===========================================================================
# Factory that produces 7 Number-entity classes for HVAC tunables. Each
# instance reads/writes a runtime field on a sub-controller (cover_controller,
# predictor, fan_controller). Mirror pattern: form value is install-time
# seed; this Number entity is the runtime source of truth (per
# `feedback_ura_mirror_pattern.md`).


def _hvac_tunable_number_factory(
    *,
    suffix: str,
    name: str,
    icon: str,
    sub_controller_attr: str,   # "_cover_controller" | "_predictor" | "_fan_controller"
    runtime_field: str,          # e.g. "_occupied_close_delta"
    conf_key: str,               # CONF_* string for form-seed lookup
    default: float,
    min_value: float,
    max_value: float,
    step: float,
    unit: str | None,
    integer: bool = False,
):
    """Build a Number entity class for an HVAC sub-controller tunable.

    The class:
      - Lives on the URA: HVAC Coordinator device
      - Reads value from CM entry on first install AND on restart
      - entry.options is the SOLE source of truth (no RestoreEntity)
      - Pushes value into sub-controller's runtime field on every change
        BEFORE async_update_entry, then writes state
      - Pushes again on coord-ready signal (handles cross-coordinator init race)

    Part 2 (post-v4.7.26): RestoreEntity is RETIRED for these 14 factory
    outputs. Each CONF_HVAC_* key is in the CM `OPTIONS_RELOAD_SUPPRESS_KEYS`
    allowlist; the listener's `_apply_in_place` dispatches each key to the
    matching `setattr(sub_controller, runtime_field, cast(value))`, so
    form-path edits land identically to entity-path edits with no full
    CM reload. The 5 watch-list keys (ac_nudge_duration, ac_nudge_eval_delay,
    ac_detection_time_gate, ac_hard_reset_min_interval, cover_override_duration)
    are consumed inline at their call sites (no stashed timedelta cache),
    so a simple setattr is sufficient — verified against hvac_override.py
    + hvac_covers.py.
    """
    cast = int if integer else float

    class _HVACTunableNumber(NumberEntity):
        _attr_has_entity_name = True
        _attr_icon = icon
        _attr_native_min_value = min_value
        _attr_native_max_value = max_value
        _attr_native_step = step
        _attr_native_unit_of_measurement = unit
        _attr_mode = NumberMode.SLIDER
        _attr_entity_category = EntityCategory.CONFIG

        def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
            from homeassistant.helpers.device_registry import DeviceInfo
            from .const import VERSION
            self.hass = hass
            self._entry = entry
            self._attr_unique_id = f"{DOMAIN}_hvac_{suffix}"
            self._attr_name = name
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, "hvac_coordinator")},
                name="URA: HVAC Coordinator",
                manufacturer="Universal Room Automation",
                model="HVAC Coordinator",
                sw_version=VERSION,
                via_device=(DOMAIN, "coordinator_manager"),
            )
            # Read form-seed from the CM entry's options
            cm_entry = self._find_cm_entry()
            cm_config = (
                {**cm_entry.data, **cm_entry.options}
                if cm_entry is not None else {}
            )
            self._value = cast(cm_config.get(conf_key, default))

        def _find_cm_entry(self):
            from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_COORDINATOR_MANAGER
            for e in self.hass.config_entries.async_entries(DOMAIN):
                if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    return e
            return None

        def _get_sub_controller(self):
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return None
            hvac = manager.coordinators.get("hvac")
            return getattr(hvac, sub_controller_attr, None) if hvac else None

        @property
        def native_value(self) -> float:
            return self._value

        @property
        def available(self) -> bool:
            return self._get_sub_controller() is not None

        def _push_to_controller(self) -> bool:
            sub = self._get_sub_controller()
            if sub is None:
                return False
            try:
                setattr(sub, runtime_field, cast(self._value))
                return True
            except Exception as e:
                _LOGGER.error(
                    "HVAC tunable %s push failed: %s", suffix, e,
                )
                return False

        async def async_added_to_hass(self) -> None:
            """Push seeded value into sub-controller; deferred-retry on race.

            No RestoreEntity. Constructor seeded `self._value` from the CM
            entry's `{**entry.data, **entry.options}` — that's the SOLE
            source of truth. If the sub-controller isn't ready at add time
            (cross-coordinator init race), retry on SIGNAL_HVAC_ENTITIES_UPDATE.
            """
            await super().async_added_to_hass()
            if not self._push_to_controller():
                from homeassistant.helpers.dispatcher import async_dispatcher_connect
                from .domain_coordinators.hvac_const import (
                    SIGNAL_HVAC_ENTITIES_UPDATE,
                )
                # Mirrors the EC sibling pattern (v4.7.6 fix-up B-M7):
                # one-shot unsub guard so the dispatcher-side and
                # async_on_remove-side don't both fire unsub on the same
                # callable (second call raises in HA).
                unsub_holder: list = []
                unsubbed = [False]

                def _safe_unsub() -> None:
                    if unsubbed[0]:
                        return
                    if unsub_holder:
                        unsubbed[0] = True
                        unsub_holder[0]()

                @callback
                def _on_hvac_tick(*_a, **_kw):
                    if self._push_to_controller() and unsub_holder and not unsubbed[0]:
                        _safe_unsub()

                unsub_holder.append(
                    async_dispatcher_connect(
                        self.hass,
                        SIGNAL_HVAC_ENTITIES_UPDATE,
                        _on_hvac_tick,
                    )
                )
                self.async_on_remove(_safe_unsub)

        async def async_set_native_value(self, value: float) -> None:
            self._value = cast(value)
            # Live-attr push BEFORE async_update_entry so the next HVAC
            # decision cycle sees the new value immediately.
            self._push_to_controller()
            try:
                # Persist into CM entry.options — sole source of truth.
                cm_entry = self._find_cm_entry()
                if cm_entry is not None:
                    self.hass.config_entries.async_update_entry(
                        cm_entry,
                        options={
                            **cm_entry.options,
                            conf_key: cast(value),
                        },
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "HVAC tunable %s options-writeback failed", suffix,
                    exc_info=True,
                )
            self.async_write_ha_state()
            _LOGGER.info("HVAC tunable %s set to %s", suffix, self._value)

    _HVACTunableNumber.__name__ = f"HVAC{suffix.title().replace('_', '')}Number"
    _HVACTunableNumber.__qualname__ = _HVACTunableNumber.__name__
    return _HVACTunableNumber


# Build the 7 v4.5.10 Number entity classes via the factory
def _build_hvac_v4510_numbers():
    """Lazy-build to avoid import at module load (CONFs may not be available)."""
    from .domain_coordinators.hvac_const import (
        CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA,
        DEFAULT_HVAC_OCCUPIED_COVER_CLOSE_DELTA,
        CONF_HVAC_COVER_CLOSE_TEMP,
        DEFAULT_HVAC_COVER_CLOSE_TEMP,
        CONF_HVAC_COVER_OPEN_TEMP,
        DEFAULT_HVAC_COVER_OPEN_TEMP,
        CONF_HVAC_COVER_OVERRIDE_HOURS,
        DEFAULT_HVAC_COVER_OVERRIDE_HOURS,
        CONF_HVAC_SOLAR_BANK_FLOOR,
        DEFAULT_HVAC_SOLAR_BANK_FLOOR,
        CONF_HVAC_FAN_ACTIVATION_DELTA,
        DEFAULT_FAN_ACTIVATION_DELTA,
        CONF_HVAC_FAN_HYSTERESIS,
        DEFAULT_FAN_HYSTERESIS,
    )
    return [
        _hvac_tunable_number_factory(
            suffix="cover_close_threshold",
            name="60 · Cover Close Threshold",
            icon="mdi:thermometer-chevron-up",
            sub_controller_attr="_cover_controller",
            runtime_field="_occupied_close_delta",
            conf_key=CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA,
            default=DEFAULT_HVAC_OCCUPIED_COVER_CLOSE_DELTA,
            min_value=0.5, max_value=5.0, step=0.5, unit="°F",
        ),
        _hvac_tunable_number_factory(
            suffix="cover_close_temp",
            name="61 · Cover Close Temp",
            icon="mdi:weather-sunny",
            sub_controller_attr="_cover_controller",
            runtime_field="_cover_close_temp",
            conf_key=CONF_HVAC_COVER_CLOSE_TEMP,
            default=DEFAULT_HVAC_COVER_CLOSE_TEMP,
            min_value=75, max_value=95, step=1, unit="°F",
        ),
        _hvac_tunable_number_factory(
            suffix="cover_open_temp",
            name="62 · Cover Open Temp",
            icon="mdi:weather-partly-cloudy",
            sub_controller_attr="_cover_controller",
            runtime_field="_cover_open_temp",
            conf_key=CONF_HVAC_COVER_OPEN_TEMP,
            default=DEFAULT_HVAC_COVER_OPEN_TEMP,
            min_value=70, max_value=90, step=1, unit="°F",
        ),
        _hvac_tunable_number_factory(
            suffix="cover_override_duration",
            name="63 · Cover Override Duration",
            icon="mdi:timer-sand",
            sub_controller_attr="_cover_controller",
            runtime_field="_cover_override_hours",
            conf_key=CONF_HVAC_COVER_OVERRIDE_HOURS,
            default=DEFAULT_HVAC_COVER_OVERRIDE_HOURS,
            min_value=0.5, max_value=24, step=0.5, unit="hr",
        ),
        _hvac_tunable_number_factory(
            suffix="solar_bank_floor",
            name="64 · Solar Banking Cool Floor",
            icon="mdi:thermometer-low",
            sub_controller_attr="_predictor",
            runtime_field="_solar_bank_floor",
            conf_key=CONF_HVAC_SOLAR_BANK_FLOOR,
            default=DEFAULT_HVAC_SOLAR_BANK_FLOOR,
            min_value=65, max_value=80, step=1, unit="°F",
        ),
        _hvac_tunable_number_factory(
            suffix="fan_on_threshold",
            name="65 · Fan On Threshold",
            icon="mdi:fan-plus",
            sub_controller_attr="_fan_controller",
            runtime_field="_activation_delta",
            conf_key=CONF_HVAC_FAN_ACTIVATION_DELTA,
            default=DEFAULT_FAN_ACTIVATION_DELTA,
            min_value=0.5, max_value=5, step=0.5, unit="°F",
        ),
        _hvac_tunable_number_factory(
            suffix="fan_off_hysteresis",
            name="66 · Fan Off Hysteresis",
            icon="mdi:fan-minus",
            sub_controller_attr="_fan_controller",
            runtime_field="_deactivation_delta",
            conf_key=CONF_HVAC_FAN_HYSTERESIS,
            default=DEFAULT_FAN_HYSTERESIS,
            min_value=0.5, max_value=5, step=0.5, unit="°F",
        ),
    ]


# ===========================================================================
# v4.5.11 — AC Energy-Aware Ramp-Down (house-wide tunables)
# ===========================================================================
# 6 house-wide Number entities push to OverrideArrester instance attrs.
# (kwh_rate_threshold is per-zone — see _build_hvac_v4511_zone_numbers below.)


def _build_hvac_v4511_numbers():
    """Lazy-build to avoid CONF import-at-module-load."""
    from .domain_coordinators.hvac_const import (
        CONF_HVAC_AC_NUDGE_SIZE,
        DEFAULT_HVAC_AC_NUDGE_SIZE,
        CONF_HVAC_AC_NUDGE_DURATION,
        DEFAULT_HVAC_AC_NUDGE_DURATION,
        CONF_HVAC_AC_NUDGE_EVAL_DELAY,
        DEFAULT_HVAC_AC_NUDGE_EVAL_DELAY,
        CONF_HVAC_AC_SUSTAINED_SAMPLES,
        DEFAULT_HVAC_AC_SUSTAINED_SAMPLES,
        CONF_HVAC_AC_DETECTION_TIME_GATE,
        DEFAULT_HVAC_AC_DETECTION_TIME_GATE,
        CONF_HVAC_AC_HARD_RESET_DAILY_LIMIT,
        DEFAULT_HVAC_AC_HARD_RESET_DAILY_LIMIT,
        CONF_HVAC_AC_HARD_RESET_MIN_INTERVAL,
        DEFAULT_HVAC_AC_HARD_RESET_MIN_INTERVAL,
    )
    return [
        _hvac_tunable_number_factory(
            suffix="ac_nudge_size",
            name="70 · AC Nudge Size",
            icon="mdi:thermometer-plus",
            sub_controller_attr="_override_arrester",
            runtime_field="_nudge_size_f",
            conf_key=CONF_HVAC_AC_NUDGE_SIZE,
            default=DEFAULT_HVAC_AC_NUDGE_SIZE,
            min_value=0.5, max_value=3.0, step=0.5, unit="°F",
        ),
        _hvac_tunable_number_factory(
            suffix="ac_nudge_duration",
            name="71 · AC Nudge Duration",
            icon="mdi:timer-sand",
            sub_controller_attr="_override_arrester",
            runtime_field="_nudge_duration_min",
            conf_key=CONF_HVAC_AC_NUDGE_DURATION,
            default=DEFAULT_HVAC_AC_NUDGE_DURATION,
            min_value=1, max_value=15, step=1, unit="min",
            integer=True,
        ),
        # v4.7.17.1: post-restore evaluation window. Range 60-1200 s
        # (1-20 min). Mid-flight change does NOT reschedule the active
        # eval timer; next nudge picks up the new value.
        _hvac_tunable_number_factory(
            suffix="ac_nudge_eval_delay",
            name="76 · AC Nudge Eval Delay",
            icon="mdi:timer-cog-outline",
            sub_controller_attr="_override_arrester",
            runtime_field="_nudge_eval_delay_s",
            conf_key=CONF_HVAC_AC_NUDGE_EVAL_DELAY,
            default=DEFAULT_HVAC_AC_NUDGE_EVAL_DELAY,
            min_value=60, max_value=1200, step=30, unit="s",
            integer=True,
        ),
        _hvac_tunable_number_factory(
            suffix="ac_sustained_samples",
            name="72 · AC Sustained Samples",
            icon="mdi:counter",
            sub_controller_attr="_override_arrester",
            runtime_field="_sustained_samples",
            conf_key=CONF_HVAC_AC_SUSTAINED_SAMPLES,
            default=DEFAULT_HVAC_AC_SUSTAINED_SAMPLES,
            min_value=2, max_value=10, step=1, unit=None,
            integer=True,
        ),
        _hvac_tunable_number_factory(
            suffix="ac_detection_time_gate",
            name="73 · AC Detection Time Gate",
            icon="mdi:timer-outline",
            sub_controller_attr="_override_arrester",
            runtime_field="_detection_time_gate_min",
            conf_key=CONF_HVAC_AC_DETECTION_TIME_GATE,
            default=DEFAULT_HVAC_AC_DETECTION_TIME_GATE,
            min_value=5, max_value=30, step=1, unit="min",
            integer=True,
        ),
        _hvac_tunable_number_factory(
            suffix="ac_hard_reset_daily_limit",
            name="74 · AC Hard Reset Daily Limit",
            icon="mdi:calendar-alert",
            sub_controller_attr="_override_arrester",
            runtime_field="_hard_reset_daily_limit",
            conf_key=CONF_HVAC_AC_HARD_RESET_DAILY_LIMIT,
            default=DEFAULT_HVAC_AC_HARD_RESET_DAILY_LIMIT,
            min_value=0, max_value=5, step=1, unit=None,
            integer=True,
        ),
        _hvac_tunable_number_factory(
            suffix="ac_hard_reset_min_interval",
            name="75 · AC Hard Reset Min Interval",
            icon="mdi:timer-lock-outline",
            sub_controller_attr="_override_arrester",
            runtime_field="_hard_reset_min_interval_min",
            conf_key=CONF_HVAC_AC_HARD_RESET_MIN_INTERVAL,
            default=DEFAULT_HVAC_AC_HARD_RESET_MIN_INTERVAL,
            min_value=30, max_value=360, step=30, unit="min",
            integer=True,
        ),
    ]


# ===========================================================================
# v4.5.11 — Per-zone AC kWh Rate Threshold (one Number per AC zone)
# ===========================================================================
# Threshold scales with AC tonnage (~25-30% of rated power floor). 3-ton
# units default to 0.8 kW; 4-ton typically wants 1.0 kW. Per-zone sliders
# allow independent tuning without forcing all units to the same value.


def _hvac_zone_kwh_threshold_factory(
    *, zone_id: str, zone_name: str, climate_entity: str,
):
    """Build a Number class for one AC zone's kWh-rate threshold.

    Pushes to ZoneState.kwh_rate_threshold (not a sub-controller attr).
    Lookup chain: hass.data[DOMAIN]["coordinator_manager"] -> hvac
    coordinator -> _zone_manager -> zones[zone_id].
    """
    from .domain_coordinators.hvac_const import DEFAULT_HVAC_AC_KWH_RATE_THRESHOLD

    class _HVACZoneKwhThresholdNumber(NumberEntity, RestoreEntity):
        _attr_has_entity_name = True
        _attr_icon = "mdi:flash-alert"
        _attr_native_min_value = 0.3
        _attr_native_max_value = 3.0
        _attr_native_step = 0.1
        _attr_native_unit_of_measurement = "kW"
        _attr_mode = NumberMode.SLIDER
        _attr_entity_category = EntityCategory.CONFIG

        def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
            from homeassistant.helpers.device_registry import DeviceInfo
            from .const import VERSION
            self.hass = hass
            self._entry = entry
            # Store both the local zone_id (for unique_id stability across
            # restarts) AND the climate_entity (for runtime lookup against
            # ZoneManager.zones — see _get_zone). ZoneManager derives its
            # zone_ids via _zone_id_from_thermostat which extracts "zone_N"
            # from the climate entity name; the local derivation here used
            # the full sanitized name. Looking up by climate_entity bridges
            # the two without forcing convergence on a single scheme.
            self._zone_id = zone_id
            self._climate_entity = climate_entity
            self._attr_unique_id = f"{DOMAIN}_hvac_ac_kwh_threshold_{zone_id}"
            self._attr_name = f"90 · AC kWh Rate Threshold ({zone_name})"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, "hvac_coordinator")},
                name="URA: HVAC Coordinator",
                manufacturer="Universal Room Automation",
                model="HVAC Coordinator",
                sw_version=VERSION,
                via_device=(DOMAIN, "coordinator_manager"),
            )
            self._value: float = float(DEFAULT_HVAC_AC_KWH_RATE_THRESHOLD)

        def _get_zone(self):
            """Look up ZoneState by climate_entity (stable across naming
            conventions). Critical fix from slice-1 review: previously
            this lookup used self._zone_id which is derived locally as
            `thermostat.replace("climate.", "").replace(".", "_")` —
            different from ZoneManager._zone_id_from_thermostat which
            extracts `zone_N` from the climate entity name. Matching by
            climate_entity (unique + stable) avoids the convention drift.
            """
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return None
            hvac = manager.coordinators.get("hvac") if hasattr(manager, "coordinators") else None
            if hvac is None:
                return None
            zm = getattr(hvac, "_zone_manager", None)
            if zm is None:
                return None
            for zone in zm.zones.values():
                if zone.climate_entity == self._climate_entity:
                    return zone
            return None

        @property
        def native_value(self) -> float:
            return self._value

        @property
        def available(self) -> bool:
            return self._get_zone() is not None

        def _push_to_zone(self) -> bool:
            zone = self._get_zone()
            if zone is None:
                return False
            try:
                zone.kwh_rate_threshold = float(self._value)
                return True
            except Exception as e:
                _LOGGER.error(
                    "Per-zone kWh threshold push failed for %s: %s",
                    self._zone_id, e,
                )
                return False

        async def async_added_to_hass(self) -> None:
            await super().async_added_to_hass()
            last_state = await self.async_get_last_state()
            if (
                last_state is not None
                and last_state.state not in ("unknown", "unavailable")
            ):
                try:
                    self._value = float(last_state.state)
                except (ValueError, TypeError):
                    pass
            if not self._push_to_zone():
                from homeassistant.helpers.dispatcher import async_dispatcher_connect
                from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
                unsub_holder: list = []

                @callback
                def _on_hvac_tick(*_a, **_kw):
                    if self._push_to_zone() and unsub_holder:
                        unsub_holder[0]()

                unsub_holder.append(
                    async_dispatcher_connect(
                        self.hass,
                        SIGNAL_HVAC_ENTITIES_UPDATE,
                        _on_hvac_tick,
                    )
                )
                self.async_on_remove(unsub_holder[0])

        async def async_set_native_value(self, value: float) -> None:
            self._value = float(value)
            self._push_to_zone()
            self.async_write_ha_state()
            _LOGGER.info(
                "AC kWh threshold for zone %s set to %.2f kW",
                self._zone_id, self._value,
            )

    _HVACZoneKwhThresholdNumber.__name__ = (
        f"HVACZoneKwhThreshold{zone_id.title().replace('_', '')}Number"
    )
    _HVACZoneKwhThresholdNumber.__qualname__ = _HVACZoneKwhThresholdNumber.__name__
    return _HVACZoneKwhThresholdNumber


def _discover_ac_zones(hass: HomeAssistant) -> list[dict]:
    """Enumerate canonical HVAC zones for per-zone threshold slider setup.

    v4.5.13.1: thin wrapper around `iter_canonical_hvac_zones`. See
    button.py:_discover_ac_zones for the same rationale — sharing the
    helper eliminates cross-platform zone_id drift (Bug Class #36).
    """
    from .domain_coordinators.hvac_zones import iter_canonical_hvac_zones
    return iter_canonical_hvac_zones(hass)


# ============================================================================
# v4.7.1 Cycle B: Dynamic Preset runtime tunable numbers
# ============================================================================


class DynamicPresetDwellMinutesNumber(NumberEntity):
    """Runtime-tunable dwell window for Dynamic Preset bucket transitions.

    Default 60, range 15-240, step 5, unit "min".
    Entity: number.ura_energy_coordinator_dynamic_preset_dwell_minutes
    Device: URA: HVAC Coordinator (migrated from EC in v4.7.3 D4)

    entry.options is the SOLE source of truth (no RestoreEntity). Writes
    go through `async_update_entry`; restart re-seeds via the constructor's
    `{**entry.data, **entry.options}` read. DPM evaluate-and-emit reads
    `entry.options` fresh every tick via `_get_cm_options()` (energy.py:2850),
    so no explicit live-attr push is needed.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-outline"
    _attr_native_step = 5.0
    _attr_native_unit_of_measurement = "min"
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_energy_dynamic_preset_dwell_minutes"
        self._attr_name = "03 · Dynamic Preset Dwell (minutes)"
        self._attr_native_min_value = 15.0
        self._attr_native_max_value = 240.0
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        from .domain_coordinators.energy_const import (
            CONF_DYNAMIC_PRESET_DWELL_MINUTES, DEFAULT_DYNAMIC_PRESET_DWELL_MINUTES
        )
        config = {**entry.data, **entry.options}
        self._value = float(config.get(CONF_DYNAMIC_PRESET_DWELL_MINUTES, DEFAULT_DYNAMIC_PRESET_DWELL_MINUTES))

    def _get_energy(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    @property
    def available(self) -> bool:
        return self._get_energy() is not None

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = float(value)
        # Push to CM entry.options so the Energy coordinator's bound method
        # _get_cm_options() picks up the new value on the next
        # evaluate_and_emit call (no explicit live-attr poke needed —
        # see class docstring).
        try:
            from .domain_coordinators.energy_const import CONF_DYNAMIC_PRESET_DWELL_MINUTES
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={**self._entry.options, CONF_DYNAMIC_PRESET_DWELL_MINUTES: float(value)},
            )
        except Exception:
            pass
        self.async_write_ha_state()
        _LOGGER.info("Dynamic preset dwell set to %.0f minutes", value)


class DynamicPresetHysteresisFNumber(NumberEntity):
    """Runtime-tunable hysteresis buffer for Dynamic Preset bucket boundaries.

    Default 2.0, range 0.5-5.0, step 0.5, unit "°F".
    Entity: number.ura_energy_coordinator_dynamic_preset_hysteresis_f
    Device: URA: HVAC Coordinator (migrated from EC in v4.7.3 D4)

    v4.7.1 Cycle B: B4.
    v4.7.3 D4: DeviceInfo.identifiers changed to hvac_coordinator; unique_id
    preserved for entity_id stability.

    Part 2 (post-v4.7.26): entry.options is the SOLE source of truth (no
    RestoreEntity). DPM evaluate-and-emit reads `entry.options` fresh on
    every tick via `_get_cm_options()` (energy.py:2850), so no explicit
    live-attr push is needed. The setter persists via async_update_entry;
    the CM reload-suppression apply path marks the key as applied
    (analogous to DPM dwell).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermometer-alert"
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "°F"
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_energy_dynamic_preset_hysteresis_f"
        self._attr_name = "04 · Dynamic Preset Hysteresis (°F)"
        self._attr_native_min_value = 0.5
        self._attr_native_max_value = 5.0
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        from .domain_coordinators.energy_const import (
            CONF_DYNAMIC_PRESET_HYSTERESIS_F, DEFAULT_DYNAMIC_PRESET_HYSTERESIS_F
        )
        config = {**entry.data, **entry.options}
        self._value = float(config.get(CONF_DYNAMIC_PRESET_HYSTERESIS_F, DEFAULT_DYNAMIC_PRESET_HYSTERESIS_F))

    def _get_energy(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    @property
    def available(self) -> bool:
        return self._get_energy() is not None

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = float(value)
        # v4.7.1 fix-up HIGH A2/B2/C2: Push to CM entry.options so the
        # bound method _get_cm_options() picks up the new value on the next
        # evaluate_and_emit call (Bug Class #32 fix).
        try:
            from .domain_coordinators.energy_const import CONF_DYNAMIC_PRESET_HYSTERESIS_F
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={**self._entry.options, CONF_DYNAMIC_PRESET_HYSTERESIS_F: float(value)},
            )
        except Exception:
            pass
        self.async_write_ha_state()
        _LOGGER.info("Dynamic preset hysteresis set to %.1f°F", value)



# =============================================================================
# v4.7.8 D2 — Egress Window HVAC Pause threshold + resume-delay Numbers
# -----------------------------------------------------------------------------
# Two sliders on URA: HVAC Coordinator device.
#  - HVACEgressPauseThresholdNumber: minutes a window must be open before pause
#    fires. Default 3, range 1-15.
#  - HVACEgressResumeDelayNumber: minutes all egress windows must be closed
#    before resume fires. Default 1, range 1-10.
# Both mirror FillPrioritySOCNumber line-for-line including the v4.7.6 fix-up
# B-M7 _safe_unsub double-unsub guard (Bug Classes #5/#19/#38/#42/#45).
# =============================================================================


class HVACEgressPauseThresholdNumber(NumberEntity):
    """Minutes window open before egress pause fires (v4.7.8 D2).

    Part 2 (post-v4.7.26): entry.options is the SOLE source of truth (no
    RestoreEntity). Setter calls `hvac.egress_manager.set_threshold_min`
    (which clamps internally) BEFORE async_update_entry. No cross-field
    constraint with the resume-delay sibling is enforced today in entity
    or config_flow paths; this retrofit preserves that posture (Part 2
    O4 — pending operator decision).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-sand"
    _attr_native_step = 1
    _attr_native_min_value = 1
    _attr_native_max_value = 15
    _attr_native_unit_of_measurement = "min"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, default: int = 3,
    ) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_egress_threshold_min"
        self._attr_name = "Egress Pause Threshold"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        config = {**entry.data, **entry.options}
        self._value = int(config.get("hvac_egress_threshold_min", default))

    def _get_hvac(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("hvac") if manager else None

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return self._get_hvac() is not None

    def _push_to_coordinator(self) -> bool:
        hvac = self._get_hvac()
        if hvac is None:
            return False
        try:
            hvac.egress_manager.set_threshold_min(self._value)
        except Exception:
            return False
        return True

    async def async_added_to_hass(self) -> None:
        """Push seeded value; deferred-retry on SIGNAL_HVAC_COORDINATOR_READY."""
        await super().async_added_to_hass()
        if not self._push_to_coordinator():
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            from .domain_coordinators.signals import SIGNAL_HVAC_COORDINATOR_READY
            unsub_holder: list = []
            unsubbed = [False]

            def _safe_unsub() -> None:
                if unsubbed[0]:
                    return
                if unsub_holder:
                    unsubbed[0] = True
                    unsub_holder[0]()

            @callback
            def _on_hvac_ready(*_a, **_kw):
                if self._push_to_coordinator() and unsub_holder and not unsubbed[0]:
                    _safe_unsub()

            unsub_holder.append(
                async_dispatcher_connect(
                    self.hass, SIGNAL_HVAC_COORDINATOR_READY, _on_hvac_ready,
                )
            )
            self.async_on_remove(_safe_unsub)

    async def async_set_native_value(self, value: float) -> None:
        self._value = int(value)
        self._push_to_coordinator()
        try:
            from .domain_coordinators.hvac_const import (
                CONF_HVAC_EGRESS_THRESHOLD_MIN,
            )
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **self._entry.options,
                    CONF_HVAC_EGRESS_THRESHOLD_MIN: int(value),
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "HVACEgressPauseThreshold options-writeback failed",
                exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info("Egress pause threshold set to %d min", int(value))


class HVACEgressResumeDelayNumber(NumberEntity):
    """Minutes all egress windows must be closed before resume (v4.7.8 D2).

    Part 2 (post-v4.7.26): entry.options is the SOLE source of truth (no
    RestoreEntity). See HVACEgressPauseThresholdNumber for the cross-field
    constraint posture (none enforced today).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-outline"
    _attr_native_step = 1
    _attr_native_min_value = 1
    _attr_native_max_value = 10
    _attr_native_unit_of_measurement = "min"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, default: int = 1,
    ) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_egress_resume_delay_min"
        self._attr_name = "Egress Resume Delay"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        config = {**entry.data, **entry.options}
        self._value = int(config.get("hvac_egress_resume_delay_min", default))

    def _get_hvac(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("hvac") if manager else None

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return self._get_hvac() is not None

    def _push_to_coordinator(self) -> bool:
        hvac = self._get_hvac()
        if hvac is None:
            return False
        try:
            hvac.egress_manager.set_resume_delay_min(self._value)
        except Exception:
            return False
        return True

    async def async_added_to_hass(self) -> None:
        """Push seeded value; deferred-retry on SIGNAL_HVAC_COORDINATOR_READY."""
        await super().async_added_to_hass()
        if not self._push_to_coordinator():
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            from .domain_coordinators.signals import SIGNAL_HVAC_COORDINATOR_READY
            unsub_holder: list = []
            unsubbed = [False]

            def _safe_unsub() -> None:
                if unsubbed[0]:
                    return
                if unsub_holder:
                    unsubbed[0] = True
                    unsub_holder[0]()

            @callback
            def _on_hvac_ready(*_a, **_kw):
                if self._push_to_coordinator() and unsub_holder and not unsubbed[0]:
                    _safe_unsub()

            unsub_holder.append(
                async_dispatcher_connect(
                    self.hass, SIGNAL_HVAC_COORDINATOR_READY, _on_hvac_ready,
                )
            )
            self.async_on_remove(_safe_unsub)

    async def async_set_native_value(self, value: float) -> None:
        self._value = int(value)
        self._push_to_coordinator()
        try:
            from .domain_coordinators.hvac_const import (
                CONF_HVAC_EGRESS_RESUME_DELAY_MIN,
            )
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **self._entry.options,
                    CONF_HVAC_EGRESS_RESUME_DELAY_MIN: int(value),
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "HVACEgressResumeDelay options-writeback failed",
                exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info("Egress resume delay set to %d min", int(value))


class FanInterferenceHoldNumber(NumberEntity):
    """Layer-1 fan-interference hold duration in seconds (D1).

    Lives on the Presence Coordinator device. Operator-tunable slider
    that pushes into ``PresenceCoordinator._fan_interference_hold_s``
    via ``set_fan_interference_hold_s``. Default 300s mirrors the
    camera-tier timeout (``_CAMERA_OCCUPANCY_TIMEOUT_SECONDS`` at
    presence.py:71). Range 60-1800.

    Part 2 (post-v4.7.26): entry.options is the SOLE source of truth (no
    RestoreEntity). The setter pushes to the presence coordinator via
    `set_fan_interference_hold_s` and mirrors the value into the CM
    entry's options (existing B-H1 mirror behavior is preserved).
    Consumed as a simple int seconds value at use sites — no derived
    cache to invalidate.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-outline"
    _attr_native_step = 30
    _attr_native_min_value = 60
    _attr_native_max_value = 1800
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import (
            CONF_FAN_INTERFERENCE_HOLD_S,
            DEFAULT_FAN_INTERFERENCE_HOLD_S,
            VERSION,
        )
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_fan_interference_hold_s"
        self._attr_name = "Fan Interference Hold"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        config = {**entry.data, **entry.options}
        self._value = int(
            config.get(
                CONF_FAN_INTERFERENCE_HOLD_S,
                DEFAULT_FAN_INTERFERENCE_HOLD_S,
            )
        )

    def _get_presence(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("presence") if manager else None

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return True

    def _push_to_coordinator(self) -> bool:
        presence = self._get_presence()
        if presence is None:
            return False
        try:
            presence.set_fan_interference_hold_s(self._value)
        except Exception:
            return False
        return True

    async def async_added_to_hass(self) -> None:
        """Best-effort push of the seeded value (no ready signal exists).

        No RestoreEntity. Constructor seeded `self._value` from
        `{**entry.data, **entry.options}` — sole source of truth. If the
        presence coordinator is not yet registered (early-boot), the
        presence coordinator's __init__ also seeds the default, so the
        gate always has a sensible value to use in the meantime.
        """
        await super().async_added_to_hass()
        self._push_to_coordinator()

    async def async_set_native_value(self, value: float) -> None:
        self._value = int(value)
        self._push_to_coordinator()
        # B-H1 fix-up: mirror the operator value into the
        # Coordinator-Manager entry.options so the next coordinator
        # __init__ (post-restart, post-restore-from-backup, or any
        # no-last-state path) re-seeds the gate at the operator's
        # value rather than the hard-coded 300s default. URA-mirror
        # pattern — see feedback_ura_mirror_pattern.md.
        try:
            from .const import (
                CONF_ENTRY_TYPE,
                CONF_FAN_INTERFERENCE_HOLD_S,
                ENTRY_TYPE_COORDINATOR_MANAGER,
            )
            for ce in self.hass.config_entries.async_entries(DOMAIN):
                if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    self.hass.config_entries.async_update_entry(
                        ce,
                        options={
                            **ce.options,
                            CONF_FAN_INTERFERENCE_HOLD_S: int(value),
                        },
                    )
                    break
        except Exception:  # noqa: BLE001 — best-effort mirror
            _LOGGER.debug(
                "Fan-interference hold: entry.options mirror failed (non-fatal)",
                exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info("Fan-interference hold set to %d seconds", int(value))


# ============================================================================
# v5.7.1 — Energy Saver Pre-Cool Offset (EC device)
# ----------------------------------------------------------------------------
# Operator-configurable °F offset applied at _execute_zone_pre_cool. Default
# -2.0 (per operator 2026-06-28: "make the space not too cold suddenly").
# Sign convention: negative = cooler. The 72°F floor (SOLAR_BANK_FLOOR) still
# clamps the resulting setpoint (I3) — an absurd configured value cannot
# breach the floor. Pattern mirrors OffPeakDrainNumber (entry.options is the
# sole source of truth; live-attr push to EC before async_update_entry).
# ============================================================================


class EnergyPreCoolOffsetNumber(NumberEntity):
    """Configurable Energy Saver Pre-Cool offset on the Energy Coordinator device."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:snowflake-thermometer"
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .domain_coordinators.hvac_const import (
            CONF_ENERGY_PRECOOL_OFFSET,
            DEFAULT_ENERGY_PRECOOL_OFFSET,
            ENERGY_PRECOOL_OFFSET_MIN,
            ENERGY_PRECOOL_OFFSET_MAX,
            ENERGY_PRECOOL_OFFSET_STEP,
        )
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_energy_energy_precool_offset"
        self._attr_name = "Energy Saver Pre-Cool Offset"
        self._attr_native_min_value = ENERGY_PRECOOL_OFFSET_MIN
        self._attr_native_max_value = ENERGY_PRECOOL_OFFSET_MAX
        self._attr_native_step = ENERGY_PRECOOL_OFFSET_STEP
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        config = {**entry.data, **entry.options}
        raw = config.get(
            CONF_ENERGY_PRECOOL_OFFSET, DEFAULT_ENERGY_PRECOOL_OFFSET,
        )
        try:
            self._value = float(raw)
        except (TypeError, ValueError):
            self._value = float(DEFAULT_ENERGY_PRECOOL_OFFSET)
        # Clamp to declared range so a corrupt option doesn't poison HA.
        self._value = max(
            ENERGY_PRECOOL_OFFSET_MIN,
            min(ENERGY_PRECOOL_OFFSET_MAX, self._value),
        )

    def _get_energy(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return self._get_energy() is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        energy = self._get_energy()
        if energy is not None:
            try:
                energy.energy_precool_offset = self._value
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Energy Saver Pre-Cool Offset: seed-push deferred",
                )

    async def async_set_native_value(self, value: float) -> None:
        from .domain_coordinators.hvac_const import (
            CONF_ENERGY_PRECOOL_OFFSET,
            ENERGY_PRECOOL_OFFSET_MIN,
            ENERGY_PRECOOL_OFFSET_MAX,
        )
        clamped = max(
            ENERGY_PRECOOL_OFFSET_MIN,
            min(ENERGY_PRECOOL_OFFSET_MAX, float(value)),
        )
        self._value = clamped
        energy = self._get_energy()
        if energy is not None:
            energy.energy_precool_offset = clamped
        try:
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **self._entry.options,
                    CONF_ENERGY_PRECOOL_OFFSET: clamped,
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Energy Saver Pre-Cool Offset: options-writeback failed",
                exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info(
            "Energy Saver Pre-Cool Offset set to %.2f°F", clamped,
        )


