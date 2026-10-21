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

    # -- build ---------------------------------------------------------------

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
        """Rebuild from DAO rows; swap only on success.

        ``rows``: ``(entry_id, utc_hour_bucket, occupied_sum, n)``.
        ``visit_rows``: ``(person_id, room_name, entry_local, exit_local)``.
        On any exception the previous model stays and ``status`` becomes
        ``refresh_failed``. Returns True on success.
        """
        try:
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
            people = self._build_people(visit_rows, max_visit_s)
        except Exception as exc:  # noqa: BLE001 — coherent-old on any error
            self.mark_failed(f"{type(exc).__name__}: {exc}")
            return False
        self._cells = cells
        self._days = days
        self._people = people
        self.status = STATUS_OK
        self.last_refresh_utc = now_utc
        self.last_error = None
        self.window_days = window_days
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
            if start.tzinfo is not None:
                start = start.replace(tzinfo=None)
            if end.tzinfo is not None:
                end = end.replace(tzinfo=None)
            if end <= start or (end - start).total_seconds() > max_visit_s:
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
        self._stopped = False

    def async_start(self) -> None:
        """Schedule the initial and nightly refresh (no-op when disabled)."""
        from homeassistant.helpers.event import (
            async_call_later,
            async_track_time_change,
        )

        from .const import (
            OCC_ANOMALY_DWELL_ENABLED,
            OCC_ANOMALY_REFRESH_LOCAL_TIME,
            OCC_ANOMALY_SETUP_REFRESH_DELAY_S,
        )

        if not OCC_ANOMALY_DWELL_ENABLED:
            self.model.status = STATUS_DISABLED
            return
        hh, mm = (int(x) for x in OCC_ANOMALY_REFRESH_LOCAL_TIME.split(":"))

        async def _nightly(_now) -> None:
            await self.async_refresh()

        async def _initial(_now) -> None:
            self._unsub_initial = None
            await self.async_refresh()

        self._unsub_nightly = async_track_time_change(
            self.hass, _nightly, hour=hh, minute=mm, second=0,
        )
        self._unsub_initial = async_call_later(
            self.hass, OCC_ANOMALY_SETUP_REFRESH_DELAY_S, _initial,
        )

    async def async_stop(self) -> None:
        """Cancel timers and drop the hass.data reference (if it is us)."""
        from .const import DOMAIN

        self._stopped = True
        for attr in ("_unsub_nightly", "_unsub_initial"):
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
        if self._stopped:
            return False
        ok = self.model.refresh(
            rows, tz, now_utc=dt_util.utcnow(), window_days=days,
            visit_rows=visits, max_visit_s=OCC_ANOMALY_USUAL_PEOPLE_MAX_VISIT_S,
        )
        if ok:
            _LOGGER.info(
                "Room dwell model refreshed: %d rooms, window %d days",
                len(self.model._cells), days,
            )
        return ok


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
