"""HOUSE-STATE step 1a D2: residency producer wiring (PresenceCoordinator).

Plan PLANNING_house_state_axes_step1.md rev 3 D2 / §A9 (A4-A8, A19, A20).
Every test drives the REAL PresenceCoordinator method that CONTAINS the
wire-in (``_handle_geofence_change``, ``async_teardown``,
``_apply_fan_interference_gate``, ``get_residents_home``) with real
``homeassistant.core.State`` objects; the clock is the coordinator's
injectable ``_residency_clock`` set to literal times.
"""

from __future__ import annotations

import asyncio
import ast
import hashlib
import pathlib
import textwrap
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

from custom_components.universal_room_automation import const as C
from custom_components.universal_room_automation.domain_coordinators import (
    presence as PR,
)
from custom_components.universal_room_automation.domain_coordinators.presence import (
    PresenceCoordinator,
)

class State:
    """Minimal immutable-enough HA State stand-in (entity_id, state,
    attributes, last_changed). Local on purpose: a legacy test file replaces
    ``homeassistant.core.State`` with a MagicMock at collection, which would
    poison these fixtures in a multi-file run (order-robustness, DoD 10)."""

    def __init__(self, entity_id, state, attributes=None, last_changed=None):
        from datetime import datetime as _dt, timezone as _tz

        self.entity_id = entity_id
        self.state = state
        self.attributes = dict(attributes or {})
        self.last_changed = last_changed or _dt.now(_tz.utc)


_URA = pathlib.Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"

OJI = "person.oji_udezue"
EZ = "person.ezinne_udezue"
KIOSK = "person.wall_kiosk"
T_SETUP = 1_000_000.0


class _Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class _FakeDB:
    def __init__(self, gate: asyncio.Event | None = None) -> None:
        self.rows: list[dict] = []
        self.gate = gate

    async def log_memory_episode(self, **kw):
        if self.gate is not None:
            await self.gate.wait()
        self.rows.append(kw)
        return 1


def _coord(*, tracked=(OJI, EZ), states=None, db=None, loop_tasks=True):
    hass = make_hass()
    st = dict(states or {})
    hass.states.get = lambda eid: st.get(eid)
    hass.states.async_all = MagicMock(return_value=[State(e, v) for e, v in st.items()
                                                    if e.startswith("person.")])
    hass.data = {C.DOMAIN: {}}
    if tracked is not None:
        hass.data[C.DOMAIN]["person_coordinator"] = SimpleNamespace(
            tracked_persons=list(tracked))
    if db is not None:
        hass.data[C.DOMAIN]["database"] = db
    if loop_tasks:
        hass.async_create_task = lambda coro: asyncio.get_running_loop().create_task(coro)
    coord = PresenceCoordinator(hass)
    coord._test_states = st
    coord._residency_clock = _Clock(T_SETUP)
    coord._setup_residency()
    coord.handle_geofence_event = lambda pid, zone: None
    return hass, coord, st


def _ev(entity_id, old, new, *, new_attrs=None):
    return SimpleNamespace(data={
        "entity_id": entity_id,
        "old_state": None if old is None else State(entity_id, old),
        "new_state": None if new is None else State(entity_id, new, new_attrs or {}),
    })


def _feed(coord, entity_id, old, new, at):
    """A live edge. A ``-> home`` edge carries a GPS ``source`` tracker that
    changed at the same instant (a real arrival, not a stale-source one)."""
    coord._residency_clock.t = at
    if new == "home" and old is not None:
        lc = datetime.fromtimestamp(at, tz=timezone.utc)
        src = f"device_tracker.{entity_id.split('.', 1)[1]}_gps"
        coord._test_states[src] = State(src, "home", last_changed=lc)
        coord._handle_geofence_change(SimpleNamespace(data={
            "entity_id": entity_id,
            "old_state": State(entity_id, old),
            "new_state": State(entity_id, new, {"source": src}, last_changed=lc),
        }))
        return
    coord._handle_geofence_change(_ev(entity_id, old, new))


# ============================================================================
# A4 / A5: the wire-in runs before every return, whatever the gates
# ============================================================================


@pytest.mark.asyncio
async def test_geofence_listener_feeds_tracker_before_returns():
    _hass, coord, _st = _coord()
    seen: list = []
    real_on_event = coord._residency.on_event

    def spy(pid, old, new, ts, **kw):
        seen.append((pid, old, new))
        return real_on_event(pid, old, new, ts, **kw)

    coord._residency.on_event = spy
    # Restore / add event (old_state None): the ledger is stamped restored.
    _feed(coord, OJI, None, "home", T_SETUP + 1)
    assert coord._residency.ledger[OJI] == ("home", T_SETUP + 1, True)
    assert list(coord._residency.recent) == []
    # Unavailable new state: the tracker still sees the event.
    _feed(coord, OJI, "home", "unavailable", T_SETUP + 2)
    assert seen == [(OJI, "home", "unavailable")]
    # A real arrival 20 min after a real departure, outside the boot window.
    _feed(coord, EZ, "home", "not_home", T_SETUP + 700)
    _feed(coord, EZ, "not_home", "home", T_SETUP + 700 + 1200)
    rec = coord._residency.recent[-1]
    assert (rec.kind, rec.person, rec.counted, rec.source_stale) == (
        "arrival", EZ, True, False)


