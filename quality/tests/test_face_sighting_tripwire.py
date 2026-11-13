"""FACE-ARRIVAL-REBUILD-1 D4 (plan rev 11 §3.5, §9 D4): the zero-sighting
trip-wire. The denominator is the census post-sentinel named-face ring (filled
by the REAL census MQTT bridge); the numerator is the producer's interior
sightings. Driven through presence's periodic tick (`_periodic_inference` ->
producer.on_tick). The NM call is observed at `fire_stuck_signal`.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

import _sighting_rig as R
from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse


@pytest_asyncio.fixture
async def rig(mods, hass, monkeypatch):
    r = await R.build(mods, hass, monkeypatch)
    pages: list = []

    async def _fake_fire(hass_, kind, key, diagnosis, remedy="", severity=None, **kw):
        pages.append((kind, severity))
        return True

    monkeypatch.setattr(mods.sighting, "fire_stuck_signal", _fake_fire)
    r.pages = pages
    yield r
    await R.teardown(r)


def _kill_hook(rig):
    """The v3.19 signature: faces flow through the census bridge but the
    producer hears nothing (its callback is gone)."""
    rig.hass.data[R.DOMAIN]["face_latch_callbacks"].clear()


async def _faces(rig, n, name="Oji", camera="family_room"):
    for _ in range(n):
        R.bridge(rig, camera, name)
    await rig.hass.async_block_till_done()


async def _tick(rig):
    await rig.presence._periodic_inference()
    await rig.hass.async_block_till_done()


@pytest.mark.asyncio
async def test_zero_with_faces_pages(rig):
    _kill_hook(rig)
    await _faces(rig, 10)
    await _tick(rig)
    assert rig.pages == [("face_sighting_zero", "HIGH")]
    await _tick(rig)
    assert len(rig.pages) == 1  # RAM latch: once


@pytest.mark.asyncio
async def test_zero_without_faces_silent(rig):
    _kill_hook(rig)
    await _faces(rig, 9)          # literal floor 10: 9 is below it
    await _tick(rig)
    assert rig.pages == []


@pytest.mark.asyncio
async def test_unknown_name_faces_silent(rig):
    _kill_hook(rig)
    await _faces(rig, 12, name="Unknown")
    await _tick(rig)
    assert rig.pages == []
    assert len(rig.census._frigate_face_named_ring) == 0  # post-sentinel ring


@pytest.mark.asyncio
async def test_unmapped_only_faces_silent(rig):
    _kill_hook(rig)
    await _faces(rig, 12, name="Bob")
    await _tick(rig)
    assert rig.pages == []
    assert len(rig.census._frigate_face_named_ring) == 12


@pytest.mark.asyncio
async def test_unpicked_only_faces_silent(rig):
    _kill_hook(rig)
    await _faces(rig, 12, camera="garage_a")
    await _tick(rig)
    assert rig.pages == []


@pytest.mark.asyncio
async def test_suppressed_faces_silent(mods, hass, monkeypatch):
    rig = await R.build(mods, hass, monkeypatch, strict=True)
    pages: list = []

    async def _fake_fire(hass_, kind, key, diagnosis, remedy="", severity=None, **kw):
        pages.append(kind)
        return True

    monkeypatch.setattr(mods.sighting, "fire_stuck_signal", _fake_fire)
    try:
        rig.census.set_face_drill_forced(hass, True)
        await _faces(rig, 12)
        assert rig.sightings == []  # the producer correctly emits nothing
        await _tick(rig)
        assert pages == []
        assert all(e[4] for e in rig.census._frigate_face_named_ring)
    finally:
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_rearm_after_recovery(rig):
    cbs = list(rig.hass.data[R.DOMAIN]["face_latch_callbacks"])
    _kill_hook(rig)
    await _faces(rig, 10)
    await _tick(rig)
    assert len(rig.pages) == 1
    rig.hass.data[R.DOMAIN]["face_latch_callbacks"].extend(cbs)  # recovered
    await _faces(rig, 1)
    await _tick(rig)
    assert rig.producer._zero_latched is False
    assert len(rig.pages) == 1


@pytest.mark.asyncio
async def test_window_zero_off(rig, monkeypatch):
    monkeypatch.setattr(rig.m.const, "FACE_SIGHTING_ZERO_WINDOW_H", 0)
    _kill_hook(rig)
    await _faces(rig, 20)
    await _tick(rig)
    assert rig.pages == []


@pytest.mark.asyncio
async def test_arrival_zero_unarmed_when_interior_off(rig, monkeypatch):
    """Interior arrivals off (the shipped default): sightings for 15 days
    with zero arrivals never page face_arrival_zero."""
    import time
    p = rig.producer
    p._setup_ts = time.time() - 15 * 86400
    await R.face(rig, "family_room", "Oji")
    await _tick(rig)
    assert [k for k, _ in rig.pages if k == "face_arrival_zero"] == []
    monkeypatch.setattr(rig.m.const, "FACE_ARRIVAL_INTERIOR_ENABLED", True)
    await _tick(rig)
    assert ("face_arrival_zero", "LOW") in rig.pages
