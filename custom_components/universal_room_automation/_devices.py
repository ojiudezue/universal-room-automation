"""Device-info helpers + device-tree stamping (v5.94.0 device/entity de-frag).

Centralises DeviceInfo authoring for identities the plan explicitly scopes:
- `music_following_coordinator`
- `notification_manager`

Also exposes `_coordinator_device_info(coordinator_id)` — a dispatcher used
by `domain_coordinators/base.py` to eliminate the "Domain Coordinator" model
first-writer-wins race (D3), and `async_stamp_via_device_tree(hass)` — the
post-setup `dr.async_update_device(via_device_id=...)` stamper that restores
device-tree nesting without touching the banned DeviceInfo.via_device kwarg
(D-NEST).

D4 baked as Option 3: rooms untouched; "URA:" prefix stays on coordinator
devices as historically authored (unique_id-safe re-home requires that names
remain unchanged for now).
"""
from __future__ import annotations

import logging
from typing import Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)

# D-NEST kill switch. Flip to False in a hotfix if the stamper misbehaves.
URA_DEVICE_TREE_STAMPING_ENABLED: Final = True

# D4 Option 3: canonical (name, model) for the identities we author.
# Kept as data so tests can diff without importing the helpers.
DEVICE_NAMES: Final[dict[str, str]] = {
    "integration": "Universal Room Automation",
    "coordinator_manager": "URA: Coordinator Manager",
    "zone_manager": "URA: Zone Manager",
    "safety_coordinator": "URA: Safety Coordinator",
    "security_coordinator": "URA: Security Coordinator",
    "presence_coordinator": "URA: Presence Coordinator",
    "energy_coordinator": "URA: Energy Coordinator",
    "hvac_coordinator": "URA: HVAC Coordinator",
    "optimization_coordinator": "URA: Optimization Coordinator",
    "music_following_coordinator": "URA: Music Following Coordinator",
    "notification_manager": "URA: Notification Manager",
}
DEVICE_MODELS: Final[dict[str, str]] = {
    "integration": "Whole House",
    "coordinator_manager": "Coordinator Manager",
    "zone_manager": "Zone Manager",
    "safety_coordinator": "Safety Coordinator",
    "security_coordinator": "Security Coordinator",
    "presence_coordinator": "Presence Coordinator",
    "energy_coordinator": "Energy Coordinator",
    "hvac_coordinator": "HVAC Coordinator",
    "optimization_coordinator": "Optimization Coordinator",
    "music_following_coordinator": "Music Following Coordinator",
    "notification_manager": "Notification Manager",
}


def _music_following_device_info() -> DeviceInfo:
    """Canonical DeviceInfo for the Music Following Coordinator device (D2)."""
    return DeviceInfo(
        identifiers={(DOMAIN, "music_following_coordinator")},
        name=DEVICE_NAMES["music_following_coordinator"],
        manufacturer="Universal Room Automation",
        model=DEVICE_MODELS["music_following_coordinator"],
        sw_version=VERSION,
    )


def _nm_device_info() -> DeviceInfo:
    """Canonical DeviceInfo for the Notification Manager device (D2)."""
    return DeviceInfo(
        identifiers={(DOMAIN, "notification_manager")},
        name=DEVICE_NAMES["notification_manager"],
        manufacturer="Universal Room Automation",
        model=DEVICE_MODELS["notification_manager"],
        sw_version=VERSION,
    )


def _coordinator_device_info(coordinator_id: str) -> DeviceInfo:
    """Return DeviceInfo for a domain coordinator's device (D3 fix).

    `coordinator_id` is the bare id used by `BaseCoordinator.coordinator_id`
    (e.g. "energy", "hvac", "music_following", "notification_manager",
    "coordinator_manager"). We map to the registry identifier the rest of the
    code uses; NM is a bare identifier, CM is "coordinator_manager", and the
    domain coordinators tack "_coordinator" on the end.
    """
    if coordinator_id == "notification_manager":
        return _nm_device_info()
    if coordinator_id == "music_following":
        return _music_following_device_info()
    if coordinator_id == "coordinator_manager":
        identifier = "coordinator_manager"
    else:
        identifier = f"{coordinator_id}_coordinator"
    name = DEVICE_NAMES.get(
        identifier, f"URA: {coordinator_id.replace('_', ' ').title()} Coordinator"
    )
    model = DEVICE_MODELS.get(
        identifier, f"{coordinator_id.replace('_', ' ').title()} Coordinator"
    )
    return DeviceInfo(
        identifiers={(DOMAIN, identifier)},
        name=name,
        manufacturer="Universal Room Automation",
        model=model,
        sw_version=VERSION,
    )


