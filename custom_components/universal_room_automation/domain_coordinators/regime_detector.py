"""Jensen-Shannon divergence regime detector for Universal Room Automation.

v4.6.2 D4 + D7: Nightly batch detection of household routine shifts.

Per (person, time_bin, day_type) cell:
  - Computes Jensen-Shannon divergence between recent (14d) and baseline
    (56d excluding recent) room-visit distributions.
  - Computes 7d vs 30d accuracy drop from prediction_results (D7).
  - Emits AnomalyEvent via database.save_anomaly_event() after 2 consecutive
    runs above threshold (persistence guard suppresses single-day excursions).

No raw SQL INSERT in this module — all writes go through DAO methods.
All reads use database._db_read() for WAL-concurrent access.
"""

from __future__ import annotations

import logging
import math
from typing import Any

_LOGGER = logging.getLogger(__name__)

# JS divergence magnitude thresholds (base-2 logarithm; range 0–1)
_JS_STABLE = 0.3      # below this: no event
_JS_INFO = 0.5        # [0.3, 0.5): INFO
_JS_WARNING = 0.7     # [0.5, 0.7): WARNING
# >= _JS_WARNING: CRITICAL

# Min observations per window for any event; stricter floor for CRITICAL
_MIN_OBS = 10
_MIN_OBS_CRITICAL = 20

# Accuracy-drop threshold (fractional, 30 percentage-point drop = 0.30)
_ACCURACY_DROP_THRESHOLD = 0.30
_MIN_PREDICTIONS = 5

# Persistence guard — emit only after this many consecutive runs above threshold
_CONSECUTIVE_REQUIRED = 2


def _js_divergence(p_dist: dict[str, float], q_dist: dict[str, float]) -> float:
    """Compute Jensen-Shannon divergence JS(P, Q) using log base 2.

    Returns a value in [0, 1]. Returns 0.0 if either distribution is empty.
    Both dicts map room_id → count (raw counts, not normalised fractions).
    Normalisation happens internally.
    """
    p_total = sum(p_dist.values())
    q_total = sum(q_dist.values())
    if p_total == 0 or q_total == 0:
        return 0.0

    rooms = set(p_dist) | set(q_dist)
    # Normalise
    p = {r: p_dist.get(r, 0) / p_total for r in rooms}
    q = {r: q_dist.get(r, 0) / q_total for r in rooms}
    # M = 0.5*(P+Q)
    m = {r: 0.5 * (p[r] + q[r]) for r in rooms}

    def _kl(a: dict, b: dict) -> float:
        total = 0.0
        for r in rooms:
            a_r = a[r]
            b_r = b[r]
            if a_r > 0 and b_r > 0:
                total += a_r * math.log2(a_r / b_r)
        return total

    js = 0.5 * _kl(p, m) + 0.5 * _kl(q, m)
    # Clamp floating-point noise to [0, 1]
    return min(1.0, max(0.0, js))


def _magnitude_bucket(js: float) -> str | None:
    """Map JS divergence to severity bucket string, or None if below threshold."""
    if js < _JS_STABLE:
        return None
    if js < _JS_INFO:
        return "INFO"
    if js < _JS_WARNING:
        return "WARNING"
    return "CRITICAL"


