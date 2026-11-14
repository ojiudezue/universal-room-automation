"""MUSIC-FOLLOWING-TRANSFER-REPAIR-1 (PLANNING_music_following_repair.md).

Every test drives the PRODUCTION MusicFollowing on a REAL Home Assistant core
(phcc factory): real state machine, real event bus, real entity / device
registries, real ConfigEntries, and real service registration. The speakers
are a small simulator registered as real services whose voluptuous schemas
are the UPSTREAM ones (music_assistant.transfer_queue: target entity +
``source_player`` + ``auto_play``; media_player.join: ``entity_id`` leader +
``group_members``), so a wrong payload raises exactly as in HA. Oracles are
hand-derived from the plan, never recomputed by the code under test.

Time: MusicFollowing's ``_sleep`` is replaced by a fake clock (``Clock``), so
verify / release / nudge waits are explicit steps a test can hold open to
land a bounce inside them.

Import isolation follows test_presence_geofence_late_person.py: the real
modules are imported fresh inside ``_d7_isolation.import_scope`` and
``sys.modules`` is restored when the file's tests end.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
import voluptuous as vol

import homeassistant as _real_ha_pkg

from _d7_isolation import import_scope

_HA_DIR = Path(_real_ha_pkg.__file__).resolve().parent
_PKG = "custom_components.universal_room_automation"
DOMAIN = "universal_room_automation"
PERSON = "Oji Udezue"
PERSON_EID = "person.oji_udezue"
PERSON2 = "Jaya"
PERSON2_EID = "person.jaya"


def _is_real_ha(mod) -> bool:
    if not isinstance(mod, types.ModuleType):
        return False
    f = getattr(mod, "__file__", None)
    if not f:
        return False
    try:
        return Path(f).resolve().is_relative_to(_HA_DIR)
    except (OSError, ValueError):
        return False


@pytest.fixture(scope="module")
def mods():
    with import_scope(("custom_components", "homeassistant"), attrs=True):
        for name in [k for k in sys.modules if k == "custom_components"
                     or k.startswith("custom_components.")]:
            sys.modules.pop(name, None)
        for name in [k for k in sys.modules if k.startswith("homeassistant")]:
            if not _is_real_ha(sys.modules[name]):
                sys.modules.pop(name, None)
        for name in ("homeassistant.helpers.dispatcher", "homeassistant.helpers.event"):
            sys.modules.pop(name, None)
        _core = sys.modules["homeassistant.core"]

        def _real_callback(func):
            setattr(func, "_hass_callback", True)
            return func

        def _real_is_callback(func):
            return getattr(func, "_hass_callback", False) is True

        _core.callback = _real_callback
        _core.is_callback = _real_is_callback
        from pytest_homeassistant_custom_component import common as _phcc
        for _name in ("State", "Event", "HomeAssistant", "CoreState",
                      "ServiceCall", "SupportsResponse", "Context"):
            setattr(_core, _name, getattr(_phcc, _name, getattr(_core, _name)))
        importlib.invalidate_caches()
        ns = types.SimpleNamespace(
            mf=importlib.import_module(f"{_PKG}.music_following"),
            const=importlib.import_module(f"{_PKG}.const"),
            trans=importlib.import_module(f"{_PKG}.transitions"),
            ctx=importlib.import_module(f"{_PKG}.ura_context"),
            pkg=importlib.import_module(_PKG),
            dc=importlib.import_module(f"{_PKG}.domain_coordinators.music_following"),
            nm=importlib.import_module(f"{_PKG}.domain_coordinators.notification_manager"),
            stuck=importlib.import_module(f"{_PKG}.domain_coordinators._stuck_signal_nm"),
            db=importlib.import_module(f"{_PKG}.database"),
            nightly=importlib.import_module(f"{_PKG}.nightly_maintenance"),
            er=importlib.import_module("homeassistant.helpers.entity_registry"),
            dr=importlib.import_module("homeassistant.helpers.device_registry"),
            MockConfigEntry=_phcc.MockConfigEntry,
        )
        yield ns


@pytest_asyncio.fixture
async def hass():
    from pytest_homeassistant_custom_component.common import (
        async_test_home_assistant,
        mock_storage,
    )

    # Real HA Store, in-memory backing (review B3 saved volumes persist).
    with mock_storage() as stored:
        async with async_test_home_assistant() as real_hass:
            real_hass.data["_mf_test_storage"] = stored
            yield real_hass
            await real_hass.async_block_till_done()
            await real_hass.async_stop(force=True)


# ---------------------------------------------------------------------------
# Speaker simulator (registered as real HA services)
# ---------------------------------------------------------------------------

GP = 524288 | 512  # GROUPING | PLAY_MEDIA


class Speaker:
    def __init__(self, name):
        self.name = name
        self.entities: list[str] = []
        self.state = "idle"
        self.volume = 0.5
        self.content = None
        self.group: list[str] = []
        self.never_plays = False       # play/join/transfer never reach "playing"
        self.nudge_plays = False       # ...but a media_play nudge does
        self.fail_join = False


class World:
    """Physical speakers behind HA entities; every call is recorded."""

    def __init__(self, hass, mods):
        self.hass = hass
        self.mods = mods
        self.speakers: dict[str, Speaker] = {}
        self.by_entity: dict[str, Speaker] = {}
        self.features: dict[str, int] = {}
        self.calls: list[tuple[str, str, dict, object]] = []

    def speaker(self, name, *entities, features=GP):
        sp = Speaker(name)
        self.speakers[name] = sp
        for e in entities:
            sp.entities.append(e)
            self.by_entity[e] = sp
            self.features[e] = features
        self.push(sp)
        return sp

    def push(self, sp, context=None):
        for e in sp.entities:
            attrs = {"volume_level": sp.volume, "supported_features": self.features[e]}
            if sp.content:
                attrs["media_content_id"] = sp.content
                attrs["media_content_type"] = "music"
                attrs["media_position"] = 42
            if sp.group:
                attrs["group_members"] = list(sp.group)
            self.hass.states.async_set(e, sp.state, attrs, context=context)

    def play(self, name, content="spotify:track:1", volume=0.5):
        sp = self.speakers[name]
        sp.state, sp.content, sp.volume = "playing", content, volume
        self.push(sp)

    def state(self, name):
        return self.speakers[name].state

    def volume(self, name):
        return self.speakers[name].volume

    def services(self, domain=None, service=None):
        return [c for c in self.calls
                if (domain is None or c[0] == domain) and (service is None or c[1] == service)]

    def _rec(self, call):
        self.calls.append((call.domain, call.service, dict(call.data), call.context))

    def register(self):
        cv = importlib.import_module("homeassistant.helpers.config_validation")
        h = self.hass

        def _eids(call):
            v = call.data.get("entity_id")
            return [v] if isinstance(v, str) else list(v or [])

        async def volume_set(call):
            self._rec(call)
            for e in _eids(call):
                sp = self.by_entity[e]
                sp.volume = float(call.data["volume_level"])
                self.push(sp, call.context)

        async def join(call):
            self._rec(call)
            leader = self.by_entity[_eids(call)[0]]
            if any(self.by_entity[m].fail_join for m in call.data["group_members"]):
                raise RuntimeError("join refused")
            members = [self.by_entity[m] for m in call.data["group_members"]]
            leader.group = [_eids(call)[0], *call.data["group_members"]]
            for m in members:
                m.content = leader.content
                if leader.state == "playing" and not m.never_plays:
                    m.state = "playing"
                self.push(m, call.context)
            self.push(leader, call.context)

        async def unjoin(call):
            self._rec(call)
            for e in _eids(call):
                sp = self.by_entity[e]
                sp.group = []
                sp.state = "idle"
                self.push(sp, call.context)

        async def play_media(call):
            self._rec(call)
            for e in _eids(call):
                sp = self.by_entity[e]
                sp.content = call.data["media_content_id"]
                sp.state = "idle" if sp.never_plays else "playing"
                self.push(sp, call.context)

        async def media_stop(call):
            self._rec(call)
            for e in _eids(call):
                sp = self.by_entity[e]
                sp.state = "idle"
                self.push(sp, call.context)

        async def media_play(call):
            self._rec(call)
            for e in _eids(call):
                sp = self.by_entity[e]
                if not sp.never_plays or sp.nudge_plays:
                    sp.state = "playing"
                self.push(sp, call.context)

        async def media_seek(call):
            self._rec(call)

        async def transfer_queue(call):
            self._rec(call)
            ent_reg = self.mods.er.async_get(h)
            src = call.data.get("source_player")
            src_entry = ent_reg.async_get(src) if src else None
            if src_entry is None or src_entry.platform != "music_assistant":
                raise ValueError("source_player must be a Music Assistant player")
            for e in _eids(call):
                tgt_entry = ent_reg.async_get(e)
                if tgt_entry is None or tgt_entry.platform != "music_assistant":
                    raise ValueError("target must be a Music Assistant player")
            s = self.by_entity[src]
            t = self.by_entity[_eids(call)[0]]
            t.content, s.content = s.content, None
            s.state = "idle"
            t.state = "idle" if t.never_plays else "playing"
            self.push(s, call.context)
            self.push(t, call.context)

        ent = vol.Schema({vol.Required("entity_id"): cv.entity_ids})
        h.services.async_register("media_player", "volume_set", volume_set,
                                  schema=ent.extend({vol.Required("volume_level"): vol.Coerce(float)}))
        h.services.async_register("media_player", "join", join, schema=ent.extend(
            {vol.Required("group_members"): vol.All(cv.ensure_list, [cv.entity_id])}))
        h.services.async_register("media_player", "unjoin", unjoin, schema=ent)
        h.services.async_register("media_player", "play_media", play_media, schema=ent.extend(
            {vol.Required("media_content_id"): str, vol.Required("media_content_type"): str}))
        h.services.async_register("media_player", "media_stop", media_stop, schema=ent)
        h.services.async_register("media_player", "media_play", media_play, schema=ent)
        h.services.async_register("media_player", "media_seek", media_seek, schema=ent.extend(
            {vol.Required("seek_position"): vol.Coerce(float)}))
        # Upstream schema: services.py SERVICE_TRANSFER_QUEUE (entity service:
        # target entity_id + optional source_player / auto_play only).
        h.services.async_register("music_assistant", "transfer_queue", transfer_queue,
                                  schema=ent.extend({
                                      vol.Optional("source_player"): cv.entity_id,
                                      vol.Optional("auto_play"): vol.Coerce(bool),
                                  }))


class Clock:
    """MusicFollowing._sleep + _monotonic replacement."""

    def __init__(self):
        self.t = 1000.0
        self.sleeps: list[float] = []
        self.hold = False
        self.waiters: list[asyncio.Event] = []

    def monotonic(self):
        return self.t

    async def sleep(self, s):
        self.sleeps.append(s)
        if self.hold:
            ev = asyncio.Event()
            self.waiters.append(ev)
            await ev.wait()
        self.t += float(s)
        await asyncio.sleep(0)

    def release(self):
        ws, self.waiters = self.waiters, []
        for ev in ws:
            ev.set()


async def until(pred, n=400):
    for _ in range(n):
        if pred():
            return True
        await asyncio.sleep(0)
    return pred()


class Rig(types.SimpleNamespace):
    pass


async def _make_rig(hass, mods, *, rooms=None, cm_options=None, db=None):
    """Rooms, registry, speakers, persons, and a real MusicFollowing."""
    MockConfigEntry = mods.MockConfigEntry
    er, dr = mods.er.async_get(hass), mods.dr.async_get(hass)
    world = World(hass, mods)
    world.register()
    plat_entries = {}

    def _pe(platform):
        if platform not in plat_entries:
            e = MockConfigEntry(domain=platform, data={})
            e.add_to_hass(hass)
            plat_entries[platform] = e
        return plat_entries[platform]

    def device(platform, *, mac=None, ident=None, area=None):
        kw = {}
        if mac:
            kw["connections"] = {("mac", mac)}
        kw["identifiers"] = {ident or (platform, f"id-{len(world.calls)}-{id(kw)}")}
        d = dr.async_get_or_create(config_entry_id=_pe(platform).entry_id, **kw)
        if area:
            dr.async_update_device(d.id, area_id=area)
        return d

    def entity(platform, object_id, dev, unique_id=None, domain="media_player"):
        return er.async_get_or_create(
            domain, platform, unique_id or f"u-{object_id}",
            suggested_object_id=object_id, device_id=dev.id,
            config_entry=_pe(platform),
        )

    # --- Kitchen: WiiM (native) + MA twin by MAC id -------------------------
    kd = device("wiim", mac="c0:f5:35:2f:c1:22", area="kitchen")
    entity("wiim", "kitchen_3", kd)
    kma = device("music_assistant", ident=("music_assistant", "upc0f5352fc122"))
    entity("music_assistant", "kitchen_5", kma)
    world.speaker("kitchen", "media_player.kitchen_3", "media_player.kitchen_5")
    # --- Study A: WiiM + MA twin --------------------------------------------
    sd = device("wiim", mac="c0:f5:35:8b:ec:04", area="study_a")
    entity("wiim", "study_a_3", sd)
    sma = device("music_assistant", ident=("music_assistant", "upc0f5358bec04"))
    entity("music_assistant", "study_a_5", sma)
    world.speaker("study_a", "media_player.study_a_3", "media_player.study_a_5")
    # --- Garage B: WiiM, NO MA twin (native-only) ---------------------------
    gd = device("wiim", mac="aa:bb:cc:dd:ee:01", area="garage_b")
    entity("wiim", "garage_b_3", gd)
    world.speaker("garage_b", "media_player.garage_b_3")
    # --- Utility: WiiM, NO MA twin -----------------------------------------
    ud = device("wiim", mac="aa:bb:cc:dd:ee:02", area="utility")
    entity("wiim", "utility_3", ud)
    world.speaker("utility", "media_player.utility_3")
    # --- Living Room: Denon AVR, no MA, no grouping -------------------------
    ld = device("denonavr", area="living_room")
    entity("denonavr", "living_room_2", ld)
    world.speaker("living", "media_player.living_room_2", features=512)
    # --- Master Bedroom: MA Sonos primary; Sonos Move bonus (MA twin) -------
    md = device("music_assistant", ident=("music_assistant", "RINCON_A"), area=None)
    entity("music_assistant", "master_bedroom_sonos_2", md)
    world.speaker("master", "media_player.master_bedroom_sonos_2")
    mvd = device("sonos", mac="aa:bb:cc:dd:ee:03", area="master_bedroom")
    entity("sonos", "move_2", mvd)
    mvma = device("music_assistant", ident=("music_assistant", "upaabbccddee03"))
    entity("music_assistant", "move_ma", mvma)
    world.speaker("move", "media_player.move_2", "media_player.move_ma")
    # a TV in the same area: no GROUPING -> never a bonus
    tvd = device("samsungtv", area="master_bedroom")
    entity("samsungtv", "master_tv", tvd)
    world.speaker("tv", "media_player.master_tv", features=512)

    # --- Person + Bermuda (registry route a) --------------------------------
    for p_eid, uid, obj in ((PERSON_EID, "8ce182", "iphone_oji"),
                            (PERSON2_EID, "89b8e4", "iphone_jaya")):
        bd = device("bermuda", ident=("bermuda", uid))
        entity("bermuda", f"{obj}_bermuda_tracker", bd, unique_id=uid, domain="device_tracker")
        entity("bermuda", f"{obj}_area", bd, unique_id=uid, domain="sensor")
        entity("bermuda", f"{obj}_distance", bd, unique_id=f"{uid}_range", domain="sensor")
        hass.states.async_set(p_eid, "home", {
            "device_trackers": [f"device_tracker.{obj}_bermuda_tracker",
                                f"device_tracker.{obj}_phone_app"]})
        hass.states.async_set(f"sensor.{obj}_area", "Kitchen", {})
        hass.states.async_set(f"sensor.{obj}_distance", "3.0", {"unit_of_measurement": "ft"})

    # --- URA config entries --------------------------------------------------
    cm = MockConfigEntry(domain=DOMAIN, data={
        "entry_type": "coordinator_manager",
        "music_following_coordinator_enabled": True,
    }, options=dict(cm_options or {}))
    cm.add_to_hass(hass)
    room_defs = rooms or [
        ("Kitchen", "media_player.kitchen_3", "kitchen"),
        ("Study A", "media_player.study_a_3", "study_a"),
        ("Garage B", "media_player.garage_b_3", "garage_b"),
        ("Laundry", "media_player.utility_3", "utility"),
        ("Living Room", "media_player.living_room_2", "living_room"),
        ("Master Bedroom", "media_player.master_bedroom_sonos_2", "master_bedroom"),
        ("Hall", None, "hall"),
    ]
    for name, player, area in room_defs:
        data = {"entry_type": "room", "room_name": name, "area_id": area}
        if player:
            data["room_media_player"] = player
        MockConfigEntry(domain=DOMAIN, data=data, title=name).add_to_hass(hass)

    td = mods.trans.TransitionDetector(hass, MagicMock(), MagicMock())
    mf = mods.mf.MusicFollowing(hass, {}, td)
    clock = Clock()
    mf._sleep = clock.sleep
    mf._monotonic = clock.monotonic
    mf.enable_for_person(PERSON_EID)
    mf.enable_for_person(PERSON2_EID)
    hass.data.setdefault(DOMAIN, {})["music_following"] = mf
    if db is not None:
        hass.data[DOMAIN]["database"] = db
    hass.data[DOMAIN]["person_coordinator"] = FakePersonLayer()
    hass.data[DOMAIN]["person_coordinator"].locations[PERSON] = "Kitchen"
    await hass.async_block_till_done()
    return Rig(hass=hass, mods=mods, world=world, mf=mf, clock=clock, td=td, cm=cm,
               er=er, dr=dr)


def T(rig, frm, to, *, person=PERSON, area="Kitchen", dwell=5, conf=0.95, path="direct",
      method="bermuda"):
    from homeassistant.util import dt as dt_util
    return rig.mods.trans.RoomTransition(
        person_id=person, from_room=frm, to_room=to, timestamp=dt_util.now(),
        duration_seconds=dwell, path_type=path, confidence=conf,
        ble_area=area, ble_area_sensor=None, ble_method=method,
    )


async def move(rig, frm, to, **kw):
    """One room change through the production entry, then let it finish."""
    area = kw.pop("area", to)
    await rig.mf._on_person_transition(T(rig, frm, to, area=area, **kw))
    await rig.mf.async_wait_idle()
    await rig.hass.async_block_till_done()
    return rig.mf._last_decision.get("outcome")


class FakePersonLayer:
    """The F4-BLE owner's public read (PersonTrackingCoordinator §4.1):
    ``tracked_persons`` + ``get_person_location``. ``data`` is deliberately
    a trap: music following must never read the store (INV-LAYER-READ)."""

    def __init__(self):
        self.locations: dict[str, str] = {}
        self.reads: list[str] = []

    @property
    def tracked_persons(self):
        return list(self.locations)

    def get_person_location(self, name):
        self.reads.append(name)
        return self.locations.get(name, "unknown")

    @property
    def data(self):
        raise AssertionError("music following read person_coordinator.data")


def layer(rig) -> FakePersonLayer:
    pc = rig.hass.data[DOMAIN].get("person_coordinator")
    if not isinstance(pc, FakePersonLayer):
        pc = FakePersonLayer()
        rig.hass.data[DOMAIN]["person_coordinator"] = pc
    return pc


_WHO = {"oji": PERSON, "jaya": PERSON2}


def set_area(rig, room, person="oji"):
    """The layer's resolved room for the person (what the gate compares)."""
    layer(rig).locations[_WHO.get(person, person)] = room


