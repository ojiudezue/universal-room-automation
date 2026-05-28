"""Tests for v4.6.9 D2 — SecurityAggregatorSensor (locks + cameras roll-up).

Mandatory test names from plan acceptance criteria:
  - test_aggregator_with_all_locks_locked_all_cameras_streaming  (→ armed)
  - test_aggregator_with_jammed_lock_reports_alert
  - test_aggregator_with_no_locks_no_cameras_reports_disarmed
  - test_aggregator_attrs_shape_flat

Plus additional coverage:
  - partial state (some locks unlocked, mixed camera streaming)
  - last_state_change_iso reflects most recent across both domains
  - last_state_change_iso is None when no entities
  - active_alert flag forces alert regardless of lock state
  - observation mode does NOT suppress state computation (Bug Class #23)
  - state vocabulary is a StrEnum (Bug Class #22)
  - extra_state_attributes shape is stable (Bug Class #37)
  - all attribute values are JSON-serializable (no Decimal, no datetime)
  - timestamps are UTC ISO 8601 strings (Bug Class #11)
  - sensor registered in CM coordinator_sensors block
  - get_security_aggregator_state() method exists on SecurityCoordinator

Bug-class guards exercised:
  #11  (timezone — all timestamps UTC, .isoformat() called)
  #22  (StrEnum vocabulary — _SecurityAggStatus rejects unknown raw values)
  #23  (observation mode does not gate state computation)
  #29  (every status branch covered: armed/disarmed/partial/alert + no-entities)
  #37  (stable attribute shape — 9 keys always present)
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — run from quality/ with PYTHONPATH=quality
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).parents[2]
SENSOR_PY = ROOT / "custom_components" / "universal_room_automation" / "sensor.py"
SECURITY_PY = (
    ROOT
    / "custom_components"
    / "universal_room_automation"
    / "domain_coordinators"
    / "security.py"
)

# Stub heavy HA deps before any integration import
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

sys.modules["homeassistant.const"].STATE_UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Helpers: build mock states and mock security coordinator
# ---------------------------------------------------------------------------

def _make_state(entity_id: str, state: str, last_changed: datetime | None = None) -> MagicMock:
    """Return a minimal mock HA state object."""
    s = MagicMock()
    s.entity_id = entity_id
    s.state = state
    s.last_changed = last_changed or datetime.now(timezone.utc)
    return s


def _make_security_coordinator(
    lock_entities: list[str],
    camera_entities: list[str],
    lock_states: dict[str, str],
    camera_states: dict[str, str],
    active_alert: bool = False,
    lock_last_changed: dict[str, datetime] | None = None,
    camera_last_changed: dict[str, datetime] | None = None,
) -> MagicMock:
    """Build a mock SecurityCoordinator that returns real states from hass.states."""
    lock_lc = lock_last_changed or {}
    camera_lc = camera_last_changed or {}

    hass = MagicMock()

    def _get_state(entity_id: str):
        all_states = {}
        for eid, st in lock_states.items():
            all_states[eid] = _make_state(eid, st, lock_lc.get(eid))
        for eid, st in camera_states.items():
            all_states[eid] = _make_state(eid, st, camera_lc.get(eid))
        return all_states.get(entity_id)

    hass.states.get = _get_state

    # Import the real _SecurityAggStatus + get_security_aggregator_state
    # by instantiating a minimal SecurityCoordinator-like object that delegates
    # to the actual method.  We do this through source inspection to avoid
    # full HA env setup.
    #
    # Instead, we replicate the coordinator's state data and call the real
    # method body by monkey-patching a thin shim.

    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator._lock_entities = lock_entities
    coordinator._camera_entities = camera_entities
    coordinator._active_alert = active_alert
    coordinator.observation_mode = False

    # Bind the real method from the module to this mock coordinator
    import importlib.util
    import types

    # We parse _SecurityAggStatus and the method from security.py source so
    # we test the real computation logic, not just shape.
    src = SECURITY_PY.read_text()

    # Extract _SecurityAggStatus enum definition
    start = src.index("class _SecurityAggStatus")
    end = src.index("\n\nclass ", start)
    enum_src = src[start:end]

    # Extract get_security_aggregator_state method
    method_start = src.index("    def get_security_aggregator_state")
    # Find end: next method at same indent level
    next_method = src.index("\n    def ", method_start + 1)
    method_src = src[method_start:next_method]

    # Build a minimal exec environment
    try:
        from enum import StrEnum  # type: ignore[attr-defined]
    except ImportError:
        from enum import Enum

        class StrEnum(str, Enum):  # type: ignore[no-redef]
            pass

    import logging
    exec_globals = {
        "StrEnum": StrEnum,
        "datetime": datetime,
        "Any": object,
        "_LOGGER": logging.getLogger("test"),
    }
    exec(compile(enum_src, "<security_agg_status>", "exec"), exec_globals)
    _SecurityAggStatus = exec_globals["_SecurityAggStatus"]

    # Wrap method_src into a standalone function and exec it
    func_src = "def get_security_aggregator_state(self):\n"
    for line in method_src.splitlines()[1:]:
        # Strip 4-space indent added by class body
        func_src += line[4:] + "\n"

    exec_globals2 = {
        **exec_globals,
        "_SecurityAggStatus": _SecurityAggStatus,
    }
    exec(compile(func_src, "<agg_method>", "exec"), exec_globals2)
    bound_method = exec_globals2["get_security_aggregator_state"]

    coordinator.get_security_aggregator_state = lambda: bound_method(coordinator)
    return coordinator, _SecurityAggStatus


# ---------------------------------------------------------------------------
# Structural tests: source file shape
# ---------------------------------------------------------------------------


class TestSourceStructure:
    """Confirm sensor class, registration, and coordinator method exist."""

    def _sensor_src(self) -> str:
        return SENSOR_PY.read_text()

    def _security_src(self) -> str:
        return SECURITY_PY.read_text()

    def test_aggregator_sensor_class_defined(self):
        assert "class SecurityAggregatorSensor" in self._sensor_src()

    def test_aggregator_sensor_registered_in_cm_block(self):
        src = self._sensor_src()
        assert "SecurityAggregatorSensor(hass, entry)" in src

    def test_get_security_aggregator_state_method_defined(self):
        assert "def get_security_aggregator_state" in self._security_src()

    def test_security_agg_status_strenum_defined(self):
        src = self._security_src()
        assert "class _SecurityAggStatus" in src
        assert '"armed"' in src
        assert '"disarmed"' in src
        assert '"partial"' in src
        assert '"alert"' in src

    def test_observation_mode_not_in_aggregator_method(self):
        """Bug Class #23: observation_mode must NOT gate state computation."""
        src = self._security_src()
        start = src.index("def get_security_aggregator_state")
        end = src.index("\n    def ", start + 1)
        block = src[start:end]
        assert "observation_mode" not in block, (
            "observation_mode must NOT appear inside get_security_aggregator_state — "
            "it gates dispatch only, not state observability (Bug Class #23)"
        )

    def test_async_added_to_hass_calls_super(self):
        """Bug Class #1: lifecycle super() call must be present."""
        src = self._sensor_src()
        start = src.index("class SecurityAggregatorSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        assert "await super().async_added_to_hass()" in block

    def test_no_async_create_task_in_sensor(self):
        """Bug Class #19: no untracked background tasks."""
        src = self._sensor_src()
        start = src.index("class SecurityAggregatorSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        assert "async_create_task" not in block

    def test_signal_security_entities_update_subscribed(self):
        """Sensor must subscribe to SIGNAL_SECURITY_ENTITIES_UPDATE for live updates."""
        src = self._sensor_src()
        start = src.index("class SecurityAggregatorSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        assert "SIGNAL_SECURITY_ENTITIES_UPDATE" in block

    def test_aggregator_method_uses_isoformat(self):
        """Bug Class #11: timestamps must be ISO strings, not datetime objects."""
        src = self._security_src()
        start = src.index("def get_security_aggregator_state")
        end = src.index("\n    def ", start + 1)
        block = src[start:end]
        assert ".isoformat()" in block

    def test_nine_attr_keys_in_sensor_extra_state_attributes(self):
        """Bug Class #37: all 9 contract keys must appear in extra_state_attributes."""
        src = self._sensor_src()
        start = src.index("class SecurityAggregatorSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        for key in (
            "locks_total", "locks_locked", "locks_unlocked", "locks_jammed",
            "cameras_total", "cameras_streaming", "cameras_idle", "cameras_offline",
            "last_state_change_iso",
        ):
            assert f'"{key}"' in block, f"Contract key {key!r} missing from sensor block"


# ---------------------------------------------------------------------------
# Behavioral tests using the real coordinator method logic
# ---------------------------------------------------------------------------


class TestAggregatorAllLocksLockedAllCamerasStreaming:
    """test_aggregator_with_all_locks_locked_all_cameras_streaming → armed"""

    def test_aggregator_with_all_locks_locked_all_cameras_streaming(self):
        """All locks locked + at least one camera streaming → armed."""
        coordinator, _Status = _make_security_coordinator(
            lock_entities=["lock.front_door", "lock.back_door"],
            camera_entities=["camera.front_yard"],
            lock_states={"lock.front_door": "locked", "lock.back_door": "locked"},
            camera_states={"camera.front_yard": "streaming"},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["status"] == "armed"
        assert result["locks_total"] == 2
        assert result["locks_locked"] == 2
        assert result["locks_unlocked"] == 0
        assert result["locks_jammed"] == 0
        assert result["cameras_total"] == 1
        assert result["cameras_streaming"] == 1

    def test_armed_with_multiple_cameras_streaming(self):
        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.door"],
            camera_entities=["camera.a", "camera.b"],
            lock_states={"lock.door": "locked"},
            camera_states={"camera.a": "streaming", "camera.b": "streaming"},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["status"] == "armed"
        assert result["cameras_streaming"] == 2


class TestAggregatorJammedLockReportsAlert:
    """test_aggregator_with_jammed_lock_reports_alert"""

    def test_aggregator_with_jammed_lock_reports_alert(self):
        """Any jammed lock → alert regardless of other state."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.front_door", "lock.back_door"],
            camera_entities=["camera.porch"],
            lock_states={"lock.front_door": "locked", "lock.back_door": "jammed"},
            camera_states={"camera.porch": "idle"},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["status"] == "alert"
        assert result["locks_jammed"] == 1

    def test_unavailable_lock_counts_as_jammed(self):
        """Unavailable lock state counts toward locks_jammed."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.door"],
            camera_entities=[],
            lock_states={"lock.door": "unavailable"},
            camera_states={},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["locks_jammed"] == 1
        assert result["status"] == "alert"

    def test_unknown_lock_counts_as_jammed(self):
        """Unknown lock state counts toward locks_jammed."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.door"],
            camera_entities=[],
            lock_states={"lock.door": "unknown"},
            camera_states={},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["locks_jammed"] == 1
        assert result["status"] == "alert"

    def test_active_alert_flag_forces_alert(self):
        """active_alert on coordinator → alert even with all locks fine."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.door"],
            camera_entities=["camera.cam"],
            lock_states={"lock.door": "locked"},
            camera_states={"camera.cam": "streaming"},
            active_alert=True,
        )
        result = coordinator.get_security_aggregator_state()
        assert result["status"] == "alert"


class TestAggregatorNoLocksNoCamerasReportsDisarmed:
    """test_aggregator_with_no_locks_no_cameras_reports_disarmed"""

    def test_aggregator_with_no_locks_no_cameras_reports_disarmed(self):
        """No locks, no cameras → disarmed (nothing to arm)."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=[],
            camera_entities=[],
            lock_states={},
            camera_states={},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["status"] == "disarmed"
        assert result["locks_total"] == 0
        assert result["cameras_total"] == 0

    def test_no_entities_last_state_change_iso_is_none(self):
        """last_state_change_iso must be None when no entities configured."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=[],
            camera_entities=[],
            lock_states={},
            camera_states={},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["last_state_change_iso"] is None


class TestAggregatorAttrsShapeFlat:
    """test_aggregator_attrs_shape_flat — Bug Class #37"""

    def test_aggregator_attrs_shape_flat(self):
        """extra_state_attributes must be a flat dict with exactly 9 int/str/None keys."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.door"],
            camera_entities=["camera.cam"],
            lock_states={"lock.door": "locked"},
            camera_states={"camera.cam": "idle"},
        )
        result = coordinator.get_security_aggregator_state()

        required_keys = {
            "locks_total", "locks_locked", "locks_unlocked", "locks_jammed",
            "cameras_total", "cameras_streaming", "cameras_idle", "cameras_offline",
            "last_state_change_iso",
        }
        # All required keys present
        assert required_keys.issubset(result.keys()), (
            f"Missing keys: {required_keys - result.keys()}"
        )
        # No nested dict values
        for key, val in result.items():
            if key == "status":
                continue  # status is a separate field, not in attrs
            assert not isinstance(val, dict), (
                f"Attribute {key!r} must not be a nested dict; got {type(val)}"
            )

    def test_attrs_all_json_serializable(self):
        """All attr values must be JSON-serializable (no Decimal, no datetime)."""
        from decimal import Decimal
        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.door"],
            camera_entities=["camera.cam"],
            lock_states={"lock.door": "locked"},
            camera_states={"camera.cam": "streaming"},
        )
        result = coordinator.get_security_aggregator_state()
        # Remove 'status' — it's the state, not an attr
        attrs = {k: v for k, v in result.items() if k != "status"}
        # Must not raise
        json.dumps(attrs)
        # No Decimal values
        for val in attrs.values():
            assert not isinstance(val, Decimal), (
                f"Decimal found in attrs — must use int/float/str/None"
            )

    def test_attrs_contain_no_datetime_objects(self):
        """Bug Class #11: last_state_change_iso must be str, not datetime."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.door"],
            camera_entities=[],
            lock_states={"lock.door": "locked"},
            camera_states={},
            lock_last_changed={"lock.door": datetime.now(timezone.utc)},
        )
        result = coordinator.get_security_aggregator_state()
        val = result["last_state_change_iso"]
        if val is not None:
            assert isinstance(val, str), (
                f"last_state_change_iso must be str, got {type(val)}"
            )
            # Must be parseable as UTC-aware ISO 8601
            parsed = datetime.fromisoformat(val)
            assert parsed.tzinfo is not None, "last_state_change_iso must be UTC-aware"

    def test_int_counts_are_integers(self):
        """All count attrs must be int, not float or str."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.a", "lock.b"],
            camera_entities=["camera.c"],
            lock_states={"lock.a": "locked", "lock.b": "unlocked"},
            camera_states={"camera.c": "idle"},
        )
        result = coordinator.get_security_aggregator_state()
        int_keys = [
            "locks_total", "locks_locked", "locks_unlocked", "locks_jammed",
            "cameras_total", "cameras_streaming", "cameras_idle", "cameras_offline",
        ]
        for key in int_keys:
            assert isinstance(result[key], int), (
                f"{key} must be int, got {type(result[key])}"
            )


class TestAggregatorPartialState:
    """partial state — some locks unlocked or mixed camera streaming."""

    def test_partial_when_some_locks_unlocked(self):
        """Some locks locked, none streaming → partial."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.front", "lock.back"],
            camera_entities=[],
            lock_states={"lock.front": "locked", "lock.back": "unlocked"},
            camera_states={},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["status"] == "partial"
        assert result["locks_locked"] == 1
        assert result["locks_unlocked"] == 1

    def test_partial_when_cameras_streaming_but_not_all_locks_locked(self):
        """Camera streaming but some lock unlocked → partial."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.front", "lock.back"],
            camera_entities=["camera.cam"],
            lock_states={"lock.front": "locked", "lock.back": "unlocked"},
            camera_states={"camera.cam": "streaming"},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["status"] == "partial"

    def test_armed_when_no_locks_but_cameras_streaming(self):
        """No locks configured + camera streaming → armed per spec rule.

        Spec rule: locks_locked == locks_total AND cameras_streaming >= 1 → armed.
        With zero locks: 0 == 0 is True, cameras_streaming >= 1 → armed.
        This is the correct spec behavior — no locks means all (zero) locks are
        locked, and the camera is actively streaming.
        """
        coordinator, _ = _make_security_coordinator(
            lock_entities=[],
            camera_entities=["camera.cam"],
            lock_states={},
            camera_states={"camera.cam": "streaming"},
        )
        result = coordinator.get_security_aggregator_state()
        # locks_total=0, cameras_streaming=1 → armed (spec: locks_locked==locks_total AND streaming>=1)
        assert result["status"] == "armed"

    def test_disarmed_when_locks_exist_but_all_unlocked_no_cameras(self):
        """All locks unlocked + no camera streaming → disarmed."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.door"],
            camera_entities=[],
            lock_states={"lock.door": "unlocked"},
            camera_states={},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["status"] == "disarmed"
        assert result["locks_unlocked"] == 1


