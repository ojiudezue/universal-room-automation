"""Switch platform for Universal Room Automation."""
#
# Universal Room Automation vv4.7.33
# Build: 2026-01-02
# File: switch.py
#

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
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


def _room_switch_entity_id(coordinator: "UniversalRoomCoordinator", suffix: str) -> str:
    """Build entity_id for a room-level switch."""
    slug = coordinator.entry.data.get("room_name", "unknown").lower().replace(" ", "_")
    return f"switch.{slug}_{suffix}"


def _migrate_excess_solar_entity_id(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """v4.7.6 D3.1: Rename the excess-solar switch entity_id (one-shot).

    Before: switch.ura_energy_coordinator_excess_solar_charging
    After:  switch.ura_energy_coordinator_evse_solar_aware_charging

    The unique_id stays "{DOMAIN}_energy_excess_solar" so HACS / history /
    long-term stats are preserved. Only the entity_id changes.

    v4.7.6 fix-up B-H3 / C-M6: idempotency is enforced by the registry
    lookup itself — once renamed, `registry.async_get(legacy_entity_id)`
    returns None and the migration is a no-op. The prior `entry.runtime_data`
    guard was non-functional (URA never initializes runtime_data) and
    risked stomping a stray dict into the typed-data slot if HA later
    starts using it. Removed.

    Bug Class #46-safe: calls entity_registry.async_update_entity(),
    not async_update_entry.
    """
    from homeassistant.helpers import entity_registry as er
    registry = er.async_get(hass)
    legacy_entity_id = "switch.ura_energy_coordinator_excess_solar_charging"
    new_entity_id = "switch.ura_energy_coordinator_evse_solar_aware_charging"
    legacy_unique_id = f"{DOMAIN}_energy_excess_solar"
    entity_entry = registry.async_get(legacy_entity_id)
    if entity_entry is None or entity_entry.unique_id != legacy_unique_id:
        return  # Already migrated, or never existed under the legacy slug.
    # If new entity_id is already taken by something else, skip — never
    # collide. The unique_id pin in the factory still preserves history.
    if registry.async_get(new_entity_id) is not None:
        return
    registry.async_update_entity(
        legacy_entity_id, new_entity_id=new_entity_id,
    )
    _LOGGER.info(
        "v4.7.6 D3.1: renamed %s → %s (unique_id %s preserved)",
        legacy_entity_id, new_entity_id, legacy_unique_id,
    )


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

    if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:
        # v4.7.6 D3.1: one-shot entity_id alias migration (Bug Class #46-safe).
        try:
            _migrate_excess_solar_entity_id(hass, entry)
        except Exception:
            _LOGGER.debug("v4.7.6 alias migration failed (non-fatal)", exc_info=True)
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
            # v4.1.1 B4 L2: Occupancy-weighted prediction toggle
            OccupancyWeightedPredictionSwitch(hass, entry),
            # v4.2.10: EC runtime toggles
            ECGridImportCapSwitch(hass, entry),
            ECLoadSheddingSwitch(hass, entry),
            ECExcessSolarSwitch(hass, entry),
            ECArbitrageSwitch(hass, entry),
            ECEvTouSwitch(hass, entry),
            # v4.7.2 D2: Dynamic Preset master kill switch (migrated to HVAC device)
            HVACDynamicPresetSwitch(hass, entry),
            # v4.7.1 fix-up D3 / v4.7.2 D3: Custom Preset Ranges master toggle (HVAC device)
            HVACGuestModeActuationSwitch(hass, entry),
            # v3.9.0: HVAC transparency switches
            HVACOverrideArresterSwitch(hass, entry),
            HVACACResetSwitch(hass, entry),
            # v4.7.7 A1: AC Nudge decouple — sibling toggle for soft-nudge
            # detection, independent of AC Reset.
            HVACACNudgeSwitch(hass, entry),
            # v4.7.8 D2: Egress Window HVAC Pause master toggle.
            HVACEgressWindowPauseSwitch(hass, entry),
            HVACObservationModeSwitch(hass, entry),
            # Fan-noise Mode-2: master kill switch for room-tier
            # fan-pause + clean recheck. Lives on the Presence
            # Coordinator device. Default OFF — operator pins ON after
            # live validation. Per-room opt-in is on each room entry.
            FanRecheckEnabledSwitch(hass, entry),
            # v4.7.15 D6: Consensus defer gates (HVAC + compliance).
            HVACConsensusDeferGateSwitch(hass, entry),
            ComplianceConsensusDeferGateSwitch(hass, entry),
            # v3.17.0: Zone Intelligence toggle
            HVACZoneIntelligenceSwitch(hass, entry),
            # v3.18.2: Zone Sweep toggle
            HVACZoneSweepSwitch(hass, entry),
            # v3.18.6: Pre-Arrival Conditioning toggle
            HVACPreArrivalSwitch(hass, entry),
            # v4.0.15: Fan Control toggle
            HVACFanControlSwitch(hass, entry),
            # v4.5.10: Solar Cover Management master toggle
            HVACSolarCoverSwitch(hass, entry),
            HVACACRampMasterSwitch(hass, entry),
            # v3.21.1 D1: Observation mode toggles for Safety, Security, Presence
            SafetyObservationModeSwitch(hass, entry),
            SecurityObservationModeSwitch(hass, entry),
            PresenceObservationModeSwitch(hass, entry),
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
        AiAutomationSwitch(coordinator),
        InfrastructureRoomSwitch(coordinator),
        # Fan-noise Mode-2 per-room opt-ins. Both default OFF.
        # RoomFanRecheckEnabledSwitch is the eligibility gate; the L2
        # opt-in is Tier-1-only weak-authorize (ignored in Tier-2 where
        # L2 is an unconditional safety veto).
        RoomFanRecheckEnabledSwitch(coordinator),
        RoomFanRecheckL2AllowedSwitch(coordinator),
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
        if coordinator_id == "hvac":
            self._attr_name = "00 · Enabled"
        else:
            self._attr_name = "Enabled"
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


class EnergyObservationModeSwitch(SwitchEntity, RestoreEntity):
    """Toggle Energy Coordinator observation mode.

    When ON: All sensors compute normally, but no control actions are executed.
    When OFF (default): Normal operation — sensors + actions.

    Entity: switch.ura_energy_observation_mode
    Device: URA: Energy Coordinator

    v3.21.0 D6: Added RestoreEntity to persist observation mode across restarts.
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
        self._deferred_restore = False

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

    async def async_added_to_hass(self) -> None:
        """Restore observation mode state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == "on":
            energy = self._get_energy()
            if energy is not None:
                energy.observation_mode = True
            else:
                # Deferred retry: coordinator may not be initialized yet
                self._deferred_restore = True
                self.async_on_remove(async_call_later(self.hass, 5, self._retry_restore))

    def _retry_restore(self, _now=None) -> None:
        """Retry setting observation mode after coordinator initializes."""
        if not self._deferred_restore:
            return
        energy = self._get_energy()
        if energy is not None:
            energy.observation_mode = True
            self._deferred_restore = False
            _LOGGER.info("Energy observation mode restored (deferred)")
        else:
            _LOGGER.warning("Energy observation mode restore failed — coordinator still unavailable after 5s")

    @property
    def available(self) -> bool:
        """Only available when energy coordinator is active."""
        return self._get_energy() is not None



# =========================================================================
# v4.2.10: Energy Coordinator Runtime Toggles
# =========================================================================
# Pattern: SwitchEntity + RestoreEntity, @callback def _retry_restore (NOT async def)


def _ec_switch_factory(
    attr_name: str, unique_suffix: str, name: str, icon: str, default: bool = False,
    unique_id_override=None,  # Optional[str] — bare for Python 3.9 compat
):
    """Factory for EC toggle switches — avoids 200 lines of boilerplate.

    v4.5.3: lifecycle race fixed. Prior bug (deferred from v4.5.0): the
    factory's `_retry_restore` had no `_deferred_restore` flag and only a
    single 5s retry — if `_get_energy()` returned None at both
    `async_added_to_hass` AND the 5s retry (e.g. CM platform setup still
    in flight), the user's persisted toggle was silently lost. Then the
    EnergyCoordinator constructor's `ec.get(CONF_*_ENABLED, …)` seed
    became the visible state after restart.

    User-visible symptom: a toggle the user had explicitly set OFF would
    appear ON after restart, because the constructor seed (read from
    cm_entry.data/options, which is unchanged when the user toggles via
    the UI) leaked through after the failed restore.

    v4.5.3 fix:
      - `_deferred_restore` flag set when restore is pending.
      - Retry chain: 5s, 30s, 120s with each callback rescheduling the
        next on continued failure.
      - Flag is cleared only on successful setattr; exhausted retries
        log a warning so future investigations have signal.

    The `is_on` default-return race documented in the prior version of
    this docstring is unchanged — it's a separate latent issue and
    out of scope for v4.5.3. If a regression reappears in that shape,
    capture HA debug logs around restart and look at the sequence of
    `is_on` calls, RestoreEntity restore values, and coord-init timing.
    """

    class _ECSwitch(SwitchEntity, RestoreEntity):
        _attr_has_entity_name = True
        _attr_icon = icon
        _attr_entity_category = EntityCategory.CONFIG

        # v4.5.3: retry chain delays for deferred restore (seconds).
        # Covers the worst observed CM/energy-coord-not-yet-registered
        # window without scheduling forever.
        _RETRY_DELAYS_S = (5, 30, 120)

        def __init__(self, hass, entry):
            self.hass = hass
            self._entry = entry
            # v4.7.6 D3.1: unique_id_override pins the unique_id to a legacy
            # slug while exposing a new entity_id / friendly name. Used by
            # the excess-solar → evse-solar-aware rename to preserve HACS
            # entity history. Default behavior (None) is unchanged.
            _suffix = unique_id_override if unique_id_override is not None else unique_suffix
            self._attr_unique_id = f"{DOMAIN}_energy_{_suffix}"
            self._attr_name = name
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, "energy_coordinator")},
                name="URA: Energy Coordinator",
                manufacturer="Universal Room Automation",
                model="Energy Coordinator",
                sw_version=VERSION,
                via_device=(DOMAIN, "coordinator_manager"),
            )
            self._default = default
            # v4.5.3: explicit deferred-restore state so _retry_restore
            # is a no-op once the restore has landed (or after the
            # async_added_to_hass fast-path succeeded).
            self._deferred_restore: bool = False
            self._deferred_value: bool = default
            self._retry_index: int = 0

        def _get_energy(self):
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            return manager.coordinators.get("energy") if manager else None

        @property
        def is_on(self) -> bool:
            energy = self._get_energy()
            if energy is None:
                return self._default
            return getattr(energy, attr_name, self._default)

        async def async_turn_on(self, **kwargs):
            energy = self._get_energy()
            if energy is not None:
                setattr(energy, attr_name, True)
                # v4.5.3: explicit user toggle wins over any pending restore.
                self._deferred_restore = False
                self.async_write_ha_state()

        async def async_turn_off(self, **kwargs):
            energy = self._get_energy()
            if energy is not None:
                setattr(energy, attr_name, False)
                self._deferred_restore = False
                self.async_write_ha_state()

        async def async_added_to_hass(self):
            await super().async_added_to_hass()

            # v4.7.x D2: Subscribe to SIGNAL_ENERGY_COORDINATOR_READY so that
            # deferred restore completes even when EC init takes longer than the
            # v4.5.3 retry budget (e.g. Envoy validation race at startup).
            # Unsub is tracked via async_on_remove — Bug Class #38.
            # The subscription is registered unconditionally so it fires even
            # when restore lands immediately (signal is a no-op then because
            # _deferred_restore is already False).
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            from .domain_coordinators.signals import SIGNAL_ENERGY_COORDINATOR_READY
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    SIGNAL_ENERGY_COORDINATOR_READY,
                    self._handle_ec_ready,
                )
            )

            last_state = await self.async_get_last_state()
            if last_state is None:
                # First-time install (no prior RestoreEntity state):
                # the constructor's `ec.get(...)` seed is the source of
                # truth. Do nothing here.
                return
            target = last_state.state == "on"
            self._deferred_value = target
            energy = self._get_energy()
            if energy is not None:
                setattr(energy, attr_name, target)
                # Restore landed immediately; no retry needed.
                self._deferred_restore = False
                # v4.7.x H1 fix-up: notify EC that this switch completed
                # restore so ECSubSwitchesSyncedSensor can track real sync.
                try:
                    energy.notify_sub_switch_restore_complete()
                except Exception:
                    pass
                self.async_write_ha_state()
                return
            # Coord not registered yet → mark deferred; SIGNAL_ENERGY_COORDINATOR_READY
            # will fire _handle_ec_ready once EC finishes async_setup().
            # The v4.5.3 timer chain is kept as a fast-path for the short window
            # between platform setup and coordinator registration.
            self._deferred_restore = True
            self._retry_index = 0
            self.async_on_remove(
                async_call_later(
                    self.hass, self._RETRY_DELAYS_S[0], self._retry_restore
                )
            )

        @callback
        def _handle_ec_ready(self) -> None:
            """Handle SIGNAL_ENERGY_COORDINATOR_READY — complete deferred restore.

            v4.7.x D2: Called when EC coord finishes async_setup().  If this
            switch still has a pending deferred restore (_deferred_restore is
            True), write the saved value to the coordinator now.  If restore
            already landed via the timer chain, this is a no-op.

            Bug Class #42: uses bound method, NOT a lambda.
            Bug Class #19: no async_create_task — @callback fires synchronously
            on the event loop.
            """
            if not self._deferred_restore:
                return
            energy = self._get_energy()
            if energy is None:
                _LOGGER.warning(
                    "EC switch %s: SIGNAL_ENERGY_COORDINATOR_READY fired but "
                    "coord still not in hass.data — restore deferred",
                    unique_suffix,
                )
                return
            setattr(energy, attr_name, self._deferred_value)
            self._deferred_restore = False
            # v4.7.x H1 fix-up: notify EC that this switch completed deferred
            # restore so ECSubSwitchesSyncedSensor tracks real per-switch sync.
            try:
                energy.notify_sub_switch_restore_complete()
            except Exception:
                pass
            self.async_write_ha_state()
            _LOGGER.info(
                "EC switch %s: deferred restore completed via SIGNAL_ENERGY_COORDINATOR_READY"
                " (value=%s)",
                unique_suffix,
                self._deferred_value,
            )

        @callback
        def _retry_restore(self, _now=None):
            if not self._deferred_restore:
                return
            energy = self._get_energy()
            if energy is not None:
                setattr(energy, attr_name, self._deferred_value)
                self._deferred_restore = False
                # v4.7.x H1 fix-up: notify EC that this switch completed
                # restore (timer path) so ECSubSwitchesSyncedSensor tracks real sync.
                try:
                    energy.notify_sub_switch_restore_complete()
                except Exception:
                    pass
                self.async_write_ha_state()
                return
            # Coord still not ready — schedule the next retry if any
            # remain in the chain.  SIGNAL_ENERGY_COORDINATOR_READY is the
            # unbounded fallback; the timer chain is a fast-path only.
            self._retry_index += 1
            if self._retry_index < len(self._RETRY_DELAYS_S):
                self.async_on_remove(
                    async_call_later(
                        self.hass,
                        self._RETRY_DELAYS_S[self._retry_index],
                        self._retry_restore,
                    )
                )
            else:
                _LOGGER.warning(
                    "EC switch %s: timer retry chain exhausted — waiting for "
                    "SIGNAL_ENERGY_COORDINATOR_READY to complete restore",
                    unique_suffix,
                )
                # _deferred_restore stays True so _handle_ec_ready still fires
                # when the signal eventually arrives.

        @property
        def available(self) -> bool:
            return self._get_energy() is not None

    _ECSwitch.__name__ = f"EC{unique_suffix.title().replace('_', '')}Switch"
    _ECSwitch.__qualname__ = _ECSwitch.__name__
    return _ECSwitch


