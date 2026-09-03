"""Time platform for Universal Room Automation.

evse-charge-onset cycle (D1b) — live-tunable dashboard entity for the
overnight EV charge-onset gate. Mirrors the OffPeakDrainNumber
post-v4.7.26 pattern (number.py:1036+):

  * `entry.options` is the SOLE source of truth (no `RestoreEntity`).
  * Seed on `__init__` from `{**entry.data, **entry.options}`.
  * `async_set_value` pushes to the EC setter BEFORE `async_update_entry`
    so the next decision tick sees the new value even if the options
    listener is still in flight.
  * CONF key is in the CM reload-suppression allowlist
    (`OPTIONS_RELOAD_SUPPRESS_KEYS` in `__init__.py`) AND routed via
    `_EC_SETTER_DISPATCH`, so an options edit — whether from THIS
    entity or from the config-flow TimeSelector — lands via
    `set_ev_charge_onset_time` on the coord without a full CM reload.
    Rev-6 B-MED-1 fix: this entity ALSO subscribes to
    `SIGNAL_ENERGY_ENTITIES_UPDATE` and re-reads `entry.options` on
    signal so a config-flow-form edit propagates back to THIS entity's
    displayed value (otherwise the entity would be stale while the
    coord was correctly updated).

The blank / disabled state is represented as `native_value = None`
(HA renders empty on the dashboard). Setting `None` clears the onset
knob (feature off). Any parse failure downstream (`_parse_hhmm`) is
treated as blank (permissive: gate disabled).
"""
from __future__ import annotations

import datetime as _dt
import logging

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONF_ENTRY_TYPE,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    VERSION,
)
from .domain_coordinators.energy_const import (
    CONF_ENERGY_EVSE_CHARGE_ONSET_TIME,
    DEFAULT_ENERGY_EVSE_CHARGE_ONSET_TIME,
)

_LOGGER = logging.getLogger(__name__)