class TestLastStateChangeIso:
    """last_state_change_iso reflects most recent change across both domains."""

    def test_last_state_change_iso_uses_most_recent_across_locks_and_cameras(self):
        """last_state_change_iso is the most recent last_changed across all entities."""
        older = datetime(2026, 5, 24, 10, 0, 0, tzinfo=timezone.utc)
        newer = datetime(2026, 5, 24, 12, 30, 0, tzinfo=timezone.utc)

        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.door"],
            camera_entities=["camera.cam"],
            lock_states={"lock.door": "locked"},
            camera_states={"camera.cam": "idle"},
            lock_last_changed={"lock.door": older},
            camera_last_changed={"camera.cam": newer},
        )
        result = coordinator.get_security_aggregator_state()
        iso = result["last_state_change_iso"]
        assert iso is not None
        parsed = datetime.fromisoformat(iso)
        assert parsed >= newer, "Should use camera's newer timestamp"

    def test_last_state_change_iso_uses_lock_when_newer(self):
        older = datetime(2026, 5, 24, 8, 0, 0, tzinfo=timezone.utc)
        newer = datetime(2026, 5, 24, 14, 0, 0, tzinfo=timezone.utc)

        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.door"],
            camera_entities=["camera.cam"],
            lock_states={"lock.door": "locked"},
            camera_states={"camera.cam": "streaming"},
            lock_last_changed={"lock.door": newer},
            camera_last_changed={"camera.cam": older},
        )
        result = coordinator.get_security_aggregator_state()
        iso = result["last_state_change_iso"]
        assert iso is not None
        parsed = datetime.fromisoformat(iso)
        assert parsed >= newer, "Should use lock's newer timestamp"

    def test_last_state_change_iso_is_str_not_datetime(self):
        """Bug Class #11: value must be str, not datetime object."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.door"],
            camera_entities=[],
            lock_states={"lock.door": "locked"},
            camera_states={},
            lock_last_changed={"lock.door": datetime.now(timezone.utc)},
        )
        result = coordinator.get_security_aggregator_state()
        val = result["last_state_change_iso"]
        if val is not None:
            assert isinstance(val, str)

    def test_last_state_change_iso_none_when_no_entities(self):
        coordinator, _ = _make_security_coordinator(
            lock_entities=[],
            camera_entities=[],
            lock_states={},
            camera_states={},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["last_state_change_iso"] is None


class TestStatusVocabulary:
    """Bug Class #22: _SecurityAggStatus is a StrEnum with exactly the 4 plan values."""

    def _extract_vocab(self) -> set[str]:
        import re
        src = SECURITY_PY.read_text()
        start = src.index("class _SecurityAggStatus")
        end = src.index("\n\nclass ", start)
        block = src[start:end]
        return set(re.findall(r'= "([^"]+)"', block))

    def test_vocabulary_contains_all_four_plan_states(self):
        vocab = self._extract_vocab()
        required = {"armed", "disarmed", "partial", "alert"}
        assert required.issubset(vocab), f"Missing vocab values: {required - vocab}"

    def test_vocabulary_has_no_extra_states(self):
        """Stable contract: exactly the 4 plan-specified values, no more."""
        vocab = self._extract_vocab()
        allowed = {"armed", "disarmed", "partial", "alert"}
        extra = vocab - allowed
        assert not extra, f"Unexpected vocab values: {extra}"

    def test_status_values_never_dash_or_na(self):
        """PWA contract guard: state vocabulary never contains '—', 'N/A', or ''."""
        forbidden = {"—", "N/A", "n/a", ""}
        vocab = self._extract_vocab()
        assert not vocab & forbidden


