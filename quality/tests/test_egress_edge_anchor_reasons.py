"""Step 7 S1 observability: every no-anchor return carries a reason, the
reason lands on the D8a outcome row, is counted per reason, and surfaces on
the persons-in-house census sensor. Drives the production entry point via the
rig of test_egress_edge_anchor."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from test_egress_edge_anchor import (  # noqa: F401  (rig fixture)
    FRONT, NOW, _TV_CONST, _cross, _face, _pairs, _rows, rig, tv,
)


def _none(rig):
    return dict(tv._layer_signals().layer_counters(rig.hass).edge_anchor_none)


async def _go(rig, direction="exit"):
    await _cross(rig, FRONT, at=NOW, direction=direction)
    return _rows(rig.db)[-1]["edge_anchor_reason"]


@pytest.mark.asyncio
async def test_reason_anchored(rig):
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    assert await _go(rig) == "anchored"
    assert _none(rig) == {}


@pytest.mark.asyncio
async def test_reason_lead_off(rig, monkeypatch):
    monkeypatch.setattr(_TV_CONST, "EGRESS_ARRIVAL_EDGE_LEAD_S", 0)
    _face(rig, "jaya", NOW)
    assert await _go(rig) == "lead_off"
    assert _none(rig) == {"lead_off": 1}


@pytest.mark.asyncio
async def test_reason_direction(rig):
    _face(rig, "jaya", NOW)
    res = tv.EgressResolution(outcome="attached", direction="ambiguous",
                              agreement="x", slug="jaya", provenance="face",
                              face_tier=0.6, live_face_legs=1)
    assert rig.tracker._compute_edge_anchor_ex("ambiguous", res, NOW) == (None, "direction")
    assert _none(rig) == {"direction": 1}


@pytest.mark.asyncio
async def test_reason_provenance_ble_only(rig):
    rig.ble["legs"] = [SimpleNamespace(person_slug="jaya", transition_ts=NOW)]
    rig.census.ble_tracker_slug_map = lambda: {"a": "jaya", "b": "oji_udezue", "c": "ezinne"}
    assert await _go(rig) == "provenance"


@pytest.mark.asyncio
async def test_reason_vetoed_is_provenance(rig):
    _face(rig, "jaya", NOW, home=False)
    assert await _go(rig) == "provenance"


def test_reason_no_slug_and_face_tier(rig):
    base = dict(outcome="attached", direction="exit", agreement="x",
                provenance="face", face_tier=0.6, live_face_legs=1)
    ex = rig.tracker._compute_edge_anchor_ex
    assert ex("exit", tv.EgressResolution(**base, slug=None), NOW) == (None, "no_slug")
    r = tv.EgressResolution(**{**base, "face_tier": None}, slug="jaya")
    assert ex("exit", r, NOW) == (None, "face_tier")
    r = tv.EgressResolution(**{**base, "face_tier": 0.5}, slug="jaya")
    assert ex("exit", r, NOW) == (None, "face_tier")
    assert _none(rig) == {"no_slug": 1, "face_tier": 2}


@pytest.mark.asyncio
async def test_reason_no_live_face_legs(rig):
    _face(rig, "jaya", NOW)
    rig.legs["front_door"] = [replace(rig.legs["front_door"][0], synthetic=True)]
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    assert await _go(rig) == "no_live_face_legs"


@pytest.mark.asyncio
async def test_reason_census_off(rig, monkeypatch):
    res = tv.EgressResolution(outcome="attached", direction="exit", agreement="x",
                              slug="jaya", provenance="face", face_tier=0.6,
                              live_face_legs=1)
    monkeypatch.setattr(rig.census, "egress_identity_enabled", lambda: False)
    assert rig.tracker._compute_edge_anchor_ex("exit", res, NOW) == (None, "census_off")


def test_reason_no_presence(rig, monkeypatch):
    res = tv.EgressResolution(outcome="attached", direction="exit", agreement="x",
                              slug="jaya", provenance="face", face_tier=0.6,
                              live_face_legs=1)
    monkeypatch.setattr(rig.tracker, "_presence_coordinator", lambda: None)
    assert rig.tracker._compute_edge_anchor_ex("exit", res, NOW) == (None, "no_presence")


@pytest.mark.asyncio
async def test_reason_truncated(rig):
    rig.presence.tracker.created_ts = (NOW - timedelta(seconds=100)).timestamp()
    _face(rig, "jaya", NOW)
    assert await _go(rig) == "truncated"
    assert _none(rig) == {"truncated": 1}


@pytest.mark.asyncio
async def test_reason_no_own_edge(rig):
    _face(rig, "jaya", NOW)
    assert await _go(rig) == "no_own_edge"
    assert _none(rig) == {"no_own_edge": 1}


@pytest.mark.asyncio
async def test_reason_partner_blocked(rig):
    _pairs(rig, "jaya|ezinne")
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=120))
    rig.presence.add("person.ezinne", NOW - timedelta(seconds=90))
    assert await _go(rig) == "partner_blocked"


@pytest.mark.asyncio
async def test_reason_error(rig):
    _face(rig, "jaya", NOW)
    rig.presence.raise_on_read = True
    assert await _go(rig) == "error"
    assert _none(rig) == {"error": 1}


@pytest.mark.asyncio
async def test_live_case_2026_11_20_ble_face_entry_anchors(rig):
    """11-20 12:38:25 doorbell entry, ble+face 0.95, own not_home->home edge
    24 s earlier, no partner edge: anchored with lead 24.0."""
    rig.ble["legs"] = [SimpleNamespace(person_slug="jaya", transition_ts=NOW)]
    _face(rig, "jaya", NOW)
    rig.presence.add("person.jaya", NOW - timedelta(seconds=24))
    assert await _go(rig, "entry") == "anchored"
    row = _rows(rig.db)[-1]
    assert row["provenance"] == "ble+face"
    assert row["edge_anchor"] == {"slug": "jaya", "lead_s": 24.0}


@pytest.mark.asyncio
async def test_live_case_ble_face_with_only_synthetic_face(rig):
    """The most likely 11-20 gate: the face leg was an MQTT latch only."""
    rig.ble["legs"] = [SimpleNamespace(person_slug="jaya", transition_ts=NOW)]
    _face(rig, "jaya", NOW)
    rig.legs["front_door"] = [replace(rig.legs["front_door"][0], synthetic=True)]
    rig.presence.add("person.jaya", NOW - timedelta(seconds=24))
    assert await _go(rig, "entry") == "no_live_face_legs"


@pytest.mark.asyncio
async def test_reasons_on_census_sensor_and_layer_diagnostics(rig, monkeypatch):
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as presence_mod,
    )

    monkeypatch.setattr(presence_mod, "_layer_signals", tv._layer_signals())
    _face(rig, "jaya", NOW)
    await _go(rig)  # no_own_edge
    shell = SimpleNamespace(hass=rig.hass, _egress_tracker=lambda: None)
    d = presence_mod.PresenceCoordinator.get_layer_diagnostics(shell)
    assert d["edge_anchor_none"] == {"no_own_edge": 1}
