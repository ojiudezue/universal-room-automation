"""EGRESS-DIRECTION-AWARE-IDENTITY-1 step 7 S1 (plan rev 3.2 §7 D1/D2).

Every crossing enters through PRODUCTION code: a REAL ``PersonCensus``, a REAL
``EgressDirectionTracker`` (``_on_egress_state_change`` -> the captured 45 s
callback -> ``_resolve_direction``), a REAL ``UniversalRoomDatabase``. F1 edges
are REAL ``ResidencyEvent`` records served through the REAL
``residency.edges_since`` / ``edges_truncated_since`` readers (the presence
delegates are one-line wrappers of those). The only stand-ins are the face /
BLE leg inputs (the producer's seams, as the d2b / D8a tests do) and NM.

Oracles are hand-derived from the plan (times and texts written as literals).
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation import transit_validator as tv
from custom_components.universal_room_automation.camera_census import (
    FaceLeg,
    PersonCensus,
)
from custom_components.universal_room_automation.domain_coordinators import (
    residency as res_mod,
)
from custom_components.universal_room_automation.transit_validator import (
    EgressDirectionTracker,
)

UTC = timezone.utc
NOW = datetime(2026, 11, 12, 18, 0, 0, tzinfo=UTC)
FRONT = "binary_sensor.front_door_person_occupancy"
GARAGE = "binary_sensor.garage_a_person_occupancy"
FOYER = "binary_sensor.foyer_person_occupancy"
EPISODE = "egress_identity_outcome"


class _StubCameraManager:
    def get_platform_for_camera(self, entity_id):
        return None

    def get_all_frigate_cameras(self):
        return []

    def resolve_configured_cameras(self, ids):
        return []


class _Clock:
    def __init__(self, t):
        self.t = t

    def now(self, *a, **k):
        return self.t

    def utcnow(self):
        return self.t


class _Presence:
    """F1 reads over a real residency ring (the presence delegates call
    ``residency.edges_since`` / ``edges_truncated_since`` on ``_residency``)."""

    def __init__(self, created_ts):
        self.tracker = SimpleNamespace(recent=deque(maxlen=64), created_ts=created_ts)
        self.raise_on_read = False
        self.calls: list = []

    def get_person_edges_since(self, t, *, persons=None, kinds=None):
        self.calls.append(("edges", t, frozenset(persons or ()), frozenset(kinds or ())))
        if self.raise_on_read:
            raise RuntimeError("boom")
        return res_mod.edges_since(
            self.tracker, t, persons=persons,
            kinds=res_mod.EDGE_KINDS if kinds is None else kinds,
        )

    def person_edges_truncated_since(self, t):
        self.calls.append(("trunc", t))
        return res_mod.edges_truncated_since(self.tracker, t)

    def add(self, person, at, *, kind="arrival", counted=True, stale=False, boot=False):
        self.tracker.recent.append(res_mod.ResidencyEvent(
            kind=kind, person=person, old_state="not_home", new_state="home",
            edge_ts=float(at.timestamp()), counted=counted, source_stale=stale,
            in_boot_window=boot, house_state="home_day", resident_set_resolved=True,
        ))


def _leg(stem, slug, last_changed, *, device="dev"):
    return FaceLeg(
        entity_id=f"sensor.{stem}_last_recognized_face",
        engine="frigate",
        device_id=f"{device}_{stem}",
        base_stem=stem,
        canonical_slug=slug,
        last_changed=last_changed,
        confidence=None,
    )


def _state(value):
    return SimpleNamespace(state=value, last_changed=NOW, attributes={})


def _ev(entity_id, value="on"):
    return SimpleNamespace(data={
        "new_state": SimpleNamespace(entity_id=entity_id, state=value),
        "old_state": SimpleNamespace(entity_id=entity_id, state="off"),
    })


@pytest_asyncio.fixture
async def rig(tmp_path, monkeypatch):
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )

    db_hass = MagicMock()
    db_hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None, **_kw):
        return asyncio.ensure_future(coro)

    db_hass.async_create_task = _sched
    db_hass.async_create_background_task = _sched
    db = UniversalRoomDatabase(db_hass)
    assert await db.initialize()
    await db.start_write_worker()

    hass = make_hass()
    states: dict = {}
    hass.states.get = lambda eid: states.get(eid)
    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        "tracked_persons": ["person.oji_udezue", "person.jaya", "person.ezinne"],
        ura_const.CONF_EGRESS_IDENTITY_ENABLED: True,
        ura_const.CONF_DOOR_GROUPS: {"front_door": "front", "garage_a": "garage_a"},
    }
    cm_entry = MagicMock()
    cm_entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_COORDINATOR_MANAGER}
    cm_entry.options = {}
    hass.config_entries.async_entries.return_value = [entry, cm_entry]
    tasks: list = []

    def _hass_sched(coro, name=None, **_kw):
        t = asyncio.ensure_future(coro)
        tasks.append(t)
        return t

    hass.async_create_task = _hass_sched
    census = PersonCensus(hass, _StubCameraManager())  # type: ignore[arg-type]
    ble: dict = {"legs": []}
    census._resolve_ble_legs = lambda ts, direction: list(ble["legs"])
    legs: dict = {}
    census._resolve_face_legs = lambda stem: list(legs.get(stem, []))
    census_calls: list = []
    _reg, _evict = census.register_egress_face, census.evict_egress_face

    def _spy_reg(pid, ts, **kw):
        census_calls.append(("register", pid))
        return _reg(pid, ts, **kw)

    def _spy_evict(pid):
        census_calls.append(("evict", pid))
        return _evict(pid)

    census.register_egress_face = _spy_reg
    census.evict_egress_face = _spy_evict
    presence = _Presence(created_ts=(NOW - timedelta(days=1)).timestamp())
    nm = MagicMock()
    nm.async_notify = AsyncMock()
    cm = SimpleNamespace(coordinators={"presence": presence})
    db_rows: list = []
    real_log = db.log_entry_exit_event

    async def _spy_log(**kw):
        db_rows.append(dict(kw))
        return await real_log(**kw)

    db.log_entry_exit_event = _spy_log
    hass.data = {ura_const.DOMAIN: {
        "census": census, "database": db, "notification_manager": nm,
        "coordinator_manager": cm,
    }}
    fired: list = []
    hass.bus = MagicMock()
    hass.bus.async_fire = lambda topic, payload: fired.append((topic, payload))

    clock = _Clock(NOW)
    monkeypatch.setattr(tv.dt_util, "now", clock.now)
    monkeypatch.setattr(tv.dt_util, "utcnow", clock.utcnow)
    scheduled: list = []

    def _call_later(_hass, delay, cb):
        scheduled.append((delay, cb))
        return lambda: None

    monkeypatch.setattr(
        sys.modules["homeassistant.helpers.event"], "async_call_later", _call_later,
    )
    # Layer counters live in hass.data; start each test at zero.
    tracker = EgressDirectionTracker(hass)
    tracker._load_door_config()
    tracker._get_interior_cameras_near = lambda cam: [FOYER]
    ns = SimpleNamespace(
        db=db, hass=hass, census=census, tracker=tracker, legs=legs, ble=ble,
        states=states, fired=fired, clock=clock, scheduled=scheduled,
        presence=presence, nm=nm, cm_entry=cm_entry, census_calls=census_calls,
        db_rows=db_rows, tasks=tasks,
    )
    try:
        yield ns
    finally:
        for t in tasks:
            if not t.done():
                await t
        await db.stop_write_worker()


async def _cross(rig, egress, *, at, direction):
    """One crossing through the production entry point. ``direction`` picks
    where the foyer (interior) event lands: after (entry), before (exit) or
    none (ambiguous)."""
    rig.clock.t = at
    if direction == "exit":
        rig.clock.t = at - timedelta(seconds=3)
        rig.tracker._on_interior_state_change(_ev(FOYER))
        rig.clock.t = at
    before = len(rig.scheduled)
    rig.tracker._on_egress_state_change(_ev(egress))
    assert len(rig.scheduled) == before + 1
    delay, cb = rig.scheduled[-1]
    if direction == "entry":
        rig.clock.t = at + timedelta(seconds=2)
        rig.tracker._on_interior_state_change(_ev(FOYER))
    rig.clock.t = at + timedelta(seconds=delay)
    await cb(rig.clock.t)
    for _ in range(3):
        await asyncio.sleep(0)
    for t in list(rig.tracker._outcome_log_tasks) + list(rig.tasks):
        await t


def _rows(db):
    conn = sqlite3.connect(db.db_file)
    try:
        return [
            json.loads(a) for (a,) in conn.execute(
                "SELECT attrs_json FROM memory_episodes WHERE episode_type = ? ORDER BY id",
                (EPISODE,),
            )
        ]
    finally:
        conn.close()


def _titles(rig):
    return [c.kwargs["title"] for c in rig.nm.async_notify.await_args_list]


def _counters(rig):
    from custom_components.universal_room_automation.domain_coordinators import (
        signals,
    )

    c = signals.layer_counters(rig.hass)
    return {
        "named": c.edge_anchor_named, "truncated": c.edge_anchor_truncated,
        "pair_blocked": c.edge_anchor_pair_blocked, "error": c.edge_anchor_error,
    }


def _face(rig, slug, at, stem="front_door", home=True):
    rig.legs[stem] = [_leg(stem, slug, at + timedelta(seconds=5))]
    rig.states[f"person.{slug}"] = _state("home" if home else "not_home")


def _pairs(rig, value):
    rig.cm_entry.options = {ura_const.CONF_EGRESS_CONFUSABLE_PAIRS: value}


# --------------------------------------------------------------------------
# D1 verify (1): tracker exit + 0.6 face + own edge -> "Jaya arrived"
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exit_called_entry_named_arrived(rig):
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Jaya arrived"]
    payload = rig.fired[-1][1]
    assert payload["direction"] == "exit"
    assert payload["person_id"] == "jaya"
    assert payload["identity_confidence"] == 0.6
    assert rig.census_calls == [("evict", "jaya")]
    rec = rig.tracker.get_last_crossing()
    assert rec.direction == "exit"
    assert rec.person_id == "jaya" and rec.identity_confidence == 0.6
    assert rec.provenance == "face"
    assert rec.identity_role == "arrival_edge_anchored"
    assert rec.nameable == (("jaya", 0.75),)
    assert rig.db_rows[-1]["direction"] == "exit"
    assert rig.db_rows[-1]["person_id"] == "jaya"
    assert _rows(rig.db)[-1]["edge_anchor"] == {"slug": "jaya", "lead_s": 120.0}
    assert _counters(rig)["named"] == 1


@pytest.mark.asyncio
async def test_entry_named_from_someone(rig):
    """0.6 face on a tracker entry: today "Someone arrived" -> "Jaya arrived"."""
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=60))
    await _cross(rig, FRONT, at=NOW, direction="entry")
    assert _titles(rig) == ["Jaya arrived"]
    assert rig.census_calls == [("register", "jaya")]


# (2) partner edge blocks
@pytest.mark.asyncio
async def test_partner_edge_blocks(rig):
    _pairs(rig, "jaya|ezinne")
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    rig.presence.add("person.ezinne", NOW - timedelta(seconds=90))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Someone left"]
    assert _counters(rig)["pair_blocked"] == 1
    assert _counters(rig)["named"] == 0
    assert rig.tracker.get_last_crossing().identity_role is None
    assert _rows(rig.db)[-1]["edge_anchor"] is None


@pytest.mark.asyncio
async def test_pair_guard_both_pairs_first_name_resolves(rig):
    """Operator value ``jaya|ezinne, jaya|oji``: ``oji`` resolves through the
    face first-name mapper to ``oji_udezue``, so Oji's edge blocks Jaya, and
    the pair is symmetric (Jaya's edge blocks an Oji face)."""
    _pairs(rig, "jaya|ezinne, jaya|oji")
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    rig.presence.add("person.oji_udezue", NOW - timedelta(seconds=30))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig)[-1] == "Someone left"

    t2 = NOW + timedelta(minutes=30)
    rig.legs.clear()
    _face(rig, "oji_udezue", t2, stem="garage_a")
    rig.presence.add("person.oji_udezue", t2 - timedelta(seconds=100))
    rig.presence.add("person.jaya", t2 - timedelta(seconds=50))
    await _cross(rig, GARAGE, at=t2, direction="exit")
    assert _titles(rig)[-1] == "Someone left"
    assert _counters(rig)["pair_blocked"] == 2


