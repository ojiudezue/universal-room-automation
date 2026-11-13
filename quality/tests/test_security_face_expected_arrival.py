"""FACE-ARRIVAL-REBUILD-1 D3 (plan rev 11 §3.4): the security expected-arrival
gate (alarm suppression) for camera-derived arrivals.

Drives the REAL `SecurityCoordinator._handle_person_arriving_signal` with the
REAL lock regime (rig from test_lock_face_arrival_corroboration: injected
clock, real arrival-edge stamps). Assertions are on the sanction checker's
`_expected_arrivals` (the sink). Window boundaries are literals.
"""

from __future__ import annotations

import pytest

from _lockout_harness import settle
from test_lock_face_arrival_corroboration import (  # noqa: F401 — fixture reuse
    EZ,
    areas,
    ez_really_away,
    make_rig,
    options,
)

OPTS = dict(security_on_arrival_add_expected=True)


def _expected(rig):
    return set(rig.sc._sanction_checker._expected_arrivals)


async def _arrive(rig, source="camera_face", **extra):
    payload = {"person_entity": EZ, "source": source, **extra}
    rig.sc._handle_person_arriving_signal(payload)
    await settle()


@pytest.mark.asyncio
async def test_face_only_rejected(areas):
    """Toggle on, a camera_face arrival with no non-face edge: no expected
    arrival (the latent alarm-suppression leak is closed)."""
    rig = await make_rig(opts=options(**OPTS))
    await ez_really_away(rig)
    await _arrive(rig)
    assert _expected(rig) == set()


@pytest.mark.asyncio
async def test_face_with_edge_accepted(areas):
    """A stamped Bermuda entry-area move for the same person within 120 s: the
    face adds the expected arrival."""
    rig = await make_rig(opts=options(**OPTS))
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage", tick=True)
    await _arrive(rig)
    assert _expected(rig) == {EZ}


@pytest.mark.asyncio
async def test_tracker_edge_accepted(areas):
    rig = await make_rig(opts=options(**OPTS))
    await ez_really_away(rig)
    await rig.person(EZ, "home")
    await rig.w.advance(30)
    rig.sc._sanction_checker._expected_arrivals.clear()
    await _arrive(rig)
    assert _expected(rig) == {EZ}


@pytest.mark.asyncio
async def test_lock_regime_none_rejects(areas):
    """No lock regime (setup failed / absent): fail closed, even with an
    edge stamped somewhere else."""
    rig = await make_rig(opts=options(**OPTS))
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage", tick=True)
    rig.sc._lock_regime = None
    await _arrive(rig)
    assert _expected(rig) == set()


@pytest.mark.asyncio
async def test_torn_down_regime_rejects(areas):
    rig = await make_rig(opts=options(**OPTS))
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage", tick=True)
    rig.regime._torn_down = True
    await _arrive(rig)
    assert _expected(rig) == set()


@pytest.mark.asyncio
async def test_late_edge_not_rechecked(areas):
    """A face rejected for want of an edge stays rejected when the edge lands
    afterwards (no held re-check in security, asymmetric by design)."""
    rig = await make_rig(opts=options(**OPTS))
    await ez_really_away(rig)
    await _arrive(rig)
    assert _expected(rig) == set()
    await rig.w.advance(10)
    rig.ble("Ezinne", location="Garage", tick=True)
    await settle()
    assert _expected(rig) == set()


@pytest.mark.parametrize("source", ["geofence", "ble", None])
@pytest.mark.asyncio
async def test_geofence_unchanged(areas, source):
    """Non-camera sources (and a missing source) add the expected arrival
    with no edge, exactly as on develop."""
    rig = await make_rig(opts=options(**OPTS))
    await ez_really_away(rig)
    payload = {"person_entity": EZ}
    if source is not None:
        payload["source"] = source
    rig.sc._handle_person_arriving_signal(payload)
    await settle()
    assert _expected(rig) == {EZ}


@pytest.mark.asyncio
async def test_toggle_off_face_and_geofence_add_nothing(areas):
    rig = await make_rig(opts=options(security_on_arrival_add_expected=False))
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage", tick=True)
    await _arrive(rig)
    await _arrive(rig, source="geofence")
    assert _expected(rig) == set()


@pytest.mark.asyncio
async def test_window_zero_never_accepts(areas, monkeypatch):
    """Config extreme: window 0 -> a face never adds, even with an edge at the
    same instant."""
    from test_lock_face_arrival_corroboration import const

    monkeypatch.setattr(const, "PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S", 0)
    rig = await make_rig(opts=options(**OPTS))
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage", age_s=1, tick=True)
    await _arrive(rig)
    assert _expected(rig) == set()


@pytest.mark.asyncio
async def test_both_lock_switches_on_face_only_no_effect(areas):
    """Config extreme: toggle on with the garage lockout AND the away lock on;
    a face-only arrival unlocks nothing and adds no expected arrival."""
    rig = await make_rig(opts=options(
        security_on_arrival_add_expected=True, security_away_lock_enabled=True,
    ), bed="locked")
    await ez_really_away(rig)
    await _arrive(rig)
    assert _expected(rig) == set()
    assert rig.unlocks() == []