ECGridImportCapSwitch = _ec_switch_factory(
    "_grid_import_cap_enabled", "grid_import_cap",
    "Grid Import Cap", "mdi:transmission-tower-import", default=False,
)
ECLoadSheddingSwitch = _ec_switch_factory(
    "_load_shedding_enabled", "load_shedding",
    "Load Shedding", "mdi:flash-alert", default=False,
)
# v4.7.6 D3.1: Renamed Excess Solar Charging → EVSE Solar-Aware Charging.
# unique_id is pinned to the legacy slug ("excess_solar") via unique_id_override
# so HACS/entity history is preserved. Friendly name and entity_id slug update;
# entity_id alias migration runs at platform setup (see
# `_migrate_excess_solar_entity_id` below — Bug Class #46-safe).
ECEVSESolarAwareSwitch = _ec_switch_factory(
    "_excess_solar_enabled", "evse_solar_aware",
    "EVSE Solar-Aware Charging", "mdi:solar-power", default=False,
    unique_id_override="excess_solar",
)
# Back-compat alias: keep old name resolvable for imports that may still
# reference it. Removed in a future release once dashboards are updated.
ECExcessSolarSwitch = ECEVSESolarAwareSwitch
ECArbitrageSwitch = _ec_switch_factory(
    "arbitrage_enabled", "arbitrage",
    "Grid Arbitrage", "mdi:battery-charging-wireless", default=False,
)

# v4.7.2.1: Replaced bespoke OccupancyWeightedPredictionSwitch class with a
# factory call. The prior bespoke class had no SIGNAL_ENERGY_COORDINATOR_READY
# subscription and only a single 5s retry — silently lost user's persisted ON
# state when EC was not yet registered at async_added_to_hass time (startup
# race Bug Class #5).
# unique_id suffix "occupancy_weighted_prediction" matches the prior bespoke
# unique_id ({DOMAIN}_energy_occupancy_weighted_prediction) for entity_id stability.
OccupancyWeightedPredictionSwitch = _ec_switch_factory(
    "occupancy_weighted",             # attr_name on EnergyCoordinator
    "occupancy_weighted_prediction",  # unique_id suffix → {DOMAIN}_energy_occupancy_weighted_prediction
    "Occupancy Weighted Prediction",  # display name (unchanged)
    "mdi:account-clock",              # icon (unchanged)
    default=False,                    # default (unchanged)
)

# v4.7.6 D6.2: Renamed friendly name "EV TOU Management" → "EVSE TOU Management"
# to reflect that L1 plugs (peer "small EVSE" devices) are now gated by this
# toggle too. entity_id and unique_id are unchanged for HACS/dashboard continuity.
_ECEvTouSwitchBase = _ec_switch_factory(
    "ev_tou_enabled", "ev_tou_management",
    "EVSE TOU Management", "mdi:ev-station", default=True,
)


