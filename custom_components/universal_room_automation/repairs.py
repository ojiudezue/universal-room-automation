"""Repairs platform for URA — fix flows for surfaced issues.

v4.3.1: implements `async_create_fix_flow` for the
`energy_envoy_invalid_<entry_id>` repair issue raised at startup when the
envoy validation gate fails.

The fix flow shows a description telling the user to fix the envoy entity
in the Coordinator Manager → Configure → Energy step, then re-runs
validation when they confirm. On pass, the repair issue is deleted and
the user is told to reload the integration. On fail, the form re-shows
with the current error.
"""

from __future__ import annotations

import logging

from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class EnvoyValidationRepairFlow(RepairsFlow):
    """Fix flow for energy_envoy_invalid_<entry_id> repair issue."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the repair flow."""
        super().__init__()
        self._hass = hass
        self._entry_id = entry_id

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        """First step — describe the issue and accept confirm."""
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict | None = None) -> FlowResult:
        """Confirm step — re-run envoy validation against current options.

        On pass: delete the repair issue, tell user to reload the integration
        (or do it for them via async_reload).
        On fail: show the form again with the current error so the user
        knows what's still wrong.
        """
        from homeassistant.helpers import issue_registry as ir
        from .domain_coordinators.energy_const import validate_envoy_config

        entry: ConfigEntry | None = self._hass.config_entries.async_get_entry(
            self._entry_id
        )
        if entry is None:
            # Entry was deleted while the repair was open — nothing to fix.
            ir.async_delete_issue(
                self._hass, DOMAIN, f"energy_envoy_invalid_{self._entry_id}"
            )
            return self.async_create_entry(title="", data={})

        # Read current entry config the same way startup wiring does
        merged = {**entry.data, **entry.options}
        energy_entity_config = {
            k: v for k, v in merged.items() if k.startswith("energy_")
        }
        # Apply auto-derive (mirrors __init__.py:1381-1386)
        from .domain_coordinators.energy_const import (
            CONF_ENERGY_ENVOY_ENTITY,
            extract_envoy_serial,
            derive_envoy_config,
        )
        envoy_eid = energy_entity_config.get(CONF_ENERGY_ENVOY_ENTITY)
        if envoy_eid:
            serial = extract_envoy_serial(envoy_eid)
            if serial:
                for k, v in derive_envoy_config(serial).items():
                    energy_entity_config.setdefault(k, v)

        result = validate_envoy_config(self._hass, energy_entity_config)

        if user_input is not None:
            # User submitted → re-validate. If pass, clear issue + reload entry.
            if result["ok"]:
                ir.async_delete_issue(
                    self._hass, DOMAIN, f"energy_envoy_invalid_{self._entry_id}"
                )
                # Reload the entry so EC can register cleanly with the new
                # config. Use named background task (Bug Class #19 prevention)
                # so HA can track and clean up if the user closes the repair
                # UI mid-reload.
                self._hass.async_create_background_task(
                    self._hass.config_entries.async_reload(self._entry_id),
                    name=f"ura_envoy_repair_reload_{self._entry_id}",
                )
                return self.async_create_entry(title="", data={})

            # Still failing — show errors and let user try again
            return self.async_show_form(
                step_id="confirm",
                description_placeholders={
                    "errors": ", ".join(
                        f"{k}={v}" for k, v in result["errors"].items()
                    ) or "unknown",
                },
                errors={"base": "envoy_validation_still_failing"},
            )

        # First render — show the description with current error context
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "errors": ", ".join(
                    f"{k}={v}" for k, v in result["errors"].items()
                ) or "unknown",
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict | None,
) -> RepairsFlow:
    """Return the fix flow for a given issue id.

    URA only registers one repair-issue family today: energy_envoy_invalid_*.
    """
    if issue_id.startswith("energy_envoy_invalid_"):
        entry_id = issue_id.removeprefix("energy_envoy_invalid_")
        return EnvoyValidationRepairFlow(hass, entry_id)
    # Unknown issue — return a no-op confirmation
    from homeassistant.components.repairs import ConfirmRepairFlow
    _LOGGER.warning("Unknown repair issue id: %s", issue_id)
    return ConfirmRepairFlow()
