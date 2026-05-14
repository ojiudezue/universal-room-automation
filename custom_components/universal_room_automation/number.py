"""Number platform for Universal Room Automation."""
#
# Universal Room Automation vv4.6.2.3
# Build: 2026-01-02
# File: number.py
#

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
            # v4.6.2 D3: Bayesian cell staleness window (default 14 days)
            BayesianCellStalenessNumber(hass, entry),
            # v4.6.2 D6: routine notification tunables
            RoutineEventCooldownDaysNumber(hass, entry),
            RoutineEventMinSeverityNumber(hass, entry),
            RoutineRegimeBaselineWindowNumber(hass, entry),
            RoutineRegimeRecentWindowNumber(hass, entry),
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
    _attr_mode = NumberMode.SLIDER
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
        self._attr_name = "48 · Zone Entry Dwell"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        config = {**entry.data, **entry.options}
        self._value = config.get(CONF_HVAC_ZONE_ENTRY_DWELL, DEFAULT_ZONE_ENTRY_DWELL_MINUTES)

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
        """Set new dwell value — takes effect on next HVAC decision cycle."""
        self._value = int(value)
        hvac = self._get_hvac()
        if hvac is not None:
            hvac._zone_entry_dwell = int(value)
        self.async_write_ha_state()
        _LOGGER.info("Zone entry dwell set to %d minutes", int(value))


class OffPeakDrainNumber(NumberEntity, RestoreEntity):
    """Configurable off-peak battery drain target on Energy Coordinator device.

    SOC% to drain to overnight based on tomorrow's solar forecast quality.
    v4.2.10: Exposes config-flow-only values as runtime-adjustable numbers.
    RestoreEntity persists slider changes across restarts.
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
        """Restore last slider value on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable"):
            try:
                restored = int(float(last_state.state))
                self._value = restored
                energy = self._get_energy()
                if energy is not None:
                    energy.set_offpeak_drain(self._quality, restored)
            except (ValueError, TypeError):
                pass

    async def async_set_native_value(self, value: float) -> None:
        self._value = int(value)
        energy = self._get_energy()
        if energy is not None:
            energy.set_offpeak_drain(self._quality, int(value))
        self.async_write_ha_state()
        _LOGGER.info("Off-peak drain %s set to %d%%", self._quality, int(value))


class PeakBufferTargetNumber(NumberEntity, RestoreEntity):
    """Configurable peak buffer target on Energy Coordinator device.

    v4.5.0 D2: replaces the v4.3.0 ArbitrageSOCNumber(role="target") slider.
    Renamed for clarity — this is the SOC the strategy holds in reserve
    for the upcoming high-rate window. The v4.3.0 ArbitrageSOCNumber
    (role="trigger") is removed entirely; v4.5.0's arbitrage gate is
    forecast-class only (no SOC trigger).

    Render mode stays SLIDER (consistent with existing % SOC sliders).
    Mirrors OffPeakDrainNumber's RestoreEntity-based pattern post-v4.3.2:
    - entry.options = initial seed only, read once in __init__
    - RestoreEntity = canonical runtime store
    - async_set_native_value updates self._value + coord setter +
      async_write_ha_state(). NO async_update_entry writeback.
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
        """Restore last slider value; push into coordinator with deferred retry.

        Mirrors `OffPeakDrainNumber` post-v4.3.2: always trust RestoreEntity,
        never re-read entry.options here (snap-back regression guard from
        v4.3.0 H6 fixed in v4.3.2). v4.3.0 C3 retry-on-signal handles the
        cross-entry init race when EC isn't yet registered.
        """
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if (
            last_state is not None
            and last_state.state not in ("unknown", "unavailable")
        ):
            try:
                self._value = int(float(last_state.state))
            except (ValueError, TypeError):
                pass

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
        self._push_to_coordinator()
        self.async_write_ha_state()
        _LOGGER.info("Peak buffer target set to %d%%", int(value))


class ArbitrageChargeLeadTimeNumber(NumberEntity, RestoreEntity):
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

    Mirrors `OffPeakDrainNumber` lifecycle exactly (RestoreEntity-based;
    NO async_update_entry writeback — see memory feedback_ura_mirror_pattern.md
    for the v4.3.2 fix shape this follows).
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
        """Restore + push (mirror OffPeakDrainNumber pattern)."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if (
            last_state is not None
            and last_state.state not in ("unknown", "unavailable")
        ):
            try:
                self._value = int(float(last_state.state))
            except (ValueError, TypeError):
                pass

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
        self._push_to_coordinator()
        self.async_write_ha_state()
        _LOGGER.info("Arbitrage charge lead time set to %d min", int(value))