class ECEvTouSwitch(_ECEvTouSwitchBase):
    """EV TOU Management switch with force-charge override attribute.

    v4.7.x D3: extends the factory-generated base to expose
    `override_active_until_iso` so the PWA and HA UI can show when a
    force-charge admin window is active.

    v4.7.x B2 fix-up: restores the force-charge override window across
    entry reloads.  The `override_active_until_iso` attribute is persisted
    in HA's state store (RestoreEntity).  On restore, if the ISO expiry is
    still in the future, the window is re-applied to the EV controller.
    An active window is NOT silently dropped on reload — the user's admin
    intent is honoured for the remainder of the original 30-min window.

    v4.7.6 fix-up C-H3: exposes `_attr_translation_key = "ev_tou_management"`
    so HA can render the per-entity description shipped in strings.json /
    translations/en.json (see `entity.switch.ev_tou_management.description`).
    The translation block also supplies `name` to preserve the existing
    "EVSE TOU Management" label — translation_key takes precedence over
    `_attr_name` when both are set.
    """

    _attr_translation_key = "ev_tou_management"

    async def async_added_to_hass(self) -> None:
        """Restore on/off state AND force-charge override across reloads.

        The base class handles on/off RestoreEntity restore and the
        SIGNAL_ENERGY_COORDINATOR_READY subscription.  This override adds
        the override-expiry restore on top.

        B2 fix-up: reads override_active_until_iso from last state attrs.
        Idempotent: expired ISO → no restore; future ISO → window re-applied.
        """
        await super().async_added_to_hass()
        # Read the persisted override expiry from the last saved state attrs.
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        override_iso = last_state.attributes.get("override_active_until_iso")
        if not override_iso:
            return
        try:
            from datetime import datetime, timezone
            from homeassistant.util import dt as dt_util
            persisted_until = datetime.fromisoformat(override_iso)
            # Ensure UTC-aware (attributes store as ISO string with offset)
            if persisted_until.tzinfo is None:
                persisted_until = persisted_until.replace(tzinfo=timezone.utc)
            now_utc = dt_util.utcnow()
            if persisted_until <= now_utc:
                # Override already expired — nothing to restore
                _LOGGER.debug(
                    "ECEvTouSwitch: persisted override expired (was %s), skipping restore",
                    override_iso,
                )
                return
            # Override is still active — re-apply it to the EV controller
            energy = self._get_energy()
            if energy is not None:
                energy.ev_controller.set_force_charge_override(persisted_until)
                _LOGGER.info(
                    "ECEvTouSwitch: force-charge override restored from state (expires %s)",
                    override_iso,
                )
            else:
                # EC not yet registered — the deferred-restore path in the
                # base class will fire _handle_ec_ready later, but that only
                # restores the on/off state.  Store the pending override here
                # so _handle_ec_ready can apply it when EC becomes available.
                self._pending_override_until = persisted_until
        except Exception:
            _LOGGER.debug(
                "ECEvTouSwitch: failed to parse persisted override ISO %r (non-fatal)",
                override_iso,
                exc_info=True,
            )

    @callback
    def _handle_ec_ready(self) -> None:
        """Extend base restore with pending force-charge override re-application.

        If a force-charge window was persisted and EC was not available at
        async_added_to_hass time, apply it now.
        """
        super()._handle_ec_ready()
        pending = getattr(self, "_pending_override_until", None)
        if pending is None:
            return
        try:
            from homeassistant.util import dt as dt_util
            now_utc = dt_util.utcnow()
            if pending <= now_utc:
                _LOGGER.debug(
                    "ECEvTouSwitch: pending override expired before EC registered; skipping"
                )
                self._pending_override_until = None
                return
            energy = self._get_energy()
            if energy is not None:
                energy.ev_controller.set_force_charge_override(pending)
                _LOGGER.info(
                    "ECEvTouSwitch: deferred force-charge override applied (expires %s)",
                    pending.isoformat(),
                )
                self._pending_override_until = None
        except Exception:
            _LOGGER.debug(
                "ECEvTouSwitch: deferred override apply failed (non-fatal)",
                exc_info=True,
            )

    @property
    def extra_state_attributes(self) -> dict:
        """Return override expiry attribute (None when no override active)."""
        energy = self._get_energy()
        if energy is None:
            return {}
        ev = energy.ev_controller
        until = ev.force_charge_until
        if until is None:
            return {"override_active_until_iso": None}
        from homeassistant.util import dt as dt_util
        now_utc = dt_util.utcnow()
        if now_utc >= until:
            return {"override_active_until_iso": None}
        return {"override_active_until_iso": until.isoformat()}


# v4.7.2 D2: Dynamic Preset master kill switch — HVAC Coordinator device.
# unique_id PRESERVED from v4.7.1 ECDynamicPresetSwitch for entity_id stability.
# DeviceInfo.identifiers changed to hvac_coordinator for correct device placement.
# Default flipped OFF→ON (feature is a no-op for zones without per-zone opt-in).


