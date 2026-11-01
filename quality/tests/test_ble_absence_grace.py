"""BLE-LOCATION-QUALITY-1 D1 — BLE absence grace (one per BLE-only episode).

Plan: docs/planning/PLANNING_ble_rearm_and_fleet_fraction.md rev 2 §1.3-1.8.

Falsifiable invariant I-D1 (rev 2): (a) BLE (present or absent) can make a
room occupied on tick t only if it was occupied on tick t-1; (b) within one
BLE-only hold episode at most ONE absent stretch is bridged, for at most
BLE_ABSENCE_GRACE_S; (c) no grace survives the hold cap, the failsafe
latch, Override Vacant or a fan-recheck release.

Authority: every test executes REAL production code — the BLE block and the
episode-end regions are compiled from coordinator.py and exec'd (the same
technique as test_ble_extend_not_create / test_ble_hold_cap), the helpers
`_ble_absence_grace_applies` / `_ble_hold_cap_exceeded` /
`apply_fan_recheck_release` / `_async_log_occupancy_edge` are the real
`UniversalRoomCoordinator` methods. Boundaries are hard-coded literals
(89 / 90 / 91 s), never the imported constant. Oracles are hand-derived.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import _provenance_harness  # noqa: F401  — mocks homeassistant
from _provenance_harness import make_hass
from _ura_const_support import ensure_ura_const, ensure_ura_signals  # noqa: E402

ensure_ura_const()
ensure_ura_signals()

from custom_components.universal_room_automation.const import (  # noqa: E402
    DOMAIN,
    STATE_BLE_PERSONS,
    STATE_OCCUPANCY_SOURCE,
    STATE_OCCUPIED,
    STATE_TIMEOUT_REMAINING,
)
from test_ble_extend_not_create import (  # noqa: E402
    _FakeSelf,
    _make_person_coord,
    _run_ble_block,
    _run_camera_block,
)

_COORD_SRC = (
    Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation" / "coordinator.py"
)
ROOM = "Jaya Bedroom"
T0 = datetime(2026, 10, 28, 6, 30, 0)
GRACE_KEY = "ble_absence_grace"


def _cm():
    return importlib.import_module(
        "custom_components.universal_room_automation.coordinator"
    )


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class _World:
    """A BLE-held room: a real-method shim + a person coordinator whose
    answer the test flips per tick + captured async_create_task calls."""

    def __init__(self, room_type="bedroom"):
        self.hass = make_hass()
        self.tasks: list = []

        def _capture(coro, *a, **kw):
            self.tasks.append(getattr(coro, "__name__", repr(coro)))
            try:
                coro.close()
            except Exception:  # noqa: BLE001
                pass
            return MagicMock()

        self.hass.async_create_task = _capture
        self.persons = {ROOM: []}
        self.hass.data[DOMAIN] = {
            "person_coordinator": _make_person_coord(self.persons, {ROOM}),
        }
        self.s = _FakeSelf(self.hass, occupancy_timeout=300)
        self.s._room_type = room_type
        self.db = MagicMock()
        self.db.log_occupancy_event = AsyncMock()
        self.s.entry = MagicMock()
        self.s.entry.entry_id = "E_JAYA"

    def held_by_ble(self, since=T0, became=None):
        """State after a BLE-only admit: chain unbroken, anchor set."""
        self.s._last_occupied_state = True
        self.s._ble_only_hold_since = since
        self.s._became_occupied_time = became or since - timedelta(minutes=20)
        self.s._last_motion_time = since - timedelta(minutes=5)
        return self

    def tick(self, now, present: bool) -> dict:
        """One room tick: the real BLE block, the real occupancy_events
        writer, then the real TRUE VACANCY FINALIZE region, then the late
        `_last_occupied_state` update (as `_async_update_data` does)."""
        self.persons[ROOM] = ["jaya"] if present else []
        data = {STATE_OCCUPIED: False, STATE_OCCUPANCY_SOURCE: "none"}
        _run_ble_block(self.s, data, now, ROOM)
        was = self.s._last_occupied_state
        _run(_cm().UniversalRoomCoordinator._async_log_occupancy_edge(
            self.s, self.db, data, was, now,
        ))
        _exec_region(_TRUE_VACANCY, self.s, {"data": data})
        self.s._last_occupied_state = bool(data[STATE_OCCUPIED])
        return data

    def exit_rows(self):
        return [c for c in self.db.log_occupancy_event.await_args_list
                if c.args[1] == "exit"]

    def entry_rows(self):
        return [c for c in self.db.log_occupancy_event.await_args_list
                if c.args[1] == "entry"]


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _region(start: str, end: str, *, prefix: str = "", dedent: int = 8):
    src = _COORD_SRC.read_text(encoding="utf-8")
    i = src.index(start)
    j = src.index(end, i + len(start))
    out = []
    for ln in src[i:j].splitlines():
        if ln.startswith(" " * dedent):
            out.append(ln[dedent:])
        elif not ln.strip():
            out.append("")
        else:
            out.append(ln)
    return compile(prefix + "\n".join(out), str(_COORD_SRC), "exec")


_TRUE_VACANCY = _region(
    "# === TRUE VACANCY FINALIZE (P24 fix",
    "# === Phase 1: Environmental Sensors ===",
)
_OVERRIDE_VACANT = _region(
    "        elif self._is_override_vacant():",
    "        # === HVAC fast occupancy response (v5.103.20)",
    prefix="if False:\n    pass\n",
    dedent=8,
)
_SKIP_FIRST = _region(
    "        if self._skip_first_automation:\n",
    '            _LOGGER.info(\n                "Room %s: First refresh',
)
# Primary Tier-1 body branch (same region test_ble_hold_cap drives).
_BODY_SRC = _COORD_SRC.read_text(encoding="utf-8")
_bi = _BODY_SRC.index("elif any_sensor_active:")
_bj = _BODY_SRC.index(
    "            # Update last occupied time when becoming occupied", _bi,
)
_BODY = compile(
    "if True:\n" + "\n".join(
        "    " + (ln[8:] if ln.startswith("        ") else ln.strip())
        for ln in _BODY_SRC[_bi:_bj].splitlines()[1:]
    ),
    str(_COORD_SRC), "exec",
)


def _exec_region(code, s, extra: dict):
    ns = {
        "self": s, "now": extra.pop("now", T0),
        "STATE_OCCUPIED": STATE_OCCUPIED,
        "STATE_OCCUPANCY_SOURCE": STATE_OCCUPANCY_SOURCE,
        "STATE_TIMEOUT_REMAINING": STATE_TIMEOUT_REMAINING,
        "room_name": ROOM,
        "_LOGGER": logging.getLogger("ble_grace_test"),
    }
    ns.update(extra)
    exec(code, ns)
    return ns


def _body_fire(w: _World, now):
    """Run the REAL primary body branch (a motion fire)."""
    w.s._last_bit = None
    w.s._last_motion_bit_time = None
    w.s._last_pir_motion_time = None
    data = {}
    _exec_region(_BODY, w.s, {
        "now": now, "data": data, "motion_detected": True,
        "motion_witness_detected": True, "presence_detected": False,
    })
    w.s._last_occupied_state = True
    return data


def _spent_episode(w: _World):
    """Grace used and open: the episode-end sites must clear all three."""
    w.held_by_ble()
    w.s._ble_absent_since = T0 + timedelta(seconds=10)
    w.s._ble_grace_used = True


# ---------------------------------------------------------------------------
# D1.1 core behaviour
# ---------------------------------------------------------------------------


def test_single_empty_tick_holds_ble_chain():
    """The 10-28 06:34 shape: BLE-only hold, ONE empty read -> still held,
    flagged, no exit row, then the person is back. Discriminator: with the
    grace off (develop behaviour) the same input exits and writes a row."""
    w = _World().held_by_ble()
    d = w.tick(T0 + timedelta(seconds=30), present=False)
    assert d[STATE_OCCUPIED] is True
    assert d[STATE_OCCUPANCY_SOURCE] == "ble"
    assert d[GRACE_KEY] is True
    assert d[STATE_BLE_PERSONS] == []
    assert d[STATE_TIMEOUT_REMAINING] == 300
    d = w.tick(T0 + timedelta(seconds=60), present=True)
    assert d[STATE_OCCUPIED] is True and GRACE_KEY not in d
    assert w.db.log_occupancy_event.await_count == 0


def test_single_empty_tick_exits_without_grace(monkeypatch):
    """Discriminating twin of the test above: BLE_ABSENCE_GRACE_S = 0 is
    develop's behaviour -> exit edge + exactly one exit row."""
    monkeypatch.setattr(_cm(), "BLE_ABSENCE_GRACE_S", 0)
    w = _World().held_by_ble()
    d = w.tick(T0 + timedelta(seconds=30), present=False)
    assert d[STATE_OCCUPIED] is False
    assert len(w.exit_rows()) == 1


