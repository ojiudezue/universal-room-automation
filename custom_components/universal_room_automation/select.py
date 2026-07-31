"""Select platform for Universal Room Automation."""
#
# Universal Room Automation vv5.38.1
# File: select.py
# v3.6.0-c1: Added house state override and zone presence mode selects
#
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ZONE,
    ENTRY_TYPE_ZONE_MANAGER,
    HOUSE_STATE_OVERRIDE_OPTIONS,
    VERSION,
    ZONE_PRESENCE_OVERRIDE_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Universal Room Automation select entities."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE)

    # v3.6.0-c1: Integration entry — house state override on URA device
    if entry_type == ENTRY_TYPE_INTEGRATION:
        entities = [
            IntegrationHouseStateOverrideSelect(hass, entry),
        ]
        async_add_entities(entities)
        return

    # v3.6.0-c1: Coordinator Manager entry — house state override on CM + Presence devices
    if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:
        entities = [
            CMHouseStateOverrideSelect(hass, entry),
            PresenceHouseStateOverrideSelect(hass, entry),
            # v4.6.2 D6: routine notification mode select
            RoutineNotificationModeSelect(hass, entry),
            # v4.7.34 Phase 1 D7: Optimizer autonomy level (6 options).
            # Lives on the Optimization Coordinator device.
            OptimizerAutonomyLevelSelect(hass, entry),
            # v5.7.1: Energy Saver Pre-Cool Scope (EC device).
            # Three options: occupied_only / whole_house / auto_pv_tiered.
            EnergyPreCoolScopeSelect(hass, entry),
            # Session B1 — EVSE drain-precedence house-load source select.
            DrainPrecedenceHouseLoadSourceSelect(hass, entry),
        ]
        async_add_entities(entities)
        return

    # v3.6.0-c1: Zone Manager entry — create zone presence mode selects for all zones
    if entry_type == ENTRY_TYPE_ZONE_MANAGER:
        merged = {**entry.data, **entry.options}
        zones_data = merged.get("zones", {})
        entities = []
        for zone_name in zones_data:
            # v3.6.0-c2.1: Use raw zone name to match aggregation.py's
            # ZoneSensorBase identifiers — f"zone_{zone}" with zone as-is.
            # Previously used zone_slug (lowercased+underscored) which
            # created mismatched device identifiers and "Unnamed device" spam.
            zone_identifier = f"zone_{zone_name}"
            entities.append(
                ZonePresenceModeSelect(hass, zone_name, zone_identifier)
            )
        if entities:
            async_add_entities(entities)
            _LOGGER.info(
                "Set up %d zone presence mode selects", len(entities)
            )
        return

    # Legacy zone entry — no selects (migrated to Zone Manager)
    if entry_type == ENTRY_TYPE_ZONE:
        return

    # Room entry — no select entities (2026-07-26: AutomationModeSelect
    # deleted; it was an inert knob with no consumer. The real enable
    # control is `switch.<room>_automation`. Existing
    # `select.<room>_automation_mode` entities will remain in the entity
    # registry as unavailable/restored until the operator removes them
    # from the registry — this integration deliberately does NOT clean
    # them up automatically (Bug Class #46: never delete registry
    # entries from code).
    return


# ============================================================================
# v3.6.0-c1: House State Override Selects
# ============================================================================


class _HouseStateOverrideSelectBase(SelectEntity):
    """Base class for house state override select entities.

    Both the integration device and CM device get one of these.
    They share the same backing state (the HouseStateMachine override).

    v3.6.0-c2.4: available=False when coordinator_manager is not running,
    which grays out the dropdown in the HA UI.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-switch-outline"
    _attr_options = HOUSE_STATE_OVERRIDE_OPTIONS

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry

    @property
    def available(self) -> bool:
        """Return False when coordinator_manager is not running."""
        return self.hass.data.get(DOMAIN, {}).get("coordinator_manager") is not None

    @property
    def current_option(self) -> str:
        """Return current override (or 'auto' if no override)."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "auto"
        presence = manager.coordinators.get("presence")
        if presence is not None:
            return presence.get_house_state_override()
        # Fallback: check state machine directly
        if manager.house_state_machine.is_overridden:
            return str(manager.house_state_machine.state)
        return "auto"

    async def async_select_option(self, option: str) -> None:
        """Set house state override."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            _LOGGER.warning("Cannot set house state: coordinator manager not initialized")
            return

        presence = manager.coordinators.get("presence")
        if presence is not None:
            presence.set_house_state_override(option)
        else:
            # Direct state machine control if Presence not registered
            from .domain_coordinators.house_state import HouseState
            if option == "auto":
                manager.house_state_machine.clear_override()
            else:
                try:
                    manager.house_state_machine.set_override(HouseState(option))
                except ValueError:
                    _LOGGER.warning("Invalid house state: %s", option)
                    return

        self.async_write_ha_state()
        _LOGGER.info("House state override set to: %s", option)


class IntegrationHouseStateOverrideSelect(_HouseStateOverrideSelectBase):
    """House state override on the URA integration device.

    Entity: select.ura_house_state_override
    Device: Universal Room Automation (integration device)
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_house_state_override"
        self._attr_name = "House State Override"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "integration")},
            name="Universal Room Automation",
            manufacturer="Universal Room Automation",
            model="Whole House",
            sw_version=VERSION,
        )


