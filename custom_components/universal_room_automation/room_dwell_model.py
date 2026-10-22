"""Room dwell model: share of time a room is occupied, by local hour x day type.

BAYES-OCCUPANCY-ANOMALY-NEVER-EVALUATES-1 (plan
``docs/planning/PLANNING_occupancy_anomaly_dwell_model.md`` D1).

Producer: every room coordinator writes a 5-minute ``environmental_data``
sample of ``occupied`` (``coordinator.py`` data-logging block), kept 365 days.
Averaging those samples by room, local hour (0-23) and day type (weekday /
weekend) gives "what share of the time is this room usually occupied at this
hour". That is DWELL, not arrivals (the old Bayesian anomaly score was
arrival-shaped and scored Study A, a long-dwell room, 0.004).

This is a general room-level component: no anomaly logic lives here, so the
forecast sensors can switch to it later without a rebuild.

Lifecycle (``RoomDwellModelRunner``): one instance per install in
``hass.data[DOMAIN]["room_dwell_model"]``, created by the INTEGRATION entry
setup and stopped through ``entry.async_on_unload``. It rebuilds once
``OCC_ANOMALY_SETUP_REFRESH_DELAY_S`` after setup and nightly at
``OCC_ANOMALY_REFRESH_LOCAL_TIME`` from one bounded GROUP BY read (plus one
bounded ``person_visits`` read for the display-only ``usual_people``). It
writes nothing. A failed refresh keeps the previous model (coherent-old).

Bug-class guards: #19/#50 (each unsub on its own attribute, cancelled in
``async_stop``); write-flood (read-only); DST (each UTC hour bucket is
converted to local time individually, never with a fixed offset).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Iterable

_LOGGER = logging.getLogger(__name__)

HASS_DATA_KEY = "room_dwell_model"

DAY_TYPE_WEEKDAY = "weekday"
DAY_TYPE_WEEKEND = "weekend"

STATUS_NEVER_REFRESHED = "never_refreshed"
STATUS_OK = "ok"
STATUS_REFRESH_FAILED = "refresh_failed"
STATUS_DISABLED = "disabled"

# Seconds of dwell one environmental_data sample stands for (writer cadence
# 300 s, coordinator.py data-logging block). Display arithmetic only.
SAMPLE_SECONDS = 300

Cell = tuple[int, str]


def day_type_of(local_dt: datetime) -> str:
    """Mon-Fri -> weekday, Sat-Sun -> weekend."""
    return DAY_TYPE_WEEKEND if local_dt.weekday() >= 5 else DAY_TYPE_WEEKDAY


def cell_of(local_dt: datetime) -> Cell:
    """The (local hour, day type) cell of a local datetime."""
    return (local_dt.hour, day_type_of(local_dt))


def cell_label(cell: Cell) -> str:
    """Human label, e.g. ``"weekday 03:00"``."""
    return f"{cell[1]} {cell[0]:02d}:00"


def _parse_utc_hour_bucket(bucket: str) -> datetime:
    """``YYYY-MM-DDTHH`` (naive UTC) -> aware UTC datetime."""
    return datetime.strptime(bucket[:13], "%Y-%m-%dT%H").replace(
        tzinfo=timezone.utc,
    )


def _ranges(hours: list[int]) -> str:
    """[8, 9, 10, 14] -> ``"08-10, 14"``."""
    if not hours:
        return ""
    out: list[str] = []
    start = prev = hours[0]
    for h in hours[1:]:
        if h == prev + 1:
            prev = h
            continue
        out.append(f"{start:02d}" if start == prev else f"{start:02d}-{prev:02d}")
        start = prev = h
    out.append(f"{start:02d}" if start == prev else f"{start:02d}-{prev:02d}")
    return ", ".join(out)


class RoomDwellModel:
    """In-memory share-by-cell model. Pure: no HA imports."""

    def __init__(self) -> None:
        # {entry_id: {cell: [occupied_sum, n]}}
        self._cells: dict[str, dict[Cell, list[int]]] = {}
        # {entry_id: {cell: distinct local dates with samples}}
        self._days: dict[str, dict[Cell, int]] = {}
        # {room_name: {cell: {person_id: seconds}}}
        self._people: dict[str, dict[Cell, dict[str, float]]] = {}
        self.status: str = STATUS_NEVER_REFRESHED
        self.last_refresh_utc: datetime | None = None
        self.last_error: str | None = None
        self.window_days: int | None = None
        # Aware UTC end of the training window (start of the refresh's local
        # day). The dwell_share producer only freezes an hour H when this is
        # <= start(H), so a scored prediction is always out of sample (I1).
        self.trained_until_utc: datetime | None = None

    # -- build ---------------------------------------------------------------

    @staticmethod
    def build(
        rows: Iterable[tuple[str, str, int, int]],
        tz: tzinfo,
        visit_rows: Iterable[tuple[str, str, str, str]] = (),
        max_visit_s: float = 86400.0,
    ) -> tuple[dict, dict, dict]:
        """Pure, CPU-bound parse (runs in the executor). Raises on bad rows.

        ``rows``: ``(entry_id, utc_hour_bucket, occupied_sum, n)``.
        ``visit_rows``: ``(person_id, room_name, entry_local, exit_local)``.
        Returns ``(cells, days, people)`` for ``apply``.
        """
        cells: dict[str, dict[Cell, list[int]]] = {}
        dates: dict[str, dict[Cell, set]] = {}
        for entry_id, bucket, occ_sum, n in rows:
            if not n:
                continue
            local = _parse_utc_hour_bucket(bucket).astimezone(tz)
            c = cell_of(local)
            slot = cells.setdefault(entry_id, {}).setdefault(c, [0, 0])
            slot[0] += int(occ_sum)
            slot[1] += int(n)
            dates.setdefault(entry_id, {}).setdefault(c, set()).add(
                local.date(),
            )
        days = {
            e: {c: len(ds) for c, ds in per.items()}
            for e, per in dates.items()
        }
        people = RoomDwellModel._build_people(visit_rows, max_visit_s)
        return cells, days, people

    def apply(
        self, built: tuple[dict, dict, dict], *, now_utc: datetime,
        window_days: int, trained_until_utc: datetime | None = None,
    ) -> None:
        """Swap in a built model (on the event loop)."""
        self._cells, self._days, self._people = built
        self.status = STATUS_OK
        self.last_refresh_utc = now_utc
        self.last_error = None
        self.window_days = window_days
        self.trained_until_utc = trained_until_utc

    def refresh(
        self,
        rows: Iterable[tuple[str, str, int, int]],
        tz: tzinfo,
        *,
        now_utc: datetime,
        window_days: int,
        visit_rows: Iterable[tuple[str, str, str, str]] = (),
        max_visit_s: float = 86400.0,
    ) -> bool:
        """``build`` + ``apply`` in one call; the previous model stays and
        ``status`` becomes ``refresh_failed`` on any build error."""
        try:
            built = self.build(rows, tz, visit_rows, max_visit_s)
        except Exception as exc:  # noqa: BLE001 — coherent-old on any error
            self.mark_failed(f"{type(exc).__name__}: {exc}")
            return False
        self.apply(built, now_utc=now_utc, window_days=window_days)
        return True

    @staticmethod
    def _build_people(
        visit_rows: Iterable[tuple[str, str, str, str]], max_visit_s: float,
    ) -> dict[str, dict[Cell, dict[str, float]]]:
        people: dict[str, dict[Cell, dict[str, float]]] = {}
        for person_id, room_name, entry_raw, exit_raw in visit_rows:
            try:
                start = datetime.fromisoformat(str(entry_raw))
                end = datetime.fromisoformat(str(exit_raw))
            except ValueError:
                continue
            try:
                long_visit = (end - start).total_seconds() > max_visit_s
                backwards = end <= start
            except TypeError:  # mixed naive/aware row: skip, don't fail
                continue
            if backwards or long_visit:
                continue
            cur = start
            while cur < end:
                nxt = min(
                    end,
                    cur.replace(minute=0, second=0, microsecond=0)
                    + timedelta(hours=1),
                )
                bucket = people.setdefault(room_name, {}).setdefault(
                    cell_of(cur), {},
                )
                bucket[person_id] = bucket.get(person_id, 0.0) + (
                    nxt - cur
                ).total_seconds()
                cur = nxt
        return people

    def mark_failed(self, reason: str) -> None:
        """Keep the previous model; record the failure."""
        self.status = STATUS_REFRESH_FAILED
        self.last_error = reason

    # -- read ----------------------------------------------------------------

    @property
    def has_model(self) -> bool:
        """True once at least one refresh has succeeded."""
        return self.last_refresh_utc is not None

    def lookup(self, entry_id: str, local_dt: datetime) -> tuple[float | None, int]:
        """``(share, n)`` for the room's cell at ``local_dt``; ``(None, 0)``
        when the cell has no samples."""
        slot = self._cells.get(entry_id, {}).get(cell_of(local_dt))
        if not slot or not slot[1]:
            return None, 0
        return slot[0] / slot[1], slot[1]

    def cell_days(self, entry_id: str, local_dt: datetime) -> int:
        """Distinct local dates that contributed samples to this cell."""
        return int(self._days.get(entry_id, {}).get(cell_of(local_dt), 0))

    def occupied_samples(self, entry_id: str, local_dt: datetime) -> int:
        slot = self._cells.get(entry_id, {}).get(cell_of(local_dt))
        return int(slot[0]) if slot else 0

    def usual_hours(self, entry_id: str, threshold: float) -> str:
        """Hours where the share is at or above ``threshold``, as text."""
        room = self._cells.get(entry_id, {})
        parts: list[str] = []
        for dt_name, label in (
            (DAY_TYPE_WEEKDAY, "weekdays"), (DAY_TYPE_WEEKEND, "weekends"),
        ):
            hours = sorted(
                h for (h, d), (occ, n) in room.items()
                if d == dt_name and n and occ / n >= threshold
            )
            if hours:
                parts.append(f"{label} {_ranges(hours)}")
        return "; ".join(parts) if parts else "none"

    # -- forecast helpers (PREDICT-MODEL-DWELL-MIGRATION-1 D1) ---------------

    def forecast(
        self,
        entry_id: str,
        now: datetime,
        horizon_h: float,
        last_hour_fraction: float | None,
        weight: float,
    ) -> float | None:
        """``w x last_hour_fraction + (1 - w) x share(cell of now + h)``.

        ``now`` must be aware. The target is computed in UTC and converted
        back to ``now``'s zone, so a horizon across a DST change lands on
        the right local hour. Returns the cell share alone when
        ``last_hour_fraction`` is None, and None when the target cell has no
        samples. Pure.
        """
        target = (
            now.astimezone(timezone.utc) + timedelta(hours=horizon_h)
        ).astimezone(now.tzinfo)
        share, _n = self.lookup(entry_id, target)
        if share is None:
            return None
        if last_hour_fraction is None:
            return share
        w = float(weight)
        return w * float(last_hour_fraction) + (1.0 - w) * share

    def _ranked_cells(self, entry_id: str) -> list[tuple[Cell, float]]:
        room = self._cells.get(entry_id, {})
        ranked = [(c, occ / n) for c, (occ, n) in room.items() if n]
        # Highest share first; ties broken by (day type, hour) so the order
        # is deterministic.
        ranked.sort(key=lambda cs: (-cs[1], cs[0][1], cs[0][0]))
        return ranked

    def peak_cell(self, entry_id: str) -> tuple[Cell, float] | None:
        """The room's highest-share cell, or None without samples."""
        ranked = self._ranked_cells(entry_id)
        return ranked[0] if ranked else None

    def top_cells(self, entry_id: str, k: int) -> list[tuple[Cell, float]]:
        """The ``k`` highest-share cells (``k <= 0`` -> empty)."""
        if k <= 0:
            return []
        return self._ranked_cells(entry_id)[:k]

    def usual_people(
        self, room_name: str, entry_id: str, local_dt: datetime, top: int = 3,
    ) -> list[dict[str, Any]]:
        """Top people by BLE visit time in this cell, with their share of the
        cell's occupied time (capped at 1.0). Display only."""
        cell = cell_of(local_dt)
        per = self._people.get(room_name, {}).get(cell, {})
        if not per:
            return []
        occ_s = self.occupied_samples(entry_id, local_dt) * SAMPLE_SECONDS
        ranked = sorted(per.items(), key=lambda kv: kv[1], reverse=True)[:top]
        return [
            {
                "person": person,
                "share": round(min(1.0, secs / occ_s), 3) if occ_s else None,
            }
            for person, secs in ranked
        ]