class EVBatteryDrainSOCNumber(NumberEntity, RestoreEntity):
    """Configurable EV battery-drain pause SOC threshold on EC device (v4.3.3).

    Exposes the previously config-flow-only `energy_ev_battery_drain_soc` value
    as a runtime-adjustable slider. When EV charging is in progress AND the
    house battery is discharging > 100W AND SOC < this threshold, the EVSE is
    paused (see `EVChargerController.determine_battery_drain_actions`).

    Slider is the canonical runtime store (mirrors v4.3.2 fix to
    ArbitrageSOCNumber). Config-flow value is the initial seed for first-ever
    startup only; subsequent slider drags persist via RestoreEntity across
    restarts and entry reloads.
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
        self._attr_name = "EV Battery Drain SOC"
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
        """Restore last slider value; push into coordinator (with deferred
        retry to handle the cross-entry init race per v4.3.0 C3 + v4.3.2 fix).
        Always trusts RestoreEntity (post-v4.3.2 pattern — no config_explicit
        branch, which caused the snap-back regression).
        """
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if (
            last_state is not None
            and last_state.state not in ("unknown", "unavailable")
        ):
            try:
                self._value = int(float(last_state.state))
            except (ValueError, TypeError):
                pass

        if not self._push_to_coordinator():
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            from .domain_coordinators.signals import SIGNAL_ENERGY_ENTITIES_UPDATE
            unsub_holder: list = []

            @callback
            def _on_energy_tick(*_args, **_kwargs):
                if self._push_to_coordinator() and unsub_holder:
                    unsub_holder[0]()
                    _LOGGER.debug(
                        "EV battery drain SOC slider pushed to EC after deferred ready",
                    )

            unsub_holder.append(
                async_dispatcher_connect(
                    self.hass, SIGNAL_ENERGY_ENTITIES_UPDATE, _on_energy_tick,
                )
            )
            self.async_on_remove(unsub_holder[0])

    async def async_set_native_value(self, value: float) -> None:
        self._value = int(value)
        self._push_to_coordinator()
        self.async_write_ha_state()
        _LOGGER.info("EV battery drain SOC threshold set to %d%%", int(value))


# ===========================================================================
# v4.6.2 D3 — Bayesian cell staleness window (Coordinator Manager device)
# ===========================================================================


class BayesianCellStalenessNumber(NumberEntity, RestoreEntity):
    """Days of inactivity after which a Bayesian cell is considered stale.

    v4.6.2 D3: PersonLikelyNextRoomSensor checks this before the frequency
    learner fallback. If the cell has had no person_visits observations within
    this many days AND geofence says away, the sensor returns "away_typical"
    instead of "unknown". Covers school/work absences, seasonal transitions,
    vacations.

    Default 14 — two weeks captures most school/work-week patterns without
    being so long it suppresses the detector during genuine routine changes.
    Range 7-90 covers one-week to three-month transitions.

    RestoreEntity is the canonical runtime store per feedback_ura_mirror_pattern.
    entry.options value is the install-time seed only.
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
        self._value = int(config.get("bayesian_cell_staleness_days", 14))

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return True

    async def async_added_to_hass(self) -> None:
        """Restore last value on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable"):
            try:
                self._value = int(float(last_state.state))
            except (ValueError, TypeError):
                pass

    async def async_set_native_value(self, value: float) -> None:
        """Persist new staleness window."""
        self._value = int(value)
        self.async_write_ha_state()
        _LOGGER.info("Bayesian cell staleness window set to %d days", int(value))


# ===========================================================================
# v4.6.2 D6 — Routine notification + algorithm tunable Number entities
# ===========================================================================
# Four Number entities on the Coordinator Manager device. All use
# RestoreEntity as the runtime store (feedback_ura_mirror_pattern: entry.options
# is the install-time seed, not the live source of truth).
# Two advanced window tunables are entity_registry_enabled_default=False so
# they don't clutter the device page but are accessible when needed.


class _RoutineNumberBase(NumberEntity, RestoreEntity):
    """Shared base for D6 routine Number entities.

    Subclasses declare class-level _attr_* values and provide:
      _conf_key   — key in entry.options / const.py CONF_*
      _default    — fallback if no entry option and no restored state
      _log_label  — human-readable name for _LOGGER.info
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

    async def async_added_to_hass(self) -> None:
        """Restore last value on startup (RestoreEntity mirror pattern)."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if (
            last_state is not None
            and last_state.state not in ("unknown", "unavailable")
        ):
            try:
                self._value = int(float(last_state.state))
            except (ValueError, TypeError):
                pass

    async def async_set_native_value(self, value: float) -> None:
        self._value = int(value)
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

    0=INFO, 1=WARNING (default), 2=CRITICAL. Maps to AnomalySeverity IntEnum.
    Events below the floor are silently dropped even in event mode.
    """

    _attr_icon = "mdi:alert-circle-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 2
    _attr_native_step = 1
    _attr_native_unit_of_measurement = None
    _conf_key = "routine_event_min_severity"
    _default = 1
    _log_label = "Routine event min severity"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._conf_key = "routine_event_min_severity"
        self._default = 1
        self._log_label = "Routine event min severity"
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
      - Reads form-seed value from entry on first install
      - RestoreEntity-backed (slider survives restart)
      - Pushes value into sub-controller's runtime field on every change
      - Pushes again on coord-ready signal (handles cross-coordinator init race)
    """
    cast = int if integer else float

    class _HVACTunableNumber(NumberEntity, RestoreEntity):
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
            await super().async_added_to_hass()
            last_state = await self.async_get_last_state()
            if (
                last_state is not None
                and last_state.state not in ("unknown", "unavailable")
            ):
                try:
                    self._value = cast(float(last_state.state))
                except (ValueError, TypeError):
                    pass
            if not self._push_to_controller():
                # Sub-controller not ready yet — listen for HVAC-ready signal.
                # v4.5.10.1: import from hvac_const (where this signal lives)
                # not signals.py. The original v4.5.10 code raised ImportError
                # because the module-level SIGNAL_HVAC_ENTITIES_UPDATE doesn't
                # exist in signals.py — only HVAC-only signals live in
                # hvac_const. Source-grep tests verified the import statement
                # was present but didn't verify the symbol resolved.
                from homeassistant.helpers.dispatcher import async_dispatcher_connect
                from .domain_coordinators.hvac_const import (
                    SIGNAL_HVAC_ENTITIES_UPDATE,
                )
                unsub_holder: list = []

                @callback
                def _on_hvac_tick(*_a, **_kw):
                    if self._push_to_controller() and unsub_holder:
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
            self._value = cast(value)
            self._push_to_controller()
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
