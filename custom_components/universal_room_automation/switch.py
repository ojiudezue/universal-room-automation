"""Switch platform for Universal Room Automation."""
#
# Universal Room Automation vv5.92.0
# Build: 2026-01-02
# File: switch.py
#
# 2026-08-23: PEP-604 unions (`str | None`) appear in annotations here. Without
# this future import those annotations are EVALUATED at def time, which raises
# on Python 3.9 — the version the local quality suite runs (production HA is on
# 3.14, where it is fine). This was the only file in the integration still
# missing it; the other 90 already carry it. PEP 563 stringification is safe
# here: nothing in this module reads __annotations__ or calls get_type_hints.

from __future__ import annotations

import logging
from typing import Any

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
    CONF_NM_DRY_RUN,
    CONF_NM_ENABLED,
    DEFAULT_NM_DRY_RUN,
    CONF_PRESENCE_ENABLED,
    CONF_SAFETY_ENABLED,
    CONF_SECURITY_ENABLED,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_INTEGRATION,
    VERSION,
    # CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 (2026-08-18):
    CONF_FACE_RECOGNITION_ENABLED,
    CONF_EGRESS_IDENTITY_ENABLED,
    DEFAULT_FACE_RECOGNITION_ENABLED,
    DEFAULT_EGRESS_IDENTITY_ENABLED,
    SIGNAL_URA_FACE_RECOGNITION_CHANGED,
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


def _cleanup_solar_banking_orphan(hass: HomeAssistant) -> None:
    """v5.7.1: Remove the orphan ECSolarBankingSwitch from the entity registry.

    The Solar HVAC Banking toggle was RETIRED in v5.7.1 (folded into
    Energy Saver Pre-Cool). The new switch uses a different unique_id
    (`{DOMAIN}_energy_energy_precool`), so the old `solar_banking`
    entity becomes an unavailable orphan on upgrade. Remove it once.

    Idempotent: subsequent runs find no orphan and no-op. Guarded with a
    small marker in hass.data so it does not loop on reload within the
    same process lifetime.

    Bug Class #46-safe: calls entity_registry.async_remove(), not
    async_update_entry.

    B-RE-2 (v5.7.1 re-review): cross-entry setup order is non-deterministic.
    The integration-entry migration (`_migrate_solar_banking_to_energy_precool`
    in __init__.py) MUST read RestoreEntity state for this orphan BEFORE we
    remove the registry entry — otherwise the migration cannot look up the
    entity_id and `restore_off` defaults to False, silently re-enabling an
    operator-explicit OFF. The migration sets `solar_banking_cleanup_done`
    after its own read+remove, so this function becomes a no-op backstop
    once the migration has run on any integration entry.
    """
    if hass.data.setdefault(DOMAIN, {}).get(
        "solar_banking_cleanup_done"
    ):
        return
    try:
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(hass)
        legacy_unique_id = f"{DOMAIN}_energy_solar_banking"
        # entity_registry has no by-unique_id index; scan switch domain.
        for ent in list(registry.entities.values()):
            if ent.domain == "switch" and ent.unique_id == legacy_unique_id:
                registry.async_remove(ent.entity_id)
                _LOGGER.info(
                    "v5.7.1: removed orphan Solar HVAC Banking switch %s "
                    "(unique_id=%s) — replaced by Energy Saver Pre-Cool",
                    ent.entity_id, legacy_unique_id,
                )
                break
        hass.data[DOMAIN]["solar_banking_cleanup_done"] = True
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "v5.7.1 solar_banking orphan cleanup failed (non-fatal)",
            exc_info=True,
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
        # CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 (2026-08-18): expose the
        # two census-adjacent flags as device switches on the
        # integration device. Both write to entry.options; the parent
        # entry does NOT reload because both keys are in
        # INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS. Face-recognition
        # fires SIGNAL_URA_FACE_RECOGNITION_CHANGED to refresh the
        # cached consumers (transit_validator + presence). Egress
        # identity is fresh-read at all consumers — no signal.
        async_add_entities([
            DomainCoordinatorsSwitch(hass, entry),
            _IntegrationOptionsSwitch(
                hass, entry,
                conf_key=CONF_FACE_RECOGNITION_ENABLED,
                default=DEFAULT_FACE_RECOGNITION_ENABLED,
                translation_key="presence_face_matching",
                fallback_name="Presence Face Matching",
                object_id="ura_presence_face_matching",
                unique_suffix="presence_face_matching",
                icon="mdi:face-recognition",
                fire_signal=SIGNAL_URA_FACE_RECOGNITION_CHANGED,
            ),
            _IntegrationOptionsSwitch(
                hass, entry,
                conf_key=CONF_EGRESS_IDENTITY_ENABLED,
                default=DEFAULT_EGRESS_IDENTITY_ENABLED,
                translation_key="name_people_at_doors",
                fallback_name="Name People at Doors",
                object_id="ura_name_people_at_doors",
                unique_suffix="name_people_at_doors",
                icon="mdi:badge-account-horizontal",
                fire_signal=None,
            ),
        ])
        return

    if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:
        # v4.7.6 D3.1: one-shot entity_id alias migration (Bug Class #46-safe).
        try:
            _migrate_excess_solar_entity_id(hass, entry)
        except Exception:
            _LOGGER.debug("v4.7.6 alias migration failed (non-fatal)", exc_info=True)
        _cleanup_solar_banking_orphan(hass)  # v5.7.1 orphan cleanup
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
            # Exterior track linker control surface (2026-08-06, operator-named)
            ExteriorPathTrackingSwitch(hass, entry),
            PathAwareNotificationsSwitch(hass, entry),
            # NM Cycle B (2026-07-20) B0: minimal dry-run gate. When ON,
            # every emit-path service call is short-circuited to a
            # `notification_log` dry-run row. Enables safe live exercise
            # of CRITICAL machinery without real outbound sends.
            NMDryRunSwitch(hass, entry),
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
            ECDrainPrecedenceEnableSwitch(hass, entry),  # Session B1
            # evse-charge-onset Rev 6 D-A — overnight charge-onset enable.
            ECEVChargeOnsetEnabledSwitch(hass, entry),
            ECEvTouSwitch(hass, entry),
            # v5.7.1 — Energy Saver Pre-Cool master toggle (EC device).
            # Replaces the retired ECSolarBankingSwitch; gates the unified
            # PV-aware energy-pre-cool branch in HVACPredictor.
            ECEnergyPreCoolSwitch(hass, entry),
            # v4.7.2 D2: Dynamic Preset master kill switch (migrated to HVAC device)
            HVACDynamicPresetSwitch(hass, entry),
            # v4.7.1 fix-up D3 / v4.7.2 D3: Custom Preset Ranges master toggle (HVAC device)
            HVACGuestModeActuationSwitch(hass, entry),
            # HVAC-PRESET-FLAP-1 D4 (2026-08-11): Duty Off-Phase Honesty
            # kill-switch. Default ON. OFF => D5 else-limb falls through
            # to the pre-cycle `preset=away` path (byte-identical restore).
            HvacOffphaseHonestyEnabledSwitch(hass, entry),
            # HC Pre-Conditioning master kill switch. Parent gate for
            # weather pre-cool + solar banking + pre-arrival + pre-heat.
            # Default ON. See PLANNING_hc_precool_toggle_oc_observability.md.
            HVACPreConditioningSwitch(hass, entry),
            # v3.9.0: HVAC transparency switches
            HVACOverrideArresterSwitch(hass, entry),
            # Arrester Operator-Immunity (2026-08-06). Temp Arrester
            # Override — arrester-scoped temporary stand-down: suspends
            # ALL arrester corrective writes house-wide for the
            # operator's "please leave me alone" case. Default OFF;
            # deliberately NOT restored across restart (default-OFF is
            # the safe state); auto-sunsets on sleep transition or
            # max-age. Operator naming ruling 2026-08-06 (arrester
            # family; NOT "Comfort Override" — that would suggest a
            # comfort dial, this is an override of arrester governance).
            HVACTempArresterOverrideSwitch(hass, entry),
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
            # build/pc-observability: three P1 presence kill switches.
            # All default ON; each is load-bearing at a specific decision
            # path (see class docstring for citation).
            PresenceGuestDetectionEnabledSwitch(hass, entry),
            PresenceArrivingRearmEnabledSwitch(hass, entry),
            PresenceAwayVetoEnabledSwitch(hass, entry),
            # v4.7.34 Phase 1 D7: Optimization Coordinator kill switch
            # (restart-persistent via entry.options write-back AND
            # RestoreEntity; modeled on EnergyObservationModeSwitch:396).
            OptimizerKillSwitch(hass, entry),
            # Hierarchical Memory MVP Stage 1 — NM severity-conditioning
            # runtime gate. Default ON. When OFF, NM conditioning is a
            # byte-identical no-op regardless of MEMORY_NM_CONDITIONING_
            # ENABLED (code const is master). Kill-switch semantics:
            # OFF here = feature disabled at runtime; const False =
            # feature dead in the build.
            MemoryNMConditioningSwitch(hass, entry),
        ])
        # v5.10.0 D5: per-person MF DND switches. Read tracked_persons
        # from the INTEGRATION entry (source of truth for persons).
        try:
            person_switches = _build_per_person_mf_switches(hass, entry)
            if person_switches:
                async_add_entities(person_switches)
        except Exception:
            _LOGGER.debug(
                "v5.10.0 per-person MF switch registration failed (non-fatal)",
                exc_info=True,
            )
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
        # D6 (bathroom-exhaust intelligence cycle): per-room mirrors of
        # options-flow toggles #2 (comfort) and #3 (humidity).
        RoomComfortFanControlSwitch(coordinator),
        RoomHumidityFanControlSwitch(coordinator),
        # v5.8.0 D2.12: reconcile-on-return per-room gate (guard 9). Default ON.
        AutoRecoverySwitch(coordinator),
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
# CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 (2026-08-18)
# Integration-entry options-backed switches (face_recognition, egress_identity)
# ============================================================================


