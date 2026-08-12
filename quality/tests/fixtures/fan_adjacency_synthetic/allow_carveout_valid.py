"""Rule 5 valid carve-out: comment includes (reason=...); scanner MUST NOT flag."""


async def good_carveout(hass, entity_id: str) -> None:
    # fan-adjacency: allow (reason=diagnostic-eviction-outside-URA-policy)
    await hass.services.async_call(
        "fan", "turn_off", {"entity_id": entity_id}, blocking=False,
    )
