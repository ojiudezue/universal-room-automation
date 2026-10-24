"""Halo S1b: NM wall-panel channel entities (WALLPANEL-URA-NOTIFY-1).

``switch.ura_nm_panel_channel`` (rung 3, default OFF, RestoreEntity) — opt-in
for the NM "panels" channel. Off = no halo.* call, no listener, no row;
turning it off releases every lease owned by ``ura``.

``number.ura_nm_panel_lease_ttl_min`` (rung 3, default 30, 1-240 min,
RestoreEntity) — lease length; bounds a lost release.

Both live on the Notification Manager device and push their value into NM,
retrying while NM is not yet constructed (same bounded retry as
``NMDryRunSwitch``). Kept in their own module so switch.py / number.py only
register them.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.restore_state import RestoreEntity

from ._devices import _nm_device_info
from .const import (
    DOMAIN,
    NM_PANEL_LEASE_TTL_MIN_DEFAULT,
    NM_PANEL_LEASE_TTL_MIN_MAX,
    NM_PANEL_LEASE_TTL_MIN_MIN,
)

_LOGGER = logging.getLogger(__name__)

# Bounded wait for NM at boot: 18 x 10 s = 3 min (mirrors NMDryRunSwitch).
_NM_SYNC_MAX_RETRIES = 18
_NM_SYNC_RETRY_S = 10


class _NMSyncMixin:
    """Push the entity's value into NM; retry while NM is not built yet."""

    hass: HomeAssistant
    _sync_retries: int
    _sync_unsub: Any

    def _get_nm(self):
        return self.hass.data.get(DOMAIN, {}).get("notification_manager")

    async def _push(self, nm) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    async def _sync_to_nm(self) -> None:
        nm = self._get_nm()
        if nm is None:
            self._sync_retries += 1
            if self._sync_retries > _NM_SYNC_MAX_RETRIES:
                _LOGGER.warning(
                    "NM not available after %d retries — %s not synced",
                    self._sync_retries, type(self).__name__,
                )
                return

            async def _deferred_sync(_now=None):
                self._sync_unsub = None
                await self._sync_to_nm()

            self._sync_unsub = async_call_later(
                self.hass, _NM_SYNC_RETRY_S, _deferred_sync,
            )
            return
        self._sync_retries = 0
        await self._push(nm)

    async def async_will_remove_from_hass(self) -> None:
        if self._sync_unsub:
            self._sync_unsub()
            self._sync_unsub = None


class NMPanelChannelSwitch(_NMSyncMixin, SwitchEntity, RestoreEntity):
    """Opt-in for the NM wall-panel (Halo) channel. Default OFF."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:tablet-dashboard"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._sync_retries = 0
        self._sync_unsub = None
        self._is_on = False
        self._attr_unique_id = f"{DOMAIN}_nm_panel_channel"
        self._attr_name = "Wall Panel Channel"
        self.entity_id = "switch.ura_nm_panel_channel"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._is_on = last_state.state == "on"
        await self._sync_to_nm()

    async def _push(self, nm) -> None:
        await nm.async_set_panel_channel_enabled(self._is_on)

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def _set(self, value: bool) -> None:
        self._is_on = value
        self._sync_retries = 0
        await self._sync_to_nm()
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)


class NMPanelLeaseTtlNumber(_NMSyncMixin, NumberEntity, RestoreEntity):
    """Panel lease TTL (minutes). Bounds how long a lost release can show."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-sand"
    _attr_native_step = 1
    _attr_native_min_value = NM_PANEL_LEASE_TTL_MIN_MIN
    _attr_native_max_value = NM_PANEL_LEASE_TTL_MIN_MAX
    _attr_native_unit_of_measurement = "min"
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._sync_retries = 0
        self._sync_unsub = None
        self._value = float(NM_PANEL_LEASE_TTL_MIN_DEFAULT)
        self._attr_unique_id = f"{DOMAIN}_nm_panel_lease_ttl_min"
        self._attr_name = "Wall Panel Lease TTL"
        self.entity_id = "number.ura_nm_panel_lease_ttl_min"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            try:
                restored = float(last_state.state)
            except (TypeError, ValueError):
                restored = None
            if restored is not None and (
                NM_PANEL_LEASE_TTL_MIN_MIN <= restored <= NM_PANEL_LEASE_TTL_MIN_MAX
            ):
                self._value = restored
        await self._sync_to_nm()

    async def _push(self, nm) -> None:
        nm.set_panel_lease_ttl_min(self._value)

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = float(value)
        self._sync_retries = 0
        await self._sync_to_nm()
        self.async_write_ha_state()