class _IntegrationOptionsSwitch(SwitchEntity):
    """A switch that reads/writes a boolean key in the INTEGRATION entry's options.

    Kill-switch semantics: `is_on` reflects the merged options value;
    toggling persists via `async_update_entry` on the integration entry.

    Load-bearing invariant: this class does NOT call `async_reload`.
    Reload is short-circuited by the
    `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` branch in
    `__init__._async_update_listener`. Belt-and-suspenders discharge:
    when `fire_signal` is set, the signal is dispatched from `_write`
    AFTER the persistence returns AND ALSO from
    `_dispatch_integration_key_signals` via `_INTEGRATION_KEY_SIGNAL_TABLE`
    a moment later — subscribers re-read the same fresh value both
    times; harmless idempotent.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        conf_key: str,
        default: bool,
        translation_key: str,
        fallback_name: str,
        object_id: str,
        unique_suffix: str,
        icon: str,
        fire_signal: str | None,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._conf_key = conf_key
        self._default = default
        self._fire_signal = fire_signal
        # MED-3 (Review C, 2026-08-18): translation_key is the canonical
        # source of the visible name via strings.json / translations/en.json;
        # _attr_name is set as an EXPLICIT fallback so a translation-load
        # failure (missing locale file, JSON parse error) still yields a
        # human-readable label instead of an entity_id-shaped one. The two
        # must be kept semantically equivalent; drift here is a UI-truth
        # defect (same class as HIGH-1 / HIGH-2 in this cycle's review).
        self._attr_translation_key = translation_key
        self._attr_name = fallback_name
        self._attr_icon = icon
        self._attr_unique_id = f"{DOMAIN}_{unique_suffix}"
        # Pin entity_id so friendly-name auto-slug drift cannot rename it.
        self.entity_id = f"switch.{object_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "integration")},
            name="Universal Room Automation",
            manufacturer="Universal Room Automation",
            model="Whole House",
            sw_version=VERSION,
        )

    @property
    def is_on(self) -> bool:
        merged = {**self._entry.data, **self._entry.options}
        return bool(merged.get(self._conf_key, self._default))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write(False)

    async def _write(self, value: bool) -> None:
        old = self.is_on
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, self._conf_key: value},
        )
        self.async_write_ha_state()
        _LOGGER.info(
            "IntegrationOptionsSwitch: %s %s → %s (entry=%s)",
            self._conf_key, old, value, self._entry.entry_id,
        )
        # Belt-and-suspenders discharge. The listener also fires this
        # signal via _INTEGRATION_KEY_SIGNAL_TABLE; both subscribers
        # re-read the same fresh entry.options value, so a double-fire
        # is a no-op. Fires here first so a subscriber connecting
        # between async_update_entry and the listener still transitions.
        if self._fire_signal is not None:
            try:
                from homeassistant.helpers.dispatcher import (  # noqa: PLC0415
                    async_dispatcher_send,
                )
                async_dispatcher_send(
                    self.hass, self._fire_signal,
                    self._entry.entry_id, self._conf_key,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "IntegrationOptionsSwitch: dispatch of %s failed (non-fatal)",
                    self._fire_signal, exc_info=True,
                )


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


class MemoryNMConditioningSwitch(SwitchEntity, RestoreEntity):
    """Hierarchical Memory MVP Stage 1 — runtime gate for NM severity
    conditioning consumer.

    Entity: switch.ura_memory_nm_conditioning
    Device: URA: Coordinator Manager
    Default: ON. When OFF, NM behaves byte-identically to today
    (no memory-driven demotion, no facade calls from the NM path).

    Kill-switch semantics: this switch is the operator-facing runtime
    gate. The module-level ``MEMORY_NM_CONDITIONING_ENABLED`` constant
    is the code-level master. BOTH must be True for conditioning to
    fire; either False disables it.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:brain"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_memory_nm_conditioning"
        self._attr_name = "Memory NM Conditioning"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )
        self._is_on = True  # default ON

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._is_on = last_state.state == "on"



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

        def _register_for_restore_accounting(self) -> None:
            """Register this switch with EC's dynamic restore-accounting.

            Idempotent. Boot-decoupling C7 fix — replaces the hardcoded
            pending-count 6. Called at async_added_to_hass AND from
            _handle_ec_ready so the count is in regardless of whether EC
            was registered at platform-setup time.
            """
            energy = self._get_energy()
            if energy is None:
                return
            try:
                energy.register_sub_switch_for_restore_accounting(
                    unique_suffix,
                )
            except Exception:  # noqa: BLE001
                pass

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

            # v5.21.0 fix-up (B-HIGH-1): subscribe to SIGNAL_ENERGY_ENTITIES_UPDATE
            # so options-flow writes that route through `_EC_SETTER_DISPATCH`
            # (e.g. `_CONF_ENERGY_DP_ENABLE`) can push a state refresh here.
            # `is_on` reads live from the coordinator attr, so calling
            # `async_write_ha_state()` immediately reflects the new value —
            # no attribute mirror required. Bug Class #38: unsub tracked via
            # `async_on_remove`. Kept as a separate single-line import so the
            # test_envoy_boot_decoupling extractor's string-replace anchor for
            # `SIGNAL_ENERGY_COORDINATOR_READY` above stays a byte match.
            from .domain_coordinators.signals import SIGNAL_ENERGY_ENTITIES_UPDATE
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    SIGNAL_ENERGY_ENTITIES_UPDATE,
                    self._handle_entities_update,
                )
            )

            # Register for dynamic restore-accounting (C7). Safe-noop if
            # EC not yet present; _handle_ec_ready re-attempts.
            self._register_for_restore_accounting()

            last_state = await self.async_get_last_state()
            if last_state is None:
                # First-time install (no prior RestoreEntity state):
                # the constructor's `ec.get(...)` seed is the source of
                # truth.  Review D D2 fix (2026-06-12):
                # `_register_for_restore_accounting()` above incremented
                # the EC pending-restore counter for this switch; without
                # a corresponding notify the counter is stuck >0 for the
                # whole runtime and `ECSubSwitchesSyncedSensor` (PROBLEM
                # device_class) stays True until the next restart on
                # fresh installs / first boot after a new sub-switch is
                # added.  Same semantics as the Bug Class #52 skip path
                # below: seed is authoritative → restore is COMPLETE.
                _energy_for_notify = self._get_energy()
                if _energy_for_notify is not None:
                    try:
                        _energy_for_notify.notify_sub_switch_restore_complete()
                    except Exception:  # noqa: BLE001
                        pass
                return
            # Bug Class #52 — RestoreEntity unavailable-coercion.
            # Skip restore when last_state is `unavailable`/`unknown` (or
            # anything other than the canonical on/off). Falling through
            # to `target = last_state.state == "on"` would coerce these
            # to False, then setattr False onto the coordinator and
            # silently clobber the options-seeded value. Treat this case
            # like first-install: constructor/options seed wins, no
            # deferred restore is scheduled (the chain ends here).
            if last_state.state not in ("on", "off"):
                _LOGGER.info(
                    "Skipping RestoreEntity restore for %s — "
                    "last_state=%s — keeping options-seeded value %s",
                    unique_suffix,
                    last_state.state,
                    getattr(
                        self._get_energy(), attr_name, self._default,
                    ),
                )
                # C1 fix: skip means the constructor/options seed is the
                # authoritative value — restore is COMPLETE, not pending.
                # Notify the sub-switch accounting so
                # ECSubSwitchesSyncedSensor converges; otherwise the
                # PROBLEM device_class sensor stays True forever on the
                # boot immediately after a poisoned restore (all 6 EC
                # sub-switches restoring as "unavailable" → all skip →
                # counter never reaches 0 without this notify).
                _energy_for_notify = self._get_energy()
                if _energy_for_notify is not None:
                    try:
                        _energy_for_notify.notify_sub_switch_restore_complete()
                    except Exception:  # noqa: BLE001
                        pass
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
        def _handle_entities_update(self, *_args, **_kwargs) -> None:
            """v5.21.0 (B-HIGH-1): refresh entity state after an EC-setter
            options-flow write. `is_on` reads the live coord attr; this
            just tells HA to re-poll it. Safe no-op if entity isn't
            fully added yet (`hass` present + platform assigned).
            """
            if self.hass is None or getattr(self, "platform", None) is None:
                return
            self.async_write_ha_state()

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
            # Late-register for restore accounting if EC wasn't present at
            # async_added_to_hass time (C7).
            self._register_for_restore_accounting()
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
                # Late-register for restore accounting if EC came up after
                # async_added_to_hass (C7).
                self._register_for_restore_accounting()
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

# Session B1 — EVSE Drain-Precedence master kill switch.
# Attr `_dp_enabled` on EnergyCoordinator (seeded from
# `CONF_ENERGY_DP_ENABLE` in entry.options; default False = today's
# behavior, KILL: false disables all transition eval + actuation per
# plan §74). Factory RestoreEntity/timer/signal machinery gives us
# restart-safe restore identical to ECGridImportCapSwitch etc.
# evse-charge-onset Rev 6 D-A — dedicated enable toggle. Mirrors the
# ECDrainPrecedenceEnableSwitch pattern (RestoreEntity + deferred restore
# + SIGNAL_ENERGY_ENTITIES_UPDATE re-read comes for free via the
# factory). Coord attr `_ev_charge_onset_enabled` is fanned out from
# `EnergyCoordinator.set_ev_charge_onset_enabled` to BOTH controllers,
# so a toggle here lands on both EV and plug tiers. Ships DORMANT
# (default=False); operator flips on after live checkpoint.
#
# v3 fix-up B-CRIT-A: the bare factory writes the coord DISPLAY MIRROR
# via setattr and NEVER calls `set_ev_charge_onset_enabled` — the drain
# gate reads the CONTROLLER attrs `_ev._ev_charge_onset_enabled` and
# `_smart_plugs._ev_charge_onset_enabled`, so a factory-only switch is
# an INERT kill switch. Subclass every write path (turn_on, turn_off,
# RestoreEntity fast-path, deferred-restore x2) to route through the
# coord setter so both controllers stay in lockstep.
_ECEVChargeOnsetEnabledBase = _ec_switch_factory(
    "_ev_charge_onset_enabled", "ev_charge_onset_enabled",
    "EV Charge Onset (Overnight)", "mdi:ev-station", default=False,
)


class ECEVChargeOnsetEnabledSwitch(_ECEVChargeOnsetEnabledBase):
    """v3 fix-up B-CRIT-A: route every write path through the coord setter.

    The base class's five setattr sites (turn_on, turn_off, RestoreEntity
    fast-path, two deferred-restore paths) all mutate the coord's
    display mirror only. This subclass overrides ONLY those write
    entry-points so the fan-out to sub-controllers actually happens.
    Read paths (`is_on`, availability, seed) are inherited unchanged.
    """

    def _route_to_setter(self, value: bool) -> None:
        energy = self._get_energy()
        if energy is None:
            return
        fn = getattr(energy, "set_ev_charge_onset_enabled", None)
        if callable(fn):
            fn(bool(value))
        else:
            # Fallback for pathological setups (coord missing setter
            # after a partial reload). Preserves baseline behavior.
            setattr(energy, "_ev_charge_onset_enabled", bool(value))

    async def async_turn_on(self, **kwargs):  # noqa: D401
        self._route_to_setter(True)
        self._deferred_restore = False
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):  # noqa: D401
        self._route_to_setter(False)
        self._deferred_restore = False
        self.async_write_ha_state()

    def _sync_after_restore(self) -> None:
        """Re-fan-out via the coord setter after any base-class restore
        write. The base setattr'd `_ev_charge_onset_enabled` on the coord;
        we then invoke the setter (idempotent) to propagate to both
        controllers. Cheap: two attribute assignments on live objects."""
        energy = self._get_energy()
        if energy is None:
            return
        try:
            fn = getattr(energy, "set_ev_charge_onset_enabled", None)
            current = getattr(energy, "_ev_charge_onset_enabled", False)
            if callable(fn):
                fn(bool(current))
        except Exception:  # noqa: BLE001
            pass

    async def async_added_to_hass(self):  # noqa: D401
        await super().async_added_to_hass()
        # RestoreEntity fast-path in the base sets attr; propagate.
        self._sync_after_restore()

    def _retry_restore(self, _now=None):  # noqa: D401
        # Re-entry guard mirrors the base factory pattern (see
        # test_low_cleanup.py::TestSwitchRestoreDeferredRetry). When
        # `_deferred_restore` is False the base already applied; skip.
        if not self._deferred_restore:
            return
        super()._retry_restore(_now)
        self._sync_after_restore()

    def _handle_ec_ready(self) -> None:  # noqa: D401
        super()._handle_ec_ready()
        self._sync_after_restore()