def test_parse_pairs_invalid_ignored(rig, caplog):
    census = rig.census
    got = rig.tracker._parse_confusable_pairs(
        "jaya|ezinne, jaya|oji, bad, a|b|c, jaya|jaya, |x", census)
    assert got == [("jaya", "ezinne"), ("jaya", "oji_udezue")]
    assert "ignoring 'bad'" in caplog.text


# (3) BLE-only never anchors; (3b) ble+face anchors
@pytest.mark.asyncio
async def test_ble_only_never_anchors(rig):
    rig.ble["legs"] = [SimpleNamespace(person_slug="jaya", transition_ts=NOW)]
    rig.census.ble_tracker_slug_map = lambda: {
        "a": "jaya", "b": "oji_udezue", "c": "ezinne"}
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    payload = rig.fired[-1][1]
    assert payload["identity_provenance"] == "ble"  # the attach happened
    assert _titles(rig) == ["Someone left"]  # 0.72 < 0.75, no anchor
    assert _counters(rig)["named"] == 0


@pytest.mark.asyncio
async def test_ble_face_anchors(rig):
    rig.ble["legs"] = [SimpleNamespace(person_slug="jaya", transition_ts=NOW)]
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert rig.fired[-1][1]["identity_provenance"] == "ble+face"
    assert _titles(rig) == ["Jaya arrived"]
    assert rig.fired[-1][1]["identity_confidence"] == 0.95