@pytest_asyncio.fixture
async def rig(hass, mods):
    r = await _make_rig(hass, mods)
    try:
        yield r
    finally:
        await r.mf.async_teardown()


def _ura(rig, call):
    return rig.mods.ctx.is_ura_context(call[3])


# ===========================================================================
# D1 — the dwell gate is gone; BLE certainty on LIVE inputs, fail open
# ===========================================================================


@pytest.mark.asyncio
async def test_mf_five_minute_dwell_then_walk_transfers(rig):
    """5 minutes in the Kitchen (transition confidence 0.50, the value the
    old gate rejected at 0.6) then a walk: the music moves."""
    rig.world.play("kitchen", volume=0.4)
    set_area(rig, "Study A")
    out = await move(rig, "Kitchen", "Study A", dwell=300, conf=0.50, path="separate")
    assert out == "success"
    tq = rig.world.services("music_assistant", "transfer_queue")
    assert len(tq) == 1
    assert rig.world.state("study_a") == "playing"


@pytest.mark.asyncio
async def test_mf_first_room_change_after_hours_away_transfers(rig):
    """After hours away the detector has no history: confidence 0.5,
    duration 0 (transitions._detect_transition). It still transfers."""
    rig.world.play("kitchen")
    set_area(rig, "Study A")
    out = await move(rig, "Kitchen", "Study A", dwell=0, conf=0.5, path="direct")
    assert out == "success"
    assert rig.world.state("study_a") == "playing"


@pytest.mark.asyncio
async def test_mf_ble_low_confidence_skips(rig):
    """The live Bermuda area no longer reads the area that produced the
    change (the person moved on before MF decided): no move, no call."""
    rig.world.play("kitchen")
    set_area(rig, "Garage B")              # live
    out = await move(rig, "Kitchen", "Study A", area="Study A")   # event area
    assert out == "ble_low_confidence"
    assert rig.world.calls == []
    assert rig.world.state("kitchen") == "playing"


@pytest.mark.asyncio
async def test_mf_ble_no_location_fails_open_counted_once(rig):
    """The layer has no location for the person: fail open, counted once
    per room change (A-L1)."""
    rig.world.play("kitchen")
    layer(rig).locations.pop(PERSON, None)
    assert await move(rig, "Kitchen", "Study A") == "success"
    assert rig.mf._transfer_stats["ble_input_missing"] == 1
    assert rig.mf._last_decision["ble_input"] == "no_location"


@pytest.mark.asyncio
async def test_mf_ble_gate_reads_the_layer_not_bermuda(rig):
    """A-H1: the gate asks the layer (get_person_location) and never reads a
    Bermuda entity. A Bermuda area sensor that disagrees is ignored; the
    layer's room decides both ways."""
    rig.hass.states.async_set("sensor.iphone_oji_area", "Garage B", {})
    rig.world.play("kitchen")
    set_area(rig, "Study A")
    assert await move(rig, "Kitchen", "Study A") == "success"
    assert PERSON in layer(rig).reads
    assert rig.mf._last_decision["ble_location"] == "Study A"


@pytest.mark.asyncio
async def test_mf_ble_any_mode_skips_check(rig):
    rig.mf.apply_config({"mf_min_ble_confidence": "any"})
    rig.world.play("kitchen")
    set_area(rig, "Garage B")
    assert await move(rig, "Kitchen", "Study A", area="Study A") == "success"


# ===========================================================================
# D2 — source = the most recent room with a playing speaker
# ===========================================================================


@pytest.mark.asyncio
async def test_mf_hallway_walk_through_transfers_from_last_playing_room(rig):
    rig.world.play("kitchen")
    set_area(rig, "Hall")
    assert await move(rig, "Kitchen", "Hall") == "no_target_player"
    rig.clock.t += 20
    set_area(rig, "Study A")
    assert await move(rig, "Hall", "Study A") == "success"
    d = rig.mf._last_decision
    assert d["source_room"] == "Kitchen" and d["source_player"] == "media_player.kitchen_3"
    assert rig.world.state("study_a") == "playing"


