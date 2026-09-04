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


async def async_cleanup_parent_entry_shells(
    hass: HomeAssistant,
    parent_entry_id: str,
    cm_entry_id: str | None = None,
) -> int:
    """v5.94.1 FIX 1: remove empty coord-shell devices on the parent entry.

    After v5.94.0 D-REHOME moved coordinator entities from the parent/
    INTEGRATION entry to the CM entry, HA left an empty device record
    behind on the parent entry (device_registry never auto-removes a
    device when its last entity migrates to a DIFFERENT config entry).
    The parent entry no longer forwards any coordinator platform, so
    removing these shells is DURABLE — nothing recreates them.

    Predicate — ALL THREE must hold to remove:
      1. device carries a URA identifier `(DOMAIN, ident)` with `ident`
         in `_STATIC_CHILD_IDS` (any coord identifier the tree tracks).
      2. `device.config_entries == {parent_entry_id}` — EXACT set
         equality, so a dual-owned device is never demoted.
      3. `er.async_entries_for_device(..., include_disabled_entities=True)`
         returns EMPTY.

    Removal: `dr.async_update_device(id, remove_config_entry_id=...)`.
    HA auto-deletes when that was the sole entry
    (helpers/device_registry.py:1176-1178). Self-verifying: safe no-harm
    if any other entry is attached (demotes instead of deleting).

    Iterates `dev_reg.devices.values()` — never `async_get_device`,
    which returns the identifier-index slot which may resolve to the
    REAL device (same-identifier hazard).

    Returns the number of shell devices actually removed.
    """
    if parent_entry_id is None:
        return 0
    try:
        from homeassistant.helpers import entity_registry as er
    except Exception:  # noqa: BLE001
        return 0
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    removed = 0
    for device in list(dev_reg.devices.values()):
        ura_ident: str | None = None
        for (dom, ident) in device.identifiers:
            if dom == DOMAIN and ident in _STATIC_CHILD_IDS:
                ura_ident = ident
                break
        if ura_ident is None:
            continue
        # SAFETY guard 1 — sole-parent-owner (exact set equality). A
        # membership check could match a dual-owned real device and
        # demote it.
        dev_entries = getattr(device, "config_entries", None)
        if dev_entries != {parent_entry_id}:
            continue
        # SAFETY guard 2 — not-CM-owned. Belt-and-suspenders on top of
        # guard 1: the REAL coord devices are owned by the CM entry
        # (never by the parent alone). If a candidate somehow carries
        # the CM entry, WARN and skip — an unexpected state that must
        # never fall through to deletion.
        if cm_entry_id is not None and cm_entry_id in (dev_entries or set()):
            _LOGGER.warning(
                "v5.94.1 FIX 1: refusing to remove device %s (ident=%s) — "
                "carries CM entry_id %s; unexpected state, failing safe",
                device.id, ura_ident, cm_entry_id,
            )
            continue
        # SAFETY guard 3 — zero entities.
        remaining = er.async_entries_for_device(
            ent_reg, device.id, include_disabled_entities=True,
        )
        if remaining:
            continue
        # Operate by device.id ONLY — never resolve via
        # async_get_device(identifiers=...) which returns the shared
        # index slot (could be the REAL device).
        try:
            dev_reg.async_update_device(
                device.id, remove_config_entry_id=parent_entry_id,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "v5.94.1 FIX 1: shell removal raised for %s (ident=%s)",
                device.id, ura_ident, exc_info=True,
            )
            continue
        removed += 1
        _LOGGER.info(
            "v5.94.1 FIX 1: removed empty parent-entry shell device %s "
            "(identifier=(DOMAIN, %r))",
            device.id, ura_ident,
        )
    if removed:
        _LOGGER.info(
            "v5.94.1 FIX 1: removed %d empty parent-entry coordinator "
            "shell device(s)", removed,
        )
    return removed


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

    # v5.94.1 FIX 2 (2026-09-03): same-identifier tie-break for the parent
    # index. In v5.94.0 dual-registration created TWO devices per coord
    # identifier — the REAL populated one on the CM entry and an empty
    # SHELL on the parent/INTEGRATION entry. The previous last-writer-wins
    # loop could resolve `coordinator_manager` to the empty shell and
    # stamp real coordinators under a dead parent, leaving the real CM
    # unnested. Rule: an EMPTY device (0 entities) that is SOLE-owned by
    # the parent/INTEGRATION entry is a removal candidate (see __init__.py
    # FIX 1) and is NEVER a valid parent — skip it from ura_index. Any
    # populated device wins the slot regardless of iteration order.
    _parent_entry_id: str | None = None
    _ent_reg = None
    try:
        # Local import: avoid cycle at module load.
        from homeassistant.helpers import entity_registry as _er
        from .const import (
            CONF_ENTRY_TYPE as _CONF_ENTRY_TYPE,
            ENTRY_TYPE_INTEGRATION as _ENTRY_TYPE_INTEGRATION,
        )
        _ent_reg = _er.async_get(hass)
        for _e in hass.config_entries.async_entries(DOMAIN):
            if _e.data.get(_CONF_ENTRY_TYPE) == _ENTRY_TYPE_INTEGRATION:
                _parent_entry_id = _e.entry_id
                break
    except Exception:  # noqa: BLE001
        # Missing hass/registry shape (e.g. minimal test hass) — no
        # tie-break available, fall through to the historical behaviour.
        _parent_entry_id = None
        _ent_reg = None

    def _is_empty_parent_shell(_device) -> bool:
        """Empty (0 entities) AND sole-owned by parent entry."""
        if _parent_entry_id is None or _ent_reg is None:
            return False
        try:
            if getattr(_device, "config_entries", None) != {_parent_entry_id}:
                return False
            from homeassistant.helpers import entity_registry as _er2
            _entries = _er2.async_entries_for_device(
                _ent_reg, _device.id, include_disabled_entities=True,
            )
            return not _entries
        except Exception:  # noqa: BLE001
            return False

    # Build identifier -> device_id index for URA-owned devices only.
    ura_index: dict[tuple[str, str], str] = {}
    for device in devices:
        if _is_empty_parent_shell(device):
            # Removal candidate — never eligible as a parent.
            continue
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
    # FIX-2 (2026-09-03, Review D D-LEAK-2): allow bounded re-arm.
    # Concurrent per-domain entry setup means an inline stamp may miss
    # devices; the once-per-boot at-start sweep may itself run before
    # a slow-DB entry has landed. Cap re-arms so a persistent parent
    # gap (bug, not race) doesn't schedule forever.
    _MAX_SCHEDULES = 3
    scheduled_count = int(domain_data.get("_device_tree_sweep_count", 0))
    if scheduled_count >= _MAX_SCHEDULES:
        return
    if domain_data.get("_device_tree_sweep_scheduled"):
        # An outstanding schedule is pending — don't double-arm now.
        # Re-arm decision is made by the sweep itself when it observes
        # residual > 0.
        return
    domain_data["_device_tree_sweep_scheduled"] = True
    domain_data["_device_tree_sweep_count"] = scheduled_count + 1

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
        # Clear the pending latch — future callers can re-arm.
        domain_data["_device_tree_sweep_scheduled"] = False
        if residual:
            _LOGGER.warning(
                "D-NEST at-start sweep: %d URA devices still lack via_device_id "
                "(INV-4 trip-wire; identifiers=%s). Sweep stamped %d devices.",
                residual, residual_ids[:10], updates,
            )
            # FIX-2 re-arm: bounded retry via async_call_later while we're
            # under the cap. This handles the slow-DB boot where a later
            # entry lands after our at-start sweep.
            count = int(domain_data.get("_device_tree_sweep_count", 0))
            if count < _MAX_SCHEDULES:
                try:
                    from homeassistant.helpers.event import async_call_later
                    async def _retry(_now=None) -> None:
                        # Delegate to the scheduler (idempotent + capped).
                        async_schedule_device_tree_sweep(hass)
                    _RETRY_DELAY_S = 30
                    handle = async_call_later(hass, _RETRY_DELAY_S, _retry)
                    domain_data.setdefault(
                        "_device_tree_sweep_retry_handles", []
                    ).append(handle)
                    _LOGGER.info(
                        "D-NEST: scheduling retry sweep in %ds "
                        "(attempt %d/%d)", _RETRY_DELAY_S,
                        count + 1, _MAX_SCHEDULES,
                    )
                except Exception:  # noqa: BLE001
                    _LOGGER.warning(
                        "D-NEST: retry-sweep scheduling failed (non-fatal)",
                        exc_info=True,
                    )
        else:
            _LOGGER.info(
                "D-NEST at-start sweep: all URA devices parented; stamped %d "
                "devices this sweep.", updates,
            )

    try:
        from homeassistant.helpers.start import async_at_started
        # FIX-5 (2026-09-03, Review D D-LEAK-5): store unsub so a
        # reload-before-started tears the listener down. Home Assistant's
        # async_at_started returns an unsub callable; we keep it in
        # domain data so URA's unload path can invoke it.
        unsub = async_at_started(hass, _sweep)
        domain_data.setdefault("_device_tree_sweep_unsubs", []).append(unsub)
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "D-NEST: async_at_started scheduling failed (non-fatal)",
            exc_info=True,
        )
