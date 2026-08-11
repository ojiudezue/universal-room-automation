"""Central chokepoint for all climate `set_temperature` + `set_preset_mode` emissions.

feature/freeze-floor (CHOKEPOINT REVISION 2026-06-17): every URA-originated
`climate.set_temperature` call routes through `emit_set_temperature` so the
freeze-protection floor and the deadband invariant are enforced in ONE place,
no per-site clamps, and any future setpoint writer inherits both.

ARREST-COMFORT-1 Cycle A (2026-08-10): both chokepoints grew an optional
``gate`` param — a zero-arg callable that returns True to DEFER the write.
The comfort-delay branch installs a gate that consults
``OverrideArrester.comfort_delay_active(zone_id)`` and, for preset writes,
the per-reason ALLOW/DEFER verdict from §3.7 of the planning doc. Deferred
writes are DROPPED (not queued for replay) per the "granted then snatched"
antipattern; the coast / severity path re-emits naturally on the next tick
if the condition still holds. A ``comfort_delay_deferred_write`` activity
row is logged when a gate defers.

Two transforms are applied by ``emit_set_temperature`` before the service call:

1. **Freeze floor** — when `freeze_active` and the emitted `target_temp_low`
   is below ``FREEZE_FLOOR``, raise it to the floor.
2. **Deadband** — a raised low must never invert or violate the heat_cool
   deadband, so ``high = max(high, low + MIN_DEADBAND)`` whenever both bounds
   are present.

The caller keeps its own ``suppress()`` / arrester handshake around this call.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.core import HomeAssistant

from .hvac_const import FREEZE_FLOOR, MIN_DEADBAND

_LOGGER = logging.getLogger(__name__)


def apply_setpoint_guards(
    target_temp_low: float | None,
    target_temp_high: float | None,
    *,
    freeze_active: bool,
) -> tuple[float | None, float | None]:
    """Pure transform: apply the freeze floor + deadband invariant."""
    low = target_temp_low
    high = target_temp_high

    if freeze_active and low is not None and low < FREEZE_FLOOR:
        low = float(FREEZE_FLOOR)

    if low is not None and high is not None and high < low + MIN_DEADBAND:
        high = low + MIN_DEADBAND

    return low, high


def _log_deferred_write(
    hass: HomeAssistant,
    *,
    site: str,
    zone_id: str,
    entity_id: str,
    reason: str,
    would_have_emitted: dict[str, Any],
) -> None:
    """ARREST-COMFORT-1 D6: emit a ``comfort_delay_deferred_write`` ledger
    row when a chokepoint gate defers a write. Fire-and-forget task so a
    logger stall never blocks the write path. All args guarded.
    """
    try:
        from ..const import DOMAIN  # local: avoid cycle at import time
        activity_logger = (
            hass.data.get(DOMAIN, {}).get("activity_logger")
            if hasattr(hass, "data") else None
        )
    except Exception:  # noqa: BLE001 — defensive
        activity_logger = None
    _LOGGER.info(
        "ARREST-COMFORT-1: DEFERRED %s at %s zone=%s reason=%s would_have=%s",
        "set_temperature" if "temp" in site or site in ("S3", "S5", "S6", "S8", "S9")
        else "set_preset_mode",
        site, zone_id, reason, would_have_emitted,
    )
    if activity_logger is None:
        return
    try:
        hass.async_create_task(
            activity_logger.log(
                coordinator="hvac",
                action="comfort_delay_deferred_write",
                description=(
                    f"Comfort-delay deferred write at {site} on {entity_id} "
                    f"(reason={reason})"
                ),
                zone=zone_id,
                importance="notable",
                entity_id=entity_id,
                details={
                    "site": site,
                    "reason": reason,
                    "would_have_emitted": would_have_emitted,
                },
            )
        )
    except Exception:  # noqa: BLE001 — defensive
        _LOGGER.debug(
            "comfort_delay_deferred_write ledger emit failed", exc_info=True,
        )


async def emit_set_temperature(
    hass: HomeAssistant,
    entity_id: str,
    *,
    target_temp_low: float | None = None,
    target_temp_high: float | None = None,
    freeze_active: bool = False,
    blocking: bool = False,
    gate: Callable[[], bool] | None = None,
    site: str = "",
    zone_id: str = "",
    reason: str = "",
) -> bool:
    """Emit a `climate.set_temperature` after the freeze-floor + deadband guards.

    Returns True if the service call was issued, False if the comfort-delay
    ``gate`` deferred it. Callers that don't care may ignore the return value.
    The caller is responsible for any arrester ``suppress()`` wrapper.
    """
    # ARREST-COMFORT-1 D6: consult the comfort-delay gate BEFORE the guard
    # transforms and BEFORE the service call. Deferred writes are dropped
    # (not queued) per §3.7.
    if gate is not None:
        try:
            defer = bool(gate())
        except Exception:  # noqa: BLE001 — a bad gate must not deny the world
            defer = False
        if defer:
            _log_deferred_write(
                hass, site=site or "unknown_set_temperature",
                zone_id=zone_id, entity_id=entity_id, reason=reason,
                would_have_emitted={
                    "target_temp_low": target_temp_low,
                    "target_temp_high": target_temp_high,
                },
            )
            return False

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
    return True


async def emit_set_preset_mode(
    hass: HomeAssistant,
    entity_id: str,
    preset_mode: str,
    *,
    blocking: bool = False,
    gate: Callable[[], bool] | None = None,
    site: str = "",
    zone_id: str = "",
    reason: str = "",
) -> bool:
    """ARREST-COMFORT-1 Cycle A D6: preset-write chokepoint.

    Mirror of ``emit_set_temperature``. All URA-originated
    ``climate.set_preset_mode`` calls should route through this so the
    comfort-delay grace can veto reverts against qualifying manual writes
    (§3.7 preset sites S1/S4/S7 and the D3 forced-away site). Migrated in
    lockstep with the gate wiring; a legacy inline ``async_call`` is a
    silent leak past the grace (§8 tertiary risk).

    Returns True if the service call was issued, False if deferred.
    """
    if gate is not None:
        try:
            defer = bool(gate())
        except Exception:  # noqa: BLE001
            defer = False
        if defer:
            _log_deferred_write(
                hass, site=site or "unknown_set_preset_mode",
                zone_id=zone_id, entity_id=entity_id, reason=reason,
                would_have_emitted={"preset_mode": preset_mode},
            )
            return False

    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": entity_id, "preset_mode": preset_mode},
        blocking=blocking,
    )
    return True
