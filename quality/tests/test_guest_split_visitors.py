"""GUEST-MODE-SPLIT-VISITORS-1 D1 — binary_sensor visitors_present (display).

Plan: docs/planning/PLANNING_guest_mode_split_2026_11.md rev 4 §D1.

INV-VIS-1: D1 adds no gate call and changes no decision. Pinned by
test_display_only_golden (rule OFF reproduces the base-tree golden: gate call
counts, guest_armed, reason, confidence, infer result) and
test_gate_call_counts_unchanged (rule ON: still exactly one call of each gate
per HOME_* tick, as on base).

Drives the REAL _run_inference (guest_split_harness.World). Local zone UTC.
"""
from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import guest_split_harness as H

HS = H.HS
GOLDEN = Path(__file__).parent / "fixtures" / "guest_split_golden_base.json"
DAY = datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)


def _world(monkeypatch, state=HS.HOME_DAY, at=DAY):
    H.install_clock(monkeypatch, at)
    return H.World(monkeypatch, state=state)


def test_display_only_golden(monkeypatch):
    """Rule OFF -> every base-golden field identical, and visitors_present is
    on exactly when (house GUEST at tick start) or room gate or cam gate."""
    rows = json.loads(GOLDEN.read_text())["rows"]
    for row in rows:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(H.CONST, "GUEST_NIGHT_STAY_RULE_ENABLED", False)
            got = H.run_tuple(mp, tuple(row["tuple"]))
        assert got == row, row["tuple"]


def test_gate_call_counts_unchanged(monkeypatch):
    """Rule ON (default): one call of each gate per HOME_* tick, one room-gate
    call per GUEST tick, none elsewhere (same counts as base)."""
    expected = {
        HS.HOME_DAY: {"room": 1, "unid": 1},
        HS.HOME_EVENING: {"room": 1, "unid": 1},
        HS.HOME_NIGHT: {"room": 1, "unid": 1},
        HS.GUEST: {"room": 1, "unid": 0},
        HS.SLEEP: {"room": 0, "unid": 0},
        HS.AWAY: {"room": 0, "unid": 0},
    }
    for state, calls in expected.items():
        with pytest.MonkeyPatch.context() as mp:
            w = _world(mp, state=state)
            w.tick()
            assert w.gate_calls == calls, state


def test_room_leg(monkeypatch):
    """45 min unknown in a guest room, no stay: on, legs.room, house HOME_DAY."""
    w = _world(monkeypatch).guest_room(45)
    assert w.tick() == HS.HOME_DAY
    assert w.coord._visitors_present is True
    assert w.coord._visitors_legs == {"room": True, "cam": False, "stay": False}


def test_cam_leg(monkeypatch):
    """Path A armed (2 unidentified, high confidence, 400 s >= 300 s): on,
    legs.cam, house HOME_DAY."""
    w = _world(monkeypatch).unidentified(2, "high", 400)
    assert w.tick() == HS.HOME_DAY
    assert w.coord._visitors_present is True
    assert w.coord._visitors_legs == {"room": False, "cam": True, "stay": False}


def test_cam_leg_const_off(monkeypatch):
    """VISITORS_CAM_LEG_ENABLED False -> legs.cam False, off."""
    monkeypatch.setattr(H.CONST, "VISITORS_CAM_LEG_ENABLED", False)
    w = _world(monkeypatch).unidentified(2, "high", 400)
    w.tick()
    assert w.coord._visitors_legs["cam"] is False
    assert w.coord._visitors_present is False


def test_stay_leg(monkeypatch):
    """Stay latch on in SLEEP (no gates evaluated there): on via legs.stay."""
    w = _world(monkeypatch, state=HS.SLEEP,
               at=datetime(2026, 11, 11, 2, 0, tzinfo=timezone.utc))
    w.coord._guest_stay_active = True
    w.tick()
    assert w.coord._visitors_legs == {"room": False, "cam": False, "stay": True}
    assert w.coord._visitors_present is True


