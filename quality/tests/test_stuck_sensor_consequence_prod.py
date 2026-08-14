"""STUCK-SENSOR-1 — production-anchored drills (MED-1 + MED-3).

Fix-up 2026-08-13 (operator directive): the shim-based `RoomShim` tests
in ``test_stuck_sensor_consequence.py`` are truth-table coverage but do
NOT route through production source — a mutation to the coordinator
would not red them (hollow-anchor). This file binds the REAL production
methods (`_p22_stuck_sensor_set` for MED-1, `_promote_dutycycle_to_exclusion`
for MED-3) onto a `_StubCoord` per the `test_sensor_capability_and_role.py`
pattern (extended for the D1 promotion + P22 boot guard surfaces).

Named drill tests:
  * test_p22_defers_exclusion_until_post_boot_observation_PROD (MED-1)
      — Deleting either boot-guard conjunction from coordinator.py's
        _p22_stuck_sensor_set MUST red this test.
  * test_stuck_exclusion_uses_merged_options_room_name_PROD (MED-3)
      — Flipping the merged-options-first accessor to data-first in
        _promote_dutycycle_to_exclusion / _get_config MUST red this test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401 — bootstrap homeassistant mocks

from custom_components.universal_room_automation.const import (
    CONF_ENTRY_TYPE,
    CONF_MOTION_SENSORS,
    CONF_STUCK_SENSOR_EXCLUSION_ENABLED,
    DEFAULT_STUCK_SENSOR_EXCLUSION_ENABLED,
    CORROBORATOR_DISAGREE_S,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_INTEGRATION,
)
from custom_components.universal_room_automation.coordinator import (
    UniversalRoomCoordinator,
)


class _FakeState:
    def __init__(self, state):
        self.state = state


class _FakeStates:
    def __init__(self, mapping):
        self._m = mapping

    def get(self, entity_id):
        s = self._m.get(entity_id)
        return _FakeState(s) if s is not None else None


class _FakeConfigEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, _domain):
        return self._entries


def _bind(method_name, coord):
    """Bind a production coordinator method onto our stub instance."""
    fn = getattr(UniversalRoomCoordinator, method_name)
    return fn.__get__(coord, type(coord))


def _make_stub_coord(*, room_data=None, room_options=None,
                    states=None, cm_options=None):
    """Instantiate a minimal stub coord that binds real production methods.

    Bypasses DataUpdateCoordinator __init__ (mocked out by the harness).
    Only surfaces the promotion + boot-guard helpers need are populated.
    """
    class _StubCoord:
        pass
    coord = _StubCoord()
    coord.hass = MagicMock()
    room_entry = MagicMock()
    room_entry.data = dict(room_data or {})
    room_entry.options = dict(room_options or {})
    room_entry.entry_id = "test_entry"
    coord.entry = room_entry
    integration_entry = MagicMock()
    integration_entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION}
    integration_entry.options = {}
    cm_entry = MagicMock()
    cm_entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}
    cm_entry.options = dict(cm_options or {})
    coord.hass.config_entries = _FakeConfigEntries([integration_entry, cm_entry])
    coord.hass.states = _FakeStates(states or {})
    coord.hass.data = {}
    # State fields the helpers touch.
    coord._sensor_on_since = {}
    coord._post_restart_seen_on = set()
    coord._stuck_sensor_hours = 4.0
    coord._last_corroborator_fire = {}
    coord._effective_corroborators_last_tick = []
    # Bind real production methods.
    coord._is_sensor_on = _bind("_is_sensor_on", coord)
    coord._get_config = _bind("_get_config", coord)
    coord._d2_boot_settle_done = _bind("_d2_boot_settle_done", coord)
    coord._d2_house_state_allows = _bind("_d2_house_state_allows", coord)
    coord._stuck_exclusion_enabled = _bind("_stuck_exclusion_enabled", coord)
    coord._p22_stuck_sensor_set = _bind("_p22_stuck_sensor_set", coord)
    coord._promote_dutycycle_to_exclusion = _bind(
        "_promote_dutycycle_to_exclusion", coord,
    )
    return coord


# ---------------------------------------------------------------------------
# MED-1 — production-anchored P22 boot-guard drill.
# ---------------------------------------------------------------------------


def test_p22_defers_exclusion_until_post_boot_observation_PROD():
    """MED-1 production anchor: exercises coordinator._p22_stuck_sensor_set.

    Mutation drill (see fix-up report): deleting either
    `and _boot_settled` OR `and s in self._post_restart_seen_on` from
    coordinator.py's `_p22_stuck_sensor_set` MUST red this test.
    """
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)

    # Boot-settle NOT done: even w/ 3h59m since AND post-restart-seen,
    # the guard MUST refuse. Nested clear-out of the coordinator-
    # manager registry via hass.data forces the fail-open branch of
    # _d2_boot_settle_done to return True by default — so we install
    # a presence mock that reports _boot_settle_done = False.
    coord = _make_stub_coord()
    coord.hass.data = {
        "universal_room_automation": {
            "coordinator_manager": MagicMock(
                coordinators={"presence": MagicMock(_boot_settle_done=False)},
            ),
        },
    }
    # 5h since — comfortably past the 4h P22 hours threshold, so the ONLY
    # thing keeping this sensor OUT of the set is the boot-settle guard.
    # Deleting `and _boot_settled` in production reddens this branch.
    coord._sensor_on_since["binary_sensor.mmwave_a"] = (
        now - timedelta(hours=5)
    )
    coord._post_restart_seen_on.add("binary_sensor.mmwave_a")
    assert coord._p22_stuck_sensor_set(now) == set()

    # Boot-settle done, but sensor NOT observed live-ON post-restart.
    coord2 = _make_stub_coord()
    coord2.hass.data = {
        "universal_room_automation": {
            "coordinator_manager": MagicMock(
                coordinators={"presence": MagicMock(_boot_settle_done=True)},
            ),
        },
    }
    coord2._sensor_on_since["binary_sensor.mmwave_b"] = (
        now - timedelta(hours=5)
    )
    # NOT in _post_restart_seen_on.
    assert coord2._p22_stuck_sensor_set(now) == set()

    # Both guards satisfied → sensor is in the stuck set.
    coord3 = _make_stub_coord()
    coord3.hass.data = {
        "universal_room_automation": {
            "coordinator_manager": MagicMock(
                coordinators={"presence": MagicMock(_boot_settle_done=True)},
            ),
        },
    }
    coord3._sensor_on_since["binary_sensor.mmwave_c"] = (
        now - timedelta(hours=5)
    )
    coord3._post_restart_seen_on.add("binary_sensor.mmwave_c")
    assert coord3._p22_stuck_sensor_set(now) == {"binary_sensor.mmwave_c"}


# ---------------------------------------------------------------------------
# MED-3 — production-anchored merged-options-first accessor drill.
# ---------------------------------------------------------------------------


def test_stuck_exclusion_uses_merged_options_room_name_PROD():
    """MED-3 production anchor: exercises _get_config's options-first
    contract as consumed by the D1 promotion path.

    Mutation drill: flipping ``self.entry.options.get(key, self.entry.data
    .get(key, default))`` to data-first in coordinator.py `_get_config`
    MUST red this test — the room's motion_sensors list should reflect
    the OPTIONS variant (empty), not the DATA variant (populated).
    """
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)

    # data-side has a corroborator wired; options-side EXPLICITLY empties
    # it. Merged-options-first → the room has NO corroborator, so
    # `_promote_dutycycle_to_exclusion` fails predicate (3) even when
    # everything else is green. Data-first would keep the corroborator
    # and let the promotion fire, reddening the assertion below.
    coord = _make_stub_coord(
        room_data={
            "room_name": "Master",
            CONF_MOTION_SENSORS: ["binary_sensor.pir_old"],
        },
        room_options={
            "room_name": "Master",
            CONF_MOTION_SENSORS: [],
        },
        states={"binary_sensor.pir_old": "off"},
        cm_options={CONF_STUCK_SENSOR_EXCLUSION_ENABLED: True},
    )
    # House state helpers happy (fail-open defaults).
    coord.hass.data = {
        "universal_room_automation": {
            "coordinator_manager": MagicMock(
                coordinators={"presence": MagicMock(
                    _boot_settle_done=True, house_state="home_day",
                )},
            ),
        },
    }

    # Verify _get_config observes the options-first (merged) list.
    got = coord._get_config(CONF_MOTION_SENSORS, [])
    assert got == [], (
        f"MERGED-OPTIONS-FIRST BROKEN: options set motion_sensors=[] but "
        f"_get_config returned {got}. Data-first flip would return the "
        f"data-side list ['binary_sensor.pir_old']."
    )

    # And confirm the promotion path stays consistent: with the effective
    # corroborator list published from the detector, an empty list must
    # fail predicate (3) regardless of other predicates.
    coord._effective_corroborators_last_tick = list(got)  # mirrors detector.
    coord._last_corroborator_fire["binary_sensor.pir_old"] = (
        now - timedelta(seconds=int(CORROBORATOR_DISAGREE_S) + 60)
    )
    assert coord._promote_dutycycle_to_exclusion(
        "binary_sensor.mmwave_x", now,
    ) is False


# ---------------------------------------------------------------------------
# Bonus: D1 predicate (1) kill-switch production anchor.
# ---------------------------------------------------------------------------


def test_kill_switch_short_circuits_promotion_PROD():
    """Predicate (1) production anchor: `_stuck_exclusion_enabled` reads
    the nm_cycle_a_knob cache; flipping the CM options key MUST route
    through the real knob-lookup helper (not a monkeypatch).
    """
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    # Kill switch OFF via CM options.
    coord = _make_stub_coord(
        room_data={"room_name": "R"},
        room_options={},
        cm_options={CONF_STUCK_SENSOR_EXCLUSION_ENABLED: False},
    )
    # Invalidate the process-wide knob cache so this test observes the
    # freshly-set option (other suites in this tree may have primed the
    # cache with True from a sibling test).
    from custom_components.universal_room_automation.domain_coordinators\
        ._nm_cycle_a import invalidate_knob_cache
    invalidate_knob_cache()
    coord._effective_corroborators_last_tick = ["binary_sensor.pir"]
    coord._last_corroborator_fire["binary_sensor.pir"] = (
        now - timedelta(seconds=int(CORROBORATOR_DISAGREE_S) + 60)
    )
    assert coord._promote_dutycycle_to_exclusion(
        "binary_sensor.mmwave", now,
    ) is False
    # Restore cache to defaults so downstream tests aren't affected.
    invalidate_knob_cache()
