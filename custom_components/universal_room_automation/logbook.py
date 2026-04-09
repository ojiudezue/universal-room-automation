"""Logbook integration for Universal Room Automation.

Formats ura_action events for the HA native logbook so they appear as
structured entries (e.g., "URA: Living Room turned on 3 lights (entry, dark)")
instead of the generic "Event: ura_action" format.
"""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME


@callback
def async_describe_events(hass, async_describe_event):
    """Describe ura_action events for the HA logbook."""

    @callback
    def async_describe_ura_action(event):
        """Format a single ura_action event."""
        data = event.data
        coordinator = data.get("coordinator", "")
        room = data.get("room")

        if room:
            name = f"URA: {room}"
        else:
            name = f"URA {coordinator.title()}"

        return {
            LOGBOOK_ENTRY_NAME: name,
            LOGBOOK_ENTRY_MESSAGE: data.get("description", "action"),
        }

    async_describe_event("universal_room_automation", "ura_action", async_describe_ura_action)