@pytest.mark.asyncio
async def test_records_written_in_observation_mode(monkeypatch):
    db = _FakeDB()
    _hass, coord, _st = _coord(db=db)
    sent: list = []
    monkeypatch.setattr(PR, "async_dispatcher_send", lambda *a: sent.append(a))
    coord.observation_mode = True
    _feed(coord, OJI, "not_home", "home", T_SETUP + 2000)
    await asyncio.sleep(0)
    assert [r.kind for r in coord._residency.recent] == ["arrival"]
    assert [r["episode_type"] for r in db.rows] == ["person_arrival"]
    assert sent == []  # SIGNAL_PERSON_ARRIVING suppressed
    coord.observation_mode = False
    _feed(coord, OJI, "home", "not_home", T_SETUP + 2100)
    _feed(coord, OJI, "not_home", "home", T_SETUP + 3100)
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_records_written_during_boot_settle():
    db = _FakeDB()
    _hass, coord, _st = _coord(db=db)
    coord._boot_settle_done = False
    _feed(coord, EZ, "home", "not_home", T_SETUP + 5)
    await asyncio.sleep(0)
    assert [r.kind for r in coord._residency.recent] == ["departure"]
    assert [r["episode_type"] for r in db.rows] == ["person_departure"]


# ============================================================================
# A6: one memory row per record; teardown gathers, then nothing more
# ============================================================================


@pytest.mark.asyncio
async def test_memory_row_per_record_and_teardown_gather():
    gate = asyncio.Event()
    db = _FakeDB(gate)
    _hass, coord, _st = _coord(db=db)
    _feed(coord, OJI, "home", "not_home", T_SETUP + 1000)
    _feed(coord, OJI, "not_home", "home", T_SETUP + 3000)
    _feed(coord, OJI, "home", "home", T_SETUP + 3001)        # attribute: no row
    _feed(coord, OJI, "home", "unavailable", T_SETUP + 3002)  # no row
    await asyncio.sleep(0)
    assert db.rows == []                                      # held at the gate
    asyncio.get_running_loop().call_later(0.05, gate.set)
    await coord.async_teardown()
    assert [(r["episode_type"], r["node_id"]) for r in db.rows] == [
        ("person_departure", "oji_udezue"), ("person_arrival", "oji_udezue")]
    arrival = db.rows[1]["attrs"]
    assert arrival["counted"] is True and arrival["person"] == OJI
    assert db.rows[1]["started_at"] == datetime.fromtimestamp(
        T_SETUP + 3000, tz=timezone.utc).isoformat()
    # After teardown no further row is scheduled.
    _feed(coord, OJI, "home", "not_home", T_SETUP + 4000)
    await asyncio.sleep(0.01)
    assert len(db.rows) == 2


@pytest.mark.asyncio
async def test_persist_kill_switch_writes_no_row(monkeypatch):
    db = _FakeDB()
    _hass, coord, _st = _coord(db=db)
    monkeypatch.setattr(PR._ura_const, "RESIDENCY_EVENT_LOG_PERSIST", False)
    _feed(coord, OJI, "not_home", "home", T_SETUP + 2000)
    await asyncio.sleep(0)
    assert db.rows == []
    assert len(coord._residency.recent) == 1  # the RAM record still exists


# ============================================================================
# A7: writer-health registration (backed AND absence-exempt)
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(("house_rows", "paged"), [
    ([(10, "away")], False),          # away the whole window: suppressed
    ([(10, "home_day")], True),       # home the whole week: dead producer
])
async def test_writer_health_registration_backed_and_absence_exempt(
    house_rows, paged, real_schema_db,
):
    from test_memory_writer_health import _FakeURADatabase, _bind_method, _const, _house

    assert {"person_arrival", "person_departure"} <= C.MEMORY_EPISODE_TYPES
    run = _bind_method()
    counts = {t: 4 for t in _const().MEMORY_WRITER_BACKED_EPISODE_TYPES}
    counts["person_arrival"] = 0
    counts["person_departure"] = 0
    db = _FakeURADatabase(counts, house=_house(real_schema_db, house_rows))
    stats = await run(db, cadence_days=7, triggered_by="nightly")
    if paged:
        assert stats["zero_row_types"] == ["person_arrival", "person_departure"]
        assert len(db.anomaly_events) == 2
    else:
        assert stats["zero_row_types"] == []
        assert stats["absence_suppressed_types"] == ["person_arrival", "person_departure"]
        assert db.anomaly_events == []


