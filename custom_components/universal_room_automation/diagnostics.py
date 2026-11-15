"""Config-entry diagnostics download (person-awareness layer ship 3a D5).

HA's diagnostics integration discovers this platform and calls
``async_get_config_entry_diagnostics`` when the operator downloads a config
entry's diagnostics (Settings > Devices & services > URA > the entry's menu).

The download is on demand: nothing is written, recorded or sent. It returns
ONLY the person-awareness layer counters
(``PresenceCoordinator.get_layer_diagnostics``) under the key
``person_awareness_layer``, for the coordinator-manager entry, plus (ship 3b,
while the camera twin owner exists) its counters under ``camera_twin_health``
(``CameraTwinHealth.get_diagnostic_counters``: counts only, no entity or
device ids); room, zone and integration entries return an empty dict. It never includes config-entry
``data`` / ``options`` (they can hold credentials and API keys), entity
states or person-coordinator ``.data``. Any key added here later must go
through ``homeassistant.components.diagnostics.async_redact_data`` with an
explicit redact list.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_COORDINATOR_MANAGER

DIAGNOSTICS_LAYER_KEY = "person_awareness_layer"
# Ship 3b: the camera twin owner's counters (``CameraTwinHealth.
# get_diagnostic_counters``: counts only, the same no-config / no-state /
# no-id rule). Present only while the owner exists.
DIAGNOSTICS_TWIN_KEY = "camera_twin_health"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry,
) -> dict[str, Any]:
    """Layer counters for the coordinator-manager entry, else ``{}``."""
    try:
        if (entry.data or {}).get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COORDINATOR_MANAGER:
            return {}
    except Exception:  # noqa: BLE001
        return {}
    layer: dict[str, Any] = {}
    try:
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        presence = manager.coordinators.get("presence") if manager is not None else None
        if presence is not None:
            layer = dict(presence.get_layer_diagnostics())
    except Exception:  # noqa: BLE001 - a download must never raise
        layer = {}
    out: dict[str, Any] = {DIAGNOSTICS_LAYER_KEY: layer}
    try:
        owner = hass.data.get(DOMAIN, {}).get(DIAGNOSTICS_TWIN_KEY)
        if owner is not None and not getattr(owner, "torn_down", False):
            out[DIAGNOSTICS_TWIN_KEY] = dict(owner.get_diagnostic_counters())
    except Exception:  # noqa: BLE001 - a download must never raise
        pass
    return out
