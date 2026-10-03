"""Single run gate for domain coordinators (CM-COORDINATORS-ADD-ONE-BY-ONE-1).

Before this module every registration site in ``__init__.py`` carried its
own inline default for its ``*_enabled`` key, and the Enabled switch used
another (True for all). On a fresh install the Energy/HVAC/NM switches read
ON while those coordinators did not run. Now every reader goes through
``coordinator_should_run`` and the one default table
``const.COORDINATOR_ENABLED_DEFAULTS``.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from . import entitlements
from .const import (
    ADDABLE_COORDINATORS,
    CONF_COORDINATORS_ADDED,
    CONF_ENTRY_TYPE,
    COORDINATOR_ENABLED_DEFAULTS,
    COORDINATOR_ENABLED_KEYS,
    COORDINATOR_LABELS,
    COORDINATORS_ADDED_MIGRATION_DONE,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
)

_LOGGER = logging.getLogger(__name__)

# Coordinator ids already logged as denied (log once per process).
_DENIED_LOGGED: set[str] = set()


def coordinator_enabled_setting(cm_config: Mapping[str, Any], coordinator_id: str) -> bool:
    """Return the stored run setting, falling back to the one default table."""
    key = COORDINATOR_ENABLED_KEYS[coordinator_id]
    return bool(cm_config.get(key, COORDINATOR_ENABLED_DEFAULTS[coordinator_id]))


def coordinator_should_run(
    cm_config: Mapping[str, Any] | None,
    coordinator_id: str,
    hass: Any = None,
) -> bool:
    """Return True if this coordinator should be registered / treated as on.

    = stored *_enabled setting (or the table default) AND the entitlement
    hook allows it. A denied coordinator is not run, logged once, and a
    repair issue is raised when ``hass`` is given.
    """
    if not coordinator_enabled_setting(cm_config or {}, coordinator_id):
        return False
    try:
        allowed, reason = entitlements.can_use_coordinator(coordinator_id)
    except Exception:  # noqa: BLE001 — a broken hook must not crash setup
        _LOGGER.warning(
            "Entitlement check for %s raised; not running it", coordinator_id,
            exc_info=True,
        )
        allowed, reason = False, "entitlement check failed"
    if allowed:
        if hass is not None:
            try:
                from homeassistant.helpers import issue_registry as ir

                ir.async_delete_issue(
                    hass, DOMAIN, f"coordinator_not_entitled_{coordinator_id}",
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Could not clear entitlement repair issue", exc_info=True)
        return True
    if coordinator_id not in _DENIED_LOGGED:
        _DENIED_LOGGED.add(coordinator_id)
        _LOGGER.warning(
            "Coordinator %s is turned on but not allowed (%s); not running it",
            coordinator_id, reason,
        )
    if hass is not None:
        try:
            from homeassistant.helpers import issue_registry as ir

            ir.async_create_issue(
                hass,
                DOMAIN,
                f"coordinator_not_entitled_{coordinator_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="coordinator_not_entitled",
                translation_placeholders={
                    "coordinator": COORDINATOR_LABELS.get(coordinator_id, coordinator_id),
                    "reason": reason or "not allowed",
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not raise entitlement repair issue", exc_info=True)
    return False


def coordinators_to_register(
    cm_config: Mapping[str, Any] | None, hass: Any = None,
) -> set[str]:
    """Return the coordinator ids the CM setup registers (pure gate).

    Used by every registration site in ``__init__.py`` (membership test).
    """
    return {
        cid for cid in COORDINATOR_ENABLED_DEFAULTS
        if coordinator_should_run(cm_config, cid, hass)
    }


def coordinators_added(cm_config: Mapping[str, Any] | None) -> list[str] | None:
    """Return the added list, or None if the key has never been written."""
    if not cm_config or CONF_COORDINATORS_ADDED not in cm_config:
        return None
    raw = cm_config.get(CONF_COORDINATORS_ADDED) or []
    return [c for c in raw if c in ADDABLE_COORDINATORS]


def is_coordinator_added(cm_config: Mapping[str, Any] | None, coordinator_id: str) -> bool:
    """True if added. Key never written (pre-migration) => treat as added."""
    added = coordinators_added(cm_config)
    if added is None:
        return True
    return coordinator_id in added


def new_install_cm_options() -> dict[str, Any]:
    """Seed options for a freshly created CM entry: only Presence added."""
    opts: dict[str, Any] = {
        COORDINATOR_ENABLED_KEYS[cid]: cid == "presence"
        for cid in ADDABLE_COORDINATORS
    }
    opts[CONF_COORDINATORS_ADDED] = ["presence"]
    opts[COORDINATORS_ADDED_MIGRATION_DONE] = True
    return opts


def migrated_cm_options(
    cm_options: Mapping[str, Any], cm_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Existing-install migration: freeze today's effective run state.

    Each coordinator's *_enabled is written explicitly with the value it
    effectively has today (explicit key, else the table default), and the
    ones that run are marked added. Nothing starts, nothing stops.
    """
    merged = {**(cm_data or {}), **cm_options}
    new = dict(cm_options)
    added: list[str] = []
    for cid in ADDABLE_COORDINATORS:
        run = coordinator_enabled_setting(merged, cid)
        new[COORDINATOR_ENABLED_KEYS[cid]] = run
        if run:
            added.append(cid)
    new[CONF_COORDINATORS_ADDED] = added
    new[COORDINATORS_ADDED_MIGRATION_DONE] = True
    return new


async def async_migrate_coordinators_added(hass: Any) -> bool:
    """Run the one-shot migration on the CM entry. Returns True if written.

    Runs at integration setup regardless of the master switch, so an
    install with the master OFF still gets an accurate added list.
    """
    for ce in hass.config_entries.async_entries(DOMAIN):
        if ce.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COORDINATOR_MANAGER:
            continue
        if ce.options.get(COORDINATORS_ADDED_MIGRATION_DONE):
            return False
        new = migrated_cm_options(ce.options, ce.data)
        # Seed the CM listener snapshot first so the update listener sees
        # no change and does not reload the CM on the upgrade boot.
        hass.data.setdefault(DOMAIN, {}).setdefault(
            "cm_last_applied_options", {},
        )[ce.entry_id] = dict(new)
        hass.config_entries.async_update_entry(ce, options=new)
        _LOGGER.info(
            "Coordinator add-list migration: marked added %s (run state unchanged)",
            new[CONF_COORDINATORS_ADDED],
        )
        return True
    return False