@pytest.mark.parametrize("prov,expect", [
    ("ble", None), ("vision", None), (None, None), ("face", "jaya"), ("ble+face", "jaya"),
])
def test_provenance_gate_direct(rig, prov, expect):
    """The provenance rule itself (INV-ANCHOR-OWN-EVIDENCE (i)), driven on the
    method that contains it with face evidence present: only face / ble+face."""
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    res = tv.EgressResolution(
        outcome="attached", direction="exit", agreement="single", slug="jaya",
        identity_confidence=0.6, provenance=prov, face_tier=0.6, live_face_legs=1,
    )
    got = rig.tracker._compute_edge_anchor("exit", res, NOW)
    assert (got or {}).get("slug") == expect


# (4) window bounds (hard-coded literals: LEAD 300, upper 45)
@pytest.mark.asyncio
async def test_edge_before_window(rig):
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=301))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Someone left"]


@pytest.mark.asyncio
async def test_edge_at_lower_bound_anchors(rig):
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=300))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Jaya arrived"]


@pytest.mark.asyncio
async def test_edge_after_upper_bound_t_plus_46(rig):
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW + timedelta(seconds=46))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Someone left"]


@pytest.mark.asyncio
async def test_edge_at_upper_bound_t_plus_45_anchors(rig):
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW + timedelta(seconds=45))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Jaya arrived"]