def _parse_hhmm_to_time(value: str | None) -> _dt.time | None:
    """Parse "HH:MM" or "HH:MM:SS" into `datetime.time`, else None.

    Rev-6 A-HIGH-1 / C-HIGH-3 fix: HA's `selector.TimeSelector` and
    `TimeEntity.set_value` both emit the value as a 3-part "HH:MM:SS"
    string (core `helpers/selector.py::TimeSelector` returns
    `time.isoformat()` which always includes seconds). The Rev-5 parser
    rejected any string with a seconds component, silently disabling the
    feature the moment an operator saved the config-flow form. Kept
    local to time.py (mirror of `energy_pool._parse_hhmm`) so this
    platform has no cross-module coupling on the parser beyond the
    coord setter itself. Seconds are DROPPED — drain releases are
    minute-precision.
    """
    if not value or not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        hh = int(parts[0])
        mm = int(parts[1])
        if len(parts) == 3:
            ss = int(parts[2])
            if not (0 <= ss <= 59):
                return None
    except (TypeError, ValueError):
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return _dt.time(hour=hh, minute=mm)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Universal Room Automation time entities.

    Today only the Coordinator Manager entry hosts time entities (the
    EV charge-onset knob is EC-global, not per-room). Room / zone
    entries add nothing on this platform.
    """
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
        async_add_entities([EVChargeOnsetTimeEntity(hass, entry)])


class EVChargeOnsetTimeEntity(TimeEntity):
    """Live-tunable EV overnight charge-onset time.

    Dashboard companion to the config-flow TimeSelector at
    config_flow.py (see `CONF_ENERGY_EVSE_CHARGE_ONSET_TIME` field).
    Blank/None ⇒ feature disabled (overnight release fires immediately,
    byte-identical to pre-cycle behavior). Default: "01:00" local.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:ev-station"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_energy_evse_charge_onset_time"
        self._attr_name = "EV Charge Onset Time"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
        )
        # Seed from entry.options (sole source of truth per D1). Default
        # "01:00" ACTIVE — feature is on out-of-the-box; the operator
        # explicitly clears the field to disable.
        config = {**entry.data, **(entry.options or {})}
        raw = config.get(
            CONF_ENERGY_EVSE_CHARGE_ONSET_TIME,
            DEFAULT_ENERGY_EVSE_CHARGE_ONSET_TIME,
        )
        self._value: _dt.time | None = _parse_hhmm_to_time(raw)

    def _get_energy(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    @property
    def native_value(self) -> _dt.time | None:
        return self._value

    @property
    def available(self) -> bool:
        # Time entities are always available even if the coord isn't yet
        # constructed — the knob is a value that persists on entry.options.
        # (Mirrors OffPeakDrainNumber which gates on coord availability;
        # here we prefer "always available" so operator can pre-set the
        # onset during setup, before coord init completes.)
        return True

    async def async_added_to_hass(self) -> None:
        """Push the seeded value into the live coord if reachable.

        Also subscribes to `SIGNAL_ENERGY_ENTITIES_UPDATE` (Rev-6 B-MED-1)
        so a config-flow-form edit — which lands in `entry.options` and
        pushes to the coord via `_EC_SETTER_DISPATCH` — refreshes THIS
        entity's displayed value too (otherwise dashboard shows stale).
        """
        await super().async_added_to_hass()
        energy = self._get_energy()
        if energy is not None:
            try:
                raw = self._value.strftime("%H:%M") if self._value else None
                energy.set_ev_charge_onset_time(raw)
            except Exception:  # noqa: BLE001 — coord may be mid-init
                _LOGGER.debug(
                    "EVChargeOnsetTime seed-push deferred", exc_info=True,
                )

        # B-MED-1: re-read entry.options on the shared EC entities signal
        # (mirrors the DP-enable precedent in __init__.py ~:6690 that
        # pings all switch subscribers). Any options-flow edit that
        # landed via _apply_in_place will already have pushed to the
        # coord; here we just refresh our local display.
        try:
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            from .domain_coordinators.signals import SIGNAL_ENERGY_ENTITIES_UPDATE

            def _refresh(*_args) -> None:
                opts = self._entry.options or {}
                raw = opts.get(CONF_ENERGY_EVSE_CHARGE_ONSET_TIME)
                self._value = _parse_hhmm_to_time(raw) if raw else None
                self.async_write_ha_state()

            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass, SIGNAL_ENERGY_ENTITIES_UPDATE, _refresh,
                )
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "EVChargeOnsetTime signal wire-up failed (swallowed)",
                exc_info=True,
            )

    async def async_set_value(self, value: _dt.time | None) -> None:
        """Persist a new onset. `value=None` disables the gate.

        Order (mirror OffPeakDrainNumber pattern, number.py:1126-1163):
          1. Update RAM `_value`.
          2. Push to coord setter FIRST — next decision tick picks up the
             new value even if the options-update listener is still in
             flight.
          3. Persist into entry.options (source of truth). CM reload is
             SUPPRESSED for this CONF key via `_EC_SETTER_DISPATCH`;
             the config-flow TimeSelector reads the same key on its
             next render, so both surfaces stay in sync.
          4. `async_write_ha_state()` to reflect the new dashboard value.
        """
        self._value = value  # `datetime.time | None`
        raw = value.strftime("%H:%M") if value else None
        energy = self._get_energy()
        if energy is not None:
            try:
                energy.set_ev_charge_onset_time(raw)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "EVChargeOnsetTime coord push failed", exc_info=True,
                )
        # Persist into entry.options. Empty string = "disabled" — same
        # sentinel the config-flow default uses and the coord setter
        # interprets as None.
        try:
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **(self._entry.options or {}),
                    CONF_ENERGY_EVSE_CHARGE_ONSET_TIME: raw if raw else "",
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "EVChargeOnsetTime options-writeback failed", exc_info=True,
            )
        self.async_write_ha_state()
        _LOGGER.info("EV charge-onset time set to %r via time entity", raw)
