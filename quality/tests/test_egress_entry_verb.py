"""Egress notice verb (operator 2026-11-20): a NAMED entry says "arrived"
only with the person's own counted arrival edge in the S1 window; a person
already home before the window "came in". Production entry point, S1 rig."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from test_egress_edge_anchor import (  # noqa: F401  (rig fixture)
    FRONT, GARAGE, NOW, _TV_CONST, _cross, _leg, _pairs, _rows, _titles, rig,
)


def _home_since(rig, slug, since):
    rig.states[f"person.{slug}"] = SimpleNamespace(
        state="home", last_changed=since, attributes={})


def _face_09(rig, slug, at, stem="garage_a"):
    """Two independent cameras -> tier 0.9 (CONFIDENCE_HIGH)."""
    rig.legs.clear()
    rig.legs[stem] = [_leg(stem, slug, at + timedelta(seconds=4))]
    rig.legs["foyer"] = [_leg("foyer", slug, at + timedelta(seconds=5))]


@pytest.mark.asyncio
async def test_live_2026_11_19_garage_entry_home_no_edge_came_in(rig):
    """11-19 19:04 garage entry, face 0.9, Jaya home since 18:18 (46 min),
    no own arrival edge -> "Jaya came in"."""
    _face_09(rig, "jaya", NOW)
    _home_since(rig, "jaya", NOW - timedelta(minutes=46))
    await _cross(rig, GARAGE, at=NOW, direction="entry")
    assert _titles(rig) == ["Jaya came in"]
    payload = rig.fired[-1][1]
    assert payload["person_id"] == "jaya" and payload["identity_confidence"] == 0.9
    assert rig.nm.async_notify.await_args.kwargs["message"] == "Jaya came in"
    assert rig.nm.async_notify.await_args.kwargs["severity"].name == "LOW"


@pytest.mark.asyncio
async def test_live_2026_11_20_doorbell_ble_face_own_edge_arrived(rig):
    """11-20 12:38:25 entry, ble+face 0.95, own edge 24 s earlier -> arrived."""
    rig.ble["legs"] = [SimpleNamespace(person_slug="jaya", transition_ts=NOW)]
    rig.legs.clear()
    rig.legs["front_door"] = [_leg("front_door", "jaya", NOW + timedelta(seconds=5))]
    _home_since(rig, "jaya", NOW - timedelta(seconds=24))
    rig.presence.add("person.jaya", NOW - timedelta(seconds=24))
    await _cross(rig, FRONT, at=NOW, direction="entry")
    assert _titles(rig) == ["Jaya arrived"]
    assert rig.fired[-1][1]["identity_confidence"] == 0.95


@pytest.mark.asyncio
async def test_named_entry_own_edge_without_anchor_arrived(rig):
    """Anchor blocked by a partner edge; the 0.9 name stands and the own
    edge keeps "arrived" (the verb rule's own-edge branch)."""
    _pairs(rig, "jaya|ezinne")
    _face_09(rig, "jaya", NOW)
    _home_since(rig, "jaya", NOW - timedelta(minutes=46))
    rig.presence.add("person.jaya", NOW - timedelta(seconds=60))
    rig.presence.add("person.ezinne", NOW - timedelta(seconds=50))
    await _cross(rig, GARAGE, at=NOW, direction="entry")
    assert _rows(rig.db)[-1]["edge_anchor_reason"] == "partner_blocked"
    assert _titles(rig) == ["Jaya arrived"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kw", [
    {"stale": True}, {"boot": True}, {"counted": False},
])
async def test_uncounted_own_edge_came_in(rig, kw):
    _pairs(rig, "jaya|ezinne")
    _face_09(rig, "jaya", NOW)
    _home_since(rig, "jaya", NOW - timedelta(minutes=46))
    rig.presence.add("person.jaya", NOW - timedelta(seconds=60), **kw)
    await _cross(rig, GARAGE, at=NOW, direction="entry")
    assert _titles(rig) == ["Jaya came in"]


