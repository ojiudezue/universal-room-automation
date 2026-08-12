"""Rule 3 violation: a fake chokepoint helper (named to look like a chokepoint
but NOT on the scanner's real allowlist) whose body issues a raw fan-domain
services.async_call with no enclosing oracle.actuate. This is the shape of a
mis-refactored caller that bypasses the real hvac_fans.py::_set_fan_state
chokepoint by open-coding the fan write. The scanner walks the body and
rule 1 fires on the raw fan-domain call.
"""


class BadCaller:
    async def bypass_chokepoint(self, hass, entity_id: str) -> None:
        # A caller that reinvents the fan-write path instead of calling
        # the real _set_fan_state chokepoint. This is exactly the failure
        # mode the reverse-adjacency scanner is meant to catch.
        await hass.services.async_call(
            "fan", "turn_off", {"entity_id": entity_id}, blocking=False,
        )