ECDrainPrecedenceEnableSwitch = _ec_switch_factory(
    "_dp_enabled", "drain_precedence_enable",
    # B2c-2 item 6 rename (operator ratification 2026-07-17, planning
    # doc §373): user-facing name is "Battery-Aware EV Charging"; internal
    # attr / unique_id / class name stay technical (`drain_precedence` /
    # `_dp_enabled` — DPM naming precedent).
    "Battery-Aware EV Charging", "mdi:battery-arrow-down", default=False,
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

# v5.7.1 — Energy Saver Pre-Cool master toggle (EC device).
# Replaces the v4.7-era ECSolarBankingSwitch (which is RETIRED — the
# `solar_banking` unique_id is cleaned up via _cleanup_solar_banking_orphan
# at platform setup, Bug Class #46-safe). Gates the unified PV-aware
# Energy Saver Pre-Cool branch in HVACPredictor._check_pre_conditioning.
# Default ON so installs that previously had banking ON keep the equivalent
# behavior post-upgrade; existing OFF state is migrated by async_migrate_entry.
# See PLANNING_v5.7.x_energy_pre_cool_unification.md (D2).
from .domain_coordinators.hvac_const import ENERGY_PRECOOL_NAME as _ENERGY_PRECOOL_NAME
ECEnergyPreCoolSwitch = _ec_switch_factory(
    "energy_precool_enabled",         # attr_name on EnergyCoordinator
    "energy_precool",                 # unique_id suffix → {DOMAIN}_energy_energy_precool
    _ENERGY_PRECOOL_NAME,             # "Energy Saver Pre-Cool"
    "mdi:snowflake-thermometer",      # icon
    default=True,                     # mirrors prior banking default
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

    def _register_for_restore_accounting(self) -> None:
        """Register this switch with EC's dynamic restore-accounting (C7).

        Idempotent — safe to call from async_added_to_hass and
        _handle_ec_ready / _retry_restore.
        """
        energy = self._get_energy()
        if energy is None:
            return
        try:
            energy.register_sub_switch_for_restore_accounting(
                "hvac_dynamic_preset",
            )
        except Exception:  # noqa: BLE001
            pass

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

        # C7 fix: dynamic restore-accounting registration.
        self._register_for_restore_accounting()

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
                # Review D D2 fix (2026-06-12): first-install seeds the
                # authoritative value, mirroring the Bug Class #52 skip
                # branch below. Without this notify the EC pending-restore
                # counter is left >0 (we registered above) and
                # ECSubSwitchesSyncedSensor stays True until restart.
                try:
                    energy.notify_sub_switch_restore_complete()
                except Exception:  # noqa: BLE001
                    pass
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

        # Bug Class #52 — RestoreEntity unavailable-coercion.
        # Skip restore when last_state is `unavailable`/`unknown`. Falling
        # through to `target = last_state.state == "on"` would coerce
        # these to False and clobber the options-seeded default (ON).
        # Treat as the "constructor seed wins" branch: do not defer, do
        # not setattr — the existing `_default=True` plus the live
        # `is_on` property reading `energy.dynamic_preset_enabled` (or
        # falling back to `self._default`) keeps state correct.
        if last_state.state not in ("on", "off"):
            # C6 fix: HVACDynamicPresetSwitch's seed is the constructor
            # default (ON), not an options entry — wording corrected.
            _LOGGER.info(
                "Skipping RestoreEntity restore for HVACDynamicPresetSwitch "
                "— last_state=%s — keeping constructor-default value %s",
                last_state.state,
                getattr(
                    self._get_energy(), "dynamic_preset_enabled",
                    self._default,
                ),
            )
            # C1 fix: skip means restore is COMPLETE (seed is authoritative);
            # notify sub-switch accounting so ECSubSwitchesSyncedSensor
            # converges instead of stranding the PROBLEM device_class True.
            _energy_for_notify = self._get_energy()
            if _energy_for_notify is not None:
                try:
                    _energy_for_notify.notify_sub_switch_restore_complete()
                except Exception:  # noqa: BLE001
                    pass
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
        # Late-register if EC wasn't present at async_added_to_hass (C7).
        self._register_for_restore_accounting()
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
            # Late-register (C7).
            self._register_for_restore_accounting()
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


class HVACPreConditioningSwitch(SwitchEntity, RestoreEntity):
    """HC Pre-Conditioning master kill switch.

    When ON (default): HVACPredictor runs the full pre-conditioning chain
    (weather pre-cool + solar banking + pre-arrival + pre-heat).
    When OFF: `_check_pre_conditioning` short-circuits and any in-flight
    pre-conditioned zones are released to their baseline range within ONE
    cycle (operator-required mid-window release parity with the EC Solar
    HVAC Banking sibling toggle).

    Backing field: HVACCoordinator.pre_conditioning_enabled.
    Device:        URA: HVAC Coordinator.
    unique_id:     {DOMAIN}_hvac_pre_conditioning_enabled.

    Restore semantics:
    - Bug Class #52 (v5.3.7 canonical pattern): if last_state is not in
      (``on``, ``off``) — e.g. ``unavailable`` / ``unknown`` post-restart
      — DO NOT coerce to OFF; keep the constructor / options seed.
    - Options write-back is the sole source of truth at runtime (mirrors
      the EC banking sibling); RestoreEntity only carries last on/off
      across HA restarts before HC has re-registered.

    NOTE: The v5.3.7 EC dynamic restore-accounting registration is
    deliberately NOT wired here — that infra is EC-specific
    (`ECSubSwitchesSyncedSensor`) and HC has no analog.

    See PLANNING_hc_precool_toggle_oc_observability.md (D1).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermometer-auto"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_pre_conditioning_enabled"
        self._attr_name = "28 · HVAC Predictive Conditioning"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # Default ON (preserves status-quo pre-conditioning behavior).
        self._default: bool = True
        # Deferred-restore state (Bug Class #5) — used when HC coord not
        # yet registered when async_added_to_hass fires.
        self._deferred_value: bool | None = None

    def _get_hvac(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    @property
    def available(self) -> bool:
        return self._get_hvac() is not None

    @property
    def is_on(self) -> bool:
        hvac = self._get_hvac()
        if hvac is None:
            return self._default
        return bool(getattr(hvac, "pre_conditioning_enabled", self._default))

    async def _write_back_options(self, value: bool) -> None:
        """Persist the toggle's last state into entry.options.

        Mirrors the EC sibling switches: options are the install-time
        seed AND the cross-restart persistence channel. The next reload
        path (init.py options listener) reads `hvac_pre_conditioning_enabled`
        from entry.options and re-applies it to HC.
        """
        try:
            from .domain_coordinators.hvac_const import (
                CONF_HVAC_PRE_CONDITIONING_ENABLED,
            )
            new_options = {
                **self._entry.options,
                CONF_HVAC_PRE_CONDITIONING_ENABLED: bool(value),
            }
            self.hass.config_entries.async_update_entry(
                self._entry, options=new_options,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "HVACPreConditioningSwitch: options write-back failed",
                exc_info=True,
            )

    async def async_turn_on(self, **kwargs) -> None:
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.pre_conditioning_enabled = True
        self._deferred_value = None
        await self._write_back_options(True)
        self.async_write_ha_state()
        _LOGGER.info("HVAC Pre-Conditioning enabled")

    async def async_turn_off(self, **kwargs) -> None:
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.pre_conditioning_enabled = False
        self._deferred_value = None
        await self._write_back_options(False)
        self.async_write_ha_state()
        _LOGGER.info("HVAC Pre-Conditioning disabled")

    async def async_added_to_hass(self) -> None:
        """Restore state — deferred via SIGNAL_HVAC_COORDINATOR_READY if needed.

        Bug Class #52 guard: skip restore when last_state is not in
        (``on``, ``off``) — keep the constructor / options-seeded default.
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
        if last_state is None:
            # First install — apply default ON.
            hvac = self._get_hvac()
            if hvac is not None:
                hvac.pre_conditioning_enabled = self._default
                self.async_write_ha_state()
            return
        # Bug Class #52 — skip transient last_state (unavailable/unknown).
        if last_state.state not in ("on", "off"):
            _LOGGER.info(
                "Skipping RestoreEntity restore for HVACPreConditioningSwitch "
                "— last_state=%s — keeping seed value %s",
                last_state.state,
                getattr(
                    self._get_hvac(), "pre_conditioning_enabled",
                    self._default,
                ),
            )
            return
        target = last_state.state == "on"
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.pre_conditioning_enabled = target
            self._deferred_value = None
            self.async_write_ha_state()
            return
        # HC not yet registered → defer.
        self._deferred_value = target
        _LOGGER.debug(
            "HVACPreConditioningSwitch: HC coord not ready — deferring "
            "restore (value=%s)", target,
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
                "HVACPreConditioningSwitch: SIGNAL_HVAC_COORDINATOR_READY "
                "fired but HC coord still not in hass.data — restore "
                "deferred",
            )
            return
        hvac.pre_conditioning_enabled = self._deferred_value
        _LOGGER.info(
            "HVACPreConditioningSwitch: deferred restore landed via "
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


class HVACTempArresterOverrideSwitch(SwitchEntity):
    """Temp Arrester Override — arrester-scoped temporary stand-down.

    Operator naming (2026-08-06): the switch belongs to the arrester
    family and OVERRIDES arrester governance temporarily; it is NOT a
    "comfort" dial. Friendly name is exactly "Temp Arrester Override";
    unique_id slug is ``ura_hvac_temp_arrester_override``.

    Operator-facing kill switch for arrester corrective writes. When ON,
    the OverrideArrester skips EVERY compromise/severe/revert/AC-ramp
    write across every zone (defense-in-depth via the
    `_corrective_writes_suppressed` helper on the arrester). Default OFF.

    Auto-sunset (first-of): transition INTO house_state == "sleep" OR
    COMFORT_OVERRIDE_MAX_S elapsed since engagement. On sunset the switch
    flips OFF and a LOW NM note fires ("Comfort Override ended (auto)").

    F7 (2026-08-07 fix-up cycle-4) — restart-amnesty invariant:
    the switch is default-OFF non-RestoreEntity by DESIGN. There is
    NO re-engagement across restart: the entry.options marker fires a
    LOW NM note ("released across restart") and clears itself; it
    does NOT call set_temp_arrester_override(True). Therefore
    ``_started_ts`` is never re-stamped across restart and no
    restart-amnesty (fresh 15min grace / fresh 6h max-age) exists.
    If a future cycle EVER adds re-engagement across restart, it MUST
    also persist ``_started_ts`` in entry.options and restore it when
    re-engaging so age math survives — otherwise every restart resets
    both the MIN_LIFE grace and the COMFORT_OVERRIDE_MAX_S cap,
    violating the "6h ceiling" invariant. Also persist any pending
    deferred-sunset flag (see hvac_override.py:_temp_arrester_override_
    pending_sunset — currently in-memory only, documented in the
    ARREST-SUNSET-1 planning doc as an acceptable RESTART GAP).

    Deliberately NOT a RestoreEntity: default-OFF is the safe state
    (documented as intentional inversion of the sibling HVAC switches
    which default ON and restore OFF). An accidental "leave it on"
    through an outage should NOT persistently disable governance —
    the operator can always re-engage after restart if intended.

    Entity: switch.ura_hvac_temp_arrester_override
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:sofa-single"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_temp_arrester_override"
        self._attr_name = "Temp Arrester Override"
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
        hvac = manager.coordinators.get("hvac")
        return hvac.override_arrester if hvac is not None else None

    @property
    def available(self) -> bool:
        return self._get_arrester() is not None

    @property
    def is_on(self) -> bool:
        arrester = self._get_arrester()
        if arrester is None:
            return False
        return arrester.temp_arrester_override_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        arrester = self._get_arrester()
        if arrester is None:
            return {}
        started = arrester.temp_arrester_override_started_ts
        return {
            "suppressed_since": (
                started.isoformat() if started is not None else None
            ),
        }

    def _persist_marker(self, value: bool) -> None:
        """B-M2: persist marker option so an unrelated reload doesn't
        silently drop the operator's engagement without any signal.

        On next setup, __init__.async_setup_entry reads the marker and
        (if True) fires a LOW NM note explaining the override was
        released to default-OFF, then clears the marker.
        """
        try:
            new_options = {
                **self._entry.options,
                "hvac_temp_arrester_override_was_active": value,
            }
            self.hass.config_entries.async_update_entry(
                self._entry, options=new_options,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug(
                "Temp Arrester Override marker persist failed (%s): %s",
                value, e,
            )

    async def async_turn_on(self, **kwargs) -> None:
        arrester = self._get_arrester()
        if arrester is not None:
            arrester.set_temp_arrester_override(True)
            self._persist_marker(True)
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        arrester = self._get_arrester()
        if arrester is not None:
            arrester.set_temp_arrester_override(False)
            self._persist_marker(False)
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to the dedicated dispatcher signal (B-H2)."""
        await super().async_added_to_hass()
        from .domain_coordinators.hvac_const import (
            SIGNAL_HVAC_TEMP_ARRESTER_OVERRIDE_UPDATE,
        )
        from homeassistant.helpers.dispatcher import async_dispatcher_connect

        @callback
        def _handle_update() -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_HVAC_TEMP_ARRESTER_OVERRIDE_UPDATE,
                _handle_update,
            )
        )


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
            # A-LOW-4: an explicit operator OFF must clear any pending
            # deferred restore, otherwise a later READY dispatch would
            # override the operator intent by re-applying the restored
            # "on" value.
            self._deferred_restore = False
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state — deferred via SIGNAL_PRESENCE_COORDINATOR_READY
        if the Presence coordinator isn't in hass.data yet.

        build/pc-observability retrofit: replaces the prior one-shot
        5-second deferred-retry (Bug Class #5 — AUDIT §A.3 concern #1)
        with the v4.7.3.1 signal-deferred pattern that mirrors
        HVACFanControlSwitch (switch.py:~3321).
        Restore-on-"on"-only semantics: default is OFF so we only apply
        a restored non-default (``on``) value.
        """
        await super().async_added_to_hass()

        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_PRESENCE_COORDINATOR_READY
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_PRESENCE_COORDINATOR_READY,
                self._handle_presence_ready,
            )
        )

        last_state = await self.async_get_last_state()
        # Bug Class #52: skip unavailable/unknown; restore-on-non-default only.
        if last_state is None or last_state.state != "on":
            return
        presence = self._get_presence()
        if presence is not None:
            presence.observation_mode = True
            self._deferred_restore = False
            self.async_write_ha_state()
            return
        # Deferred path — presence coord not yet registered.
        self._deferred_restore = True
        _LOGGER.debug(
            "PresenceObservationModeSwitch: presence coord not ready — "
            "deferring restore",
        )

    @callback
    def _handle_presence_ready(self) -> None:
        """Complete deferred restore when SIGNAL_PRESENCE_COORDINATOR_READY fires.

        Bug Class #42 / #19: bound @callback, runs synchronously on the loop.
        """
        if not self._deferred_restore:
            return
        presence = self._get_presence()
        if presence is None:
            _LOGGER.warning(
                "PresenceObservationModeSwitch: SIGNAL_PRESENCE_COORDINATOR_"
                "READY fired but presence coord still missing — restore deferred",
            )
            return
        presence.observation_mode = True
        self._deferred_restore = False
        _LOGGER.info(
            "PresenceObservationModeSwitch: deferred restore landed via "
            "SIGNAL_PRESENCE_COORDINATOR_READY",
        )
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Only available when Presence coordinator is active."""
        return self._get_presence() is not None


# ============================================================================
# build/pc-observability: three P1 kill switches on the Presence Coordinator
# device. All default ON. All follow the v5.48.0 HVACFanControlSwitch hygiene
# EXACTLY:
#   - SwitchEntity + RestoreEntity
#   - signal-deferred restore via SIGNAL_PRESENCE_COORDINATOR_READY
#   - restore-on-"off"-only semantics (default ON — only restore the non-
#     default value) — mirrors NMMessagingSuppressSwitch's "restore only
#     the non-default" precedent.
#   - `_deferred_value` sentinel cleared by explicit operator toggles.
#   - `suppressed_since` ISO timestamp attr when OFF (provenance).
# Each switch is LOAD-BEARING against a specific presence-coord decision
# path — see the per-switch docstring for the citation.
# ============================================================================


class _PresenceKillSwitchBase(SwitchEntity, RestoreEntity):
    """Base for the three presence kill switches (default ON).

    Subclasses set:
      * ``_unique_slug``     — used to build unique_id + attr slug
      * ``_friendly_name``   — plain-English label
      * ``_backing_field``   — attribute on presence coord that gates behavior
      * ``_since_field``     — provenance timestamp attribute on presence coord
      * ``_icon``            — mdi icon
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    _unique_slug: str = ""
    _friendly_name: str = ""
    _backing_field: str = ""
    _since_field: str = ""
    _icon: str = "mdi:toggle-switch"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{self._unique_slug}"
        self._attr_name = self._friendly_name
        self._attr_icon = self._icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # Deferred restore sentinel (bool target or None).
        self._deferred_value: bool | None = None
        # B-H1: stash of `suppressed_since` from last_state so a deferred
        # restore preserves the ORIGINAL OFF timestamp (matching the fast
        # path). None → deferred handler falls back to utcnow().
        self._deferred_since: str | None = None

    def _get_presence(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("presence")

    @property
    def available(self) -> bool:
        return self._get_presence() is not None

    @property
    def is_on(self) -> bool:
        presence = self._get_presence()
        if presence is None:
            return True  # default ON
        return bool(getattr(presence, self._backing_field, True))

    @property
    def extra_state_attributes(self) -> dict:
        presence = self._get_presence()
        if presence is None:
            return {}
        return {
            "suppressed_since": getattr(presence, self._since_field, None),
        }

    async def async_turn_on(self, **kwargs) -> None:
        presence = self._get_presence()
        if presence is not None:
            setattr(presence, self._backing_field, True)
            setattr(presence, self._since_field, None)
            self._deferred_value = None
            self.async_write_ha_state()
            _LOGGER.info("Presence: %s enabled", self._friendly_name)

    async def async_turn_off(self, **kwargs) -> None:
        presence = self._get_presence()
        if presence is not None:
            setattr(presence, self._backing_field, False)
            try:
                from homeassistant.util import dt as _dtu
                setattr(presence, self._since_field, _dtu.utcnow().isoformat())
            except Exception:  # noqa: BLE001 — defensive
                setattr(presence, self._since_field, None)
            self._deferred_value = None
            self.async_write_ha_state()
            _LOGGER.info("Presence: %s disabled", self._friendly_name)

    async def async_added_to_hass(self) -> None:
        """Signal-deferred restore. Restore-on-'off'-only (default ON)."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_PRESENCE_COORDINATOR_READY
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_PRESENCE_COORDINATOR_READY,
                self._handle_presence_ready,
            )
        )
        last_state = await self.async_get_last_state()
        # Bug Class #52: skip unavailable/unknown; restore only the non-default
        # value ("off" here since default is ON). Matches NMMessagingSuppress
        # precedent at switch.py:~3451.
        if last_state is None or last_state.state != "off":
            return
        presence = self._get_presence()
        if presence is not None:
            setattr(presence, self._backing_field, False)
            try:
                from homeassistant.util import dt as _dtu
                # Prefer preserved suppressed_since; fall back to now.
                attrs = getattr(last_state, "attributes", None) or {}
                sus = attrs.get("suppressed_since")
                if isinstance(sus, str) and sus:
                    setattr(presence, self._since_field, sus)
                else:
                    setattr(presence, self._since_field, _dtu.utcnow().isoformat())
            except Exception:  # noqa: BLE001 — defensive
                pass
            self._deferred_value = None
            self.async_write_ha_state()
            return
        # Presence coord not registered — defer.
        self._deferred_value = False
        # B-H1: stash restored suppressed_since so the deferred path applies
        # it verbatim (mirrors the fast path above).
        try:
            attrs = getattr(last_state, "attributes", None) or {}
            _sus = attrs.get("suppressed_since")
            self._deferred_since = _sus if isinstance(_sus, str) and _sus else None
        except Exception:  # noqa: BLE001
            self._deferred_since = None
        _LOGGER.debug(
            "%s: presence coord not ready — deferring restore (value=False, "
            "suppressed_since=%s)",
            type(self).__name__,
            self._deferred_since,
        )

    @callback
    def _handle_presence_ready(self) -> None:
        """Bug Class #42 / #19: bound @callback synchronous handler."""
        if self._deferred_value is None:
            return
        presence = self._get_presence()
        if presence is None:
            _LOGGER.warning(
                "%s: SIGNAL_PRESENCE_COORDINATOR_READY fired but presence "
                "coord still missing — restore deferred",
                type(self).__name__,
            )
            # B-M4: clear the deferred sentinels so a second READY dispatch
            # (or a later successful path) can't apply a stale target.
            self._deferred_value = None
            self._deferred_since = None
            return
        setattr(presence, self._backing_field, self._deferred_value)
        if self._deferred_value is False:
            # B-H1: prefer the stashed `_deferred_since` so the OFF
            # timestamp restored from the recorder is preserved verbatim;
            # fall back to now only when nothing was preserved.
            try:
                from homeassistant.util import dt as _dtu
                _since = self._deferred_since or _dtu.utcnow().isoformat()
                setattr(presence, self._since_field, _since)
            except Exception:  # noqa: BLE001
                pass
        _LOGGER.info(
            "%s: deferred restore landed via SIGNAL_PRESENCE_COORDINATOR_READY "
            "(value=%s, since=%s)",
            type(self).__name__,
            self._deferred_value,
            self._deferred_since,
        )
        self._deferred_value = None
        self._deferred_since = None
        self.async_write_ha_state()


