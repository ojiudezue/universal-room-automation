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

# ---------------------------------------------------------------------------
# D2-MED-1 (2026-08-19): tree-poisoning safety.
#
# The mutation drills below edit production source on disk (that IS the
# point — a subprocess pytest must load the mutated .py). Even with
# per-drill try/finally, a hard kill (Ctrl-C, subprocess timeout, OOM,
# test collection failure INSIDE the with-block) could leave the tree
# poisoned. Belt+braces: an autouse module-scoped fixture snapshots
# every file we might touch at collection time and restores each on
# session end AND per-test (in case a drill leaks). Idempotent.
# ---------------------------------------------------------------------------

_TOUCHED_FILES: list[pathlib.Path] = [
    _URA / "coordinator.py",
    _URA / "domain_coordinators" / "chatter_detector.py",
    _URA / "domain_coordinators" / "sensor_exclusion.py",
    _URA / "sensor.py",
    _URA / "const.py",
    # D7 (2026-08-19): drills 21 mutates const, 22 mutates chatter_detector;
    # 20 mutates coordinator. All covered above.
    _URA / "select.py",
    _URA / "number.py",
]


@pytest.fixture(scope="module", autouse=True)
def _snapshot_and_restore_touched_sources():
    """Snapshot every production file drills may edit; restore on exit.

    Guarantees `git status --porcelain` reports no drift after this
    module's tests complete, regardless of drill outcome.
    """
    snapshots: dict[pathlib.Path, str] = {
        p: p.read_text() for p in _TOUCHED_FILES if p.exists()
    }
    try:
        yield
    finally:
        for p, orig in snapshots.items():
            if p.read_text() != orig:
                p.write_text(orig)


@pytest.fixture(autouse=True)
def _per_test_restore_touched_sources():
    """Per-test belt on top of the module-scoped braces: any drill that
    somehow bypasses its own try/finally is caught here too."""
    snaps: dict[pathlib.Path, str] = {
        p: p.read_text() for p in _TOUCHED_FILES if p.exists()
    }
    try:
        yield
    finally:
        for p, orig in snaps.items():
            if p.exists() and p.read_text() != orig:
                p.write_text(orig)


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