@pytest.mark.asyncio
async def test_mf_lookback_expired_records_no_source_player(rig):
    rig.world.play("kitchen")
    set_area(rig, "Hall")
    await move(rig, "Kitchen", "Hall")
    rig.clock.t += 91          # default lookback 90 s
    set_area(rig, "Study A")
    assert await move(rig, "Hall", "Study A") == "no_source_player"
    assert rig.mf._last_decision["knob"] == "lookback=90 age=91"


@pytest.mark.asyncio
async def test_mf_lookback_boundary_89_90_91(rig):
    for age, want in ((89, "success"), (90, "success"), (91, "no_source_player")):
        r = rig
        r.world.speakers["study_a"].state = "idle"
        r.world.push(r.world.speakers["study_a"])
        r.world.play("kitchen")
        r.mf._last_transfer_target.clear()
        set_area(r, "Hall")
        await move(r, "Kitchen", "Hall")
        r.clock.t += age
        set_area(r, "Study A")
        assert await move(r, "Hall", "Study A") == want, age
        r.clock.t += 1000


@pytest.mark.asyncio
async def test_mf_hall_speaker_not_playing_records_source_not_playing(rig):
    """The room left has a speaker that is not playing and no lookback."""
    set_area(rig, "Study A")
    assert await move(rig, "Garage B", "Study A") == "source_not_playing"


@pytest.mark.asyncio
async def test_mf_lookback_source_with_others_skips(rig):
    rig.world.play("kitchen")
    set_area(rig, "Hall")
    await move(rig, "Kitchen", "Hall")
    set_area(rig, "Kitchen", person="jaya")     # through the layer, A-H1
    set_area(rig, "Study A")
    assert await move(rig, "Hall", "Study A") == "source_has_others"
    assert rig.world.state("kitchen") == "playing"


@pytest.mark.asyncio
async def test_mf_lookback_zero_disables(rig):
    rig.mf.apply_config({"mf_source_lookback_seconds": 0})
    rig.world.play("kitchen")
    set_area(rig, "Hall")
    await move(rig, "Kitchen", "Hall")
    set_area(rig, "Study A")
    assert await move(rig, "Hall", "Study A") == "no_source_player"


# ===========================================================================
# D3 — three correct paths, follow modes
# ===========================================================================


@pytest.mark.asyncio
async def test_mf_ma_payload_target_and_source_player(rig):
    rig.world.play("kitchen")
    set_area(rig, "Study A")
    await move(rig, "Kitchen", "Study A")
    (dom, svc, data, ctx), = rig.world.services("music_assistant", "transfer_queue")
    assert data == {"entity_id": ["media_player.study_a_5"],
                    "source_player": "media_player.kitchen_5", "auto_play": True}
    assert rig.mods.ctx.is_ura_context(ctx)


@pytest.mark.asyncio
async def test_mf_ma_skipped_when_ma_source_not_playing(rig):
    """The native WiiM plays (e.g. AirPlay) but its MA twin reads idle: the
    MA queue is not the music the person hears, so MA is not used."""
    rig.world.play("kitchen")
    rig.hass.states.async_set("media_player.kitchen_5", "idle",
                              {"supported_features": GP})
    set_area(rig, "Study A")
    await move(rig, "Kitchen", "Study A")
    assert rig.world.services("music_assistant") == []
    assert rig.mf._last_decision["path"] == "generic"


@pytest.mark.asyncio
async def test_mf_join_leader_is_source(rig):
    """Native WiiMs, no MA: entity_id (leader) = the playing source."""
    rig.mf.apply_config({"mf_follow_mode": "extend"})
    rig.world.play("garage_b")
    set_area(rig, "Laundry")
    assert await move(rig, "Garage B", "Laundry") == "success"
    (_, _, data, _), = rig.world.services("media_player", "join")
    assert data == {"entity_id": ["media_player.garage_b_3"],
                    "group_members": ["media_player.utility_3"]}


@pytest.mark.asyncio
async def test_mf_chained_move_joins_to_group_leader(rig):
    """Garage B -> Laundry (join), then Laundry -> Living? no grouping. Use
    Laundry -> Garage B? Instead: a third WiiM room via config edit."""
    rig.mf.apply_config({"mf_follow_mode": "extend", "mf_cooldown_seconds": 0})
    rig.world.play("garage_b")
    set_area(rig, "Laundry")
    await move(rig, "Garage B", "Laundry")
    # Laundry (follower) -> Study A, with Study A's MA twin removed so the
    # native path is the one taken.
    rig.er.async_remove("media_player.study_a_5")
    rig.world.speakers["kitchen"].state = "idle"
    set_area(rig, "Study A")
    assert await move(rig, "Laundry", "Study A") == "success"
    joins = rig.world.services("media_player", "join")
    assert joins[-1][2] == {"entity_id": ["media_player.garage_b_3"],
                            "group_members": ["media_player.study_a_3"]}
    assert "mf_group" in rig.mf._last_decision["path_reason"]


@pytest.mark.asyncio
async def test_mf_move_mode_skips_join_when_leader_release_unsafe(rig):
    """Move mode, native-only WiiMs: releasing the source (the leader) is
    unverified, so the move uses play_media instead of join."""
    rig.world.play("garage_b")
    set_area(rig, "Laundry")
    assert await move(rig, "Garage B", "Laundry") == "success"
    assert rig.world.services("media_player", "join") == []
    assert rig.mf._last_decision["path"] == "generic"
    assert "join_leader_release_unsafe:wiim" in rig.mf._last_decision["path_reason"]


@pytest.mark.parametrize("path_case", ["ma", "generic"])
@pytest.mark.asyncio
async def test_mf_move_mode_quiets_source_after_target_playing(rig, path_case):
    """Original design: fade to 10 %, target confirmed, release after the
    delay, original volume back."""
    if path_case == "ma":
        src, dst, sp_s, sp_d = "Kitchen", "Study A", "kitchen", "study_a"
    else:
        src, dst, sp_s, sp_d = "Garage B", "Laundry", "garage_b", "utility"
    rig.world.play(sp_s, volume=0.4)
    set_area(rig, dst)
    assert await move(rig, src, dst) == "success"
    assert rig.world.state(sp_d) == "playing"
    assert rig.world.state(sp_s) == "idle"
    assert rig.world.volume(sp_s) == 0.4
    assert rig.clock.sleeps[-1] == 5          # release delay default
    if path_case == "generic":
        vols = [c[2]["volume_level"] for c in rig.world.services("media_player", "volume_set")
                if c[2]["entity_id"] == [f"media_player.{'garage_b_3'}"]]
        assert vols == [0.1, 0.4]             # fade, then restore
        stops = rig.world.services("media_player", "media_stop")
        assert stops[0][2] == {"entity_id": ["media_player.garage_b_3"]}


@pytest.mark.asyncio
async def test_mf_extend_mode_never_quiets_source(rig):
    rig.mf.apply_config({"mf_follow_mode": "extend"})
    rig.world.play("garage_b", volume=0.6)
    set_area(rig, "Laundry")
    assert await move(rig, "Garage B", "Laundry") == "success"
    assert rig.world.state("garage_b") == "playing"
    assert rig.world.volume("garage_b") == 0.6
    assert rig.world.services("media_player", "media_stop") == []
    assert rig.world.services("media_player", "unjoin") == []


@pytest.mark.asyncio
async def test_mf_extend_mode_on_ma_pair_keeps_source_playing(rig):
    """A-H2: "Play in both rooms" on an MA-covered pair never calls
    transfer_queue (it moves the queue and stops the source); the MA target
    joins the playing MA source instead and the Kitchen keeps playing."""
    rig.mf.apply_config({"mf_follow_mode": "extend"})
    rig.world.play("kitchen", volume=0.6)
    set_area(rig, "Study A")
    assert await move(rig, "Kitchen", "Study A") == "success"
    assert rig.world.services("music_assistant", "transfer_queue") == []
    (_, _, data, _), = rig.world.services("media_player", "join")
    assert data == {"entity_id": ["media_player.kitchen_5"],
                    "group_members": ["media_player.study_a_5"]}
    assert rig.world.state("kitchen") == "playing"
    assert rig.world.state("study_a") == "playing"
    assert rig.world.volume("kitchen") == 0.6


@pytest.mark.asyncio
async def test_mf_fade_undone_when_target_not_playing(rig):
    rig.world.play("garage_b", volume=0.4)
    rig.world.speakers["utility"].never_plays = True
    set_area(rig, "Laundry")
    assert await move(rig, "Garage B", "Laundry") == "verify_failed"
    assert rig.world.state("garage_b") == "playing"
    assert rig.world.volume("garage_b") == 0.4
    assert rig.mf._saved_volumes == {}


@pytest.mark.parametrize("pair", [
    ("Kitchen", "Study A", "kitchen", "study_a"),        # MA
    ("Garage B", "Laundry", "garage_b", "utility"),      # generic
    ("Garage B", "Living Room", "garage_b", "living"),   # generic cross-brand
])
@pytest.mark.asyncio
async def test_mf_source_untouched_when_target_not_playing(rig, pair):
    src, dst, sp_s, sp_d = pair
    rig.world.play(sp_s, volume=0.3)
    rig.world.speakers[sp_d].never_plays = True
    set_area(rig, dst)
    out = await move(rig, src, dst)
    assert out == "verify_failed"
    if sp_s != "kitchen":   # MA itself stops the source queue when it moves
        assert rig.world.state(sp_s) == "playing"
    assert rig.world.volume(sp_s) == 0.3
    assert rig.world.services("media_player", "media_stop") == []
    assert rig.world.services("media_player", "unjoin") == []


@pytest.mark.asyncio
async def test_mf_source_volume_restored_after_release(rig):
    rig.world.play("garage_b", volume=0.37)
    set_area(rig, "Laundry")
    await move(rig, "Garage B", "Laundry")
    assert rig.world.volume("garage_b") == 0.37


@pytest.mark.asyncio
async def test_mf_saved_volumes_empty_after_restore(rig):
    rig.world.play("garage_b")
    set_area(rig, "Laundry")
    await move(rig, "Garage B", "Laundry")
    assert rig.mf._saved_volumes == {}


@pytest.mark.asyncio
async def test_mf_path_order_ma_then_native_then_generic(rig, monkeypatch):
    rig.mf.apply_config({"mf_follow_mode": "move", "mf_cooldown_seconds": 0})
    rig.world.play("kitchen")
    set_area(rig, "Study A")
    await move(rig, "Kitchen", "Study A")
    assert rig.mf._last_decision["path"] == "ma"
    # MA off -> both WiiMs group -> native join (extend: the source leads).
    rig.mf.apply_config({"mf_follow_mode": "extend"})
    monkeypatch.setattr(rig.mods.const, "MF_MA_FIRST_ENABLED", False)
    rig.world.speakers["study_a"].state = "idle"
    rig.world.push(rig.world.speakers["study_a"])
    rig.world.play("kitchen")
    rig.clock.t += 100
    await move(rig, "Kitchen", "Study A")
    assert rig.mf._last_decision["path"] == "join"
    # Cross brand -> generic.
    set_area(rig, "Living Room")
    await move(rig, "Study A", "Living Room")
    assert rig.mf._last_decision["path"] == "generic"


@pytest.mark.asyncio
async def test_mf_generic_seek_uses_position_offset_knob(rig):
    rig.mf.apply_config({"mf_position_offset": 7})
    rig.world.play("garage_b")
    set_area(rig, "Living Room")
    await move(rig, "Garage B", "Living Room")
    (_, _, data, _), = rig.world.services("media_player", "media_seek")
    assert data["seek_position"] == 49.0          # 42 + 7


@pytest.mark.asyncio
async def test_mf_all_calls_carry_ura_context(rig):
    rig.world.play("garage_b")
    set_area(rig, "Laundry")
    await move(rig, "Garage B", "Laundry")
    assert rig.world.calls
    assert all(_ura(rig, c) for c in rig.world.calls)


