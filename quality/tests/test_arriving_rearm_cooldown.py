"""B-2026-08-03-2: Arriving re-arm cooldown after failed deferred_retry.

Load-bearing invariant: after an ARRIVING attempt collapses back to
AWAY, subsequent outdoor-only motion (patio, front porch) must NOT
immediately re-trigger ARRIVING for ARRIVING_REARM_COOLDOWN_S. Real
arrivals — tracker coming home, egress camera, interior tier1 — must
STILL bypass the cooldown so latency to a genuine arrival is
unaffected.

Fix-up C-CRIT-1: the bypass predicate is now a production method
(`PresenceCoordinator._arriving_rearm_bypass`) which these tests IMPORT
and DRIVE directly — no in-file replica. A single tight AST anchor on
the unique call-site marker string confirms the gate still calls the
extracted helper.
"""
from __future__ import annotations

import os
import re
import sys
import types
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Mock homeassistant (mirrors the shape used by
# test_metric_baseline_integration.py so both files coexist in one run).
# ---------------------------------------------------------------------------
def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls, "callback": _identity, "State": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_time_interval": MagicMock(),
        "async_call_later": MagicMock(),
        "async_track_state_change_event": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": MagicMock(),
        "now": MagicMock(),
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(), "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}
for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


HERE = os.path.dirname(__file__)
PRESENCE_PATH = os.path.abspath(
    os.path.join(
        HERE, "..", "..",
        "custom_components", "universal_room_automation",
        "domain_coordinators", "presence.py",
    )
)


def _presence_source() -> str:
    with open(PRESENCE_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Constant + state-init anchors (rung-1 default + kill-switch).
# ---------------------------------------------------------------------------
def test_arriving_rearm_cooldown_const_defined():
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as _p,
    )
    assert _p.ARRIVING_REARM_COOLDOWN_S == 900


def test_arriving_rearm_cooldown_kill_switch_documented():
    src = _presence_source()
    assert re.search(
        r"ARRIVING_REARM_COOLDOWN_S.*(?:disable|kill)",
        src,
        re.IGNORECASE | re.DOTALL,
    ), "Kill-switch (0 disables) semantics must be documented"


def test_arriving_rearm_state_initialized():
    src = _presence_source()
    assert "self._arriving_rearm_until: float = 0.0" in src
    assert "self._arriving_last_was_outdoor_only: bool = False" in src


# ---------------------------------------------------------------------------
# Call-site anchor — the extracted helper is invoked from the gate site.
# Unique-string anchor (not `new_state = None`, which appears >1x).
# ---------------------------------------------------------------------------
def test_gate_calls_extracted_helper():
    src = _presence_source()
    assert "ARRIVING_REARM_CALLSITE_ANCHOR" in src, (
        "Gate call-site anchor comment must remain — extracted "
        "_arriving_rearm_bypass helper is invoked from _run_inference"
    )
    # And the helper call itself.
    assert re.search(
        r"self\._arriving_rearm_bypass\(",
        src,
    ), "Gate site must call self._arriving_rearm_bypass(...)"


def test_gate_suppression_clears_new_state():
    """The suppression path must set `new_state = None` inside the gate.
    Anchor unique to the suppression branch (not any of the other
    `new_state = None` sites), located via the log-message string."""
    src = _presence_source()
    # Extract the block from the suppression log to the next blank line.
    m = re.search(
        r"Arriving re-arm cooldown suppressing AWAY→ARRIVING[\s\S]{0,400}?new_state\s*=\s*None",
        src,
    )
    assert m, "Suppression branch must clear new_state to None"


def test_arm_narrowed_to_outdoor_only_collapse():
    """MED-A1: arming must be gated on _arriving_last_was_outdoor_only."""
    src = _presence_source()
    assert re.search(
        r"current_state == HouseState\.ARRIVING\s*\n\s*and new_state == HouseState\.AWAY\s*\n\s*and self\._arriving_last_was_outdoor_only",
        src,
    ), "Arming must require self._arriving_last_was_outdoor_only (MED-A1)"


# ---------------------------------------------------------------------------
# Drive the extracted bypass predicate directly.
# ---------------------------------------------------------------------------
def _bypass_via_production(**kwargs):
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )
    return PresenceCoordinator._arriving_rearm_bypass(**kwargs)