@pytest.mark.asyncio
async def test_partner_edge_after_upper_bound_ignored(rig):
    _pairs(rig, "jaya|ezinne")
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    rig.presence.add("person.ezinne", NOW + timedelta(seconds=46))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Jaya arrived"]
    assert _counters(rig)["pair_blocked"] == 0


# (5) stale / boot / not counted / departure edges
@pytest.mark.asyncio
@pytest.mark.parametrize("kw", [
    {"stale": True}, {"boot": True}, {"counted": False}, {"counted": None},
    {"kind": "departure"},
])
async def test_stale_and_boot_edges_ignored(rig, kw):
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120), **kw)
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Someone left"]


@pytest.mark.asyncio
async def test_stale_partner_edge_does_not_block(rig):
    _pairs(rig, "jaya|ezinne")
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    rig.presence.add("person.ezinne", NOW - timedelta(seconds=90), stale=True)
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Jaya arrived"]


# (5b) truncated ring
@pytest.mark.asyncio
async def test_truncated_ring_no_anchor(rig):
    rig.presence.tracker.created_ts = (NOW - timedelta(seconds=100)).timestamp()
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=60))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Someone left"]
    assert _counters(rig)["truncated"] == 1
    trunc = [c for c in rig.presence.calls if c[0] == "trunc"]
    assert trunc == [("trunc", NOW.timestamp() - 300)]