@pytest.mark.asyncio
async def test_mf_active_playback_blocked_when_target_playing(rig):
    rig.world.play("kitchen")
    rig.world.play("study_a", content="other")
    set_area(rig, "Study A")
    assert await move(rig, "Kitchen", "Study A") == "active_playback_blocked"
    assert rig.world.calls == []


@pytest.mark.asyncio
async def test_mf_room_opted_out_is_no_target_player(hass, mods):
    r = await _make_rig(hass, mods, rooms=[
        ("Kitchen", "media_player.kitchen_3", "kitchen"),
    ])
    mods.MockConfigEntry(domain=DOMAIN, data={
        "entry_type": "room", "room_name": "Study A", "area_id": "study_a",
        "room_media_player": "media_player.study_a_3",
        "music_following_enabled": False}).add_to_hass(hass)
    try:
        r.world.play("kitchen")
        set_area(r, "Study A")
        assert await move(r, "Kitchen", "Study A") == "no_target_player"
        assert r.mf._last_decision["reason"] == "room_opted_out"
    finally:
        await r.mf.async_teardown()


# ===========================================================================
# D3 primary / bonus (INV-MF-6)
# ===========================================================================


@pytest.mark.asyncio
async def test_mf_bonus_joins_after_primary_success(rig):
    rig.world.play("kitchen")
    set_area(rig, "Master Bedroom")
    assert await move(rig, "Kitchen", "Master Bedroom") == "success"
    joins = rig.world.services("media_player", "join")
    assert [j[2] for j in joins] == [{"entity_id": ["media_player.master_bedroom_sonos_2"],
                                      "group_members": ["media_player.move_ma"]}]
    # the TV (no GROUPING) is never joined; the primary is the leader
    tq = rig.world.services("music_assistant", "transfer_queue")
    assert rig.world.calls.index(tq[0]) < rig.world.calls.index(joins[0])


@pytest.mark.asyncio
async def test_mf_bonus_join_failure_does_not_fail_move(rig):
    rig.world.speakers["move"].fail_join = True
    rig.world.play("kitchen")
    set_area(rig, "Master Bedroom")
    assert await move(rig, "Kitchen", "Master Bedroom") == "success"
    assert rig.mf._transfer_stats["bonus_join_failed"] == 1
    assert rig.world.state("master") == "playing"


@pytest.mark.asyncio
async def test_mf_verify_reads_primary_only(rig):
    """The bonus would play but the primary does not: verify_failed, and no
    bonus join is attempted (bonus only after success)."""
    rig.world.speakers["master"].never_plays = True
    rig.world.play("kitchen")
    set_area(rig, "Master Bedroom")
    rig.hass.states.async_set("media_player.move_2", "playing", {"supported_features": GP})
    assert await move(rig, "Kitchen", "Master Bedroom") == "verify_failed"
    assert rig.world.services("media_player", "join") == []


@pytest.mark.asyncio
async def test_mf_bonus_off_knob(rig):
    rig.mf.apply_config({"mf_bonus_joins": False})
    rig.world.play("kitchen")
    set_area(rig, "Master Bedroom")
    assert await move(rig, "Kitchen", "Master Bedroom") == "success"
    assert rig.world.services("media_player", "join") == []


@pytest.mark.asyncio
async def test_mf_bonus_released_on_next_move_out(rig):
    rig.mf.apply_config({"mf_cooldown_seconds": 0})
    rig.world.play("kitchen")
    set_area(rig, "Master Bedroom")
    await move(rig, "Kitchen", "Master Bedroom")
    set_area(rig, "Study A")
    rig.clock.t += 200
    assert await move(rig, "Master Bedroom", "Study A") == "success"
    unj = [c[2] for c in rig.world.services("media_player", "unjoin")]
    assert {"entity_id": ["media_player.move_ma"]} in unj


# ===========================================================================
# D3b — fast bounce (INV-MF-5), fake clock, ping-pong 0 and cooldown 0
# ===========================================================================


def _bounce_knobs(rig):
    rig.mf.apply_config({"mf_cooldown_seconds": 0, "mf_ping_pong_window": 0})


def _one_room_playing(rig, rooms):
    return [r for r in rooms if rig.world.state(r) == "playing"]


@pytest.mark.asyncio
async def test_mf_bounce_during_fade_restores_and_keeps_queue(rig):
    """A -> B lands inside the verify wait (source faded to 10 %); B -> A
    supersedes: the fade is undone, B is taken back, A keeps its queue."""
    _bounce_knobs(rig)
    rig.world.play("garage_b", content="spotify:album:9", volume=0.45)
    set_area(rig, "Laundry")
    rig.clock.hold = True
    first = asyncio.ensure_future(
        rig.mf._on_person_transition(T(rig, "Garage B", "Laundry", area="Laundry")))
    assert await until(lambda: rig.clock.waiters)          # inside verify
    assert rig.world.volume("garage_b") == 0.1
    set_area(rig, "Garage B")
    second = asyncio.ensure_future(
        rig.mf._on_person_transition(T(rig, "Laundry", "Garage B", area="Garage B")))
    rig.clock.hold = False
    rig.clock.release()
    await asyncio.gather(first, second)
    await rig.mf.async_wait_idle()
    await rig.hass.async_block_till_done()
    assert rig.world.volume("garage_b") == 0.45
    assert rig.world.speakers["garage_b"].content == "spotify:album:9"
    assert _one_room_playing(rig, ["garage_b", "utility"]) == ["garage_b"]
    assert rig.mf._transfer_stats["superseded"] == 1
    assert rig.mf._transfer_stats["returned_in_flight"] == 1
    assert rig.mf._saved_volumes == {}


@pytest.mark.asyncio
async def test_mf_bounce_after_target_plays_before_release(rig):
    """Bounce back inside the release delay (target confirmed, source still
    faded): B is taken back, A restored, exactly one room plays."""
    _bounce_knobs(rig)
    rig.mf.apply_config({"mf_verify_delay": 0})
    rig.world.play("garage_b", volume=0.5)
    set_area(rig, "Laundry")
    rig.clock.hold = True
    first = asyncio.ensure_future(
        rig.mf._on_person_transition(T(rig, "Garage B", "Laundry", area="Laundry")))
    await first                                              # success booked
    assert rig.mf._last_decision["outcome"] == "success"
    assert await until(lambda: rig.clock.waiters)           # release delay
    set_area(rig, "Garage B")
    second = asyncio.ensure_future(
        rig.mf._on_person_transition(T(rig, "Laundry", "Garage B", area="Garage B")))
    rig.clock.hold = False
    rig.clock.release()
    await second
    await rig.mf.async_wait_idle()
    await rig.hass.async_block_till_done()
    assert _one_room_playing(rig, ["garage_b", "utility"]) == ["garage_b"]
    assert rig.world.volume("garage_b") == 0.5
    assert rig.mf._last_decision["outcome"] == "returned_in_flight"
    # one outcome each: success (first) + returned_in_flight (second)
    assert rig.mf._transfer_stats["success"] == 1
    assert rig.mf._transfer_stats["superseded"] == 0


@pytest.mark.asyncio
async def test_mf_bounce_to_third_room_during_release_completes_move(rig):
    _bounce_knobs(rig)
    rig.mf.apply_config({"mf_verify_delay": 0})
    rig.world.play("garage_b", volume=0.5)
    set_area(rig, "Laundry")
    rig.clock.hold = True
    await rig.mf._on_person_transition(T(rig, "Garage B", "Laundry", area="Laundry"))
    assert await until(lambda: rig.clock.waiters)
    set_area(rig, "Living Room")
    second = asyncio.ensure_future(
        rig.mf._on_person_transition(T(rig, "Laundry", "Living Room", area="Living Room")))
    rig.clock.hold = False
    rig.clock.release()
    await second
    await rig.mf.async_wait_idle()
    await rig.hass.async_block_till_done()
    assert rig.world.volume("garage_b") == 0.5
    assert _one_room_playing(rig, ["garage_b", "utility", "living"]) == ["living"]


@pytest.mark.asyncio
async def test_mf_rapid_triple_bounce_one_room_playing_volumes_restored(rig):
    _bounce_knobs(rig)
    rig.world.play("garage_b", volume=0.33)
    rig.world.speakers["utility"].volume = 0.21
    rig.world.push(rig.world.speakers["utility"])
    rig.clock.hold = True
    legs = [("Garage B", "Laundry"), ("Laundry", "Garage B"), ("Garage B", "Laundry"),
            ("Laundry", "Garage B")]
    futs = []
    for frm, to in legs:
        set_area(rig, to)
        futs.append(asyncio.ensure_future(
            rig.mf._on_person_transition(T(rig, frm, to, area=to))))
        await until(lambda: rig.clock.waiters, n=50)
    rig.clock.hold = False
    for _ in range(10):
        rig.clock.release()
        await asyncio.sleep(0)
    done, pending = await asyncio.wait(futs, timeout=5)
    assert not pending
    await rig.mf.async_wait_idle()
    await rig.hass.async_block_till_done()
    playing = _one_room_playing(rig, ["garage_b", "utility"])
    assert len(playing) == 1
    assert rig.world.volume("garage_b") in (0.33,)
    assert rig.mf._saved_volumes == {}
    n = sum(rig.mf._transfer_stats[k] for k in rig.mods.mf.MF_OUTCOMES)
    assert n == 4                                  # exactly one outcome per leg


@pytest.mark.asyncio
async def test_mf_two_people_bounce_same_rooms(rig):
    """Two people are independent; they serialise on the house lock; the
    second sees the first's new room as having another occupant."""
    _bounce_knobs(rig)
    rig.world.play("garage_b")
    set_area(rig, "Laundry")
    set_area(rig, "Garage B", person="jaya")
    a = await move(rig, "Garage B", "Laundry")
    assert a == "source_has_others"       # Jaya is still in Garage B
    set_area(rig, "Laundry", person="jaya")
    b = await move(rig, "Garage B", "Laundry", person=PERSON2)
    assert b == "success"
    assert _one_room_playing(rig, ["garage_b", "utility"]) == ["utility"]


# ===========================================================================
# D4 — one outcome registry; verify on ground truth; manual transfer
# ===========================================================================


@pytest.mark.asyncio
async def test_mf_record_stat_unknown_name_is_counted(rig, caplog):
    with caplog.at_level(logging.WARNING):
        rig.mf._record_stat("no_such_outcome")
    assert rig.mf._transfer_stats["unknown_outcome"] == 1
    assert "unknown outcome" in caplog.text


@pytest.mark.asyncio
async def test_mf_registry_is_single_source(rig, mods):
    m = mods.mf
    assert set(rig.mf._transfer_stats) == set(m.MF_OUTCOMES) | set(m.MF_COUNTERS)
    assert set(rig.mf.get_diagnostic_data()["outcomes_today"]) == set(m.MF_OUTCOMES)
    assert m.MF_SKIP_OUTCOMES == frozenset(set(m.MF_OUTCOMES) - {"success", "success_nudged"})
    assert "unverified" not in rig.mf._transfer_stats
    assert "low_confidence" not in rig.mf._transfer_stats