@pytest.mark.parametrize("secs,held", [(89, True), (90, False), (91, False)])
def test_grace_window_boundary_literal(secs, held):
    """First empty read at T0+30; held strictly below 90 s from it."""
    w = _World().held_by_ble()
    first = T0 + timedelta(seconds=30)
    assert w.tick(first, present=False)[STATE_OCCUPIED] is True
    d = w.tick(first + timedelta(seconds=secs), present=False)
    assert d[STATE_OCCUPIED] is held


def test_grace_expires_at_bound_writes_one_exit_row():
    w = _World().held_by_ble()
    first = T0 + timedelta(seconds=30)
    for off in (0, 30, 60):
        assert w.tick(first + timedelta(seconds=off), False)[STATE_OCCUPIED]
    d = w.tick(first + timedelta(seconds=90), present=False)
    assert d[STATE_OCCUPIED] is False and GRACE_KEY not in d
    assert len(w.exit_rows()) == 1
    # Exit row duration = seconds since _last_motion_time (untouched by
    # grace): motion at T0-300 -> exit at T0+120 -> 420 s.
    assert w.exit_rows()[0].args[3] == 420
    # Vacant afterwards; later absent ticks write nothing more.
    w.tick(first + timedelta(seconds=120), present=False)
    assert len(w.exit_rows()) == 1
    assert w.entry_rows() == []


