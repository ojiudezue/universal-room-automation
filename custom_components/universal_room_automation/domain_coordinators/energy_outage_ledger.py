"""EC-OUTAGE-LEDGER — Stage L of PLANNING_ec_storm_and_blind_decisions.md.

Evidence-only ledger in ``ura_activity_log`` (no decision consumer, by
design):

* ``nws_alert`` (D-L1) — one row per NWS alert message ID seen in the raw
  feed, per boot. Driven from the energy timer decision cycle right after
  ``determine_mode`` returns, so it runs regardless of the decision's early
  returns (grid disconnect, fully blind).
* ``grid_outage`` (D-L2) — the Enphase cloud system-event calendar is the
  PRIMARY witness (``witness="cloud"``, one row per off-grid event,
  deduplicated on event start, including across boots via a DB read).
  Local sensors (``grid_enabled`` switch via ``_grid_outage_active`` and the
  Enpower ``grid_status`` binary sensor) are corroboration only: an
  off-grid transition of the last non-None value writes a
  ``witness="local_only"`` observation row and never opens an episode.
  ``sensor.iq_gateway_hacs_grid_mode`` is deliberately NOT used (P4: 98
  false flips in 7 days).

Every DB write is fire-and-forget through ``hass.async_create_task`` on the
existing ``log_activity`` DAO (same contract as ``_record_reserve_dispatch``).
Nothing here raises into the caller.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from .energy_const import (
    ACTIVITY_LEDGER_IMPORTANCE,
    OUTAGE_CALENDAR_ENTITY_SUFFIX,
    OUTAGE_CALENDAR_GENERATOR_SUBSTR,
    OUTAGE_CALENDAR_OFFGRID_SUBSTR,
    OUTAGE_CALENDAR_ONGRID_SUBSTR,
    OUTAGE_CALENDAR_PLATFORM,
    OUTAGE_DEDUP_TOLERANCE_MIN,
    OUTAGE_LEDGER_MAX_SEEN,
    OUTAGE_SWEEP_INITIAL_DELAY_S,
    OUTAGE_SWEEP_INTERVAL_H,
    OUTAGE_SWEEP_LOOKBACK_H,
    OUTAGE_SWEEP_TIMEOUT_S,
)

_LOGGER = logging.getLogger(__name__)

_DOMAIN = "universal_room_automation"

# Fields copied verbatim from each NWS alert into the nws_alert row.
NWS_ALERT_LEDGER_FIELDS: tuple[str, ...] = (
    "Event", "NWSCode", "Type", "Status", "Severity", "Certainty",
    "Sent", "Onset", "Expires", "Ends", "AreasAffected",
)


def alert_key(alert: dict[str, Any]) -> str | None:
    """Dedup key of one NWS alert message: ``ID``, else ``URL``, else Event|Sent."""
    for k in ("ID", "URL"):
        v = alert.get(k)
        if v:
            return str(v)
    ev, sent = alert.get("Event"), alert.get("Sent")
    if ev or sent:
        return f"{ev}|{sent}"
    return None


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO datetime string (or pass a datetime through); None-safe."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    if isinstance(value, dict):  # {"dateTime": "..."} shape
        value = value.get("dateTime") or value.get("date")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    # Naive values are not comparable with aware ones: treat as UTC.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _alert_end(alert: dict[str, Any]) -> datetime | None:
    return _parse_dt(alert.get("Ends")) or _parse_dt(alert.get("Expires"))


def classify_calendar_summary(summary: Any) -> str | None:
    """Case-folded SUBSTRING classifier: 'offgrid' / 'ongrid' / 'generator' / None.

    Off-grid is tested first. An empty off-grid substring never matches.
    """
    text = str(summary or "").casefold()
    if not text:
        return None
    off = OUTAGE_CALENDAR_OFFGRID_SUBSTR.casefold()
    on = OUTAGE_CALENDAR_ONGRID_SUBSTR.casefold()
    gen = OUTAGE_CALENDAR_GENERATOR_SUBSTR.casefold()
    if off and off in text:
        return "offgrid"
    if on and on in text:
        return "ongrid"
    if gen and gen in text:
        return "generator"
    return None


class OutageLedger:
    """RAM state + writers for the nws_alert / grid_outage ledger."""

    def __init__(self, hass: Any) -> None:
        self.hass = hass
        # alert key -> end datetime (or None). Pruned when the key has left
        # the feed AND its end has passed (or it has no end), so a feed blip
        # (unavailable / empty list) does not re-log the same message.
        self._seen_alerts: dict[str, datetime | None] = {}
        # Per-sensor last NON-None local reading (True = off-grid).
        self._local_last: dict[str, bool] = {}
        # Recent local off-grid observations: (time, sensor).
        self._local_obs: deque[tuple[datetime, str]] = deque(
            maxlen=OUTAGE_LEDGER_MAX_SEEN,
        )
        # Decision snapshots on change: (time, snapshot dict).
        self._decision_hist: deque[tuple[datetime, dict[str, Any]]] = deque(
            maxlen=OUTAGE_LEDGER_MAX_SEEN,
        )
        # Cloud off-grid event starts already written (UTC iso keys).
        self._cloud_seen: set[str] = set()
        self._cloud_seeded = False
        self._unresolved_warned = False
        # Scheduling handles (Bug Class #38: every timer/task is cancelled).
        self._initial_unsub: Any = None
        self._interval_unsub: Any = None
        self._sweep_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # DB write (fire-and-forget)
    # ------------------------------------------------------------------
    def _emit(
        self,
        *,
        action: str,
        timestamp: str,
        description: str,
        payload: dict[str, Any],
        entity_id: str | None,
    ) -> bool:
        try:
            db = self.hass.data.get(_DOMAIN, {}).get("database")
        except Exception:  # noqa: BLE001
            db = None
        if db is None:
            _LOGGER.debug("ledger row skipped (no database) action=%s", action)
            return False
        coro = db.log_activity(
            timestamp=timestamp,
            coordinator="energy",
            action=action,
            room=None,
            zone=None,
            importance=ACTIVITY_LEDGER_IMPORTANCE,
            description=description,
            details_json=json.dumps(payload, default=str),
            entity_id=entity_id,
        )
        if inspect.iscoroutine(coro):
            self.hass.async_create_task(coro)
        return True

    # ------------------------------------------------------------------
    # Per-tick hook (D-L1 + D-L2(ii))
    # ------------------------------------------------------------------
    def record_tick(
        self,
        *,
        now: datetime,
        alerts: Any,
        nws_entity: str | None,
        decision: Any,
        decision_age_s: float | None,
        soc: Any,
        local_readings: dict[str, bool | None],
    ) -> None:
        """Run the per-tick ledger. Never raises."""
        try:
            self._record_alerts(now, alerts, nws_entity, decision_age_s)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("ledger: nws_alert pass failed", exc_info=True)
        snap = self._decision_snapshot(decision, decision_age_s)
        try:
            if not self._decision_hist or self._decision_hist[-1][1].get(
                "key",
            ) != snap.get("key"):
                self._decision_hist.append((now, snap))
        except Exception:  # noqa: BLE001
            pass
        try:
            self._record_local(now, local_readings, snap, alerts, soc)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("ledger: local witness pass failed", exc_info=True)

    @staticmethod
    def _decision_snapshot(decision: Any, age_s: float | None) -> dict[str, Any]:
        if decision is None:
            return {"key": None, "tier": None, "hold_depth": None,
                    "reserve_floor": None, "decision_age_s": age_s}
        tier = getattr(decision, "tier", None)
        depth = getattr(decision, "hold_depth", None)
        floor = getattr(decision, "reserve_floor", None)
        return {
            "key": (tier, depth, floor),
            "tier": tier,
            "hold_depth": depth,
            "reserve_floor": floor,
            "decision_age_s": age_s,
        }

    def _record_alerts(
        self, now: datetime, alerts: Any, nws_entity: str | None,
        decision_age_s: float | None,
    ) -> None:
        if not isinstance(alerts, list):
            return  # unavailable / not configured: no rows, no pruning
        present: set[str] = set()
        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            key = alert_key(alert)
            if key is None:
                continue
            present.add(key)
            if key in self._seen_alerts:
                continue
            payload = {f: alert.get(f) for f in NWS_ALERT_LEDGER_FIELDS}
            payload.update({
                "id": key,
                "ura_class": None,   # Stage B product table not shipped
                "ura_tier": None,
                "local": "unknown",  # Stage B locality not shipped
                "decision_age_s": decision_age_s,
            })
            if self._emit(
                action="nws_alert",
                timestamp=now.isoformat(),
                description=(
                    f"nws_alert {alert.get('Event')} "
                    f"{alert.get('Type')} {alert.get('NWSCode')}"
                ),
                payload=payload,
                entity_id=nws_entity,
            ):
                self._seen_alerts[key] = _alert_end(alert)
        # Prune: left the feed AND (ended or no end known).
        for key in list(self._seen_alerts):
            if key in present:
                continue
            end = self._seen_alerts[key]
            if end is None or end <= now:
                del self._seen_alerts[key]
        # Hard ceiling: drop the oldest-inserted keys not in the feed.
        if len(self._seen_alerts) > OUTAGE_LEDGER_MAX_SEEN:
            for key in list(self._seen_alerts):
                if len(self._seen_alerts) <= OUTAGE_LEDGER_MAX_SEEN:
                    break
                if key not in present:
                    del self._seen_alerts[key]

    def _record_local(
        self, now: datetime, readings: dict[str, bool | None],
        snap: dict[str, Any], alerts: Any, soc: Any,
    ) -> None:
        for sensor, reading in (readings or {}).items():
            if reading is None:
                continue  # None never transitions, never resets the baseline
            prev = self._local_last.get(sensor)
            self._local_last[sensor] = bool(reading)
            # A boot reading (prev None) only sets the baseline: the test
            # below requires a prior non-None False, so it writes nothing.
            if prev is False and reading is True:
                alert_ids = []
                if isinstance(alerts, list):
                    alert_ids = [
                        k for k in (alert_key(a) for a in alerts
                                    if isinstance(a, dict)) if k
                    ]
                payload = {
                    "witness": "local_only",
                    "sensor": sensor,
                    "tier": snap.get("tier"),
                    "hold_depth": snap.get("hold_depth"),
                    "reserve_floor": snap.get("reserve_floor"),
                    "decision_age_s": snap.get("decision_age_s"),
                    "active_alert_ids": alert_ids,
                    "soc": soc,
                }
                self._emit(
                    action="grid_outage",
                    timestamp=now.isoformat(),
                    description=f"grid_outage local_only {sensor} off-grid "
                                f"(observation, not an episode)",
                    payload=payload,
                    entity_id=sensor,
                )
                self._local_obs.append((now, sensor))

    # ------------------------------------------------------------------
    # Cloud sweep (D-L2(i))
    # ------------------------------------------------------------------
    def resolve_calendar(self) -> tuple[str | None, int]:
        """Registry lookup: (entity_id, match_count). entity_id only iff exactly one."""
        if not OUTAGE_CALENDAR_PLATFORM:
            return None, 0
        from homeassistant.helpers import entity_registry as er
        reg = er.async_get(self.hass)
        found = [
            e.entity_id for e in list(reg.entities.values())
            if e.entity_id.startswith("calendar.")
            and e.entity_id.endswith(OUTAGE_CALENDAR_ENTITY_SUFFIX)
            and e.platform == OUTAGE_CALENDAR_PLATFORM
        ]
        return (found[0] if len(found) == 1 else None), len(found)

    async def _fetch_events(
        self, eid: str, start: datetime, end: datetime,
    ) -> list[dict[str, Any]]:
        resp = await asyncio.wait_for(
            self.hass.services.async_call(
                "calendar", "get_events",
                {"entity_id": eid, "start_date_time": start,
                 "end_date_time": end},
                blocking=True, return_response=True,
            ),
            timeout=OUTAGE_SWEEP_TIMEOUT_S,
        )
        body = (resp or {}).get(eid) or {}
        events = body.get("events") or []
        return [e for e in events if isinstance(e, dict)]

    async def _seed_cloud_seen(self, now: datetime) -> None:
        """Cross-boot dedup: load cloud rows already written in the lookback."""
        self._cloud_seeded = True
        try:
            db = self.hass.data.get(_DOMAIN, {}).get("database")
            if db is None or not hasattr(db, "query_activities"):
                return
            since = (now - timedelta(hours=OUTAGE_SWEEP_LOOKBACK_H + 24))
            res = await db.query_activities(
                since=since.isoformat(), coordinator="energy",
                action="grid_outage", limit=1000,
                columns=("details_json",),
            )
            for row in (res or {}).get("rows", []):
                try:
                    d = json.loads(row.get("details_json") or "{}")
                except Exception:  # noqa: BLE001
                    continue
                if d.get("witness") == "cloud" and d.get("event_start_utc"):
                    self._cloud_seen.add(str(d["event_start_utc"]))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("outage sweep: dedup seed failed", exc_info=True)

    async def sweep(self, now: datetime | None = None) -> int:
        """One cloud sweep. Returns rows written. Never raises."""
        try:
            return await self._sweep(now)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001 — incl. TimeoutError
            _LOGGER.warning("outage sweep failed (no rows written): %r", err)
            return 0

    async def _sweep(self, now: datetime | None) -> int:
        if not OUTAGE_CALENDAR_OFFGRID_SUBSTR:
            return 0
        now = now or datetime.now(timezone.utc)
        eid, n = self.resolve_calendar()
        if eid is None:
            if not self._unresolved_warned:
                self._unresolved_warned = True
                _LOGGER.warning(
                    "outage sweep: calendar not resolved (found %d)", n,
                )
            return 0
        st = self.hass.states.get(eid)
        if st is not None and st.state == "unavailable":
            _LOGGER.debug("outage sweep: %s unavailable, skipping", eid)
            return 0
        start = now - timedelta(hours=OUTAGE_SWEEP_LOOKBACK_H)
        events = await self._fetch_events(eid, start, now)
        if not self._cloud_seeded:
            await self._seed_cloud_seen(now)
        parsed: list[tuple[datetime, str, str]] = []
        for ev in events:
            cls = classify_calendar_summary(ev.get("summary"))
            t = _parse_dt(ev.get("start"))
            if cls is None or t is None:
                continue
            parsed.append((t, cls, str(ev.get("summary"))))
        parsed.sort(key=lambda x: x[0])
        offgrid = [p for p in parsed if p[1] == "offgrid"]
        _LOGGER.info(
            "outage sweep: parsed %d events, %d off-grid", len(events),
            len(offgrid),
        )
        tol = timedelta(minutes=OUTAGE_DEDUP_TOLERANCE_MIN)
        written = 0
        for t, _cls, summary in offgrid:
            key = t.astimezone(timezone.utc).isoformat()
            if key in self._cloud_seen:
                continue
            ongrid_at = next(
                (p[0] for p in parsed if p[1] == "ongrid" and p[0] > t), None,
            )
            win_end = ongrid_at or now
            generator_events = [
                {"start": p[0].isoformat(), "summary": p[2]}
                for p in parsed
                if p[1] == "generator" and t <= p[0] <= win_end
            ]
            corroborated = any(abs(ot - t) <= tol for ot, _s in self._local_obs)
            nearest = None
            for ht, snap in self._decision_hist:
                if ht <= t:
                    nearest = {k: v for k, v in snap.items() if k != "key"}
                    nearest["recorded_at"] = ht.isoformat()
            payload = {
                "witness": "cloud",
                "event_start": t.isoformat(),
                "event_start_utc": key,
                "summary": summary,
                "ongrid_at": ongrid_at.isoformat() if ongrid_at else None,
                "generator_events": generator_events,
                "corroborated_by_local": corroborated,
                "inclement_decision": nearest,
            }
            if self._emit(
                action="grid_outage",
                timestamp=key,
                description=f"grid_outage cloud off-grid at {t.isoformat()}",
                payload=payload,
                entity_id=eid,
            ):
                self._cloud_seen.add(key)
                written += 1
        if len(self._cloud_seen) > OUTAGE_LEDGER_MAX_SEEN:
            for k in sorted(self._cloud_seen)[: len(self._cloud_seen)
                                              - OUTAGE_LEDGER_MAX_SEEN]:
                self._cloud_seen.discard(k)
        return written

    # ------------------------------------------------------------------
    # Scheduling (tracked; cancelled on unload)
    # ------------------------------------------------------------------
    def _spawn_sweep(self, _now: Any = None) -> None:
        if self._sweep_task is not None and not self._sweep_task.done():
            return  # one sweep at a time
        self._sweep_task = self.hass.async_create_task(self.sweep())

    def arm(self) -> bool:
        """Schedule the first sweep + the interval. Idempotent. False = disabled."""
        if OUTAGE_SWEEP_INTERVAL_H <= 0 or not OUTAGE_CALENDAR_PLATFORM:
            return False
        from homeassistant.helpers.event import (
            async_call_later,
            async_track_time_interval,
        )
        if self._initial_unsub is None:
            self._initial_unsub = async_call_later(
                self.hass, OUTAGE_SWEEP_INITIAL_DELAY_S, self._on_initial,
            )
        if self._interval_unsub is None:
            self._interval_unsub = async_track_time_interval(
                self.hass, self._spawn_sweep,
                timedelta(hours=OUTAGE_SWEEP_INTERVAL_H),
            )
        return True

    def _on_initial(self, _now: Any = None) -> None:
        self._initial_unsub = None
        self._spawn_sweep()

    def cancel(self) -> None:
        """Cancel timers and any in-flight sweep. Safe to call repeatedly."""
        for attr in ("_initial_unsub", "_interval_unsub"):
            unsub = getattr(self, attr)
            if unsub is not None:
                try:
                    unsub()
                except Exception:  # noqa: BLE001
                    pass
                setattr(self, attr, None)
        task = self._sweep_task
        if task is not None and not task.done():
            task.cancel()
        self._sweep_task = None
