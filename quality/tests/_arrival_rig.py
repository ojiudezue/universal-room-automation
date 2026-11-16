"""Shared rig for arc step 8 arrival-action tests (PLANNING_identity_actions_v6.md
rev 3.6.1). Real HA core (phcc), the production MusicFollowing engine, the REAL
residency producer (PresenceCoordinator._feed_residency + ResidencyTracker +
_persist_residency_event, borrowed onto a light presence stand-in), the real
SIGNAL_RESIDENCY_EVENT dispatcher and the real UniversalRoomDatabase on a tmp
SQLite file. Speakers come from the MF repair simulator (real services with the
upstream schemas). Timers go through the engine's injectable scheduler so a test
fires the window end, the confirm timer and the departure wait explicitly.
"""
from __future__ import annotations

import asyncio
import os
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock

from test_music_following_repair import Clock, World  # noqa: F401

DOMAIN = "universal_room_automation"
OJI, OJI_EID = "Oji Udezue", "person.oji_udezue"
EZ, EZ_EID = "Ezinne Udezue", "person.ezinne_udezue"
JAYA, JAYA_EID = "Jaya", "person.jaya"
T0 = 1_800_000_000.0           # wall clock start (epoch seconds)
PICK = {"media_content_id": "library://playlist/7", "media_content_type": "playlist",
        "entity_id": "media_player.kitchen_5"}


class Wall:
    def __init__(self, t):
        self.t = float(t)

    def __call__(self):
        return self.t


class Layer:
    """F4-BLE owner public reads + async_add_listener (the reserved R10 key)."""

    def __init__(self):
        self.locations: dict[str, str] = {OJI: "Kitchen", EZ: "Kitchen", JAYA: "Kitchen"}
        self.listeners: list = []
        from datetime import timedelta
        self.update_interval = timedelta(seconds=30)
        self.moves: list = []
        self.moves_truncated = False

    @property
    def tracked_persons(self):
        return [OJI, EZ, JAYA]

    def get_person_location(self, name):
        return self.locations.get(name, "unknown")

    def async_add_listener(self, cb):
        self.listeners.append(cb)

        def _u():
            if cb in self.listeners:
                self.listeners.remove(cb)
        return _u

    def location_moves_since(self, t):
        assert isinstance(t, datetime) and t.tzinfo is not None, "aware datetime required"
        return tuple(m for m in self.moves if m.ts >= t)

    def location_moves_truncated_since(self, t):
        assert isinstance(t, datetime) and t.tzinfo is not None, "aware datetime required"
        return self.moves_truncated

    def fire(self):
        for cb in list(self.listeners):
            cb()

    @property
    def data(self):
        raise AssertionError("arrival engine read person_coordinator.data")


class FakeRoom:
    def __init__(self):
        self.data = {"occupied": False}
        self.onset = None
        self.enabled = True
        self.automation = types.SimpleNamespace(
            is_sleep_mode_active=lambda: False, is_dark=lambda _lux=None: False)

    def occupied_since(self):
        return self.onset if self.data.get("occupied") else None

    def _is_automation_enabled(self):
        return self.enabled


def make_presence_cls(PR):
    P = PR.PresenceCoordinator

    class PresenceStub:
        """The real residency producer and F1/F4 read methods, borrowed."""
        _setup_residency = P._setup_residency
        _residency_residents = P._residency_residents
        _feed_residency = P._feed_residency
        _persist_residency_event = P._persist_residency_event
        get_residency_snapshot = P.get_residency_snapshot
        get_person_edges_since = P.get_person_edges_since
        person_edges_truncated_since = P.person_edges_truncated_since
        location_moves_since = P.location_moves_since
        location_moves_truncated_since = P.location_moves_truncated_since

        def __init__(self, hass, wall):
            self.hass = hass
            self._residency_clock = wall
            self.house_state = "home_day"
            self.census = None
            self.census_reads: list = []
            self._setup_residency()

        def get_house_census(self, view="trust", *, cls=None):
            self.census_reads.append(cls)
            return self.census

    return PresenceStub


def census(unidentified):
    return types.SimpleNamespace(unidentified_or_guests=unidentified, identified=1,
                                 total=1 + unidentified)


class Timers:
    def __init__(self):
        self.pending: list = []

    def __call__(self, hass, delay, cb):
        item = [float(delay), cb, False]
        self.pending.append(item)

        def _cancel():
            item[2] = True
        return _cancel

    def fire_all(self, now=None):
        fired = 0
        for item in list(self.pending):
            if not item[2]:
                item[2] = True
                item[1](now)
                fired += 1
        return fired