class PresenceGuestDetectionEnabledSwitch(_PresenceKillSwitchBase):
    """Kill switch for guest detection (Paths A + B). Default ON.

    Load-bearing: gates ``_guest_gate_armed`` (Path A, presence.py) AND
    ``_guest_room_gate_armed`` (Path B, presence.py). When OFF, both
    return False early and no HouseState.GUEST transition can fire from
    presence-driven paths.
    """

    _unique_slug = "presence_guest_detection_enabled"
    _friendly_name = "Guest Detection"
    _backing_field = "_guest_detection_enabled"
    _since_field = "_guest_detection_suppressed_since"
    _icon = "mdi:account-question"


class PresenceArrivingRearmEnabledSwitch(_PresenceKillSwitchBase):
    """Kill switch for the arriving re-arm cooldown. Default ON.

    Load-bearing: gates the cooldown-suppression block in
    ``_run_inference`` AND the cooldown-arming site (both in presence.py).
    OFF is equivalent to ``ARRIVING_REARM_COOLDOWN_S = 0`` at runtime.
    """

    _unique_slug = "presence_arriving_rearm_enabled"
    _friendly_name = "Arrival Re-Alerts"
    _backing_field = "_arriving_rearm_enabled"
    _since_field = "_arriving_rearm_suppressed_since"
    _icon = "mdi:timer-refresh"


