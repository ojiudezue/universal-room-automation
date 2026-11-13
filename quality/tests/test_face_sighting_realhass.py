"""FACE-ARRIVAL-REBUILD-1 D6 (plan rev 11 §9 D6): one REAL-HA integration test.

REAL hass core, REAL config-entry shapes (picks incl. a URA fused room pick),
REAL PersonCensus (MQTT face bridge), REAL PresenceCoordinator through
``async_setup`` (not a helper), REAL SecurityCoordinator with a REAL
LockRegimeController (and with none), all wired by the REAL dispatcher and
bus. Fires a face-sensor change, a bridge message and an egress event, plus a
restart-shaped restore, and asserts sightings, the (absent / present)
camera_face arrival and each access consumer's effect. Guards the v5.8.0
fake-coordinator incident class.

HVAC is represented by the signal it consumes (``SIGNAL_PERSON_ARRIVING``
with ``source="camera_face"``); its `pre_arrival_sources` filter is
unchanged and covered by the HVAC suite.
"""
from __future__ import annotations

import time

import pytest

import _sighting_rig as R
from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse


async def _full(mods, hass, monkeypatch, *, regime: bool, interior: bool):
    if interior:
        monkeypatch.setattr(mods.const, "FACE_ARRIVAL_INTERIOR_ENABLED", True)
    rig = await R.build(mods, hass, monkeypatch, setup=False,
                        persons={p: "not_home" for p in R.TRACKED})
    cm = mods.const
    ents = R.entries(mods)
    ents.append(R.SimpleNamespace(entry_id="cm", data={
        cm.CONF_ENTRY_TYPE: cm.ENTRY_TYPE_COORDINATOR_MANAGER}, options={
        "security_on_arrival_add_expected": True,
        "security_coordinator_enabled": True,
    }))
    R.install_entries(hass, monkeypatch, ents)
    await rig.presence.async_setup()
    rig.producer = rig.presence._person_sightings
    rig.producer._setup_ts = time.time() - 700
    sc = mods.security.SecurityCoordinator(hass, lock_entities=[], garage_entities=[])
    sc._lock_regime = None
    if regime:
        from importlib import import_module
        LR = import_module(
            "custom_components.universal_room_automation.domain_coordinators."
            "security_lock_regime").LockRegimeController
        lr = LR(hass, sc)
        await lr.async_setup()
        lr._setup_ts = time.time() - 1000
        sc._lock_regime = lr
    rig.unsubs.append(mods.dispatcher.async_dispatcher_connect(
        hass, mods.signals.SIGNAL_PERSON_ARRIVING, sc._handle_person_arriving_signal))
    arrivals: list = []

    def _cap(p):
        arrivals.append(p)

    _cap._hass_callback = True
    rig.unsubs.append(mods.dispatcher.async_dispatcher_connect(
        hass, mods.signals.SIGNAL_PERSON_ARRIVING, _cap))
    rig.sc, rig.arrivals = sc, arrivals
    return rig


@pytest.mark.parametrize("regime", [True, False])
@pytest.mark.asyncio
async def test_sources_to_consumers_end_to_end(mods, hass, monkeypatch, regime):
    rig = await _full(mods, hass, monkeypatch, regime=regime, interior=True)
    try:
        # Setup line: the URA fused Study B pick resolved, Garage A did not.
        diag = rig.presence.get_person_sighting_diagnostics()
        assert R.STUDY_FUSED in diag["face_sighting_picks_resolved"]
        assert diag["face_sighting_picks_unresolved"][R.GARAGE_FUSED] == "room_cameras_empty"
        # (b) face-sensor change, person away -> sighting + camera_face arrival,
        # but security adds NO expected arrival (no independent edge).
        await R.face(rig, "family_room", "Oji")
        # (a) bridge message on another picked camera.
        R.bridge(rig, "staircase", "Jaya")
        await hass.async_block_till_done()
        # (c) egress face crossing -> sighting, never an arrival.
        await R.egress(rig, person_id="ezinne")
        srcs = sorted((s.slug, s.sighting_source) for s in rig.sightings)
        assert srcs == [("ezinne", "egress_entry"), ("jaya", "interior_pick"),
                        ("oji_udezue", "interior_pick")]
        cams = [a for a in rig.arrivals if a.get("source") == "camera_face"]
        assert sorted(a["person_entity"] for a in cams) == ["person.jaya", "person.oji_udezue"]
        assert rig.sc._sanction_checker._expected_arrivals == {}
        # A geofence arrival still adds (develop behaviour, L19).
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(hass, mods.signals.SIGNAL_PERSON_ARRIVING,
                              {"person_entity": "person.ziri", "source": "geofence"})
        await hass.async_block_till_done()
        assert set(rig.sc._sanction_checker._expected_arrivals) == {"person.ziri"}
        # Restart-shaped restore: a face sensor restored (old state None ->
        # unavailable -> name) is not a sighting.
        n = len(rig.sightings)
        hass.states.async_remove(R.FACE["upstairs_hall"])
        hass.states.async_set(R.FACE["upstairs_hall"], "Ziri")
        await hass.async_block_till_done()
        assert len(rig.sightings) == n
        if regime:
            assert "person.oji_udezue" in rig.sc._lock_regime._pending_faces
    finally:
        await rig.presence.async_teardown()
        if regime:
            await rig.sc._lock_regime.async_teardown()
        await R.teardown(rig)


@pytest.mark.asyncio
async def test_interior_arrivals_off_by_default(mods, hass, monkeypatch):
    rig = await _full(mods, hass, monkeypatch, regime=False, interior=False)
    try:
        await R.face(rig, "family_room", "Oji")
        assert len(rig.sightings) == 1
        assert [a for a in rig.arrivals if a.get("source") == "camera_face"] == []
    finally:
        await rig.presence.async_teardown()
        await R.teardown(rig)