# ---------------------------------------------------------------------------
# D-NEST — device-tree stamping via dr.async_update_device(via_device_id=...)
# ---------------------------------------------------------------------------

# Static child->parent map (identifier tuples). Room + zone identifiers are
# dynamic (entry_id / zone_<n>) and enumerated at runtime.
PARENT_MAP: Final[dict[tuple[str, str], tuple[str, str]]] = {
    (DOMAIN, "coordinator_manager"): (DOMAIN, "integration"),
    (DOMAIN, "zone_manager"): (DOMAIN, "integration"),
    (DOMAIN, "safety_coordinator"): (DOMAIN, "coordinator_manager"),
    (DOMAIN, "security_coordinator"): (DOMAIN, "coordinator_manager"),
    (DOMAIN, "presence_coordinator"): (DOMAIN, "coordinator_manager"),
    (DOMAIN, "energy_coordinator"): (DOMAIN, "coordinator_manager"),
    (DOMAIN, "hvac_coordinator"): (DOMAIN, "coordinator_manager"),
    (DOMAIN, "optimization_coordinator"): (DOMAIN, "coordinator_manager"),
    (DOMAIN, "music_following_coordinator"): (DOMAIN, "coordinator_manager"),
    (DOMAIN, "notification_manager"): (DOMAIN, "coordinator_manager"),
}

_STATIC_CHILD_IDS: Final[frozenset[str]] = frozenset(
    ident for (_dom, ident) in PARENT_MAP.keys()
)


def _resolve_parent_identifier(
    identifier: tuple[str, str],
) -> tuple[str, str] | None:
    """Return the parent identifier for a URA device identifier, or None if root."""
    if identifier[0] != DOMAIN:
        return None
    _, ident = identifier
    if ident == "integration":
        return None  # root
    if identifier in PARENT_MAP:
        return PARENT_MAP[identifier]
    # Dynamic: zone_<n> -> zone_manager; anything else non-static -> integration
    # (room devices use entry_id as their identifier — unpredictable).
    if ident.startswith("zone_") and ident != "zone_manager":
        return (DOMAIN, "zone_manager")
    if ident not in _STATIC_CHILD_IDS:
        return (DOMAIN, "integration")
    return None