def test_grace_never_creates_from_vacant():
    """I-D1(a): a vacant room never becomes occupied via BLE, absent or
    present, even with a stale anchor left behind."""
    w = _World()
    w.s._last_occupied_state = False
    w.s._ble_only_hold_since = T0 - timedelta(minutes=3)
    for i, present in enumerate([False, True, False, True, False]):
        d = w.tick(T0 + timedelta(seconds=30 * i), present)
        assert d[STATE_OCCUPIED] is False
    assert w.db.log_occupancy_event.await_count == 0


def test_grace_requires_ble_only_anchor():
    """Room held by motion (anchor None) + BLE empty -> no grace: today's
    behaviour (exit), and no grace is spent."""
    w = _World()
    w.s._last_occupied_state = True
    w.s._ble_only_hold_since = None
    w.s._became_occupied_time = T0 - timedelta(minutes=2)
    d = w.tick(T0, present=False)
    assert d[STATE_OCCUPIED] is False
    assert w.s._ble_grace_used is False


@pytest.mark.parametrize("room_type,anchor_age,held", [
    ("bathroom", 7201, False),   # cap on, exceeded
    ("bathroom", 3600, True),    # cap on, within
    ("bedroom", 7201, True),     # cap default off
])
def test_grace_respects_hold_cap(room_type, anchor_age, held):
    w = _World(room_type=room_type)
    w.held_by_ble(since=T0 - timedelta(seconds=anchor_age))
    d = w.tick(T0, present=False)
    assert d[STATE_OCCUPIED] is held


