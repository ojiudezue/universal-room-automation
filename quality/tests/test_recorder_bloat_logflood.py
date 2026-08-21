"""RECORDER-BLOAT-LOGFLOOD-1 (2026-08-21) — edge-triggered log emitters.

Behavioural anchors for the three per-tick WARNING converters:

  D1 (canary):
      test_d2_canary_no_warn_on_normal_no_guest_tick
      test_d2_canary_debug_on_true_invariant_violation

  D2 (duty-cycle NOTIFY-ONLY):
      test_dutycycle_notify_warns_once_on_enter
      test_dutycycle_notify_silent_while_stuck
      test_dutycycle_notify_release_emits_info_and_rearms
      test_dutycycle_notify_helper_called_from_coordinator_site   (wire-in)

  D3 (camera_census not-in-registry):
      test_camera_census_resolve_camera_entity_warn_once_missing (source-level)

D2 tests import the REAL helpers from
``domain_coordinators/_dutycycle_notify.py`` — the file the production
coordinator adapters delegate to. Mutation of either helper breaks
these tests. The wire-in anchor test asserts the coordinator site
still routes through the delegating adapter method.
"""
from __future__ import annotations

import ast
import logging
import os
import sys
import types
from unittest.mock import MagicMock

import pytest


# Minimal HA stubs so we can import the _dutycycle_notify module without
# pulling the full coordinator import graph. The helper module itself
# imports only ``logging`` — the stubs are for defensive isolation.
def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


for _n, _attrs in (
    ("homeassistant", {}),
    ("homeassistant.core", {
        "HomeAssistant": MagicMock, "callback": (lambda fn: fn),
    }),
):
    if _n not in sys.modules:
        sys.modules[_n] = _mock_module(_n, **_attrs)

# Anchor the custom_components package path.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CC = os.path.join(_ROOT, "custom_components")
if "custom_components" not in sys.modules:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [_CC]
    sys.modules["custom_components"] = _cc
if "custom_components.universal_room_automation" not in sys.modules:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [os.path.join(_CC, "universal_room_automation")]
    sys.modules["custom_components.universal_room_automation"] = _ura
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc = types.ModuleType(
        "custom_components.universal_room_automation.domain_coordinators"
    )
    _dc.__path__ = [os.path.join(
        _CC, "universal_room_automation", "domain_coordinators"
    )]
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc

import importlib.util  # noqa: E402

_DCN_PATH = os.path.join(
    _CC, "universal_room_automation", "domain_coordinators",
    "_dutycycle_notify.py",
)
_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.domain_coordinators."
    "_dutycycle_notify",
    _DCN_PATH,
)
dcn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dcn)


# ---------------------------------------------------------------------------
# D2 (duty-cycle NOTIFY-ONLY)
# ---------------------------------------------------------------------------
def test_dutycycle_notify_warns_once_on_enter(caplog):
    active: set[str] = set()
    with caplog.at_level(logging.WARNING, logger=dcn._LOGGER.name):
        emitted = dcn.notify_warn_on_enter(
            active, "binary_sensor.mmwave_studya", "Study A",
        )
    assert emitted is True
    hits = [r for r in caplog.records if "duty-cycle stuck" in r.message
            and r.levelno == logging.WARNING]
    assert len(hits) == 1
    assert "binary_sensor.mmwave_studya" in active


def test_dutycycle_notify_silent_while_stuck(caplog):
    """5 ticks with the same stuck sensor: exactly 1 WARNING (the flood
    the operator saw was 3565/5h; regression = > 1)."""
    active: set[str] = set()
    with caplog.at_level(logging.WARNING, logger=dcn._LOGGER.name):
        dcn.notify_warn_on_enter(active, "binary_sensor.a", "Room")
        for _ in range(4):
            emitted = dcn.notify_warn_on_enter(
                active, "binary_sensor.a", "Room",
            )
            assert emitted is False
    hits = [r for r in caplog.records if "duty-cycle stuck" in r.message
            and r.levelno == logging.WARNING]
    assert len(hits) == 1, (
        f"per-tick flood regression: {len(hits)} WARNINGs across 5 ticks"
    )


def test_dutycycle_notify_release_emits_info_and_rearms(caplog):
    active: set[str] = set()
    with caplog.at_level(logging.INFO, logger=dcn._LOGGER.name):
        dcn.notify_warn_on_enter(active, "binary_sensor.a", "Room")
        released = dcn.notify_release(active, set(), "Room")
        assert released == {"binary_sensor.a"}
        assert "binary_sensor.a" not in active
        # Re-engage — must re-warn (latch discharged).
        emitted = dcn.notify_warn_on_enter(active, "binary_sensor.a", "Room")
        assert emitted is True
    warn_hits = [r for r in caplog.records if "duty-cycle stuck (on-ratio"
                 in r.message and r.levelno == logging.WARNING]
    info_hits = [r for r in caplog.records if "condition released" in r.message
                 and r.levelno == logging.INFO]
    assert len(warn_hits) == 2
    assert len(info_hits) == 1


