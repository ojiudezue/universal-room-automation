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

import json
import logging
import time
from typing import Any, Callable, Final

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .hvac_const import (
    CLIMATE_WRITE_LOG_IMPORTANCE,
    FREEZE_FLOOR,
    MIN_DEADBAND,
)

_LOGGER = logging.getLogger(__name__)


def _capture_preset_reason(
    hass: HomeAssistant, zone_id: str, reason: str,
) -> None:
    """HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1 D6 (v5.103.8).

    Cache the ``reason=`` argument on the HVAC coordinator, keyed by
    zone_id, so the zone-preset sensor can surface it as
    ``retreat_reason``. Called from the two chokepoint success paths
    (initial + retry). Covers ALL 11 URA-side preset-write sites
    automatically — no per-caller wiring (Bug Class #53 prevention).

    Best-effort: never raises. Empty/missing zone_id or reason falls
    through to the sensor's ``unknown`` default.
    """
    if not zone_id:
        return
    try:
        from homeassistant.util import dt as dt_util  # noqa: PLC0415
        from ..const import DOMAIN  # noqa: PLC0415
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        hvac = manager.coordinators.get("hvac") if hasattr(
            manager, "coordinators",
        ) else None
        if hvac is None:
            return
        cache = getattr(hvac, "_last_reason_by_zone", None)
        if cache is None:
            cache = {}
            hvac._last_reason_by_zone = cache
        cache[zone_id] = (reason or "unknown", dt_util.utcnow())
    except Exception:  # noqa: BLE001
        # Best-effort observability — never let a cache write take
        # down a preset-write call site.
        _LOGGER.debug(
            "preset-reason capture failed for zone=%s reason=%s",
            zone_id, reason, exc_info=True,
        )


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


# ==========================================================================
# HVAC-W1-THERMOSTAT-DEFINITION Stage A (behaviour-neutral write governance)
#
# INV-A: every URA-originated wire-level `climate` service call issues
# exactly one `climate_write` row-schedule call before the funnel returns
# or raises. See docs/planning/PLANNING_hvac_w1a_thermostat_write_governance.md.
# The row-schedule is fire-and-forget via `hass.async_create_task` — NEVER
# awaited, NEVER raises, NEVER alters wire-call raise/swallow/return
# semantics (F2, F11, F14).
# ==========================================================================


def _snapshot_climate_state(
    hass: HomeAssistant, entity_id: str,
) -> dict[str, Any]:
    """Read `preset_mode` / `hold_activity` / setpoints / mode SYNCHRONOUSLY
    from the live climate state (F6 — captured BEFORE the wire await so a
    late echo cannot corrupt `values_before`).

    Absent keys are recorded as ``None`` (F6 "null-with-key when absent").
    Never raises — a state-read failure yields all-null.
    """
    out: dict[str, Any] = {
        "preset_mode": None,
        "hold_activity": None,
        "target_low": None,
        "target_high": None,
        "hvac_mode": None,
    }
    try:
        state = hass.states.get(entity_id)
        if state is None:
            return out
        attrs = state.attributes or {}
        out["preset_mode"] = attrs.get("preset_mode")
        out["hold_activity"] = attrs.get("hold_activity")
        tl = attrs.get("target_temp_low")
        th = attrs.get("target_temp_high")
        out["target_low"] = float(tl) if tl is not None else None
        out["target_high"] = float(th) if th is not None else None
        out["hvac_mode"] = state.state
    except Exception:  # noqa: BLE001 — defensive; snapshot never raises
        _LOGGER.debug(
            "climate_write snapshot failed for %s", entity_id, exc_info=True,
        )
    return out