class HVACDynamicPresetSwitch(SwitchEntity, RestoreEntity):
    """Master kill switch for Dynamic Preset Auto-Adjust.

    Backing field: EnergyCoordinator._dynamic_preset_enabled.
    Device:        URA: HVAC Coordinator (changed from EC in v4.7.2).
    unique_id:     {DOMAIN}_energy_dynamic_preset_enabled (PRESERVED — entity_id stable).

    Default ON: DPM is a no-op for any zone without CONF_ZONE_DYNAMIC_PRESET_ENABLED=True,
    so the OFF default was over-conservative. Existing user-saved OFF is honoured.

    Replicates the SIGNAL_ENERGY_COORDINATOR_READY deferred-restore pattern from
    _ec_switch_factory (Bug Class #5 + #38 compliance).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermometer-auto"
    _attr_entity_category = EntityCategory.CONFIG

    _RETRY_DELAYS_S = (5, 30, 120)

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        # unique_id PRESERVED from v4.7.1 ECDynamicPresetSwitch — entity_id stable.
        self._attr_unique_id = f"{DOMAIN}_energy_dynamic_preset_enabled"
        self._attr_name = "02 · Dynamic Preset Auto-Adjust"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # Default ON (see docstring).
        self._default: bool = True
        self._deferred_restore: bool = False
        self._deferred_value: bool = True
        self._retry_index: int = 0
        # B4 fix (v4.7.2 reviewer fix-up): initialize here so direct attribute
        # access is safe on all code paths (not just the deferred first-install path).
        self._default_flip_pending_nm: bool = False

    def _get_energy(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    @property
    def available(self) -> bool:
        return self._get_energy() is not None

    @property
    def is_on(self) -> bool:
        energy = self._get_energy()
        if energy is None:
            return self._default
        return getattr(energy, "dynamic_preset_enabled", self._default)

    async def async_turn_on(self, **kwargs) -> None:
        energy = self._get_energy()
        if energy is not None:
            energy.dynamic_preset_enabled = True
            self._deferred_restore = False
            self.async_write_ha_state()
            _LOGGER.info("HVAC: Dynamic Preset Auto-Adjust enabled")

    async def async_turn_off(self, **kwargs) -> None:
        energy = self._get_energy()
        if energy is not None:
            energy.dynamic_preset_enabled = False
            self._deferred_restore = False
            self.async_write_ha_state()
            _LOGGER.info("HVAC: Dynamic Preset Auto-Adjust disabled")

    async def async_added_to_hass(self) -> None:
        """Restore state — deferred via SIGNAL_ENERGY_COORDINATOR_READY if EC not yet ready.

        v4.7.2 D2: Replicates _ec_switch_factory deferred-restore pattern.
        Default flip: first-time install (no saved state) → ON.
        User-saved OFF: respected (not clobbered by default).
        NM notification: fires once when default-flip applies (no prior saved state).
        Bug Class #38: unsubs tracked via async_on_remove.
        """
        await super().async_added_to_hass()

        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_ENERGY_COORDINATOR_READY
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ENERGY_COORDINATOR_READY,
                self._handle_ec_ready,
            )
        )

        last_state = await self.async_get_last_state()
        if last_state is None:
            # First-time install — apply default ON and fire NM notification.
            self._deferred_value = True
            energy = self._get_energy()
            if energy is not None:
                energy.dynamic_preset_enabled = True
                self._deferred_restore = False
                self.async_write_ha_state()
                _LOGGER.info(
                    "HVACDynamicPresetSwitch: first install — defaulting ON "
                    "(feature is no-op for zones without per-zone opt-in)"
                )
                self._fire_default_on_nm_notification()
            else:
                # EC not yet ready — defer and fire NM notification when it arrives.
                self._deferred_restore = True
                self._default_flip_pending_nm = True
                self._retry_index = 0
                self.async_on_remove(
                    async_call_later(
                        self.hass, self._RETRY_DELAYS_S[0], self._retry_restore
                    )
                )
            return

        target = last_state.state == "on"
        self._deferred_value = target
        energy = self._get_energy()
        if energy is not None:
            energy.dynamic_preset_enabled = target
            self._deferred_restore = False
            try:
                energy.notify_sub_switch_restore_complete()
            except Exception:
                pass
            self.async_write_ha_state()
            return

        # EC not yet ready — defer restore.
        self._deferred_restore = True
        self._retry_index = 0
        self.async_on_remove(
            async_call_later(
                self.hass, self._RETRY_DELAYS_S[0], self._retry_restore
            )
        )

    def _fire_default_on_nm_notification(self) -> None:
        """Fire a one-shot NM info notification on first install after v4.7.2."""
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            nm = manager.coordinators.get("notification_manager") if manager else None
            if nm is not None:
                nm.send_info(
                    "Dynamic Preset Auto-Adjust is now ON by default. "
                    "It only activates for zones where per-zone DPM is enabled. "
                    "You can turn it off from the HVAC Coordinator device page."
                )
        except Exception:
            pass

    @callback
    def _handle_ec_ready(self) -> None:
        """Handle SIGNAL_ENERGY_COORDINATOR_READY — complete deferred restore.

        Bug Class #42: bound method, not lambda.
        Bug Class #19: @callback fires synchronously on event loop.
        """
        if not self._deferred_restore:
            return
        energy = self._get_energy()
        if energy is None:
            _LOGGER.warning(
                "HVACDynamicPresetSwitch: SIGNAL_ENERGY_COORDINATOR_READY fired "
                "but EC still not in hass.data — restore deferred"
            )
            return
        energy.dynamic_preset_enabled = self._deferred_value
        self._deferred_restore = False
        try:
            energy.notify_sub_switch_restore_complete()
        except Exception:
            pass
        self.async_write_ha_state()
        _LOGGER.info(
            "HVACDynamicPresetSwitch: deferred restore completed via "
            "SIGNAL_ENERGY_COORDINATOR_READY (value=%s)",
            self._deferred_value,
        )
        # Fire NM notification if this was a first-install default-flip.
        if getattr(self, "_default_flip_pending_nm", False):
            self._default_flip_pending_nm = False
            self._fire_default_on_nm_notification()

    @callback
    def _retry_restore(self, _now=None):
        if not self._deferred_restore:
            return
        energy = self._get_energy()
        if energy is not None:
            energy.dynamic_preset_enabled = self._deferred_value
            self._deferred_restore = False
            try:
                energy.notify_sub_switch_restore_complete()
            except Exception:
                pass
            self.async_write_ha_state()
            if getattr(self, "_default_flip_pending_nm", False):
                self._default_flip_pending_nm = False
                self._fire_default_on_nm_notification()
            return
        self._retry_index += 1
        if self._retry_index < len(self._RETRY_DELAYS_S):
            self.async_on_remove(
                async_call_later(
                    self.hass,
                    self._RETRY_DELAYS_S[self._retry_index],
                    self._retry_restore,
                )
            )
        else:
            _LOGGER.warning(
                "HVACDynamicPresetSwitch: timer retry chain exhausted — waiting for "
                "SIGNAL_ENERGY_COORDINATOR_READY to complete restore"
            )


class HVACGuestModeActuationSwitch(SwitchEntity, RestoreEntity):
    """D3: Master kill switch for Guest Mode HVAC actuation.

    When ON (default): OverrideEngine temperature ranges are applied to
    thermostats when house_state is guest (or dynamic preset is active).
    When OFF: _apply_house_state_presets skips the OverrideEngine path
    entirely and reverts to plain set_preset_mode behavior.

    Entity: switch.ura_hvac_coordinator_guest_mode_actuation_enabled
    Device: URA: HVAC Coordinator

    v4.7.1 fix-up D3 (PLANNING_v4.7.x_guest_mode_actuation_phase1.md §5.D3 reduced).
    v4.7.3.1: deferred-restore via SIGNAL_HVAC_COORDINATOR_READY (Bug Class #5/#38).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-arrow-right"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_guest_mode_actuation_enabled"
        self._attr_name = "01 · Custom Preset Ranges"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # v4.7.3.1: deferred-restore state (Bug Class #5).
        self._deferred_value: bool | None = None

    def _get_hvac(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("hvac") if manager else None

    @property
    def available(self) -> bool:
        return self._get_hvac() is not None

    @property
    def is_on(self) -> bool:
        hvac = self._get_hvac()
        if hvac is None:
            return True  # default ON
        return getattr(hvac, "_guest_mode_actuation_enabled", True)

    async def async_turn_on(self, **kwargs) -> None:
        hvac = self._get_hvac()
        if hvac is not None:
            hvac._guest_mode_actuation_enabled = True
            self._deferred_value = None
            self.async_write_ha_state()
            _LOGGER.info("HVAC: Guest Mode Actuation enabled")

    async def async_turn_off(self, **kwargs) -> None:
        hvac = self._get_hvac()
        if hvac is not None:
            hvac._guest_mode_actuation_enabled = False
            self._deferred_value = None
            # Clear last-emitted range so next enable re-applies baseline
            if hasattr(hvac, "_last_emitted_range"):
                hvac._last_emitted_range.clear()
            self.async_write_ha_state()
            _LOGGER.info("HVAC: Guest Mode Actuation disabled")

    async def async_added_to_hass(self) -> None:
        """Restore state — deferred via SIGNAL_HVAC_COORDINATOR_READY if needed.

        v4.7.3.1: Bug Class #5 fix. Subscribes to SIGNAL_HVAC_COORDINATOR_READY
        (Bug Class #38: unsub tracked via async_on_remove).
        """
        await super().async_added_to_hass()

        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_HVAC_COORDINATOR_READY
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_HVAC_COORDINATOR_READY,
                self._handle_hvac_ready,
            )
        )

        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state not in ("on", "off"):
            # No prior state — default ON is truth; nothing to restore.
            return
        target = last_state.state == "on"
        hvac = self._get_hvac()
        if hvac is not None:
            # Fast path: HVAC coord already registered.
            hvac._guest_mode_actuation_enabled = target
            self._deferred_value = None
            self.async_write_ha_state()
            return
        # Deferred path: HVAC coord not yet registered.
        self._deferred_value = target
        _LOGGER.debug(
            "HVACGuestModeActuationSwitch: HVAC coord not ready — deferring restore "
            "(value=%s)",
            target,
        )

    @callback
    def _handle_hvac_ready(self) -> None:
        """Handle SIGNAL_HVAC_COORDINATOR_READY — complete deferred restore.

        Bug Class #42: bound method, not lambda.
        Bug Class #19: @callback fires synchronously on the event loop.
        """
        if self._deferred_value is None:
            return
        hvac = self._get_hvac()
        if hvac is None:
            _LOGGER.warning(
                "HVACGuestModeActuationSwitch: SIGNAL_HVAC_COORDINATOR_READY fired "
                "but HVAC coord still not in hass.data — restore deferred"
            )
            return
        hvac._guest_mode_actuation_enabled = self._deferred_value
        _LOGGER.info(
            "HVACGuestModeActuationSwitch: deferred restore landed via "
            "SIGNAL_HVAC_COORDINATOR_READY (value=%s)",
            self._deferred_value,
        )
        self._deferred_value = None
        self.async_write_ha_state()