# (6) vetoed
@pytest.mark.asyncio
async def test_vetoed_never_anchors(rig):
    _face(rig, "jaya", NOW, home=False)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Someone left"]
    assert rig.presence.calls == []


@pytest.mark.asyncio
async def test_ambiguous_never_anchors(rig):
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    await _cross(rig, FRONT, at=NOW, direction="ambiguous")
    assert _titles(rig) == []
    assert rig.presence.calls == []


@pytest.mark.asyncio
async def test_name_switch_off_never_anchors(rig, monkeypatch):
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    monkeypatch.setattr(rig.census, "egress_identity_enabled", lambda: False)
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Someone left"]
    assert rig.presence.calls == []


@pytest.mark.asyncio
async def test_synthetic_only_face_never_anchors(rig):
    from dataclasses import replace

    _face(rig, "jaya", NOW)
    rig.legs["front_door"] = [replace(rig.legs["front_door"][0], synthetic=True)]
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Someone left"]


@pytest.mark.asyncio
async def test_min_tier_knob_gates(rig, monkeypatch):
    """MIN_TIER raised to 0.75: a single 0.6 face leg no longer anchors."""
    monkeypatch.setattr(ura_const, "EGRESS_ARRIVAL_EDGE_MIN_TIER", 0.75)
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Someone left"]


# (8) non-confusable pair arriving together: the face names Oji
@pytest.mark.asyncio
async def test_non_confusable_pair_named(rig):
    _pairs(rig, "jaya|ezinne")
    _face(rig, "oji_udezue", NOW)
    rig.presence.add("person.oji_udezue", NOW - timedelta(seconds=100))
    rig.presence.add("person.jaya", NOW - timedelta(seconds=95))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Oji Udezue arrived"]


@pytest.mark.asyncio
async def test_other_persons_edge_never_anchors(rig):
    """Only S's OWN edge anchors: Ezinne's edge does not anchor a Jaya face."""
    _face(rig, "jaya", NOW)
    rig.presence.add("person.ezinne", NOW - timedelta(seconds=100))
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Someone left"]


# INV-SECURITY: bus / DB / census / record identity fields unchanged
@pytest.mark.asyncio
async def test_anchor_never_reaches_bus_db_census(rig, monkeypatch):
    async def run(lead, at):
        monkeypatch.setattr(ura_const, "EGRESS_ARRIVAL_EDGE_LEAD_S", lead)
        rig.legs.clear()
        _face(rig, "jaya", at)
        rig.presence.add("person.jaya", at - timedelta(seconds=120))
        n_calls = len(rig.census_calls)
        await _cross(rig, FRONT, at=at, direction="exit")
        bus = dict(rig.fired[-1][1])
        bus.pop("timestamp")
        db = dict(rig.db_rows[-1])
        rec = rig.tracker.get_last_crossing()
        ident = (rec.person_id, rec.provenance, rec.identity_confidence,
                 rec.direction, rec.confidence)
        return bus, db, rig.census_calls[n_calls:], ident, rec

    off = await run(0, NOW)
    on = await run(300, NOW + timedelta(minutes=30))
    assert on[0] == off[0]
    assert on[1] == off[1]
    assert on[2] == off[2] == [("evict", "jaya")]
    assert on[3] == off[3] == ("jaya", "face", 0.6, "exit", 0.8)
    assert off[4].identity_role is None and off[4].nameable == ()
    assert on[4].identity_role == "arrival_edge_anchored"


def test_edge_conf_below_security_bar():
    assert ura_const.EGRESS_ARRIVAL_EDGE_CONFIDENCE == 0.75
    assert ura_const.EGRESS_ARRIVAL_EDGE_CONFIDENCE < 0.9
    assert ura_const.CONSUMER_CLASS_MIN_CONFIDENCE["security"] == 0.9
    assert ura_const.EGRESS_ARRIVAL_EDGE_LEAD_S == 300
    assert ura_const.CONF_EGRESS_CONFUSABLE_PAIRS == "egress_confusable_pairs"
    assert ura_const.DEFAULT_EGRESS_CONFUSABLE_PAIRS == ""