@pytest.mark.asyncio
async def test_own_edge_outside_window_came_in(rig):
    _face_09(rig, "jaya", NOW)
    _home_since(rig, "jaya", NOW - timedelta(minutes=46))
    rig.presence.add("person.jaya", NOW - timedelta(seconds=301))
    await _cross(rig, GARAGE, at=NOW, direction="entry")
    assert _titles(rig) == ["Jaya came in"]


@pytest.mark.asyncio
async def test_truncated_ring_reads_as_no_edge(rig):
    rig.presence.tracker.created_ts = (NOW - timedelta(seconds=100)).timestamp()
    _face_09(rig, "jaya", NOW)
    _home_since(rig, "jaya", NOW - timedelta(minutes=46))
    rig.presence.add("person.jaya", NOW - timedelta(seconds=60))
    await _cross(rig, GARAGE, at=NOW, direction="entry")
    assert _titles(rig) == ["Jaya came in"]


@pytest.mark.asyncio
async def test_home_inside_window_no_edge_keeps_arrived(rig):
    """Home only since 299 s (inside the window), no edge: today's text."""
    _face_09(rig, "jaya", NOW)
    _home_since(rig, "jaya", NOW - timedelta(seconds=299))
    await _cross(rig, GARAGE, at=NOW, direction="entry")
    assert _titles(rig) == ["Jaya arrived"]


@pytest.mark.asyncio
async def test_home_301s_before_no_edge_came_in(rig):
    _face_09(rig, "jaya", NOW)
    _home_since(rig, "jaya", NOW - timedelta(seconds=301))
    await _cross(rig, GARAGE, at=NOW, direction="entry")
    assert _titles(rig) == ["Jaya came in"]


@pytest.mark.asyncio
async def test_exit_unchanged_left(rig):
    _face_09(rig, "jaya", NOW)
    _home_since(rig, "jaya", NOW - timedelta(minutes=46))
    await _cross(rig, GARAGE, at=NOW, direction="exit")
    assert _titles(rig) == ["Jaya left"]


@pytest.mark.asyncio
async def test_unnamed_entry_someone_arrived(rig):
    rig.legs.clear()
    rig.legs["garage_a"] = [_leg("garage_a", "jaya", NOW + timedelta(seconds=5))]
    _home_since(rig, "jaya", NOW - timedelta(minutes=46))
    await _cross(rig, GARAGE, at=NOW, direction="entry")
    assert _titles(rig) == ["Someone arrived"]


@pytest.mark.asyncio
async def test_lead_zero_keeps_arrived(rig, monkeypatch):
    monkeypatch.setattr(_TV_CONST, "EGRESS_ARRIVAL_EDGE_LEAD_S", 0)
    _face_09(rig, "jaya", NOW)
    _home_since(rig, "jaya", NOW - timedelta(minutes=46))
    await _cross(rig, GARAGE, at=NOW, direction="entry")
    assert _titles(rig) == ["Jaya arrived"]
    assert rig.presence.calls == []


@pytest.mark.asyncio
async def test_own_edge_after_upper_bound_came_in(rig):
    """Edge at t_E + 46 s (window ends at + 45 s) is not this crossing's."""
    _face_09(rig, "jaya", NOW)
    _home_since(rig, "jaya", NOW - timedelta(minutes=46))
    rig.presence.add("person.jaya", NOW + timedelta(seconds=46))
    await _cross(rig, GARAGE, at=NOW, direction="entry")
    assert _titles(rig) == ["Jaya came in"]


@pytest.mark.asyncio
async def test_not_home_state_keeps_arrived(rig):
    """Person state not home (unknown) before the window: not "came in"."""
    _face_09(rig, "jaya", NOW)
    rig.states["person.jaya"] = SimpleNamespace(
        state="unknown", last_changed=NOW - timedelta(minutes=46), attributes={})
    await _cross(rig, GARAGE, at=NOW, direction="entry")
    assert _titles(rig) == ["Jaya arrived"]
