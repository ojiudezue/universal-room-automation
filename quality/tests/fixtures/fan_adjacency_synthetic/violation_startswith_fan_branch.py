"""Rule 2 violation: generic services.async_call under an ``entity.startswith("fan.")`` branch."""


async def bad_startswith(hass, entity_id: str) -> None:
    if entity_id.startswith("fan."):
        await hass.services.async_call(
            "homeassistant", "turn_on", {"entity_id": entity_id}, blocking=False,
        )
