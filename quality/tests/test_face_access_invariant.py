"""FACE-ARRIVAL-REBUILD-1 INV-ACCESS (plan rev 11 §2, D3).

In any reachable path a camera-derived arrival (source in
CAMERA_DERIVED_ARRIVAL_SOURCES, or an unknown source) can never on its own
release a garage lockout, unlock the away lock, add an expected arrival, or
disarm. Both gates classify with ONE helper. REAL SecurityCoordinator + REAL
lock regime (rig from test_lock_face_arrival_corroboration).
"""

from __future__ import annotations

import pytest

from _lockout_harness import settle
from test_lock_face_arrival_corroboration import (  # noqa: F401 — fixture reuse
    AE,
    EZ,
    LOCK_A,
    LOCK_B,
    R,
    areas,
    ez_really_away,
    make_rig,
    options,
    sec,
)

OPTS = dict(security_on_arrival_add_expected=True, security_away_lock_enabled=True)


async def _arrive(rig, source, **extra):
    payload = {"person_entity": EZ, **extra}
    if source is not ...:
        payload["source"] = source
    rig.sc._handle_person_arriving_signal(payload)
    await settle()


def _expected(rig):
    return set(rig.sc._sanction_checker._expected_arrivals)


@pytest.mark.parametrize("source", ["camera_vision", ""])
@pytest.mark.asyncio
async def test_unknown_arrival_source_requires_corroboration(areas, source):
    """An unknown source with no edge: no lock release, no away unlock, no
    expected arrival (fail closed in BOTH gates)."""
    rig = await make_rig(opts=options(**OPTS), bed="locked")
    await ez_really_away(rig)
    await _arrive(rig, source)
    assert rig.unlocks() == []
    assert EZ in rig.regime._pending_faces
    assert _expected(rig) == set()


@pytest.mark.asyncio
async def test_camera_egress_requires_corroboration(areas):
    """`camera_egress` (no producer in Phase 1) is gated from this ship on."""
    rig = await make_rig(opts=options(**OPTS), bed="locked")
    await ez_really_away(rig)
    await _arrive(rig, "camera_egress")
    assert rig.unlocks() == []
    assert _expected(rig) == set()
    rig.ble("Ezinne", location="Garage", tick=True)
    await _arrive(rig, "camera_egress")
    assert set(rig.unlocks()) >= {LOCK_A, LOCK_B}
    assert _expected(rig) == {EZ}


@pytest.mark.asyncio
async def test_camera_derived_set_used_by_both_gates(areas):
    """camera_face: both gates hold without an edge and both act with one."""
    rig = await make_rig(opts=options(**OPTS))
    await ez_really_away(rig)
    await _arrive(rig, "camera_face")
    assert rig.unlocks() == [] and _expected(rig) == set()
    rig.ble("Ezinne", location="Garage", tick=True)
    rig.w.calls.clear()
    await _arrive(rig, "camera_face")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert _expected(rig) == {EZ}


@pytest.mark.asyncio
async def test_missing_source_is_not_camera_derived(areas):
    """A payload with NO source key behaves as on develop: the lock regime
    releases on really-away and security adds the expected arrival."""
    rig = await make_rig(opts=options(**OPTS))
    await ez_really_away(rig)
    await _arrive(rig, ...)
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert _expected(rig) == {EZ}
    assert AE.arrival_source_needs_corroboration(None) is False


def test_source_classifier_shared_by_both_gates():
    """Hand-written truth table of the ONE classifier (both gates import it)."""
    f = AE.arrival_source_needs_corroboration
    assert [f(s) for s in (None, "geofence", "ble", "camera_face", "camera_egress",
                           "camera_vision", "", "GEOFENCE")] == [
        False, False, False, True, True, True, True, True]
    assert R.arrival_source_needs_corroboration is f
    assert sec.arrival_source_needs_corroboration is f


@pytest.mark.asyncio
async def test_no_sighting_payload_uses_now(areas):
    """A camera_face payload without a `sighting` is judged at NOW on the lock
    regime's own clock (at_ts None -> `_ts()`): an edge 100 s before now
    corroborates, one 200 s before now does not. A payload WITH a sighting is
    judged at the sighting's recognition ts."""
    rig = await make_rig(opts=options(**OPTS))
    await ez_really_away(rig)
    seen = []
    real = rig.regime.face_input_corroborated

    def _spy(person, at_ts=None):
        seen.append(at_ts)
        return real(person, at_ts)

    rig.regime.face_input_corroborated = _spy
    await rig.person(EZ, "home")          # tracker edge at t_edge
    t_edge = rig.regime._ts()
    rig.sc._sanction_checker._expected_arrivals.clear()
    await rig.w.advance(100)
    await _arrive(rig, "camera_face")
    assert seen == [None]
    assert _expected(rig) == {EZ}
    rig.sc._sanction_checker._expected_arrivals.clear()
    await rig.w.advance(100)              # now = t_edge + 200
    await _arrive(rig, "camera_face")
    assert _expected(rig) == set()
    seen.clear()
    sighting = type("S", (), {"ts": t_edge + 30})()
    await _arrive(rig, "camera_face", sighting=sighting)
    assert seen == [t_edge + 30]
    assert _expected(rig) == {EZ}


@pytest.mark.asyncio
async def test_no_face_path_reaches_disarm(areas, monkeypatch):
    """No SIGNAL_PERSON_ARRIVING path (face, egress, unknown, with or without an
    edge) calls handle_disarm."""
    rig = await make_rig(opts=options(**OPTS))
    calls = []

    async def _disarm(*a, **k):
        calls.append((a, k))

    monkeypatch.setattr(rig.sc, "handle_disarm", _disarm)
    await ez_really_away(rig)
    for src in ("camera_face", "camera_egress", "camera_vision", "geofence", "ble"):
        await _arrive(rig, src)
    rig.ble("Ezinne", location="Garage", tick=True)
    await _arrive(rig, "camera_face")
    assert calls == []