def _schedule_climate_write_row(
    hass: HomeAssistant,
    *,
    verb: str,
    entity_id: str,
    site: str,
    zone_id: str,
    reason: str,
    blocking: bool,
    excursion_id: str | None,
    values_before: dict[str, Any],
    values_after: dict[str, Any],
    ts_issued: float,
    ts_returned: float,
    wire_ok: bool,
    exc: str | None,
    issued_wallclock: str | None = None,
) -> None:
    """Fire-and-forget schedule of ONE `climate_write` ledger row.

    Bypasses `ActivityLogger.log` (F4): direct-calls `database.log_activity`
    so there is NO dedup, NO `SIGNAL_ACTIVITY_LOGGED` dispatch, and NO
    `ura_action` HA-event fire — two identical writes 1 s apart land as
    two rows.

    Guarded exactly like `_log_deferred_write` (F14): a missing/absent
    `hass.data[DOMAIN]["database"]` degrades to a debug log; this helper
    NEVER raises. Scheduled via `hass.async_create_task` (F2): NEVER
    awaited — a slow DB write cannot back-pressure the wire path.
    """
    try:
        from ..const import DOMAIN  # local: avoid cycle at import time
        db = (
            hass.data.get(DOMAIN, {}).get("database")
            if hasattr(hass, "data") else None
        )
    except Exception:  # noqa: BLE001 — defensive
        db = None
    if db is None:
        _LOGGER.debug(
            "climate_write row skipped (no database) verb=%s site=%s zone=%s",
            verb, site, zone_id,
        )
        return
    try:
        payload = {
            "verb": verb,
            "site": site,
            "reason": reason,
            "blocking": bool(blocking),
            "wire_ok": bool(wire_ok),
            "exc": exc,
            "excursion_id": excursion_id,
            "values_before": values_before,
            "values_after": values_after,
            "ts_issued": float(ts_issued),
            "ts_returned": float(ts_returned),
        }
        details_json = json.dumps(payload, default=str)
        # B-MEDIUM: use the wall-clock ISSUE time as the row timestamp so
        # a blocking wire call that only returns after ha_carrier already
        # updated HA state does not make URA's own write look external
        # (§7 provenance query #6). Falls back to now() if the caller
        # didn't stamp one (defensive; every funnel stamps).
        timestamp = issued_wallclock or dt_util.utcnow().isoformat()
        description = (
            f"{verb} zone={zone_id} site={site} reason={reason}"
        )
        # Fire-and-forget: NEVER awaited (F2). A DB stall cannot delay
        # the wire path.
        _coro = db.log_activity(
            timestamp=timestamp,
            coordinator="hvac",
            action="climate_write",
            room=None,
            zone=zone_id or None,
            importance=CLIMATE_WRITE_LOG_IMPORTANCE,
            description=description,
            details_json=details_json,
            entity_id=entity_id,
        )
        # Duck-check: MagicMock-shaped test doubles return non-coroutines
        # from log_activity; scheduling those would leak a non-awaitable
        # onto the loop. In production `log_activity` is an async def and
        # this check is a no-op.
        import inspect  # local — cheap, avoids top-level cycle
        if inspect.iscoroutine(_coro):
            hass.async_create_task(_coro)
    except Exception:  # noqa: BLE001 — defensive
        _LOGGER.debug(
            "climate_write row schedule failed verb=%s site=%s",
            verb, site, exc_info=True,
        )


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
# (ha_carrier/climate.py:405-409). It is NOT a destination — it is the only
# way to clear an anonymous hold so a NAMED one can be pinned.
# CORRECTED 2026-09-26 (operator): the Bryant thermostats DO still run
# their own schedules — zone_1 reduced to a single 06:00 Home entry
# (since 2026-09-20 11:39), zones 2 and 3 still on 4-entry schedules. The
# working assumption is that those schedules are being reduced so URA is
# the only controller; until then, "resume" briefly hands the zone to a
# live vendor schedule before the pin lands. See
# docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md §5/§10.
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
    site: str,
    zone_id: str,
    reason: str,
    excursion_id: str | None = None,
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

    # HVAC-W1-A INV-A: snapshot BEFORE the wire await (F6).
    _values_before = _snapshot_climate_state(hass, entity_id)
    _ts_issued = time.monotonic()
    # B-MEDIUM: wall-clock ISSUE time — used as the row timestamp so a
    # blocking call that returns after ha_carrier has already updated HA
    # state doesn't make URA's own write look external.
    _issued_wall = dt_util.utcnow().isoformat()
    _wire_ok = False
    _exc_name: str | None = None
    try:
        await hass.services.async_call(
            "climate", "set_temperature", service_data, blocking=blocking,
        )
        _wire_ok = True
    except BaseException as _wire_exc:  # noqa: BLE001 — re-raised below
        _exc_name = type(_wire_exc).__name__
        _schedule_climate_write_row(
            hass,
            verb="set_temperature",
            entity_id=entity_id,
            site=site,
            zone_id=zone_id,
            reason=reason,
            blocking=blocking,
            excursion_id=excursion_id,
            values_before=_values_before,
            values_after=dict(service_data),
            ts_issued=_ts_issued,
            ts_returned=time.monotonic(),
            wire_ok=False,
            exc=_exc_name,
            issued_wallclock=_issued_wall,
        )
        raise
    _schedule_climate_write_row(
        hass,
        verb="set_temperature",
        entity_id=entity_id,
        site=site,
        zone_id=zone_id,
        reason=reason,
        blocking=blocking,
        excursion_id=excursion_id,
        values_before=_values_before,
        values_after=dict(service_data),
        ts_issued=_ts_issued,
        ts_returned=time.monotonic(),
        wire_ok=_wire_ok,
        exc=None,
        issued_wallclock=_issued_wall,
    )
    return True


