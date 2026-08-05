"""build/pc-observability: behavioral tests for the three P1 kill switches
plus counter-promotion parity + retrofitted PresenceObservationModeSwitch.

Modeled on the ``test_arriving_rearm_cooldown.py`` HA-mocking preamble
and the ``test_fan_sweep_trio.py`` extract-and-exec pattern for
mutation-sensitive coverage of the signal-deferred restore handler.

Load-bearing invariants tested:

  * PresenceGuestDetectionEnabledSwitch OFF disarms both guest-gate paths
    (Path A ``_guest_gate_armed`` and Path B ``_guest_room_gate_armed``).
  * PresenceArrivingRearmEnabledSwitch OFF renders the arriving re-arm
    cooldown block a no-op (source-anchored).
  * PresenceAwayVetoEnabledSwitch OFF coerces the two AWAY-veto denominators
    passed to ``_inference_engine.infer(...)`` to False (source-anchored).
  * Six new PC-device entities exist AND read the SAME underlying counter/
    state as the corresponding house-state-sensor attr (parity anchor).
  * PresenceObservationModeSwitch restore is now signal-deferred (retrofit).
  * SIGNAL_PRESENCE_COORDINATOR_READY defined + dispatched in async_setup.
"""

from __future__ import annotations

import ast
import os
import re
import sys
import textwrap
from unittest.mock import MagicMock

# Reuse the identical HA-mock preamble from the sibling arriving-rearm test.
# Importing it installs the mocked homeassistant.* modules into sys.modules
# under the exact shape the production PresenceCoordinator import chain
# needs. This is the same trick test_fan_sweep_trio.py uses.
import quality.tests.test_arriving_rearm_cooldown  # noqa: F401


HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PC_PY = os.path.join(
    ROOT,
    "custom_components", "universal_room_automation",
    "domain_coordinators", "presence.py",
)
SIGNALS_PY = os.path.join(
    ROOT,
    "custom_components", "universal_room_automation",
    "domain_coordinators", "signals.py",
)
SWITCH_PY = os.path.join(
    ROOT, "custom_components", "universal_room_automation", "switch.py",
)
SENSOR_PY = os.path.join(
    ROOT, "custom_components", "universal_room_automation", "sensor.py",
)
BINSENSOR_PY = os.path.join(
    ROOT, "custom_components", "universal_room_automation", "binary_sensor.py",
)