class CMHouseStateOverrideSelect(_HouseStateOverrideSelectBase):
    """House state override on the Coordinator Manager device.

    Entity: select.ura_cm_house_state_override
    Device: URA: Coordinator Manager
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_cm_house_state_override"
        self._attr_name = "House State Override"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )


class PresenceHouseStateOverrideSelect(_HouseStateOverrideSelectBase):
    """House state override on the Presence Coordinator device.

    Entity: select.ura_presence_house_state_override
    Device: URA: Presence Coordinator
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_presence_house_state_override"
        self._attr_name = "House State Override"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )


# ============================================================================
# v3.6.0-c1: Zone Presence Mode Select (future — added per zone device)
# ============================================================================

class ZonePresenceModeSelect(SelectEntity):
    """Zone presence mode override on a zone device.

    Entity: select.ura_{zone_name}_presence_mode
    Device: URA: Zone {zone_name}
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:map-marker-radius"
    _attr_options = ZONE_PRESENCE_OVERRIDE_OPTIONS

    def __init__(
        self,
        hass: HomeAssistant,
        zone_name: str,
        zone_identifier: str,
    ) -> None:
        """Initialize."""
        self.hass = hass
        self._zone_name = zone_name
        zone_slug = zone_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{DOMAIN}_{zone_slug}_presence_mode"
        self._attr_name = f"{zone_name} Presence Mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, zone_identifier)},
        )

    @property
    def current_option(self) -> str:
        """Return current zone presence mode."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "auto"
        presence = manager.coordinators.get("presence")
        if presence is None:
            return "auto"
        tracker = presence.zone_trackers.get(self._zone_name)
        if tracker is None:
            return "auto"
        if tracker.is_overridden:
            return tracker._override or "auto"
        return "auto"

    async def async_select_option(self, option: str) -> None:
        """Set zone presence mode override."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        presence = manager.coordinators.get("presence")
        if presence is None:
            return
        tracker = presence.zone_trackers.get(self._zone_name)
        if tracker is None:
            _LOGGER.warning("No zone tracker for: %s", self._zone_name)
            return

        tracker.set_override(option)
        self.async_write_ha_state()
        _LOGGER.info(
            "Zone %s presence mode set to: %s",
            self._zone_name, option,
        )


# ============================================================================
# v4.6.2 D6 — Routine Notification Mode Select
# ============================================================================


class RoutineNotificationModeSelect(SelectEntity):
    """Select entity controlling how routine shift events are notified.

    Entity: select.ura_coordinator_manager_routine_change_notification_mode
    Device: URA: Coordinator Manager

    Options:
      silent       — no notifications (default; use during 4-6 week warm-up)
      weekly_digest — enqueue events; flush in one digest Sunday 09:00
      event        — notify per-event subject to cooldown + severity floor

    The chosen mode is persisted to entry.options under
    CONF_ROUTINE_CHANGE_NOTIFICATION_MODE so it survives restart. The
    NotificationManager reads this at signal-dispatch time; no restart needed
    after a mode change.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-ring-outline"
    _attr_options = ["silent", "weekly_digest", "event"]

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        from .const import CONF_ROUTINE_CHANGE_NOTIFICATION_MODE, VERSION
        self._conf_key = CONF_ROUTINE_CHANGE_NOTIFICATION_MODE
        self._attr_unique_id = f"{DOMAIN}_routine_change_notification_mode"
        self._attr_name = "Routine Change Notification Mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )
        merged = {**entry.data, **entry.options}
        self._current = merged.get(self._conf_key, "silent")

    @property
    def current_option(self) -> str:
        """Return current notification mode."""
        return self._current

    async def async_select_option(self, option: str) -> None:
        """Persist mode change to entry.options and update HA state."""
        from .const import CONF_ROUTINE_CHANGE_NOTIFICATION_MODE
        self._current = option
        new_options = {**self._entry.options, CONF_ROUTINE_CHANGE_NOTIFICATION_MODE: option}
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        self.async_write_ha_state()
        _LOGGER.info("Routine change notification mode set to: %s", option)


