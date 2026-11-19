"""SECURITY-LOCK-STALE-STATE-1: swept-lock freshness check (D1-D4).

Plan: docs/planning/PLANNING_security_lock_freshness.md.

A lock that stops reporting keeps its last state in HA. The periodic sweep
read a silent ``locked`` lock as compliant for 55 h (11-16 07:37 -> 11-18).
This module answers one question per lock per sweep: when did the lock last
REALLY report, and is it stale, dead, or blind?

* Freshness (D1) = newest of the lock's own ``last_reported`` /
  ``last_changed`` and, for a Z-Wave lock, its same-device ``last_seen``
  sensor VALUE. Siblings come from the entity registry by ``device_id`` +
  ``platform`` + ``translation_key`` (never by entity-id string), with
  disabled entities included so a disabled ``last_seen`` reads ``disabled``.
  A stamp counts as a real report only if it is later than boot + grace
  (INV-3) and, for the lock's own stamps, later than the last
  unavailable->state recovery (a zwave_js cache restore is not a report).
  The newest real report is persisted in a Store so a restart cannot make a
  silent lock look fresh.
* Staleness (D2) applies only to locks with an ENABLED ``last_seen`` (D0:
  other locks' stamps do not advance while healthy).
* Pages (D3/D4) are HIGH NotificationActions, deduped by the Store record,
  re-paged after R while the condition holds.

The module never builds a lock or unlock command (INV-2). The only service
call it builds is a value refresh with an EMPTY ``target_device`` so the
ConflictResolver can never drop the sweep's own ``lock.lock`` for the same
device in favour of it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .base import NotificationAction, ServiceCallAction, Severity

_LOGGER = logging.getLogger(__name__)

STORE_KEY_SUFFIX = "lock_freshness"
STORE_VERSION = 1
# Store save delay (seconds). Writes happen at most once per sweep and only
# when a value moved; the delay coalesces them.
STORE_SAVE_DELAY_S = 30

HAZARD_LOCK_UNVERIFIED = "lock_unverified"
PAGE_TITLE = "Lock not verified"
PAGE_TITLE_COMMON = "Locks offline together"
PAGE_TITLE_SIGNAL = "Lock freshness signal disabled"
NOTICE_TITLE_CLEAR = "Lock reporting again"
COMMON_KEY = "__common_mode__"

SIGNAL_LAST_SEEN = "last_seen"
SIGNAL_DISABLED = "disabled"
SIGNAL_NONE = "none"

_UNREAL = (None, "unavailable", "unknown", "")


def _aware(ts: Any) -> datetime | None:
    """A tz-aware datetime or None (CF-8: never re-tag a naive stamp)."""
    if isinstance(ts, str):
        ts = dt_util.parse_datetime(ts)
    if not isinstance(ts, datetime) or ts.tzinfo is None:
        return None
    return ts


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts is not None else None


@dataclass
class SweepFreshness:
    """What the sweep needs from one freshness pass."""

    stale: set[str] = field(default_factory=set)
    actions: list[Any] = field(default_factory=list)
    signal_anomalies: list[str] = field(default_factory=list)
    # Swept locks the sweep must not count as compliant (stale, or restored
    # after a dead page with no real report since).
    unverified: set[str] = field(default_factory=set)
    # Locks whose offline notice the freshness page owns (one notice per
    # incident): the old MEDIUM offline digest skips them.
    offline_owned: set[str] = field(default_factory=set)
    freshness_signal: dict[str, str] = field(default_factory=dict)
    age_h: dict[str, float | None] = field(default_factory=dict)


class LockFreshnessTracker:
    """Per-lock freshness, dead debounce and persistent page dedup."""

    def __init__(
        self,
        hass: Any,
        store: Any,
        boot_ts: datetime,
        *,
        boot_grace_s: float,
        dead_debounce_min: float,
    ) -> None:
        self.hass = hass
        self._store = store
        self.boot_ts = boot_ts
        self._boot_grace_s = float(boot_grace_s)
        self._dead_debounce_s = float(dead_debounce_min) * 60.0
        # Persisted: {lock_id: {"real_report_ts", "paged_ts", "paged_kind",
        # "signal_paged_ts"}} plus COMMON_KEY -> {"paged_ts"}.
        self._records: dict[str, dict[str, Any]] = {}
        # RAM: the lock-state stamp of the last unavailable->state recovery.
        self._recovery_ts: dict[str, datetime] = {}
        # RAM: last state seen by a sweep (fallback recovery detection).
        self._prev_state: dict[str, str | None] = {}
        # RAM: when the current dead/unavailable condition was first seen.
        self._dead_since: dict[str, datetime] = {}
        # D4 display counters (RAM, display only).
        self.stale_pages_total = 0
        self.last_stale_page: str | None = None
        # RAM: last refresh per lock (bounded while a page is pending).
        self._refreshed: dict[str, datetime] = {}
        # RAM: D4 anomaly row written once per blind episode.
        self._signal_anomaly_sent: set[str] = set()

    # ----------------------------------------------------------- persistence
    async def async_load(self) -> None:
        if self._store is None:
            return
        try:
            data = await self._store.async_load()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Lock freshness: Store load failed", exc_info=True)
            data = None
        if isinstance(data, dict) and isinstance(data.get("locks"), dict):
            self._records = {
                str(k): dict(v) for k, v in data["locks"].items()
                if isinstance(v, dict)
            }

    def _save(self) -> None:
        if self._store is None:
            return
        snapshot = {"locks": {k: dict(v) for k, v in self._records.items()}}
        try:
            self._store.async_delay_save(lambda: snapshot, STORE_SAVE_DELAY_S)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Lock freshness: Store save failed", exc_info=True)

    def record(self, lock_id: str) -> dict[str, Any]:
        """The persisted record for ``lock_id`` (read-only use in tests)."""
        return dict(self._records.get(lock_id, {}))

    # ------------------------------------------------------------- listener
    def note_state_change(self, lock_id: str, old_state: Any, new_state: Any) -> None:
        """State listener: an unavailable/unknown -> lock-state edge is a
        cache restore; remember its stamp so it is not read as a report."""
        old = getattr(old_state, "state", None)
        new = getattr(new_state, "state", None)
        if old in _UNREAL and new not in _UNREAL:
            ts = _aware(getattr(new_state, "last_changed", None)) or dt_util.utcnow()
            self._recovery_ts[lock_id] = ts

    # ------------------------------------------------------------- registry
    def _resolve(self, lock_id: str) -> dict[str, Any]:
        """Registry facts for one lock: platform, last_seen + node_status
        siblings (with disabled flag), display name. Never by name."""
        out: dict[str, Any] = {
            "platform": None, "last_seen": None, "last_seen_disabled": False,
            "node_status": None, "device_name": None, "entry_name": None,
        }
        try:
            from homeassistant.helpers import device_registry as dr  # noqa: PLC0415
            from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

            ent_reg = er.async_get(self.hass)
            entry = ent_reg.async_get(lock_id)
            if entry is None:
                return out
            out["platform"] = entry.platform
            out["entry_name"] = entry.name or entry.original_name
            if not entry.device_id:
                return out
            for sib in er.async_entries_for_device(
                ent_reg, entry.device_id, include_disabled_entities=True
            ):
                if sib.entity_id == lock_id or sib.platform != "zwave_js":
                    continue
                if sib.translation_key == "last_seen" and out["last_seen"] is None:
                    out["last_seen"] = sib.entity_id
                    out["last_seen_disabled"] = sib.disabled_by is not None
                elif sib.translation_key == "node_status" and out["node_status"] is None:
                    if sib.disabled_by is None:
                        out["node_status"] = sib.entity_id
            try:
                dev = dr.async_get(self.hass).async_get(entry.device_id)
                if dev is not None:
                    out["device_name"] = dev.name_by_user or dev.name
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Lock freshness: registry lookup failed for %s",
                          lock_id, exc_info=True)
        return out

    def _name(self, lock_id: str, state: Any, info: dict[str, Any]) -> str:
        attrs = getattr(state, "attributes", None) or {}
        name = attrs.get("friendly_name") if isinstance(attrs, dict) else None
        return str(name or info.get("entry_name") or info.get("device_name") or lock_id)

    # ------------------------------------------------------------------ sweep
    def sweep(
        self,
        lock_ids: list[str],
        excluded: set[str],
        now: datetime,
        *,
        stale_hours: float,
        repage_hours: float,
    ) -> SweepFreshness:
        """One freshness pass over every registered lock (sync, no await)."""
        out = SweepFreshness()
        grace_end = self.boot_ts + timedelta(seconds=self._boot_grace_s)
        in_grace = now < grace_end
        stale_s = float(stale_hours) * 3600.0
        repage_s = float(repage_hours) * 3600.0
        dirty = False
        per_lock: dict[str, dict[str, Any]] = {}

        for lock_id in lock_ids:
            st = self.hass.states.get(lock_id)
            info = self._resolve(lock_id)
            is_zwave = info["platform"] == "zwave_js"
            if info["last_seen"] and not info["last_seen_disabled"]:
                signal = SIGNAL_LAST_SEEN
            elif info["last_seen"]:
                signal = SIGNAL_DISABLED
            else:
                signal = SIGNAL_NONE
            out.freshness_signal[lock_id] = signal
            cur = getattr(st, "state", None)
            lock_unavail = cur in _UNREAL

            # Fallback recovery detection between sweeps (the listener is the
            # primary): unavailable last sweep, a lock state now.
            if (
                lock_id in self._prev_state
                and self._prev_state[lock_id] in _UNREAL
                and not lock_unavail
            ):
                ts = _aware(getattr(st, "last_changed", None))
                prior = self._recovery_ts.get(lock_id)
                if ts is not None and (prior is None or ts > prior):
                    self._recovery_ts[lock_id] = ts
            self._prev_state[lock_id] = cur

            rec = self._records.setdefault(lock_id, {})
            real = _aware(rec.get("real_report_ts"))
            cands: list[datetime] = []
            if not lock_unavail:
                recovery = self._recovery_ts.get(lock_id)
                for attr in ("last_reported", "last_changed"):
                    ts = _aware(getattr(st, attr, None))
                    if ts is None or ts <= grace_end or ts > now:
                        continue
                    if recovery is not None and ts <= recovery:
                        continue
                    cands.append(ts)
            if signal == SIGNAL_LAST_SEEN:
                ls = self.hass.states.get(info["last_seen"])
                ls_val = getattr(ls, "state", None)
                if ls_val not in _UNREAL:
                    ts = _aware(ls_val)
                    if ts is not None and grace_end < ts <= now:
                        cands.append(ts)
            if cands:
                newest = max(cands)
                if real is None or newest > real:
                    real = newest
                    rec["real_report_ts"] = _iso(real)
                    dirty = True

            ref = real if real is not None else grace_end
            age_s = (now - ref).total_seconds()
            out.age_h[lock_id] = round(age_s / 3600.0, 2) if real is not None else None

            node_dead = False
            if info["node_status"]:
                ns = self.hass.states.get(info["node_status"])
                node_dead = getattr(ns, "state", None) == "dead"
            dead = lock_unavail or node_dead
            if dead:
                self._dead_since.setdefault(lock_id, now)
            else:
                self._dead_since.pop(lock_id, None)
            dead_ready = dead and (
                now - self._dead_since[lock_id]
            ).total_seconds() >= self._dead_debounce_s

            swept = lock_id not in excluded
            stale = (
                not in_grace
                and swept
                and signal == SIGNAL_LAST_SEEN
                and not lock_unavail
                and age_s > stale_s
            )
            if stale:
                out.stale.add(lock_id)
            per_lock[lock_id] = {
                "state": st, "info": info, "is_zwave": is_zwave,
                "signal": signal, "real": real, "age_s": age_s,
                "dead": dead, "dead_ready": dead_ready,
                "lock_unavail": lock_unavail, "node_dead": node_dead,
                "stale": stale, "swept": swept,
            }

        if in_grace:
            # INV-3: no page of any kind inside the boot grace.
            if dirty:
                self._save()
            return out

        # Common mode: every swept lock (>= 2) down together -> one page.
        swept_ids = [lid for lid in lock_ids if lid not in excluded]
        common = len(swept_ids) >= 2 and all(
            per_lock[lid]["dead_ready"] for lid in swept_ids
        )
        common_rec = self._records.setdefault(COMMON_KEY, {})
        if common:
            down = [lid for lid in lock_ids if per_lock[lid]["dead_ready"]]
            out.offline_owned.update(down)
            paged = _aware(common_rec.get("paged_ts"))
            if paged is None or (repage_s > 0 and (now - paged).total_seconds() >= repage_s):
                names = ", ".join(
                    self._name(lid, per_lock[lid]["state"], per_lock[lid]["info"])
                    for lid in down
                )
                out.actions.append(NotificationAction(
                    coordinator_id="security",
                    severity=Severity.HIGH,
                    message=(
                        f"All swept locks went offline together ({names}). "
                        "This looks like a Z-Wave or Home Assistant event, not "
                        "the locks themselves; their state is unknown, check "
                        "the doors and the Z-Wave network."
                    ),
                    channels=["security"],
                    hazard_type=HAZARD_LOCK_UNVERIFIED,
                    location=",".join(down),
                    description=PAGE_TITLE_COMMON,
                    data={"on_notify_result": self._on_delivered(
                        COMMON_KEY, "paged_ts", now, also_dead=down)},
                ))
        elif common_rec.get("paged_ts"):
            common_rec.pop("paged_ts", None)
            dirty = True

        for lock_id in lock_ids:
            p = per_lock[lock_id]
            rec = self._records[lock_id]
            name = self._name(lock_id, p["state"], p["info"])
            paged = _aware(rec.get("paged_ts"))
            real = p["real"]
            reported_since = (
                paged is not None and real is not None and real > paged
            )
            hazard = None
            if p["dead_ready"] and not common:
                hazard = "dead"
            elif p["stale"]:
                hazard = "stale"
            elif (
                paged is not None and not p["dead"]
                and rec.get("paged_kind") in ("dead", "restored")
                and not reported_since
            ):
                # Back from a dead page through a cache restore with no real
                # report since: still unverified, keep paging every R.
                hazard = "restored"
            if p["dead"]:
                out.offline_owned.add(lock_id)
            if hazard in ("stale", "restored") and p["swept"]:
                out.unverified.add(lock_id)
            if hazard is not None:
                due = paged is None or (
                    repage_s > 0 and (now - paged).total_seconds() >= repage_s
                )
                if due:
                    out.actions.append(self._page(lock_id, name, hazard, p, now))
                    if hazard == "stale" and self._refresh_due(lock_id, now, repage_s):
                        out.actions.append(self._refresh(lock_id, p["is_zwave"]))
            elif paged is not None and not p["dead"] and reported_since:
                # First real report after the page: clear + one notice.
                rec.pop("paged_ts", None)
                rec.pop("paged_kind", None)
                self._refreshed.pop(lock_id, None)
                dirty = True
                out.actions.append(NotificationAction(
                    coordinator_id="security",
                    severity=Severity.MEDIUM,
                    message=f"{name} is reporting again.",
                    channels=["security"],
                    location=lock_id,
                    description=NOTICE_TITLE_CLEAR,
                ))
            if hazard is None and paged is None:
                # Episode over (or never paged): next stale episode refreshes.
                self._refreshed.pop(lock_id, None)

            # D4: a swept Z-Wave lock without an ENABLED last_seen is blind.
            if p["swept"] and p["is_zwave"] and p["signal"] != SIGNAL_LAST_SEEN:
                sp = _aware(rec.get("signal_paged_ts"))
                if sp is None or (repage_s > 0 and (now - sp).total_seconds() >= repage_s):
                    if lock_id not in self._signal_anomaly_sent:
                        self._signal_anomaly_sent.add(lock_id)
                        out.signal_anomalies.append(lock_id)
                    out.actions.append(NotificationAction(
                        coordinator_id="security",
                        severity=Severity.HIGH,
                        message=(
                            f"Freshness signal disabled for {name}; staleness "
                            "cannot be detected. Enable its Z-Wave 'Last seen' "
                            "sensor."
                        ),
                        channels=["security"],
                        location=lock_id,
                        description=PAGE_TITLE_SIGNAL,
                        data={"on_notify_result": self._on_delivered(
                            lock_id, "signal_paged_ts", now)},
                    ))
            else:
                self._signal_anomaly_sent.discard(lock_id)
                if rec.get("signal_paged_ts"):
                    rec.pop("signal_paged_ts", None)
                    dirty = True

        if dirty:
            self._save()
        return out

    def _on_delivered(self, key: str, field_name: str, now: datetime,
                      kind: str | None = None, also_dead: list | None = None):
        """Dedup latches on DELIVERY (review B HIGH): a page NM dropped
        (quiet hours, dedup, kill switch) leaves the record pending, so the
        next sweep proposes it again."""
        def _cb(delivered: bool) -> None:
            if not delivered:
                return
            rec = self._records.setdefault(key, {})
            rec[field_name] = _iso(now)
            if kind is not None:
                rec["paged_kind"] = kind
                if kind == "stale":
                    self.stale_pages_total += 1
                    self.last_stale_page = _iso(now)
            # Common-mode page: mark each down lock paged "dead" so a later
            # cache restore stays unverified per lock (review B2 MEDIUM).
            for lid in also_dead or ():
                lrec = self._records.setdefault(lid, {})
                lrec["paged_ts"] = _iso(now)
                lrec["paged_kind"] = "dead"
            self._save()
        return _cb

    def _refresh_due(self, lock_id: str, now: datetime, repage_s: float) -> bool:
        """One refresh per stale episode, again after R (bounded radio use
        while a page waits for quiet hours to end)."""
        last = self._refreshed.get(lock_id)
        if last is None or (repage_s > 0 and (now - last).total_seconds() >= repage_s):
            self._refreshed[lock_id] = now
            return True
        return False

    def _page(self, lock_id: str, name: str, hazard: str, p: dict,
              now: datetime) -> NotificationAction:
        real = p["real"]
        since = (
            f"{p['age_s'] / 3600.0:.0f} h" if real is not None else "since restart"
        )
        if hazard == "restored":
            msg = (
                f"{name} is back online but has not reported since it went "
                "offline; state not verified, check the door."
            )
        elif hazard == "stale":
            msg = (
                f"{name} has not reported for {since}; state unknown, "
                "check the door."
            )
        elif p["node_dead"] and not p["lock_unavail"]:
            msg = (
                f"{name} is not responding (Z-Wave node dead); last report "
                f"{since if real is not None else 'unknown'}. State unknown, "
                "check the door."
            )
        else:
            msg = (
                f"{name} is offline; last report "
                f"{since + ' ago' if real is not None else 'unknown'}. State "
                "unknown, check the door."
            )
        return NotificationAction(
            coordinator_id="security",
            severity=Severity.HIGH,
            message=msg,
            channels=["security"],
            hazard_type=HAZARD_LOCK_UNVERIFIED,
            location=lock_id,
            description=PAGE_TITLE,
            data={"on_notify_result": self._on_delivered(
                lock_id, "paged_ts", now,
                kind=hazard)},
        )

    @staticmethod
    def _refresh(lock_id: str, is_zwave: bool) -> ServiceCallAction:
        # Empty target_device: the ConflictResolver groups by target_device
        # and keeps ONE action per device; a refresh must never displace the
        # sweep's lock.lock (INV-2).
        if is_zwave:
            return ServiceCallAction(
                coordinator_id="security",
                target_device="",
                severity=Severity.MEDIUM,
                # Non-blocking: a silent node must not stall the action loop.
                data={"blocking": False},
                service="zwave_js.refresh_value",
                service_data={"entity_id": lock_id},
                description=f"Lock freshness: refresh {lock_id}",
            )
        return ServiceCallAction(
            coordinator_id="security",
            target_device="",
            severity=Severity.MEDIUM,
            data={"blocking": False},
            service="homeassistant.update_entity",
            service_data={"entity_id": lock_id},
            description=f"Lock freshness: refresh {lock_id}",
        )