def _src(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 1. Signal wiring
# ---------------------------------------------------------------------------


def test_signal_presence_coordinator_ready_defined():
    src = _src(SIGNALS_PY)
    assert "SIGNAL_PRESENCE_COORDINATOR_READY" in src, (
        "New signal must be declared in signals.py"
    )
    assert 'ura_presence_coordinator_ready' in src


def test_signal_dispatched_in_presence_async_setup():
    src = _src(PC_PY)
    # Signal import + dispatch after _ready_event.set() are both required.
    assert "SIGNAL_PRESENCE_COORDINATOR_READY" in src
    m = re.search(
        r"self\._ready_event\.set\(\)[\s\S]{0,600}?SIGNAL_PRESENCE_COORDINATOR_READY",
        src,
    )
    assert m, (
        "PresenceCoordinator.async_setup() must dispatch "
        "SIGNAL_PRESENCE_COORDINATOR_READY after _ready_event.set()"
    )


# ---------------------------------------------------------------------------
# 2. Kill-switch state fields declared
# ---------------------------------------------------------------------------


def test_kill_switch_state_fields_declared():
    src = _src(PC_PY)
    for field in (
        "self._guest_detection_enabled: bool = True",
        "self._arriving_rearm_enabled: bool = True",
        "self._away_veto_enabled: bool = True",
        "self._guest_detection_suppressed_since",
        "self._arriving_rearm_suppressed_since",
        "self._away_veto_suppressed_since",
    ):
        assert field in src, f"Missing PC state field: {field}"


# ---------------------------------------------------------------------------
# 3. Guest-detection kill switch — behavioral (Path A + Path B)
# ---------------------------------------------------------------------------


def _load_extracted(class_name: str, method_name: str, path: str = PC_PY):
    """Extract a method body from source and exec it — mutation-sensitive.

    Mirrors test_fan_sweep_trio._load_handle_hvac_ready. Load-bearing:
    source mutation of the extracted method flows through to the exec'd
    function, so removing the kill-switch guard makes these tests fail.
    """
    body = _extract_method_body(class_name, method_name, path)
    ns: dict = {"_LOGGER": MagicMock()}
    exec(compile(body, f"<extract {class_name}.{method_name}>", "exec"), ns)
    return ns[method_name]


class _GuestGateShim:
    """Minimal namespace for calling ``_guest_gate_armed`` unbound.

    ``_guest_gate_armed`` reads: ``_guest_detection_enabled``,
    ``_unidentified_first_seen``, ``_guest_persistence_check_handle``,
    ``_guest_persistence_seconds``, ``_guest_require_confidence``. It
    calls ``self._confidence_at_least`` and ``self._disarm_guest_gate``
    and ``self._schedule_guest_persistence_recheck``.
    """

    _CONFIDENCE_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}

    def __init__(self, *, enabled: bool):
        self._guest_detection_enabled = enabled
        self._unidentified_first_seen = None
        self._guest_persistence_check_handle = None
        self._guest_persistence_seconds = 0  # fire-immediately path if reached
        self._guest_require_confidence = "medium"
        self._disarm_called = 0
        self._scheduled = 0

    def _confidence_at_least(self, observed, required):
        return (
            self._CONFIDENCE_RANK.get(observed, 0)
            >= self._CONFIDENCE_RANK.get(required, 0)
        )

    def _disarm_guest_gate(self):
        self._disarm_called += 1
        self._unidentified_first_seen = None

    def _schedule_guest_persistence_recheck(self, secs):
        self._scheduled += 1


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def test_guest_gate_armed_returns_false_when_kill_switch_off():
    """Path A: OFF → disarm + return False even with strong evidence.

    Extract-and-exec via _load_extracted (mutation-sensitive): removing
    the ``if not self._guest_detection_enabled`` guard from the real
    presence.py source causes this assertion to fail.
    """
    guest_gate = _load_extracted(
        "PresenceCoordinator", "_guest_gate_armed", PC_PY,
    )
    shim = _GuestGateShim(enabled=False)
    result = guest_gate(
        shim,
        unidentified_count=5,
        census_confidence="high",
        now=_now(),
    )
    assert result is False, (
        "Kill switch OFF must short-circuit Path A regardless of evidence"
    )
    assert shim._disarm_called >= 1, (
        "OFF path must disarm the gate (clear pending arm state)"
    )


def test_guest_gate_armed_returns_true_when_kill_switch_on_and_evidence_present():
    """Path A ON: fire-immediately branch (persistence=0) with valid evidence."""
    guest_gate = _load_extracted(
        "PresenceCoordinator", "_guest_gate_armed", PC_PY,
    )
    shim = _GuestGateShim(enabled=True)
    result = guest_gate(
        shim,
        unidentified_count=2,
        census_confidence="high",
        now=_now(),
    )
    assert result is True, (
        "Kill switch ON + valid evidence must let the gate fire — "
        "confirms the OFF-path guard is the ONLY thing suppressing above"
    )


class _GuestRoomGateShim:
    """Namespace for ``_guest_room_gate_armed``. Reads
    ``_guest_detection_enabled`` and iterates ``_guest_room_state``."""

    def __init__(self, *, enabled: bool):
        self._guest_detection_enabled = enabled
        # A single room with a first_seen well in the past + threshold=1 min
        # so the gate would fire if not for the kill switch.
        from datetime import datetime, timedelta, timezone
        old = datetime.now(timezone.utc) - timedelta(minutes=30)
        self._guest_room_state = {
            "Guest Room": {
                "first_seen": old,
                "current_occupancy_known": False,
                "threshold_min": 1,
            }
        }


def test_guest_room_gate_returns_false_when_kill_switch_off():
    """Path B: OFF → return False even with sustained-unknown occupancy."""
    fn = _load_extracted("PresenceCoordinator", "_guest_room_gate_armed", PC_PY)
    shim = _GuestRoomGateShim(enabled=False)
    assert fn(shim, now=_now()) is False


def test_guest_room_gate_fires_when_kill_switch_on():
    """Path B: ON + threshold satisfied → True. Confirms the ONLY reason
    the OFF case above returns False is the kill-switch guard."""
    fn = _load_extracted("PresenceCoordinator", "_guest_room_gate_armed", PC_PY)
    shim = _GuestRoomGateShim(enabled=True)
    assert fn(shim, now=_now()) is True


# ---------------------------------------------------------------------------
# 4. Arriving re-arm kill switch — source-anchor (behavioral gate is
# deep inside _run_inference; the guard is a single conjunct alongside
# ARRIVING_REARM_COOLDOWN_S > 0). Mutation of either conjunct is caught.
# ---------------------------------------------------------------------------


