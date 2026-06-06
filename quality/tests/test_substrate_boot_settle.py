"""Occupancy substrate — D6 cold-boot storm coordination tests.

Invariants:

1. During the boot window (``_boot_settle_done == False``), state-change
   events update ``_raw_state`` but DO NOT dispatch
   ``SIGNAL_SUBSTRATE_KIND_CHANGED``.
2. At settle (``release_boot_settle``), exactly one synthetic signal is
   emitted per True-seeded ``(room, kind)`` slot. False slots emit
   nothing.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass, fake_room_entry

from custom_components.universal_room_automation.const import (
    CONF_MOTION_SENSORS,
    CONF_MMWAVE_SENSORS,
)
from custom_components.universal_room_automation.domain_coordinators import (
    occupancy_substrate as substrate_mod,
)
from custom_components.universal_room_automation.domain_coordinators.occupancy_substrate import (  # noqa: E501
    OccupancySubstrate,
)


def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


def _state(value: str):
    s = MagicMock()
    s.state = value
    return s


def test_dispatch_suppressed_during_boot(monkeypatch) -> None:
    hass = make_hass()
    entry = fake_room_entry(
        "Bedroom",
        **{CONF_MOTION_SENSORS: ["binary_sensor.bedroom_motion"]},
    )
    hass.config_entries.async_entries.return_value = [entry]

    dispatches = []

    def _fake_dispatch(_hass, signal, *args):
        dispatches.append((signal, args))

    monkeypatch.setattr(
        substrate_mod, "async_dispatcher_send", _fake_dispatch,
    )
    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    assert sub._boot_settle_done is False

    # Simulate a state-change event during the boot window.
    evt = MagicMock()
    evt.data = {
        "entity_id": "binary_sensor.bedroom_motion",
        "new_state": _state("on"),
    }
    sub._handle_state_change(evt)
    # _raw_state was updated but no dispatch fired.
    assert sub.is_kind_active("Bedroom", "motion") is True
    assert dispatches == []


def test_settle_emits_only_true_slots(monkeypatch) -> None:
    hass = make_hass()
    entry_a = fake_room_entry(
        "RoomA",
        **{CONF_MOTION_SENSORS: ["binary_sensor.a_motion"]},
    )
    entry_b = fake_room_entry(
        "RoomB",
        **{CONF_MMWAVE_SENSORS: ["binary_sensor.b_mmwave"]},
    )
    hass.config_entries.async_entries.return_value = [entry_a, entry_b]

    def _states_get(entity_id):
        # A=on, B=off at seed time.
        if entity_id == "binary_sensor.a_motion":
            return _state("on")
        if entity_id == "binary_sensor.b_mmwave":
            return _state("off")
        return None

    hass.states.get = MagicMock(side_effect=_states_get)

    dispatches = []

    def _fake_dispatch(_hass, signal, *args):
        dispatches.append((signal, args))

    monkeypatch.setattr(
        substrate_mod, "async_dispatcher_send", _fake_dispatch,
    )
    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())

    sub.release_boot_settle()
    # Exactly one signal for RoomA / motion / True; nothing for RoomB.
    assert len(dispatches) == 1
    signal, args = dispatches[0]
    assert signal == "ura_substrate_kind_changed"
    assert args == ("RoomA", "motion", True)


def test_settle_empty_house_zero_dispatches(monkeypatch) -> None:
    hass = make_hass()
    entry = fake_room_entry(
        "Bedroom",
        **{CONF_MOTION_SENSORS: ["binary_sensor.bedroom_motion"]},
    )
    hass.config_entries.async_entries.return_value = [entry]
    hass.states.get = MagicMock(return_value=_state("off"))

    dispatches = []
    monkeypatch.setattr(
        substrate_mod, "async_dispatcher_send",
        lambda _hass, signal, *a: dispatches.append((signal, a)),
    )
    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    sub.release_boot_settle()
    assert dispatches == []


def test_post_settle_edges_dispatch(monkeypatch) -> None:
    hass = make_hass()
    entry = fake_room_entry(
        "Bedroom",
        **{CONF_MOTION_SENSORS: ["binary_sensor.bedroom_motion"]},
    )
    hass.config_entries.async_entries.return_value = [entry]
    hass.states.get = MagicMock(return_value=_state("off"))

    dispatches = []
    monkeypatch.setattr(
        substrate_mod, "async_dispatcher_send",
        lambda _hass, signal, *a: dispatches.append((signal, a)),
    )
    sub = OccupancySubstrate(hass)
    _run(sub.async_setup())
    sub.release_boot_settle()
    # Now drive a live state-change edge.
    evt = MagicMock()
    evt.data = {
        "entity_id": "binary_sensor.bedroom_motion",
        "new_state": _state("on"),
    }
    sub._handle_state_change(evt)
    assert dispatches == [
        ("ura_substrate_kind_changed", ("Bedroom", "motion", True)),
    ]
