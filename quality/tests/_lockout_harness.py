"""Shared harness for the garage lockout tests (GARAGE-REMOTE-LOCKOUT-SCHEDULE-1).

Loads the REAL production modules under a private package name
(``_ura_lockout_pkg``) so this file never touches ``custom_components.*``
entries other test files install, and the conftest snapshot restores the
``_ura_`` prefix after each module. HA helpers used by the regime are
injected fakes (clock, timers, state trackers), so behaviour does not depend
on which HA stubs other files left in ``sys.modules``.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import pathlib
import sys
import types
from datetime import datetime, timedelta, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
URA = ROOT / "custom_components" / "universal_room_automation"
PKG = "_ura_lockout_pkg"


def load(modname: str):
    """Import ``<PKG>.<modname>`` from the real source tree."""
    if PKG not in sys.modules:
        pkg = types.ModuleType(PKG)
        pkg.__path__ = [str(URA)]
        sys.modules[PKG] = pkg
        dc = types.ModuleType(f"{PKG}.domain_coordinators")
        dc.__path__ = [str(URA / "domain_coordinators")]
        sys.modules[f"{PKG}.domain_coordinators"] = dc
    return importlib.import_module(f"{PKG}.{modname}")


TZ = timezone(timedelta(hours=-6))


class FakeState:
    def __init__(self, entity_id: str, state: str, attributes: dict | None = None,
                 last_changed: datetime | None = None) -> None:
        self.entity_id = entity_id
        self.state = state
        self.attributes = dict(attributes or {})
        self.last_changed = last_changed

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.entity_id}={self.state}>"


class FakeEvent:
    def __init__(self, data: dict) -> None:
        self.data = data


class FakeEntry:
    def __init__(self, data: dict, options: dict, entry_id: str = "cm") -> None:
        self.data = data
        self.options = options
        self.entry_id = entry_id


class World:
    """Fake hass + clock + timers + trackers + recording services."""

    def __init__(self, start: datetime, cm_options: dict, *, entry_type: str) -> None:
        self.now = start
        self.timers: list[dict] = []
        self.listeners: list[dict] = []
        self.added_cbs: list = []
        self.removed_cbs: list = []
        self.calls: list[tuple[str, str, str, bool]] = []
        self.call_hooks: list = []  # fn(domain, service, entity) -> None, run at call entry
        self.apply_service_state = True
        self.cm_entry = FakeEntry({"entry_type": entry_type}, dict(cm_options))
        self.extra_entries: list[FakeEntry] = []
        world = self

        class _States:
            def __init__(self) -> None:
                self._s: dict[str, FakeState] = {}

            def get(self, eid):
                return self._s.get(eid)

            def async_all(self, domain=None):
                return [s for e, s in self._s.items()
                        if domain is None or e.startswith(domain + ".")]

        class _Services:
            async def async_call(self, domain, service, data, blocking=False, **kw):
                eid = (data or {}).get("entity_id", "")
                world.calls.append((domain, service, eid, blocking))
                for hook in list(world.call_hooks):
                    hook(domain, service, eid)
                if world.apply_service_state and domain == "lock" and eid:
                    world.set_state(eid, "locked" if service == "lock" else "unlocked")

        class _ConfigEntries:
            def async_entries(self, domain=None):
                return [world.cm_entry, *world.extra_entries]

            def async_update_entry(self, entry, options=None, **kw):
                if options is not None:
                    entry.options = dict(options)

            async def async_reload(self, entry_id):
                if world.on_reload is not None:
                    await world.on_reload(entry_id)

        class _Hass:
            pass

        self.on_reload = None
        hass = _Hass()
        hass.states = _States()
        hass.services = _Services()
        hass.config_entries = _ConfigEntries()
        hass.data = {}
        hass.async_create_task = lambda coro, *a, **k: asyncio.get_event_loop().create_task(coro)
        hass.verify_event_loop_thread = lambda *a, **k: None
        self.dispatched: list = []
        self.hass = hass

    # -- clock / timers --------------------------------------------------
    def clock(self) -> datetime:
        return self.now

    def call_later(self, hass, delay, cb):
        rec = {"at": self.now + timedelta(seconds=float(delay)), "cb": cb,
               "cancelled": False, "delay": float(delay)}
        self.timers.append(rec)

        def _unsub():
            rec["cancelled"] = True

        return _unsub

    def live_timers(self) -> list[dict]:
        return [t for t in self.timers if not t["cancelled"] and not t.get("fired")]

    async def advance(self, seconds: float) -> None:
        end = self.now + timedelta(seconds=seconds)
        while True:
            due = sorted((t for t in self.live_timers() if t["at"] <= end),
                         key=lambda t: t["at"])
            if not due:
                break
            t = due[0]
            self.now = max(self.now, t["at"])
            t["fired"] = True
            res = t["cb"](self.now)
            if asyncio.iscoroutine(res):
                await res
            await settle()
        self.now = end
        await settle()

    # -- trackers ----------------------------------------------------------
    def track_state(self, hass, entity_ids, cb):
        ids = [entity_ids] if isinstance(entity_ids, str) else list(entity_ids)
        rec = {"ids": set(ids), "cb": cb, "active": True}
        self.listeners.append(rec)

        def _unsub():
            rec["active"] = False

        return _unsub

    def track_added(self, hass, domain, cb):
        self.added_cbs.append(cb)
        return lambda: self.added_cbs.remove(cb) if cb in self.added_cbs else None

    def track_removed(self, hass, domain, cb):
        self.removed_cbs.append(cb)
        return lambda: self.removed_cbs.remove(cb) if cb in self.removed_cbs else None

    def set_state(self, eid: str, state: str | None, attributes: dict | None = None) -> None:
        old = self.hass.states.get(eid)
        if state is None:
            self.hass.states._s.pop(eid, None)
            new = None
        else:
            attrs = attributes if attributes is not None else (old.attributes if old else {})
            new = FakeState(eid, state, attrs, last_changed=self.now)
            self.hass.states._s[eid] = new
        ev = FakeEvent({"entity_id": eid, "old_state": old, "new_state": new})
        for rec in list(self.listeners):
            if rec["active"] and eid in rec["ids"]:
                rec["cb"](ev)
        if eid.startswith("person.") and old is None and new is not None:
            for cb in list(self.added_cbs):
                cb(ev)
        if eid.startswith("person.") and old is not None and new is None:
            for cb in list(self.removed_cbs):
                cb(ev)

    def seed(self, eid: str, state: str, attributes: dict | None = None,
             last_changed: datetime | None = None) -> None:
        """Set a state without firing any event (pre-setup world)."""
        self.hass.states._s[eid] = FakeState(eid, state, attributes, last_changed)

    def locks_called(self, service: str) -> list[str]:
        return [c[2] for c in self.calls if c[0] == "lock" and c[1] == service]


async def settle(rounds: int = 10) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)