async def emit_set_preset_mode(
    hass: HomeAssistant,
    entity_id: str,
    preset_mode: str,
    *,
    blocking: bool = False,
    gate: Callable[[], bool] | None = None,
    site: str,
    zone_id: str,
    reason: str,
    excursion_id: str | None = None,
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
    # HVAC-W1-A A-LOW-3 (fix-up round 3): label the pin `+pin` whenever
    # a resume was ATTEMPTED — even if the resume raised — so a stranded
    # zone rooted in a resume-then-failed-pin is greppable as `+pin`,
    # not as the bare site name. Track "resume attempted" separately
    # from "resume succeeded".
    _resume_attempted = False
    _resumed = False
    if _needs_resume_first(hass, entity_id, preset_mode):
        _resume_attempted = True
        # HVAC-W1-A INV-A: snapshot + row PER ATTEMPTED WIRE CALL (F11).
        _resume_data = {"entity_id": entity_id, "preset_mode": PRESET_RESUME}
        _resume_before = _snapshot_climate_state(hass, entity_id)
        _resume_ts_issued = time.monotonic()
        _resume_wall = dt_util.utcnow().isoformat()
        _resume_ok = False
        _resume_exc: str | None = None
        try:
            await hass.services.async_call(
                "climate",
                "set_preset_mode",
                _resume_data,
                blocking=True,
            )
            _resumed = True
            _resume_ok = True
        except BaseException as _re:  # noqa: BLE001 — CancelledError still logs
            # Fail-forward on regular Exceptions; re-raise BaseException
            # (Cancelled/KeyboardInterrupt) AFTER scheduling the row.
            _resume_exc = type(_re).__name__
            _LOGGER.debug(
                "resume-then-pin: resume failed for %s; pinning anyway "
                "on regular Exception, otherwise (Cancelled/KeyboardInterrupt) "
                "re-raising after scheduling the row",
                entity_id, exc_info=True,
            )
            _schedule_climate_write_row(
                hass,
                verb="set_preset_mode",
                entity_id=entity_id,
                site=f"{site}+resume",
                zone_id=zone_id,
                reason=reason,
                blocking=True,
                excursion_id=excursion_id,
                values_before=_resume_before,
                values_after=dict(_resume_data),
                ts_issued=_resume_ts_issued,
                ts_returned=time.monotonic(),
                wire_ok=False,
                exc=_resume_exc,
                issued_wallclock=_resume_wall,
            )
            if not isinstance(_re, Exception):
                raise
        else:
            _schedule_climate_write_row(
                hass,
                verb="set_preset_mode",
                entity_id=entity_id,
                site=f"{site}+resume",
                zone_id=zone_id,
                reason=reason,
                blocking=True,
                excursion_id=excursion_id,
                values_before=_resume_before,
                values_after=dict(_resume_data),
                ts_issued=_resume_ts_issued,
                ts_returned=time.monotonic(),
                wire_ok=_resume_ok,
                exc=None,
                issued_wallclock=_resume_wall,
            )

    _pin_data = {"entity_id": entity_id, "preset_mode": preset_mode}
    # A-LOW-3: label `+pin` when the resume was ATTEMPTED (attempted-then-
    # failed included), so provenance queries partition cleanly.
    _pin_site = f"{site}+pin" if _resume_attempted else site
    _pin_before = _snapshot_climate_state(hass, entity_id)
    _pin_ts_issued = time.monotonic()
    _pin_wall = dt_util.utcnow().isoformat()
    try:
        await hass.services.async_call(
            "climate",
            "set_preset_mode",
            _pin_data,
            blocking=blocking,
        )
    except BaseException as _pin_exc:  # noqa: BLE001 — CancelledError logs too
        _schedule_climate_write_row(
            hass,
            verb="set_preset_mode",
            entity_id=entity_id,
            site=_pin_site,
            zone_id=zone_id,
            reason=reason,
            blocking=blocking,
            excursion_id=excursion_id,
            values_before=_pin_before,
            values_after=dict(_pin_data),
            ts_issued=_pin_ts_issued,
            ts_returned=time.monotonic(),
            wire_ok=False,
            exc=type(_pin_exc).__name__,
            issued_wallclock=_pin_wall,
        )
        # For non-Exception BaseException (Cancelled/KI), do not retry —
        # re-raise now.
        if not isinstance(_pin_exc, Exception):
            raise
        if _resumed:
            _retry_data = {"entity_id": entity_id, "preset_mode": preset_mode}
            _retry_before = _snapshot_climate_state(hass, entity_id)
            _retry_ts_issued = time.monotonic()
            _retry_wall = dt_util.utcnow().isoformat()
            _retry_ok = False
            _retry_exc: str | None = None
            try:
                await hass.services.async_call(
                    "climate",
                    "set_preset_mode",
                    _retry_data,
                    blocking=True,
                )
                _retry_ok = True
                _LOGGER.warning(
                    "resume-then-pin: pin retry succeeded for %s (%s)",
                    entity_id, preset_mode,
                )
            except BaseException as _re:  # noqa: BLE001
                _retry_exc = type(_re).__name__
                _LOGGER.error(
                    "resume-then-pin: CLEARED the hold on %s but could not "
                    "pin %s after a retry — zone is following the thermostat "
                    "schedule with no hold until the next write",
                    entity_id, preset_mode, exc_info=True,
                )
                _schedule_climate_write_row(
                    hass,
                    verb="set_preset_mode",
                    entity_id=entity_id,
                    site=f"{site}+pin_retry",
                    zone_id=zone_id,
                    reason=reason,
                    blocking=True,
                    excursion_id=excursion_id,
                    values_before=_retry_before,
                    values_after=dict(_retry_data),
                    ts_issued=_retry_ts_issued,
                    ts_returned=time.monotonic(),
                    wire_ok=False,
                    exc=_retry_exc,
                    issued_wallclock=_retry_wall,
                )
                if not isinstance(_re, Exception):
                    raise
                raise _pin_exc from None
            _schedule_climate_write_row(
                hass,
                verb="set_preset_mode",
                entity_id=entity_id,
                site=f"{site}+pin_retry",
                zone_id=zone_id,
                reason=reason,
                blocking=True,
                excursion_id=excursion_id,
                values_before=_retry_before,
                values_after=dict(_retry_data),
                ts_issued=_retry_ts_issued,
                ts_returned=time.monotonic(),
                wire_ok=_retry_ok,
                exc=None,
                issued_wallclock=_retry_wall,
            )
            if _retry_ok:
                _capture_preset_reason(hass, zone_id, reason)
                return True
        raise
    _schedule_climate_write_row(
        hass,
        verb="set_preset_mode",
        entity_id=entity_id,
        site=_pin_site,
        zone_id=zone_id,
        reason=reason,
        blocking=blocking,
        excursion_id=excursion_id,
        values_before=_pin_before,
        values_after=dict(_pin_data),
        ts_issued=_pin_ts_issued,
        ts_returned=time.monotonic(),
        wire_ok=True,
        exc=None,
        issued_wallclock=_pin_wall,
    )
    _capture_preset_reason(hass, zone_id, reason)
    return True


# ==========================================================================
# HVAC-W1-A D1: emit_set_hvac_mode (third funnel).
# ==========================================================================


async def emit_set_hvac_mode(
    hass: HomeAssistant,
    entity_id: str,
    hvac_mode: str,
    *,
    site: str,
    zone_id: str,
    reason: str,
    blocking: bool,
    excursion_id: str | None = None,
) -> bool:
    """Central chokepoint for `climate.set_hvac_mode` writes.

    Behaviour-neutral: NO gate, NO transform. Wraps ONE
    ``hass.services.async_call("climate", "set_hvac_mode", ...)`` and
    schedules ONE `climate_write` row per attempted wire call (F11).
    Never swallows / never modifies wire-call raise semantics (F11).
    Required kwargs: `site`, `zone_id`, `reason`, `blocking` (F3, F10).
    """
    service_data = {"entity_id": entity_id, "hvac_mode": hvac_mode}
    _values_before = _snapshot_climate_state(hass, entity_id)
    _ts_issued = time.monotonic()
    _issued_wall = dt_util.utcnow().isoformat()
    try:
        await hass.services.async_call(
            "climate", "set_hvac_mode", service_data, blocking=blocking,
        )
    except BaseException as _wire_exc:  # noqa: BLE001 — re-raised below
        _schedule_climate_write_row(
            hass,
            verb="set_hvac_mode",
            entity_id=entity_id,
            site=site,
            zone_id=zone_id,
            reason=reason,
            blocking=blocking,
            excursion_id=excursion_id,
            values_before=_values_before,
            values_after=dict(service_data),
            ts_issued=_ts_issued,
            ts_returned=time.monotonic(),
            wire_ok=False,
            exc=type(_wire_exc).__name__,
            issued_wallclock=_issued_wall,
        )
        raise
    _schedule_climate_write_row(
        hass,
        verb="set_hvac_mode",
        entity_id=entity_id,
        site=site,
        zone_id=zone_id,
        reason=reason,
        blocking=blocking,
        excursion_id=excursion_id,
        values_before=_values_before,
        values_after=dict(service_data),
        ts_issued=_ts_issued,
        ts_returned=time.monotonic(),
        wire_ok=True,
        exc=None,
        issued_wallclock=_issued_wall,
    )
    return True