async def async_stamp_via_device_tree(hass: HomeAssistant) -> int:
    """Restore device-tree nesting for URA-owned devices (D-NEST).

    Called AFTER `async_forward_entry_setups` from each entry's
    `async_setup_entry`. Uses `dr.async_update_device(via_device_id=...)`
    — the sanctioned post-creation API — instead of the banned
    `DeviceInfo(via_device=...)` kwarg that HA 2026.9 removes.

    Idempotent: skips devices whose `via_device_id` already matches. Returns
    the count of devices actually updated (for logging + tests).
    """
    if not URA_DEVICE_TREE_STAMPING_ENABLED:
        return 0

    dev_reg = dr.async_get(hass)
    updates = 0
    # Snapshot device iterable — we may mutate via_device_id during iteration.
    devices = list(dev_reg.devices.values())
    # Build identifier -> device_id index for URA-owned devices only.
    ura_index: dict[tuple[str, str], str] = {}
    for device in devices:
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:
                ura_index[identifier] = device.id

    for identifier, device_id in ura_index.items():
        parent_ident = _resolve_parent_identifier(identifier)
        if parent_ident is None:
            continue
        parent_device_id = ura_index.get(parent_ident)
        if parent_device_id is None:
            _LOGGER.debug(
                "device-tree stamp: parent %s not yet registered for child %s",
                parent_ident, identifier,
            )
            continue
        try:
            current = dev_reg.async_get(device_id)
            if current is None or current.via_device_id == parent_device_id:
                continue
            dev_reg.async_update_device(
                device_id, via_device_id=parent_device_id,
            )
            updates += 1
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "device-tree stamp failed for %s -> %s",
                identifier, parent_ident, exc_info=True,
            )

    # HIGH-B3 (2026-09-03): report unresolved-parent COUNT as an INV-4
    # trip-wire. On cold-boot, some room/zone devices may be created after
    # this inline pass runs (concurrent per-entry setup); count them so the
    # once-per-boot async_at_started sweep below has a target to close.
    unresolved = 0
    for identifier, device_id in ura_index.items():
        parent_ident = _resolve_parent_identifier(identifier)
        if parent_ident is None:
            continue
        current = dev_reg.async_get(device_id)
        if current is None or current.via_device_id is None:
            unresolved += 1

    if updates or unresolved:
        _LOGGER.info(
            "D-NEST: stamped via_device_id on %d URA devices; "
            "%d devices still have unresolved parents (retry at HA-started).",
            updates, unresolved,
        )
    return updates


def async_schedule_device_tree_sweep(hass: HomeAssistant) -> None:
    """HIGH-B3 fix (2026-09-03): schedule a ONE-shot device-tree sweep via
    `async_at_started` in addition to inline per-entry stamping.

    Rationale: URA sets up 40+ room + zone + zone_manager + CM + INTEGRATION
    config entries CONCURRENTLY (HA asyncio.gather). An inline stamp from one
    entry\'s setup cannot see devices created after it. This scheduler runs
    ONE cover-all sweep after HA is fully started, when every URA config
    entry has completed forward_entry_setups and every URA device exists.

    Idempotent: `hass.data[DOMAIN]["_device_tree_sweep_scheduled"]` guards
    against multiple schedulings across concurrent CM/INTEGRATION calls.

    At-start sweep logs the residual unresolved-parent count at WARN as an
    INV-4 trip-wire.
    """
    if not URA_DEVICE_TREE_STAMPING_ENABLED:
        return
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_device_tree_sweep_scheduled"):
        return
    domain_data["_device_tree_sweep_scheduled"] = True

    async def _sweep(_now=None) -> None:
        try:
            updates = await async_stamp_via_device_tree(hass)
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "D-NEST at-start sweep raised (non-fatal)", exc_info=True,
            )
            return
        # Post-sweep, count residual unresolved parents.
        try:
            dev_reg = dr.async_get(hass)
            ura_index: dict[tuple[str, str], str] = {}
            for device in list(dev_reg.devices.values()):
                for identifier in device.identifiers:
                    if identifier[0] == DOMAIN:
                        ura_index[identifier] = device.id
            residual = 0
            residual_ids: list[tuple[str, str]] = []
            for identifier, device_id in ura_index.items():
                parent_ident = _resolve_parent_identifier(identifier)
                if parent_ident is None:
                    continue
                current = dev_reg.async_get(device_id)
                if current is None or current.via_device_id is None:
                    residual += 1
                    residual_ids.append(identifier)
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "D-NEST at-start sweep residual-count raised (non-fatal)",
                exc_info=True,
            )
            return
        if residual:
            _LOGGER.warning(
                "D-NEST at-start sweep: %d URA devices still lack via_device_id "
                "(INV-4 trip-wire; identifiers=%s). Sweep stamped %d devices.",
                residual, residual_ids[:10], updates,
            )
        else:
            _LOGGER.info(
                "D-NEST at-start sweep: all URA devices parented; stamped %d "
                "devices this sweep.", updates,
            )

    try:
        from homeassistant.helpers.start import async_at_started
        async_at_started(hass, _sweep)
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "D-NEST: async_at_started scheduling failed (non-fatal)",
            exc_info=True,
        )