class HVACOverrideArresterSwitch(SwitchEntity, RestoreEntity):
    """Toggle HVAC Override Arrester.

    When ON (default): Arrester detects manual overrides and reverts/compromises.
    When OFF: Passive mode — overrides are tracked for diagnostics but not reverted.

    Entity: switch.ura_hvac_override_arrester
    Device: URA: HVAC Coordinator

    v4.7.3.1: deferred-restore via SIGNAL_HVAC_COORDINATOR_READY (Bug Class #5/#38).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-alert"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_override_arrester"
        self._attr_name = "20 · Override Arrester"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # v4.7.3.1: deferred-restore state (Bug Class #5).
        self._deferred_value: bool | None = None

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
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable override arrester (passive mode)."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.override_arrester.enabled = False
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state — deferred via SIGNAL_HVAC_COORDINATOR_READY if needed.

        v4.7.3.1: Bug Class #5 fix. Subscribes to SIGNAL_HVAC_COORDINATOR_READY
        (Bug Class #38: unsub tracked via async_on_remove).
        """
        await super().async_added_to_hass()

        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_HVAC_COORDINATOR_READY
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_HVAC_COORDINATOR_READY,
                self._handle_hvac_ready,
            )
        )

        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state not in ("on", "off"):
            # No prior state or transient state — default ON is truth; nothing to restore.
            return
        target = last_state.state == "on"
        hvac = self._get_hvac()
        if hvac is not None:
            # Fast path: HVAC coord already registered.
            hvac.override_arrester.enabled = target
            self._deferred_value = None
            self.async_write_ha_state()
            return
        # Deferred path: HVAC coord not yet registered.
        self._deferred_value = target
        _LOGGER.debug(
            "HVACOverrideArresterSwitch: HVAC coord not ready — deferring restore "
            "(value=%s)",
            target,
        )

    @callback
    def _handle_hvac_ready(self) -> None:
        """Handle SIGNAL_HVAC_COORDINATOR_READY — complete deferred restore.

        Bug Class #42: bound method, not lambda.
        Bug Class #19: @callback fires synchronously on the event loop.
        """
        if self._deferred_value is None:
            return
        hvac = self._get_hvac()
        if hvac is None:
            _LOGGER.warning(
                "HVACOverrideArresterSwitch: SIGNAL_HVAC_COORDINATOR_READY fired "
                "but HVAC coord still not in hass.data — restore deferred"
            )
            return
        hvac.override_arrester.enabled = self._deferred_value
        _LOGGER.info(
            "HVACOverrideArresterSwitch: deferred restore landed via "
            "SIGNAL_HVAC_COORDINATOR_READY (value=%s)",
            self._deferred_value,
        )
        self._deferred_value = None
        self.async_write_ha_state()

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

    v4.7.3.1 extension: deferred-restore via SIGNAL_HVAC_COORDINATOR_READY
    (Bug Class #5/#38).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:refresh-circle"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_reset"
        self._attr_name = "25 · AC Reset"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # v4.7.3.1 extension: deferred-restore state (Bug Class #5).
        self._deferred_value: bool | None = None

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
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable AC reset."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.override_arrester.ac_reset_enabled = False
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state — deferred via SIGNAL_HVAC_COORDINATOR_READY if needed.

        v4.7.3.1 extension: Bug Class #5 fix. Subscribes to SIGNAL_HVAC_COORDINATOR_READY
        (Bug Class #38: unsub tracked via async_on_remove).
        """
        await super().async_added_to_hass()

        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_HVAC_COORDINATOR_READY
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_HVAC_COORDINATOR_READY,
                self._handle_hvac_ready,
            )
        )

        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state not in ("on", "off"):
            # No prior state or transient state — default ON is truth; nothing to restore.
            return
        target = last_state.state == "on"
        hvac = self._get_hvac()
        if hvac is not None:
            # Fast path: HVAC coord already registered.
            hvac.override_arrester.ac_reset_enabled = target
            self._deferred_value = None
            self.async_write_ha_state()
            return
        # Deferred path: HVAC coord not yet registered.
        self._deferred_value = target
        _LOGGER.debug(
            "HVACACResetSwitch: HVAC coord not ready — deferring restore (value=%s)",
            target,
        )

    @callback
    def _handle_hvac_ready(self) -> None:
        """Handle SIGNAL_HVAC_COORDINATOR_READY — complete deferred restore.

        Bug Class #42: bound method, not lambda.
        Bug Class #19: @callback fires synchronously on the event loop.
        """
        if self._deferred_value is None:
            return
        hvac = self._get_hvac()
        if hvac is None:
            _LOGGER.warning(
                "HVACACResetSwitch: SIGNAL_HVAC_COORDINATOR_READY fired "
                "but HVAC coord still not in hass.data — restore deferred"
            )
            return
        hvac.override_arrester.ac_reset_enabled = self._deferred_value
        _LOGGER.info(
            "HVACACResetSwitch: deferred restore landed via "
            "SIGNAL_HVAC_COORDINATOR_READY (value=%s)",
            self._deferred_value,
        )
        self._deferred_value = None
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Only available when HVAC coordinator is active."""
        return self._get_hvac() is not None


class HVACACNudgeSwitch(SwitchEntity, RestoreEntity):
    """Toggle HVAC AC Nudge (v4.7.7 A1).

    When ON (default): soft-nudge detection runs on the HVAC decision
    cycle. Detected overshoot + sustained kWh-rate triggers a bump of
    the cool setpoint by `hvac_ac_nudge_size` °F for
    `hvac_ac_nudge_duration` minutes, then evaluates effectiveness.
    When OFF: soft-nudge detection is skipped (Gate 0b in
    `OverrideArrester.check_ac_reset`); AC Reset (if also ON) continues
    to be invokable via direct triggers.

    Entity: switch.ura_hvac_ac_nudge
    Device: URA: HVAC Coordinator
    Sibling of: switch.ura_hvac_ac_reset (independent feature toggle).

    v4.7.7 A1: mirrors HVACACResetSwitch line-for-line including the
    v4.7.3.1 deferred-restore pattern via SIGNAL_HVAC_COORDINATOR_READY
    (Bug Classes #5, #19, #38, #42 — see switch.py:1383 HVACACResetSwitch
    for the source pattern).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermometer-chevron-up"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_nudge"
        self._attr_name = "26 · AC Nudge"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # v4.7.7 A1: deferred-restore state (Bug Class #5).
        self._deferred_value: bool | None = None

    def _get_hvac(self):
        """Get the HVAC coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    @property
    def is_on(self) -> bool:
        """Return True if AC nudge is enabled."""
        hvac = self._get_hvac()
        if hvac is None:
            return True  # default on
        return hvac.override_arrester.ac_nudge_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable AC nudge."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.override_arrester.ac_nudge_enabled = True
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable AC nudge."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.override_arrester.ac_nudge_enabled = False
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state — deferred via SIGNAL_HVAC_COORDINATOR_READY if needed.

        Mirrors v4.7.3.1 HVACACResetSwitch.async_added_to_hass exactly.
        Bug Classes: #5 (deferred restore), #38 (unsub via async_on_remove).
        """
        await super().async_added_to_hass()

        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_HVAC_COORDINATOR_READY
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_HVAC_COORDINATOR_READY,
                self._handle_hvac_ready,
            )
        )

        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state not in ("on", "off"):
            # No prior state or transient state — default ON is truth; nothing to restore.
            return
        target = last_state.state == "on"
        hvac = self._get_hvac()
        if hvac is not None:
            # Fast path: HVAC coord already registered.
            hvac.override_arrester.ac_nudge_enabled = target
            self._deferred_value = None
            self.async_write_ha_state()
            return
        # Deferred path: HVAC coord not yet registered.
        self._deferred_value = target
        _LOGGER.debug(
            "HVACACNudgeSwitch: HVAC coord not ready — deferring restore (value=%s)",
            target,
        )

    @callback
    def _handle_hvac_ready(self) -> None:
        """Handle SIGNAL_HVAC_COORDINATOR_READY — complete deferred restore.

        Bug Class #42: bound method, not lambda.
        Bug Class #19: @callback fires synchronously on the event loop.
        """
        if self._deferred_value is None:
            return
        hvac = self._get_hvac()
        if hvac is None:
            _LOGGER.warning(
                "HVACACNudgeSwitch: SIGNAL_HVAC_COORDINATOR_READY fired "
                "but HVAC coord still not in hass.data — restore deferred"
            )
            return
        hvac.override_arrester.ac_nudge_enabled = self._deferred_value
        _LOGGER.info(
            "HVACACNudgeSwitch: deferred restore landed via "
            "SIGNAL_HVAC_COORDINATOR_READY (value=%s)",
            self._deferred_value,
        )
        self._deferred_value = None
        self.async_write_ha_state()

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

    v4.7.3.1 extension: replaced 5-second timer retry with deferred-restore
    via SIGNAL_HVAC_COORDINATOR_READY (Bug Class #5/#38).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:eye-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_observation_mode"
        self._attr_name = "10 · HVAC Observation Mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # v4.7.3.1 extension: deferred-restore state (Bug Class #5).
        self._deferred_value: bool | None = None

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
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable HVAC observation mode."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.observation_mode = False
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state — deferred via SIGNAL_HVAC_COORDINATOR_READY if needed.

        v4.7.3.1 extension: Bug Class #5 fix. Replaces the old 5-second timer retry
        with the signal-based deferred-restore pattern. Subscribes to
        SIGNAL_HVAC_COORDINATOR_READY (Bug Class #38: unsub tracked via async_on_remove).
        """
        await super().async_added_to_hass()

        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_HVAC_COORDINATOR_READY
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_HVAC_COORDINATOR_READY,
                self._handle_hvac_ready,
            )
        )

        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state not in ("on", "off"):
            # No prior state or transient state — default OFF is truth; nothing to restore.
            return
        target = last_state.state == "on"
        hvac = self._get_hvac()
        if hvac is not None:
            # Fast path: HVAC coord already registered.
            hvac.observation_mode = target
            self._deferred_value = None
            self.async_write_ha_state()
            return
        # Deferred path: HVAC coord not yet registered.
        self._deferred_value = target
        _LOGGER.debug(
            "HVACObservationModeSwitch: HVAC coord not ready — deferring restore "
            "(value=%s)",
            target,
        )

    @callback
    def _handle_hvac_ready(self) -> None:
        """Handle SIGNAL_HVAC_COORDINATOR_READY — complete deferred restore.

        Bug Class #42: bound method, not lambda.
        Bug Class #19: @callback fires synchronously on the event loop.
        """
        if self._deferred_value is None:
            return
        hvac = self._get_hvac()
        if hvac is None:
            _LOGGER.warning(
                "HVACObservationModeSwitch: SIGNAL_HVAC_COORDINATOR_READY fired "
                "but HVAC coord still not in hass.data — restore deferred"
            )
            return
        hvac.observation_mode = self._deferred_value
        _LOGGER.info(
            "HVACObservationModeSwitch: deferred restore landed via "
            "SIGNAL_HVAC_COORDINATOR_READY (value=%s)",
            self._deferred_value,
        )
        self._deferred_value = None
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Only available when HVAC coordinator is active."""
        return self._get_hvac() is not None


# ============================================================================
# v4.7.15 D6: Consensus defer gate switches (HVAC + compliance)
# ============================================================================


class HVACConsensusDeferGateSwitch(SwitchEntity, RestoreEntity):
    """v4.7.15 D6: Toggle HVAC consensus defer gate.

    When ON (default): _apply_house_state_presets skips preset writes when
    signal_consensus < 0.5 AND last house-state transition < 30 s ago.
    When OFF: gate disabled — HVAC reverts to pre-v4.7.15 behaviour.

    Entity: switch.ura_hvac_consensus_defer_gate
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:gate-arrow-right"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_consensus_defer_gate"
        self._attr_name = "HVAC Consensus Defer Gate"
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

    @property
    def is_on(self) -> bool:
        hvac = self._get_hvac()
        if hvac is None:
            return True  # default ON when coord unavailable
        return getattr(hvac, "_defer_gate_enabled", True)

    async def async_turn_on(self, **kwargs) -> None:
        hvac = self._get_hvac()
        if hvac is not None:
            hvac._defer_gate_enabled = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        hvac = self._get_hvac()
        if hvac is not None:
            hvac._defer_gate_enabled = False
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        # Default ON: only flip to OFF if explicitly restored to OFF.
        if last_state is not None and last_state.state == "off":
            hvac = self._get_hvac()
            if hvac is not None:
                hvac._defer_gate_enabled = False

    @property
    def available(self) -> bool:
        return self._get_hvac() is not None


class ComplianceConsensusDeferGateSwitch(SwitchEntity, RestoreEntity):
    """v4.7.15 D6: Toggle compliance violation defer gate.

    When ON (default): _emit_compliance_violation_anomaly suppresses emits
    when signal_consensus < 0.6 sustained for >= 60 s.
    When OFF: gate disabled — compliance violations emit at v4.7.14 cadence.

    Entity: switch.ura_compliance_consensus_defer_gate
    Device: URA: Coordinator Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:gate-arrow-right"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_compliance_consensus_defer_gate"
        self._attr_name = "Compliance Consensus Defer Gate"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    def _get_compliance(self):
        """Get the ComplianceTracker instance (lives on coordinator_manager)."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return getattr(manager, "compliance_tracker", None)

    @property
    def is_on(self) -> bool:
        tracker = self._get_compliance()
        if tracker is None:
            return True  # default ON
        return getattr(tracker, "_compliance_defer_gate_enabled", True)

    async def async_turn_on(self, **kwargs) -> None:
        tracker = self._get_compliance()
        if tracker is not None:
            tracker._compliance_defer_gate_enabled = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        tracker = self._get_compliance()
        if tracker is not None:
            tracker._compliance_defer_gate_enabled = False
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == "off":
            tracker = self._get_compliance()
            if tracker is not None:
                tracker._compliance_defer_gate_enabled = False

    @property
    def available(self) -> bool:
        return self._get_compliance() is not None


