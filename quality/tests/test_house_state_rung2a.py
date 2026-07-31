"""v5.39.0 House-State Rung 2a — Security auto-follow ENABLED path.

Targeted tests that drive REAL production methods (Bug Class #62 bar):
each test either exercises a real SecurityCoordinator instance's methods
or asserts on the real module-level mapping/severity dicts.

Covered:

1. Debounce constant exists (Numbers-Get-Knobs rung 1) + sane default.
2. ``_HOUSE_STATE_TO_ARMED`` matches the plan's table exactly.
3. ``_STATE_DRIVEN_NM_SEVERITY`` matches INV-4 (HIGH for AWAY/VACATION).
4. ``_handle_house_state_intent`` schedules a debounced fire and a
   subsequent intent CANCELS + REPLACES the prior pending target.
5. ``_fire_state_driven_arming`` under ``observation_mode`` calls neither
   ``handle_arm`` nor ``handle_disarm`` and does NOT emit NM, BUT records
   ``_state_driven_arming_last`` with ``suppressed="observation_mode"``.
6. Happy path fires ``handle_arm`` (the SAME public path manual UI uses)
   and emits ONE NM with severity HIGH for AWAY.
7. DISARMED target routes through ``handle_disarm`` (not handle_arm).
8. Flag-OFF regression: ``_on_house_state_changed_signal`` with flag
   False must NOT queue any intent (Rung 1 invariant preserved).
9. Handler no-op when target equals current and nothing pending.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub heavy HA deps BEFORE any integration import (mirrors the pattern in
# test_v4_6_9_security_aggregator.py).
# ---------------------------------------------------------------------------
_HA_STUBS: dict = {
    "homeassistant": MagicMock(),
    "homeassistant.core": MagicMock(),
    "homeassistant.config_entries": MagicMock(),
    "homeassistant.helpers": MagicMock(),
    "homeassistant.helpers.update_coordinator": MagicMock(),
    "homeassistant.helpers.restore_state": MagicMock(),
    "homeassistant.helpers.dispatcher": MagicMock(),
    "homeassistant.helpers.entity": MagicMock(),
    "homeassistant.helpers.entity_platform": MagicMock(),
    "homeassistant.helpers.event": MagicMock(),
    "homeassistant.helpers.device_registry": MagicMock(),
    "homeassistant.components.sensor": MagicMock(),
    "homeassistant.components.button": MagicMock(),
    "homeassistant.components.binary_sensor": MagicMock(),
    "homeassistant.util": MagicMock(),
    "homeassistant.util.dt": MagicMock(),
    "homeassistant.const": MagicMock(),
}
for _k, _v in _HA_STUBS.items():
    sys.modules.setdefault(_k, _v)

# Provide a real callback pass-through so decorators work.
sys.modules["homeassistant.core"].callback = lambda f: f


# Provide our own controllable async_call_later that stashes calls on hass.
def _async_call_later(hass, delay, cb):
    hass._pending_calls.append({"delay": delay, "cb": cb, "cancelled": False})
    idx = len(hass._pending_calls) - 1

    def _unsub():
        hass._pending_calls[idx]["cancelled"] = True

    return _unsub


sys.modules["homeassistant.helpers.event"].async_call_later = _async_call_later
sys.modules["homeassistant.helpers.event"].async_track_state_change_event = (
    lambda *a, **k: (lambda: None)
)
sys.modules["homeassistant.helpers.event"].async_track_time_interval = (
    lambda *a, **k: (lambda: None)
)
sys.modules["homeassistant.helpers.dispatcher"].async_dispatcher_connect = (
    lambda *a, **k: (lambda: None)
)
sys.modules["homeassistant.helpers.dispatcher"].async_dispatcher_send = (
    lambda *a, **k: None
)

import datetime as _dt

sys.modules["homeassistant.util.dt"].utcnow = lambda: _dt.datetime.now(
    _dt.timezone.utc
)

ROOT = pathlib.Path(__file__).parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Pre-register stub package modules so submodule imports (const, security,
# base, signals) load the FILES directly without executing the heavy
# ``__init__.py`` (which pulls in person_coordinator + real HA).
import types as _types_pkg

_pkg_root = _types_pkg.ModuleType("custom_components")
_pkg_root.__path__ = [str(ROOT / "custom_components")]
sys.modules.setdefault("custom_components", _pkg_root)

_pkg_ura = _types_pkg.ModuleType("custom_components.universal_room_automation")
_pkg_ura.__path__ = [str(ROOT / "custom_components" / "universal_room_automation")]
sys.modules.setdefault("custom_components.universal_room_automation", _pkg_ura)

_pkg_dc = _types_pkg.ModuleType(
    "custom_components.universal_room_automation.domain_coordinators"
)
_pkg_dc.__path__ = [
    str(ROOT / "custom_components" / "universal_room_automation" / "domain_coordinators")
]
sys.modules.setdefault(
    "custom_components.universal_room_automation.domain_coordinators", _pkg_dc
)


from custom_components.universal_room_automation.const import (  # noqa: E402
    SECURITY_AUTO_FOLLOW_ARM_DELAY_S,
)
from custom_components.universal_room_automation.domain_coordinators.security import (  # noqa: E402
    ArmedState,
    SecurityCoordinator,
    _HOUSE_STATE_TO_ARMED,
    _state_driven_severity,
)
from custom_components.universal_room_automation.domain_coordinators.base import (  # noqa: E402
    Intent,
    Severity,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeNM:
    def __init__(self):
        self.calls: list[dict] = []

    async def async_notify(self, **kwargs):
        self.calls.append(kwargs)


class _FakeManager:
    def __init__(self, nm=None):
        self._notification_manager = nm
        self.policy_calls: list[dict] = []

    def record_state_driven_action(self, policy, coordinator, action_record):
        self.policy_calls.append(
            {
                "policy": policy,
                "coordinator": coordinator,
                "record": action_record,
            }
        )


def _make_coord(nm=None):
    hass = NS()
    hass._pending_calls = []
    hass.data = {"universal_room_automation": {}}
    coord = SecurityCoordinator(hass, auto_follow_house_state=True)
    manager = _FakeManager(nm=nm)
    coord.hass.data["universal_room_automation"]["coordinator_manager"] = manager
    # B-H1 fix-up: fire path reads NM from the public hass.data slot, not
    # the private manager attribute.
    if nm is not None:
        coord.hass.data["universal_room_automation"]["notification_manager"] = nm
    return coord, manager, hass


def _live_calls(hass):
    return [c for c in hass._pending_calls if not c["cancelled"]]


# ---------------------------------------------------------------------------
# 1. Debounce constant
# ---------------------------------------------------------------------------


def test_debounce_constant_defined():
    assert isinstance(SECURITY_AUTO_FOLLOW_ARM_DELAY_S, int)
    assert 5 <= SECURITY_AUTO_FOLLOW_ARM_DELAY_S <= 300


# ---------------------------------------------------------------------------
# 2 + 3. Mapping + severity policy
# ---------------------------------------------------------------------------


def test_house_state_to_armed_mapping_complete():
    """A-H3 fix-up: rung-2a table is EXACTLY the 5 mapped house_states.

    home_day / home_evening / home_night / sleep are DELIBERATELY unmapped
    (rung 2b territory, deferred).
    """
    expected = {
        "away": ArmedState.ARMED_AWAY,
        "vacation": ArmedState.ARMED_VACATION,
        "guest": ArmedState.ARMED_HOME,
        "arriving": ArmedState.DISARMED,
        "waking": ArmedState.DISARMED,
    }
    assert _HOUSE_STATE_TO_ARMED == expected
    for k in ("home_day", "home_evening", "home_night", "sleep"):
        assert k not in _HOUSE_STATE_TO_ARMED


def test_severity_direction_aware():
    """A-M3 fix-up: severity is a function of (from, to), not to alone."""
    # Escalations → HIGH
    assert (
        _state_driven_severity(ArmedState.DISARMED, ArmedState.ARMED_AWAY)
        == Severity.HIGH
    )
    assert (
        _state_driven_severity(ArmedState.DISARMED, ArmedState.ARMED_VACATION)
        == Severity.HIGH
    )
    # Guest-arm: DISARMED → ARMED_HOME must be HIGH (per fix-up spec).
    assert (
        _state_driven_severity(ArmedState.DISARMED, ArmedState.ARMED_HOME)
        == Severity.HIGH
    )
    assert (
        _state_driven_severity(ArmedState.ARMED_HOME, ArmedState.ARMED_AWAY)
        == Severity.HIGH
    )
    # De-escalations → MEDIUM
    assert (
        _state_driven_severity(ArmedState.ARMED_AWAY, ArmedState.ARMED_HOME)
        == Severity.MEDIUM
    )
    assert (
        _state_driven_severity(ArmedState.ARMED_AWAY, ArmedState.DISARMED)
        == Severity.MEDIUM
    )
    assert (
        _state_driven_severity(ArmedState.ARMED_HOME, ArmedState.DISARMED)
        == Severity.MEDIUM
    )


# ---------------------------------------------------------------------------
# 4. Debounce cancel-and-replace
# ---------------------------------------------------------------------------


def test_handle_house_state_intent_schedules_debounce():
    coord, _mgr, hass = _make_coord()
    coord._armed_state = ArmedState.DISARMED

    coord._handle_house_state_intent(
        Intent(source="house_state_change", data={"new_state": "away"})
    )
    live1 = _live_calls(hass)
    assert len(live1) == 1
    # ARM target → full debounce delay.
    assert live1[0]["delay"] == float(SECURITY_AUTO_FOLLOW_ARM_DELAY_S)
    assert coord._pending_house_state == "away"

    # Second intent (another ARM target that differs from current) replaces
    # the target and cancels prior.
    coord._handle_house_state_intent(
        Intent(source="house_state_change", data={"new_state": "guest"})
    )
    live2 = _live_calls(hass)
    assert len(live2) == 1
    assert coord._pending_house_state == "guest"


# ---------------------------------------------------------------------------
# 5. Observation mode: suppress actuation, still record diagnostic
# ---------------------------------------------------------------------------


def test_fire_arming_observation_mode_suppresses_but_records():
    nm = _FakeNM()
    coord, mgr, _hass = _make_coord(nm=nm)
    coord.observation_mode = True
    coord._armed_state = ArmedState.DISARMED

    call_log: list[str] = []

    async def _arm(state, *, source="manual"):
        call_log.append(f"arm:{state}")

    async def _disarm(*, source="manual"):
        call_log.append("disarm")

    coord.handle_arm = _arm  # type: ignore[assignment]
    coord.handle_disarm = _disarm  # type: ignore[assignment]

    coord._pending_house_state = "away"
    asyncio.run(coord._fire_state_driven_arming())

    assert call_log == [], (
        "observation_mode MUST NOT invoke handle_arm/handle_disarm"
    )
    assert nm.calls == [], "observation_mode MUST NOT emit NM"
    rec = coord._state_driven_arming_last
    assert rec["from_state"] == ArmedState.DISARMED.value
    assert rec["to_armed"] == ArmedState.ARMED_AWAY.value
    assert rec["house_state"] == "away"
    assert rec["notified"] is False
    assert rec["suppressed"] == "observation_mode"
    assert len(mgr.policy_calls) == 1
    assert mgr.policy_calls[0]["policy"] == "security.auto_follow"


# ---------------------------------------------------------------------------
# 6. Happy path: actuates via public entrypoint + one NM emit
# ---------------------------------------------------------------------------


def test_fire_arming_actuates_and_notifies():
    nm = _FakeNM()
    coord, mgr, _hass = _make_coord(nm=nm)
    coord._armed_state = ArmedState.DISARMED
    coord.observation_mode = False

    call_log: list[str] = []

    async def _arm(state, *, source="manual"):
        call_log.append(f"arm:{state}")
        coord._armed_state = ArmedState(state)

    async def _disarm(*, source="manual"):
        call_log.append("disarm")

    coord.handle_arm = _arm  # type: ignore[assignment]
    coord.handle_disarm = _disarm  # type: ignore[assignment]

    coord._pending_house_state = "away"
    asyncio.run(coord._fire_state_driven_arming())

    assert call_log == ["arm:armed_away"], (
        "auto-follow arming MUST route through handle_arm (public path, "
        "INV-2 no-bypass)"
    )
    assert len(nm.calls) == 1
    nm_call = nm.calls[0]
    assert nm_call["coordinator_id"] == "security"
    assert nm_call["severity"] == Severity.HIGH
    assert "away" in nm_call["message"]
    rec = coord._state_driven_arming_last
    assert rec["notified"] is True
    assert rec["suppressed"] is None
    assert rec["to_armed"] == ArmedState.ARMED_AWAY.value


# ---------------------------------------------------------------------------
# 7. DISARM path uses handle_disarm
# ---------------------------------------------------------------------------


def test_fire_arming_disarm_uses_public_disarm():
    nm = _FakeNM()
    coord, _mgr, _hass = _make_coord(nm=nm)
    coord._armed_state = ArmedState.ARMED_AWAY
    coord.observation_mode = False

    call_log: list[str] = []

    async def _arm(state, *, source="manual"):
        call_log.append(f"arm:{state}")

    async def _disarm(*, source="manual"):
        call_log.append("disarm")
        coord._armed_state = ArmedState.DISARMED

    coord.handle_arm = _arm  # type: ignore[assignment]
    coord.handle_disarm = _disarm  # type: ignore[assignment]

    coord._pending_house_state = "arriving"
    asyncio.run(coord._fire_state_driven_arming())

    assert call_log == ["disarm"]
    assert len(nm.calls) == 1
    assert nm.calls[0]["severity"] == Severity.MEDIUM


# ---------------------------------------------------------------------------
# 8. Flag-OFF regression at the signal bridge
# ---------------------------------------------------------------------------


def test_flag_off_no_intent_queued():
    coord, _mgr, _hass = _make_coord()
    coord._auto_follow_house_state = False

    def _queue(_i):
        raise AssertionError("must not queue when flag off")

    coord.hass.data["universal_room_automation"]["coordinator_manager"] = NS(
        queue_intent=_queue
    )
    coord._on_house_state_changed_signal(
        {"new_state": "away", "old_state": "home_day"}
    )


# ---------------------------------------------------------------------------
# 9. Handler no-op when target already equals current
# ---------------------------------------------------------------------------


def test_handler_no_op_when_target_equals_current():
    """Same-target short-circuit — no scheduling, no churn."""
    coord, _mgr, hass = _make_coord()
    coord._armed_state = ArmedState.ARMED_HOME
    # "guest" maps to ARMED_HOME (same as current) → short-circuit.
    coord._handle_house_state_intent(
        Intent(source="house_state_change", data={"new_state": "guest"})
    )
    assert _live_calls(hass) == []
    assert coord._pending_house_state is None


def test_handler_unmapped_house_state_no_op():
    """A-H3 fix-up: HOME_* / SLEEP are unmapped in rung-2a table."""
    coord, _mgr, hass = _make_coord()
    coord._armed_state = ArmedState.DISARMED
    for hs in ("home_day", "home_evening", "home_night", "sleep"):
        coord._handle_house_state_intent(
            Intent(source="house_state_change", data={"new_state": hs})
        )
    assert _live_calls(hass) == []
    assert coord._pending_house_state is None


# ---------------------------------------------------------------------------
# 10. Asymmetric debounce (A-M1 fix-up)
# ---------------------------------------------------------------------------


def test_arm_target_uses_full_debounce_delay():
    coord, _mgr, hass = _make_coord()
    coord._armed_state = ArmedState.DISARMED
    coord._handle_house_state_intent(
        Intent(source="house_state_change", data={"new_state": "away"})
    )
    live = _live_calls(hass)
    assert len(live) == 1
    assert live[0]["delay"] == float(SECURITY_AUTO_FOLLOW_ARM_DELAY_S)


def test_disarm_target_fires_immediately():
    """DE-escalation (arriving/waking → DISARMED) must be time-critical."""
    coord, _mgr, hass = _make_coord()
    coord._armed_state = ArmedState.ARMED_AWAY
    # Schedule a prior pending ARM fire that must be CANCELLED by the
    # disarm intent (operator at the door wins).
    coord._handle_house_state_intent(
        Intent(source="house_state_change", data={"new_state": "vacation"})
    )
    assert coord._pending_house_state == "vacation"

    coord._handle_house_state_intent(
        Intent(source="house_state_change", data={"new_state": "arriving"})
    )
    live = _live_calls(hass)
    assert len(live) == 1
    # 0-delay fire (immediate) for DISARMED target.
    assert live[0]["delay"] == 0.0
    assert coord._pending_house_state == "arriving"


# ---------------------------------------------------------------------------
# 11. Fire-time gate re-check (A-H1 / C-1 / B-M1 fix-ups)
# ---------------------------------------------------------------------------


def _install_arm_disarm_probes(coord):
    call_log: list[str] = []

    async def _arm(state, *, source="manual"):
        call_log.append(f"arm:{state}:{source}")
        coord._armed_state = ArmedState(state)

    async def _disarm(*, source="manual"):
        call_log.append(f"disarm:{source}")
        coord._armed_state = ArmedState.DISARMED

    coord.handle_arm = _arm  # type: ignore[assignment]
    coord.handle_disarm = _disarm  # type: ignore[assignment]
    return call_log


def test_fire_gate_auto_follow_off_records_suppressed():
    coord, _mgr, _hass = _make_coord()
    call_log = _install_arm_disarm_probes(coord)
    coord._armed_state = ArmedState.DISARMED
    coord._pending_house_state = "away"
    # Flag flipped OFF during the debounce window.
    coord._auto_follow_house_state = False
    asyncio.run(coord._fire_state_driven_arming())
    assert call_log == []
    assert coord._state_driven_arming_last["suppressed"] == "auto_follow_off"


def test_fire_gate_disabled_records_suppressed():
    coord, _mgr, _hass = _make_coord()
    call_log = _install_arm_disarm_probes(coord)
    coord._armed_state = ArmedState.DISARMED
    coord._pending_house_state = "away"
    coord._enabled = False
    asyncio.run(coord._fire_state_driven_arming())
    assert call_log == []
    assert coord._state_driven_arming_last["suppressed"] == "disabled"


def test_fire_gate_shutting_down_skips_silently():
    coord, _mgr, _hass = _make_coord()
    call_log = _install_arm_disarm_probes(coord)
    coord._armed_state = ArmedState.DISARMED
    coord._pending_house_state = "away"
    coord._shutting_down = True
    # Pre-set to sentinel to prove we did NOT record over it.
    coord._state_driven_arming_last = {"marker": "untouched"}
    asyncio.run(coord._fire_state_driven_arming())
    assert call_log == []
    # shutting_down MUST NOT record — teardown may be tearing sensors.
    assert coord._state_driven_arming_last == {"marker": "untouched"}


# ---------------------------------------------------------------------------
# 12. Manual-override hold (A-H2 fix-up) — mutation-anchored
# ---------------------------------------------------------------------------


def test_manual_disarm_suppresses_subsequent_auto_follow_same_house_state():
    """Manual action under a house_state holds until a DISTINCT transition.

    Mutation anchor: if _stamp_manual_action is stubbed out, the second
    "away" fire proceeds (arm call fires) and this test fails.
    """
    coord, mgr, _hass = _make_coord()
    # Manager exposes house_state used by _stamp_manual_action.
    mgr.house_state = "away"
    coord._armed_state = ArmedState.ARMED_AWAY
    coord.observation_mode = False

    # Operator manually disarms while house_state=="away" — REAL handle_disarm
    # (no probe yet) so _stamp_manual_action fires from the real path.
    asyncio.run(coord.handle_disarm())
    assert coord._manual_action_house_state == "away"

    # Now install probes and drive the fire path.
    call_log = _install_arm_disarm_probes(coord)

    # Auto-follow fire for the SAME house_state should be suppressed.
    coord._pending_house_state = "away"
    asyncio.run(coord._fire_state_driven_arming())
    assert call_log == [], (
        "manual hold must suppress auto-follow arm for same house_state"
    )
    assert coord._state_driven_arming_last["suppressed"] == "manual_hold"

    # Distinct house_state ("guest") clears the stamp and proceeds.
    coord._pending_house_state = "guest"
    asyncio.run(coord._fire_state_driven_arming())
    assert call_log == ["arm:armed_home:auto_follow"]
    assert coord._manual_action_house_state is None


def test_auto_follow_source_does_not_stamp():
    """Fire-path invocations must pass source="auto_follow" (no stamp)."""
    coord, mgr, _hass = _make_coord()
    _install_arm_disarm_probes(coord)
    mgr.house_state = "away"
    coord._armed_state = ArmedState.DISARMED
    coord._pending_house_state = "away"
    asyncio.run(coord._fire_state_driven_arming())
    assert coord._manual_action_house_state is None