class RegimeDetector:
    """Nightly batch detector for Bayesian routine regime shifts.

    Injected dependencies (no global imports at module level to satisfy
    Bug Class #34 and avoid circular loads):
      - hass: HomeAssistant
      - database: UniversalRoomDatabase (provides _db_read(), DAO methods)
      - bayesian_predictor: BayesianPredictor (provides _known_persons etc.)
    """

    def __init__(self, hass: Any, database: Any, bayesian_predictor: Any, entry: Any = None) -> None:
        self._hass = hass
        self._database = database
        self._bayesian = bayesian_predictor
        # entry is the CM ConfigEntry; used to read live window-days tunables
        # (D6 Number entities). None-safe: falls back to module constants.
        self._entry = entry

    def _window_days(self) -> tuple[int, int]:
        """Return (baseline_days, recent_days), respecting D6 tunables.

        v4.6.2 review fix B#3 follow-on: The D6 Number entities
        (`RoutineRegimeBaselineWindowNumber`, `RoutineRegimeRecentWindowNumber`)
        use the URA Mirror Pattern (RestoreEntity-backed `_value`, no write
        back to entry.options). Reading entry.options would only see the
        install-time seed, making the slider dead config. Read the live HA
        entity state instead.

        Fallback order:
          1. number.ura_coordinator_manager_routine_regime_baseline_window_days
          2. number.ura_coordinator_manager_routine_regime_recent_window_days
          3. hardcoded 56 / 14 (academic-default seeds)
        """
        baseline, recent = 56, 14
        try:
            _bs = self._hass.states.get(
                "number.ura_coordinator_manager_routine_regime_baseline_window_days"
            )
            if _bs is not None and _bs.state not in ("unknown", "unavailable", None):
                baseline = int(float(_bs.state))
            _rs = self._hass.states.get(
                "number.ura_coordinator_manager_routine_regime_recent_window_days"
            )
            if _rs is not None and _rs.state not in ("unknown", "unavailable", None):
                recent = int(float(_rs.state))
        except Exception:
            pass
        return baseline, recent

    async def run_nightly(self) -> dict:
        """Entry point called from nightly maintenance scheduler.

        Returns summary dict: {cells_evaluated, events_emitted, persons_evaluated}.
        """
        cells_evaluated = 0
        events_emitted = 0

        try:
            known_persons: set[str] = self._bayesian.known_persons
        except Exception as e:
            _LOGGER.warning("RegimeDetector: could not read known_persons: %s", e, exc_info=True)
            return {"cells_evaluated": 0, "events_emitted": 0, "persons_evaluated": 0}

        _LOGGER.info(
            "RegimeDetector: starting nightly run for %d persons", len(known_persons)
        )

        for person_id in known_persons:
            for time_bin in range(6):       # 6 time bins
                for day_type in range(2):   # 0=weekday, 1=weekend
                    cells_evaluated += 1
                    try:
                        emitted = await self._evaluate_cell(person_id, time_bin, day_type)
                        if emitted:
                            events_emitted += 1
                    except Exception as e:
                        _LOGGER.warning(
                            "RegimeDetector: cell (%s,%d,%d) failed: %s",
                            person_id, time_bin, day_type, e,
                            exc_info=True,
                        )

        _LOGGER.info(
            "RegimeDetector: nightly run complete — cells=%d, events=%d, persons=%d",
            cells_evaluated, events_emitted, len(known_persons),
        )
        return {
            "cells_evaluated": cells_evaluated,
            "events_emitted": events_emitted,
            "persons_evaluated": len(known_persons),
        }

    async def _evaluate_cell(
        self, person_id: str, time_bin: int, day_type: int
    ) -> bool:
        """Evaluate one cell for regime shift; return True if an event was emitted."""
        # Read JS divergence data
        js_data = await self._compute_cell_divergence(person_id, time_bin, day_type)
        # Read accuracy drop data (D7)
        acc_data = await self._compute_cell_accuracy_drop(person_id, time_bin, day_type)

        # Determine severity from each signal
        js_bucket: str | None = js_data.get("magnitude_bucket") if js_data else None
        acc_bucket: str | None = acc_data.get("magnitude_bucket") if acc_data else None

        # Combined bucket = max severity of the two signals
        severity_rank = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
        combined_bucket: str | None = None
        if js_bucket and acc_bucket:
            combined_bucket = (
                js_bucket if severity_rank[js_bucket] >= severity_rank[acc_bucket]
                else acc_bucket
            )
            source = "combined"
        elif js_bucket:
            combined_bucket = js_bucket
            source = "js_divergence"
        elif acc_bucket:
            combined_bucket = acc_bucket
            source = "accuracy_drop"
        else:
            # No signal above threshold — reset consecutive counter
            await self._persist_state(person_id, time_bin, day_type, "stable")
            return False

        # Vacation-cell skip (geofence-away proxy).
        # v4.6.2 review fix A#4: use the configured recent-window setting
        # so the vacation check tracks whatever the user picked in the D6
        # `RoutineRegimeRecentWindowNumber` advanced tunable.
        _baseline_days, recent_days = self._window_days()
        if await self._is_vacation_cell(person_id, time_bin, day_type, recent_days):
            _LOGGER.debug(
                "RegimeDetector: vacation-cell skip (%s, tb=%d, dt=%d)",
                person_id, time_bin, day_type,
            )
            # v4.6.2 review fix A#3: reset consecutive counter on vacation
            # skip so the persistence guard isn't bypassed when the person
            # returns. Without this, a cell that was at counter=1 before
            # the vacation would emit on the FIRST above-threshold run
            # after return instead of requiring two consecutive runs.
            await self._persist_state(person_id, time_bin, day_type, "stable")
            return False

        # Increment consecutive counter and check persistence guard
        new_counter = await self._persist_state(person_id, time_bin, day_type, combined_bucket)
        if new_counter < _CONSECUTIVE_REQUIRED:
            _LOGGER.debug(
                "RegimeDetector: persistence guard (%s, tb=%d, dt=%d) counter=%d < %d",
                person_id, time_bin, day_type, new_counter, _CONSECUTIVE_REQUIRED,
            )
            return False

        await self._emit_regime_event(
            person_id, time_bin, day_type,
            js_data=js_data,
            acc_data=acc_data,
            combined_bucket=combined_bucket,
            source=source,
        )
        return True

    async def _compute_cell_divergence(
        self, person_id: str, time_bin: int, day_type: int
    ) -> dict | None:
        """Compute JS divergence between recent (14d) and baseline (56d) windows.

        Reads person_visits, derives time_bin/day_type from entry_time via
        SQLite strftime. Returns dict or None if insufficient observations.
        """
        # Time bin hour boundaries (same mapping as _hour_to_time_bin)
        _TB_HOURS = {
            0: (0, 5),
            1: (6, 8),
            2: (9, 11),
            3: (12, 16),
            4: (17, 20),
            5: (21, 23),
        }
        hour_min, hour_max = _TB_HOURS.get(time_bin, (0, 23))

        if day_type == 0:
            dow_clause = "CAST(strftime('%w', entry_time) AS INTEGER) BETWEEN 1 AND 5"
        else:
            dow_clause = "CAST(strftime('%w', entry_time) AS INTEGER) IN (0, 6)"

        try:
            from datetime import timedelta as _td
            from homeassistant.util import dt as _dt_util  # function-local — Bug Class #34
            baseline_days, recent_days = self._window_days()
            now = _dt_util.utcnow()
            recent_cutoff = (now - _td(days=recent_days)).isoformat()
            baseline_cutoff = (now - _td(days=baseline_days + recent_days)).isoformat()

            async with self._database._db_read() as db:
                # Recent window: last 14 days
                cursor = await db.execute(
                    f"""SELECT room_id, COUNT(*) as cnt
                        FROM person_visits
                        WHERE person_id = ?
                          AND entry_time >= ?
                          AND CAST(strftime('%H', entry_time) AS INTEGER) BETWEEN ? AND ?
                          AND {dow_clause}
                        GROUP BY room_id""",
                    (person_id, recent_cutoff, hour_min, hour_max),
                )
                p_rows = await cursor.fetchall()

                # Baseline window: 14–70 days ago (56d window excluding recent)
                cursor = await db.execute(
                    f"""SELECT room_id, COUNT(*) as cnt
                        FROM person_visits
                        WHERE person_id = ?
                          AND entry_time >= ?
                          AND entry_time < ?
                          AND CAST(strftime('%H', entry_time) AS INTEGER) BETWEEN ? AND ?
                          AND {dow_clause}
                        GROUP BY room_id""",
                    (person_id, baseline_cutoff, recent_cutoff, hour_min, hour_max),
                )
                q_rows = await cursor.fetchall()

            p_dist = {row[0]: row[1] for row in p_rows}
            q_dist = {row[0]: row[1] for row in q_rows}
            p_total = sum(p_dist.values())
            q_total = sum(q_dist.values())

            # Min observations floor
            if p_total < _MIN_OBS or q_total < _MIN_OBS:
                return None

            js = _js_divergence(p_dist, q_dist)
            bucket = _magnitude_bucket(js)

            # CRITICAL requires stricter floor
            if bucket == "CRITICAL" and (p_total < _MIN_OBS_CRITICAL or q_total < _MIN_OBS_CRITICAL):
                bucket = "WARNING"  # Downgrade rather than suppress

            # Top movers: rooms with largest P-Q probability difference
            p_norm = {r: p_dist.get(r, 0) / p_total for r in set(p_dist) | set(q_dist)}
            q_norm = {r: q_dist.get(r, 0) / q_total for r in set(p_dist) | set(q_dist)}
            top_movers = sorted(
                [
                    {"room": r, "p_share": round(p_norm[r], 4), "q_share": round(q_norm[r], 4)}
                    for r in p_norm
                ],
                key=lambda x: abs(x["p_share"] - x["q_share"]),
                reverse=True,
            )[:3]

            return {
                "js": round(js, 4),
                "magnitude_bucket": bucket,
                "top_movers": top_movers,
                "p_total_obs": p_total,
                "q_total_obs": q_total,
            }
        except Exception as e:
            _LOGGER.warning(
                "RegimeDetector: _compute_cell_divergence failed (%s, tb=%d, dt=%d): %s",
                person_id, time_bin, day_type, e,
                exc_info=True,
            )
            return None

    async def _compute_cell_accuracy_drop(
        self, person_id: str, time_bin: int, day_type: int
    ) -> dict | None:
        """D7: Compute accuracy drop in prediction_results for this cell.

        Reads prediction_results WHERE prediction_type='next_room' for this
        person. Computes top-1 hit rate for recent 7d vs baseline 30d
        (excluding the recent 7d window). Returns dict or None.
        """
        _TB_HOURS = {
            0: (0, 5),
            1: (6, 8),
            2: (9, 11),
            3: (12, 16),
            4: (17, 20),
            5: (21, 23),
        }
        hour_min, hour_max = _TB_HOURS.get(time_bin, (0, 23))

        if day_type == 0:
            dow_clause = "CAST(strftime('%w', prediction_timestamp) AS INTEGER) BETWEEN 1 AND 5"
        else:
            dow_clause = "CAST(strftime('%w', prediction_timestamp) AS INTEGER) IN (0, 6)"

        try:
            from datetime import timedelta as _td
            from homeassistant.util import dt as _dt_util  # function-local — Bug Class #34
            now = _dt_util.utcnow()
            recent_cutoff = (now - _td(days=7)).isoformat()
            baseline_cutoff = (now - _td(days=30 + 7)).isoformat()

            async with self._database._db_read() as db:
                # Recent 7d: count total predictions and top-1 hits
                cursor = await db.execute(
                    f"""SELECT
                            COUNT(*) as total,
                            SUM(CASE WHEN predicted_value = actual_value
                                     AND actual_value IS NOT NULL THEN 1 ELSE 0 END) as hits
                        FROM prediction_results
                        WHERE prediction_type = 'next_room'
                          AND person_id = ?
                          AND prediction_timestamp >= ?
                          AND CAST(strftime('%H', prediction_timestamp) AS INTEGER)
                              BETWEEN ? AND ?
                          AND {dow_clause}""",
                    (person_id, recent_cutoff, hour_min, hour_max),
                )
                recent_row = await cursor.fetchone()

                # Baseline 30d (excluding recent 7d)
                cursor = await db.execute(
                    f"""SELECT
                            COUNT(*) as total,
                            SUM(CASE WHEN predicted_value = actual_value
                                     AND actual_value IS NOT NULL THEN 1 ELSE 0 END) as hits
                        FROM prediction_results
                        WHERE prediction_type = 'next_room'
                          AND person_id = ?
                          AND prediction_timestamp >= ?
                          AND prediction_timestamp < ?
                          AND CAST(strftime('%H', prediction_timestamp) AS INTEGER)
                              BETWEEN ? AND ?
                          AND {dow_clause}""",
                    (person_id, baseline_cutoff, recent_cutoff, hour_min, hour_max),
                )
                base_row = await cursor.fetchone()

            recent_total = recent_row[0] if recent_row else 0
            recent_hits = recent_row[1] if recent_row and recent_row[1] is not None else 0
            base_total = base_row[0] if base_row else 0
            base_hits = base_row[1] if base_row and base_row[1] is not None else 0

            if recent_total < _MIN_PREDICTIONS or base_total < _MIN_PREDICTIONS:
                return None

            recent_rate = recent_hits / recent_total
            base_rate = base_hits / base_total
            drop = base_rate - recent_rate

            if drop < _ACCURACY_DROP_THRESHOLD:
                return None

            # Map drop magnitude to severity bucket
            if drop >= 0.6:
                bucket = "CRITICAL"
            elif drop >= 0.45:
                bucket = "WARNING"
            else:
                bucket = "INFO"

            return {
                "recent_hit_rate": round(recent_rate, 4),
                "baseline_hit_rate": round(base_rate, 4),
                "drop": round(drop, 4),
                "magnitude_bucket": bucket,
                "recent_total": recent_total,
                "base_total": base_total,
            }
        except Exception as e:
            _LOGGER.warning(
                "RegimeDetector: _compute_cell_accuracy_drop failed (%s, tb=%d, dt=%d): %s",
                person_id, time_bin, day_type, e,
                exc_info=True,
            )
            return None

    async def _is_vacation_cell(
        self, person_id: str, time_bin: int, day_type: int, recent_days: int
    ) -> bool:
        """Return True if the cell has zero visits in the recent window.

        Zero visits in the recent window is used as a proxy for geofence-away
        >50% of the window — typical vacation/extended-absence signal. Uses
        is_cell_stale() which reads via _db_read().
        """
        try:
            from ..bayesian_predictor import is_cell_stale  # function-local — Bug Class #34
            return await is_cell_stale(
                self._database, person_id, time_bin, day_type, recent_days
            )
        except Exception as e:
            _LOGGER.warning(
                "RegimeDetector: _is_vacation_cell failed (%s, tb=%d, dt=%d): %s",
                person_id, time_bin, day_type, e,
                exc_info=True,
            )
            return False

    async def _persist_state(
        self,
        person_id: str,
        time_bin: int,
        day_type: int,
        magnitude_bucket: str | None,
    ) -> int:
        """Increment or reset the consecutive-run counter for a cell.

        When magnitude_bucket is "stable" or None, the counter resets to 0.
        Otherwise it increments from the previous stored value.
        Returns the new counter value (used by caller for persistence guard).
        """
        try:
            existing = await self._database.get_regime_cell_state(
                person_id, time_bin, day_type
            )
            if magnitude_bucket in ("stable", None):
                new_counter = 0
            else:
                old_counter = existing["unacknowledged_consecutive"] if existing else 0
                new_counter = old_counter + 1

            await self._database.upsert_regime_cell_state(
                person_id, time_bin, day_type,
                new_counter,
                magnitude_bucket,
            )
            return new_counter
        except Exception as e:
            _LOGGER.warning(
                "RegimeDetector: _persist_state failed (%s, tb=%d, dt=%d): %s",
                person_id, time_bin, day_type, e,
                exc_info=True,
            )
            return 0

    async def _emit_regime_event(
        self,
        person_id: str,
        time_bin: int,
        day_type: int,
        js_data: dict | None,
        acc_data: dict | None,
        combined_bucket: str,
        source: str,
    ) -> None:
        """Build and persist an AnomalyEvent for a confirmed regime shift."""
        # function-local imports — Bug Class #34
        from ..domain_coordinators.anomaly_event import AnomalyEvent, AnomalySeverity
        from homeassistant.util import dt as _dt_util

        severity_map = {
            "INFO": AnomalySeverity.INFO,
            "WARNING": AnomalySeverity.WARNING,
            "CRITICAL": AnomalySeverity.CRITICAL,
        }
        severity = severity_map.get(combined_bucket, AnomalySeverity.WARNING)

        payload: dict[str, Any] = {
            "cell": {"person_id": person_id, "time_bin": time_bin, "day_type": day_type},
            "magnitude": combined_bucket,
            "source": source,
        }
        if js_data:
            payload.update({
                "js": js_data.get("js"),
                "top_movers": js_data.get("top_movers"),
                "p_total": js_data.get("p_total_obs"),
                "q_total": js_data.get("q_total_obs"),
            })
        if acc_data:
            payload.update({
                "accuracy_recent_hit_rate": acc_data.get("recent_hit_rate"),
                "accuracy_baseline_hit_rate": acc_data.get("baseline_hit_rate"),
                "accuracy_drop": acc_data.get("drop"),
            })

        event = AnomalyEvent(
            coordinator="bayesian",
            type="bayesian.routine_shift",
            severity=severity,
            event_class="regime_shift",
            detected_at=_dt_util.utcnow().isoformat(),
            payload=payload,
            person_id=person_id,
        )

        try:
            row_id = await self._database.save_anomaly_event(event)
            # v4.6.2 review fix B#4: save_anomaly_event swallows errors and
            # returns None on failure. Don't dispatch downstream signals if
            # the row never landed — phantom emit would cause D5 sensors to
            # refresh against a row that doesn't exist and (worse) NM weekly
            # digest to enqueue against a non-existent anomaly_log row.
            if row_id is None:
                _LOGGER.warning(
                    "RegimeDetector: save_anomaly_event returned None for "
                    "(person=%s, tb=%d, dt=%d) — signals NOT dispatched",
                    person_id, time_bin, day_type,
                )
                return
            _LOGGER.info(
                "RegimeDetector: regime_shift emitted (person=%s, tb=%d, dt=%d, "
                "severity=%s, source=%s, row_id=%s)",
                person_id, time_bin, day_type, combined_bucket, source, row_id,
            )
            # Notify D5 sensors and D6 notification handler — function-local
            # imports to satisfy Bug Class #34 (avoid circular loads).
            from homeassistant.helpers.dispatcher import async_dispatcher_send
            from ..domain_coordinators.signals import (
                SIGNAL_REGIME_EVENT_EMITTED,
                SIGNAL_ROUTINE_STATUS_UPDATE,
            )
            async_dispatcher_send(self._hass, SIGNAL_ROUTINE_STATUS_UPDATE)
            async_dispatcher_send(
                self._hass,
                SIGNAL_REGIME_EVENT_EMITTED,
                {
                    # v4.6.2 review fix B#1/A#2: thread the row_id so NM's
                    # weekly digest can persist a valid FK reference into
                    # regime_weekly_digest_queue.anomaly_log_id (otherwise
                    # latent FK violation if/when foreign_keys=ON).
                    "anomaly_log_id": row_id,
                    "person_id": person_id,
                    "severity": int(severity),
                    "time_bin": time_bin,
                    "day_type": day_type,
                },
            )
        except Exception as e:
            _LOGGER.warning(
                "RegimeDetector: _emit_regime_event failed (%s, tb=%d, dt=%d): %s",
                person_id, time_bin, day_type, e,
                exc_info=True,
            )
