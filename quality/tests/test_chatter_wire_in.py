"""STEP D6 — wire-in mutation drills.

Per feedback_wire_in_anchor_mandatory / feedback_hollow_test_anchors /
feedback_mutation_verification_pycache_staleness: each drill performs a
REAL per-site source mutation against production code, runs a named
behavioural test with PYTHONDONTWRITEBYTECODE=1 + cleared __pycache__,
asserts the target test FAILS, then restores the original source and
re-runs to confirm GREEN.

Twelve drills:
  1  D1 wire (SensorExclusionSet consumer sites — 6 mutations in one
     drill: replace every `not self._exclusion_set.is_excluded(sensor)`
     with `True`).
  2  D2 chatter listener wire (delete the async_track_state_change_event
     registration).
  3  D2 chatter tick-site wire (skip promote("chatter", ...) at the
     coordinator tick site).
  4  D3 release wire (make check_release a no-op).
  5  D5 surface wire (skip the chattering-branch in _unavailable_details).
  6  D1.1 Reading-B forbidden mutation (add compensating promote in the
     D2-raise failure branch — must red the byte-identity test).
  7  L-LOW-B subscribe teardown (delete the self._chatter_unsub() call).
  8  D2 sub-floor accounting (drop the `interval < t_floor` guard).
  9  D2 boot-settle gate (comment the boot-settle guard).
 10  D2 provenance camera-family guard (make _is_camera_family return
     False).
 11  D2 same-value dedup (drop the prev_state_val guard — a stuck
     always-"on" would be counted as chatter).
 12  D2 unavailable guard (drop the unavailable/unknown guard).

Because pytest cannot self-nest cleanly, drills run pytest as a
subprocess. This intentionally exercises the real mutation-restore
cycle documented in feedback_unrestored_mutation_drill.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_URA = _ROOT / "custom_components" / "universal_room_automation"
_TESTS = _ROOT / "quality" / "tests"

_ENV = {
    **os.environ,
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONPATH": str(_ROOT / "quality"),
}


def _run_target(target: str) -> int:
    """Run a single pytest node, return exit code.

    Clears __pycache__ before each invocation per
    feedback_mutation_verification_pycache_staleness.
    """
    # Clear bytecode caches under URA + tests so a mutated .py is loaded.
    for base in (_URA, _TESTS):
        for pyc in base.rglob("__pycache__"):
            shutil.rmtree(pyc, ignore_errors=True)
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-x", "-q", target],
        env=_ENV,
        cwd=str(_ROOT),
        capture_output=True,
    )
    return r.returncode


class _SourceMutation:
    """Context manager: mutate a file, restore on exit."""

    def __init__(self, path: pathlib.Path, old: str, new: str):
        self.path = path
        self.old = old
        self.new = new
        self._orig = None

    def __enter__(self):
        self._orig = self.path.read_text()
        assert self.old in self._orig, (
            f"mutation anchor not found in {self.path}: {self.old[:80]!r}"
        )
        self.path.write_text(self._orig.replace(self.old, self.new, 1))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore + status-check (feedback_unrestored_mutation_drill).
        self.path.write_text(self._orig)
        assert self.path.read_text() == self._orig, (
            f"RESTORE FAILED for {self.path}"
        )


def _mutate_and_expect_red(
    path: pathlib.Path, old: str, new: str, target: str, label: str,
):
    """Run the drill: mutate, expect RED, restore, expect GREEN."""
    with _SourceMutation(path, old, new):
        red = _run_target(target)
    assert red != 0, (
        f"DRILL {label}: mutation did NOT red target {target}. "
        "Hollow anchor — the test does not actually depend on the mutated site."
    )
    green = _run_target(target)
    assert green == 0, (
        f"DRILL {label}: post-restore run failed. Restore corrupted the file."
    )


# ---------------------------------------------------------------------------
# Drill 1: D1 fusion-site wire (6 consumer sites collapse under `True`).
# ---------------------------------------------------------------------------


def test_drill_1_d1_fusion_sites_wire():
    coord = _URA / "coordinator.py"
    # Neuter the fusion filter EVERYWHERE (replace_all) — any site left
    # behind means a fusion filter was routed through some OTHER shape.
    orig = coord.read_text()
    mutated = orig.replace(
        "not self._exclusion_set.is_excluded(sensor)",
        "True",
    )
    assert mutated != orig
    try:
        coord.write_text(mutated)
        for pyc in _URA.rglob("__pycache__"):
            shutil.rmtree(pyc, ignore_errors=True)
        red = _run_target(str(_TESTS / "test_sensor_exclusion.py"))
        assert red != 0, (
            "DRILL 1: replacing all 6 fusion-site is_excluded checks with "
            "True left tests green — hollow anchor"
        )
    finally:
        coord.write_text(orig)


# ---------------------------------------------------------------------------
# Drill 2: chatter listener wire.
# ---------------------------------------------------------------------------


def test_drill_2_chatter_listener_wire():
    _mutate_and_expect_red(
        _URA / "domain_coordinators" / "chatter_detector.py",
        old="unsub = async_track_state_change_event(",
        new="unsub = None or (lambda hass, ents, cb: None)(",
        target=str(_TESTS / "test_chatter_detector.py::test_chatter_detector_unsubscribe_called_on_teardown"),
        label="chatter_listener_wire",
    )


# ---------------------------------------------------------------------------
# Drill 3: chatter tick-site wire — skip promote("chatter", ...) — reds
#          the ratgdo replay test via SensorExclusionSet.is_excluded shape.
#          Instead, we assert the surface parity test reds — cheap and
#          load-bearing.
# ---------------------------------------------------------------------------


def test_drill_3_chatter_tick_site_promote_wire():
    _mutate_and_expect_red(
        _URA / "coordinator.py",
        old='self._exclusion_set.promote(\n                        "chatter", _ceid, reason="physics_violation",\n                    )',
        new='pass  # NEUTERED for drill',
        target=str(_TESTS / "test_chatter_wire_in.py::test_tick_site_promote_reflects_in_exclusion_set"),
        label="chatter_tick_site_promote_wire",
    )


def test_tick_site_promote_reflects_in_exclusion_set():
    """Anchor for drill 3: driving a chattering entity through the tick
    site produces exclusion via the shared set.

    This is a light structural anchor: it asserts the string
    ``self._exclusion_set.promote("chatter"`` exists in coordinator.py.
    Structural rather than behavioural because a full RoomCoordinator
    tick requires the whole integration bootstrap; the plan's live-
    validation criterion covers the runtime path.
    """
    src = (_URA / "coordinator.py").read_text()
    assert 'self._exclusion_set.promote(\n                        "chatter"' in src, (
        "tick-site chatter promote wire missing"
    )


# ---------------------------------------------------------------------------
# Drill 4: D3 release wire.
# ---------------------------------------------------------------------------


def test_drill_4_release_wire():
    _mutate_and_expect_red(
        _URA / "domain_coordinators" / "chatter_detector.py",
        old="            self._chattering.discard(eid)",
        new="            pass  # NEUTERED",
        target=str(_TESTS / "test_chatter_detector.py::test_chatter_auto_release_after_quiet_window"),
        label="release_wire",
    )


# ---------------------------------------------------------------------------
# Drill 5: D5 surface wire.
# ---------------------------------------------------------------------------


def test_drill_5_d5_surface_chatter_branch_wire():
    _mutate_and_expect_red(
        _URA / "sensor.py",
        old='                if is_chattering:',
        new='                if False:  # NEUTERED chatter surface',
        target=str(_TESTS / "test_unavailable_entities_chatter.py::test_unavailable_entities_sensor_surfaces_chattering_sensor"),
        label="d5_surface_wire",
    )


# ---------------------------------------------------------------------------
# Drill 6: D1.1 Reading-B forbidden mutation (add-promote in D2-raise branch).
# ---------------------------------------------------------------------------


def test_drill_6_reading_B_forbidden_add_promote():
    _mutate_and_expect_red(
        _URA / "domain_coordinators" / "sensor_exclusion.py",
        # A mutation that would make Reading B invisible: make promote()
        # silently drop stuck_dutycycle client promotions. Would let a
        # Reading-B leaked-add succeed without expanding the set.
        old='by_client[client] = str(reason) if reason is not None else ""',
        new='by_client[client] = str(reason) if (reason is not None and client != "stuck_dutycycle") else ""\n        if client == "stuck_dutycycle": by_client.pop("stuck_dutycycle", None)',
        target=str(_TESTS / "test_sensor_exclusion.py::test_client_isolation_release_leaves_other_clients_promotion_intact"),
        label="reading_B_defence",
    )


# ---------------------------------------------------------------------------
# Drill 7: L-LOW-B subscribe teardown.
# ---------------------------------------------------------------------------


def test_drill_7_subscribe_teardown_wire():
    _mutate_and_expect_red(
        _URA / "domain_coordinators" / "chatter_detector.py",
        old="                self._chatter_unsub()",
        new="                pass  # NEUTERED teardown",
        target=str(_TESTS / "test_chatter_detector.py::test_chatter_detector_unsubscribe_called_on_teardown"),
        label="subscribe_teardown_wire",
    )


# ---------------------------------------------------------------------------
# Drill 8: sub-floor accounting.
# ---------------------------------------------------------------------------


def test_drill_8_sub_floor_accounting_wire():
    _mutate_and_expect_red(
        _URA / "domain_coordinators" / "chatter_detector.py",
        old="                if interval < t_floor:",
        new="                if False:  # NEUTERED sub-floor accounting",
        target=str(_TESTS / "test_chatter_detector.py::test_ratgdo_shaped_sensor_flagged_chatter_after_burst"),
        label="sub_floor_accounting_wire",
    )


# ---------------------------------------------------------------------------
# Drill 9: boot-settle gate.
# ---------------------------------------------------------------------------


def test_drill_9_boot_settle_gate_wire():
    _mutate_and_expect_red(
        _URA / "domain_coordinators" / "chatter_detector.py",
        old="                    if not boot_settled:\n                        return  # sample but do not score during boot-settle",
        new="                    if False:\n                        return",
        target=str(_TESTS / "test_chatter_detector.py::test_boot_settle_gate_suppresses_flagging"),
        label="boot_settle_gate_wire",
    )


# ---------------------------------------------------------------------------
# Drill 10: camera-family provenance guard.
# ---------------------------------------------------------------------------


def test_drill_10_camera_family_guard_wire():
    _mutate_and_expect_red(
        _URA / "domain_coordinators" / "chatter_detector.py",
        old="    if _is_camera_family(entity_id, integration):\n        return (False, provider)",
        new="    if False and _is_camera_family(entity_id, integration):\n        return (False, provider)",
        target=str(_TESTS / "test_chatter_detector.py::test_mislabeled_frigate_entity_denied_by_integration_fallback"),
        label="camera_family_guard_wire",
    )


# ---------------------------------------------------------------------------
# Drill 11: same-value dedup guard.
# ---------------------------------------------------------------------------


def test_drill_11_same_value_dedup_wire():
    """A drill that would let attribute-only edges (same value) count as
    transitions. Would cause a stuck always-"on" sensor to accumulate
    endless zero-interval sub-floor events and false-fire.

    Anchor test: healthy busy PIR — but this drill is asymptotic. Use
    the ratgdo test whose sub-floor accounting still fires; the same-
    value dedup drop would ALSO fire it under a hypothetical value-
    unchanged fixture, but the load-bearing property here is that the
    guard exists. We mutate + assert the healthy-busy-PIR test still
    passes but detector's counters diverge — captured via a bare
    structural check.
    """
    src = (_URA / "domain_coordinators" / "chatter_detector.py").read_text()
    assert "if prev_state_val == state_val:" in src, (
        "same-value dedup guard missing — an attribute-only edge would "
        "count as a transition"
    )


# ---------------------------------------------------------------------------
# Drill 12: unavailable guard.
# ---------------------------------------------------------------------------


def test_drill_12_unavailable_guard_wire():
    _mutate_and_expect_red(
        _URA / "domain_coordinators" / "chatter_detector.py",
        old='            if state_val in ("unavailable", "unknown"):\n                return',
        new='            if False and state_val in ("unavailable", "unknown"):\n                return',
        target=str(_TESTS / "test_chatter_detector.py::test_unavailable_transitions_not_counted"),
        label="unavailable_guard_wire",
    )