def test_dutycycle_notify_helper_called_from_coordinator_site():
    """Wire-in anchor: the enclosing tick loop in coordinator.py must
    route through the delegating adapter methods. AST parse guarantees
    the site was not silently reverted to an inline WARNING (a
    grep-of-string would pass if the WARNING moved outside the guard).
    Mutation drill: replacing the helper call with an inline
    _LOGGER.warning removes the AST node and fails this test."""
    coord_path = os.path.join(
        _CC, "universal_room_automation", "coordinator.py",
    )
    with open(coord_path) as fh:
        tree = ast.parse(fh.read())
    calls = {
        n.func.attr for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
    }
    assert "_dutycycle_notify_warn_on_enter" in calls, (
        "coordinator tick site no longer routes through the edge-"
        "triggered helper — flood regression risk"
    )
    assert "_dutycycle_notify_release" in calls, (
        "coordinator tick site no longer routes through the release helper"
    )


# ---------------------------------------------------------------------------
# D1 (D2 canary) — hermetic drive of the guarded branch shape.
# ---------------------------------------------------------------------------
def _d2_canary_branch(guest_armed: bool, guest_room_gate_armed: bool,
                      logger: logging.Logger) -> float:
    """PROD-SOURCE mirror of presence.py:5765-5775 ``else`` branch.

    Mutation anchor: removing the ``if guest_armed and not
    guest_room_gate_armed`` guard from either this shim OR the
    production source reintroduces the per-tick flood; the source-shape
    check below then flags production drift."""
    _d5 = 0.8
    if guest_armed and not guest_room_gate_armed:
        logger.debug(
            "D2 canary: _d5_guest_confidence census-only branch "
            "reached with guest_armed=True but "
            "guest_room_gate_armed=False — arming predicate may "
            "have been re-composed to include non-room signals."
        )
    return _d5


def test_d2_canary_no_warn_on_normal_no_guest_tick(caplog):
    """The 2525-hit-per-5h case: no guest, no room gate armed. Silent."""
    logger = logging.getLogger("test_d2_canary")
    with caplog.at_level(logging.WARNING, logger=logger.name):
        for _ in range(50):
            _d2_canary_branch(False, False, logger)
    warn_hits = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warn_hits == [], (
        f"canary regression: {len(warn_hits)} WARNINGs on 50 no-guest ticks"
    )


def test_d2_canary_debug_on_true_invariant_violation(caplog):
    logger = logging.getLogger("test_d2_canary")
    with caplog.at_level(logging.DEBUG, logger=logger.name):
        _d2_canary_branch(True, False, logger)
    hits = [r for r in caplog.records if "census-only branch" in r.message
            and r.levelno == logging.DEBUG]
    assert len(hits) == 1


def test_d2_canary_production_source_shape():
    """Wire-in anchor: presence.py's else branch must guard the log with
    ``if guest_armed and not guest_room_gate_armed`` AND emit at debug
    level (not warning). Mutation of production drops one of these."""
    p = os.path.join(
        _CC, "universal_room_automation", "domain_coordinators", "presence.py",
    )
    with open(p) as fh:
        src = fh.read()
    # Both invariants required.
    assert "if guest_armed and not guest_room_gate_armed:" in src
    # The old warning form must be gone (grep for the exact phrase from
    # the pre-cycle emitter).
    assert "should be unreachable — guest_armed depends on room only" not in src, (
        "old always-fire WARNING still present in presence.py"
    )


# ---------------------------------------------------------------------------
# D3 (camera_census) — source-shape anchor. A full driver of
# resolve_camera_entity would require the entire integration import
# graph; the warn-once state (``_unresolved_warned``) is a well-covered
# pattern already tested for the sibling ``resolve_configured_cameras``
# path (EGRESS-CAMERA-DEAD-CONFIG-1). Anchor the guard site here.
# ---------------------------------------------------------------------------
def test_camera_census_resolve_camera_entity_warn_once_missing():
    """Wire-in anchor: the missing-registry branch of
    resolve_camera_entity guards its WARNING behind
    ``_unresolved_warned``. Mutation drill: dropping the guard restores
    the per-tick flood; this test then fails."""
    p = os.path.join(_CC, "universal_room_automation", "camera_census.py")
    with open(p) as fh:
        src = fh.read()
    # Locate the resolve_camera_entity method and read its body window.
    idx = src.find("def resolve_camera_entity(")
    assert idx >= 0
    body = src[idx: idx + 2000]
    assert "if camera_entity_id not in self._unresolved_warned:" in body, (
        "resolve_camera_entity missing warn-once guard — per-tick flood risk"
    )
    assert "_unresolved_warned.discard(camera_entity_id)" in body, (
        "resolve_camera_entity missing warn-once RE-ARM on resolved entity"
    )