# ============================================================================
# v4.7.34 Phase 1 D7: OptimizerAutonomyLevelSelect
#   + Pillar B (Phase 5) D2/D6: plain-English labels + confirm-guard
# ============================================================================
#
# Pillar B D2: the six raw `OPTIMIZER_LEVEL_*` tokens stay as the persisted
# values (no migration). The dropdown carries plain-English labels via the
# `entity.select.optimizer_autonomy_level.state.*` translation keys.
#
# Pillar B D6 (confirm-guard): selecting a rung that ranks >= L2
# (reversible_device) from L0 (advisory) or L1 (shadow), or any UPWARD
# escalation, does NOT commit immediately. The select writes the
# *requested* rung to `CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL` on the CM
# entry options, exposes the local state as `pending_<target>`, and waits
# for the operator to press `OptimizerConfirmEscalationButton`. The
# coordinator NEVER reads the pending key — `effective_level` still reads
# only `CONF_OPTIMIZER_AUTONOMY_LEVEL` (see plan D6). De-escalations
# (lower-rank → higher OR any → lower) commit IMMEDIATELY and strip any
# stale pending key.
#
# Restart resilience: the pending key is persisted on `entry.options` so
# a restart restores the same pending state. Kill-switch ENGAGE strips
# the pending key (`OptimizerKillSwitch.async_turn_on`).


_PENDING_PREFIX = "pending_"


def _is_pending_option(option: str) -> bool:
    """Return True if ``option`` is a `pending_<level>` token."""
    return isinstance(option, str) and option.startswith(_PENDING_PREFIX)


def _pending_target(option: str) -> str:
    """Return the underlying level for a `pending_<level>` token."""
    return option[len(_PENDING_PREFIX):] if _is_pending_option(option) else option