def test_grace_branch_never_fires_cap_nm_or_moves_anchor():
    """No NM from the grace branch, even on the tick the cap is exceeded;
    anchor / session / motion clocks untouched by a grace tick."""
    w = _World(room_type="bathroom")
    anchor = T0 - timedelta(seconds=3600)
    w.held_by_ble(since=anchor)
    became = w.s._became_occupied_time
    motion = w.s._last_motion_time
    d = w.tick(T0, present=False)
    assert d[GRACE_KEY] is True
    assert w.s._ble_only_hold_since == anchor
    assert w.s._became_occupied_time == became
    assert w.s._last_motion_time == motion
    assert w.tasks == []
    # Cap exceeded while absent: refused, still no NM from this branch.
    w2 = _World(room_type="bathroom")
    w2.held_by_ble(since=T0 - timedelta(seconds=7201))
    w2.tick(T0, present=False)
    assert w2.tasks == []
    # Contrast: the PRESENT branch does own the cap NM.
    w3 = _World(room_type="bathroom")
    w3.held_by_ble(since=T0 - timedelta(seconds=7201))
    w3.tick(T0, present=True)
    assert w3.tasks == ["_fire_ble_hold_cap_nm"]


def test_present_tick_resets_absence_stamp():
    w = _World().held_by_ble()
    w.tick(T0 + timedelta(seconds=30), present=False)
    assert w.s._ble_absent_since == T0 + timedelta(seconds=30)
    assert w.s._ble_grace_used is True
    w.tick(T0 + timedelta(seconds=60), present=True)
    assert w.s._ble_absent_since is None
    assert w.s._ble_grace_used is True


def test_intermittent_bleed_does_not_chain_grace():
    """HIGH-1: absent, present, absent, present ... in ONE episode -> the
    second absent tick exits. (Develop exits on the first: see
    test_single_empty_tick_exits_without_grace.)"""
    w = _World().held_by_ble()
    seq = [False, True, False, True, False]
    occ = [w.tick(T0 + timedelta(seconds=30 * (i + 1)), p)[STATE_OCCUPIED]
           for i, p in enumerate(seq)]
    assert occ == [True, True, False, False, False]
    assert len(w.exit_rows()) == 1


def test_grace_used_resets_only_on_episode_end():
    """A present tick does not reset `_ble_grace_used`; an episode end
    (real true-vacancy region) does, and the next BLE-only episode (after a
    real body fire + BLE admit) gets its own grace."""
    w = _World().held_by_ble()
    w.tick(T0 + timedelta(seconds=30), False)       # grace opens
    w.tick(T0 + timedelta(seconds=60), True)        # closes, still used
    assert w.s._ble_grace_used is True
    assert w.tick(T0 + timedelta(seconds=90), False)[STATE_OCCUPIED] is False
    # TRUE VACANCY FINALIZE ran inside tick(): episode ended.
    assert w.s._ble_grace_used is False
    assert w.s._ble_only_hold_since is None
    # New episode: body fire, then a BLE-only admit, then one empty read.
    _body_fire(w, T0 + timedelta(seconds=600))
    w.s._became_occupied_time = T0 + timedelta(seconds=600)
    assert w.tick(T0 + timedelta(seconds=900), True)[STATE_OCCUPIED] is True
    assert w.s._ble_only_hold_since == T0 + timedelta(seconds=900)
    d = w.tick(T0 + timedelta(seconds=930), False)
    assert d[STATE_OCCUPIED] is True and d[GRACE_KEY] is True