# ============================================================================
# v3.21.1 D1: Observation mode toggles for Safety, Security, Presence
# ============================================================================


class SafetyObservationModeSwitch(SwitchEntity, RestoreEntity):
    """Toggle Safety Coordinator observation mode.

    When ON: Hazard detection continues but no actions are executed
    (no NM alerts, no service calls, no emergency lights).
    When OFF (default): Normal operation.

    Entity: switch.ura_safety_observation_mode
    Device: URA: Safety Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:eye-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_safety_observation_mode"
        self._attr_name = "Safety Observation Mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "safety_coordinator")},
            name="URA: Safety Coordinator",
            manufacturer="Universal Room Automation",
            model="Safety Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        self._deferred_restore = False

    def _get_safety(self):
        """Get the Safety coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("safety")

    @property
    def is_on(self) -> bool:
        """Return True if Safety observation mode is active."""
        safety = self._get_safety()
        if safety is None:
            return False
        return safety.observation_mode

    async def async_turn_on(self, **kwargs) -> None:
        """Enable Safety observation mode."""
        safety = self._get_safety()
        if safety is not None:
            safety.observation_mode = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable Safety observation mode."""
        safety = self._get_safety()
        if safety is not None:
            safety.observation_mode = False
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == "on":
            safety = self._get_safety()
            if safety is not None:
                safety.observation_mode = True
            else:
                # Deferred retry: coordinator may not be initialized yet
                self._deferred_restore = True
                self.async_on_remove(async_call_later(self.hass, 5, self._retry_restore))

    def _retry_restore(self, _now=None) -> None:
        """Retry setting observation mode after coordinator initializes."""
        if not self._deferred_restore:
            return
        safety = self._get_safety()
        if safety is not None:
            safety.observation_mode = True
            self._deferred_restore = False
            _LOGGER.info("Safety observation mode restored (deferred)")
        else:
            _LOGGER.warning("Safety observation mode restore failed — coordinator still unavailable after 5s")

    @property
    def available(self) -> bool:
        """Only available when Safety coordinator is active."""
        return self._get_safety() is not None


class SecurityObservationModeSwitch(SwitchEntity, RestoreEntity):
    """Toggle Security Coordinator observation mode.

    When ON: Entry evaluation and armed state tracking continue but no
    lock commands, NM alerts, or camera triggers are executed.
    When OFF (default): Normal operation.

    Entity: switch.ura_security_observation_mode
    Device: URA: Security Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:eye-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_security_observation_mode"
        self._attr_name = "Security Observation Mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "security_coordinator")},
            name="URA: Security Coordinator",
            manufacturer="Universal Room Automation",
            model="Security Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        self._deferred_restore = False

    def _get_security(self):
        """Get the Security coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("security")

    @property
    def is_on(self) -> bool:
        """Return True if Security observation mode is active."""
        security = self._get_security()
        if security is None:
            return False
        return security.observation_mode

    async def async_turn_on(self, **kwargs) -> None:
        """Enable Security observation mode."""
        security = self._get_security()
        if security is not None:
            security.observation_mode = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable Security observation mode."""
        security = self._get_security()
        if security is not None:
            security.observation_mode = False
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == "on":
            security = self._get_security()
            if security is not None:
                security.observation_mode = True
            else:
                # Deferred retry: coordinator may not be initialized yet
                self._deferred_restore = True
                self.async_on_remove(async_call_later(self.hass, 5, self._retry_restore))

    def _retry_restore(self, _now=None) -> None:
        """Retry setting observation mode after coordinator initializes."""
        if not self._deferred_restore:
            return
        security = self._get_security()
        if security is not None:
            security.observation_mode = True
            self._deferred_restore = False
            _LOGGER.info("Security observation mode restored (deferred)")
        else:
            _LOGGER.warning("Security observation mode restore failed — coordinator still unavailable after 5s")

    @property
    def available(self) -> bool:
        """Only available when Security coordinator is active."""
        return self._get_security() is not None


class PresenceObservationModeSwitch(SwitchEntity, RestoreEntity):
    """Toggle Presence Coordinator observation mode.

    When ON: Inference and zone tracking continue but
    SIGNAL_HOUSE_STATE_CHANGED and SIGNAL_PERSON_ARRIVING are not
    dispatched.
    When OFF (default): Normal operation.

    Entity: switch.ura_presence_observation_mode
    Device: URA: Presence Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:eye-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_presence_observation_mode"
        self._attr_name = "Presence Observation Mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        self._deferred_restore = False

    def _get_presence(self):
        """Get the Presence coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("presence")

    @property
    def is_on(self) -> bool:
        """Return True if Presence observation mode is active."""
        presence = self._get_presence()
        if presence is None:
            return False
        return presence.observation_mode

    async def async_turn_on(self, **kwargs) -> None:
        """Enable Presence observation mode."""
        presence = self._get_presence()
        if presence is not None:
            presence.observation_mode = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable Presence observation mode."""
        presence = self._get_presence()
        if presence is not None:
            presence.observation_mode = False
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == "on":
            presence = self._get_presence()
            if presence is not None:
                presence.observation_mode = True
            else:
                # Deferred retry: coordinator may not be initialized yet
                self._deferred_restore = True
                self.async_on_remove(async_call_later(self.hass, 5, self._retry_restore))

    def _retry_restore(self, _now=None) -> None:
        """Retry setting observation mode after coordinator initializes."""
        if not self._deferred_restore:
            return
        presence = self._get_presence()
        if presence is not None:
            presence.observation_mode = True
            self._deferred_restore = False
            _LOGGER.info("Presence observation mode restored (deferred)")
        else:
            _LOGGER.warning("Presence observation mode restore failed — coordinator still unavailable after 5s")

    @property
    def available(self) -> bool:
        """Only available when Presence coordinator is active."""
        return self._get_presence() is not None


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
        # v4.5.10: friendlier label. Underlying CONF + entity_id stay the
        # same to preserve dashboards and existing automations.
        self._attr_name = "30 · Per-Zone HVAC Control"
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
        # v4.5.10: friendlier label. Underlying CONF + entity_id stay the
        # same to preserve dashboards.
        self._attr_name = "46 · Vacancy Auto-Off"
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


class HVACSolarCoverSwitch(SwitchEntity, RestoreEntity):
    """v4.5.10: Master toggle for the solar-gain cover management feature.

    When ON (default): CoverController runs its full v4.5.9 logic —
    discovers covers from rooms in HVAC zones (respecting per-room
    `cover_hvac_managed` opt-out), closes covers during peak solar
    hours, reopens at end of solar window. Tilt-aware dispatch.

    When OFF: CoverController.update() early-returns. No close or open
    commands fire from HVAC. Per-room cover automation (timed open/close,
    exit close) is unaffected — only the solar-gain feature is gated.

    Entity: switch.ura_hvac_solar_cover
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:weather-sunny-alert"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_solar_cover"
        self._attr_name = "45 · Solar Cover Management"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_cover_controller(self):
        """Get the CoverController instance via HVAC coord."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        hvac = manager.coordinators.get("hvac")
        return getattr(hvac, "_cover_controller", None) if hvac else None

    @property
    def is_on(self) -> bool:
        """Return True if Solar Cover Management is enabled."""
        cc = self._get_cover_controller()
        if cc is None:
            return True  # default on
        return getattr(cc, "_solar_gain_enabled", True)

    async def async_turn_on(self, **kwargs) -> None:
        """Enable Solar Cover Management."""
        cc = self._get_cover_controller()
        if cc is not None:
            cc._solar_gain_enabled = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable Solar Cover Management. CoverController.update() will
        early-return on the next decision tick."""
        cc = self._get_cover_controller()
        if cc is not None:
            cc._solar_gain_enabled = False
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            cc = self._get_cover_controller()
            if cc is not None:
                cc._solar_gain_enabled = last_state.state == "on"

    @property
    def available(self) -> bool:
        """Only available when CoverController is active."""
        return self._get_cover_controller() is not None


