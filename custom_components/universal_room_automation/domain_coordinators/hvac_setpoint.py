"""Central chokepoint for all climate `set_temperature` emissions.

feature/freeze-floor (CHOKEPOINT REVISION 2026-06-17): every URA-originated
`climate.set_temperature` call routes through `emit_set_temperature` so the
freeze-protection floor and the deadband invariant are enforced in ONE place,
no per-site clamps, and any future setpoint writer inherits both.

Two transforms are applied before the service call:

1. **Freeze floor** — when `freeze_active` and the emitted `target_temp_low`
   is below ``FREEZE_FLOOR``, raise it to the floor. Pipe-safety net; NO-OP in
   normal operation (winter presets already hold ≥58°F).
2. **Deadband** — a raised low must never invert or violate the heat_cool
   deadband, so ``high = max(high, low + MIN_DEADBAND)`` whenever both bounds
   are present. Fixes A-HIGH-1 (clamping low to 50 with cool_high<52 used to
   invert the range).

The caller keeps its own ``suppress()`` / arrester handshake around this call;
the chokepoint performs ONLY the transform + the service call.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .hvac_const import FREEZE_FLOOR, MIN_DEADBAND

_LOGGER = logging.getLogger(__name__)


def apply_setpoint_guards(
    target_temp_low: float | None,
    target_temp_high: float | None,
    *,
    freeze_active: bool,
) -> tuple[float | None, float | None]:
    """Pure transform: apply the freeze floor + deadband invariant.

    Returns the (low, high) that ``emit_set_temperature`` will actually write.
    Exposed separately so a caller with an idempotent throttle can compare
    against the post-guard pair WITHOUT the transform drifting from the wire
    path. Present bounds only — ``None`` is preserved.
    """
    low = target_temp_low
    high = target_temp_high

    # 1. Freeze floor — only raise a present, sub-floor low when armed.
    if freeze_active and low is not None and low < FREEZE_FLOOR:
        low = float(FREEZE_FLOOR)

    # 2. Deadband invariant — a raised low must not invert/violate the band.
    #    Only enforce when BOTH bounds are present.
    if low is not None and high is not None and high < low + MIN_DEADBAND:
        high = low + MIN_DEADBAND

    return low, high


async def emit_set_temperature(
    hass: HomeAssistant,
    entity_id: str,
    *,
    target_temp_low: float | None = None,
    target_temp_high: float | None = None,
    freeze_active: bool = False,
    blocking: bool = False,
) -> None:
    """Emit a `climate.set_temperature` after the freeze-floor + deadband guards.

    Callers pass whichever bounds they intend to write; ``None`` bounds are
    preserved (some callers set only one). Only present bounds are clamped.
    The caller is responsible for any arrester ``suppress()`` wrapper.
    """
    low, high = apply_setpoint_guards(
        target_temp_low, target_temp_high, freeze_active=freeze_active,
    )
    if freeze_active and target_temp_low is not None and low != target_temp_low:
        _LOGGER.info(
            "HVAC: freeze-floor chokepoint raised %s low %.1f -> %.1f°F",
            entity_id, target_temp_low, low,
        )

    service_data: dict[str, float | str] = {"entity_id": entity_id}
    if low is not None:
        service_data["target_temp_low"] = low
    if high is not None:
        service_data["target_temp_high"] = high

    await hass.services.async_call(
        "climate", "set_temperature", service_data, blocking=blocking,
    )