class OptimizerAutonomyLevelSelect(SelectEntity):
    """Six-rung autonomy ladder selector with confirm-guard.

    Options (lowest → highest, raw values — labels live in translations):
        advisory | shadow | reversible_device | propose_config |
        immediate_config | unbounded

    Default = ``shadow`` (Phase 1 ship default — L1 dry-run with NO real
    actuation). Persistence is via entry.options write-back (single source
    of truth, Bug Class #46-safe).

    Confirm-guard (Pillar B D2/D6): UPWARD jumps to L2+ stage a pending
    value rather than committing. See module-level comment.

    Entity: select.ura_optimizer_autonomy_level
    Device: URA: Optimization Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:tune-vertical"
    _attr_translation_key = "optimizer_autonomy_level"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        from homeassistant.helpers.entity import EntityCategory
        from .const import (
            CONF_OPTIMIZER_AUTONOMY_LEVEL,
            CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL,
            DEFAULT_OPTIMIZER_AUTONOMY_LEVEL,
            OPTIMIZER_AUTONOMY_LEVELS,
        )
        self.hass = hass
        self._entry = entry
        self._conf_key = CONF_OPTIMIZER_AUTONOMY_LEVEL
        self._pending_key = CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL
        self._default = DEFAULT_OPTIMIZER_AUTONOMY_LEVEL
        # `_attr_options` must contain every value `current_option` can
        # return (HA SelectEntity contract). We include the 6 real rungs
        # AND every `pending_<level>` so the entity state stays valid
        # while an escalation is staged. The dropdown picker is meant to
        # be driven from the labelled rungs; selecting a `pending_*`
        # token via the UI is a no-op (see `async_select_option`).
        self._attr_options = list(OPTIMIZER_AUTONOMY_LEVELS) + [
            f"{_PENDING_PREFIX}{lvl}" for lvl in OPTIMIZER_AUTONOMY_LEVELS
        ]
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_unique_id = f"{DOMAIN}_optimizer_autonomy_level"
        self._attr_name = "Autonomy Level"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "optimization_coordinator")},
            name="URA: Optimization Coordinator",
            manufacturer="Universal Room Automation",
            model="Optimization Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # Seed from options first, then data, then default. Pending key
        # is checked first — if a pending escalation persists across a
        # restart the state should reflect that, NOT the real rung.
        opts = entry.options or {}
        data = entry.data or {}
        pending = opts.get(self._pending_key)
        if pending in OPTIMIZER_AUTONOMY_LEVELS:
            self._attr_current_option = f"{_PENDING_PREFIX}{pending}"
        elif self._conf_key in opts and opts[self._conf_key] in OPTIMIZER_AUTONOMY_LEVELS:
            self._attr_current_option = opts[self._conf_key]
        elif self._conf_key in data and data[self._conf_key] in OPTIMIZER_AUTONOMY_LEVELS:
            self._attr_current_option = data[self._conf_key]
        else:
            self._attr_current_option = self._default

    @property
    def current_option(self) -> str:
        return self._attr_current_option

    @property
    def available(self) -> bool:
        return True

    @property
    def extra_state_attributes(self) -> dict:
        """Expose pending target (if any) for dashboards / automations."""
        opts = self._entry.options or {}
        pending = opts.get(self._pending_key)
        committed = opts.get(self._conf_key, self._default)
        return {
            "committed_level": committed,
            "pending_level": pending,
        }

    def _committed_level(self) -> str:
        """Return the most-recently committed real rung (post-pending)."""
        from .const import OPTIMIZER_AUTONOMY_LEVELS
        opts = self._entry.options or {}
        committed = opts.get(self._conf_key)
        if committed in OPTIMIZER_AUTONOMY_LEVELS:
            return committed
        data = self._entry.data or {}
        committed = data.get(self._conf_key)
        if committed in OPTIMIZER_AUTONOMY_LEVELS:
            return committed
        return self._default

    def _rank(self, level: str) -> int:
        from .const import OPTIMIZER_LEVEL_RANK
        return OPTIMIZER_LEVEL_RANK.get(level, 0)

    def _write_options(self, *, real: str | None = None,
                       pending: str | None = "__keep__") -> None:
        """Mutate entry.options atomically.

        ``real``: when non-None, set `CONF_OPTIMIZER_AUTONOMY_LEVEL`.
        ``pending``: when ``None`` strip the pending key; the sentinel
        ``"__keep__"`` leaves it alone; any string sets it.
        """
        try:
            options = dict(self._entry.options or {})
            if real is not None:
                options[self._conf_key] = real
            if pending is None:
                options.pop(self._pending_key, None)
            elif pending != "__keep__":
                options[self._pending_key] = pending
            self.hass.config_entries.async_update_entry(
                self._entry, options=options,
            )
        except Exception:  # noqa: BLE001 — never crash UI
            _LOGGER.debug(
                "Optimizer autonomy level options write-back failed",
                exc_info=True,
            )

    async def async_select_option(self, option: str) -> None:
        """Handle a UI / service-call selection.

        Routing (Pillar B fix-up A-M4 — confirm-guard scope narrowed):
          - Selecting a ``pending_<level>`` token routes through to the
            underlying level (M5 fix: was a silent no-op, now treated as
            equivalent to selecting ``<level>`` directly).
          - Selecting a LOWER-or-EQUAL rank commits immediately (any
            de-escalation, including L1→L0 or L0→L0).
          - Selecting a HIGHER rank that is BELOW L2 (reversible_device)
            commits immediately. advisory↔shadow moves do NOT stage —
            those are no-actuation rungs and the confirm-guard is only
            warranted once we cross into real-actuation territory.
          - Selecting a rank >= L2 stages as pending (confirm-guard).
        """
        from .const import OPTIMIZER_AUTONOMY_LEVELS, OPTIMIZER_LEVEL_RANK
        if option not in self._attr_options:
            _LOGGER.warning(
                "OptimizerAutonomyLevelSelect: unknown option %s", option,
            )
            return
        if _is_pending_option(option):
            # Pillar B fix-up A-M5: selecting a `pending_<level>` token
            # via the dropdown maps through to the underlying level so
            # the dropdown is not "stuck" with a useless option. HA
            # requires `state ∈ options` while a pending escalation is
            # staged, but operator-initiated re-selection of the pending
            # token should behave the same as picking the bare level.
            option = _pending_target(option)
            if option not in OPTIMIZER_AUTONOMY_LEVELS:
                _LOGGER.debug(
                    "Pending token mapped to unknown level, ignoring",
                )
                return
        if option not in OPTIMIZER_AUTONOMY_LEVELS:
            return

        committed = self._committed_level()
        requested_rank = self._rank(option)
        committed_rank = self._rank(committed)
        # L2 = reversible_device rank — confirm-guard threshold.
        l2_rank = OPTIMIZER_LEVEL_RANK.get("reversible_device", 2)

        if requested_rank <= committed_rank:
            # De-escalation (or no-op): commit immediately and strip any
            # stale pending key.
            self._write_options(real=option, pending=None)
            self._attr_current_option = option
            _LOGGER.info(
                "Optimizer autonomy level set to %s (immediate, "
                "de-escalation from %s)",
                option, committed,
            )
        elif requested_rank < l2_rank:
            # Upward escalation BELOW the confirm-guard threshold (i.e.
            # advisory ↔ shadow only — both no-actuation rungs). Commit
            # immediately and strip any stale pending key.
            self._write_options(real=option, pending=None)
            self._attr_current_option = option
            _LOGGER.info(
                "Optimizer autonomy level set to %s (immediate, "
                "below-L2 escalation from %s)",
                option, committed,
            )
        else:
            # Upward escalation TO L2+: stage as pending. The coordinator
            # NEVER reads the pending key — `effective_level` keeps using
            # the committed value until the confirm button fires.
            self._write_options(pending=option)
            self._attr_current_option = f"{_PENDING_PREFIX}{option}"
            _LOGGER.info(
                "Optimizer autonomy level escalation PENDING %s "
                "(committed=%s, press Confirm to apply)",
                option, committed,
            )
        self.async_write_ha_state()

    @callback
    def _refresh_from_options(self) -> None:
        """Reconcile local state with the latest entry.options.

        Called by the Confirm / Cancel buttons (and on options update)
        so the entity's reported state reflects the post-button-press
        truth without waiting for a config-entry reload.
        """
        from .const import OPTIMIZER_AUTONOMY_LEVELS
        opts = self._entry.options or {}
        pending = opts.get(self._pending_key)
        if pending in OPTIMIZER_AUTONOMY_LEVELS:
            self._attr_current_option = f"{_PENDING_PREFIX}{pending}"
        else:
            self._attr_current_option = self._committed_level()
        try:
            self.async_write_ha_state()
        except Exception:  # noqa: BLE001 — during teardown
            pass

    async def async_added_to_hass(self) -> None:
        """Register this instance so the OC buttons can refresh us.

        Stored at ``hass.data[DOMAIN]["optimizer_autonomy_select"]`` —
        a single-instance slot since the integration only ever wires one
        Optimization Coordinator.
        """
        await super().async_added_to_hass()
        try:
            self.hass.data.setdefault(DOMAIN, {})[
                "optimizer_autonomy_select"
            ] = self
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "OptimizerAutonomyLevelSelect: registry slot store failed",
                exc_info=True,
            )

    async def async_will_remove_from_hass(self) -> None:
        """Clear the registry slot on remove to avoid stale references."""
        try:
            slot = self.hass.data.get(DOMAIN, {})
            if slot.get("optimizer_autonomy_select") is self:
                slot.pop("optimizer_autonomy_select", None)
        except Exception:  # noqa: BLE001
            pass
        await super().async_will_remove_from_hass()


# ============================================================================
# v5.7.1 — Energy Saver Pre-Cool Scope (EC device)
# ----------------------------------------------------------------------------
# Three-value selector wired to EnergyCoordinator.energy_precool_scope.
# entry.options is the SOLE source of truth (mirror of OffPeakDrainNumber /
# PeakBufferTargetNumber pattern — no RestoreEntity). Setter pushes the new
# value to EC BEFORE async_update_entry so the next HVAC decision cycle sees
# the new scope immediately. Restart re-seeds via __init__'s config read.
# Invalid restored / configured values fall back to DEFAULT_ENERGY_PRECOOL_SCOPE.
# ============================================================================


class EnergyPreCoolScopeSelect(SelectEntity):
    """Select entity for Energy Saver Pre-Cool scope."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-thermometer-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.entity import EntityCategory
        from .domain_coordinators.hvac_const import (
            CONF_ENERGY_PRECOOL_SCOPE,
            DEFAULT_ENERGY_PRECOOL_SCOPE,
            ENERGY_PRECOOL_SCOPE_VALUES,
        )
        self.hass = hass
        self._entry = entry
        self._conf_key = CONF_ENERGY_PRECOOL_SCOPE
        self._attr_options = list(ENERGY_PRECOOL_SCOPE_VALUES)
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_unique_id = f"{DOMAIN}_energy_energy_precool_scope"
        self._attr_name = "Energy Saver Pre-Cool Scope"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        merged = {**entry.data, **entry.options}
        raw = merged.get(self._conf_key, DEFAULT_ENERGY_PRECOOL_SCOPE)
        if raw not in ENERGY_PRECOOL_SCOPE_VALUES:
            raw = DEFAULT_ENERGY_PRECOOL_SCOPE
        self._current = raw

    def _get_energy(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    @property
    def current_option(self) -> str:
        return self._current

    @property
    def available(self) -> bool:
        return self._get_energy() is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        energy = self._get_energy()
        if energy is not None:
            try:
                energy.energy_precool_scope = self._current
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Energy Saver Pre-Cool Scope: seed-push deferred",
                )

    async def async_select_option(self, option: str) -> None:
        from .domain_coordinators.hvac_const import (
            CONF_ENERGY_PRECOOL_SCOPE,
            DEFAULT_ENERGY_PRECOOL_SCOPE,
            ENERGY_PRECOOL_SCOPE_VALUES,
        )
        if option not in ENERGY_PRECOOL_SCOPE_VALUES:
            option = DEFAULT_ENERGY_PRECOOL_SCOPE
        self._current = option
        energy = self._get_energy()
        if energy is not None:
            energy.energy_precool_scope = option
        try:
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **self._entry.options,
                    CONF_ENERGY_PRECOOL_SCOPE: option,
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Energy Saver Pre-Cool Scope: options-writeback failed",
                exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info("Energy Saver Pre-Cool Scope set to: %s", option)


