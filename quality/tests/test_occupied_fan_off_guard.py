"""hotfix/occupied-fan-off-guard (2026-08-04).

Behavioral tests for THE INVARIANT:

    HVAC never dispatches a fan turn_OFF for a room whose live occupied
    binary sensor reads 'on' — any house state, any room type.

Exemptions:
    - turn_off_all_managed (operator kill-switch global off)
    - recheck paths (identified by callers not passing room_name)
    - occupancy sensor unavailable/unknown/missing (fail-open)

Reuses the HA-module mocking preamble + `_make_controller` fixture
factory from the sweep-trio test to drive REAL production code paths.
Each test has a companion mutation-drill note describing which single
source change would flip it RED.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

# Reuse the sweep-trio module's HA-mock preamble AND controller factory.
import quality.tests.test_fan_sweep_trio as _sweep_trio  # noqa: F401

from custom_components.universal_room_automation.const import DOMAIN
from custom_components.universal_room_automation.domain_coordinators.hvac_const import (
    DEFAULT_FAN_VACANCY_HOLD,
    FAN_ADOPTED_VACANCY_HOLD_MULT,
)
from custom_components.universal_room_automation.domain_coordinators import (
    hvac_fans as _hvac_fans_mod,
)


def _set_now(dt: datetime) -> None:
    fn = lambda: dt  # noqa: E731
    _hvac_fans_mod.dt_util.now = fn
    _hvac_fans_mod.dt_util.utcnow = fn


@pytest.fixture(autouse=True)
def _restore_dt_util():
    yield
    default = lambda: datetime.utcnow()  # noqa: E731
    _hvac_fans_mod.dt_util.now = default
    _hvac_fans_mod.dt_util.utcnow = default


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# Convenience alias — same signature the sweep-trio file exports.
_make_controller = _sweep_trio._make_controller


def _fan_off_calls(svc_log):
    return [c for c in svc_log if c[1] == "turn_off"]


def _fan_on_calls(svc_log):
    return [c for c in svc_log if c[1] == "turn_on"]


# ---------------------------------------------------------------------------
# THE INVARIANT — guard suppresses OFF for an occupied room
# ---------------------------------------------------------------------------


class TestGuardSuppressesOffForOccupiedRoom:
    """Mutation drill: delete the ``if occ == 'on' and not is_exempt_from_guard``
    branch in hvac_fans._set_fan_state → this test goes RED (fan.turn_off
    IS dispatched, room_fan.is_on flips to False)."""

    def test_off_suppressed_and_state_unchanged(self):
        base = datetime(2026, 8, 4, 19, 0, 0)
        _set_now(base)
        ctrl, room_fan, svc_log, writes = _make_controller(
            entity_on=True, entity_speed=100,
            occupied=False,       # zone conditions say vacant → sweep armed
            occ_binary_on=True,   # but LIVE occupancy sensor is ON
        )
        # Prime: adopt existing external ON.
        _run(ctrl.update(energy_constraint=None, house_state="home_evening"))
        assert room_fan.is_on is True
        assert room_fan.trigger == "external"
        # FAN-MANUAL-1: adoption also opens the ON hold. This test
        # exercises the occupied-fan-off guard suppression; clear the
        # hold so the guard is the sole reason no OFF is dispatched.
        room_fan.manual_on_hold_until = ""

        # Fast-forward past the doubled adopted hold — sweep would fire.
        doubled = int(DEFAULT_FAN_VACANCY_HOLD * FAN_ADOPTED_VACANCY_HOLD_MULT)
        _set_now(base + timedelta(seconds=doubled + 60))
        _run(ctrl.update(energy_constraint=None, house_state="home_evening"))

        # INVARIANT: no fan.turn_off service call was made.
        assert _fan_off_calls(svc_log) == [], (
            "Guard failed: fan.turn_off dispatched into occupied room"
        )
        # State left as-is (fan stays adopted-on).
        assert room_fan.is_on is True, (
            "Guard failed: room_fan.is_on mutated when OFF was suppressed"
        )
        # Episode written with suppressed=True (harm-prevented log).
        conflicts = [
            w for w in writes if w.get("episode_type") == "actuation_conflict"
        ]
        assert len(conflicts) >= 1
        assert conflicts[-1]["attrs"].get("suppressed") is True, (
            "Suppressed OFF must record actuation_conflict with "
            "attrs.suppressed=True"
        )


# ---------------------------------------------------------------------------
# Vacant rooms still sweep — timing unchanged
# ---------------------------------------------------------------------------


class TestVacantRoomStillSweeps:
    """Mutation drill: broaden guard to fire regardless of occ state →
    this test goes RED (turn_off is suppressed for a vacant room)."""

    def test_vacant_room_off_dispatches_normally(self):
        base = datetime(2026, 8, 4, 19, 0, 0)
        _set_now(base)
        ctrl, room_fan, svc_log, writes = _make_controller(
            entity_on=True, entity_speed=100,
            occupied=False, occ_binary_on=False,
        )
        _run(ctrl.update(energy_constraint=None, house_state="home_evening"))
        # FAN-MANUAL-1: clear adoption-opened hold (orthogonal).
        room_fan.manual_on_hold_until = ""
        doubled = int(DEFAULT_FAN_VACANCY_HOLD * FAN_ADOPTED_VACANCY_HOLD_MULT)
        _set_now(base + timedelta(seconds=doubled + 60))
        _run(ctrl.update(energy_constraint=None, house_state="home_evening"))

        assert len(_fan_off_calls(svc_log)) >= 1, (
            "Vacant sweep must dispatch fan.turn_off"
        )
        assert room_fan.is_on is False


# ---------------------------------------------------------------------------
# Unavailable occupancy sensor — guard fails open
# ---------------------------------------------------------------------------


class TestUnavailableOccupancyFailsOpen:
    """Mutation drill: change ``_read_room_occupied_state`` to treat
    unavailable as 'on' → this test goes RED."""

    def test_unavailable_sensor_still_sweeps(self):
        base = datetime(2026, 8, 4, 19, 0, 0)
        _set_now(base)
        ctrl, room_fan, svc_log, writes = _make_controller(
            entity_on=True, entity_speed=100,
            occupied=False, occ_binary_on=False,
        )
        # Override the states.get so the occupancy sensor is unavailable.
        fan_entity = room_fan.fan_entities[0]
        occ_entity = "binary_sensor.study_a_occupied"

        class _S:
            def __init__(self, s, attrs=None):
                self.state = s
                self.attributes = attrs or {}

        def _get(entity_id):
            if entity_id == fan_entity:
                return _S("on", {"percentage": 100})
            if entity_id == occ_entity:
                return _S("unavailable")
            return None

        ctrl.hass.states.get = _get

        _run(ctrl.update(energy_constraint=None, house_state="home_evening"))
        # FAN-MANUAL-1: clear adoption-opened hold (orthogonal).
        room_fan.manual_on_hold_until = ""
        doubled = int(DEFAULT_FAN_VACANCY_HOLD * FAN_ADOPTED_VACANCY_HOLD_MULT)
        _set_now(base + timedelta(seconds=doubled + 60))
        _run(ctrl.update(energy_constraint=None, house_state="home_evening"))

        assert len(_fan_off_calls(svc_log)) >= 1, (
            "Fail-open failed: unavailable occupancy sensor blocked sweep"
        )


# ---------------------------------------------------------------------------
# turn_off_all_managed exemption — still turns off in occupied rooms
# ---------------------------------------------------------------------------


class TestTurnOffAllManagedExempt:
    """Mutation drill: remove the trigger_path == 'turn_off_all_managed'
    exemption → this test goes RED (kill-switch is neutered)."""

    def test_kill_switch_still_turns_off_occupied_room(self):
        base = datetime(2026, 8, 4, 19, 0, 0)
        _set_now(base)
        ctrl, room_fan, svc_log, writes = _make_controller(
            entity_on=True, entity_speed=100,
            occupied=True, occ_binary_on=True,
        )
        room_fan.is_on = True
        _run(ctrl.turn_off_all_managed())

        assert len(_fan_off_calls(svc_log)) >= 1, (
            "Operator kill-switch must NOT be blocked by occupancy guard"
        )
        assert room_fan.is_on is False


# ---------------------------------------------------------------------------
# Activity log written on real OFF dispatches
# ---------------------------------------------------------------------------


class TestActivityLogOnRealOff:
    """Mutation drill: remove the ``self._log_fan_off_activity`` call
    at the tail of _set_fan_state → this test goes RED."""

    def test_activity_row_written_on_vacant_sweep(self):
        base = datetime(2026, 8, 4, 19, 0, 0)
        _set_now(base)
        ctrl, room_fan, svc_log, writes = _make_controller(
            entity_on=True, entity_speed=100,
            occupied=False, occ_binary_on=False,
        )
        activity_calls: list = []

        class _AL:
            def log(self, **kw):  # sync — matches db.log_memory_episode pattern
                activity_calls.append(dict(kw))
                return None

        ctrl.hass.data[DOMAIN]["activity_logger"] = _AL()

        _run(ctrl.update(energy_constraint=None, house_state="home_evening"))
        # FAN-MANUAL-1: clear adoption-opened hold (orthogonal).
        room_fan.manual_on_hold_until = ""
        doubled = int(DEFAULT_FAN_VACANCY_HOLD * FAN_ADOPTED_VACANCY_HOLD_MULT)
        _set_now(base + timedelta(seconds=doubled + 60))
        _run(ctrl.update(energy_constraint=None, house_state="home_evening"))

        fan_offs = [c for c in activity_calls if c.get("action") == "fan_off"]
        assert len(fan_offs) >= 1, (
            "Real OFF dispatch must write an ura_activity_log 'fan_off' row"
        )
        assert fan_offs[0]["room"] == "Study A"


# ---------------------------------------------------------------------------
# Dueling-loop replay — 2026-08-03 evening master-bedroom scenario
# ---------------------------------------------------------------------------


class TestDuelingLoopReplay:
    """Master bedroom, home_evening, temperature-lit fan + vacancy sweep
    dueling: occupied binary_sensor stays ON while mmwave-stillness makes
    zone.room_conditions.occupied read False for the sweep path. Under
    the guard, the fan should stay on across many update cycles with
    ZERO turn_off dispatches and ZERO speed churn.

    Mutation drill: remove the guard → this test goes RED (multiple
    fan.turn_off dispatches accumulate across the 5-cycle replay)."""

    def test_no_off_dispatches_across_replay(self):
        base = datetime(2026, 8, 4, 19, 0, 0)
        _set_now(base)
        ctrl, room_fan, svc_log, writes = _make_controller(
            entity_on=True, entity_speed=100,
            occupied=False, occ_binary_on=True,
        )
        # Prime adoption.
        _run(ctrl.update(energy_constraint=None, house_state="home_evening"))
        assert room_fan.is_on is True

        # Fast-forward past the hold and run 5 update cycles a minute
        # apart — mimics the 19:00-20:43 CDT flap window.
        doubled = int(DEFAULT_FAN_VACANCY_HOLD * FAN_ADOPTED_VACANCY_HOLD_MULT)
        for i in range(5):
            _set_now(base + timedelta(seconds=doubled + 60 + i * 60))
            _run(ctrl.update(energy_constraint=None, house_state="home_evening"))

        assert _fan_off_calls(svc_log) == [], (
            f"Dueling loop: fan.turn_off dispatched during replay "
            f"({len(_fan_off_calls(svc_log))} times)"
        )
        assert room_fan.is_on is True


def test_slugify_matches_ha_for_parenthetical_rooms():
    """M-1 audit (2026-08-04): the kids' bedrooms carry parentheses and the
    old slugifier produced nonexistent entity ids — the guard failed open
    and the observer was blind in exactly those rooms. Pin HA-compatible
    slugs for every live divergent name found by the offline audit."""
    from custom_components.universal_room_automation.memory_facade import _slugify
    assert _slugify("Ziri Bedroom (Bedroom 5)") == "ziri_bedroom_bedroom_5"
    assert _slugify("Jaya Bedroom (Bedroom 4)") == "jaya_bedroom_bedroom_4"
    assert _slugify("Study A") == "study_a"
    assert _slugify("Master  Bedroom") == "master_bedroom"
    assert _slugify("Jaya-Bedroom") == "jaya_bedroom"
