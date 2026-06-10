"""Routine-Awareness Next-State Forecaster.

Frequency/recency forecaster over ``house_state_log`` rows. Produces
P(next_state | current_state, day_type, time_bin) plus a median transition
ETA, in service of the v4.6.9 D1 PWA contract sensor
``sensor.ura_presence_coordinator_next_state``.

Design (see ``docs/planning/PLANNING_routine_awareness_next_state_forecaster.md``):
  * In-memory aggregate keyed by ``(prev_state_str, day_type, time_bin)``.
  * Refreshed periodically (``ROUTINE_FORECAST_REFRESH_SECONDS``) from a
    bounded read (``ROUTINE_FORECAST_MAX_ROWS`` rows over
    ``ROUTINE_FORECAST_HISTORY_DAYS``). No new DB writes anywhere
    (post-v5.x write-flood discipline).
  * Incrementally updated on each ``SIGNAL_HOUSE_STATE_CHANGED`` signal —
    appends a single row to the aggregate without re-reading the DB.
  * ``predict(current_state)`` cascades through coarser cells when support
    is thin: (C, dt, tb) → (C, dt, *) → (C, *, *) → ``unknown / 0.0``.
  * Output vocabulary collapsed to ``_NextStateVocab`` (sensor.py) — but
    histograms keep the raw HouseState granularity so ETA medians stay
    meaningful.

Bug-class guards (see ``docs/QUALITY_CONTEXT.md``):
  * #14 (config staleness): no caching of predictions; ``predict`` always
    recomputes from the live aggregate.
  * #19 (untracked background tasks): the ``async_track_time_interval``
    unsub is stored on ``self._unsub_refresh`` AND cleaned up in
    ``async_shutdown``.
  * #34 (function-local imports): all imports — datetime, dt_util,
    helpers — are module-level.
  * #50 (subscription clobber): the dispatcher unsub is stored on a
    dedicated attribute (``self._unsub_signal``), NOT a shared list that
    another path might rebuild and clobber.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Final

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from ..const import (
    DOMAIN,
    ROUTINE_FORECAST_HISTORY_DAYS,
    ROUTINE_FORECAST_MAX_ROWS,
    ROUTINE_FORECAST_MIN_SUPPORT,
    ROUTINE_FORECAST_MODEL_ID,
    ROUTINE_FORECAST_REFRESH_SECONDS,
)
from .signals import SIGNAL_HOUSE_STATE_CHANGED

_LOGGER = logging.getLogger(__name__)

# Time bin / day-type helpers — bin definition mirrors
# bayesian_predictor._hour_to_time_bin and _day_type so the forecaster's
# cells align with RegimeDetector's cell vocabulary (existing learned
# routine geometry).
_TIME_BINS: Final[int] = 6  # 0..5


def _hour_to_time_bin(hour: int) -> int:
    """Return time bin 0..5 — mirrors bayesian_predictor._hour_to_time_bin."""
    if hour < 6:
        return 0
    if hour < 9:
        return 1
    if hour < 12:
        return 2
    if hour < 17:
        return 3
    if hour < 21:
        return 4
    return 5


def _day_type(dt: datetime) -> int:
    """Return 0 for weekday, 1 for weekend."""
    return 1 if dt.weekday() >= 5 else 0


# Vocab-collapse table — HouseState string -> _NextStateVocab string. The
# sensor side validates against the StrEnum; this table is the single
# source of truth for the mapping. Keep it exhaustive over HouseState
# (presence guarantee: all rows are HouseState values) so we never feed
# the validator a value it doesn't recognise (Bug Class #22).
_VOCAB_COLLAPSE: Final[dict[str, str]] = {
    "away": "away",
    "arriving": "home_day",
    "home_day": "home_day",
    "home_evening": "home_night",
    "home_night": "home_night",
    "sleep": "sleep",
    "waking": "home_day",
    "guest": "guest",
    "vacation": "vacation",
}

_GUEST_PASSTHROUGH_STATES: Final[frozenset[str]] = frozenset({"guest", "vacation"})


def _collapse_vocab(state: str) -> str:
    """Collapse a raw HouseState string to the _NextStateVocab string.

    Unknown / unexpected inputs collapse to ``"unknown"`` to keep the
    sensor's StrEnum validator happy (Bug Class #22).
    """
    return _VOCAB_COLLAPSE.get(state, "unknown")


class RoutineForecaster:
    """In-memory frequency/recency forecaster over house_state_log."""

    def __init__(self, hass: HomeAssistant, database: Any) -> None:
        self.hass = hass
        self._db = database

        # Aggregate: counts[(prev_state, day_type, time_bin)][next_state] = N
        self._counts: dict[tuple[str, int, int], dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        # etas[(prev_state, day_type, time_bin)][next_state] = list[float seconds]
        self._etas: dict[tuple[str, int, int], dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # Track last row we've seen so incremental updates can compute
        # dwell time without re-reading the DB.
        self._last_row_ts: datetime | None = None
        self._last_row_state: str | None = None

        # Lifecycle unsubs — dedicated attributes per Bug Class #50
        # (NEVER appended to a shared list another path rebuilds).
        self._unsub_refresh: Any = None
        self._unsub_signal: Any = None

        # Telemetry for diagnostics
        self._last_refresh_iso: str | None = None
        self._refresh_row_count: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Subscribe to signals + schedule periodic refresh; do initial aggregation.

        Safe to call multiple times — repeat calls are no-ops thanks to the
        unsub guards. The caller (PresenceCoordinator) owns the lifecycle.
        """
        # Initial aggregate from DB. Safe under boot-settle: predict() gates
        # its OWN output on _boot_settle_done (via caller), but the
        # aggregate itself is harmless to build early.
        try:
            await self.async_refresh()
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "RoutineForecaster: initial refresh raised (non-fatal); "
                "predict will return unknown until next refresh",
                exc_info=True,
            )

        # Periodic refresh — store unsub on dedicated attribute per #50.
        if self._unsub_refresh is None:
            try:
                self._unsub_refresh = async_track_time_interval(
                    self.hass,
                    self._handle_refresh_tick,
                    timedelta(seconds=ROUTINE_FORECAST_REFRESH_SECONDS),
                )
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.debug(
                    "RoutineForecaster: failed to schedule refresh interval",
                    exc_info=True,
                )

        # Incremental update on each house-state transition.
        if self._unsub_signal is None:
            try:
                self._unsub_signal = async_dispatcher_connect(
                    self.hass,
                    SIGNAL_HOUSE_STATE_CHANGED,
                    self._handle_house_state_change,
                )
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.debug(
                    "RoutineForecaster: failed to subscribe to "
                    "SIGNAL_HOUSE_STATE_CHANGED",
                    exc_info=True,
                )

        _LOGGER.info(
            "RoutineForecaster: setup complete (cells=%d, last_refresh=%s)",
            len(self._counts),
            self._last_refresh_iso,
        )

    async def async_shutdown(self) -> None:
        """Cancel timer + signal subscription (Bug Class #19 + #50)."""
        if self._unsub_refresh is not None:
            try:
                self._unsub_refresh()
            except Exception:  # noqa: BLE001
                pass
            self._unsub_refresh = None
        if self._unsub_signal is not None:
            try:
                self._unsub_signal()
            except Exception:  # noqa: BLE001
                pass
            self._unsub_signal = None
        _LOGGER.debug("RoutineForecaster: shutdown complete")

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    @callback
    def _handle_refresh_tick(self, _now: Any = None) -> None:
        """async_track_time_interval callback — kicks an async refresh."""
        self.hass.async_create_task(self.async_refresh())

    async def async_refresh(self) -> None:
        """Re-read the bounded window and rebuild the aggregate from scratch.

        Bounded by ``ROUTINE_FORECAST_HISTORY_DAYS`` (cutoff) and
        ``ROUTINE_FORECAST_MAX_ROWS`` (LIMIT) — read-only.
        """
        if self._db is None:
            return
        try:
            cutoff_dt = dt_util.utcnow() - timedelta(
                days=ROUTINE_FORECAST_HISTORY_DAYS
            )
            since_iso = cutoff_dt.isoformat()
            rows = await self._db.fetch_house_state_log_since(
                since_iso, ROUTINE_FORECAST_MAX_ROWS
            )
        except Exception:  # noqa: BLE001 — defensive against DB-down
            _LOGGER.debug(
                "RoutineForecaster: fetch_house_state_log_since raised",
                exc_info=True,
            )
            return

        # Fresh aggregate — rebuild from scratch so dropped rows fall out
        # of the rolling window (Bug Class #46: never re-derive lazily;
        # eagerly recompute at refresh).
        new_counts: dict[tuple[str, int, int], dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        new_etas: dict[tuple[str, int, int], dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # Walk rows chronologically. Each row records a transition from
        # ``previous_state`` -> ``state`` AT ``timestamp``. We need the
        # time the previous_state BEGAN to compute dwell — that is the
        # timestamp of the row BEFORE this one whose ``state`` equals
        # this row's ``previous_state``. The simplest correct mapping:
        # track the timestamp of the most recently emitted row (because
        # the prior row's ``state`` is by definition this row's
        # ``previous_state``); the dwell is now - prior_ts and the cell
        # is keyed by (previous_state, dt(prior_ts), tb(prior_ts)).
        prior_ts: datetime | None = None
        prior_state: str | None = None
        for row in rows:
            try:
                ts = self._parse_ts(row.get("timestamp"))
                if ts is None:
                    continue
                state = row.get("state")
                prev = row.get("previous_state")
                if not state or not prev:
                    prior_ts = ts
                    prior_state = state
                    continue

                # Exclude guest/vacation prev_state rows from non-guest
                # cells — prevents bleed-through during long guest runs
                # (mirrors RegimeDetector's defensive posture).
                if prev in _GUEST_PASSTHROUGH_STATES:
                    prior_ts = ts
                    prior_state = state
                    continue

                # Convert ts to local for binning — routine is local-time-keyed.
                local_ref = ts
                try:
                    local_ref = dt_util.as_local(ts)
                except Exception:  # noqa: BLE001
                    pass
                # The cell is keyed on when ``prev`` BEGAN. If we have a
                # prior_ts AND it lines up (prior_state == prev), use it.
                # Otherwise fall back to this row's local time as a
                # best-effort key (most rows still get the right bin
                # because transitions usually stay within one bin).
                if prior_ts is not None and prior_state == prev:
                    try:
                        cell_ref = dt_util.as_local(prior_ts)
                    except Exception:  # noqa: BLE001
                        cell_ref = prior_ts
                    dwell_seconds = max(
                        0.0, (ts - prior_ts).total_seconds()
                    )
                else:
                    cell_ref = local_ref
                    dwell_seconds = 0.0

                cell = (
                    prev,
                    _day_type(cell_ref),
                    _hour_to_time_bin(cell_ref.hour),
                )
                new_counts[cell][state] += 1
                if dwell_seconds > 0:
                    new_etas[cell][state].append(dwell_seconds)

                prior_ts = ts
                prior_state = state
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "RoutineForecaster: malformed log row skipped",
                    exc_info=True,
                )
                continue

        self._counts = new_counts
        self._etas = new_etas
        self._last_refresh_iso = dt_util.utcnow().isoformat()
        self._refresh_row_count = len(rows)
        # Seed incremental tracker from the last row we saw.
        self._last_row_ts = prior_ts
        self._last_row_state = prior_state
        _LOGGER.info(
            "RoutineForecaster: refreshed aggregate from %d rows; %d cells",
            self._refresh_row_count,
            len(self._counts),
        )

    @callback
    def _handle_house_state_change(self, payload: Any) -> None:
        """Incremental update on SIGNAL_HOUSE_STATE_CHANGED.

        Payload shape (verified in presence.py:4706): dict with
        ``old_state``, ``new_state``, ``trigger``, ``confidence``.
        Some callers may pass a HouseStateChange dataclass — handle both.
        """
        try:
            if isinstance(payload, dict):
                prev = payload.get("old_state") or payload.get("previous_state")
                state = payload.get("new_state")
            else:
                prev = getattr(payload, "previous_state", None) or getattr(
                    payload, "old_state", None
                )
                state = getattr(payload, "new_state", None)
            if not prev or not state:
                return

            now_utc = dt_util.utcnow()
            try:
                local_ref = dt_util.as_local(now_utc)
            except Exception:  # noqa: BLE001
                local_ref = now_utc

            # Skip guest/vacation prev_state to keep cells clean.
            if prev not in _GUEST_PASSTHROUGH_STATES:
                if self._last_row_ts is not None and self._last_row_state == prev:
                    try:
                        cell_ref = dt_util.as_local(self._last_row_ts)
                    except Exception:  # noqa: BLE001
                        cell_ref = self._last_row_ts
                    dwell_seconds = max(
                        0.0, (now_utc - self._last_row_ts).total_seconds()
                    )
                else:
                    cell_ref = local_ref
                    dwell_seconds = 0.0
                cell = (
                    prev,
                    _day_type(cell_ref),
                    _hour_to_time_bin(cell_ref.hour),
                )
                self._counts[cell][state] = self._counts[cell].get(state, 0) + 1
                if dwell_seconds > 0:
                    self._etas[cell][state].append(dwell_seconds)

            self._last_row_ts = now_utc
            self._last_row_state = state
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "RoutineForecaster: incremental update raised", exc_info=True
            )

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, current_state: Any) -> dict:
        """Return the next-state prediction in the D1 PWA contract shape.

        ``current_state`` may be a HouseState enum, a raw string, or
        anything with a ``value`` attribute. Robust to either; if it
        can't be coerced to a string we fall back to ``unknown``.
        """
        current_str = self._coerce_state_str(current_state)
        predicted_at_iso = dt_util.utcnow().isoformat()

        # Guest / vacation passthrough — sparse, unreliable data; emit
        # the current vocab with low confidence and no ETA. This keeps
        # the PWA tile from showing "unknown" during real guest runs.
        if current_str in _GUEST_PASSTHROUGH_STATES:
            vocab_state = _collapse_vocab(current_str)
            return {
                "state": vocab_state,
                "confidence": 0.3,
                "predicted_at_iso": predicted_at_iso,
                "model": f"{ROUTINE_FORECAST_MODEL_ID}+guest_passthrough",
                "current_state": current_str,
                "transition_eta_minutes": None,
            }

        now_local = dt_util.as_local(dt_util.utcnow())
        day_type = _day_type(now_local)
        time_bin = _hour_to_time_bin(now_local.hour)

        # Cascade through coarser cells.
        cell_counts, cell_etas = self._lookup_with_cascade(
            current_str, day_type, time_bin
        )

        if not cell_counts:
            return self._unknown(predicted_at_iso, current_str)

        total = sum(cell_counts.values())
        if total < ROUTINE_FORECAST_MIN_SUPPORT:
            return self._unknown(predicted_at_iso, current_str)

        # Argmax. If the argmax collapses to the same vocab as the
        # current state, prefer the second-place candidate that
        # collapses OFF-DIAGONAL — avoids the "next state = current
        # state" UX bug for cases like home_evening -> home_night when
        # currently at home_night.
        current_vocab = _collapse_vocab(current_str)
        sorted_candidates = sorted(
            cell_counts.items(), key=lambda kv: kv[1], reverse=True
        )
        chosen_state: str | None = None
        chosen_count: int = 0
        for cand_state, cand_n in sorted_candidates:
            cand_vocab = _collapse_vocab(cand_state)
            if cand_vocab == current_vocab:
                continue  # off-diagonal preferred
            chosen_state = cand_state
            chosen_count = cand_n
            break

        if chosen_state is None:
            # All support collapses to the current vocab — honest unknown
            # is better than a self-pointing prediction.
            return self._unknown(predicted_at_iso, current_str)

        confidence = max(0.0, min(1.0, chosen_count / total))
        eta_minutes: int | None = None
        eta_samples = cell_etas.get(chosen_state) or []
        if eta_samples:
            try:
                median_seconds = statistics.median(eta_samples)
                eta_minutes = int(round(median_seconds / 60.0))
            except Exception:  # noqa: BLE001
                eta_minutes = None

        return {
            "state": _collapse_vocab(chosen_state),
            "confidence": float(confidence),
            "predicted_at_iso": predicted_at_iso,
            "model": ROUTINE_FORECAST_MODEL_ID,
            "current_state": current_str,
            "transition_eta_minutes": eta_minutes,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _lookup_with_cascade(
        self,
        current_str: str,
        day_type: int,
        time_bin: int,
    ) -> tuple[dict[str, int], dict[str, list[float]]]:
        """Return (counts, etas) for the first cell with sufficient support.

        Cascade: (C, dt, tb) -> (C, dt, *) -> (C, *, *) -> ({}, {}).
        """
        # Exact cell.
        exact_counts = self._counts.get((current_str, day_type, time_bin))
        if exact_counts and sum(exact_counts.values()) >= ROUTINE_FORECAST_MIN_SUPPORT:
            return (
                dict(exact_counts),
                dict(self._etas.get((current_str, day_type, time_bin), {})),
            )

        # Day-type cell, any time bin.
        dt_counts: dict[str, int] = defaultdict(int)
        dt_etas: dict[str, list[float]] = defaultdict(list)
        for tb in range(_TIME_BINS):
            c = self._counts.get((current_str, day_type, tb))
            if not c:
                continue
            for k, v in c.items():
                dt_counts[k] += v
            e = self._etas.get((current_str, day_type, tb)) or {}
            for k, v in e.items():
                dt_etas[k].extend(v)
        if dt_counts and sum(dt_counts.values()) >= ROUTINE_FORECAST_MIN_SUPPORT:
            return dict(dt_counts), dict(dt_etas)

        # State-only cell, any day_type + any time_bin.
        any_counts: dict[str, int] = defaultdict(int)
        any_etas: dict[str, list[float]] = defaultdict(list)
        for dt in (0, 1):
            for tb in range(_TIME_BINS):
                c = self._counts.get((current_str, dt, tb))
                if not c:
                    continue
                for k, v in c.items():
                    any_counts[k] += v
                e = self._etas.get((current_str, dt, tb)) or {}
                for k, v in e.items():
                    any_etas[k].extend(v)
        if any_counts and sum(any_counts.values()) >= ROUTINE_FORECAST_MIN_SUPPORT:
            return dict(any_counts), dict(any_etas)

        return {}, {}

    @staticmethod
    def _coerce_state_str(current_state: Any) -> str:
        """Coerce HouseState | str | other to a string. Defaults to ``unknown``."""
        if current_state is None:
            return "unknown"
        if isinstance(current_state, str):
            return current_state
        val = getattr(current_state, "value", None)
        if isinstance(val, str):
            return val
        try:
            return str(current_state)
        except Exception:  # noqa: BLE001
            return "unknown"

    @staticmethod
    def _unknown(predicted_at_iso: str, current_str: str) -> dict:
        """Stable-shape ``unknown / 0.0`` response (Bug Class #29 / #37)."""
        return {
            "state": "unknown",
            "confidence": 0.0,
            "predicted_at_iso": predicted_at_iso,
            "model": ROUTINE_FORECAST_MODEL_ID,
            "current_state": current_str,
            "transition_eta_minutes": None,
        }

    @staticmethod
    def _parse_ts(raw: Any) -> datetime | None:
        """Parse an ISO timestamp from house_state_log; return None on failure."""
        if not isinstance(raw, str):
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            # Fall back: strip 'Z' suffix sometimes appended by writers.
            try:
                parsed = datetime.fromisoformat(raw.rstrip("Z"))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            try:
                parsed = dt_util.as_utc(parsed)
            except Exception:  # noqa: BLE001
                # Assume UTC if dt_util can't help (unit-test stub).
                from datetime import timezone

                parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
