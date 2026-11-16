"""Stuck-Signal Watchdog — shared NM emit + per-day dedup latch (X21 pattern).

Cycle: v5.35.0 (see docs/planning/PLANNING_stuck_signal_watchdog.md).

Detection + discount + notify ONLY. This module never actuates, never mutates
detector state; it only fans a coalesced "stuck_signal" notification through
the NotificationManager, latched per-(kind, key)/day so a standing stuck
condition surfaces once per operator-visible day rather than every tick.

All entry points are FAIL-OPEN: any exception is logged at debug and
swallowed. A NM emit failure must never propagate into the safety /
census / presence pipelines that call us.

Bug Class #34 note: the NotificationManager `Severity` enum is imported
LOCALLY inside the async function bodies (`from .notification_manager
import Severity`). This is a deliberate exception to the "module-top
imports" rule — notification_manager.py depends transitively on const.py
and importing it at module top here creates a circular load during
integration setup. Bug Class #34 concerns `async_dispatcher_send` /
event-helper conditional imports, which this file does not use.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Tuple

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_STUCK_SIGNAL_NM_ENABLED,
    DEFAULT_STUCK_SIGNAL_NM_ENABLED,
    DOMAIN,
    STUCK_SIGNAL_NM_COORDINATOR_ID,
    STUCK_SIGNAL_NM_HAZARD_TYPE,
)
from ._nm_cycle_a import nm_cycle_a_knob

_LOGGER = logging.getLogger(__name__)

# Module-level per-day latch keyed by (kind, key_tuple) -> ISO date str.
# Total-flushed by ``reset_latches_for_tests`` (test-only). In production
# the calendar-day change alone re-arms the latch — no manual clear needed
# except for the paired recover semantics of D4-X7.
_LATCHES: dict[Tuple[str, Tuple[Any, ...]], str] = {}

# M-4 fix-up 2026-07-28: track keys that have EVER emitted a stuck NM in
# this process so `fire_stuck_signal_recovered` can skip the recovery
# emit when no prior stuck was fired (avoids spurious "recovered" for
# entities that were never flagged). Cleared on `reset_latches_for_tests`.
_STUCK_SIGNAL_NOTIFIED: set[Tuple[str, Tuple[Any, ...]]] = set()

# v5.36.0 D1 ledger — per-kind emit stats. RAM-only (resets on restart);
# populated in `fire_stuck_signal` on successful dispatch; read via
# `get_emit_stats()` for the house-level diagnostic sensor.
# Shape: { kind: {"last_fired": ISO_str, "fires_today": int, "date": ISO_date} }
_EMIT_STATS: dict[str, dict[str, Any]] = {}

# Ship 3b review B-L4: (kind, key) of fire_stuck_signal_ex sends awaiting
# their dispatch. A second sender of the same key inside that window gets
# NOT_SENT (no latch; it retries next tick and then reads ALREADY_SENT).
# Pre-existing and NOT closed here: a task cancelled inside
# ``nm.async_notify`` (owner teardown) can deliver the NM without setting
# the latch, because ``fire_stuck_signal`` latches after its await.
_SEND_INFLIGHT: set[Tuple[str, Tuple[Any, ...]]] = set()


def _kill_switch_on(hass: HomeAssistant) -> bool:
    """Return True when NM emits are ENABLED (default True).

    Reads the rung-2 kill switch via the NM Cycle A knob cache, so an
    options-flow flip takes effect on the next call without restart.
    Falls back to the default on lookup failure (fail-open: an unreadable
    CM options entry should not silence stuck-signal alerts).
    """
    try:
        return bool(nm_cycle_a_knob(
            hass, CONF_STUCK_SIGNAL_NM_ENABLED, DEFAULT_STUCK_SIGNAL_NM_ENABLED,
        ))
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "stuck_signal kill-switch read failed (fail-open, default enabled)",
            exc_info=True,
        )
        return DEFAULT_STUCK_SIGNAL_NM_ENABLED


def _today_iso(now: datetime | None = None) -> str:
    """Return today's date as ISO string in LOCAL time.

    A-MED-4 fix-up 2026-07-28: uses LOCAL date (`dt_util.now()`), NOT UTC.
    Otherwise the operator-visible "one alert per day" boundary flips at
    UTC midnight (5 pm–8 pm local depending on TZ), which is confusing.
    """
    if now is None:
        now = dt_util.now()
    return now.date().isoformat()


# M-6 / A-LOW-4 fix-up 2026-07-28: prune latch entries older than this
# many days on every write, so the module dict cannot grow unboundedly
# across long HA uptimes.
_LATCH_MAX_AGE_DAYS: int = 30


def _prune_stale_latches(today: str) -> None:
    """Drop latch entries whose date is older than _LATCH_MAX_AGE_DAYS."""
    try:
        cutoff_days = _LATCH_MAX_AGE_DAYS
        today_date = datetime.fromisoformat(today).date()
        stale = []
        for k, v in _LATCHES.items():
            try:
                d = datetime.fromisoformat(v).date()
                if (today_date - d).days > cutoff_days:
                    stale.append(k)
            except (TypeError, ValueError):
                stale.append(k)
        for k in stale:
            _LATCHES.pop(k, None)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("_prune_stale_latches failed (swallowed)", exc_info=True)


async def _write_stuck_anomaly(
    hass: HomeAssistant,
    kind: str,
    key: Tuple[Any, ...],
    diagnosis: str,
    exclusion_engaged: bool = False,
) -> None:
    """Persist a POINT_IN_TIME anomaly row for a stuck-signal emit.

    v5.36.0 D2. Mirrors the shape used by
    ``energy_write_verify._emit_anomaly`` (grep write_verification_failed):
    build the AnomalyEvent + call ``database.save_anomaly_event``. Local
    imports guard the circular-load hazard the module docstring calls out.
    Fail-open: any exception is swallowed by the caller wrapper.
    """
    from ..const import DOMAIN as _DOMAIN  # noqa: PLC0415
    from .anomaly_event import (  # noqa: PLC0415
        AnomalyEvent,
        AnomalySeverity,
        AnomalyType,
        build_context_json,
    )

    database = hass.data.get(_DOMAIN, {}).get("database")
    if database is None:
        return
    # STUCK-SENSOR-1 MED-2: `exclusion_engaged` present in the extra
    # dict ONLY when True. Pre-cycle rows omit the field entirely so
    # ledger_golden fixtures replay byte-identical.
    extra: dict[str, Any] = {
        "kind": kind, "key": list(key), "diagnosis": diagnosis,
    }
    if exclusion_engaged:
        extra["exclusion_engaged"] = True
    payload = build_context_json(source_signal="stuck_signal", extra=extra)
    event = AnomalyEvent(
        coordinator="stuck_signal",
        type=str(kind),
        severity=AnomalySeverity.WARNING,
        anomaly_type=AnomalyType.POINT_IN_TIME,
        detected_at=dt_util.utcnow().isoformat(),
        payload=payload,
    )
    await database.save_anomaly_event(event)


async def fire_stuck_signal(
    hass: HomeAssistant,
    kind: str,
    key: Tuple[Any, ...],
    diagnosis: str,
    remedy: str = "",
    now: datetime | None = None,
    title_override: str | None = None,
    exclusion_engaged: bool = False,
    severity: str | None = None,
) -> bool:
    """Fire a stuck_signal NM once per (kind, key) per calendar day.

    ``severity``: optional ``Severity`` member NAME (e.g. "HIGH"), the same
    per-call pattern as the HVAC S10 latches (``hvac._s10_notify``).
    None -> MEDIUM, byte-identical for every existing caller. MEDIUM reaches
    no channel under the live NM config (HVAC state of play, S10 latch
    note), so a trip-wire meant to page passes "HIGH".

    Returns True iff the NM was actually dispatched this call. False on
    kill-switch off, latch already fired today, missing NM, NM dropped it
    before delivery (no latch is set then), or exception.

    Never raises.
    """
    try:
        if not _kill_switch_on(hass):
            return False
        latch_key = (kind, tuple(key))
        today = _today_iso(now)
        if _LATCHES.get(latch_key) == today:
            _LOGGER.debug(
                "stuck_signal: latch suppressed %s/%s (already fired %s)",
                kind, key, today,
            )
            return False
        nm = hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            _LOGGER.debug(
                "stuck_signal: NotificationManager not available (kind=%s)",
                kind,
            )
            return False
        # Local import to sidestep circular loads (const.py cannot depend on
        # notification_manager.py); Bug Class #34 does NOT apply because
        # this is not a dispatcher/event-helper import.
        from .notification_manager import Severity  # noqa: PLC0415

        # P24 diagnosability fix (2026-08-10): callers may pass
        # `title_override` to include context (e.g. room + duration) in
        # the title. The title is persisted in `_emit_audit_row` — the
        # `message` field there is a "[audit]" sentinel, so a bare
        # `f"Stuck signal: {kind}"` title left P24 audit rows un-
        # attributable to a room.
        title = title_override or f"Stuck signal: {kind}"
        message = diagnosis
        # STUCK-SENSOR-1 D2b (MED-2): append the exclusion_engaged marker
        # to the message body ONLY when True; absent otherwise so
        # existing per-kind diagnosis strings remain byte-identical.
        if exclusion_engaged:
            message = f"{message}\n[exclusion_engaged: true]"
        if remedy:
            message = f"{message}\n\nSuggested remedy: {remedy}"
        delivered = await nm.async_notify(
            coordinator_id=STUCK_SIGNAL_NM_COORDINATOR_ID,
            severity=(
                getattr(Severity, severity) if severity else Severity.MEDIUM
            ),
            title=title,
            message=message,
            hazard_type=STUCK_SIGNAL_NM_HAZARD_TYPE,
            location=str(kind),
        )
        # STUCK-SENSOR-S3B-S1-1: NM dropped it before delivery (boot-settle,
        # dedup, quiet hours, silence, kill switch) -> no day latch, so the
        # next tick re-offers it (the discharge). ``is False`` keeps any NM
        # stand-in that returns None on the old latch-on-call behaviour.
        if delivered is False:
            _LOGGER.debug(
                "stuck_signal: NM dropped %s/%s before delivery; not latched",
                kind, key,
            )
            return False
        _LATCHES[latch_key] = today
        _STUCK_SIGNAL_NOTIFIED.add(latch_key)
        _prune_stale_latches(today)
        # v5.36.0 D1 ledger update — per-kind last_fired / fires_today.
        try:
            stats = _EMIT_STATS.get(kind)
            if stats is None or stats.get("date") != today:
                stats = {"date": today, "fires_today": 0, "last_fired": None}
                _EMIT_STATS[kind] = stats
            stats["fires_today"] = int(stats.get("fires_today", 0)) + 1
            stats["last_fired"] = (now or dt_util.now()).isoformat()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("stuck_signal ledger update failed", exc_info=True)
        # v5.36.0 D2 — persist an anomaly row (per-day-latched, so ≤1 per
        # (kind,key) per day; no write-flood risk). Wrapped: a DB failure
        # must NEVER block the NM emit path above.
        try:
            await _write_stuck_anomaly(
                hass, kind, key, diagnosis,
                exclusion_engaged=exclusion_engaged,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "stuck_signal anomaly write failed (swallowed): kind=%s key=%s",
                kind, key, exc_info=True,
            )
        _LOGGER.info(
            "stuck_signal NM fired: kind=%s key=%s diagnosis=%s",
            kind, key, diagnosis,
        )
        return True
    except Exception:  # noqa: BLE001 — never propagate into caller pipeline
        _LOGGER.debug(
            "stuck_signal fire failed (swallowed): kind=%s key=%s",
            kind, key, exc_info=True,
        )
        return False


# Person-awareness ship 3b (§6.6 "Send result"): a send result that tells
# "already sent and not recovered" from "not sent". ``fire_stuck_signal``
# keeps its bool for every existing caller.
SENT = "sent"
ALREADY_SENT = "already_sent"
NOT_SENT = "not_sent"


def stuck_signal_notified(kind: str, key: Tuple[Any, ...]) -> bool:
    """True iff ``(kind, key)`` was sent and not yet recovered (any date).
    Pure read of the notified set (the owner's adoption of a room page)."""
    try:
        return (kind, tuple(key)) in _STUCK_SIGNAL_NOTIFIED
    except Exception:  # noqa: BLE001
        return False


def stuck_signal_dispatch_ready(hass: HomeAssistant) -> bool:
    """Ship 3b review B-L6: a stuck-signal NM can dispatch now (the kill
    switch is on and the NotificationManager is present). Callers that
    re-offer a page every tick skip scheduling a send while this is False
    (no task churn while NM is off); the next tick after NM comes up sends.
    Never raises (False on error)."""
    try:
        if not _kill_switch_on(hass):
            return False
        return hass.data.get(DOMAIN, {}).get("notification_manager") is not None
    except Exception:  # noqa: BLE001
        return False


async def fire_stuck_signal_ex(
    hass: HomeAssistant,
    kind: str,
    key: Tuple[Any, ...],
    diagnosis: str,
    remedy: str = "",
    now: datetime | None = None,
    title_override: str | None = None,
    exclusion_engaged: bool = False,
    severity: str | None = None,
) -> str:
    """``fire_stuck_signal`` with a three-way result.

    ``ALREADY_SENT`` whenever ``(kind, key)`` is in the notified set, i.e.
    sent and not yet recovered, WHATEVER the date: the per-day ``_LATCHES``
    test alone would let a room page at 23:59 and an owner tick at 00:01
    both send. ``SENT`` when this call dispatched; ``NOT_SENT`` otherwise
    (NM missing, kill switch off, exception): retry next tick. The
    recovery (``fire_stuck_signal_recovered``) clears the notified set, so
    a later outage pages again. Never raises.
    """
    try:
        if stuck_signal_notified(kind, key):
            return ALREADY_SENT
        flight = (kind, tuple(key))
        if flight in _SEND_INFLIGHT:
            return NOT_SENT  # review B-L4: the same key is being sent
        _SEND_INFLIGHT.add(flight)
        try:
            ok = await fire_stuck_signal(
                hass, kind=kind, key=key, diagnosis=diagnosis, remedy=remedy,
                now=now, title_override=title_override,
                exclusion_engaged=exclusion_engaged, severity=severity,
            )
        finally:
            _SEND_INFLIGHT.discard(flight)
    except Exception:  # noqa: BLE001
        return NOT_SENT
    return SENT if ok is True else NOT_SENT


async def fire_stuck_signal_recovered(
    hass: HomeAssistant,
    kind: str,
    key: Tuple[Any, ...],
    message: str,
    now: datetime | None = None,
) -> bool:
    """Companion to :func:`fire_stuck_signal` for paired recovery events.

    Used by D4-X7 (actuator flap quarantine) when a quarantined entity
    releases — emits a "recovered" NM and CLEARS the corresponding latch
    so a future flap on the same entity re-notifies immediately (rather
    than waiting for next-day rollover).

    Returns True iff a recovery NM was dispatched.
    """
    latch_key = (kind, tuple(key))
    # M-4 fix-up 2026-07-28: recovery emit conditional on a prior stuck
    # emit for this (kind, key). Without this we'd send phantom
    # "recovered" NMs for entities that were never flagged.
    if latch_key not in _STUCK_SIGNAL_NOTIFIED:
        _LATCHES.pop(latch_key, None)
        return False
    _STUCK_SIGNAL_NOTIFIED.discard(latch_key)
    # Clear the latch first so a re-arm can fire immediately even if the
    # NM dispatch below fails.
    _LATCHES.pop(latch_key, None)
    try:
        if not _kill_switch_on(hass):
            return False
        nm = hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return False
        from .notification_manager import Severity  # noqa: PLC0415

        await nm.async_notify(
            coordinator_id=STUCK_SIGNAL_NM_COORDINATOR_ID,
            severity=Severity.LOW,
            title=f"Stuck signal recovered: {kind}",
            message=message,
            hazard_type=STUCK_SIGNAL_NM_HAZARD_TYPE,
            location=str(kind),
        )
        _LOGGER.info(
            "stuck_signal recovery NM fired: kind=%s key=%s", kind, key,
        )
        return True
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "stuck_signal recovery fire failed (swallowed): kind=%s key=%s",
            kind, key, exc_info=True,
        )
        return False


def reset_latches_for_tests() -> None:
    """Drop all per-day latches. Test-only helper."""
    _LATCHES.clear()
    _STUCK_SIGNAL_NOTIFIED.clear()
    _EMIT_STATS.clear()
    _SEND_INFLIGHT.clear()


def get_emit_stats() -> dict[str, dict[str, Any]]:
    """Return a copy of the per-kind NM emit ledger.

    RAM-only ledger (resets on HA restart, documented on the sensor).
    Shape: ``{kind: {"last_fired": ISO, "fires_today": int, "date": ISO}}``.
    Consumed by the house-level `sensor.ura_stuck_signal_watchdog`.
    """
    return {k: dict(v) for k, v in _EMIT_STATS.items()}


def latch_snapshot_for_tests() -> dict[Tuple[str, Tuple[Any, ...]], str]:
    """Return a copy of the current latch map. Test-only helper."""
    return dict(_LATCHES)