def test_off_outside_home_guest(monkeypatch):
    """SLEEP / AWAY with an armed room shape and unidentified bodies: the
    gates are not evaluated there -> off."""
    for state, at in ((HS.SLEEP, datetime(2026, 11, 11, 2, 0, tzinfo=timezone.utc)),
                      (HS.AWAY, DAY)):
        with pytest.MonkeyPatch.context() as mp:
            w = _world(mp, state=state, at=at).guest_room(45)
            w.unidentified(2, "high", 400)
            w.coord._census_count = 0 if state == HS.AWAY else 2
            w.tick()
            assert w.coord._visitors_present is False, state


def test_switch_off_follows_guest_only(monkeypatch):
    """Guest detection OFF: legs all False; a GUEST override reads on."""
    w = _world(monkeypatch).guest_room(45).unidentified(2, "high", 400)
    w.coord._guest_detection_enabled = False
    w.coord._guest_stay_active = True
    w.tick()
    assert w.coord._visitors_legs == {"room": False, "cam": False, "stay": False}
    assert w.coord._visitors_present is False
    w.sm.set_override(HS.GUEST)
    w.tick()
    assert w.coord._visitors_present is True


def test_since_edge(monkeypatch):
    """since = UTC time of the last off -> on edge; kept while on; None off."""
    clock = H.install_clock(monkeypatch, DAY)
    w = H.World(monkeypatch, state=HS.HOME_DAY)
    w.tick()
    assert w.coord._visitors_since is None
    w.guest_room(45)
    w.tick()
    assert w.coord._visitors_since == "2026-11-10T14:00:00+00:00"
    clock.advance(60)
    w.tick()
    assert w.coord._visitors_since == "2026-11-10T14:00:00+00:00"
    w.guest_room(None)
    clock.advance(60)
    w.tick()
    assert w.coord._visitors_since is None
    assert w.coord._visitors_present is False


def _bs_module(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "homeassistant.helpers.device_registry",
                        H.REAL_DEVICE_REGISTRY)
    return importlib.import_module(f"{H._PKG}.binary_sensor")


def test_unique_id_and_device(monkeypatch):
    """Entity: unique id universal_room_automation_visitors_present, the
    Presence Coordinator device, `legs` unrecorded; reads the presence
    coordinator through coordinator_manager.coordinators; missing -> off."""
    BS = _bs_module(monkeypatch)
    hass = SimpleNamespace(data={})
    ent = BS.VisitorsPresentBinarySensor(hass, SimpleNamespace(entry_id="cm"))
    assert ent.unique_id == "universal_room_automation_visitors_present"
    assert ent.device_info["identifiers"] == {
        ("universal_room_automation", "presence_coordinator")}
    assert "legs" in ent._unrecorded_attributes
    assert ent.is_on is False
    presence = SimpleNamespace(
        _visitors_present=True, _visitors_legs={"room": True, "cam": False,
                                                "stay": False},
        _visitors_since="2026-11-10T14:00:00+00:00",
    )
    hass.data[H.DOMAIN] = {"coordinator_manager": SimpleNamespace(
        coordinators={"presence": presence})}
    assert ent.is_on is True
    assert ent.extra_state_attributes == {
        "legs": {"room": True, "cam": False, "stay": False},
        "since": "2026-11-10T14:00:00+00:00",
    }


def test_entity_registered_on_cm_entry(monkeypatch):
    """Wire-in: async_setup_entry for the Coordinator Manager entry adds a
    VisitorsPresentBinarySensor."""
    from unittest.mock import MagicMock

    BS = _bs_module(monkeypatch)
    AGG = importlib.import_module(f"{H._PKG}.aggregation")
    added = []
    hass = MagicMock()
    hass.data = {H.DOMAIN: {}}
    entry = MagicMock()
    entry.entry_id = "cm"
    entry.data = {H.CONST.CONF_ENTRY_TYPE: H.CONST.ENTRY_TYPE_COORDINATOR_MANAGER}
    entry.options = {}

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(AGG, "async_setup_cm_hosted_aggregation_binary_sensors",
                        _noop)
    H.run(BS.async_setup_entry(hass, entry,
                               lambda ents, *a, **k: added.extend(ents)))
    assert [e for e in added
            if type(e).__name__ == "VisitorsPresentBinarySensor"]
