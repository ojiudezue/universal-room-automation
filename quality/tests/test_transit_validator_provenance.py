"""FACE-ARRIVAL-REBUILD-1 (plan rev 11 §9 D1 / D8a; rev 4 H1): the additive
`identity_provenance` key on `ura_person_egress_event`, and the 3-tuple
wrapper / provenance constants it relies on.

Crossings go through the REAL `_on_egress_state_change` -> `_resolve_direction`
-> `_resolve_egress_face_identity_ex` path (rig from test_egress_outcome_log);
no attach dict and no resolution is stamped by hand.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from test_egress_outcome_log import (  # noqa: F401 — fixture reuse
    NOW,
    _cross,
    _leg,
    _state,
    rig,
)

from custom_components.universal_room_automation import const as ura_const


@pytest.mark.asyncio
async def test_face_only_real_path_provenance_face(rig):
    """A face-only crossing (no BLE leg) through the real resolver fires the
    bus event with identity_provenance == "face" (rev 4 H1: a plain stash copy
    would publish None because the face path wrote no key)."""
    rig.legs["front_door"] = [_leg("front_door", "oji_udezue", NOW + timedelta(seconds=3))]
    rig.states["person.oji_udezue"] = _state("home")
    await _cross(rig, "binary_sensor.front_door_person_occupancy", at=NOW)
    topic, payload = rig.fired[-1]
    assert topic == "ura_person_egress_event"
    assert payload["person_id"] == "oji_udezue"
    assert payload["identity_provenance"] == "face"


@pytest.mark.asyncio
async def test_bus_event_carries_identity_provenance(rig):
    """BLE-only attach -> "ble"; unnamed crossing -> None. The key exists on
    every egress event (additive)."""
    from custom_components.universal_room_automation.camera_census import (
        BleTransitionLeg,
    )

    rig.census._ble_tracker_slug_map = {
        "device_tracker.oji_ble": "oji_udezue",
        "device_tracker.jaya_ble": "jaya",
    }
    leg = BleTransitionLeg(
        person_slug="oji_udezue",
        transition_ts=NOW - timedelta(seconds=20),
        direction="arriving",
        engine="ble",
        confidence=ura_const.BLE_TRANSITION_CONFIDENCE,
        provenance=ura_const.IDENTITY_PROVENANCE_BLE,
        source_entity="device_tracker.oji_ble",
    )
    rig.census._resolve_ble_legs = lambda ts, direction: [leg]
    rig.census._consume_ble_arriving_legs = lambda slug: None
    await _cross(rig, "binary_sensor.front_door_person_occupancy", at=NOW)
    payload = rig.fired[-1][1]
    assert payload["person_id"] == "oji_udezue"
    assert payload["identity_confidence"] == ura_const.BLE_TRANSITION_ONLY_CONFIDENCE
    assert payload["identity_provenance"] == "ble"

    rig.census._resolve_ble_legs = lambda ts, direction: []
    await _cross(
        rig, "binary_sensor.garage_a_person_occupancy",
        at=NOW + timedelta(minutes=5),
    )
    payload = rig.fired[-1][1]
    assert payload["person_id"] is None
    assert "identity_provenance" in payload and payload["identity_provenance"] is None


@pytest.mark.asyncio
async def test_census_register_keeps_ble_face_tag(rig):
    """Behavioural pin of the census rename: a `ble+face` registration survives
    the face-producer-down filter, a `face` one does not."""
    census = rig.census
    census._is_egress_identity_enabled = lambda: True
    census.register_egress_face("oji_udezue", NOW, provenance="ble+face")
    census.register_egress_face("jaya", NOW, provenance="face")
    census._is_egress_identity_failsafe_strict = lambda: True
    census._is_face_producer_live = lambda: False
    fresh = census._get_egress_face_ids_fresh(NOW + timedelta(seconds=5))
    assert "oji_udezue" in fresh
    assert "jaya" not in fresh


@pytest.mark.asyncio
async def test_face_only_attach_stash_provenance_face(rig):
    """C-M5: the face-only attach stamps census._egress_identity_last_attach
    provenance "face" explicitly (readers gate face names on it)."""
    rig.legs["front_door"] = [_leg("front_door", "oji_udezue", NOW + timedelta(seconds=3))]
    rig.states["person.oji_udezue"] = _state("home")
    await _cross(rig, "binary_sensor.front_door_person_occupancy", at=NOW)
    stash = rig.census._egress_identity_last_attach
    assert stash["person"] == "oji_udezue"
    assert stash["provenance"] == "face"
