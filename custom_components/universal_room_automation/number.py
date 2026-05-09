"""Number platform for Universal Room Automation."""
#
# Universal Room Automation vv4.5.7
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
        ]
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
        self._attr_name = "Zone Entry Dwell"
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