class HVACACRampMasterSwitch(SwitchEntity, RestoreEntity):
    """v4.5.11: Master toggle for the AC energy-aware ramp-down feature.

    When ON: detection cycle runs (per-zone gates still apply — needs
    ac_load_sensor configured + ramp_zone_enabled). Soft nudges and hard
    resets fire under their respective gates.

    When OFF: no detections, no nudges, no resets. Any in-flight nudges
    are cancelled and original setpoints restored (via the
    ramp_master_enabled.setter on OverrideArrester).

    Default OFF on first install — feature is invasive (changes setpoints,
    can cycle compressors). User must explicitly opt in after configuring
    per-zone ac_load_sensor.

    Entity: switch.ura_hvac_ac_ramp_master
    Device: URA: HVAC Coordinator

    v4.7.3.1: deferred-restore via SIGNAL_HVAC_COORDINATOR_READY (Bug Class #5/#38).
    Note: backing target is hvac._override_arrester.ramp_master_enabled (sub-object
    property), accessed via _get_arrester() — not directly on the HVAC coord.
    _handle_hvac_ready uses _get_arrester() for the same reason.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:air-conditioner"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_ramp_master"
        self._attr_name = "15 · AC Ramp-Down (Energy-Aware)"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # v4.7.3.1: deferred-restore state (Bug Class #5).
        self._deferred_value: bool | None = None

    def _get_arrester(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        hvac = manager.coordinators.get("hvac")
        return getattr(hvac, "_override_arrester", None) if hvac else None

    @property
    def is_on(self) -> bool:
        arr = self._get_arrester()
        if arr is None:
            return False
        return getattr(arr, "_ramp_master_enabled", False)

    async def async_turn_on(self, **kwargs) -> None:
        arr = self._get_arrester()
        if arr is not None:
            arr.ramp_master_enabled = True
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        arr = self._get_arrester()
        if arr is not None:
            arr.ramp_master_enabled = False  # setter cancels in-flight nudges
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state — deferred via SIGNAL_HVAC_COORDINATOR_READY if needed.

        v4.7.3.1: Bug Class #5 fix. Subscribes to SIGNAL_HVAC_COORDINATOR_READY
        (Bug Class #38: unsub tracked via async_on_remove).
        Default OFF on first install — feature is invasive (user must opt in).
        """
        await super().async_added_to_hass()

        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_HVAC_COORDINATOR_READY
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_HVAC_COORDINATOR_READY,
                self._handle_hvac_ready,
            )
        )

        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state not in ("on", "off"):
            # No prior state or transient state — default OFF is truth; nothing to restore.
            return
        target = last_state.state == "on"
        arr = self._get_arrester()
        if arr is not None:
            # Fast path: HVAC coord already registered (arrester available).
            arr.ramp_master_enabled = target
            self._deferred_value = None
            self.async_write_ha_state()
            return
        # Deferred path: arrester not yet available (HVAC coord not registered).
        self._deferred_value = target
        _LOGGER.debug(
            "HVACACRampMasterSwitch: HVAC coord not ready — deferring restore "
            "(value=%s)",
            target,
        )

    @callback
    def _handle_hvac_ready(self) -> None:
        """Handle SIGNAL_HVAC_COORDINATOR_READY — complete deferred restore.

        Bug Class #42: bound method, not lambda.
        Bug Class #19: @callback fires synchronously on the event loop.
        Note: uses _get_arrester() (not _get_hvac()) — backing field lives
        on hvac._override_arrester, consistent with the rest of this class.
        """
        if self._deferred_value is None:
            return
        arr = self._get_arrester()
        if arr is None:
            _LOGGER.warning(
                "HVACACRampMasterSwitch: SIGNAL_HVAC_COORDINATOR_READY fired "
                "but arrester still not in hass.data — restore deferred"
            )
            return
        arr.ramp_master_enabled = self._deferred_value
        _LOGGER.info(
            "HVACACRampMasterSwitch: deferred restore landed via "
            "SIGNAL_HVAC_COORDINATOR_READY (value=%s)",
            self._deferred_value,
        )
        self._deferred_value = None
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._get_arrester() is not None


class HVACPreArrivalSwitch(SwitchEntity, RestoreEntity):
    """Toggle HVAC pre-arrival conditioning.

    When ON (default): HVAC pre-conditions zones when a person arrives
    home (via geofence or BLE detection).
    When OFF: Pre-arrival signals are ignored — no zone pre-conditioning.

    v3.18.6: Provides runtime control over pre-arrival feature.

    Entity: switch.ura_hvac_pre_arrival
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-clock"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_pre_arrival"
        self._attr_name = "35 · Pre-Arrival Conditioning"
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
        """Return True if pre-arrival conditioning is enabled."""
        hvac = self._get_hvac()
        if hvac is None:
            return True  # default on
        return hvac.pre_arrival_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable pre-arrival conditioning."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.pre_arrival_enabled = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable pre-arrival conditioning."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.pre_arrival_enabled = False
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            hvac = self._get_hvac()
            if hvac is not None:
                hvac.pre_arrival_enabled = last_state.state == "on"

    @property
    def available(self) -> bool:
        """Only available when HVAC coordinator is active."""
        return self._get_hvac() is not None


class HVACFanControlSwitch(SwitchEntity, RestoreEntity):
    """Toggle HVAC temperature-based fan control.

    When ON (default): FanController manages ceiling fans based on
    temperature delta from thermostat setpoint, with occupancy gating.
    When OFF: FanController is completely disabled — no temperature-based
    fan activation. Pre-arrival fan bridge (Path 2) is NOT affected.

    v4.0.15: Added to address fan flapping with external leave automations.

    Entity: switch.ura_hvac_coordinator_fan_control
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:fan"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_fan_control"
        self._attr_name = "40 · Fan Control"
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
        """Return True if fan control is enabled."""
        hvac = self._get_hvac()
        if hvac is None:
            return True  # default on
        return hvac.fan_control_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable temperature-based fan control."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.fan_control_enabled = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable temperature-based fan control."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.fan_control_enabled = False
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            hvac = self._get_hvac()
            if hvac is not None:
                hvac.fan_control_enabled = last_state.state == "on"
            else:
                # HVAC coordinator may not be registered yet — retry after 5s
                self._deferred_restore_state = last_state.state
                self.async_on_remove(
                    async_call_later(self.hass, 5, self._retry_restore)
                )

    @callback
    def _retry_restore(self, _now=None) -> None:
        """Deferred restore if HVAC coordinator wasn't ready at startup."""
        state = getattr(self, "_deferred_restore_state", None)
        if state is None:
            return
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.fan_control_enabled = state == "on"
            self._deferred_restore_state = None
        else:
            _LOGGER.debug("HVAC still not ready for fan control restore")

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


class OverrideOccupiedSwitch(UniversalRoomEntity, SwitchEntity, RestoreEntity):
    """Switch to override room as occupied."""

    _attr_icon = "mdi:account-check"

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "override_occupied", "Override Occupied")
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"

    async def async_turn_on(self, **kwargs) -> None:
        """Force room to occupied state."""
        self._attr_is_on = True
        # Review fix: publish state BEFORE mutual exclusion service call
        # so coordinator sees correct state if refresh interleaves
        self.async_write_ha_state()
        # Mutually exclusive: turn off vacant override
        vacant_slug = _room_switch_entity_id(self.coordinator, "override_vacant")
        vacant_state = self.hass.states.get(vacant_slug)
        if vacant_state and vacant_state.state == "on":
            await self.hass.services.async_call("switch", "turn_off", {"entity_id": vacant_slug})
        _LOGGER.info("Override occupied enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Remove occupied override."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Override occupied disabled for room: %s", self.coordinator.entry.data.get("room_name"))


class OverrideVacantSwitch(UniversalRoomEntity, SwitchEntity, RestoreEntity):
    """Switch to override room as vacant."""

    _attr_icon = "mdi:account-off"

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "override_vacant", "Override Vacant")
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"

    async def async_turn_on(self, **kwargs) -> None:
        """Force room to vacant state."""
        self._attr_is_on = True
        # Review fix: publish state BEFORE mutual exclusion service call
        self.async_write_ha_state()
        # Mutually exclusive: turn off occupied override
        occ_slug = _room_switch_entity_id(self.coordinator, "override_occupied")
        occ_state = self.hass.states.get(occ_slug)
        if occ_state and occ_state.state == "on":
            await self.hass.services.async_call("switch", "turn_off", {"entity_id": occ_slug})
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


# ============================================================================
# v3.21.0 D7: AI Automation Per-Room Toggle
# ============================================================================