class PresenceAwayVetoEnabledSwitch(_PresenceKillSwitchBase):
    """Kill switch for the person-tracker AWAY veto (v4.7.14 shared helper). Default ON.

    Load-bearing: when OFF, coerces the ``all_tracked_persons_away`` +
    ``all_trusted_or_lost_away_persons_away`` locals AND the
    ``self._all_tracked_persons_away`` instance attribute to ``False`` at
    the top of the ``_inference_engine.infer(...)`` call block in
    presence.py, so both the v4.7.14 (α) and v5.7.0 WS-A (β) AWAY-veto
    paths — AND the house-state-sensor surface that reads the instance
    attr — reflect the disabled state (A-HIGH-1 fix-up).
    """

    _unique_slug = "presence_away_veto_enabled"
    _friendly_name = "Away Confirmation Veto"
    _backing_field = "_away_veto_enabled"
    _since_field = "_away_veto_suppressed_since"
    _icon = "mdi:home-remove"


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
        # Bug Class #52 — skip unavailable/unknown to preserve constructor default.
        if last_state is not None and last_state.state in ("on", "off"):
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
        # Bug Class #52 — skip unavailable/unknown to preserve constructor default.
        if last_state is not None and last_state.state in ("on", "off"):
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

    def _persist_master_option(self, value: bool) -> None:
        """Write-through to entry.options — reload-safe persistence.

        Fixes the 2026-08-06 reload→OFF regression: on config-entry reload,
        the arrester is recreated at DEFAULT=False; RestoreEntity's
        last_state during a quick reload is often `unavailable` (the
        restore-only-if-'on'/'off' guard skips), so the switch UI came
        back OFF and the ramp feature silently disabled itself.

        We route the master through ``entry.options[hvac_ac_ramp_master
        _enabled]`` — the same channel the CM already uses for live-tunable
        options (see ``OPTIONS_RELOAD_SUPPRESS_KEYS`` in __init__.py, which
        this key was added to so the write does NOT itself trigger a reload
        loop). The HVAC coordinator init seeds ``_ramp_master_enabled`` from
        this option, so the value survives every subsequent reload.

        Only writes when the value actually changes (guards against
        reload-loop feedback in case a future update_listener change
        wires an unexpected reload for this key).
        """
        try:
            current = bool(self._entry.options.get(
                "hvac_ac_ramp_master_enabled",
            ))
            if current == value:
                return
            new_options = {**self._entry.options,
                           "hvac_ac_ramp_master_enabled": value}
            self.hass.config_entries.async_update_entry(
                self._entry, options=new_options,
            )
        except Exception as e:  # noqa: BLE001 — persistence is belt+braces
            _LOGGER.warning(
                "HVACACRampMasterSwitch: entry.options write-through "
                "failed for hvac_ac_ramp_master_enabled=%s: %s "
                "(RestoreEntity is the fallback)", value, e,
            )

    async def async_turn_on(self, **kwargs) -> None:
        arr = self._get_arrester()
        if arr is not None:
            arr.ramp_master_enabled = True
            self._persist_master_option(True)
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        arr = self._get_arrester()
        if arr is not None:
            arr.ramp_master_enabled = False  # setter cancels in-flight nudges
            self._persist_master_option(False)
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

        # AUTHORITY ORDER (2026-08-06 fix): entry.options is now the
        # primary source of truth. RestoreEntity's last_state is the
        # belt-and-braces fallback ONLY when the option is absent (fresh
        # install). Fixes the reload→OFF regression where last_state was
        # 'unavailable' during a quick reload and the RestoreEntity path
        # skipped, silently disabling the ramp feature.
        opt_value = self._entry.options.get("hvac_ac_ramp_master_enabled")
        if opt_value is not None:
            target = bool(opt_value)
        else:
            last_state = await self.async_get_last_state()
            if last_state is None or last_state.state not in ("on", "off"):
                # No prior state, no option — default OFF is truth.
                return
            target = last_state.state == "on"
            # MED-A5 caveat 1: one-shot migration — copy the clean
            # RestoreEntity on/off into the option so the NEXT reload
            # doesn't lose the value through the RestoreEntity==unavailable
            # gap. Guarded: if the write fails, we still applied `target`
            # to the arrester below.
            self._persist_master_option(target)
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
            "(value=%s, source=%s)",
            target, "option" if opt_value is not None else "last_state",
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
        # Bug Class #52 — skip unavailable/unknown to preserve constructor default.
        if last_state is not None and last_state.state in ("on", "off"):
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

    hotfix/fan-sweep-trio (2026-08-03): deferred-restore via
    SIGNAL_HVAC_COORDINATOR_READY (Bug Class #5/#38). Replaces the
    prior one-shot 5-second timer retry that dropped the restored
    value if the HVAC coord was still not registered after that window.
    Mirrors the v4.7.3.1 HVACOverrideArresterSwitch pattern.

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
        # hotfix/fan-sweep-trio (2026-08-03): deferred-restore state
        # (Bug Class #5). Mirrors ECSwitch factory line ~707 hygiene:
        # explicit None sentinel; explicit user toggles null it out;
        # the signal handler nulls it after applying.
        self._deferred_value: bool | None = None

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
            # Explicit user toggle wins over any pending deferred restore.
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable temperature-based fan control."""
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.fan_control_enabled = False
            self._deferred_value = None
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state — deferred via SIGNAL_HVAC_COORDINATOR_READY
        if the HVAC coordinator isn't in hass.data yet.

        hotfix/fan-sweep-trio (2026-08-03): Bug Class #5 fix. Old code
        used a single 5-second one-shot retry — if the HVAC coord
        still hadn't registered after that window (real-world observed
        on cold boots when the operator had turned Fan Control OFF),
        the restored OFF was silently dropped and Fan Control came up
        ON (the constructor default). Now the switch subscribes to
        SIGNAL_HVAC_COORDINATOR_READY (Bug Class #38: unsub tracked
        via async_on_remove) — the deferred value applies whenever
        the HVAC coord actually finishes setup, no matter how long
        that takes.
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
        # Bug Class #52 / MED-1 — skip unavailable/unknown to preserve
        # constructor default (matches v4.7.3.1 pattern across all HVAC
        # switches).
        if last_state is None or last_state.state not in ("on", "off"):
            return
        target = last_state.state == "on"
        hvac = self._get_hvac()
        if hvac is not None:
            # Fast path: HVAC coord already registered.
            hvac.fan_control_enabled = target
            self._deferred_value = None
            self.async_write_ha_state()
            return
        # Deferred path: HVAC coord not yet registered.
        self._deferred_value = target
        _LOGGER.debug(
            "HVACFanControlSwitch: HVAC coord not ready — deferring "
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
                "HVACFanControlSwitch: SIGNAL_HVAC_COORDINATOR_READY "
                "fired but HVAC coord still not in hass.data — restore "
                "deferred",
            )
            return
        hvac.fan_control_enabled = self._deferred_value
        _LOGGER.info(
            "HVACFanControlSwitch: deferred restore landed via "
            "SIGNAL_HVAC_COORDINATOR_READY (value=%s)",
            self._deferred_value,
        )
        self._deferred_value = None
        self.async_write_ha_state()

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
        # Notification Hygiene FIX 1: mark that the current pending sync
        # was triggered by RestoreEntity (not an operator toggle) so
        # _sync_to_nm can apply the stale-restore age gate.
        self._restore_pending = False
        # MED-A3: authoritative suppression origin timestamp maintained
        # on the switch itself; restored from RestoreEntity attrs.
        self._suppressed_since_attr: str | None = None
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
            self._restore_pending = True  # FIX 1: age-gate on next sync
            # MED-A3: recover the suppression origin attribute if the
            # RestoreEntity round-trip preserved it. Non-string / absent →
            # leave None (stale gate then falls back to nm._suppressed_since
            # or last_changed).
            try:
                attrs = getattr(last_state, "attributes", None) or {}
                sus = attrs.get("suppressed_since")
                if isinstance(sus, str) and sus:
                    self._suppressed_since_attr = sus
            except Exception:  # noqa: BLE001
                _LOGGER.debug("suppressed_since restore failed (swallowed)", exc_info=True)
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
            # Notification Hygiene FIX 1 (B-2026-08-03-3(c)): if the
            # restored ON state is older than the max-age gate, refuse
            # to restore — come up unsuppressed and emit a one-shot
            # MEDIUM so the operator can re-engage intentionally. Only
            # applies to the restore-triggered sync path; operator
            # toggles (async_turn_on) bypass this gate.
            if self._restore_pending:
                self._restore_pending = False
                from .const import NM_SUPPRESSION_RESTORE_MAX_AGE_S
                from homeassistant.util import dt as _dtu
                max_age = int(NM_SUPPRESSION_RESTORE_MAX_AGE_S)
                stale = False
                age_s: float | None = None
                if max_age > 0:
                    # MED-A3: earliest-wins across (nm._suppressed_since,
                    # switch attribute, last_changed). Removes the
                    # dependence on NM restoring _suppressed_since before
                    # the sync fires. Any source may be absent / invalid.
                    candidates: list = []
                    nm_since = getattr(nm, "_suppressed_since", None)
                    if nm_since is not None:
                        candidates.append(nm_since)
                    sw_iso = getattr(self, "_suppressed_since_attr", None)
                    if isinstance(sw_iso, str) and sw_iso:
                        try:
                            candidates.append(_dtu.parse_datetime(sw_iso))
                        except Exception:  # noqa: BLE001
                            _LOGGER.debug(
                                "switch suppressed_since parse failed (swallowed)",
                                exc_info=True,
                            )
                    st = self.hass.states.get(self.entity_id) if self.entity_id else None
                    lc = getattr(st, "last_changed", None) if st else None
                    if lc is not None:
                        candidates.append(lc)
                    # Drop Nones from parse failures; require tz-aware for compare.
                    candidates = [c for c in candidates if c is not None]
                    since = min(candidates) if candidates else None
                    if since is not None:
                        try:
                            age_s = (_dtu.utcnow() - since).total_seconds()
                            stale = age_s > max_age
                        except (TypeError, ValueError):
                            stale = False
                if stale:
                    self._is_on = False
                    _LOGGER.warning(
                        "NM messaging suppression NOT restored on startup — "
                        "prior suppression was %.0fs old (max_age=%ds). Coming "
                        "up unsuppressed. Re-enable via switch if intended.",
                        age_s or 0.0, max_age,
                    )
                    self.async_write_ha_state()
                    # One-shot MEDIUM notification (NM is unsuppressed so
                    # this fires through normal channels).
                    try:
                        from .domain_coordinators.base import Severity
                        days = int((age_s or 0) // 86400)
                        await nm.async_notify(
                            coordinator_id="notification_manager",
                            # MED-A4: promote to HIGH so the stale-suppression
                            # one-shot bypasses digest preferences (immediate).
                            severity=Severity.HIGH,
                            title="NM suppression not restored across restart",
                            message=(
                                f"NM messaging suppression was ON for "
                                f"~{days}d before restart (older than "
                                f"{max_age // 3600}h max). URA came up "
                                "unsuppressed — re-enable if intended."
                            ),
                            hazard_type=None,
                            location=None,
                        )
                    except Exception:  # noqa: BLE001
                        _LOGGER.debug(
                            "One-shot stale-suppression notify failed (swallowed)",
                            exc_info=True,
                        )
                    return
            await nm.async_suppress_messaging()
            _LOGGER.info("Synced messaging suppression to NM")
        elif not self._is_on and nm.messaging_suppressed:
            await nm.async_resume_messaging()
            _LOGGER.info("Synced messaging resume to NM")
        # Clear restore flag on any successful sync (idempotent).
        self._restore_pending = False

    def _get_nm(self):
        """Get the notification manager instance."""
        return self.hass.data.get(DOMAIN, {}).get("notification_manager")

    @property
    def is_on(self) -> bool:
        """Return True if messaging is suppressed (self-contained state)."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Suppress all outbound messaging."""
        # HIGH-A1: operator intent supersedes any pending restore-sync.
        # Cancel a deferred restore-sync so its stale age gate can't run
        # against a fresh toggle, and clear the restore-pending flag.
        self._restore_pending = False
        if self._sync_unsub:
            try:
                self._sync_unsub()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("cancel pending sync raised (swallowed)", exc_info=True)
            self._sync_unsub = None
        self._is_on = True
        # MED-A3: stamp suppression origin on the switch itself so the
        # stale gate has an authoritative earliest-wins source that does
        # not depend on NM restore ordering.
        from homeassistant.util import dt as _dtu
        self._suppressed_since_attr = _dtu.utcnow().isoformat()
        nm = self._get_nm()
        if nm is not None:
            await nm.async_suppress_messaging()
        else:
            self._sync_retries = 0
            await self._sync_to_nm()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Resume outbound messaging."""
        # HIGH-A1: operator intent supersedes any pending restore-sync.
        self._restore_pending = False
        if self._sync_unsub:
            try:
                self._sync_unsub()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("cancel pending sync raised (swallowed)", exc_info=True)
            self._sync_unsub = None
        self._is_on = False
        # MED-A3: clear suppression origin attribute on operator resume.
        self._suppressed_since_attr = None
        nm = self._get_nm()
        if nm is not None:
            await nm.async_resume_messaging()
        else:
            self._sync_retries = 0
            await self._sync_to_nm()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict:
        """MED-A3: expose suppression origin timestamp for the stale gate.

        Persisted via RestoreEntity and read back in
        ``async_added_to_hass`` so the earliest-wins gate does not depend
        on NM having repopulated ``_suppressed_since`` yet.
        """
        return {"suppressed_since": self._suppressed_since_attr}

    @property
    def available(self) -> bool:
        """Always available — state is self-contained, NM synced when ready."""
        return True


class NMDryRunSwitch(SwitchEntity, RestoreEntity):
    """NM Cycle B B0: master dry-run gate.

    When ON: every emit-path `hass.services.async_call` in NM is short-
    circuited to a minimal `notification_log` row (dry_run=1). Enables
    safe live exercise of CRITICAL machinery — repeat cadence, safe-word
    ack, storm behavior — without any real Pushover / iMessage /
    WhatsApp / Companion / TTS / Alert-Light send.

    Kill-switch semantics: `true = zero outbound`. Restart-safe via
    RestoreEntity. Sole exception: `_restore_alert_lights` teardown is
    NOT gated — lights must be returned to their pre-alert state so
    physical state stays honest.

    Entity: switch.ura_nm_dry_run
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:test-tube"
    _attr_entity_category = EntityCategory.CONFIG

    _MAX_SYNC_RETRIES = 18  # 18 × 10s = 3 minutes max wait for NM

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._sync_retries = 0
        self._sync_unsub = None
        self._attr_unique_id = f"{DOMAIN}_nm_dry_run"
        self._attr_name = "Dry Run"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "notification_manager")},
            name="URA: Notification Manager",
            manufacturer="Universal Room Automation",
            model="Notification Manager",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # Seed from options-flow at install; RestoreEntity overrides on restart.
        opts = {**entry.data, **entry.options}
        self._is_on = bool(opts.get(CONF_NM_DRY_RUN, DEFAULT_NM_DRY_RUN))

    async def async_added_to_hass(self) -> None:
        """Restore last state and sync to NM."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._is_on = last_state.state == "on"
        if self._is_on:
            _LOGGER.warning(
                "NM dry-run gate restored ON — outbound notifications SHORT-CIRCUITED"
            )
        await self._sync_to_nm()

    async def async_will_remove_from_hass(self) -> None:
        if self._sync_unsub:
            self._sync_unsub()
            self._sync_unsub = None

    def _get_nm(self):
        return self.hass.data.get(DOMAIN, {}).get("notification_manager")

    async def _sync_to_nm(self) -> None:
        """Push local state to NM. Bounded-retry on NM-not-ready."""
        nm = self._get_nm()
        if nm is None:
            self._sync_retries += 1
            if self._sync_retries > self._MAX_SYNC_RETRIES:
                _LOGGER.warning(
                    "NM not available after %d retries — giving up dry-run sync "
                    "(switch state preserved locally, will sync on next toggle)",
                    self._sync_retries,
                )
                return
            async def _deferred_sync(_now=None):
                # Named coroutine — avoids Bug Class #42
                # (lambda-wrapped async_create_task) tripwire.
                self._sync_unsub = None
                await self._sync_to_nm()

            self._sync_unsub = async_call_later(self.hass, 10, _deferred_sync)
            return
        self._sync_retries = 0
        await nm.set_dry_run_active(self._is_on)

    @property
    def is_on(self) -> bool:
        return self._is_on

    def _writeback_options(self, value: bool) -> None:
        """NM Cycle B fix-up (2026-07-20, B-B4): options-writeback pattern
        (mirrors the Numbers). Persist the toggle into CM entry.options so
        NM.__init__ reads the true value at construction post-restart;
        RestoreEntity remains as a display-state backup only. The
        `CONF_NM_DRY_RUN` key is reload-suppressed in
        `OPTIONS_RELOAD_SUPPRESS_KEYS`, so this write does NOT cause a
        CM reload."""
        try:
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={**self._entry.options, CONF_NM_DRY_RUN: bool(value)},
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("NMDryRunSwitch options-writeback failed", exc_info=True)

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        self._writeback_options(True)
        nm = self._get_nm()
        if nm is not None:
            await nm.set_dry_run_active(True)
        else:
            self._sync_retries = 0
            await self._sync_to_nm()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        self._writeback_options(False)
        nm = self._get_nm()
        if nm is not None:
            await nm.set_dry_run_active(False)
        else:
            self._sync_retries = 0
            await self._sync_to_nm()
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
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


class AutoRecoverySwitch(UniversalRoomEntity, SwitchEntity, RestoreEntity):
    """Per-room reconcile-on-return gate (v5.8.0, D2.12, guard 9).

    Straight sibling of AutomationSwitch / ClimateAutomationSwitch /
    CoverAutomationSwitch. SEPARATE from the master AutomationSwitch and
    manual_mode — this gates ONLY whether the ActuatorReconciler dispatches a
    service call. When OFF, the reconciler STILL computes would_reconcile for
    observability (the manual dry-run / safe-rollout lever). Default ON.

    Bug Class #52 guard: an ``unavailable`` / ``unknown`` last-state does NOT
    coerce to OFF — it falls back to the default (ON).
    """

    _attr_icon = "mdi:backup-restore"
    # Enabled by default (v5.8.0 operator decision): this is the documented
    # dry-run / safe-rollout lever (flip OFF, watch would_reconcile, flip ON).
    # A registry-disabled entity would force the operator to enable a hidden
    # entity before the dry-run path is usable, defeating its purpose.
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "auto_recovery", "Device Auto Recovery")
        self._attr_is_on = True  # Default to enabled

    async def async_added_to_hass(self) -> None:
        """Restore last state (Bug Class #52 guard)."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            # Only adopt a CONCRETE on/off. An unavailable/unknown last-state
            # must NOT coerce to OFF — leave the default ON.
            self._attr_is_on = last_state.state == "on"

    @property
    def available(self) -> bool:
        """Switch is always available."""
        return True

    async def async_turn_on(self, **kwargs) -> None:
        """Enable reconcile-on-return for this room."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("Auto-Recovery enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Disable reconcile-on-return (dry-run / preview mode)."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Auto-Recovery disabled for room: %s", self.coordinator.entry.data.get("room_name"))


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


# ============================================================================
# v4.7.34 Phase 1 D7: OptimizerKillSwitch
# ============================================================================
#
# Restart-persistent kill switch for the Optimization Coordinator. When ON,
# the coordinator's effective autonomy clamps synchronously to L0 (advisory)
# regardless of stored config, in-flight intents are cancelled, and HVAC
# suppression TTLs are explicitly closed via OverrideArrester.unsuppress().
#
# Persistence: belt-and-suspenders (per plan D2) — entry.options write-back
# AND RestoreEntity. Modeled on EnergyObservationModeSwitch at switch.py:396.


class OptimizerKillSwitch(SwitchEntity, RestoreEntity):
    """Kill switch for the URA Optimization Coordinator.

    When ON: clamp effective rung to L0 advisory immediately and persist
    state across HA restart.

    Entity: switch.ura_optimizer_kill_switch
    Device: URA: Optimization Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:hand-back-right-off"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        from .const import (
            CONF_OPTIMIZER_KILL_SWITCH,
            DEFAULT_OPTIMIZER_KILL_SWITCH,
        )
        self.hass = hass
        self._entry = entry
        self._conf_key = CONF_OPTIMIZER_KILL_SWITCH
        self._default = DEFAULT_OPTIMIZER_KILL_SWITCH
        self._attr_unique_id = f"{DOMAIN}_optimizer_kill_switch"
        self._attr_name = "Optimizer Kill Switch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "optimization_coordinator")},
            name="URA: Optimization Coordinator",
            manufacturer="Universal Room Automation",
            model="Optimization Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # Seed from options first (single source of truth), fall back to
        # data, then default — same as the Comfort sliders' D6 pattern.
        opts = entry.options or {}
        data = entry.data or {}
        if self._conf_key in opts and opts[self._conf_key] is not None:
            self._attr_is_on = bool(opts[self._conf_key])
        elif self._conf_key in data and data[self._conf_key] is not None:
            self._attr_is_on = bool(data[self._conf_key])
        else:
            self._attr_is_on = bool(self._default)

    @property
    def is_on(self) -> bool:
        return bool(self._attr_is_on)

    @property
    def available(self) -> bool:
        return True

    def _write_options(self, value: bool) -> None:
        try:
            options = {**(self._entry.options or {}), self._conf_key: bool(value)}
            self.hass.config_entries.async_update_entry(
                self._entry, options=options,
            )
        except Exception:  # noqa: BLE001 — never crash UI
            _LOGGER.debug(
                "Optimizer kill switch options write-back failed",
                exc_info=True,
            )

    def _close_suppression_ttls(self) -> None:
        """When tripping the kill switch, close any open HVAC suppression
        TTLs so a half-applied URA write doesn't sit suppressed.

        Sibling-fix of A-CRIT-1: ``hass.data[DOMAIN]["hvac_coordinator"]``
        is not a slot the integration populates. Resolve via the
        CoordinatorManager (``coordinators["hvac"]``) with a back-compat
        fallback to the legacy slot for tests that mount it directly.
        """
        try:
            domain_data = self.hass.data.get(DOMAIN, {}) or {}
            hvac = domain_data.get("hvac_coordinator")
            if hvac is None:
                cm = domain_data.get("coordinator_manager")
                if cm is not None:
                    coords = getattr(cm, "coordinators", None) or {}
                    hvac = coords.get("hvac")
            if hvac is None:
                return
            arrester = getattr(hvac, "override_arrester", None)
            if arrester is None:
                return
            # _suppressed_until is a dict[entity_id, expiry] (hvac_override.py:137)
            for eid in list(getattr(arrester, "_suppressed_until", {}).keys()):
                try:
                    arrester.unsuppress(eid)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Closing suppression TTLs on kill switch failed",
                exc_info=True,
            )

    async def async_turn_on(self, **kwargs) -> None:
        """Engage the kill switch. Persist + close suppression TTLs.

        Pillar B D6: engaging the kill switch ALSO strips any pending
        autonomy escalation. A pending L0→L2+ jump must not survive a
        kill — the operator's "fast brake" trumps any in-flight UX.

        Pillar B fix-up A-H2 / A-L11: persist the kill flag AND strip the
        pending key in ONE merged ``async_update_entry`` call (was two
        sequential writes triggering two CM reload-suppression evaluations
        in a row). After the write, push the autonomy select to refresh
        immediately so the entity leaves any ``pending_*`` token without
        waiting for the platform's 30s poll interval — same pattern the
        Confirm / Cancel buttons use.
        """
        from .const import CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL
        self._attr_is_on = True
        # ONE merged dict-copy + ONE async_update_entry: kill flag set,
        # pending stripped, all other options preserved.
        try:
            opts = dict(self._entry.options or {})
            opts[self._conf_key] = True
            opts.pop(CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL, None)
            self.hass.config_entries.async_update_entry(
                self._entry, options=opts,
            )
        except Exception:  # noqa: BLE001 — never crash UI
            _LOGGER.debug(
                "Optimizer kill switch engage options write failed",
                exc_info=True,
            )
        self._refresh_autonomy_select()
        self._close_suppression_ttls()
        _LOGGER.info(
            "Optimizer kill switch ENGAGED, autonomy clamped to advisory",
        )
        self.async_write_ha_state()

    def _refresh_autonomy_select(self) -> None:
        """Push the OptimizerAutonomyLevelSelect to re-read options.

        Mirrors ``button._refresh_autonomy_select`` so the select leaves
        ``pending_*`` state immediately on kill engage.
        """
        try:
            sel = (
                self.hass.data.get(DOMAIN, {}).get(
                    "optimizer_autonomy_select",
                )
            )
            if sel is not None and hasattr(sel, "_refresh_from_options"):
                sel._refresh_from_options()
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Optimizer autonomy select refresh on kill engage failed",
                exc_info=True,
            )

    async def async_turn_off(self, **kwargs) -> None:
        """Release the kill switch. Restores configured autonomy level."""
        self._attr_is_on = False
        self._write_options(False)
        _LOGGER.info("Optimizer kill switch RELEASED")
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore kill state on startup — FAIL CLOSED on split-brain.

        B-C2 fix-up: the kill switch is a safety primitive and MUST
        never fail open. If EITHER persistence channel (entry.options
        OR RestoreEntity last_state) reports `engaged`, we engage. The
        plan D2 line 248 mandates RestoreEntity, so we keep it.

        Concretely: if options=False but last_state=on (e.g. options was
        cleared by a manual edit while the entity restore won), we stay
        engaged AND re-write options=True so the two persistence
        channels reconverge.
        """
        await super().async_added_to_hass()
        opts = self._entry.options or {}
        opts_says_on = bool(opts.get(self._conf_key)) if self._conf_key in opts else None
        last = await self.async_get_last_state()
        last_says_on = last is not None and last.state == "on"
        # Engage if EITHER source says engaged.
        if opts_says_on is True or last_says_on:
            self._attr_is_on = True
            if opts_says_on is not True:
                # Reconverge options to match the engaged state.
                self._write_options(True)
            self.async_write_ha_state()
            return
        # If neither source said engaged, leave the constructor's seed
        # (default released) and write the state out so the entity isn't
        # stuck in "unknown" until the first user interaction.
        self.async_write_ha_state()


# ============================================================================
# D6 — Room-device switches for the bathroom-exhaust intelligence cycle.
# These mirror the options-flow toggles #2 (comfort) and #3 (humidity) onto
# the room device so per-room operator control is one tap (not a config-flow
# round-trip). Writeback pattern follows RoomFanRecheckEnabledSwitch.
# ============================================================================


class _RoomBooleanOptionSwitch(
    UniversalRoomEntity, SwitchEntity, RestoreEntity,
):
    """Generic per-room boolean options-writeback switch.

    Subclasses set `_conf_key`, `_default`, the entity slug+display name in
    `__init__`. RestoreEntity is the runtime store; entry.options seeds
    install-time defaults. Writes the value back into the room entry.options
    on toggle so consumers reading `entry.options` pick it up immediately.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _conf_key: str = ""
    _default: bool = False

    def _read_default(self) -> bool:
        merged = {
            **self.coordinator.entry.data,
            **self.coordinator.entry.options,
        }
        return bool(merged.get(self._conf_key, self._default))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        # Fan/humidity toggle-symmetry (2026-07-22, F2 MEDIUM):
        # dual-source precedence — RestoreEntity vs options-flow write.
        # Options-flow is the OTHER writer for these knobs
        # (config_flow.py:9277-9283 humidity, :1858/1870 comfort). If the
        # operator edits the options flow between restarts, the reload
        # would otherwise restore the switch's stale entity state while
        # consumers read the fresh option → switch display diverges from
        # consumer behavior until the next physical toggle.
        # Precedence: options value (if the key is PRESENT in entry
        # options) wins at boot; RestoreEntity only covers the
        # key-ABSENT first-boot case.
        # Bug Class #52 guard preserved: last_state.state must be
        # "on"/"off" (never trust unavailable/unknown).
        try:
            entry_options = self.coordinator.entry.options
        except Exception:  # noqa: BLE001 — defensive; entry always present at added_to_hass
            entry_options = {}
        if self._conf_key in entry_options:
            self._attr_is_on = bool(entry_options[self._conf_key])
        elif last_state is not None and last_state.state in ("on", "off"):
            self._attr_is_on = last_state.state == "on"
        else:
            self._attr_is_on = self._read_default()

    def _mirror_options(self, value: bool) -> None:
        try:
            entry = self.coordinator.entry
            self.hass.config_entries.async_update_entry(
                entry,
                options={**entry.options, self._conf_key: value},
            )
        except Exception:  # noqa: BLE001 — best-effort options mirror
            _LOGGER.debug(
                "%s: options mirror failed", type(self).__name__, exc_info=True,
            )

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self._mirror_options(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self._mirror_options(False)
        self.async_write_ha_state()


class RoomComfortFanControlSwitch(_RoomBooleanOptionSwitch):
    """D6 — per-room Comfort Fan Control toggle (mirrors CONF_FAN_CONTROL_ENABLED)."""

    _attr_icon = "mdi:fan-auto"

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        from .const import CONF_FAN_CONTROL_ENABLED
        super().__init__(
            coordinator, "comfort_fan_control", "Comfort Fan Control",
        )
        self._conf_key = CONF_FAN_CONTROL_ENABLED
        self._default = False
        self._attr_is_on = self._read_default()


class RoomHumidityFanControlSwitch(_RoomBooleanOptionSwitch):
    """D6 — per-room Humidity Fan Control toggle (mirrors CONF_HUMIDITY_FAN_CONTROL_ENABLED)."""

    _attr_icon = "mdi:fan-alert"

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        from .const import (
            CONF_HUMIDITY_FAN_CONTROL_ENABLED,
            DEFAULT_HUMIDITY_FAN_CONTROL_ENABLED,
        )
        super().__init__(
            coordinator, "humidity_fan_control", "Humidity Fan Control",
        )
        self._conf_key = CONF_HUMIDITY_FAN_CONTROL_ENABLED
        self._default = DEFAULT_HUMIDITY_FAN_CONTROL_ENABLED
        self._attr_is_on = self._read_default()


# ============================================================================
# v5.10.0 D5: Per-person Music Following DND switch
# ============================================================================


def _build_per_person_mf_switches(hass: HomeAssistant, cm_entry: ConfigEntry) -> list:
    """v5.10.0 D5: build one MFPersonFollowSwitch per tracked person.

    Called from the Coordinator Manager entry setup so persons show up on
    the MF Coordinator device (no per-person Person device exists yet —
    critique noted a future migration if/when that changes).

    Reads ``CONF_TRACKED_PERSONS`` from the INTEGRATION entry (set by
    the config-flow → __init__.py :1641 write-back). Returns [] if the
    integration entry isn't yet loaded or has no tracked persons.
    """
    from .const import CONF_TRACKED_PERSONS  # noqa: PLC0415
    tracked: list[str] = []
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
            merged = {**e.data, **e.options}
            tracked = list(merged.get(CONF_TRACKED_PERSONS) or [])
            break
    switches = []
    for person_id in tracked:
        if not isinstance(person_id, str) or not person_id:
            continue
        switches.append(MFPersonFollowSwitch(hass, cm_entry, person_id))
    return switches


class MFPersonFollowSwitch(SwitchEntity, RestoreEntity):
    """v5.10.0 D5: per-person Music Following DND toggle.

    ON  → this person's transitions trigger music transfers (default).
    OFF → the person is removed from MusicFollowing._enabled_persons and
          their transitions do NOT trigger transfers.

    Persistence: RestoreEntity. Guarded against Bug Class #52
    (RestoreEntity unavailable/unknown coercion): if the last-state is
    a transient (unavailable/unknown), we DEFAULT the switch back ON
    (the constructor default), we do NOT force it OFF.

    Device: attached to the MF Coordinator device today. Critique noted a
    future migration to a per-Person device when that device exists.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-music"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, person_id: str
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._person_id = person_id
        # Default ON — matches the __init__.py:1913 auto-enable-for-all.
        self._is_on = True
        # entity_id-safe slug (lowercased with underscores).
        slug = person_id.lower().replace(" ", "_")
        self._attr_unique_id = f"{DOMAIN}_mf_person_follow_{slug}"
        # v5.10.0 fix-up C-L1: with has_entity_name=True + the parent
        # device name ("URA: Music Following Coordinator"), HA prefixes
        # the device name automatically. Emitting "Music Following: X"
        # here produced "Music Following Coordinator Music Following: X".
        # Just the person_id keeps the friendly name clean.
        self._attr_name = person_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "music_following_coordinator")},
            name="URA: Music Following Coordinator",
            manufacturer="Universal Room Automation",
            model="Music Following Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_mf(self):
        return self.hass.data.get(DOMAIN, {}).get("music_following")

    def _write_pref(self, mf, value: bool) -> None:
        """v5.10.0 fix-up FIX-5 (B-HIGH-1): write per-person follow pref
        into the MusicFollowing singleton's authoritative pref dict.
        Prefs are the SINGLE source of truth for per-person enable
        state and survive coordinator reloads (the singleton persists).
        """
        try:
            prefs = getattr(mf, "_person_follow_prefs", None)
            if isinstance(prefs, dict):
                prefs[self._person_id] = bool(value)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "MFPersonFollowSwitch(%s): pref write failed",
                self._person_id, exc_info=True,
            )

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        mf = self._get_mf()
        if mf is not None:
            try:
                mf.enable_for_person(self._person_id)
                self._write_pref(mf, True)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "enable_for_person(%s) failed", self._person_id, exc_info=True
                )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        mf = self._get_mf()
        if mf is not None:
            try:
                mf.disable_for_person(self._person_id)
                self._write_pref(mf, False)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "disable_for_person(%s) failed", self._person_id, exc_info=True
                )
        self.async_write_ha_state()

    async def _apply_restore_to_singleton(self, _now=None) -> None:
        """v5.10.0 fix-up FIX-5 (C-H1): deferred re-apply of restored
        state to the MusicFollowing singleton.

        On restart the switch's async_added_to_hass fires before the
        integration finishes initialising the MusicFollowing singleton
        (registered at __init__.py:1910). Retrying every 5s (capped)
        keeps the pref-write in sync with the singleton's arrival
        without depending on a signal that doesn't exist for MF-ready.
        """
        mf = self._get_mf()
        if mf is not None:
            try:
                if self._is_on:
                    mf.enable_for_person(self._person_id)
                else:
                    mf.disable_for_person(self._person_id)
                self._write_pref(mf, self._is_on)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "MFPersonFollowSwitch(%s) deferred restore→singleton failed",
                    self._person_id, exc_info=True,
                )
            return
        # MF still not up — schedule another retry (max 12 attempts = 60s).
        self._deferred_attempts = getattr(self, "_deferred_attempts", 0) + 1
        if self._deferred_attempts >= 12:
            _LOGGER.debug(
                "MFPersonFollowSwitch(%s): giving up on deferred restore "
                "after %d retries; sync_enabled_persons will reconcile on "
                "next coord setup",
                self._person_id, self._deferred_attempts,
            )
            return
        try:
            from homeassistant.helpers.event import async_call_later
            # v5.10.0 re-review follow-up: track the retry so teardown
            # cancels it (Bug Class #34 — untracked deferred callback).
            self.async_on_remove(
                async_call_later(self.hass, 5, self._apply_restore_to_singleton)
            )
        except Exception:  # noqa: BLE001
            pass

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        # Bug Class #52 guard — treat transient last_state as "keep default".
        if last_state is None or last_state.state not in ("on", "off"):
            if last_state is not None and last_state.state in ("unavailable", "unknown"):
                _LOGGER.info(
                    "MFPersonFollowSwitch(%s): last_state=%s treated as OFF-but-log "
                    "(Bug Class #52 guard) — keeping constructor default ON",
                    self._person_id, last_state.state,
                )
            # Apply constructor default to the singleton.
            mf = self._get_mf()
            if mf is not None and self._is_on:
                try:
                    mf.enable_for_person(self._person_id)
                    self._write_pref(mf, True)
                except Exception:  # noqa: BLE001
                    pass
            elif mf is None:
                # v5.10.0 fix-up FIX-5 (C-H1): MF not up yet — schedule
                # deferred re-apply.
                await self._apply_restore_to_singleton()
            return
        self._is_on = last_state.state == "on"
        mf = self._get_mf()
        if mf is None:
            # v5.10.0 fix-up FIX-5 (C-H1): defer until MF singleton is up.
            await self._apply_restore_to_singleton()
            return
        try:
            if self._is_on:
                mf.enable_for_person(self._person_id)
            else:
                mf.disable_for_person(self._person_id)
            self._write_pref(mf, self._is_on)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "MFPersonFollowSwitch(%s) restore→singleton failed",
                self._person_id, exc_info=True,
            )


# ============================================================================
# Exterior track linker control surface (build/exterior-track, 2026-08-06)
# ============================================================================


class _ExteriorLinkerSwitchBase(SwitchEntity, RestoreEntity):
    """Base for the two exterior-linker switches (operator-named).

    Default ON. Restore-"off"-only (unavailable/unknown never poisons —
    Bug Class #52). The linker is created in async_setup_entry BEFORE
    platforms forward (see __init__.py ordering), so restore applies
    directly — no deferred-signal machinery needed (unlike the presence
    kill switches, whose coordinator races platform setup).
    suppressed_since carries the operator's original OFF time across
    restarts (notification-hygiene precedent).
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    # Subclasses set: unique-id suffix, name, icon, backing flag + since attr.
    _flag_attr: str = ""
    _since_attr: str = ""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "security_coordinator")},
            name="URA: Security Coordinator",
            manufacturer="Universal Room Automation",
            model="Security Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_linker(self):
        return self.hass.data.get(DOMAIN, {}).get("exterior_track_linker")

    @property
    def available(self) -> bool:
        return self._get_linker() is not None

    @property
    def is_on(self) -> bool:
        linker = self._get_linker()
        if linker is None:
            return True  # default-ON story; available=False masks this anyway
        return bool(getattr(linker, self._flag_attr, True))

    @property
    def extra_state_attributes(self) -> dict:
        linker = self._get_linker()
        since = getattr(linker, self._since_attr, None) if linker else None
        return {"suppressed_since": since} if since else {}

    async def async_turn_on(self, **kwargs) -> None:
        linker = self._get_linker()
        if linker is not None:
            setattr(linker, self._flag_attr, True)
            setattr(linker, self._since_attr, None)
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        linker = self._get_linker()
        if linker is not None:
            setattr(linker, self._flag_attr, False)
            from homeassistant.util import dt as _dtu
            setattr(linker, self._since_attr, _dtu.utcnow().isoformat())
            self._on_turned_off(linker)
            self.async_write_ha_state()

    def _on_turned_off(self, linker) -> None:
        """Subclass hook — fire-axe drains open tracks (MEDIUM-1)."""

    def _apply_off(self, linker, prior_since=None) -> None:
        setattr(linker, self._flag_attr, False)
        if prior_since:
            setattr(linker, self._since_attr, prior_since)
        else:
            from homeassistant.util import dt as _dtu
            setattr(linker, self._since_attr, _dtu.utcnow().isoformat())
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # LOW-1: the linker lives on the INTEGRATION entry; these switches
        # live on the CM entry — sibling entries can set up concurrently,
        # so a persisted OFF must be able to defer on the ready signal.
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_EXTERIOR_LINKER_READY
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_EXTERIOR_LINKER_READY,
                self._handle_linker_ready,
            )
        )
        last_state = await self.async_get_last_state()
        # Restore-"off"-only: ON is the coordinator default; unavailable /
        # unknown / missing restore never flips the feature off (#52).
        if last_state is None or last_state.state != "off":
            return
        prior_since = last_state.attributes.get("suppressed_since")
        linker = self._get_linker()
        if linker is None:
            # Defer: apply when SIGNAL_EXTERIOR_LINKER_READY fires.
            self._deferred_off_since = prior_since or ""
            return
        self._apply_off(linker, prior_since)

    _deferred_off_since = None  # str | None (py39-exec-safe: no PEP604 at class level)

    def _handle_linker_ready(self) -> None:
        if self._deferred_off_since is None:
            return
        linker = self._get_linker()
        if linker is None:
            return  # stay armed for a later dispatch
        prior = self._deferred_off_since or None
        self._deferred_off_since = None
        self._apply_off(linker, prior)


