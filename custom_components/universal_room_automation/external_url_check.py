"""External-URL reachability self-check (v5.107.3).

Pushover and the companion app send notification image *links* built from
HA's ``external_url`` (notification_manager / perimeter_alert._absolutize);
WhatsApp and iMessage attach the file, so a dead external URL went unnoticed
for weeks. This check GETs ``<external_url>/manifest.json`` from the HA host
(shared aiohttp session, short timeout, no auth) once HA has started and then
daily. Unreachable (timeout / DNS / connection error / non-2xx) -> one
Repairs issue; reachable -> the issue is deleted. external_url unset -> no-op
(debug log only). Never raises.

Pattern REUSED from version_check.py (issue create/delete) and
__init__._schedule_ec_role_scan (async_at_started + interval, both unsubs on
the owning entry).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOMAIN,
    EXTERNAL_URL_CHECK_INTERVAL_S,
    EXTERNAL_URL_CHECK_TIMEOUT_S,
)

_LOGGER = logging.getLogger(__name__)

ISSUE_ID = "external_url_unreachable"
PROBE_PATH = "/manifest.json"


async def _async_probe(hass: HomeAssistant, url: str) -> tuple[bool, str]:
    """GET url; return (reachable, reason). Never raises."""
    try:
        import aiohttp  # noqa: PLC0415
        from homeassistant.helpers.aiohttp_client import (  # noqa: PLC0415
            async_get_clientsession,
        )

        session = async_get_clientsession(hass)
        timeout = aiohttp.ClientTimeout(total=EXTERNAL_URL_CHECK_TIMEOUT_S)
        async with session.get(
            url, timeout=timeout, allow_redirects=True,
        ) as resp:
            if 200 <= resp.status < 300:
                return True, f"HTTP {resp.status}"
            return False, f"HTTP {resp.status}"
    except Exception as err:  # noqa: BLE001 — timeout, DNS, TLS, refused
        return False, type(err).__name__


async def async_check_external_url(hass: HomeAssistant) -> dict[str, Any]:
    """Probe external_url; create/delete the repair issue. Never raises."""
    external_url = getattr(hass.config, "external_url", None)
    if not external_url:
        _LOGGER.debug("external URL check: external_url unset, skipping")
        return {"external_url": None, "reachable": None, "reason": "unset"}
    base = str(external_url).rstrip("/")
    reachable, reason = await _async_probe(hass, base + PROBE_PATH)
    status = {"external_url": base, "reachable": reachable, "reason": reason}
    try:
        if reachable:
            ir.async_delete_issue(hass, DOMAIN, ISSUE_ID)
        else:
            _LOGGER.warning(
                "External URL %s is not reachable (%s); notification image "
                "links will be broken", base, reason,
            )
            ir.async_create_issue(
                hass,
                DOMAIN,
                ISSUE_ID,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_ID,
                translation_placeholders={"url": base, "reason": reason},
            )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("external URL check: issue update failed", exc_info=True)
    return status


def async_start_external_url_check(hass: HomeAssistant, entry: Any) -> None:
    """Defer the first check until HA has started, then repeat daily.

    The interval is armed (and registered on the entry) BEFORE the first
    probe awaits, so an unload during that probe still cancels it.
    """
    from homeassistant.helpers.start import async_at_started  # noqa: PLC0415

    async def _tick(_now: Any) -> None:
        await async_check_external_url(hass)

    async def _at_started(_hass: HomeAssistant) -> None:
        entry.async_on_unload(
            async_track_time_interval(
                hass, _tick, timedelta(seconds=EXTERNAL_URL_CHECK_INTERVAL_S),
            )
        )
        await async_check_external_url(hass)

    entry.async_on_unload(async_at_started(hass, _at_started))