def test_grace_key_absent_on_non_grace_ticks():
    w = _World().held_by_ble()
    d = w.tick(T0 + timedelta(seconds=30), True)    # present admit
    assert GRACE_KEY not in d
    d = w.tick(T0 + timedelta(seconds=60), False)   # grace
    assert d[GRACE_KEY] is True
    d = w.tick(T0 + timedelta(seconds=150), False)  # expired
    assert GRACE_KEY not in d


@pytest.mark.parametrize("knob,value", [
    ("BLE_ABSENCE_GRACE_S", 0),
    ("BLE_CHAIN_HOLD_ENABLED", False),
])
def test_grace_zero_is_kill_switch(monkeypatch, knob, value):
    """0 = off: exit exactly as develop, no field is touched."""
    monkeypatch.setattr(_cm(), knob, value)
    w = _World().held_by_ble()
    d = w.tick(T0 + timedelta(seconds=30), present=False)
    assert d[STATE_OCCUPIED] is False
    assert GRACE_KEY not in d
    assert w.s._ble_absent_since is None


def test_failsafe_latch_blocks_grace():
    """I-D1(c): the block's outer guard - a latched failsafe gets no grace."""
    w = _World().held_by_ble()
    w.s._failsafe_fired = True
    d = w.tick(T0 + timedelta(seconds=30), present=False)
    assert d[STATE_OCCUPIED] is False
    assert w.s._ble_grace_used is False


# ---------------------------------------------------------------------------
# Episode end — every site that clears `_ble_only_hold_since` clears both
# grace fields (paired clears). D2 demotion is anchored in
# test_occupancy_source_follows_capability.py
# (test_d2_demotion_ends_ble_only_episode); camera also in
# test_ble_extend_not_create.py::test_camera_block_unchanged_by_this_cycle.
# ---------------------------------------------------------------------------


def _clear_body_fire(w):
    _body_fire(w, T0 + timedelta(seconds=20))


def _clear_camera(w):
    cam = MagicMock()
    cam.get_person_sensor_for_area = MagicMock(return_value=["binary_sensor.c"])
    w.hass.data[DOMAIN]["camera_manager"] = cam
    w.hass.states.get = MagicMock(return_value=MagicMock(state="on"))
    w.s._get_room_area = lambda: "jaya_bedroom"
    data = {STATE_OCCUPIED: False}
    _run_camera_block(w.s, data, T0 + timedelta(seconds=20), ROOM)
    assert data[STATE_OCCUPANCY_SOURCE] == "camera"


def _clear_true_vacancy(w):
    _exec_region(_TRUE_VACANCY, w.s, {"data": {STATE_OCCUPIED: False}})


def _clear_override_vacant(w):
    w.s._is_override_vacant = lambda: True
    w.s._last_occupied_since_for_handler = None
    data = {STATE_OCCUPIED: True}
    _exec_region(_OVERRIDE_VACANT, w.s, {"data": data})
    assert data[STATE_OCCUPIED] is False


def _clear_skip_first(w):
    w.s._skip_first_automation = True
    w.s._last_occupied_since_for_handler = None
    _exec_region(_SKIP_FIRST, w.s, {
        "data": {STATE_OCCUPIED: False, STATE_OCCUPANCY_SOURCE: "none"},
    })


def _clear_recheck_release(w):
    w.s.data = {STATE_OCCUPIED: True}
    w.s._hvac_evidence_active = True
    w.s._last_occupied_since_for_handler = None
    w.hass.data = {}
    _cm().UniversalRoomCoordinator.apply_fan_recheck_release(w.s)
    assert w.s._last_occupied_state is False


@pytest.mark.parametrize("site", [
    _clear_body_fire, _clear_camera, _clear_true_vacancy,
    _clear_override_vacant, _clear_skip_first, _clear_recheck_release,
], ids=["body_fire", "camera", "true_vacancy", "override_vacant",
        "skip_first", "recheck_release"])
def test_override_vacant_and_recheck_release_clear_stamp(site):
    w = _World()
    _spent_episode(w)
    site(w)
    assert w.s._ble_only_hold_since is None
    assert w.s._ble_absent_since is None
    assert w.s._ble_grace_used is False