class TestObservationModeDoesNotGateState:
    """Bug Class #23: observation_mode gates dispatch only, not state observation."""

    def test_observation_mode_does_not_change_aggregator_result(self):
        """get_security_aggregator_state() must return the same result regardless
        of observation_mode — computation is never suppressed."""
        kwargs = dict(
            lock_entities=["lock.door"],
            camera_entities=["camera.cam"],
            lock_states={"lock.door": "locked"},
            camera_states={"camera.cam": "streaming"},
        )
        coord_normal, _ = _make_security_coordinator(**kwargs, active_alert=False)
        coord_obs, _ = _make_security_coordinator(**kwargs, active_alert=False)
        coord_obs.observation_mode = True  # should have no effect on the method

        result_normal = coord_normal.get_security_aggregator_state()
        result_obs = coord_obs.get_security_aggregator_state()

        assert result_normal["status"] == result_obs["status"]
        assert result_normal["locks_locked"] == result_obs["locks_locked"]
        assert result_normal["cameras_streaming"] == result_obs["cameras_streaming"]

    def test_aggregator_method_source_has_no_observation_mode_guard(self):
        """Source-level guard: get_security_aggregator_state() must not reference
        observation_mode inside its body (Bug Class #23)."""
        src = SECURITY_PY.read_text()
        start = src.index("def get_security_aggregator_state")
        end = src.index("\n    def ", start + 1)
        block = src[start:end]
        assert "observation_mode" not in block