@pytest.mark.asyncio
async def test_edge_read_raises_notice_unchanged(rig):
    _face(rig, "jaya", NOW)
    rig.presence.raise_on_read = True
    await _cross(rig, FRONT, at=NOW, direction="exit")
    assert _titles(rig) == ["Someone left"]
    assert _counters(rig)["error"] == 1
    assert rig.fired[-1][1]["person_id"] == "jaya"
    assert _rows(rig.db)[-1]["edge_anchor"] is None


# (7) INV-NOOP golden replay: LEAD 0 -> NM kwargs equal to develop's rule
GOLDEN = {
    # direction, identity_confidence -> develop's title (hand-derived from
    # _arrival_departure_notify @ ef6149950: name iff conf >= 0.75)
    ("entry", None): "Someone arrived", ("entry", 0.6): "Someone arrived",
    ("entry", 0.75): "Jaya arrived", ("entry", 0.9): "Jaya arrived",
    ("exit", None): "Someone left", ("exit", 0.6): "Someone left",
    ("exit", 0.75): "Jaya left", ("exit", 0.9): "Jaya left",
}


@pytest.mark.asyncio
async def test_lead_zero_noop_golden(rig, monkeypatch):
    monkeypatch.setattr(ura_const, "EGRESS_ARRIVAL_EDGE_LEAD_S", 0)
    at = NOW
    legs_for = {
        None: [],
        0.6: lambda t: [_leg("front_door", "jaya", t + timedelta(seconds=5))],
        0.75: lambda t: [
            _leg("front_door", "jaya", t + timedelta(seconds=4), device="a"),
            _leg("front_door", "jaya", t + timedelta(seconds=5), device="b")],
        0.9: lambda t: [
            _leg("front_door", "jaya", t + timedelta(seconds=4)),
            _leg("foyer", "jaya", t + timedelta(seconds=5))],
    }
    rig.states["person.jaya"] = _state("home")
    for direction in ("entry", "exit", "ambiguous"):
        for conf, mk in legs_for.items():
            at = at + timedelta(minutes=10)
            rig.legs.clear()
            if conf is not None:
                for leg in mk(at):
                    rig.legs.setdefault(leg.base_stem, []).append(leg)
            rig.presence.add("person.jaya", at - timedelta(seconds=60))
            n = len(rig.nm.async_notify.await_args_list)
            await _cross(rig, FRONT, at=at, direction=direction)
            calls = rig.nm.async_notify.await_args_list[n:]
            if direction == "ambiguous":
                assert calls == []
                continue
            assert len(calls) == 1
            kw = calls[0].kwargs
            assert kw["title"] == GOLDEN[(direction, conf)]
            assert kw["message"] == kw["title"]
            assert kw["coordinator_id"] == "presence"
            assert kw["severity"].name == "LOW"
            rec = rig.tracker.get_last_crossing()
            assert rec.identity_role is None and rec.nameable == ()
            assert _rows(rig.db)[-1]["edge_anchor"] is None
    assert rig.presence.calls == []


# --------------------------------------------------------------------------
# D2 trip-wire (nightly op over persisted rows)
# --------------------------------------------------------------------------


async def _episode(db, etype, attrs, at, ref):
    await db.log_memory_episode(
        node_id=ref, episode_type=etype, attrs=attrs, source_ref=ref,
        started_at=at.isoformat(), ended_at=at.isoformat(),
        window_dedup=False, dedup_source_ref=True,
    )


async def _flush(db):
    for _ in range(50):
        await asyncio.sleep(0.01)
        if db._write_queue.empty():
            break
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_tripwire_fires_on_zero_with_arrivals(rig, monkeypatch):
    fired: list = []

    async def _fake_fire(hass, kind, key, diagnosis="", remedy="", **kw):
        fired.append((kind, key, kw.get("severity"), diagnosis))
        return True

    from custom_components.universal_room_automation.domain_coordinators import (
        _stuck_signal_nm,
    )
    monkeypatch.setattr(_stuck_signal_nm, "fire_stuck_signal", _fake_fire)
    rig.db.hass.data = {ura_const.DOMAIN: {"egress_tracker": rig.tracker}}
    base = NOW - timedelta(days=6)
    await _episode(rig.db, EPISODE, {"outcome": "no_leg", "edge_anchor": None}, base, "o1")
    for i in range(3):
        await _episode(rig.db, "person_arrival", {
            "counted": True, "source_stale": False, "in_boot_window": False,
        }, base + timedelta(hours=i + 1), f"a{i}")
    await _flush(rig.db)
    assert await rig.db.run_egress_edge_anchor_tripwire() is True
    assert fired == [(
        "egress_edge_anchor_zero", ("house",), "HIGH",
        "Door arrival naming has not fired in 7 days although residents arrived 3 times.",
    )]
    from custom_components.universal_room_automation.nightly_maintenance import (
        nightly_cleanup_ops,
    )
    assert ("egress_edge_anchor_tripwire", "run_egress_edge_anchor_tripwire", {}) in (
        nightly_cleanup_ops())


