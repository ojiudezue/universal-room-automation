"""Residency tracker (HOUSE-STATE-FIRST-PRINCIPLES-1 step 1a D2).

Plan: docs/planning/PLANNING_house_state_axes_step1.md rev 3, Part A.

A pure core (no HA import, no clock read): the presence coordinator feeds it
every raw ``person.*`` state-change event from its geofence listener and asks
it for per-person arrival / departure records.

* A RECORD is EDGE-based on the RAW person state: one ``arrival`` per raw
  ``not_home | <named zone> | unknown | unavailable -> home`` edge and one
  ``departure`` per raw ``home -> not_home | <named zone>`` edge of a resident.
  ``home -> unknown | unavailable`` and same-state (attribute-only) events
  produce none.
* ``counted`` is the lock regime's own counted-return rule
  (``arrival_edges.counted_return``) over this tracker's own ``_last_real``
  ledger (``arrival_edges.update_last_real`` / ``stamp_restored``), computed
  from the PRE-update ledger. One rule, two ledgers (INV-RULE).
* Concept split (named, Bug Class #63): records are edge-based on RAW state;
  the presence coordinator's ``residents_home`` is level-based on TRUST
  state. A resident whose GPS ``home`` BLE overrules gets a counted arrival
  but is not in ``residents_home``. Both are right for their readers.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Callable

from ..arrival_edges import counted_return, stamp_restored, update_last_real

KIND_ARRIVAL = "arrival"
KIND_DEPARTURE = "departure"

_UNREAL = frozenset({"unknown", "unavailable"})


@dataclass(frozen=True)
class ResidencyEvent:
    """One resident arrival / departure edge (display + the severity rule)."""

    kind: str
    person: str
    old_state: str | None
    new_state: str | None
    edge_ts: float
    counted: bool | None
    source_stale: bool
    in_boot_window: bool
    house_state: str | None
    resident_set_resolved: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def person_slug(pid: str) -> str:
    """``person.oji_udezue`` -> ``oji_udezue``."""
    return str(pid or "").split(".", 1)[-1].lower()


class ResidencyTracker:
    """Per-person arrived / left ledger fed from raw person edges.

    ``residents_fn()`` returns the resident person entity ids, or ``None``
    when the resident set cannot be resolved yet (early boot: then every
    ``person.*`` edge is recorded but stamped ``resident_set_resolved``
    False, and ``recent_arrival`` skips it).
    """

    def __init__(
        self,
        residents_fn: Callable[[], Any],
        *,
        setup_ts: float,
        boot_window_s: float,
        min_away_s: float,
        recent_events: int,
    ) -> None:
        self._residents_fn = residents_fn
        self._setup_ts = float(setup_ts)
        self._boot_window_s = float(boot_window_s)
        self._min_away_s = float(min_away_s)
        # person -> (state, since_ts, restored); the shared ledger shape.
        self.ledger: dict[str, tuple[str, float, bool]] = {}
        self.arrived_at: dict[str, float] = {}
        self.left_at: dict[str, float] = {}
        self.last_event: dict[str, ResidencyEvent] = {}
        self.recent: deque[ResidencyEvent] = deque(maxlen=max(1, int(recent_events)))

    def in_boot_window(self, ts: float) -> bool:
        return ts < self._setup_ts + self._boot_window_s

    def _resident_status(self, pid: str) -> tuple[bool, bool]:
        """(is_resident, resident_set_resolved)."""
        try:
            residents = self._residents_fn()
        except Exception:  # noqa: BLE001 — treat as unresolved
            residents = None
        if residents is None:
            return str(pid).startswith("person."), False
        return pid in residents, True

    def on_restore(self, pid: str, new_val: str | None, ts: float) -> None:
        """An add / restore event (``old_state`` None): stamp restored, no
        record."""
        stamp_restored(self.ledger, pid, new_val, ts)

    def on_event(
        self,
        pid: str,
        old_val: str | None,
        new_val: str | None,
        edge_ts: float,
        *,
        source_stale: bool = False,
        house_state: str | None = None,
    ) -> ResidencyEvent | None:
        """A live state-change event. Returns the record, or None."""
        record: ResidencyEvent | None = None
        if old_val != new_val:
            kind: str | None = None
            if new_val == "home":
                kind = KIND_ARRIVAL
            elif old_val == "home" and new_val is not None and new_val not in _UNREAL:
                kind = KIND_DEPARTURE
            if kind is not None:
                resident, resolved = self._resident_status(pid)
                if resident:
                    in_boot = self.in_boot_window(edge_ts)
                    counted: bool | None = None
                    if kind == KIND_ARRIVAL:
                        # From the PRE-update ledger.
                        counted = counted_return(
                            old_val,
                            self.ledger.get(pid),
                            edge_ts,
                            in_boot_window=in_boot,
                            min_away_s=self._min_away_s,
                        )
                    record = ResidencyEvent(
                        kind=kind,
                        person=pid,
                        old_state=old_val,
                        new_state=new_val,
                        edge_ts=float(edge_ts),
                        counted=counted,
                        source_stale=bool(source_stale) if kind == KIND_ARRIVAL else False,
                        in_boot_window=in_boot,
                        house_state=house_state,
                        resident_set_resolved=resolved,
                    )
        update_last_real(self.ledger, pid, new_val, edge_ts)
        if record is not None:
            if record.kind == KIND_ARRIVAL:
                self.arrived_at[pid] = record.edge_ts
            else:
                self.left_at[pid] = record.edge_ts
            self.last_event[pid] = record
            self.recent.append(record)
        return record

    def recent_arrival(
        self,
        within_s: float,
        now_ts: float,
        *,
        counted: bool = True,
        include_stale: bool = False,
        include_boot: bool = False,
    ) -> ResidencyEvent | None:
        """The newest arrival record within ``within_s`` of ``now_ts`` that
        passes the filters, else None. ``within_s <= 0`` -> None. Records
        with an unresolved resident set never qualify."""
        if within_s <= 0:
            return None
        for ev in reversed(self.recent):
            if ev.kind != KIND_ARRIVAL or not ev.resident_set_resolved:
                continue
            age = now_ts - ev.edge_ts
            if age < 0 or age > within_s:
                continue
            if counted and not ev.counted:
                continue
            if not include_stale and ev.source_stale:
                continue
            if not include_boot and ev.in_boot_window:
                continue
            return ev
        return None

    def last_of(self, kind: str) -> ResidencyEvent | None:
        for ev in reversed(self.recent):
            if ev.kind == kind:
                return ev
        return None

    def snapshot(self) -> dict[str, Any]:
        persons = sorted(set(self.arrived_at) | set(self.left_at))
        return {
            "persons": {
                person_slug(p): {
                    "arrived_at": self.arrived_at.get(p),
                    "left_at": self.left_at.get(p),
                }
                for p in persons
            },
            "last_arrival": _ev_dict(self.last_of(KIND_ARRIVAL)),
            "last_departure": _ev_dict(self.last_of(KIND_DEPARTURE)),
        }


def _ev_dict(ev: ResidencyEvent | None) -> dict[str, Any] | None:
    return None if ev is None else ev.as_dict()