def test_arriving_rearm_kill_switch_gates_suppression_block():
    src = _src(PC_PY)
    # Both the suppression block AND the arming block must AND with the flag.
    # Suppression block:
    m1 = re.search(
        r"ARRIVING_REARM_COOLDOWN_S > 0\s*\n\s*and self\._arriving_rearm_enabled",
        src,
    )
    assert m1, (
        "Arriving re-arm SUPPRESSION block must be gated on "
        "self._arriving_rearm_enabled — MUTATION removes the guard."
    )
    # Arming block: two conjunctions gated on the flag must appear.
    gated = re.findall(
        r"ARRIVING_REARM_COOLDOWN_S > 0\s*\n\s*and self\._arriving_rearm_enabled",
        src,
    )
    assert len(gated) >= 2, (
        "BOTH the suppression block AND the arming block must be gated on "
        "self._arriving_rearm_enabled (otherwise OFF still latches the timer)."
    )


# ---------------------------------------------------------------------------
# 5. Away-veto kill switch — source anchor on the coercion at infer() call.
# ---------------------------------------------------------------------------


def test_away_veto_kill_switch_coerces_infer_kwargs_when_off():
    src = _src(PC_PY)
    # Rebinding-in-place preserves the kwarg literal at the infer() call
    # (anchored by test_v4714 + test_v570). The kill-switch guard MUST
    # coerce BOTH the path-α and path-β locals to False when OFF.
    m = re.search(
        r"if not self\._away_veto_enabled:\s*\n\s*all_tracked_persons_away = False\s*\n\s*all_trusted_or_lost_away_persons_away = False",
        src,
    )
    assert m, (
        "Away-veto kill switch must rebind BOTH denominators to False "
        "when OFF (path α + path β). MUTATION removes either assignment "
        "→ re-opens the veto."
    )


# ---------------------------------------------------------------------------
# 6. Wake-backstop NM anomaly emission
# ---------------------------------------------------------------------------


def test_wake_backstop_emits_nm_notify():
    src = _src(PC_PY)
    # Must call the extracted helper inside the backstop-fire branch AND
    # the helper must call notification_manager.async_notify.
    assert re.search(
        r"self\._wake_backstop_fires \+= 1[\s\S]{0,1000}?self\._emit_wake_backstop_anomaly\(",
        src,
    ), (
        "Wake-backstop fire site must invoke the NM-emitting helper "
        "(operator directive: sev-2 signal must reach NM history)."
    )
    # Helper body must call NM.async_notify.
    helper_idx = src.find("def _emit_wake_backstop_anomaly")
    assert helper_idx > 0
    end = src.find("\n    def ", helper_idx + 1)
    helper_body = src[helper_idx: end if end > 0 else helper_idx + 2000]
    assert "notification_manager" in helper_body
    assert "async_notify" in helper_body


# ---------------------------------------------------------------------------
# 7. Counter-promotion parity: the new sensors + binary_sensor must read
# the same underlying presence-coord fields the house-state attrs read.
# ---------------------------------------------------------------------------


def test_new_pc_sensors_read_same_backing_fields_as_attrs():
    sensor_src = _src(SENSOR_PY)
    # Sensor classes must be registered in async_setup_entry (existence check).
    for cls in (
        "PresenceCensusCountSensor",
        "PresenceWakeBlockedTicksSensor",
        "PresenceWakeBackstopFiresSensor",
        "PresenceArrivingRearmSuppressedSensor",
        "PresenceArrivingRearmBypassedSensor",
        "PresenceDiagnosticSensor",
    ):
        assert f"class {cls}" in sensor_src
        assert cls + "(hass, entry)" in sensor_src, (
            f"{cls} must be instantiated in async_setup_entry"
        )
    # Each sensor's native_value must read the same field the attr on the
    # giant house-state sensor reads (see sensor.py:~4566-4658).
    parity = {
        "PresenceCensusCountSensor": "_census_count",
        "PresenceWakeBlockedTicksSensor": "_wake_blocked_ticks",
        "PresenceWakeBackstopFiresSensor": "_wake_backstop_fires",
        "PresenceArrivingRearmSuppressedSensor": "_arriving_rearm_suppressed",
        "PresenceArrivingRearmBypassedSensor": "_arriving_rearm_bypassed",
    }
    for cls, field in parity.items():
        class_start = sensor_src.find(f"class {cls}")
        class_end = sensor_src.find("\nclass ", class_start + 1)
        body = (
            sensor_src[class_start:class_end]
            if class_end > 0
            else sensor_src[class_start:]
        )
        assert f'"{field}"' in body, (
            f"{cls} must lazy-read presence.{field} (parity with attr)"
        )