@pytest.mark.asyncio
async def test_tripwire_quiet_without_arrivals(rig, monkeypatch):
    fired: list = []

    async def _fake_fire(hass, kind, key, diagnosis="", remedy="", **kw):
        fired.append(kind)
        return True

    from custom_components.universal_room_automation.domain_coordinators import (
        _stuck_signal_nm,
    )
    monkeypatch.setattr(_stuck_signal_nm, "fire_stuck_signal", _fake_fire)
    base = NOW - timedelta(days=6)
    await _episode(rig.db, EPISODE, {"outcome": "no_leg", "edge_anchor": None}, base, "o1")
    # two counted arrivals + one stale: 2 < 3
    for i, stale in enumerate((False, False, True)):
        await _episode(rig.db, "person_arrival", {
            "counted": True, "source_stale": stale, "in_boot_window": False,
        }, base + timedelta(hours=i + 1), f"a{i}")
    await _flush(rig.db)
    assert await rig.tracker.async_edge_anchor_tripwire(rig.db) is False
    # one more counted arrival -> 3 -> fires
    await _episode(rig.db, "person_arrival", {
        "counted": True, "source_stale": False, "in_boot_window": False,
    }, base + timedelta(hours=5), "a9")
    await _flush(rig.db)
    assert await rig.tracker.async_edge_anchor_tripwire(rig.db) is True
    # an anchored row in the window -> quiet
    await _episode(rig.db, EPISODE, {"outcome": "attached",
                                     "edge_anchor": {"slug": "jaya", "lead_s": 80.0}},
                   base + timedelta(hours=6), "o2")
    await _flush(rig.db)
    assert await rig.tracker.async_edge_anchor_tripwire(rig.db) is False
    assert fired == ["egress_edge_anchor_zero"]


@pytest.mark.asyncio
async def test_tripwire_quiet_before_s1_rows_cover_window(rig, monkeypatch):
    fired: list = []

    async def _fake_fire(hass, kind, key, diagnosis="", remedy="", **kw):
        fired.append(kind)
        return True

    from custom_components.universal_room_automation.domain_coordinators import (
        _stuck_signal_nm,
    )
    monkeypatch.setattr(_stuck_signal_nm, "fire_stuck_signal", _fake_fire)
    base = NOW - timedelta(days=6)
    await _episode(rig.db, EPISODE, {"outcome": "no_leg"}, base, "o0")  # pre-S1 row
    for i in range(4):
        await _episode(rig.db, "person_arrival", {
            "counted": True, "source_stale": False, "in_boot_window": False,
        }, base + timedelta(hours=i + 1), f"a{i}")
    await _flush(rig.db)
    assert await rig.tracker.async_edge_anchor_tripwire(rig.db) is False
    monkeypatch.setattr(ura_const, "EGRESS_ARRIVAL_EDGE_LEAD_S", 0)
    assert await rig.tracker.async_edge_anchor_tripwire(rig.db) is False
    assert fired == []


def test_layer_diagnostics_carry_edge_anchor_counters():
    from custom_components.universal_room_automation.domain_coordinators import (
        signals,
    )

    hass = SimpleNamespace(data={})
    for name in ("edge_anchor_named", "edge_anchor_truncated",
                 "edge_anchor_pair_blocked", "edge_anchor_error"):
        signals.count_layer_event(hass, name)
    c = signals.layer_counters(hass)
    assert (c.edge_anchor_named, c.edge_anchor_truncated,
            c.edge_anchor_pair_blocked, c.edge_anchor_error) == (1, 1, 1, 1)
