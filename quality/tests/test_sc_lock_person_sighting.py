"""FACE-ARRIVAL-REBUILD-1 D3 (plan rev 11 §3.4): the lock regime for an
interior camera_face arrival, and its public corroboration wrapper.

REAL lock regime (rig from test_lock_face_arrival_corroboration)."""

from __future__ import annotations

import pytest

from _lockout_harness import settle
from test_lock_face_arrival_corroboration import (  # noqa: F401 — fixture reuse
    EZ,
    LOCK_A,
    LOCK_B,
    areas,
    ez_really_away,
    make_rig,
)


@pytest.mark.asyncio
async def test_interior_face_held_pending_when_really_away(areas):
    """Person really away, no edge: the face is held in `_pending_faces` and
    nothing is released."""
    rig = await make_rig()
    await ez_really_away(rig)
    rig.regime.on_person_arriving({"person_entity": EZ, "source": "camera_face"})
    await settle()
    assert EZ in rig.regime._pending_faces
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_face_released_with_bermuda_entry_edge(areas):
    rig = await make_rig()
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage", tick=True)
    rig.regime.on_person_arriving({"person_entity": EZ, "source": "camera_face"})
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert EZ not in rig.regime._pending_faces


@pytest.mark.asyncio
async def test_face_input_corroborated_matches_private(areas):
    """The public wrapper answers exactly as the private rule, at the face
    time it is given, on both sides of the 120 s window (literal boundary)."""
    rig = await make_rig()
    await ez_really_away(rig)
    t_face = rig.regime._ts()
    assert rig.regime.face_input_corroborated(EZ, t_face) is False  # no edge yet
    await rig.person(EZ, "home")
    t_edge = rig.regime._ts()
    for dt_s, expected in ((-121, False), (-120, True), (0, True), (120, True), (121, False)):
        at = t_edge + dt_s
        assert rig.regime.face_input_corroborated(EZ, at) is expected, dt_s
        assert rig.regime.face_input_corroborated(EZ, at) == (
            rig.regime._face_arrival_corroborated(EZ, at)
        )
    rig.regime._torn_down = True
    assert rig.regime.face_input_corroborated(EZ, t_edge) is False