def training_window(
    now_local: datetime, window_days: int,
) -> tuple[datetime, datetime]:
    """``[start, end)`` as aware datetimes: ``window_days`` whole local days
    ending at the start of today (today is excluded so the episode being
    judged never trains the model)."""
    end = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=window_days)
    return start, end


def _effective_window_days() -> int:
    from .const import OCC_ANOMALY_WINDOW_DAYS, RETENTION_ROOM_HISTORY_DAYS

    days = int(OCC_ANOMALY_WINDOW_DAYS)
    if RETENTION_ROOM_HISTORY_DAYS and RETENTION_ROOM_HISTORY_DAYS > 0:
        days = min(days, int(RETENTION_ROOM_HISTORY_DAYS))
    return max(1, days)


class RoomDwellModelRunner:
    """Owns the model and its refresh schedule (HA side)."""

    def __init__(self, hass) -> None:
        self.hass = hass
        self.model = RoomDwellModel()
        self._unsub_nightly = None
        self._unsub_initial = None
        self._unsub_retry = None
        self._stopped = False
        # dwell_share producer (PREDICT-MODEL-DWELL-MIGRATION-1 D3). All in
        # memory: a restart loses at most the current and previous hour.
        self._unsub_dwell_tick = None
        # {aware UTC hour start: {entry_id: (share, cell_n)}}
        self._frozen: dict[datetime, dict[str, tuple[float, int]]] = {}
        self._last_scored_utc_hour: datetime | None = None
        # Occupied fraction of the last scored hour, per room (D2 blend).
        self._last_hour_fraction: dict[str, float] = {}
        self.skipped_freeze = 0

    def async_start(self) -> None:
        """Schedule the initial and nightly refresh (no-op when disabled)."""
        from homeassistant.helpers.event import (
            async_call_later,
            async_track_time_change,
        )

        from .const import (
            OCC_ANOMALY_DWELL_ENABLED,
            OCC_ANOMALY_REFRESH_LOCAL_TIME,
            OCC_ANOMALY_RETRY_DELAY_S,
            OCC_ANOMALY_SETUP_REFRESH_DELAY_S,
        )

        if not OCC_ANOMALY_DWELL_ENABLED:
            self.model.status = STATUS_DISABLED
            return
        hh, mm = (int(x) for x in OCC_ANOMALY_REFRESH_LOCAL_TIME.split(":"))

        async def _nightly(_now) -> None:
            await self.async_refresh()

        async def _retry(_now) -> None:
            self._unsub_retry = None
            await self.async_refresh()

        async def _initial(_now) -> None:
            self._unsub_initial = None
            ok = await self.async_refresh()
            if not ok and not self._stopped:
                # one retry after a failed / no-database first build
                self._unsub_retry = async_call_later(
                    self.hass, OCC_ANOMALY_RETRY_DELAY_S, _retry,
                )

        self._unsub_nightly = async_track_time_change(
            self.hass, _nightly, hour=hh, minute=mm, second=0,
        )
        self._unsub_initial = async_call_later(
            self.hass, OCC_ANOMALY_SETUP_REFRESH_DELAY_S, _initial,
        )
        self._register_dwell_tick(async_track_time_change)

    def _register_dwell_tick(self, track_time_change) -> None:
        """Hourly dwell_share tick on its own unsub (D3). No-op when the
        producer is switched off."""
        from .const import DWELL_SHARE_PRODUCER_ENABLED, DWELL_SHARE_TICK_MINUTE

        if not DWELL_SHARE_PRODUCER_ENABLED:
            return
        minute = DWELL_SHARE_TICK_MINUTE
        if not isinstance(minute, int) or not 0 <= minute <= 14:
            _LOGGER.warning(
                "DWELL_SHARE_TICK_MINUTE=%r is outside 0-14; using 2", minute,
            )
            minute = 2
        self._unsub_dwell_tick = track_time_change(
            self.hass, self._async_dwell_tick, minute=minute, second=0,
        )

    def last_hour_fraction(self, entry_id: str) -> float | None:
        """Occupied fraction of the last scored hour (None after a restart
        until the producer has scored an hour, and when it is off)."""
        return self._last_hour_fraction.get(entry_id)

    def _room_entry_ids(self) -> list[str]:
        from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_ROOM

        try:
            entries = self.hass.config_entries.async_entries(DOMAIN)
        except Exception:  # noqa: BLE001
            return []
        return [
            e.entry_id for e in entries
            if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM
        ]

    async def _async_dwell_tick(self, _now=None) -> None:
        """Score the finished hour, then freeze the new one. Never raises."""
        if self._stopped:
            return
        try:
            await self._dwell_tick()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("dwell_share producer tick failed: %s", exc)

    async def _dwell_tick(self) -> None:
        from homeassistant.util import dt as dt_util

        from .const import DOMAIN, DWELL_SHARE_MIN_ACTUAL_SAMPLES

        hour = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        prev = hour - timedelta(hours=1)

        # 1. Score H-1 with the share frozen at its start. The frozen entry
        # is dropped whether or not the write succeeds (no retry/backfill),
        # and the same-hour guard is set before any await so a second
        # invocation for the same hour does nothing (I2).
        frozen_prev = self._frozen.pop(prev, None)
        for key in [k for k in self._frozen if k < prev]:
            self._frozen.pop(key, None)
        if frozen_prev is not None and prev != self._last_scored_utc_hour:
            self._last_scored_utc_hour = prev
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db is not None:
                since = prev.replace(tzinfo=None).isoformat()
                until = hour.replace(tzinfo=None).isoformat()
                try:
                    actual_rows = await db.get_room_occupied_share_by_hour(
                        since, until,
                    )
                except Exception:  # noqa: BLE001
                    self._last_hour_fraction = {}
                    raise
                actual: dict[str, tuple[int, int]] = {}
                for entry_id, _bucket, occ, n in actual_rows:
                    o, c = actual.get(entry_id, (0, 0))
                    actual[entry_id] = (o + int(occ), c + int(n))
                min_n = max(1, int(DWELL_SHARE_MIN_ACTUAL_SAMPLES))
                stamp = prev.isoformat()
                rows: list[tuple] = []
                fractions: dict[str, float] = {}
                for entry_id, (share, cell_n) in frozen_prev.items():
                    occ, n = actual.get(entry_id, (0, 0))
                    if n < min_n:
                        continue
                    frac = occ / n
                    fractions[entry_id] = frac
                    rows.append((
                        entry_id, stamp, "dwell_share",
                        str(round(share, 4)), cell_n,
                        str(round(frac, 4)), round(share - frac, 4),
                    ))
                self._last_hour_fraction = fractions
                if rows:
                    await db.save_prediction_results_batch(rows)

        # 2. Freeze H, only from a model trained strictly before H (I1), and
        # only once per hour (the first tick inside H wins).
        if hour in self._frozen:
            return
        model = self.model
        trained = model.trained_until_utc
        if not model.has_model or trained is None or trained > hour:
            self.skipped_freeze += 1
            _LOGGER.debug(
                "dwell_share: no freeze for %s (model=%s trained_until=%s)",
                hour.isoformat(), model.has_model, trained,
            )
            return
        local = hour.astimezone(dt_util.DEFAULT_TIME_ZONE)
        frozen: dict[str, tuple[float, int]] = {}
        for entry_id in self._room_entry_ids():
            share, n = model.lookup(entry_id, local)
            if share is not None:
                frozen[entry_id] = (share, n)
        if frozen:
            self._frozen[hour] = frozen

    async def async_stop(self) -> None:
        """Cancel timers and drop the hass.data reference (if it is us)."""
        from .const import DOMAIN

        self._stopped = True
        for attr in ("_unsub_nightly", "_unsub_initial", "_unsub_retry",
                     "_unsub_dwell_tick"):
            unsub = getattr(self, attr)
            setattr(self, attr, None)
            if unsub is not None:
                try:
                    unsub()
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("room dwell model unsub raised", exc_info=True)
        domain_data = self.hass.data.get(DOMAIN, {})
        if domain_data.get(HASS_DATA_KEY) is self:
            domain_data.pop(HASS_DATA_KEY, None)

    async def async_refresh(self) -> bool:
        """One bounded read, then an atomic swap. Never raises."""
        from homeassistant.util import dt as dt_util

        from .const import (
            DOMAIN,
            OCC_ANOMALY_USUAL_PEOPLE_MAX_VISIT_S,
            OCC_ANOMALY_USUAL_PEOPLE_MAX_VISITS,
        )

        if self._stopped:
            return False
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is None:
            self.model.mark_failed("no_database")
            return False
        days = _effective_window_days()
        tz = dt_util.DEFAULT_TIME_ZONE
        start, end = training_window(dt_util.now(), days)
        since_utc = start.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
        until_utc = end.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
        try:
            rows = await db.get_room_occupied_share_by_hour(since_utc, until_utc)
            try:
                visits = await db.get_closed_person_visits(
                    str(start.replace(tzinfo=None)),
                    str(end.replace(tzinfo=None)),
                    OCC_ANOMALY_USUAL_PEOPLE_MAX_VISITS,
                )
            except Exception:  # noqa: BLE001 — display-only input
                _LOGGER.debug("room dwell model: person_visits read failed",
                              exc_info=True)
                visits = []
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Room dwell model refresh failed (keeping previous): %s", exc)
            self.model.mark_failed(f"{type(exc).__name__}: {exc}")
            return False
        try:
            # CPU-bound parse of ~60k rows + visits off the event loop.
            built = await self.hass.async_add_executor_job(
                RoomDwellModel.build, rows, tz, visits,
                OCC_ANOMALY_USUAL_PEOPLE_MAX_VISIT_S,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Room dwell model build failed (keeping previous): %s", exc)
            self.model.mark_failed(f"{type(exc).__name__}: {exc}")
            return False
        if self._stopped:  # a stop during the read or the build wins
            return False
        self.model.apply(
            built, now_utc=dt_util.utcnow(), window_days=days,
            trained_until_utc=end.astimezone(timezone.utc),
        )
        _LOGGER.info(
            "Room dwell model refreshed: %d rooms, window %d days",
            len(self.model._cells), days,
        )
        return True


async def async_setup_room_dwell_model(hass) -> RoomDwellModelRunner:
    """Create (or replace) the install's runner and start its schedule."""
    from .const import DOMAIN

    domain_data = hass.data.setdefault(DOMAIN, {})
    existing = domain_data.get(HASS_DATA_KEY)
    if existing is not None:
        await existing.async_stop()
    runner = RoomDwellModelRunner(hass)
    domain_data[HASS_DATA_KEY] = runner
    runner.async_start()
    return runner
