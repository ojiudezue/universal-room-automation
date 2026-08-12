"""Rule 5 partial violation: carve-out present but missing (reason=...)."""


async def bad_carveout(hass, entity_id: str) -> None:
    # fan-adjacency: allow
    await hass.services.async_call(
        "fan", "turn_off", {"entity_id": entity_id}, blocking=False,
    )