def test_arriving_rearm_active_binary_sensor_registered():
    src = _src(BINSENSOR_PY)
    assert "class PresenceArrivingRearmActiveBinarySensor" in src
    assert "PresenceArrivingRearmActiveBinarySensor(hass, entry)" in src
    # Must read _arriving_rearm_until (same field the attr uses).
    assert "_arriving_rearm_until" in src


def test_diagnostic_sensor_is_disabled_by_default_and_diagnostic_category():
    src = _src(SENSOR_PY)
    class_start = src.find("class PresenceDiagnosticSensor")
    class_end = src.find("\nclass ", class_start + 1)
    body = src[class_start:class_end]
    assert "_attr_entity_registry_enabled_default = False" in body, (
        "PresenceDiagnosticSensor must default to disabled"
    )
    assert "EntityCategory.DIAGNOSTIC" in body, (
        "PresenceDiagnosticSensor must be entity_category=DIAGNOSTIC"
    )
    # Copies the four dark surfaces without deleting them from the
    # house-state sensor (operator adjudication #3 — additive only).
    for surface in (
        "last_veto_decision",
        "signal_consensus_inputs",
        "excluded_persons",
        "zone_verdicts",
    ):
        assert surface in body


def test_house_state_sensor_attrs_preserved_additive_only():
    """Operator adjudication #3: existing attrs remain untouched."""
    src = _src(SENSOR_PY)
    class_start = src.find("class PresenceHouseStateSensor")
    class_end = src.find("\nclass ", class_start + 1)
    body = src[class_start:class_end]
    # Every attr the audit enumerated must still be written on the
    # house-state sensor (no split-off, no removal).
    for attr in (
        '"last_veto_decision"',
        '"signal_consensus_inputs"',
        '"excluded_persons"',
        '"wake_blocked_ticks"',
        '"wake_backstop_fires"',
        '"arriving_rearm_suppressed"',
        '"arriving_rearm_bypassed"',
        '"arriving_rearm_active"',
        '"census_count"',
    ):
        assert attr in body, f"House-state sensor lost attr {attr} — must be additive only"


# ---------------------------------------------------------------------------
# 8. Switch retrofit: PresenceObservationModeSwitch now uses signal-deferred restore.
# ---------------------------------------------------------------------------


def _extract_class_body(class_name: str, path: str) -> str:
    src = _src(path)
    start = src.find(f"class {class_name}")
    assert start > 0, f"{class_name} not found in {path}"
    end = src.find("\nclass ", start + 1)
    return src[start:end] if end > 0 else src[start:]


def test_presence_observation_mode_retrofitted_to_signal_ready():
    body = _extract_class_body("PresenceObservationModeSwitch", SWITCH_PY)
    assert "SIGNAL_PRESENCE_COORDINATOR_READY" in body, (
        "PresenceObservationModeSwitch must use the signal-deferred restore "
        "pattern (retrofit — AUDIT §A.3 concern #1)"
    )
    assert "async_dispatcher_connect" in body
    assert "async_on_remove" in body
    # Old racy pattern must be gone.
    assert "async_call_later" not in body, (
        "Retrofit: async_call_later 5s retry must be removed"
    )
    assert "_retry_restore" not in body, (
        "Retrofit: _retry_restore method must be removed"
    )


def test_presence_observation_mode_has_ready_callback():
    body = _extract_class_body("PresenceObservationModeSwitch", SWITCH_PY)
    assert "_handle_presence_ready" in body
    handle_pos = body.find("def _handle_presence_ready")
    pre = body[max(0, handle_pos - 40):handle_pos]
    assert "@callback" in pre, (
        "_handle_presence_ready must be @callback decorated (Bug #42/#19)"
    )


# ---------------------------------------------------------------------------
# 9. Three new kill switches — hygiene contract mirrors HVACFanControlSwitch.
# ---------------------------------------------------------------------------


KILL_SWITCH_CLASSES = (
    "PresenceGuestDetectionEnabledSwitch",
    "PresenceArrivingRearmEnabledSwitch",
    "PresenceAwayVetoEnabledSwitch",
)