def test_bypass_outdoor_only_motion_does_not_bypass():
    assert not _bypass_via_production(
        any_indoor_zone_occupied=False,
        census_count=0,
        tracked_count=4,
        all_tracked_persons_away=True,
    )


def test_bypass_interior_tier1_bypasses():
    assert _bypass_via_production(
        any_indoor_zone_occupied=True,
        census_count=0,
        tracked_count=4,
        all_tracked_persons_away=True,
    )


def test_bypass_camera_or_egress_bypasses():
    assert _bypass_via_production(
        any_indoor_zone_occupied=False,
        census_count=1,
        tracked_count=4,
        all_tracked_persons_away=True,
    )


def test_bypass_tracker_coming_home_bypasses():
    assert _bypass_via_production(
        any_indoor_zone_occupied=False,
        census_count=0,
        tracked_count=4,
        all_tracked_persons_away=False,
    )


def test_bypass_empty_tracker_config_does_not_bypass_via_tracker():
    assert not _bypass_via_production(
        any_indoor_zone_occupied=False,
        census_count=0,
        tracked_count=0,
        all_tracked_persons_away=False,
    )


# ---------------------------------------------------------------------------
# 15-attempt flap replay: drive the extracted helper + the same clock/latch
# model the production gate uses. This IS the load-bearing simulation now —
# no in-file _bypass replica.
# ---------------------------------------------------------------------------
def test_flap_replay_cooldown_clips_outdoor_only_attempts():
    """Replay the 2026-08-03 patio flap: 15 outdoor-only ARRIVING attempts
    in 3h. With the cooldown armed, the extracted bypass helper returns
    False for outdoor-only evidence → most attempts are suppressed.
    """
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as _p,
    )
    COOLDOWN = _p.ARRIVING_REARM_COOLDOWN_S
    attempt_times = [
        0, 61, 720, 780, 1440, 1500, 2160, 2220,
        2880, 2940, 3600, 3660, 4320, 4380, 5040,
    ]
    rearm_until = 0.0
    accepted = 0
    for t in attempt_times:
        # Outdoor-only tick: bypass predicate returns False.
        outdoor_only_bypass = _p.PresenceCoordinator._arriving_rearm_bypass(
            any_indoor_zone_occupied=False,
            census_count=0,
            tracked_count=4,
            all_tracked_persons_away=True,
        )
        assert outdoor_only_bypass is False
        if t >= rearm_until:
            # No active cooldown OR expired — attempt accepted, collapses
            # ~61s later, arm cooldown at collapse instant.
            accepted += 1
            rearm_until = (t + 61) + COOLDOWN
        # else: suppressed by cooldown gate.
    assert accepted <= 5, (
        f"Cooldown must clip flap: got {accepted} accepted ARRIVING "
        f"transitions across the 3h window; pre-fix was 15"
    )


def test_sensor_surfaces_arriving_rearm_counters():
    """MED-B (Reviewer B): sensor.py must expose the rearm counters
    alongside wake_blocked_ticks so operators can see live suppression /
    bypass activity from the dashboard."""
    sensor_path = os.path.abspath(
        os.path.join(
            HERE, "..", "..", "custom_components",
            "universal_room_automation", "sensor.py",
        )
    )
    with open(sensor_path, "r", encoding="utf-8") as fh:
        sensor_src = fh.read()
    assert 'attrs["arriving_rearm_suppressed"]' in sensor_src
    assert 'attrs["arriving_rearm_bypassed"]' in sensor_src
    assert 'attrs["arriving_rearm_active"]' in sensor_src
    # Sibling counter still present.
    assert 'attrs["wake_blocked_ticks"]' in sensor_src


def test_flap_replay_tracker_evidence_bypasses_active_cooldown():
    """05:43Z real-family-arrival replay: cooldown is active, tracker
    evidence arrives (all_tracked_persons_away → False). The extracted
    helper must return True → gate bypasses → no added arrival latency.
    """
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as _p,
    )
    assert _p.PresenceCoordinator._arriving_rearm_bypass(
        any_indoor_zone_occupied=False,
        census_count=0,
        tracked_count=4,
        all_tracked_persons_away=False,  # tracker now home
    ) is True