class AiAutomationSwitch(UniversalRoomEntity, SwitchEntity, RestoreEntity):
    """Switch to enable/disable AI automation for a room.

    When ON (default): AI rules and automation chaining execute normally.
    When OFF: AI rules and chained automations are skipped for this room.

    Entity: switch.{room_slug}_ai_automation
    """

    _attr_icon = "mdi:robot"
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "ai_automation", "AI Automation")
        self._attr_is_on = True  # Default: enabled

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"

    async def async_turn_on(self, **kwargs) -> None:
        """Enable AI automation for this room."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("AI automation enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Disable AI automation for this room."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("AI automation disabled for room: %s", self.coordinator.entry.data.get("room_name"))


class InfrastructureRoomSwitch(UniversalRoomEntity, SwitchEntity, RestoreEntity):
    """Mark a room as infrastructure (always-on equipment).

    When ON: Room is excluded from waste detection (D6), reported as
    infrastructure baseline instead. Excluded from cost/hour rankings (D7).
    When OFF (default for most rooms): Normal waste/efficiency tracking.

    Auto-defaults to ON for rooms with room_type == "infrastructure".

    Entity: switch.{room_slug}_infrastructure
    v4.2.0 B4 L3
    """

    _attr_icon = "mdi:server-network"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "infrastructure", "Infrastructure Room")
        # Default from room_type
        self._attr_is_on = getattr(coordinator, "_infrastructure_room", False)

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"
        # Sync to coordinator
        self.coordinator._infrastructure_room = self._attr_is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Mark room as infrastructure."""
        self._attr_is_on = True
        self.coordinator._infrastructure_room = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Unmark room as infrastructure."""
        self._attr_is_on = False
        self.coordinator._infrastructure_room = False
        self.async_write_ha_state()



# =============================================================================
# v4.7.8 D2 — Egress Window HVAC Pause master toggle
# -----------------------------------------------------------------------------
# Single switch on URA: HVAC Coordinator device. When ON (default), an egress
# window open past `egress_pause_threshold_min` triggers climate.set_hvac_mode:
# off on the canonical HVAC zone. When OFF, the manager clears counters but
# does NOT auto-resume an already-paused zone (avoids flap when user toggles
# the switch while a window is open). Mirrors HVACACNudgeSwitch line-for-line
# including the v4.7.3.1 deferred-restore via SIGNAL_HVAC_COORDINATOR_READY
# (Bug Classes #5 / #38 / #42 — bound method handler, not lambda).
# =============================================================================


class HVACEgressWindowPauseSwitch(SwitchEntity, RestoreEntity):
    """Toggle Egress Window HVAC Pause (v4.7.8 D2).

    Default ON. RestoreEntity is the canonical runtime store; entry.options
    seeds install-time only.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:window-open-variant"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_egress_window_pause"
        # Friendly ordering — sits at "27" so it lands directly below AC Nudge (26).
        self._attr_name = "27 · Egress Window Pause"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # v4.7.8 D2: deferred-restore state (Bug Class #5).
        self._deferred_value: bool | None = None

    def _get_hvac(self):
        """Get the HVAC coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    @property
    def is_on(self) -> bool:
        """Return True if egress pause is enabled."""
        hvac = self._get_hvac()
        if hvac is None:
            return True  # default on
        try:
            return bool(hvac.egress_manager.enabled)
        except Exception:
            return True

    async def async_turn_on(self, **kwargs) -> None:
        """Enable egress pause."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.egress_manager.enabled = True
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable egress pause."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.egress_manager.enabled = False
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state — deferred via SIGNAL_HVAC_COORDINATOR_READY if needed.

        Mirrors HVACACNudgeSwitch.async_added_to_hass exactly.
        Bug Classes: #5 (deferred restore), #38 (unsub via async_on_remove).
        """
        await super().async_added_to_hass()

        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_HVAC_COORDINATOR_READY
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_HVAC_COORDINATOR_READY,
                self._handle_hvac_ready,
            )
        )

        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state not in ("on", "off"):
            # v4.7.8 fix-up B-H3: fresh install (no saved state). Still
            # discard the initial-restore gate bit so the first tick can
            # proceed using the seeded default.
            hvac = self._get_hvac()
            if hvac is not None:
                try:
                    hvac.egress_manager._initial_restore_pending.discard(
                        "enabled"
                    )
                except Exception:
                    pass
            return
        target = last_state.state == "on"
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.egress_manager.enabled = target
            self._deferred_value = None
            self.async_write_ha_state()
            return
        # Deferred path: HVAC coord not yet registered.
        self._deferred_value = target
        _LOGGER.debug(
            "HVACEgressWindowPauseSwitch: HVAC coord not ready — deferring "
            "restore (value=%s)",
            target,
        )

    @callback
    def _handle_hvac_ready(self) -> None:
        """Handle SIGNAL_HVAC_COORDINATOR_READY — complete deferred restore.

        Bug Class #42: bound method, not lambda.
        Bug Class #19: @callback fires synchronously on the event loop.
        """
        if self._deferred_value is None:
            return
        hvac = self._get_hvac()
        if hvac is None:
            _LOGGER.warning(
                "HVACEgressWindowPauseSwitch: SIGNAL_HVAC_COORDINATOR_READY "
                "fired but HVAC coord still not in hass.data — restore deferred"
            )
            return
        hvac.egress_manager.enabled = self._deferred_value
        _LOGGER.info(
            "HVACEgressWindowPauseSwitch: deferred restore landed via "
            "SIGNAL_HVAC_COORDINATOR_READY (value=%s)",
            self._deferred_value,
        )
        self._deferred_value = None
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Only available when HVAC coordinator is active."""
        return self._get_hvac() is not None


# =============================================================================
# Fan-noise Mode-2 — master kill switch + per-room opt-ins
# -----------------------------------------------------------------------------
# Master switch lives on URA: Presence Coordinator device. Mirrors the
# operator value into hass.data[DOMAIN]["fan_recheck_master_enabled"]
# (FanRecheckManager reads from there each eligibility check) AND into
# the CM entry.options (URA mirror pattern — entry.options seeds the next
# coordinator __init__, RestoreEntity is the runtime store).
#
# Per-room switches live on the room device. They write directly into
# the room entry.options so the next FanRecheckManager._is_eligible call
# picks them up; RestoreEntity preserves operator intent across restart.
# Defaults default to False — a post-deploy instance with no operator
# action does NOT actuate.
# =============================================================================


class FanRecheckEnabledSwitch(SwitchEntity, RestoreEntity):
    """Master kill switch for room-tier fan-recheck (Mode-2 mitigation).

    Default OFF. RestoreEntity is the canonical runtime store; entry.options
    seeds install-time only. Operator flips ON after live validation.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:fan-alert"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_name = "Fan Recheck"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from .const import (
            CONF_FAN_RECHECK_ENABLED,
            DEFAULT_FAN_RECHECK_ENABLED,
        )
        self.hass = hass
        self._entry = entry
        self._conf_key = CONF_FAN_RECHECK_ENABLED
        self._default = DEFAULT_FAN_RECHECK_ENABLED
        self._attr_unique_id = f"{DOMAIN}_fan_recheck_enabled"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        config = {**entry.data, **entry.options}
        self._is_on = bool(config.get(self._conf_key, self._default))
        # Seed the runtime master flag on construction so eligibility
        # checks before async_added_to_hass land on the install-time
        # default (False) rather than KeyError-then-default-False.
        self.hass.data.setdefault(DOMAIN, {})[
            "fan_recheck_master_enabled"
        ] = self._is_on

    @property
    def is_on(self) -> bool:
        return self._is_on

    def _mirror_runtime(self, value: bool) -> None:
        """Push current value to hass.data so FanRecheckManager sees it."""
        self.hass.data.setdefault(DOMAIN, {})[
            "fan_recheck_master_enabled"
        ] = value

    def _mirror_options(self, value: bool) -> None:
        """Mirror to CM entry.options (URA mirror pattern).

        Next coordinator __init__ re-seeds from this value rather than
        snapping back to DEFAULT_FAN_RECHECK_ENABLED on reload.
        """
        try:
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={**self._entry.options, self._conf_key: value},
            )
        except Exception:  # noqa: BLE001 — best-effort mirror
            _LOGGER.debug(
                "FanRecheckEnabledSwitch: entry.options mirror failed",
                exc_info=True,
            )

    async def async_added_to_hass(self) -> None:
        """Restore last state — RestoreEntity is the runtime source."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._is_on = last_state.state == "on"
        self._mirror_runtime(self._is_on)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        self._mirror_runtime(True)
        self._mirror_options(True)
        self.async_write_ha_state()
        _LOGGER.info("FanRecheckEnabledSwitch: master enabled")

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        self._mirror_runtime(False)
        self._mirror_options(False)
        self.async_write_ha_state()
        _LOGGER.info("FanRecheckEnabledSwitch: master disabled")


class RoomFanRecheckEnabledSwitch(
    UniversalRoomEntity, SwitchEntity, RestoreEntity,
):
    """Per-room opt-in for the fan-recheck mechanism.

    Default OFF. RestoreEntity is the runtime store; entry.options
    seeds install-time only. Writes the value back into the room
    entry.options on toggle so the FanRecheckManager
    `_merged_config(room_coord)` read picks it up immediately.
    """

    _attr_icon = "mdi:fan-clock"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        from .const import (
            CONF_ROOM_FAN_RECHECK_ENABLED,
            DEFAULT_ROOM_FAN_RECHECK_ENABLED,
        )
        super().__init__(
            coordinator, "fan_recheck_enabled", "Fan Recheck",
        )
        self._conf_key = CONF_ROOM_FAN_RECHECK_ENABLED
        merged = {**coordinator.entry.data, **coordinator.entry.options}
        self._attr_is_on = bool(
            merged.get(self._conf_key, DEFAULT_ROOM_FAN_RECHECK_ENABLED),
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._attr_is_on = last_state.state == "on"

    def _mirror_options(self, value: bool) -> None:
        try:
            entry = self.coordinator.entry
            self.hass.config_entries.async_update_entry(
                entry,
                options={**entry.options, self._conf_key: value},
            )
        except Exception:  # noqa: BLE001 — best-effort mirror
            _LOGGER.debug(
                "RoomFanRecheckEnabledSwitch: options mirror failed",
                exc_info=True,
            )

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self._mirror_options(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self._mirror_options(False)
        self.async_write_ha_state()


class RoomFanRecheckL2AllowedSwitch(
    UniversalRoomEntity, SwitchEntity, RestoreEntity,
):
    """Per-room Tier-1 L2 weak-authorize opt-in for fan-recheck.

    Tier-1-only: enables the weak L2 path where a trustworthy phone in
    an adjacent room may *authorize* a recheck (person provably
    next-door). Default OFF because adjacency drift may be real
    next-door presence. Ignored in Tier-2/0 (L2 there is an unconditional
    safety VETO regardless of this flag).
    """

    _attr_icon = "mdi:fan-chevron-up"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        from .const import (
            CONF_FAN_RECHECK_L2_ALLOWED,
            DEFAULT_FAN_RECHECK_L2_ALLOWED,
        )
        super().__init__(
            coordinator, "fan_recheck_l2_allowed", "Fan Recheck L2 Allowed",
        )
        self._conf_key = CONF_FAN_RECHECK_L2_ALLOWED
        merged = {**coordinator.entry.data, **coordinator.entry.options}
        self._attr_is_on = bool(
            merged.get(self._conf_key, DEFAULT_FAN_RECHECK_L2_ALLOWED),
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._attr_is_on = last_state.state == "on"

    def _mirror_options(self, value: bool) -> None:
        try:
            entry = self.coordinator.entry
            self.hass.config_entries.async_update_entry(
                entry,
                options={**entry.options, self._conf_key: value},
            )
        except Exception:  # noqa: BLE001 — best-effort mirror
            _LOGGER.debug(
                "RoomFanRecheckL2AllowedSwitch: options mirror failed",
                exc_info=True,
            )

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self._mirror_options(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self._mirror_options(False)
        self.async_write_ha_state()
