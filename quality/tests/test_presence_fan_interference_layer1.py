"""D3 — Fan-on Layer-1 interference diagnostic tests.

OBSERVATION-ONLY. Covers:
  * no-fan-config baseline
  * positive fire: fan on + mmwave sole + no BLE + no camera
  * negative: PIR corroboration (motion=True)
  * negative: BLE Layer-1 person in room
  * negative: camera signal active in zone
  * mode-invariance: zone-tracker `mode` output unchanged whether the
    listener is active or not (D3 is a diagnostic side-channel only)
  * docstring obligation (the D7 handoff)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

from custom_components.universal_room_automation.domain_coordinators.presence import (
    PresenceCoordinator,
    ZonePresenceTracker,
    ZonePresenceMode,
)


def _build_coord_with_tracker(rooms=("a",), zone="z1"):
    hass = make_hass()
    coord = PresenceCoordinator(hass)
    tracker = ZonePresenceTracker(hass, zone, list(rooms))
    coord._zone_trackers = {zone: tracker}
    return hass, coord, tracker


def test_no_fan_config_no_observation() -> None:
    """With no rooms in _fan_on_rooms, the helper returns []."""
    hass, coord, tracker = _build_coord_with_tracker()
    tracker.update_room_occupancy("a", True, kind="mmwave")
    assert coord._compute_fan_interference_rooms() == []


def test_fan_on_mmwave_sole_no_ble_no_camera_flags_room() -> None:
    hass, coord, tracker = _build_coord_with_tracker()
    tracker._fan_on_rooms.add("a")
    tracker.update_room_occupancy("a", True, kind="mmwave")
    # No person_coord in hass.data => BLE absence.
    out = coord._compute_fan_interference_rooms()
    assert out == ["a"]


def test_fan_on_mmwave_plus_pir_does_not_flag() -> None:
    hass, coord, tracker = _build_coord_with_tracker()
    tracker._fan_on_rooms.add("a")
    tracker.update_room_occupancy("a", True, kind="mmwave")
    tracker.update_room_occupancy("a", True, kind="motion")
    assert coord._compute_fan_interference_rooms() == []


def test_fan_on_mmwave_plus_ble_does_not_flag() -> None:
    from custom_components.universal_room_automation.const import DOMAIN
    hass, coord, tracker = _build_coord_with_tracker()
    tracker._fan_on_rooms.add("a")
    tracker.update_room_occupancy("a", True, kind="mmwave")
    # Inject person_coord with a person in the room.
    pc = MagicMock()
    pc.get_persons_in_room = MagicMock(return_value=["Alice"])
    hass.data[DOMAIN] = {"person_coordinator": pc}
    assert coord._compute_fan_interference_rooms() == []


def test_fan_on_mmwave_plus_camera_does_not_flag() -> None:
    hass, coord, tracker = _build_coord_with_tracker()
    tracker._fan_on_rooms.add("a")
    tracker.update_room_occupancy("a", True, kind="mmwave")
    tracker._camera_occupied["binary_sensor.cam_zone1_person"] = True
    assert coord._compute_fan_interference_rooms() == []


def test_mode_output_invariant_with_d3_listener() -> None:
    """`tracker.mode` and `raw_occupied` must NOT depend on D3 state.

    Set up an mmwave-sole room and toggle fan-on; the tracker's mode
    and raw_occupied are identical in both branches.
    """
    hass, coord, tracker = _build_coord_with_tracker()
    tracker.update_room_occupancy("a", True, kind="mmwave")
    mode_before = tracker.mode
    raw_before = tracker.raw_occupied
    tracker._fan_on_rooms.add("a")
    # D3 compute runs (observation-only) — must not change mode/raw.
    _ = coord._compute_fan_interference_rooms()
    assert tracker.mode == mode_before
    assert tracker.raw_occupied == raw_before


def test_listener_lifecycle_unregister_on_reload() -> None:
    """Lifecycle: _unsub_listeners is the cleanup vector for the D3 listener.

    We do not exercise the full reload path here (requires HA test
    rig) — instead we confirm the discovery routine populates
    `_unsub_listeners` and the routine is callable.
    """
    hass, coord, tracker = _build_coord_with_tracker()
    # Stage one room entry with a fan.
    from custom_components.universal_room_automation.const import (
        CONF_FANS, CONF_ENTRY_TYPE, CONF_ROOM_NAME, ENTRY_TYPE_ROOM,
    )
    entry = MagicMock()
    entry.data = {
        CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
        CONF_ROOM_NAME: "a",
        CONF_FANS: ["fan.bedroom"],
    }
    entry.options = {}
    hass.config_entries.async_entries.return_value = [entry]
    # State: fan currently on.
    s = MagicMock()
    s.state = "on"
    hass.states.get.return_value = s
    coord._unsub_listeners = []
    coord._discover_room_fans()
    # The room should now be present in _fan_on_rooms.
    assert "a" in tracker._fan_on_rooms
    # And listener registration appended exactly one unsub.
    assert len(coord._unsub_listeners) == 1


def test_d3_docstring_meets_obligation() -> None:
    """D7 obligation: the D3 helper carries a >=10-line docstring naming
    the primitive + four key phrases.
    """
    doc = (
        PresenceCoordinator._compute_fan_interference_rooms.__doc__ or ""
    )
    lines = [ln for ln in doc.splitlines() if ln.strip()]
    assert len(lines) >= 10, (
        f"D3 docstring too short ({len(lines)} non-empty lines); "
        "the D7 handoff requires >=10 lines."
    )
    lower = doc.lower()
    assert "interference-conditional" in lower
    assert "fusion" in lower
    assert "research_2026-06-03" in lower
    assert "deferred" in lower