@pytest.mark.asyncio
async def test_mf_every_transition_has_exactly_one_outcome(hass, mods):
    """Table-driven: each scenario books exactly one outcome, the named one."""
    cases = {}

    async def run(name, setup, frm, to, **kw):
        r = await _make_rig(hass, mods) if not cases else cases["rig"]
        cases["rig"] = r
        r.mf._last_transfer_target.clear()
        r.mf._recent_source.clear()
        r.mf._current_house_state = ""
        r.mf.apply_config({"mf_min_ble_confidence": "normal", "mf_follow_mode": "move"})
        for sp in r.world.speakers.values():
            sp.state, sp.never_plays, sp.content = "idle", False, None
            r.world.push(sp)
        r.hass.data[DOMAIN].pop("person_coordinator", None)
        r.cm.data  # noqa: B018
        before = dict(r.mf._transfer_stats)
        await setup(r)
        set_area(r, kw.pop("live_area", to))
        out = await move(r, frm, to, **kw)
        delta = {k: r.mf._transfer_stats[k] - before[k] for k in mods.mf.MF_OUTCOMES
                 if r.mf._transfer_stats[k] != before[k]}
        assert delta == {name: 1}, (name, delta)
        assert out == name
        r.clock.t += 500

    async def nothing(r):
        return None

    async def play_k(r):
        r.world.play("kitchen")

    async def play_gb(r):
        r.world.play("garage_b")

    async def target_dead(r):
        r.world.play("kitchen")
        r.hass.states.async_set("media_player.study_a_3", "unavailable", {})

    async def target_plays(r):
        r.world.play("kitchen")
        r.world.play("study_a", content="x")

    async def never(r):
        r.world.play("garage_b")
        r.world.speakers["utility"].never_plays = True

    async def sleep_state(r):
        r.world.play("kitchen")
        r.mf.update_house_state("sleep")

    async def night_state(r):
        r.world.play("kitchen")
        r.mf.update_house_state("home_night")
        r.mf.apply_config({"mf_night_suppress_mode": "block_all"})

    async def others(r):
        r.world.play("kitchen")
        set_area(r, "Kitchen", person="jaya")

    async def cooldown(r):
        r.world.play("kitchen")
        from homeassistant.util import dt as dt_util
        r.mf._last_transfer_time[mods.mf._person_key(PERSON)] = dt_util.now()
        r.mf._last_transfer_target[mods.mf._person_key(PERSON)] = "Study A"

    async def no_content(r):
        sp = r.world.speakers["garage_b"]
        sp.state = "playing"
        r.world.push(sp)

    async def raise_path(r):
        r.world.play("garage_b")
        r.mf._resolve_path = MagicMock(side_effect=RuntimeError("boom"))

    try:
        await run("success", play_k, "Kitchen", "Study A")
        await run("same_room", nothing, "Kitchen", "Kitchen")
        await run("ble_low_confidence", play_k, "Kitchen", "Study A", live_area="Garage B")
        await run("cooldown_blocked", cooldown, "Kitchen", "Study A")
        await run("no_source_player", nothing, "Hall", "Study A")
        await run("source_not_playing", nothing, "Kitchen", "Study A")
        await run("no_target_player", play_k, "Kitchen", "Hall")
        await run("target_unavailable", target_dead, "Kitchen", "Study A")
        await run("source_has_others", others, "Kitchen", "Study A")
        await run("active_playback_blocked", target_plays, "Kitchen", "Study A")
        await run("sleep_suppressed", sleep_state, "Kitchen", "Study A")
        await run("night_suppressed", night_state, "Kitchen", "Study A")
        await run("verify_failed", never, "Garage B", "Laundry")
        await run("failed", no_content, "Garage B", "Laundry")
        await run("exception", raise_path, "Garage B", "Laundry")
        r = cases["rig"]
        await run("person_not_enabled", nothing, "Kitchen", "Study A", person="Guest Person")
        hass.config_entries.async_update_entry(
            r.cm, data={**r.cm.data, "music_following_coordinator_enabled": False})
        await run("coordinator_disabled", play_k, "Kitchen", "Study A")
    finally:
        if "rig" in cases:
            await cases["rig"].mf.async_teardown()


@pytest.mark.asyncio
async def test_mf_stale_transition_outcome(rig):
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    rig.world.play("kitchen")
    set_area(rig, "Study A")
    t = T(rig, "Kitchen", "Study A", area="Study A")
    t.timestamp = dt_util.now() - timedelta(seconds=16)
    await rig.mf._on_person_transition(t)
    assert rig.mf._last_decision["outcome"] == "stale_transition"


@pytest.mark.asyncio
async def test_mf_ping_pong_suppression_books_one_decision(rig):
    rig.mf.record_ping_pong_suppressed(PERSON, "Study A", "Kitchen")
    assert rig.mf._transfer_stats["ping_pong_suppressed"] == 1
    assert rig.mf._last_decision["outcome"] == "ping_pong_suppressed"


@pytest.mark.asyncio
async def test_mf_nudge_only_on_own_generic_media(rig):
    """Generic path: the target loaded MF's content but did not start -> one
    media_play nudge -> success_nudged. A target showing other content gets
    no nudge."""
    rig.world.play("garage_b", content="spotify:track:7")
    sp = rig.world.speakers["living"]
    sp.never_plays, sp.nudge_plays = True, True
    set_area(rig, "Living Room")
    assert await move(rig, "Garage B", "Living Room") == "success_nudged"
    assert len(rig.world.services("media_player", "media_play")) == 1
    assert rig.mf.success_count() == 1
    # other content on the target -> no nudge
    rig.clock.t += 100
    rig.mf._last_transfer_target.clear()
    rig.world.play("garage_b", content="spotify:track:7")
    sp.state, sp.nudge_plays = "idle", False
    rig.world.push(sp)
    rig.mf._call_orig = rig.mf._call

    async def _play_other(domain, service, data=None, **kw):
        if service == "play_media":
            data = {**data, "media_content_id": "something-else"}
        return await rig.mf._call_orig(domain, service, data, **kw)

    rig.mf._call = _play_other
    assert await move(rig, "Garage B", "Living Room") == "verify_failed"
    assert len(rig.world.services("media_player", "media_play")) == 1


@pytest.mark.asyncio
async def test_mf_success_rate_counts_nudged(rig, mods):
    rig.mf._record_stat("success_nudged")
    rig.mf._record_stat("verify_failed")
    assert rig.mf.get_diagnostic_data()["transfer_success_rate"] == 50.0


@pytest.mark.asyncio
async def test_mf_manual_transfer_verifies_before_release(rig):
    rig.world.play("garage_b", volume=0.4)
    rig.world.speakers["utility"].never_plays = True
    ok = await rig.mf.manual_transfer(PERSON, "Garage B", "Laundry")
    await rig.hass.async_block_till_done()
    assert ok is False
    assert rig.world.state("garage_b") == "playing"
    assert rig.world.volume("garage_b") == 0.4
    rig.world.speakers["utility"].never_plays = False
    ok = await rig.mf.manual_transfer(PERSON, "Garage B", "Laundry")
    await rig.hass.async_block_till_done()
    assert ok is True
    assert rig.world.state("utility") == "playing"
    assert rig.world.state("garage_b") == "idle"


# ===========================================================================
# D5 — observability
# ===========================================================================


@pytest.mark.asyncio
async def test_mf_decision_log_line_has_all_fields(rig, caplog, mods):
    rig.world.play("kitchen")
    set_area(rig, "Study A")
    with caplog.at_level(logging.INFO):
        await move(rig, "Kitchen", "Study A", dwell=300)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("MF decision ")]
    assert len(lines) == 1
    line = lines[0]
    for f in mods.mf.MF_DECISION_FIELDS:
        assert f" {f}=" in f" {line[len('MF decision '):]}", f
    assert "outcome=success" in line and "dwell_s=300" in line and "path=ma" in line
    diag = rig.mf.get_diagnostic_data()
    assert diag["last_decision"]["outcome"] == "success"
    assert diag["knobs"]["follow_mode"] == "move"
    assert diag["outcomes_today"]["success"] == 1


@pytest.mark.asyncio
async def test_mf_reversal_target_paused_by_person(rig):
    rig.world.play("garage_b")
    set_area(rig, "Laundry")
    await move(rig, "Garage B", "Laundry")
    # the person pauses the new room by hand (no URA context)
    rig.hass.states.async_set("media_player.utility_3", "paused",
                              {"supported_features": GP})
    await rig.hass.async_block_till_done()
    acc = rig.mf.accuracy()
    assert acc["successes"] == 1 and acc["reversals"] == 1
    assert acc["by_kind"] == {"target_stopped_by_hand": 1}
    assert acc["pct"] == 0.0


@pytest.mark.asyncio
async def test_mf_own_call_is_not_reversal(rig):
    """MF's own release (media_stop with the URA context) and a following
    MF move out of the target are not reversals."""
    rig.mf.apply_config({"mf_cooldown_seconds": 0})
    rig.world.play("garage_b")
    set_area(rig, "Laundry")
    await move(rig, "Garage B", "Laundry")
    set_area(rig, "Living Room")
    rig.clock.t += 50
    await move(rig, "Laundry", "Living Room")
    await rig.hass.async_block_till_done()
    assert rig.mf.accuracy()["reversals"] == 0


@pytest.mark.asyncio
async def test_mf_digest_section_counts(rig):
    rig.mf.apply_config({"mf_cooldown_seconds": 0})
    assert rig.mf.digest_section() == ""
    rig.world.play("garage_b")
    set_area(rig, "Laundry")
    await move(rig, "Garage B", "Laundry")
    rig.world.speakers["living"].never_plays = True
    rig.world.play("utility")
    set_area(rig, "Living Room")
    await move(rig, "Laundry", "Living Room")
    line = rig.mf.digest_section()
    assert line == "Music following, last 24 h: 2 moves, 1 played, 1 failed."


@pytest.mark.asyncio
async def test_mf_nm_digest_builder_reads_mf(rig, mods):
    rig.world.play("garage_b")
    set_area(rig, "Laundry")
    await move(rig, "Garage B", "Laundry")
    nm_like = types.SimpleNamespace(hass=rig.hass)
    line = mods.nm.NotificationManager._build_music_following_digest_section(nm_like)
    assert line == "Music following, last 24 h: 1 moves, 1 played."


@pytest.mark.asyncio
async def test_mf_silent_tripwire_fires_on_zero_success(rig, monkeypatch):
    fired = []

    async def _fire(hass, kind, key, diagnosis, remedy="", **kw):
        fired.append((kind, key, diagnosis, kw.get("severity")))
        return True

    monkeypatch.setattr(rig.mods.stuck, "fire_stuck_signal", _fire)
    for _ in range(3):
        rig.world.play("garage_b")
        rig.world.speakers["utility"].never_plays = True
        set_area(rig, "Laundry")
        rig.clock.t += 100
        await move(rig, "Garage B", "Laundry")
    res = await rig.mf.async_nightly_health_check()
    assert res["candidates"] == 3 and res["successes"] == 0 and res["fired"] is True
    assert fired[0][0] == "music_follow_silent" and fired[0][3] == "HIGH"
    assert "verify_failed (3)" in fired[0][2]


@pytest.mark.asyncio
async def test_mf_silent_tripwire_quiet_without_candidates(rig, monkeypatch):
    fired = []

    async def _fire(*a, **kw):
        fired.append(a)
        return True

    monkeypatch.setattr(rig.mods.stuck, "fire_stuck_signal", _fire)
    for _ in range(5):
        set_area(rig, "Study A")
        rig.clock.t += 100
        await move(rig, "Kitchen", "Study A")     # nothing playing
    res = await rig.mf.async_nightly_health_check()
    assert res["candidates"] == 0 and fired == []


@pytest.mark.asyncio
async def test_mf_silent_tripwire_floor_boundary(rig, monkeypatch):
    """2 candidates < floor 3: quiet."""
    fired = []

    async def _fire(*a, **kw):
        fired.append(a)
        return True

    monkeypatch.setattr(rig.mods.stuck, "fire_stuck_signal", _fire)
    for _ in range(2):
        rig.world.play("garage_b")
        rig.world.speakers["utility"].never_plays = True
        set_area(rig, "Laundry")
        rig.clock.t += 100
        await move(rig, "Garage B", "Laundry")
    res = await rig.mf.async_nightly_health_check()
    assert res["candidates"] == 2 and fired == []


@pytest.mark.asyncio
async def test_mf_nightly_op_registered(mods):
    names = [op[1] for op in mods.nightly.nightly_cleanup_ops()]
    assert "run_music_following_health_check" in names


# ===========================================================================
# D6 — room memory episodes (REAL database, production DDL)
# ===========================================================================


