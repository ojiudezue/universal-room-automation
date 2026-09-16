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

Zone-scope admission (fix-up D-MED-2): the gate protects a ZONE, not a
specific writer. Any URA caller that reaches this chokepoint with a gate
consulting ``comfort_delay_active(zone_id)`` inherits the deferral for
the whole grace window. From the operator's perspective the grace is
"URA, back off this zone for N minutes", not "URA, back off this SPECIFIC
decision path for N minutes". Cf. planning §Non-goals.

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
from typing import Any, Callable, Final

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



# HVAC-MANUAL-PRESET-CONTRACT-1 D2a. The integration exposes a special
# "resume" preset that calls `resume_schedule`, clearing the hold entirely
# (ha_carrier/climate.py:405-409). It is NOT a destination — the operator
# does not use the Bryant schedule — it is the only way to clear an
# anonymous hold so a NAMED one can be pinned.
PRESET_RESUME: Final = "resume"

# The value a raw-setpoint write leaves in `hold_activity`: a hold with no
# named activity. This is what cannot be overwritten by a named pin.
ANONYMOUS_HOLD: Final = "manual"


def _needs_resume_first(
    hass: HomeAssistant, entity_id: str, target_preset: str,
) -> bool:
    """Return True when the zone must be cleared before a named pin will take.

    Reads `hold_activity` from the live entity. NOTE (plan review R2-HIGH-1):
    immediately after a write this attribute carries the integration's
    OPTIMISTIC local value rather than cloud truth, so this read is only
    trustworthy outside a write's settle window. That is acceptable here
    because being wrong is cheap in BOTH directions:
      * false positive -> a redundant `resume` before a pin that would have
        worked anyway; the pin still lands.
      * false negative -> the pre-existing behaviour (name discarded), which
        the next write retries.
    It is NOT acceptable to make this read authoritative for anything else.

    Never raises: a failure here must not block a thermostat write.
    """
    try:
        if target_preset == PRESET_RESUME:
            return False  # resuming IS the clear; never recurse
        state = hass.states.get(entity_id)
        if state is None:
            return False
        # CAPABILITY CHECK (not a vendor check). `resume` and the "manual"
        # anonymous-hold marker are BRYANT/CARRIER semantics, and this is a
        # SHARED chokepoint that every climate write passes through. A
        # thermostat from another integration may mean something different by
        # "manual" and may have no `resume` preset at all — firing one at it
        # would be a guaranteed-failing service call on every write.
        #
        # So we gate on the entity's OWN advertised capability rather than on
        # the integration name: only attempt the clear when the device itself
        # lists `resume` among its preset_modes. Unknown thermostats fall
        # through to the pre-existing direct-pin behaviour, unchanged.
        # See HVAC-PRESET-WRITE-STRATEGY-1 for the full per-integration
        # abstraction this is the seed of.
        modes = state.attributes.get("preset_modes") or ()
        if PRESET_RESUME not in modes:
            return False
        hold = state.attributes.get("hold_activity")
        if hold is None:
            return False  # no hold at all -> a pin takes directly
        return str(hold) == ANONYMOUS_HOLD
    except Exception:  # noqa: BLE001
        return False


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

    # ==================================================================
    # HVAC-MANUAL-PRESET-CONTRACT-1 D2a — RESUME-THEN-PIN.
    #
    # THE MECHANISM (measured live 2026-09-16, zone_1). A Bryant/Carrier
    # zone sitting in an ANONYMOUS hold (`hold_activity == "manual"`, which
    # is what any raw setpoint write leaves behind) will NOT accept a named
    # activity hold written over the top of it: the cloud keeps the
    # activity's SETPOINTS and DISCARDS THE NAME. Two direct writes to a
    # stuck zone reverted to `manual` in 44s and 68s, each inside the
    # measured 42-79s coordinator refresh window, while the setpoints
    # persisted. Clearing the hold first with the integration's special
    # "resume" preset and THEN pinning took, and held for 8 minutes across
    # 9 cloud-confirmed refreshes with zero reverts.
    #
    # WHY THIS IS THE RIGHT HOME. This function is already the documented
    # preset-write chokepoint (see the docstring above), so every URA
    # caller inherits the fix. The alternative considered and rejected was
    # the borrow / `return_excursion` primitive — plan review measured that
    # NONE of the 11 setpoint-writing functions reference `borrow` and that
    # `return_excursion` emits no writes at all, so routing through it
    # would have produced a half-applied fix (Bug Class #53).
    #
    # WHY IT IS CONDITIONAL. A zone already on a NAMED hold accepts a
    # direct pin — zone_3 does this continuously. `resume` is only needed
    # to escape an ANONYMOUS hold, so we pay its cost (a brief window on
    # the thermostat's own schedule) only when there is no alternative.
    #
    # ADJACENCY IS LOAD-BEARING (invariant I3). Between the resume and the
    # pin the zone follows the Bryant schedule, which the operator does not
    # use. Nothing awaitable and failure-prone may sit between them, and
    # the resume is NOT issued unless we are about to pin.
    # ==================================================================
    _resumed = False
    if _needs_resume_first(hass, entity_id, preset_mode):
        try:
            await hass.services.async_call(
                "climate",
                "set_preset_mode",
                {"entity_id": entity_id, "preset_mode": PRESET_RESUME},
                blocking=True,
            )
            _resumed = True
        except Exception:  # noqa: BLE001
            # Fail-forward: if the CLEAR fails we still attempt the pin.
            # Worst case is the pre-existing behaviour (name discarded).
            _LOGGER.debug(
                "resume-then-pin: resume failed for %s; pinning anyway",
                entity_id, exc_info=True,
            )

    try:
        await hass.services.async_call(
            "climate",
            "set_preset_mode",
            {"entity_id": entity_id, "preset_mode": preset_mode},
            blocking=blocking,
        )
    except Exception:
        # INVARIANT I3 — "the zone is never left following the vendor
        # schedule". Found by the adversarial build review, and it is the
        # one way this fix could CAUSE the harm it exists to prevent:
        # if the clear succeeded and the pin then fails (a cloud 504, a
        # momentarily unavailable entity, any service error — all observed
        # on this integration), the zone sits on the Bryant schedule with
        # NO hold, indefinitely, because nothing else re-pins it.
        #
        # Having cleared the hold we OWE the zone a pin. Retry once, then
        # surface at ERROR: a zone released to a schedule the operator does
        # not use is not a debug-level event, and the ledger/log is the only
        # way anyone would ever find out.
        if _resumed:
            try:
                await hass.services.async_call(
                    "climate",
                    "set_preset_mode",
                    {"entity_id": entity_id, "preset_mode": preset_mode},
                    blocking=True,
                )
                _LOGGER.warning(
                    "resume-then-pin: pin retry succeeded for %s (%s)",
                    entity_id, preset_mode,
                )
                return True
            except Exception:  # noqa: BLE001
                _LOGGER.error(
                    "resume-then-pin: CLEARED the hold on %s but could not "
                    "pin %s after a retry — zone is following the thermostat "
                    "schedule with no hold until the next write",
                    entity_id, preset_mode, exc_info=True,
                )
        raise
    return True
