"""EC-LOADED-VS-INSTALLED-VERSION-1 — loaded vs installed version check.

Loaded version = ``const.VERSION`` (the code actually running; also the
DeviceInfo ``sw_version``). Installed version = ``version`` in this
integration's ``manifest.json`` on disk. After a deploy installs new files
but before HA restarts, the two differ and live checks silently read old
code. This raises ONE informational Repairs issue while they differ and
deletes it when they match.

Deploys intentionally decouple install from restart (no HA restart while the
house sleeps), so a mismatch is a normal, expected state — the issue is
informational (WARNING, not fixable), never an error. Never raises.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN, VERSION, VERSION_CHECK_INTERVAL_S

_LOGGER = logging.getLogger(__name__)

ISSUE_ID = "restart_pending_version_mismatch"
DATA_KEY = "version_status"
MANIFEST_PATH = Path(__file__).parent / "manifest.json"


def normalize_version(value: Any) -> str | None:
    """Strip whitespace and a leading 'v'/'V'; None/blank -> None."""
    if value is None:
        return None
    text = str(value).strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    return text or None


def _read_manifest_version(path: Path) -> str | None:
    """Blocking read — must run in the executor."""
    try:
        with open(path, encoding="utf-8") as fh:
            return normalize_version(json.load(fh).get("version"))
    except Exception:  # noqa: BLE001
        _LOGGER.debug("version check: manifest unreadable at %s", path, exc_info=True)
        return None


async def async_check_version(
    hass: HomeAssistant, manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Compare loaded vs installed; create/delete the repair issue. Never raises."""
    loaded = normalize_version(VERSION)
    installed: str | None = None
    try:
        installed = await hass.async_add_executor_job(
            _read_manifest_version, manifest_path or MANIFEST_PATH,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("version check: executor read failed", exc_info=True)
    restart_pending = installed is not None and installed != loaded
    status = {
        "loaded_version": loaded,
        "installed_version": installed,
        "restart_pending": restart_pending,
    }
    try:
        hass.data.setdefault(DOMAIN, {})[DATA_KEY] = status
        if installed is None:
            return status  # unknown -> no-op; leave any existing issue alone
        if restart_pending:
            ir.async_create_issue(
                hass,
                DOMAIN,
                ISSUE_ID,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_ID,
                translation_placeholders={
                    "loaded": loaded or "",
                    "installed": installed,
                },
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, ISSUE_ID)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("version check: issue update failed", exc_info=True)
    return status


async def async_start_version_check(hass: HomeAssistant, entry: Any) -> None:
    """Run once now, then every VERSION_CHECK_INTERVAL_S; unsub on unload."""
    await async_check_version(hass)

    async def _tick(_now: Any) -> None:
        await async_check_version(hass)

    entry.async_on_unload(
        async_track_time_interval(
            hass, _tick, timedelta(seconds=VERSION_CHECK_INTERVAL_S),
        )
    )