@pytest_asyncio.fixture
async def dbrig(hass, mods, tmp_path):
    db_hass = MagicMock()
    db_hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None, **_kw):
        return asyncio.ensure_future(coro)

    db_hass.async_create_task = _sched
    db_hass.async_create_background_task = _sched
    db = mods.db.UniversalRoomDatabase(db_hass)
    assert await db.initialize()
    await db.start_write_worker()
    r = await _make_rig(hass, mods, db=db)
    db_hass.data = {DOMAIN: {"music_following": r.mf}}
    r.db = db
    try:
        yield r
    finally:
        await r.mf.async_teardown()
        await db.stop_write_worker()


async def _flush(r):
    await r.mf.async_wait_idle()
    if r.mf._episode_tasks:
        await asyncio.wait(list(r.mf._episode_tasks))
    await r.hass.async_block_till_done()


@pytest.mark.asyncio
async def test_mf_episode_written_per_decision(dbrig):
    r = dbrig
    r.world.play("kitchen")
    set_area(r, "Study A")
    await move(r, "Kitchen", "Study A")
    await _flush(r)
    rows = await r.db.read_memory_episodes("room:study_a", "music_follow_decision")
    assert len(rows) == 1
    a = rows[0]["attrs"]
    assert a["outcome"] == "success" and a["source_player"] == "media_player.kitchen_3"
    assert a["target_player"] == "media_player.study_a_3" and a["path"] == "ma"
    assert rows[0]["source_ref"].startswith("mf:oji udezue:")


@pytest.mark.asyncio
async def test_mf_episode_not_written_without_players(dbrig):
    r = dbrig
    r.world.play("kitchen")
    set_area(r, "Hall")
    await move(r, "Kitchen", "Hall")             # no target player
    await _flush(r)
    rows = await r.db.read_memory_episodes_by_type("music_follow_decision")
    assert rows == []


@pytest.mark.asyncio
async def test_mf_episode_survives_window_dedup(dbrig):
    """Two moves into the same room 10 s apart are both written (the 60 s
    per-type window would drop the second)."""
    r = dbrig
    r.mf.apply_config({"mf_cooldown_seconds": 0})
    r.world.play("garage_b")
    r.world.speakers["utility"].never_plays = True
    set_area(r, "Laundry")
    await move(r, "Garage B", "Laundry")
    await asyncio.sleep(0.01)
    await move(r, "Garage B", "Laundry")
    await _flush(r)
    rows = await r.db.read_memory_episodes("room:laundry", "music_follow_decision")
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_mf_nightly_accuracy_rollup_from_db(dbrig):
    r = dbrig
    r.world.play("garage_b")
    set_area(r, "Laundry")
    await move(r, "Garage B", "Laundry")
    r.hass.states.async_set("media_player.utility_3", "paused", {"supported_features": GP})
    await _flush(r)
    res = await r.db.run_music_following_health_check()
    assert res["accuracy_7d"]["successes"] == 1
    assert res["accuracy_7d"]["reversals"] == 1
    acc = r.mf.accuracy()
    assert acc["window"] == "7d" and acc["pct"] == 0.0


@pytest.mark.asyncio
async def test_mf_episode_types_registered_and_writer_backed(mods):
    c = mods.const
    assert {"music_follow_decision", "music_follow_reversal"} <= c.MEMORY_EPISODE_TYPES
    assert "music_follow_decision" in c.MEMORY_WRITER_BACKED_EPISODE_TYPES
    assert "music_follow_reversal" not in c.MEMORY_WRITER_BACKED_EPISODE_TYPES
    assert "music_follow_decision" in c.MEMORY_WRITER_HEALTH_ABSENCE_EXEMPT_TYPES
    assert c.MF_EPISODE_LOG_PERSIST is True


# ===========================================================================
# D7 — knobs live, listener leak, hazard scope, preference hook
# ===========================================================================


@pytest.mark.asyncio
async def test_mf_knobs_live_after_options_update(rig, mods):
    """The real CM in-place apply pushes every MF key to the engine; each key
    is in the reload-suppress allowlist (a save never reloads the CM)."""
    pkg, c = mods.pkg, mods.const
    keys = {c.CONF_MF_COOLDOWN_SECONDS, c.CONF_MF_PING_PONG_WINDOW, c.CONF_MF_VERIFY_DELAY,
            c.CONF_MF_RELEASE_DELAY, c.CONF_MF_POSITION_OFFSET,
            c.CONF_MF_SLEEP_SUPPRESS,
            c.CONF_MF_NIGHT_SUPPRESS_MODE, c.CONF_MF_STALE_TRANSITION_SECONDS,
            c.CONF_MF_FOLLOW_MODE, c.CONF_MF_BONUS_JOINS, c.CONF_MF_MIN_BLE_CONFIDENCE,
            c.CONF_MF_SOURCE_LOOKBACK_SECONDS}
    assert pkg._MF_LIVE_KEYS == keys
    assert keys <= pkg.OPTIONS_RELOAD_SUPPRESS_KEYS
    assert "music_on_arrival_start" in pkg.OPTIONS_RELOAD_SUPPRESS_KEYS
    new = {c.CONF_MF_COOLDOWN_SECONDS: 0, c.CONF_MF_PING_PONG_WINDOW: 0,
           c.CONF_MF_VERIFY_DELAY: 30, c.CONF_MF_RELEASE_DELAY: 11,
           c.CONF_MF_POSITION_OFFSET: 9,
           c.CONF_MF_SLEEP_SUPPRESS: False, c.CONF_MF_NIGHT_SUPPRESS_MODE: "block_all",
           c.CONF_MF_STALE_TRANSITION_SECONDS: 40, c.CONF_MF_FOLLOW_MODE: "extend",
           c.CONF_MF_BONUS_JOINS: False, c.CONF_MF_MIN_BLE_CONFIDENCE: "strict",
           c.CONF_MF_SOURCE_LOOKBACK_SECONDS: 0, "music_on_arrival_start": True}
    applied = pkg._apply_in_place(rig.hass, rig.cm, set(new), new)
    assert applied == set(new)
    assert rig.mf.knobs() == {
        "follow_mode": "extend", "release_delay_s": 11.0, "bonus_joins": False,
        "location_certainty": "normal", "lookback_s": 0.0,
        "cooldown_s": 0.0, "ping_pong_s": 0.0, "verify_delay_s": 30.0,
        "position_offset_s": 9.0, "stale_transition_s": 40.0, "sleep_suppress": False,
        "night_suppress_mode": "block_all"}
    assert rig.td._ping_pong_window_s == 0.0
    assert rig.mf.get_diagnostic_data()["knobs_applied_at"]


@pytest.mark.asyncio
async def test_mf_verify_delay_extremes_0_and_30(rig):
    for delay in (0, 30):
        rig.mf.apply_config({"mf_verify_delay": delay, "mf_cooldown_seconds": 0,
                             "mf_follow_mode": "extend"})
        rig.clock.sleeps.clear()
        rig.world.speakers["utility"].state = "idle"
        rig.world.push(rig.world.speakers["utility"])
        rig.world.play("garage_b")
        set_area(rig, "Laundry")
        rig.clock.t += 100
        assert await move(rig, "Garage B", "Laundry") == "success"
        assert rig.clock.sleeps == ([] if delay == 0 else [30.0])


@pytest.mark.asyncio
async def test_mf_cooldown_boundary_7_8_9(rig):
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    key = rig.mods.mf._person_key(PERSON)
    for since, want in ((7, "cooldown_blocked"), (8, "success"), (9, "success")):
        rig.world.speakers["study_a"].state = "idle"
        rig.world.push(rig.world.speakers["study_a"])
        rig.world.play("kitchen")
        rig.mf._last_transfer_time[key] = dt_util.now() - timedelta(seconds=since)
        rig.mf._last_transfer_target[key] = "Study A"
        set_area(rig, "Study A")
        assert await move(rig, "Kitchen", "Study A") == want, since


@pytest.mark.asyncio
async def test_mf_ping_pong_window_live_and_zero_disables(rig):
    from homeassistant.util import dt as dt_util
    td = rig.td
    now = dt_util.now()
    td._record_transition(PERSON, "Kitchen", "Study A", now)
    assert td._is_ping_pong(PERSON, "Study A", "Kitchen", now) is True
    rig.mf.apply_config({"mf_ping_pong_window": 0})
    assert td._is_ping_pong(PERSON, "Study A", "Kitchen", now) is False


@pytest.mark.asyncio
async def test_mf_cooldown_zero_pingpong_zero_back_and_forth(rig):
    """Cooldown 0 + ping-pong 0: a back-and-forth walk gives at most one move
    per leg and the music ends where the person is."""
    _bounce_knobs(rig)
    rig.world.play("garage_b")
    for frm, to in (("Garage B", "Laundry"), ("Laundry", "Garage B"),
                    ("Garage B", "Laundry")):
        set_area(rig, to)
        rig.clock.t += 30
        assert await move(rig, frm, to) == "success"
    assert _one_room_playing(rig, ["garage_b", "utility"]) == ["utility"]
    assert rig.mf._transfer_stats["success"] == 3


@pytest.mark.asyncio
async def test_mf_reload_does_not_duplicate_listeners(rig, mods):
    base = len(rig.mf._diagnostic_listeners)
    for _ in range(3):
        coord = mods.dc.MusicFollowingCoordinator(rig.hass)
        await coord.async_setup()
        assert len(rig.mf._diagnostic_listeners) == base + 1
        await coord.async_teardown()
        assert len(rig.mf._diagnostic_listeners) == base
        rig.hass.data[DOMAIN]["music_following"] = rig.mf


@pytest.mark.asyncio
async def test_mf_coordinator_setup_pushes_knobs_into_engine(rig, mods):
    coord = mods.dc.MusicFollowingCoordinator(
        rig.hass, cooldown_seconds=13, verify_delay=4, unjoin_delay=6,
        options={"mf_follow_mode": "extend", "mf_source_lookback_seconds": 45,
                 "mf_min_ble_confidence": "any"})
    await coord.async_setup()
    try:
        k = rig.mf.knobs()
        assert (k["cooldown_s"], k["verify_delay_s"], k["release_delay_s"]) == (13.0, 4.0, 6.0)
        assert (k["follow_mode"], k["lookback_s"], k["location_certainty"]) == ("extend", 45.0, "any")
    finally:
        await coord.async_teardown()
        rig.hass.data[DOMAIN]["music_following"] = rig.mf


@pytest.mark.asyncio
async def test_mf_hazard_stop_scoped_to_room_players(rig, mods):
    rig.world.play("kitchen")
    rig.world.play("tv", content="netflix")       # not a configured player
    coord = mods.dc.MusicFollowingCoordinator(rig.hass)
    coord._music_following = rig.mf
    await coord._stop_all_playback()
    await rig.hass.async_block_till_done()
    stopped = [c[2]["entity_id"] for c in rig.world.services("media_player", "media_stop")]
    assert stopped == [["media_player.kitchen_3"]]
    assert rig.world.state("tv") == "playing"


@pytest.mark.asyncio
async def test_mf_preference_provider_none_is_identity(rig):
    assert rig.mf._preference_provider is None
    rig.world.play("garage_b", volume=0.4)
    set_area(rig, "Laundry")
    assert await move(rig, "Garage B", "Laundry") == "success"
    assert rig.world.state("garage_b") == "idle"           # move mode


@pytest.mark.asyncio
async def test_mf_preference_provider_overrides_mode_and_volume(rig):
    seen = []

    def provider(person_key, ctx):
        seen.append((person_key, ctx["to_room"]))
        return {"follow_mode": "extend", "target_volume": 0.25}

    rig.mf.set_preference_provider(provider)
    rig.world.play("garage_b", volume=0.4)
    set_area(rig, "Laundry")
    assert await move(rig, "Garage B", "Laundry") == "success"
    assert seen == [("oji udezue", "Laundry")]
    assert rig.world.state("garage_b") == "playing"         # extend
    assert rig.world.volume("utility") == 0.25