def test_recheck_release_then_absent_tick_gets_no_grace():
    """I-D1(c): after a fan-recheck release the chain is broken out of
    band, so the next empty tick cannot grace (and nothing re-creates)."""
    w = _World().held_by_ble()
    _clear_recheck_release(w)
    w.hass.data = {DOMAIN: {
        "person_coordinator": _make_person_coord(w.persons, {ROOM}),
    }}
    d = w.tick(T0 + timedelta(seconds=30), present=False)
    assert d[STATE_OCCUPIED] is False


def test_override_vacant_mid_grace_ends_it():
    """Override Vacant on a grace tick forces vacant and ends the episode;
    the next empty tick has a broken chain -> no grace."""
    w = _World().held_by_ble()
    d = w.tick(T0 + timedelta(seconds=30), present=False)
    assert d[GRACE_KEY] is True
    _clear_override_vacant(w)
    assert w.s._last_occupied_state is False
    d = w.tick(T0 + timedelta(seconds=60), present=False)
    assert d[STATE_OCCUPIED] is False


# ---------------------------------------------------------------------------
# Helper-level (real method on a bare coordinator instance)
# ---------------------------------------------------------------------------


def _bare():
    cm = _cm()
    c = object.__new__(cm.UniversalRoomCoordinator)
    entry = MagicMock()
    entry.data = {"room_name": ROOM, "room_type": "bedroom"}
    entry.options = {}
    object.__setattr__(c, "entry", entry)
    object.__setattr__(c, "_room_type", "bedroom")
    object.__setattr__(c, "_last_occupied_state", True)
    object.__setattr__(c, "_ble_only_hold_since", T0)
    object.__setattr__(c, "_ble_absent_since", None)
    object.__setattr__(c, "_ble_grace_used", False)
    return c


def test_helper_opens_grace_once_per_episode():
    c = _bare()
    now = T0 + timedelta(seconds=30)
    assert c._ble_absence_grace_applies(now) is True
    assert c._ble_absent_since == now and c._ble_grace_used is True
    # Same open grace, later tick within the window: still True, stamp kept.
    assert c._ble_absence_grace_applies(now + timedelta(seconds=60)) is True
    assert c._ble_absent_since == now
    # Closed by a present read (simulated), grace spent -> False.
    c._ble_absent_since = None
    assert c._ble_absence_grace_applies(now + timedelta(seconds=120)) is False
    assert c._ble_absent_since is None


def test_cap_helper_fail_open_and_exceeded():
    c = _bare()
    c._room_type = "bathroom"
    c._ble_only_hold_since = T0 - timedelta(seconds=7201)
    exceeded, dur, cap = c._ble_hold_cap_exceeded(T0)
    assert (exceeded, dur, cap) == (True, 7201.0, 7200)
    c._ble_only_hold_since = None
    assert c._ble_hold_cap_exceeded(T0) == (False, 0.0, 0)
    c._ble_only_hold_since = T0 - timedelta(seconds=7201)
    c._room_type = "bedroom"
    assert c._ble_hold_cap_exceeded(T0)[0] is False


def test_init_seeds_grace_fields():
    """The REAL `__init__` seeds both fields (a restart starts at None /
    False); without them the first absent tick would raise."""
    import homeassistant.helpers.frame as _frame
    from unittest.mock import patch

    hass = MagicMock()
    hass.data = {}
    entry = MagicMock()
    entry.data = {"room_name": ROOM, "room_type": "bedroom"}
    entry.options = {}
    entry.entry_id = "E1"
    with patch.object(_frame, "report_usage", lambda *a, **k: None):
        c = _cm().UniversalRoomCoordinator(hass, entry)
    assert c._ble_absent_since is None
    assert c._ble_grace_used is False
    assert c._ble_only_hold_since is None