def test_kill_switch_classes_registered():
    src = _src(SWITCH_PY)
    for cls in KILL_SWITCH_CLASSES:
        assert f"class {cls}" in src, f"{cls} class missing"
        assert cls + "(hass, entry)" in src, (
            f"{cls} must be instantiated in async_setup_entry"
        )


def test_kill_switches_use_signal_deferred_restore():
    """All three subclass ``_PresenceKillSwitchBase`` — which is the class
    that carries the SIGNAL_PRESENCE_COORDINATOR_READY subscription.
    """
    src = _src(SWITCH_PY)
    base_start = src.find("class _PresenceKillSwitchBase")
    assert base_start > 0
    base_end = src.find("\nclass PresenceGuestDetectionEnabledSwitch")
    body = src[base_start:base_end]
    assert "SIGNAL_PRESENCE_COORDINATOR_READY" in body
    assert "async_dispatcher_connect" in body
    assert "async_on_remove" in body
    assert "RestoreEntity" in _src(SWITCH_PY)
    # Restore-on-off-only (default ON; restore only the non-default value).
    assert 'last_state.state != "off"' in body, (
        "Restore path must be restore-on-'off'-only (default ON) — mirrors "
        "NMMessagingSuppressSwitch precedent for restore-only-non-default."
    )
    # suppressed_since provenance attribute exposed when OFF.
    assert '"suppressed_since"' in body


def test_kill_switch_defaults_on_and_backs_correct_fields():
    """Each subclass wires the correct backing field on the presence coord."""
    src = _src(SWITCH_PY)
    fields = {
        "PresenceGuestDetectionEnabledSwitch": (
            "_guest_detection_enabled", "_guest_detection_suppressed_since",
        ),
        "PresenceArrivingRearmEnabledSwitch": (
            "_arriving_rearm_enabled", "_arriving_rearm_suppressed_since",
        ),
        "PresenceAwayVetoEnabledSwitch": (
            "_away_veto_enabled", "_away_veto_suppressed_since",
        ),
    }
    for cls, (backing, since) in fields.items():
        body = _extract_class_body(cls, SWITCH_PY)
        assert f'_backing_field = "{backing}"' in body, (
            f"{cls} must wire backing field {backing}"
        )
        assert f'_since_field = "{since}"' in body, (
            f"{cls} must wire since field {since}"
        )


# ---------------------------------------------------------------------------
# 10. Extract + exec the base class's _handle_presence_ready — behavioral
# mutation test analogous to test_fan_sweep_trio's approach for HVAC.
# ---------------------------------------------------------------------------


def _extract_method_body(class_name: str, method_name: str, path: str) -> str:
    src = _src(path)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for m in node.body:
                if (
                    isinstance(m, (ast.AsyncFunctionDef, ast.FunctionDef))
                    and m.name == method_name
                ):
                    return textwrap.dedent(ast.get_source_segment(src, m))
    raise AssertionError(f"{class_name}.{method_name} not found")


def _load_handle_presence_ready():
    body = _extract_method_body(
        "_PresenceKillSwitchBase", "_handle_presence_ready", SWITCH_PY,
    )
    ns: dict = {"_LOGGER": MagicMock()}
    exec(compile(body, "<extract>", "exec"), ns)
    return ns["_handle_presence_ready"]


class _KSShim:
    def __init__(self, presence, deferred):
        self._get_presence = lambda: presence
        self._deferred_value = deferred
        self._backing_field = "_guest_detection_enabled"
        self._since_field = "_guest_detection_suppressed_since"
        self.state_writes = 0

    def async_write_ha_state(self):
        self.state_writes += 1


def test_handle_ready_applies_deferred_false():
    handler = _load_handle_presence_ready()
    presence = MagicMock()
    presence._guest_detection_enabled = True
    shim = _KSShim(presence, deferred=False)
    handler(shim)
    assert presence._guest_detection_enabled is False, (
        "Deferred restore must apply — MUTATION of the setattr line makes "
        "this fail."
    )
    assert shim._deferred_value is None
    assert shim.state_writes >= 1


def test_handle_ready_no_defer_is_noop():
    handler = _load_handle_presence_ready()
    presence = MagicMock()
    presence._guest_detection_enabled = True
    shim = _KSShim(presence, deferred=None)
    handler(shim)
    assert presence._guest_detection_enabled is True, "no-op path"


def test_handle_ready_presence_still_missing_preserves_defer():
    handler = _load_handle_presence_ready()
    shim = _KSShim(presence=None, deferred=False)
    handler(shim)
    assert shim._deferred_value is False, (
        "Missing presence must preserve deferred value for a later retry"
    )
