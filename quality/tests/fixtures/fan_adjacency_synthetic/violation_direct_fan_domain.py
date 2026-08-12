"""Rule 1 violation: services.async_call("fan", ...) with no oracle.actuate wrap."""


async def bad_direct_fan(hass, entity_id: str) -> None:
    await hass.services.async_call(
        "fan", "turn_on", {"entity_id": entity_id}, blocking=False,
    )
