"""C-MED-2 substrate-gap canary — focused MagicMock tests.

Exercises the canary block extracted into
``UniversalRoomCoordinator._check_substrate_gap`` (coordinator.py). The
canary WARN-logs ONCE per (room, entity) per boot when a Tier-1 sensor
from a room's CONF list is currently ON but is NOT tracked by the
shared ``OccupancySubstrate`` — the v4.7.24-class regression symptom
(v5.12.0 D4).

Four cases (Review C C-MED-2):
  1. WARN when sensor is ON and ABSENT from the substrate map.
  2. Silent when sensor IS tracked.
  3. Once-per-(room, entity) per boot — second invocation silent.
  4. Silent when hass.data[DOMAIN]["occupancy_substrate"] is None.
"""

from __future__ import annotations

import importlib.util  # noqa: F401 — required for _provenance_harness
import logging
from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

from custom_components.universal_room_automation.const import DOMAIN
from custom_components.universal_room_automation.coordinator import (
    UniversalRoomCoordinator,
)


class _FakeState:
    def __init__(self, state: str) -> None:
        self.state = state


def _make_coord(hass) -> UniversalRoomCoordinator:
    """Build a UniversalRoomCoordinator via object.__new__ and seed only
    the attributes ``_check_substrate_gap`` reads.

    Pattern borrowed from test_prediction_sensor_kill_list.py:140 and
    test_arbitrate_solar_attainability_ladder.py:1222. Wrinkle unique to
    this class: ``UniversalRoomCoordinator`` inherits from ``DataUpdateCoordinator``
    which the harness mocks as ``MagicMock``, so a normal ``obj.attr = x``
    assignment routes through Mock's __setattr__ and raises
    (``_mock_methods`` sentinel absent because Mock.__init__ never ran).
    Use ``object.__setattr__`` to bypass Mock's plumbing entirely.
    """
    c = object.__new__(UniversalRoomCoordinator)

    def _set(name, value):
        object.__setattr__(c, name, value)

    _set("hass", hass)
    _set("_substrate_gap_warned", set())
    # `_is_sensor_on` reads self.entry.data for the "unavailable" debug
    # log path; seed a minimal entry so no AttributeError leaks.
    entry = MagicMock()
    entry.data = {"room_name": "TestRoom"}
    _set("entry", entry)
    return c


def _seed_substrate(hass, entity_to_room_kind: dict) -> None:
    substrate = MagicMock()
    substrate._entity_to_room_kind = entity_to_room_kind
    hass.data.setdefault(DOMAIN, {})["occupancy_substrate"] = substrate


# ---------------------------------------------------------------------------
# Case 1 — WARN when sensor ON and NOT in substrate map
# ---------------------------------------------------------------------------


def test_canary_warns_when_sensor_on_but_untracked(caplog) -> None:
    hass = make_hass()
    hass.states.get = MagicMock(
        side_effect=lambda eid: (
            _FakeState("on") if eid == "binary_sensor.gap_motion" else None
        ),
    )
    # Substrate exists but does NOT track our sensor.
    _seed_substrate(hass, entity_to_room_kind={})
    c = _make_coord(hass)

    with caplog.at_level(
        logging.WARNING,
        logger="custom_components.universal_room_automation.coordinator",
    ):
        c._check_substrate_gap(
            "TestRoom",
            ["binary_sensor.gap_motion"],
            [],
            [],
        )

    matches = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "substrate gap" in r.message
    ]
    assert len(matches) == 1, (
        f"expected one substrate-gap WARN; got records={[r.message for r in caplog.records]}"
    )
    assert "binary_sensor.gap_motion" in matches[0].message
    # The (room, entity) was recorded to prevent re-warning.
    assert "binary_sensor.gap_motion" in c._substrate_gap_warned


# ---------------------------------------------------------------------------
# Case 2 — silent when sensor IS tracked
# ---------------------------------------------------------------------------


def test_canary_silent_when_sensor_tracked(caplog) -> None:
    hass = make_hass()
    hass.states.get = MagicMock(return_value=_FakeState("on"))
    _seed_substrate(
        hass,
        entity_to_room_kind={
            "binary_sensor.tracked_motion": ("TestRoom", "motion"),
        },
    )
    c = _make_coord(hass)

    with caplog.at_level(
        logging.WARNING,
        logger="custom_components.universal_room_automation.coordinator",
    ):
        c._check_substrate_gap(
            "TestRoom",
            ["binary_sensor.tracked_motion"],
            [],
            [],
        )

    assert not any(
        "substrate gap" in r.message for r in caplog.records
    ), f"canary fired when it should be silent; records={[r.message for r in caplog.records]}"
    assert "binary_sensor.tracked_motion" not in c._substrate_gap_warned


# ---------------------------------------------------------------------------
# Case 3 — once per (room, entity) per boot
# ---------------------------------------------------------------------------


def test_canary_once_per_room_entity_per_boot(caplog) -> None:
    hass = make_hass()
    hass.states.get = MagicMock(return_value=_FakeState("on"))
    _seed_substrate(hass, entity_to_room_kind={})
    c = _make_coord(hass)

    with caplog.at_level(
        logging.WARNING,
        logger="custom_components.universal_room_automation.coordinator",
    ):
        c._check_substrate_gap(
            "TestRoom", ["binary_sensor.gap_motion"], [], [],
        )
        c._check_substrate_gap(
            "TestRoom", ["binary_sensor.gap_motion"], [], [],
        )

    matches = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "substrate gap" in r.message
    ]
    assert len(matches) == 1, (
        f"expected exactly one WARN across two invocations; got {len(matches)} "
        f"records={[r.message for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# Case 4 — silent when occupancy_substrate is None
# ---------------------------------------------------------------------------


def test_canary_silent_when_substrate_absent(caplog) -> None:
    hass = make_hass()
    hass.states.get = MagicMock(return_value=_FakeState("on"))
    # Substrate absent (None).
    hass.data.setdefault(DOMAIN, {})["occupancy_substrate"] = None
    c = _make_coord(hass)

    with caplog.at_level(
        logging.WARNING,
        logger="custom_components.universal_room_automation.coordinator",
    ):
        c._check_substrate_gap(
            "TestRoom", ["binary_sensor.gap_motion"], [], [],
        )

    assert not any(
        "substrate gap" in r.message for r in caplog.records
    ), (
        "canary must be silent when substrate not registered; "
        f"records={[r.message for r in caplog.records]}"
    )
    assert "binary_sensor.gap_motion" not in c._substrate_gap_warned