# ============================================================================
# A8: residents_home = trust state minus phone-left-behind
# ============================================================================


def _registry(monkeypatch, plb: dict[str, str]):
    from homeassistant.helpers import entity_registry as er

    class _Reg:
        def async_get_entity_id(self, domain, platform, unique_id):
            return plb.get(unique_id)

    monkeypatch.setattr(er, "async_get", lambda hass: _Reg())


@pytest.mark.asyncio
async def test_residents_home_trust_and_phone_left_behind(monkeypatch):
    ez_plb = "binary_sensor.ura_ezinne_udezue_phone_left_behind"
    _registry(monkeypatch, {
        f"{C.DOMAIN}_person_ezinne_udezue_phone_left_behind": ez_plb})
    states = {OJI: State(OJI, "home"), EZ: State(EZ, "home"),
              KIOSK: State(KIOSK, "home"), ez_plb: State(ez_plb, "on")}
    hass, coord, st = _coord(states={})
    st.update(states)
    overruled = {OJI}

    class _PC:
        tracked_persons = [OJI, EZ]

        def effective_person_state(self, pid):
            if pid in overruled:
                return "not_home"  # BLE overrules a GPS home
            s = st.get(pid)
            return s.state if s else None

    hass.data[C.DOMAIN]["person_coordinator"] = _PC()
    # Oji: raw home, trust not_home -> out. Ezinne: phone left behind -> out.
    assert coord.get_residents_home() == frozenset()
    assert coord.get_residents_home_count() == 0
    st[ez_plb] = State(ez_plb, "off")
    assert coord.get_residents_home() == frozenset({EZ})
    overruled.clear()
    assert coord.get_residents_home() == frozenset({OJI, EZ})
    # Fail-open: unavailable / missing sensor counts the person home.
    st[ez_plb] = State(ez_plb, "unavailable")
    assert EZ in coord.get_residents_home()
    del st[ez_plb]
    assert EZ in coord.get_residents_home()


@pytest.mark.asyncio
async def test_residents_home_resident_set():
    """tracked_persons set -> only those; empty list -> every person.*;
    no person coordinator -> unresolved -> empty."""
    hass, coord, st = _coord(tracked=())
    st.update({OJI: State(OJI, "home"), KIOSK: State(KIOSK, "home")})
    hass.states.async_all = MagicMock(return_value=[st[OJI], st[KIOSK]])
    assert coord.get_residents_home() == frozenset({OJI, KIOSK})
    hass.data[C.DOMAIN]["person_coordinator"] = SimpleNamespace(tracked_persons=[OJI])
    assert coord.get_residents_home() == frozenset({OJI})
    del hass.data[C.DOMAIN]["person_coordinator"]
    assert coord.get_residents_home() == frozenset()


@pytest.mark.asyncio
async def test_resident_set_unresolved_records_flagged():
    hass, coord, _st = _coord(tracked=None)
    _feed(coord, KIOSK, "not_home", "home", T_SETUP + 5000)
    rec = coord._residency.recent[-1]
    assert rec.person == KIOSK and rec.resident_set_resolved is False
    assert coord.get_recent_resident_arrival(300, now_ts=T_SETUP + 5010) is None


@pytest.mark.asyncio
async def test_non_resident_ignored_with_tracked_persons():
    _hass, coord, _st = _coord()
    _feed(coord, KIOSK, "not_home", "home", T_SETUP + 5000)
    assert list(coord._residency.recent) == []


@pytest.mark.asyncio
async def test_source_stale_wired_from_person_source(monkeypatch):
    """A person reading home from a source tracker that did not change at
    the edge -> the record carries source_stale; the getter refuses it."""
    src = "device_tracker.ez_ipad"
    hass, coord, st = _coord()
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    st[src] = State(src, "home", last_changed=now - timedelta(seconds=4119))
    new = State(EZ, "home", {"source": src}, last_changed=now)
    coord._residency_clock.t = T_SETUP + 5000
    coord._handle_geofence_change(SimpleNamespace(data={
        "entity_id": EZ, "old_state": State(EZ, "not_home"), "new_state": new}))
    rec = coord._residency.recent[-1]
    assert rec.source_stale is True
    assert coord.get_recent_resident_arrival(300, now_ts=T_SETUP + 5010) is None
    st[src] = State(src, "home", last_changed=now)
    coord._residency_clock.t = T_SETUP + 6000
    coord._handle_geofence_change(SimpleNamespace(data={
        "entity_id": EZ, "old_state": State(EZ, "not_home"), "new_state": new}))
    assert coord._residency.recent[-1].source_stale is False
    assert coord.get_recent_resident_arrival(300, now_ts=T_SETUP + 6010).person == EZ