class TestCameraStateCategories:
    """Camera state classification: streaming / idle / offline."""

    def test_unavailable_camera_counts_as_offline(self):
        coordinator, _ = _make_security_coordinator(
            lock_entities=[],
            camera_entities=["camera.cam"],
            lock_states={},
            camera_states={"camera.cam": "unavailable"},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["cameras_offline"] == 1
        assert result["cameras_streaming"] == 0
        assert result["cameras_idle"] == 0

    def test_unknown_camera_counts_as_offline(self):
        coordinator, _ = _make_security_coordinator(
            lock_entities=[],
            camera_entities=["camera.cam"],
            lock_states={},
            camera_states={"camera.cam": "unknown"},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["cameras_offline"] == 1

    def test_idle_camera_counts_as_idle(self):
        coordinator, _ = _make_security_coordinator(
            lock_entities=[],
            camera_entities=["camera.cam"],
            lock_states={},
            camera_states={"camera.cam": "idle"},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["cameras_idle"] == 1

    def test_recording_camera_counts_as_idle(self):
        """'recording' is an active-but-not-streaming state → idle bucket."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=[],
            camera_entities=["camera.cam"],
            lock_states={},
            camera_states={"camera.cam": "recording"},
        )
        result = coordinator.get_security_aggregator_state()
        assert result["cameras_idle"] == 1

    def test_counts_sum_to_total(self):
        """streaming + idle + offline == cameras_total for any state mix."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=[],
            camera_entities=["camera.a", "camera.b", "camera.c"],
            lock_states={},
            camera_states={
                "camera.a": "streaming",
                "camera.b": "idle",
                "camera.c": "unavailable",
            },
        )
        result = coordinator.get_security_aggregator_state()
        total = result["cameras_streaming"] + result["cameras_idle"] + result["cameras_offline"]
        assert total == result["cameras_total"]

    def test_lock_counts_sum_to_total(self):
        """locked + unlocked + jammed == locks_total for any state mix."""
        coordinator, _ = _make_security_coordinator(
            lock_entities=["lock.a", "lock.b", "lock.c"],
            camera_entities=[],
            lock_states={
                "lock.a": "locked",
                "lock.b": "unlocked",
                "lock.c": "unavailable",
            },
            camera_states={},
        )
        result = coordinator.get_security_aggregator_state()
        total = result["locks_locked"] + result["locks_unlocked"] + result["locks_jammed"]
        assert total == result["locks_total"]