async def make(hass, mods, tmp_path, *, profiles=None, cm_extra=None):
    from test_music_following_repair import _make_rig
    import importlib

    PR = importlib.import_module("custom_components.universal_room_automation.domain_coordinators.presence")
    db_hass = MagicMock()
    db_hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None, **_kw):
        return asyncio.ensure_future(coro)

    db_hass.async_create_task = _sched
    db_hass.async_create_background_task = _sched
    db = mods.db.UniversalRoomDatabase(db_hass)
    assert await db.initialize()
    await db.start_write_worker()
    rooms = [
        ("Kitchen", "media_player.kitchen_3", "kitchen"),
        ("Study A", "media_player.study_a_3", "study_a"),
        ("Master Bedroom", "media_player.master_bedroom_sonos_2", "master_bedroom"),
        ("Master Bath", None, "master_bath"),
        ("Jaya Bedroom", "media_player.garage_b_3", "garage_b"),
    ]
    r = await _make_rig(hass, mods, rooms=rooms, db=db, cm_options={})
    db_hass.data = {DOMAIN: {"music_following": r.mf}}
    r.db = db
    ids = {}
    for ce in hass.config_entries.async_entries(DOMAIN):
        if ce.data.get("entry_type") == "room":
            ids[ce.data["room_name"]] = ce.entry_id
    r.ids = ids
    r.rooms = {eid: FakeRoom() for eid in ids.values()}
    for eid, room in r.rooms.items():
        hass.data[DOMAIN][eid] = room
    r.layer = Layer()
    hass.data[DOMAIN]["person_coordinator"] = r.layer
    r.wall = Wall(T0)
    r.mf._wall = r.wall
    r.timers = Timers()
    r.mf._call_later = r.timers
    r.wrapper = types.SimpleNamespace(observation_mode=False)
    r.Presence = make_presence_cls(PR)
    r.presence = r.Presence(hass, r.wall)
    hass.data[DOMAIN]["coordinator_manager"] = types.SimpleNamespace(
        coordinators={"presence": r.presence, "music_following": r.wrapper})
    r.mf.update_house_state("home_day")
    # media_pause (absent from the MF simulator) + a STOP-capable master.
    import voluptuous as vol
    import homeassistant.helpers.config_validation as cv

    async def _pause(call):
        r.world._rec(call)
        v = call.data.get("entity_id")
        for e in ([v] if isinstance(v, str) else list(v or [])):
            sp = r.world.by_entity[e]
            sp.state = "paused"
            r.world.push(sp, call.context)
    hass.services.async_register("media_player", "media_pause", _pause,
                                 schema=vol.Schema({vol.Required("entity_id"): cv.entity_ids}))
    r.world.features["media_player.master_bedroom_sonos_2"] |= 4096
    r.world.push(r.world.speakers["master"])
    master, bath, jaya = ids["Master Bedroom"], ids["Master Bath"], ids["Jaya Bedroom"]
    r.master, r.bath, r.jaya_room = master, bath, jaya
    prof = profiles if profiles is not None else {
        OJI_EID: {"rooms_bedroom": [master], "rooms_bathroom": [bath], "auto_music": True,
                  "music_default": dict(PICK), "music_volume": 0.3},
        EZ_EID: {"rooms_bedroom": [master], "rooms_bathroom": [bath], "auto_music": True,
                 "music_default": dict(PICK)},
        JAYA_EID: {"rooms_bedroom": [jaya], "auto_music": True, "music_default": dict(PICK)},
    }
    opts = {"person_profiles": prof}
    opts.update(cm_extra or {})
    hass.config_entries.async_update_entry(r.cm, options=opts)
    r.mf.async_start_arrival_actions()
    await drain(r)
    return r


def set_profile(r, person_eid, **changes):
    opts = dict(r.cm.options)
    prof = {k: dict(v) for k, v in (opts.get("person_profiles") or {}).items()}
    prof.setdefault(person_eid, {}).update(changes)
    opts["person_profiles"] = prof
    r.hass.config_entries.async_update_entry(r.cm, options=opts)


def set_cm(r, **changes):
    opts = dict(r.cm.options)
    opts.update(changes)
    r.hass.config_entries.async_update_entry(r.cm, options=opts)


async def drain(r, rounds=6):
    for _ in range(rounds):
        await r.hass.async_block_till_done()
        pending = [t for t in list(r.mf._arrival_tasks) + list(r.mf._episode_tasks)
                   if not t.done()]
        logs = [t for t in list(getattr(r.presence, "_residency_log_tasks", set()) or set())
                if not t.done()]
        if pending or logs:
            await asyncio.wait(pending + logs, timeout=5)
        await asyncio.sleep(0)
    await r.db.flush_write_queue() if hasattr(r.db, "flush_write_queue") else None


def _feed(r, eid, old, new, *, stale=False):
    """One raw person.* state change through the REAL residency producer."""
    hass = r.hass
    old_st = hass.states.get(eid)
    if old_st is None or old_st.state != old:
        hass.states.async_set(eid, old, {})
        old_st = hass.states.get(eid)
    src = f"device_tracker.{eid.split('.', 1)[1]}_phone"
    if new == "home" and not stale:
        hass.states.async_set(src, "home", {})
    attrs = {"source": src if not stale else "device_tracker.missing_tracker"}
    hass.states.async_set(eid, new, attrs)
    r.presence._feed_residency(eid, old_st, hass.states.get(eid))


async def depart(r, eid, at):
    r.wall.t = at
    _feed(r, eid, "home", "not_home")
    await drain(r)


async def come_home(r, eid, at, *, old="not_home", stale=False):
    r.wall.t = at
    _feed(r, eid, old, "home", stale=stale)
    await drain(r)


async def trip(r, eid, away_s, *, start=None):
    """Leave at ``start`` (default now), return ``away_s`` later."""
    t = r.wall.t if start is None else start
    await depart(r, eid, t)
    await come_home(r, eid, t + away_s)


async def outcomes(r, *types_):
    rows = []
    for t in (types_ or ("arrival_music", "welcome_scene")):
        rows.extend(await r.db.read_memory_episodes_by_type(t))
    return [x["attrs"] for x in sorted(rows, key=lambda x: x["id"])]


async def names(r, person=OJI_EID):
    return [a["outcome"] for a in await outcomes(r) if a.get("person") == person]


def ura_calls(r, service):
    return [c for c in r.world.services("media_player", service)]


async def window_end(r):
    r.timers.fire_all()
    await drain(r)