# ============================================================================
# A20: the fan gate closure delegates; parity with the _run_inference copy
# ============================================================================


def test_fan_gate_closure_delegates(monkeypatch):
    from test_fan_interference_gate_layer1 import _build, _seed_fan_suspect

    hass, coord, tracker = _build()
    _seed_fan_suspect(tracker, "a")
    pc = MagicMock()
    pc.get_persons_in_room = MagicMock(return_value=["Oji Udezue"])
    hass.data[C.DOMAIN] = {"person_coordinator": pc}
    tracker._ble_occupied = False
    asked: list = []

    def fake(name):
        asked.append(name)
        return True  # phone left behind

    monkeypatch.setattr(coord, "_phone_left_behind_on", fake)
    _gated, ladder = coord._apply_fan_interference_gate(["a"], 300)
    assert ladder.get("a") == "L3"
    assert "Oji Udezue" in asked
    monkeypatch.setattr(coord, "_phone_left_behind_on", lambda name: False)
    tracker._fan_interference_hold_until.clear()
    _gated, ladder = coord._apply_fan_interference_gate(["a"], 300)
    assert ladder.get("a") == "L1"


def _run_inference_closure_source() -> str:
    tree = ast.parse((_URA / "domain_coordinators" / "presence.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_inference":
            for sub in ast.walk(node):
                if isinstance(sub, ast.FunctionDef) and sub.name == "_phone_trustworthy":
                    return textwrap.dedent(ast.get_source_segment(
                        (_URA / "domain_coordinators" / "presence.py").read_text(), sub))
    raise AssertionError("closure not found")


@pytest.mark.parametrize("name", ["oji_udezue", "Ezinne Udezue"])
@pytest.mark.parametrize("case", ["on", "off", "unknown", "unavailable", "missing", "unregistered"])
def test_phone_left_behind_parity_with_run_inference_closure(monkeypatch, name, case):
    slug = name.lower().replace(" ", "_")
    uid = f"{C.DOMAIN}_person_{slug}_phone_left_behind"
    eid = f"binary_sensor.{C.DOMAIN}_{slug}_phone_left_behind"
    reg_map = {} if case == "unregistered" else {uid: eid}
    states = {} if case in ("missing", "unregistered") else {eid: State(eid, case)}

    class _Reg:
        def async_get_entity_id(self, domain, platform, unique_id):
            assert (domain, platform) == ("binary_sensor", C.DOMAIN)
            return reg_map.get(unique_id)

    from homeassistant.helpers import entity_registry as er

    monkeypatch.setattr(er, "async_get", lambda hass: _Reg())
    coord = object.__new__(PresenceCoordinator)
    coord.hass = SimpleNamespace(states=SimpleNamespace(get=states.get))
    ns = {"DOMAIN": C.DOMAIN, "_entity_reg": _Reg(), "self": coord}
    exec(_run_inference_closure_source(), ns)  # noqa: S102 — the real closure
    trustworthy = ns["_phone_trustworthy"](name)
    assert coord._phone_left_behind_on(name) is (not trustworthy)
    # Independent oracle: only a registered sensor reading "on" excludes.
    assert coord._phone_left_behind_on(name) is (case == "on")


# ============================================================================
# A19: INV-MACHINE (1a changes no line of the machine / inference / dispatch)
# ============================================================================

# ast.dump sha256 of develop @ 7d826060 (pre-1a), computed once from that tree
# with .venv-ha python 3.13 (ast.dump differs across Python versions).
_DEVELOP_HASHES = {
    "_run_inference": "bd0a187e30f76a15870f303213c622ebd14a3bed537f1ab6de19c3ffd4a20b35",
    "_dispatch_house_state_change": "720566e1cf4221c68e86729f5c7b16e43f1f15e25cf3f773fb73458da823c940",
    "house_state.py": "38749b0e8b0e596924b1e6201ac107ac671648eee17780af809850b00d067a08",
}


def _hash(node) -> str:
    return hashlib.sha256(ast.dump(node).encode()).hexdigest()


def test_run_inference_source_unchanged():
    tree = ast.parse((_URA / "domain_coordinators" / "presence.py").read_text())
    got = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in (
            "_run_inference", "_dispatch_house_state_change"
        ):
            got[node.name] = _hash(node)
    got["house_state.py"] = _hash(
        ast.parse((_URA / "domain_coordinators" / "house_state.py").read_text()))
    assert got == _DEVELOP_HASHES
