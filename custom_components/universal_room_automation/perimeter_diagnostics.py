"""Perimeter diagnostic helpers (CIRCLING-SEVERITY-1 D3).

Extracted from the sensor to be independently testable. See
`docs/planning/PLANNING_circling_severity.md` §D3.

INV-M: a track classified `circling` at a perimeter camera dispatches
at least once (`alert_count >= 1`) in every house state EXCEPT `guest`,
provided the linker + NM are enabled.

D3 is the enforcement machinery. Every one of trace paths 5-7 (NM raise,
teardown short-circuit, cancelled delayed dispatch) leaves a `circling`
track with `alert_count == 0` and no other observable signal. This
helper reads the linker's in-memory open + recently-closed tracks and
returns the count + offending track_ids.

Live-tripwire semantics: no persisted counter, HA restart drops state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Iterable

from homeassistant.util import dt as dt_util

from .const import CIRCLING_DIAG_LOOKBACK_HOURS

_LOGGER = logging.getLogger(__name__)


def _iter_person_tracks_for_diag(linker: Any) -> Iterable[Any]:
    """Yield every ExteriorTrack (open + recently-closed) with label='person'.

    Best-effort: linker internals are private; any AttributeError falls
    through as an empty iterator (fail-open — the diagnostic returns 0).
    """
    try:
        open_by_label = getattr(linker, "_tracks", {}) or {}
        for t in open_by_label.get("person", []) or []:
            yield t
    except Exception:  # noqa: BLE001
        _LOGGER.debug("perimeter_diagnostics: open tracks iter failed", exc_info=True)
    try:
        for t in getattr(linker, "_closed_recent", []) or []:
            if getattr(t, "label", None) == "person":
                yield t
    except Exception:  # noqa: BLE001
        _LOGGER.debug("perimeter_diagnostics: closed tracks iter failed", exc_info=True)


def count_circling_zero_dispatch(
    linker: Any,
    now: datetime | None = None,
    lookback_hours: int = CIRCLING_DIAG_LOOKBACK_HOURS,
) -> tuple[int, list[dict]]:
    """Return (count, offending_tracks) for INV-M enforcement.

    A track is offending iff:
      * label == 'person'
      * classify(t) == 'circling'
      * alert_count == 0
      * started_at within the last `lookback_hours`

    Returns up to the 10 newest offenders (attribute list). Fail-open:
    any exception collapses to (0, []) — diagnostic never poisons the
    dispatch path.
    """
    if linker is None:
        return 0, []
    now = now or dt_util.now()
    try:
        cutoff = now - timedelta(hours=lookback_hours)
    except Exception:  # noqa: BLE001
        return 0, []

    offenders: list[tuple[datetime, dict]] = []
    for t in _iter_person_tracks_for_diag(linker):
        try:
            if int(getattr(t, "alert_count", 0) or 0) != 0:
                continue
            started_at = getattr(t, "started_at", None)
            if started_at is None:
                continue
            # Tz-tolerant comparison: coerce mismatched aware/naive to naive.
            try:
                if started_at < cutoff:
                    continue
            except TypeError:
                _sa = started_at.replace(tzinfo=None) if started_at.tzinfo else started_at
                _cu = cutoff.replace(tzinfo=None) if cutoff.tzinfo else cutoff
                if _sa < _cu:
                    continue
            classification = linker.classify(t)
            if classification != "circling":
                continue
            offenders.append(
                (
                    started_at,
                    {
                        "track_id": getattr(t, "track_id", "?"),
                        "first_seen_at": started_at.isoformat(),
                    },
                )
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "perimeter_diagnostics: per-track eval failed", exc_info=True,
            )
            continue

    # Newest first, cap at 10 for the attribute payload.
    offenders.sort(key=lambda x: x[0], reverse=True)
    attrs = [a for _, a in offenders[:10]]
    return len(offenders), attrs
