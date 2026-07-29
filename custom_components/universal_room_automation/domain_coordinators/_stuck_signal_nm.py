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
    payload = build_context_json(
        source_signal="stuck_signal",
        extra={"kind": kind, "key": list(key), "diagnosis": diagnosis},
    )
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
) -> bool:
    """Fire a stuck_signal NM once per (kind, key) per calendar day.

    Returns True iff the NM was actually dispatched this call. False on
    kill-switch off, latch already fired today, missing NM, or exception.

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

        title = f"Stuck signal: {kind}"
        message = diagnosis
        if remedy:
            message = f"{diagnosis}\n\nSuggested remedy: {remedy}"
        await nm.async_notify(
            coordinator_id=STUCK_SIGNAL_NM_COORDINATOR_ID,
            severity=Severity.MEDIUM,
            title=title,
            message=message,
            hazard_type=STUCK_SIGNAL_NM_HAZARD_TYPE,
            location=str(kind),
        )
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
            await _write_stuck_anomaly(hass, kind, key, diagnosis)
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