class DrainPrecedenceHouseLoadSourceSelect(SelectEntity):
    """Select entity for EVSE Drain-Precedence house-load source (plan §80).

    Options: "max_span_r1" | "live_span" | "r1_base". Ratification §257
    picks `max_span_r1` (conservative blend) as ship default; the others
    are opt-in for probe re-runs. `entry.options` is the sole source of
    truth (mirrors EnergyPreCoolScopeSelect above — no RestoreEntity).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-lightning-bolt-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.entity import EntityCategory
        from .domain_coordinators.energy_const import (
            CONF_ENERGY_DP_HOUSE_LOAD_SOURCE,
            CONF_DP_HOUSE_LOAD_SOURCE as _DEFAULT,
            DP_HOUSE_LOAD_SOURCES,
        )
        self.hass = hass
        self._entry = entry
        self._conf_key = CONF_ENERGY_DP_HOUSE_LOAD_SOURCE
        self._default = _DEFAULT
        self._valid = tuple(DP_HOUSE_LOAD_SOURCES)
        self._attr_options = list(DP_HOUSE_LOAD_SOURCES)
        # v5.21.0 BAEC control-surface consolidation: retire from device
        # page (options-flow is primary write path); demote to DIAGNOSTIC
        # + disabled-by-default. Bug Class #46 avoidance: disable, not
        # delete; re-enabling restores round-trip.
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_entity_registry_enabled_default = False
        self._attr_unique_id = f"{DOMAIN}_energy_dp_house_load_source"
        self._attr_name = "Overnight house load estimate"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        merged = {**entry.data, **entry.options}
        raw = merged.get(self._conf_key, self._default)
        if raw not in self._valid:
            raw = self._default
        self._current = raw

    def _get_energy(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    @property
    def current_option(self) -> str:
        return self._current

    @property
    def available(self) -> bool:
        return self._get_energy() is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        energy = self._get_energy()
        if energy is not None:
            try:
                energy.set_dp_house_load_source(self._current)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "DP House Load Source: seed-push deferred",
                )

    async def async_select_option(self, option: str) -> None:
        if option not in self._valid:
            option = self._default
        self._current = option
        energy = self._get_energy()
        if energy is not None:
            try:
                energy.set_dp_house_load_source(option)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "DP House Load Source: setter raised", exc_info=True,
                )
        try:
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={**self._entry.options, self._conf_key: option},
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "DP House Load Source: options-writeback failed", exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info("DP House Load Source set to: %s", option)