class ExteriorPathTrackingSwitch(_ExteriorLinkerSwitchBase):
    """Fire axe: OFF = no tracks, census zeroed, narrative/severity inert —
    per-camera alerting byte-identical to the no-linker baseline."""

    _attr_icon = "mdi:map-marker-path"
    _flag_attr = "tracking_enabled"
    _since_attr = "tracking_suppressed_since"

    def _on_turned_off(self, linker) -> None:
        # MEDIUM-1: fire axe is instantaneous — drain all open tracks so
        # census zeroes NOW and in-flight tracks write their episodes.
        try:
            linker.drain_open_tracks(reason="operator_off")
        except Exception:  # noqa: BLE001 — switch flip must never raise
            pass

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_exterior_path_tracking"
        self._attr_name = "Exterior Path Tracking"


class PathAwareNotificationsSwitch(_ExteriorLinkerSwitchBase):
    """Judgment layer only: OFF = classic per-camera severity (LOUDER,
    never silent); tracking, census and path narratives keep running."""

    _attr_icon = "mdi:bell-badge"
    _flag_attr = "smart_alerts_enabled"
    _since_attr = "smart_alerts_suppressed_since"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_path_aware_notifications"
        self._attr_name = "Path Aware Notifications"


class HvacOffphaseHonestyEnabledSwitch(SwitchEntity, RestoreEntity):
    """HVAC-PRESET-FLAP-1 D4: Duty Off-Phase Honesty kill-switch.

    When ON (default): the D5 duty limiter in occupied zones routes the
    off-phase write through `emit_set_temperature` at
    `home_target_high + COMFORT_OFFPHASE_OFFSET_F` instead of forcing
    `preset=away` (S14 path).
    When OFF: the D5 else-limb takes the kill-switch dominance
    short-circuit and writes `effective_preset = "away"` — byte-identical
    pre-cycle behavior.

    Entity: switch.ura_hvac_coordinator_offphase_honesty_enabled
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:snowflake-check"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_offphase_honesty_enabled"
        # Operator-renamed 2026-08-14 ("Coast Preset Preservation") — the
        # old label described the design debate, not the behavior. unique_id
        # unchanged (entity_id stable); friendly name only.
        self._attr_name = "Coast Preset Preservation"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
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
            return True
        try:
            return bool(hvac.hvac_offphase_honesty_enabled)
        except Exception:  # noqa: BLE001
            return True

    async def async_turn_on(self, **kwargs) -> None:
        hvac = self._get_hvac()
        if hvac is not None:
            try:
                hvac.hvac_offphase_honesty_enabled = True
            except Exception:  # noqa: BLE001
                pass
            self._deferred_value = None
            self.async_write_ha_state()
            _LOGGER.info("HVAC-PRESET-FLAP-1: Duty Off-Phase Honesty enabled")
        try:
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **self._entry.options,
                    "hvac_offphase_honesty_enabled": True,
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "HvacOffphaseHonesty options-writeback failed", exc_info=True,
            )

    async def async_turn_off(self, **kwargs) -> None:
        hvac = self._get_hvac()
        if hvac is not None:
            try:
                hvac.hvac_offphase_honesty_enabled = False
            except Exception:  # noqa: BLE001
                pass
            self._deferred_value = None
            self.async_write_ha_state()
            _LOGGER.warning(
                "HVAC-PRESET-FLAP-1: Duty Off-Phase Honesty DISABLED — "
                "occupied zones will fall through to preset=away during "
                "the off-phase (pre-cycle behavior)."
            )
        try:
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **self._entry.options,
                    "hvac_offphase_honesty_enabled": False,
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "HvacOffphaseHonesty options-writeback failed", exc_info=True,
            )

    async def async_added_to_hass(self) -> None:
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
            return
        target = last_state.state == "on"
        hvac = self._get_hvac()
        if hvac is not None:
            try:
                hvac.hvac_offphase_honesty_enabled = target
            except Exception:  # noqa: BLE001
                pass
            self._deferred_value = None
            self.async_write_ha_state()
            return
        self._deferred_value = target

    @callback
    def _handle_hvac_ready(self) -> None:
        if self._deferred_value is None:
            return
        hvac = self._get_hvac()
        if hvac is None:
            return
        try:
            hvac.hvac_offphase_honesty_enabled = self._deferred_value
        except Exception:  # noqa: BLE001
            pass
        self._deferred_value = None
        self.async_write_ha_state()