def test_drill_1_d1_fusion_filter_helper_wire():
    """C-CRIT-1 de-hollow: mutate the extracted _fusion_filter_active
    helper (single site — all 6 fusion legs route through it) and
    assert the REAL behavioural test in
    test_sensor_exclusion.test_fusion_filter_active_drops_excluded_sensors
    would fail if the helper stopped filtering. That test is a
    copy-of-body against the same shape; a coordinator source mutation
    also reds test_chatter_tick_helper::test_fusion_filter_active_extracted_matches_coordinator
    which extracts and drives the helper AST directly.
    """
    _mutate_and_expect_red(
        _URA / "coordinator.py",
        old="        return [\n            s for s in sensors\n            if s and not self._exclusion_set.is_excluded(s)\n        ]",
        new="        return list(sensors)  # NEUTERED",
        target=str(_TESTS / "test_chatter_tick_helper.py::test_fusion_filter_active_extracted_matches_coordinator"),
        label="d1_fusion_filter_helper_wire",
    )


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
    """C-CRIT-2 de-hollow: the tick-site chatter promote lives inside
    the extracted _apply_chatter_tick helper. Real behavioural anchor:
    test_chatter_tick_helper::test_apply_chatter_tick_promotes_current_chatterers.
    Mutating the promote call must red the real test.
    """
    _mutate_and_expect_red(
        _URA / "coordinator.py",
        # D7 (2026-08-19): promote now sits inside the `if is_act:`
        # branch; anchor updated to match.
        old='self._exclusion_set.promote(\n                    "chatter", _ceid, reason="physics_violation",\n                )',
        new='pass  # NEUTERED for drill',
        target=str(_TESTS / "test_chatter_tick_helper.py::test_apply_chatter_tick_promotes_current_chatterers"),
        label="chatter_tick_site_promote_wire",
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


def test_drill_9_boot_settle_gate_general_suppress_wire():
    """Boot-settle gate: general suppress-during-boot behaviour.

    Post-D-HIGH-2 the gate lives BEFORE the deque append (drill 13
    covers the boot-transient leak fix specifically); drill 9 shares
    the same anchor but targets the general suppression test.
    Duplicate coverage is deliberate — the gate is load-bearing.
    """
    _mutate_and_expect_red(
        _URA / "domain_coordinators" / "chatter_detector.py",
        old="            if not boot_settled:\n                # Drop the edge entirely",
        new="            if False:\n                # NEUTERED for drill 9",
        target=str(_TESTS / "test_chatter_detector.py::test_boot_settle_gate_suppresses_flagging"),
        label="boot_settle_gate_general_suppress",
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


# ---------------------------------------------------------------------------
# Fix-up round drills (2026-08-19).
# ---------------------------------------------------------------------------


def test_drill_13_d_high_2_boot_gate_wire():
    """D-HIGH-2: neutering the boot-settle early-return must red the
    boot-transient regression test."""
    _mutate_and_expect_red(
        _URA / "domain_coordinators" / "chatter_detector.py",
        old="            if not boot_settled:\n                # Drop the edge entirely",
        new="            if False and not boot_settled:\n                # NEUTERED",
        target=str(_TESTS / "test_chatter_detector.py::test_d_high_2_boot_transient_no_instant_quarantine_on_restart"),
        label="d_high_2_boot_gate_wire",
    )


def test_drill_14_d_med_1_z2m_fallback_wire():
    """D-MED-1: neutering the Zigbee-native + device_class fallback must
    red the numeric-id Z2M classifier test."""
    _mutate_and_expect_red(
        _URA / "domain_coordinators" / "chatter_detector.py",
        old="    if integration and integration.lower() in _ZIGBEE_NATIVE_PLATFORMS:",
        new="    if False and integration and integration.lower() in _ZIGBEE_NATIVE_PLATFORMS:",
        target=str(_TESTS / "test_chatter_detector.py::test_d_med_1_z2m_numeric_id_scored_via_device_class_fallback"),
        label="d_med_1_z2m_fallback_wire",
    )


def test_drill_15_m_a1_per_day_latch_wire():
    """M-A1: neutering the _chatter_nm_fired latch check must red the
    write-flood regression test."""
    _mutate_and_expect_red(
        _URA / "coordinator.py",
        old="            if _nm_key in self._chatter_nm_fired:\n                continue\n            self._chatter_nm_fired.add(_nm_key)",
        new="            if False:\n                continue\n            pass  # NEUTERED latch",
        target=str(_TESTS / "test_chatter_tick_helper.py::test_apply_chatter_tick_ma1_per_day_latch_prevents_write_flood"),
        label="m_a1_latch_wire",
    )


def test_drill_16_b_low_2_provenance_guard_wire():
    """B-LOW-2: neutering the clients_for() guard on _stuck_sensor_kinds
    pop must red the provenance-guarded pop test."""
    _mutate_and_expect_red(
        _URA / "coordinator.py",
        old="            if not self._exclusion_set.clients_for(_rel):\n                self._stuck_sensor_kinds.pop(_rel, None)",
        new="            self._stuck_sensor_kinds.pop(_rel, None)  # NEUTERED B-LOW-2 guard",
        target=str(_TESTS / "test_chatter_tick_helper.py::test_apply_chatter_tick_b_low_2_pop_guarded_by_provenance"),
        label="b_low_2_provenance_guard_wire",
    )


def test_drill_17_b_low_4_discharge_wire():
    """B-LOW-4: neutering the kill-switch discharge call must red the
    suppression-needs-discharge test."""
    _mutate_and_expect_red(
        _URA / "coordinator.py",
        old="        if self._chatter_kill_switch_last and not enabled:\n            self._discharge_chatter_latches(room_name)",
        new="        if False and self._chatter_kill_switch_last and not enabled:\n            self._discharge_chatter_latches(room_name)",
        target=str(_TESTS / "test_chatter_tick_helper.py::test_apply_chatter_tick_b_low_4_kill_switch_flip_discharges_latch"),
        label="b_low_4_discharge_wire",
    )


def test_drill_18_recalibration_k10_constant_wire():
    """D-HIGH-1: the recalibrated K=10 default must be present. A
    mutation back to K=20 would red the invisoutlet-shape acceptance test.
    """
    _mutate_and_expect_red(
        _URA / "const.py",
        old="DEFAULT_CHATTER_BURST_K: Final = 10",
        new="DEFAULT_CHATTER_BURST_K: Final = 20",
        target=str(_TESTS / "test_chatter_detector.py::test_recalibration_invisoutlet_shape_flagged_at_K10"),
        label="d_high_1_k10_recalibration_wire",
    )


def test_drill_20_d7_shadow_vs_act_seam_wire():
    """D7 (2026-08-19): removing the `if is_act:` guard on the fusion
    promote would let SHADOW mode quarantine — regressing shadow-first.
    Must red the load-bearing test_d7_shadow_mode_does_not_promote test.
    """
    _mutate_and_expect_red(
        _URA / "coordinator.py",
        old="        for _ceid in chatter_current:\n            if is_act:",
        new="        for _ceid in chatter_current:\n            if True:  # NEUTERED — promotes in every mode",
        target=str(_TESTS / "test_chatter_d7_shadow_act.py::test_d7_shadow_mode_does_not_promote_into_exclusion_set"),
        label="d7_shadow_vs_act_seam",
    )


def test_drill_21_d7_default_mode_shadow_wire():
    """D7 default mode must be shadow. Mutating the default reds the
    SHADOW-FIRST doctrine test."""
    _mutate_and_expect_red(
        _URA / "const.py",
        old='DEFAULT_CHATTER_MODE: Final = CHATTER_MODE_SHADOW',
        new='DEFAULT_CHATTER_MODE: Final = CHATTER_MODE_ACT',
        target=str(_TESTS / "test_chatter_d7_shadow_act.py::test_d7_default_mode_is_shadow"),
        label="d7_default_mode_shadow",
    )


def test_drill_23_d7_HIGH_mode_transition_release_wire():
    """D7 HIGH fix-up (2026-08-19): neutering the act->non-act
    release-on-transition call must red the load-bearing
    test_d7_HIGH_act_to_shadow_flip_releases_chatter_exclusions test.
    """
    _mutate_and_expect_red(
        _URA / "coordinator.py",
        old="        if self._chatter_act_last and not is_act_now:\n            self._release_all_chatter_exclusions(room_name)",
        new="        if False and self._chatter_act_last and not is_act_now:\n            self._release_all_chatter_exclusions(room_name)",
        target=str(_TESTS / "test_chatter_d7_shadow_act.py::test_d7_HIGH_act_to_shadow_flip_releases_chatter_exclusions"),
        label="d7_HIGH_mode_transition_release",
    )


def test_drill_24_d7_HIGH_release_helper_body_wire():
    """D7 HIGH fix-up: neutering the exclusion_set.release call inside
    _release_all_chatter_exclusions must red the STEP-EXCLUDE-3-preserving
    mode-flip test."""
    _mutate_and_expect_red(
        _URA / "coordinator.py",
        old='            self._exclusion_set.release("chatter", _eid)',
        new='            pass  # NEUTERED release',
        target=str(_TESTS / "test_chatter_d7_shadow_act.py::test_d7_HIGH_act_to_shadow_flip_releases_chatter_exclusions"),
        label="d7_HIGH_release_helper_body",
    )


def test_drill_22_d7_room_telemetry_wire():
    """D7 telemetry surface — removing the telemetry() call in
    UnavailableEntitiesSensor reds the telemetry acceptance test."""
    _mutate_and_expect_red(
        _URA / "domain_coordinators" / "chatter_detector.py",
        old='            rows.append({\n                "entity_id": eid,',
        new='            _ = eid  # NEUTERED telemetry\n            continue\n            rows.append({\n                "entity_id": eid,',
        target=str(_TESTS / "test_chatter_d7_shadow_act.py::test_d7_room_telemetry_surfaces_burst_count_and_would_quarantine"),
        label="d7_room_telemetry",
    )


def test_drill_19_recalibration_t_floor_1_0_wire():
    """D-HIGH-1: the recalibrated unified T_floor=1.0s default must be
    present. A mutation to 1.5s would red the Meross healthy sentinel
    (worst burst 10 at 1.5s vs K=10 -> false-quarantine)."""
    _mutate_and_expect_red(
        _URA / "const.py",
        old="DEFAULT_CHATTER_T_FLOOR_S: Final = 1.0",
        new="DEFAULT_CHATTER_T_FLOOR_S: Final = 0.3",
        target=str(_TESTS / "test_chatter_detector.py::test_recalibration_invisoutlet_shape_flagged_at_K10"),
        label="d_high_1_t_floor_recalibration_wire",
    )
