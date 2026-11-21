"""Shared rig for AI-ROOM-RULES-TRUST-REPAIR-1 tests.

Builds the REAL ``UniversalRoomCoordinator`` (same pattern as
test_shared_space_failsafe_paused_rooms) over a MagicMock hass whose
``services`` is a recording fake (domain, service, data, target, context)
and whose ``states`` is a plain dict. No sys.modules surgery.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.universal_room_automation.const import DOMAIN


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class FakeServices:
    def __init__(self):
        self.calls: list = []
        self.registered = {("ai_task", "generate_data"), ("switch", "turn_on")}
        self.response = None
        self.raise_on: dict = {}

    def has_service(self, domain, service):
        return (domain, service) in self.registered

    async def async_call(self, domain, service, data=None, blocking=False,
                         context=None, return_response=False, **kw):
        self.calls.append(SimpleNamespace(
            domain=domain, service=service, data=dict(data or {}),
            target=_one((data or {}).get("entity_id")), context=context,
            blocking=blocking,
        ))
        err = self.raise_on.get((domain, service))
        if err is not None:
            raise err
        if return_response:
            return self.response
        return None

    def rule_calls(self):
        return [c for c in self.calls if c.domain != "ai_task"]


def _one(target):
    """A one-entity list (the manual-hold oracle returns lists) -> the id."""
    if isinstance(target, list) and len(target) == 1:
        return target[0]
    return target


def st(state, **attrs):
    return SimpleNamespace(state=state, attributes=dict(attrs), context=None)


class Rig:
    def __init__(self, *, rules=None, chains=None, data_rules=None, room="Exercise Room",
                 switches=None, states=None, extra_options=None, persons_in_room=None):
        import homeassistant.helpers.frame as _frame
        from custom_components.universal_room_automation import coordinator as co

        self.co = co
        self.db = MagicMock()
        self.db.log_memory_episode = AsyncMock(return_value=1)
        for name in ("get_energy_for_period", "get_next_occupancy_prediction",
                     "get_occupancy_percentage", "get_peak_occupancy_hour",
                     "log_environmental_data", "log_occupancy_event"):
            setattr(self.db, name, AsyncMock(return_value=None))
        self.services = FakeServices()
        self.states = dict(states or {})
        self.persons_in_room = list(persons_in_room or [])
        pc = MagicMock()
        pc.get_persons_in_room = lambda r: list(self.persons_in_room)
        hass = MagicMock()
        hass.data = {DOMAIN: {"database": self.db, "person_coordinator": pc}}
        hass.states.get = lambda eid: self.states.get(eid)
        hass.services = self.services
        self.unsubs: list = []
        self.bus_listeners: list = []

        def _listen(event, cb):
            self.bus_listeners.append((event, cb))
            unsub = MagicMock()
            self.unsubs.append(unsub)
            return unsub

        hass.bus.async_listen = _listen
        self.hass = hass
        data = {"room_name": room, "room_type": "generic", "entry_type": "room",
                "lights": ["light.exercise_lamp"], "illuminance_threshold": 20}
        if data_rules is not None:
            data["ai_rules"] = data_rules
        options = dict(extra_options or {})
        if rules is not None:
            options["ai_rules"] = rules
        if chains is not None:
            options["automation_chains"] = chains
        entry = MagicMock()
        entry.data = data
        entry.options = options
        entry.entry_id = "EX1"
        self.tasks: list = []
        entry.async_create_background_task = (
            lambda _h, coro, _name=None, eager_start=False: self.tasks.append(coro)
        )
        self.entry = entry
        with patch.object(_frame, "report_usage", lambda *a, **k: None):
            c = co.UniversalRoomCoordinator(hass, entry)
        c._skip_first_automation = False
        self.switches = {"ai_automation": True, "manual_mode": False, "automation": True}
        self.switches.update(switches or {})
        c._get_room_switch_state = lambda key: self.switches.get(key)
        c.data = {}
        self.c = c

    async def drain(self):
        """Run every scheduled background coroutine (episode writes, rule runs)."""
        while self.tasks:
            coro = self.tasks.pop(0)
            await coro

    def __del__(self):
        # Close coroutines a test chose not to drain (no "never awaited" noise).
        for coro in getattr(self, "tasks", []):
            try:
                coro.close()
            except Exception:  # noqa: BLE001
                pass

    def episodes(self, episode_type="room_rule_decision"):
        out = []
        for call in self.db.log_memory_episode.await_args_list:
            kw = call.kwargs
            if kw.get("episode_type") == episode_type:
                out.append(kw)
        return out


def light_rule(rule_id="r1", trigger="enter", person="", service="turn_on",
               entity="light.exercise_lamp", data=None, conditions=None, enabled=True,
               created_at="2026-01-01T00:00:00+00:00"):
    return {
        "rule_id": rule_id, "source": "described", "trigger_type": trigger,
        "person": person, "conditions": conditions or [],
        "actions": [{"domain": entity.split(".")[0], "service": service,
                     "target": {"entity_id": entity}, "data": dict(data or {})}],
        "enabled": enabled, "description": "test", "summary": "",
        "created_at": created_at,
    }


def automation_rule(rule_id="a1", trigger="enter", automation="automation.exercise_music",
                    skip_condition=False, person=""):
    return {
        "rule_id": rule_id, "source": "automation", "trigger_type": trigger,
        "person": person, "conditions": [],
        "actions": [{"domain": "automation", "service": "trigger",
                     "target": {"entity_id": automation},
                     "data": {"skip_condition": skip_condition}}],
        "automation_entity": automation, "skip_condition": skip_condition,
        "enabled": True, "created_at": "2026-01-01T00:00:00+00:00",
    }