@pytest.mark.asyncio
async def test_mf_preference_provider_error_never_blocks(rig):
    rig.mf.set_preference_provider(lambda *_: 1 / 0)
    rig.world.play("garage_b")
    set_area(rig, "Laundry")
    assert await move(rig, "Garage B", "Laundry") == "success"


@pytest.mark.asyncio
async def test_mf_event_carries_ble_facts_to_listeners(rig, mods):
    """The producer's additive keys reach the transition (detector path)."""
    seen = []
    td = mods.trans.TransitionDetector(rig.hass, MagicMock(), MagicMock())
    td._log_transition = MagicMock(side_effect=lambda *a, **k: asyncio.sleep(0))
    td.async_add_listener(lambda t: seen.append(t))
    from homeassistant.util import dt as dt_util
    ev = types.SimpleNamespace(data={
        "person_id": PERSON, "previous_location": "Kitchen", "current_location": "Study A",
        "timestamp": dt_util.now(), "method": "bermuda", "bermuda_area": "Study A",
        "area_sensor": "sensor.iphone_oji_area"})
    td._update_history(PERSON, "Kitchen", dt_util.now())
    await td._on_location_change(ev)
    assert seen and seen[0].ble_area == "Study A"
    assert seen[0].ble_area_sensor == "sensor.iphone_oji_area"
    assert seen[0].ble_method == "bermuda"


@pytest.mark.asyncio
async def test_mf_teardown_restores_inflight_volume(rig):
    rig.world.play("garage_b", volume=0.45)
    set_area(rig, "Laundry")
    rig.clock.hold = True
    fut = asyncio.ensure_future(
        rig.mf._on_person_transition(T(rig, "Garage B", "Laundry", area="Laundry")))
    assert await until(lambda: rig.clock.waiters)
    assert rig.world.volume("garage_b") == 0.1
    await rig.mf.async_teardown()
    await fut
    await rig.hass.async_block_till_done()
    assert rig.world.volume("garage_b") == 0.45


# ===========================================================================
# §8 — the Coordinator Manager form (REAL options flow)
# ===========================================================================


@pytest.mark.asyncio
async def test_mf_cm_form_round_trip_flattens_fine_tuning(rig, mods):
    cf = importlib.import_module(f"{_PKG}.config_flow")
    rig.hass.config_entries.async_update_entry(rig.cm, options={"pre_existing": "keep"})
    flow = cf.UniversalRoomAutomationOptionsFlow(rig.cm)
    flow.hass = rig.hass
    form = await flow.async_step_coordinator_music_following(None)
    adv0 = form["data_schema"].schema[next(k for k in form["data_schema"].schema
                                          if str(getattr(k, "schema", k)) == "advanced")]
    cert = next(k for k in adv0.schema.schema if str(k) == "mf_min_ble_confidence")
    assert [o["value"] for o in adv0.schema.schema[cert].config["options"]] == ["any", "normal"]
    top = {str(getattr(k, "schema", k)) for k in form["data_schema"].schema}
    assert {"mf_follow_mode", "mf_sleep_suppress", "mf_night_suppress_mode",
            "music_anomaly_sensitivity", "advanced"} == top
    assert "mf_min_confidence" not in top
    adv = form["data_schema"].schema[next(k for k in form["data_schema"].schema
                                         if str(getattr(k, "schema", k)) == "advanced")]
    inner = {str(getattr(k, "schema", k)) for k in adv.schema.schema}
    assert inner == {"mf_unjoin_delay", "mf_cooldown_seconds", "mf_ping_pong_window",
                     "mf_verify_delay", "mf_source_lookback_seconds",
                     "mf_stale_transition_seconds",
                     "mf_min_ble_confidence", "mf_position_offset", "mf_bonus_joins"}
    res = await flow.async_step_coordinator_music_following({
        "mf_follow_mode": "extend", "mf_sleep_suppress": True,
        "advanced": {"mf_unjoin_delay": 0, "mf_cooldown_seconds": 0},
    })
    assert res["data"] == {"pre_existing": "keep", "mf_follow_mode": "extend",
                           "mf_sleep_suppress": True, "mf_unjoin_delay": 0,
                           "mf_cooldown_seconds": 0}


@pytest.mark.asyncio
async def test_mf_digest_line_reaches_delivered_nm_digest(rig, mods):
    """Wire-in anchor: the REAL NotificationManager._fire_digest appends the
    music-following line to the message it delivers (heartbeat day)."""
    rig.world.play("garage_b")
    set_area(rig, "Laundry")
    await move(rig, "Garage B", "Laundry")
    sent = []

    class _DB:
        async def get_pending_digest(self, pid):
            return []

        async def count_no_route_since(self, pid, since):
            return 0

        async def mark_digest_delivered(self, *a, **k):
            return None

    rig.hass.data[DOMAIN]["database"] = _DB()
    NM = mods.nm.NotificationManager
    nm_like = types.SimpleNamespace(hass=rig.hass, _last_digest_flush={}, _config={})
    nm_like._build_optimizer_digest_section = lambda: ""
    nm_like._build_music_following_digest_section = types.MethodType(
        NM._build_music_following_digest_section, nm_like)
    nm_like._format_digest = lambda pending: ""

    async def _deliver(pid, cfg, msg):
        sent.append(msg)
        return False

    nm_like._deliver_digest = _deliver
    await NM._fire_digest(nm_like, "person.oji_udezue", {})
    assert sent and sent[0].endswith("Music following, last 24 h: 1 moves, 1 played.")


@pytest.mark.asyncio
async def test_mf_bonus_never_joins_non_grouping_speaker(rig, mods):
    """An MA player in the room without GROUPING is never joined."""
    er = rig.er
    cfg = mods.MockConfigEntry(domain="sonos", data={})
    cfg.add_to_hass(rig.hass)
    d = rig.dr.async_get_or_create(config_entry_id=cfg.entry_id,
                                   connections={("mac", "aa:bb:cc:dd:ee:09")})
    rig.dr.async_update_device(d.id, area_id="master_bedroom")
    er.async_get_or_create("media_player", "sonos", "u-radio", suggested_object_id="radio",
                           device_id=d.id, config_entry=cfg)
    cfg2 = mods.MockConfigEntry(domain="music_assistant", data={})
    cfg2.add_to_hass(rig.hass)
    d2 = rig.dr.async_get_or_create(config_entry_id=cfg2.entry_id,
                                    identifiers={("music_assistant", "upaabbccddee09")})
    er.async_get_or_create("media_player", "music_assistant", "u-radio-ma",
                           suggested_object_id="radio_ma", device_id=d2.id, config_entry=cfg2)
    rig.world.speaker("radio", "media_player.radio", "media_player.radio_ma", features=512)
    rig.world.play("kitchen")
    set_area(rig, "Master Bedroom")
    assert await move(rig, "Kitchen", "Master Bedroom") == "success"
    joined = [m for j in rig.world.services("media_player", "join") for m in j[2]["group_members"]]
    assert joined == ["media_player.move_ma"]


@pytest.mark.asyncio
async def test_mf_verify_reads_native_primary_not_ma_twin(rig):
    """MA path: the MA twin reads playing but the room's configured speaker
    does not -> verify_failed (only the primary confirms)."""
    twin = Speaker("study_ma")
    twin.entities.append("media_player.study_a_5")
    rig.world.by_entity["media_player.study_a_5"] = twin
    rig.world.speakers["study_ma"] = twin
    rig.world.play("kitchen")
    set_area(rig, "Study A")
    assert await move(rig, "Kitchen", "Study A") == "verify_failed"
    assert twin.state == "playing" and rig.world.state("study_a") == "idle"


@pytest.mark.asyncio
async def test_mf_ura_context_stop_of_target_is_not_reversal(rig):
    rig.world.play("garage_b")
    set_area(rig, "Laundry")
    await move(rig, "Garage B", "Laundry")
    await rig.mf._call("media_player", "media_stop", {"entity_id": "media_player.utility_3"})
    await rig.hass.async_block_till_done()
    assert rig.mf.accuracy()["reversals"] == 0


@pytest.mark.asyncio
async def test_mf_silent_tripwire_quiet_with_one_success(rig, monkeypatch):
    fired = []

    async def _fire(*a, **kw):
        fired.append(a)
        return True

    monkeypatch.setattr(rig.mods.stuck, "fire_stuck_signal", _fire)
    rig.mf.apply_config({"mf_cooldown_seconds": 0})
    for i in range(3):
        rig.world.speakers["utility"].state = "idle"
        rig.world.push(rig.world.speakers["utility"])
        rig.world.play("garage_b")
        rig.world.speakers["utility"].never_plays = i > 0
        set_area(rig, "Laundry")
        rig.clock.t += 100
        await move(rig, "Garage B", "Laundry")
    res = await rig.mf.async_nightly_health_check()
    assert res["candidates"] == 3 and res["successes"] == 1 and fired == []


# ===========================================================================
# Review fix-up (v_music_following_repair_A.md / _B.md)
# ===========================================================================


def _stall_after(rig, service, entity):
    """Wrap MusicFollowing._call: the named call LANDS (the speaker acts),
    then the await stays open until the returned event is set. Models a
    cancel delivered while a blocking service call is still in flight."""
    gate = asyncio.Event()
    entered = asyncio.Event()
    real = rig.mf._call

    async def _call(domain, svc, data=None, **kw):
        ms = await real(domain, svc, data, **kw)
        eid = (data or {}).get("entity_id")
        if svc == service and eid == entity and not gate.is_set():
            entered.set()
            await gate.wait()
        return ms

    rig.mf._call = _call
    return gate, entered


@pytest.mark.asyncio
async def test_mf_source_room_opted_out_never_moves_music_out(hass, mods):
    """A-L2: the per-room switch covers both sides; music is not moved out
    of a room whose Music Following is off."""
    rooms = [("Garage B", "media_player.garage_b_3", "garage_b"),
             ("Laundry", "media_player.utility_3", "utility")]
    r = await _make_rig(hass, mods, rooms=rooms)
    try:
        for e in hass.config_entries.async_entries(DOMAIN):
            if e.data.get("room_name") == "Garage B":
                hass.config_entries.async_update_entry(
                    e, data={**e.data, "music_following_enabled": False})
        r.world.play("garage_b")
        set_area(r, "Laundry")
        assert await move(r, "Garage B", "Laundry") == "no_source_player"
        assert r.mf._last_decision["reason"] == "source_room_opted_out"
        assert r.world.calls == []
    finally:
        await r.mf.async_teardown()


@pytest.mark.asyncio
async def test_mf_room_player_by_area_id_not_name(rig):
    """A-M2: the room's primary is found through the room entry's area_id
    (device area), and ``media_player.<room>`` is never guessed."""
    dev = rig.dr.async_get_or_create(
        config_entry_id=rig.hass.config_entries.async_entries("wiim")[0].entry_id,
        connections={("mac", "aa:bb:cc:dd:ee:77")})
    rig.dr.async_update_device(dev.id, area_id="hall")
    rig.er.async_get_or_create("media_player", "wiim", "u-odd", suggested_object_id="zz_odd_name",
                               device_id=dev.id)
    rig.world.speaker("hallspk", "media_player.zz_odd_name")
    rig.world.speaker("decoy", "media_player.hall")            # name-shaped, no area
    rig.world.play("kitchen")
    set_area(rig, "Hall")
    await move(rig, "Kitchen", "Hall")
    assert rig.mf._last_decision["target_player"] == "media_player.zz_odd_name"
    assert rig.world.state("decoy") == "idle"


@pytest.mark.asyncio
async def test_mf_hazard_stop_reaches_area_resolved_primary(hass, mods):
    """A-M1: a room with no configured player whose speaker MF found by
    area and started is stopped by a hazard; a TV is not."""
    rooms = [("Garage B", "media_player.garage_b_3", "garage_b"),
             ("Laundry", None, "utility")]
    r = await _make_rig(hass, mods, rooms=rooms)
    try:
        r.world.play("garage_b")                 # move mode: generic play_media
        r.world.play("tv", content="netflix")
        set_area(r, "Laundry")
        assert await move(r, "Garage B", "Laundry") == "success"
        assert r.world.state("utility") == "playing"
        assert "media_player.utility_3" not in r.mf.configured_players()
        coord = mods.dc.MusicFollowingCoordinator(hass)
        coord._music_following = r.mf
        await coord._stop_all_playback()
        await hass.async_block_till_done()
        stopped = {c[2]["entity_id"][0] for c in r.world.services("media_player", "media_stop")}
        assert "media_player.utility_3" in stopped
        assert r.world.state("utility") == "idle"
        assert r.world.state("tv") == "playing"
    finally:
        await r.mf.async_teardown()


@pytest.mark.asyncio
async def test_mf_hazard_cancels_inflight_and_blocks_new_moves(rig, mods):
    """B2: a hazard while a move waits on verify cancels it (target taken
    back, booked hazard_blocked), stops with the URA context, and refuses
    the next room change."""
    rig.world.play("garage_b", volume=0.45)
    set_area(rig, "Laundry")
    rig.clock.hold = True
    fut = asyncio.ensure_future(
        rig.mf._on_person_transition(T(rig, "Garage B", "Laundry", area="Laundry")))
    assert await until(lambda: rig.clock.waiters)
    assert rig.world.state("utility") == "playing"
    coord = mods.dc.MusicFollowingCoordinator(rig.hass)
    coord._music_following = rig.mf
    await coord._stop_all_playback()
    await fut
    await rig.hass.async_block_till_done()
    rig.clock.hold = False
    rig.clock.release()
    assert rig.mf._transfer_stats["hazard_blocked"] == 1
    assert rig.world.state("utility") == "idle"
    assert rig.world.state("garage_b") == "idle"
    assert rig.world.volume("garage_b") == 0.45
    assert all(_ura(rig, c) for c in rig.world.services("media_player", "media_stop"))
    n_calls = len(rig.world.calls)
    rig.world.play("garage_b")
    assert await move(rig, "Garage B", "Laundry") == "hazard_blocked"
    assert len(rig.world.calls) == n_calls


@pytest.mark.asyncio
async def test_mf_lock_released_before_verify_wait(rig):
    """B1: person A's move waiting on verify does not hold the house lock;
    person B's move reaches its own verify wait meanwhile."""
    rig.world.play("garage_b")
    rig.world.play("kitchen")
    set_area(rig, "Laundry")
    set_area(rig, "Study A", person="jaya")
    rig.clock.hold = True
    a = asyncio.ensure_future(
        rig.mf._on_person_transition(T(rig, "Garage B", "Laundry", area="Laundry")))
    assert await until(lambda: len(rig.clock.waiters) == 1)
    b = asyncio.ensure_future(rig.mf._on_person_transition(
        T(rig, "Kitchen", "Study A", person=PERSON2, area="Study A")))
    assert await until(lambda: len(rig.clock.waiters) == 2)
    rig.clock.hold = False
    for _ in range(10):
        rig.clock.release()
        await asyncio.sleep(0)
    await asyncio.gather(a, b)
    await rig.mf.async_wait_idle()
    assert rig.mf._transfer_stats["success"] == 2


@pytest.mark.asyncio
async def test_mf_saved_volume_survives_restart(rig, mods):
    """B3: the pre-fade volume is persisted; a new MusicFollowing (the
    process after a crash) puts it back on a speaker still at the fade
    level, and leaves one turned up by hand alone."""
    rig.world.play("garage_b", volume=0.45)
    set_area(rig, "Laundry")
    rig.clock.hold = True
    fut = asyncio.ensure_future(
        rig.mf._on_person_transition(T(rig, "Garage B", "Laundry", area="Laundry")))
    assert await until(lambda: rig.clock.waiters)
    assert rig.world.volume("garage_b") == 0.1
    for _ in range(20):
        await asyncio.sleep(0.01)
    td2 = mods.trans.TransitionDetector(rig.hass, MagicMock(), MagicMock())
    mf2 = mods.mf.MusicFollowing(rig.hass, {}, td2)
    try:
        assert await mf2.async_replay_saved_volumes() == 1
        for _ in range(5):
            await asyncio.sleep(0)
        assert rig.world.volume("garage_b") == 0.45
    finally:
        await mf2.async_teardown()
        rig.clock.hold = False
        rig.clock.release()
        await fut


@pytest.mark.asyncio
async def test_mf_restart_replay_leaves_hand_set_volume(rig, mods):
    store = rig.mf._volumes_store()
    await store.async_save({"volumes": {"media_player.garage_b_3": 0.45}})
    rig.world.speakers["garage_b"].volume = 0.7
    rig.world.push(rig.world.speakers["garage_b"])
    td2 = mods.trans.TransitionDetector(rig.hass, MagicMock(), MagicMock())
    mf2 = mods.mf.MusicFollowing(rig.hass, {}, td2)
    try:
        assert await mf2.async_replay_saved_volumes() == 0
        assert rig.world.volume("garage_b") == 0.7
        assert mf2._saved_volumes == {}
    finally:
        await mf2.async_teardown()


@pytest.mark.asyncio
async def test_mf_init_replays_saved_volumes(rig, mods):
    """B3 wire-in: async_init (the start path) puts a persisted volume back."""
    await rig.mf._volumes_store().async_save({"volumes": {"media_player.garage_b_3": 0.45}})
    rig.world.speakers["garage_b"].volume = 0.1
    rig.world.push(rig.world.speakers["garage_b"])
    td2 = mods.trans.TransitionDetector(rig.hass, MagicMock(), MagicMock())
    mf2 = mods.mf.MusicFollowing(rig.hass, {}, td2)
    try:
        await mf2.async_init()
        for _ in range(5):
            await asyncio.sleep(0)
        assert rig.world.volume("garage_b") == 0.45
    finally:
        await mf2.async_teardown()


@pytest.mark.asyncio
async def test_mf_teardown_restores_orphan_saved_volume(rig):
    """B4: a volume still saved with no live record (its cleanup was cut
    short by a second cancel) is put back by teardown."""
    rig.world.speakers["garage_b"].volume = 0.1
    rig.world.push(rig.world.speakers["garage_b"])
    rig.mf._saved_volumes["media_player.garage_b_3"] = 0.45
    await rig.mf.async_teardown()
    await rig.hass.async_block_till_done()
    assert rig.world.volume("garage_b") == 0.45


@pytest.mark.asyncio
async def test_mf_bounce_during_source_stop_keeps_one_room_playing(rig):
    """B5: the bounce back lands while the source stop is in flight (it
    already took effect). The target is kept, and the next move brings the
    music back: exactly one room plays, the person's."""
    _bounce_knobs(rig)
    rig.mf.apply_config({"mf_verify_delay": 0, "mf_release_delay": 0})
    gate, entered = _stall_after(rig, "media_stop", "media_player.garage_b_3")
    rig.world.play("garage_b", volume=0.5)
    set_area(rig, "Laundry")
    await rig.mf._on_person_transition(T(rig, "Garage B", "Laundry", area="Laundry"))
    await asyncio.wait_for(entered.wait(), 2)
    assert rig.world.state("garage_b") == "idle"
    set_area(rig, "Garage B")
    await rig.mf._on_person_transition(T(rig, "Laundry", "Garage B", area="Garage B"))
    await rig.mf.async_wait_idle()
    await rig.hass.async_block_till_done()
    assert _one_room_playing(rig, ["garage_b", "utility"]) == ["garage_b"]


@pytest.mark.asyncio
async def test_mf_cancel_during_start_call_undoes_target(rig):
    """B6: a bounce cancels the move while play_media is still awaited (it
    already took effect): cleanup takes the target back."""
    _bounce_knobs(rig)
    gate, entered = _stall_after(rig, "play_media", "media_player.utility_3")
    rig.world.play("garage_b", volume=0.5)
    set_area(rig, "Laundry")
    first = asyncio.ensure_future(
        rig.mf._on_person_transition(T(rig, "Garage B", "Laundry", area="Laundry")))
    await asyncio.wait_for(entered.wait(), 2)
    assert rig.world.state("utility") == "playing"
    set_area(rig, "Garage B")
    second = asyncio.ensure_future(
        rig.mf._on_person_transition(T(rig, "Laundry", "Garage B", area="Garage B")))
    await asyncio.gather(first, second)
    await rig.mf.async_wait_idle()
    await rig.hass.async_block_till_done()
    assert _one_room_playing(rig, ["garage_b", "utility"]) == ["garage_b"]


@pytest.mark.asyncio
async def test_mf_tripwire_counts_persisted_decisions_after_restart(dbrig, monkeypatch):
    """B7: three failed candidates, then a restart empties the in-memory
    window; the trip-wire still counts the persisted rows and fires."""
    r = dbrig
    fired = []

    async def _fire(hass, kind, key, diagnosis, remedy="", **kw):
        fired.append(kind)
        return True

    monkeypatch.setattr(r.mods.stuck, "fire_stuck_signal", _fire)
    r.mf.apply_config({"mf_cooldown_seconds": 0})
    for _ in range(3):
        r.world.play("garage_b")
        r.world.speakers["utility"].never_plays = True
        set_area(r, "Laundry")
        r.clock.t += 100
        await move(r, "Garage B", "Laundry")
    await _flush(r)
    r.mf._recent_decisions.clear()                # the restart
    res = await r.mf.async_nightly_health_check(r.db)
    assert res["window_source"] == "db"
    assert res["candidates"] == 3 and res["successes"] == 0
    assert fired == ["music_follow_silent"]


@pytest.mark.asyncio
async def test_mf_parent_unload_tears_music_following_down(rig, mods, monkeypatch):
    """B8: unloading the integration entry tears the MusicFollowing
    singleton down before dropping it."""
    calls = []
    real = rig.mf.async_teardown

    async def _spy():
        calls.append(rig.hass.data[DOMAIN].get("music_following") is rig.mf)
        await real()

    rig.mf.async_teardown = _spy
    entry = mods.MockConfigEntry(domain=DOMAIN, data={"entry_type": "integration"})
    entry.add_to_hass(rig.hass)

    async def _unload_platforms(*_a, **_k):
        return True

    monkeypatch.setattr(rig.hass.config_entries, "async_unload_platforms", _unload_platforms)
    await mods.pkg.async_unload_entry(rig.hass, entry)
    assert calls == [True]
    assert "music_following" not in rig.hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_mf_saved_strict_and_distance_are_safe(rig, mods):
    """The distance gate was dropped 2026-11-14. An install that saved
    certainty "strict" and a distance gets Normal (the room check still
    runs), no crash; the form shows the saved "strict" as Normal."""
    applied = rig.mf.apply_config({"mf_min_ble_confidence": "strict",
                                   "mf_high_confidence_distance": 1})
    assert rig.mf.knobs()["location_certainty"] == "normal"
    assert "mf_high_confidence_distance" not in applied
    rig.world.play("kitchen")
    set_area(rig, "Garage B")
    assert await move(rig, "Kitchen", "Study A", area="Study A") == "ble_low_confidence"
    cf = importlib.import_module(f"{_PKG}.config_flow")
    rig.hass.config_entries.async_update_entry(
        rig.cm, options={"mf_min_ble_confidence": "strict", "mf_high_confidence_distance": 1})
    flow = cf.UniversalRoomAutomationOptionsFlow(rig.cm)
    flow.hass = rig.hass
    form = await flow.async_step_coordinator_music_following(None)
    adv = form["data_schema"].schema[next(k for k in form["data_schema"].schema
                                         if str(getattr(k, "schema", k)) == "advanced")]
    cert = next(k for k in adv.schema.schema if str(k) == "mf_min_ble_confidence")
    assert cert.default() == "normal"
