"""HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1 — mutation-anchored tests.

Covers D-b1 reason rename (`runtime_exceeded` → `energy_shed_cap_reached`),
D-b2 occupancy gate (coast + fused-occupied → defer force-away, ledger
reason `energy_shed_cap_deferred_occupied`; shed still dominates; empty
under coast still forces away), and D-b3 Rung-3 knobs + master enable
(`0` cap = per-mode kill; disabled switch = whole primitive no-ops).

Every test is a per-site mutation anchor: neuter the specified source
site and the named test REDs. See planning §Falsifiable invariant
INV-D5-GATE.
"""
from __future__ import annotations

import ast
import importlib.util as _ilu
import os
import sys
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock


_HERE = os.path.dirname(__file__)
_URA = os.path.abspath(os.path.join(_HERE, "..", "..",
                                    "custom_components",
                                    "universal_room_automation"))
_DC = os.path.join(_URA, "domain_coordinators")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# D-b1 — reason rename completeness
# ---------------------------------------------------------------------------

def test_dbb1_hvac_preset_reasons_contains_new_reasons_and_not_old():
    """D-b1: HVAC_PRESET_REASONS carries `energy_shed_cap_reached` and
    `energy_shed_cap_deferred_occupied` and NO LONGER carries the old
    `runtime_exceeded` (Single-User-No-Back-Compat: no alias)."""
    src = _read(os.path.join(_URA, "const.py"))
    # Locate the HVAC_PRESET_REASONS = frozenset({...}) literal.
    tree = ast.parse(src)
    found_set: set[str] = set()
    def _harvest(val):
        # frozenset({"a", "b", ...}) or set() literal
        if isinstance(val, ast.Call):
            for arg in val.args:
                if isinstance(arg, ast.Set):
                    for elt in arg.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            found_set.add(elt.value)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "HVAC_PRESET_REASONS":
                    _harvest(node.value)
        elif isinstance(node, ast.AnnAssign):
            tgt = node.target
            if isinstance(tgt, ast.Name) and tgt.id == "HVAC_PRESET_REASONS" and node.value is not None:
                _harvest(node.value)
    assert "energy_shed_cap_reached" in found_set, (
        "D-b1: HVAC_PRESET_REASONS must carry the renamed reason "
        "`energy_shed_cap_reached`"
    )
    assert "energy_shed_cap_deferred_occupied" in found_set, (
        "D-b2: HVAC_PRESET_REASONS must carry `energy_shed_cap_deferred_occupied`"
    )
    assert "runtime_exceeded" not in found_set, (
        "D-b1 rename incomplete: `runtime_exceeded` still in "
        "HVAC_PRESET_REASONS (Single-User-No-Back-Compat: no alias)"
    )


def test_dbb1_s1_ladder_emits_energy_shed_cap_reached_not_runtime_exceeded():
    """D-b1: the S1 reason ladder in hvac.py assigns
    `preset_change_reason = "energy_shed_cap_reached"`, NOT the old
    `runtime_exceeded`. Mutation anchor: revert the emit at
    hvac.py:2311 back to `"runtime_exceeded"` and this test REDs."""
    src = _read(os.path.join(_DC, "hvac.py"))
    tree = ast.parse(src)
    ladder_literals: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id == "preset_change_reason":
                if isinstance(node.value, ast.Constant) and isinstance(
                    node.value.value, str,
                ):
                    ladder_literals.add(node.value.value)
    assert "energy_shed_cap_reached" in ladder_literals, (
        "D-b1: S1 ladder must assign preset_change_reason = "
        "\"energy_shed_cap_reached\""
    )
    assert "runtime_exceeded" not in ladder_literals, (
        "D-b1: S1 ladder still assigns the old `runtime_exceeded` "
        "reason — rename incomplete"
    )


# ---------------------------------------------------------------------------
# D-b2 — occupancy gate + shed-dominates + empty-still-force-away
# ---------------------------------------------------------------------------

def test_dbb2_gate_reads_any_room_hvac_occupied_and_defers_on_coast():
    """D-b2: the D5 force-away site (hvac.py) must gate on
    `any_room_hvac_occupied` (or its fused-fallback pattern) AND
    `energy_constraint_mode != "shed"` before deferring.

    Mutation anchor: remove the `any_room_hvac_occupied` check from the
    D5 gate branch and this test REDs.
    """
    src = _read(os.path.join(_DC, "hvac.py"))
    # The gate lives inside the S14-removed else-branch. The test
    # checks the gate branch names both properties.
    # Extract the block containing `_d5_occupancy_deferred_this_tick`
    # assignment.
    marker = "_d5_occupancy_deferred_this_tick = True"
    assert marker in src, (
        "D-b2: the gate must set _d5_occupancy_deferred_this_tick = True"
    )
    # Grab a 40-line window around the marker.
    idx = src.index(marker)
    window = src[max(0, idx - 4000): idx + 400]
    assert "any_room_hvac_occupied" in window, (
        "D-b2: the gate MUST read `any_room_hvac_occupied` "
        "(step-4-B fused signal)"
    )
    assert 'self._energy_constraint_mode != "shed"' in window, (
        "D-b2: the gate MUST be conditional on "
        "`self._energy_constraint_mode != \"shed\"` — shed still dominates"
    )


def test_dbb2_deferred_reason_emitted_in_ledger_details():
    """D-b2: the episode-gated activity-log row emitted when the gate
    fires carries `reason: energy_shed_cap_deferred_occupied` in its
    details dict.

    Mutation anchor: change the emit-site reason literal to any other
    string and this test REDs.
    """
    src = _read(os.path.join(_DC, "hvac.py"))
    assert '"reason": "energy_shed_cap_deferred_occupied"' in src, (
        "D-b2: the D5 defer ledger row must carry the reason "
        "`energy_shed_cap_deferred_occupied`"
    )


def test_dbb2_empty_coast_still_force_away_and_shed_dominates():
    """D-b2: the else-branch of the D-b2 gate STILL executes
    `effective_preset = "away"` — i.e. UNoccupied coast AND ANY shed
    zone continue to be forced away.

    Mutation anchor: remove the `else: effective_preset = "away"`
    below the gate and this test REDs.
    """
    src = _read(os.path.join(_DC, "hvac.py"))
    # Look for the else-arm literally right after the gate block.
    # We anchor on the phrase that documents shed-dominance +
    # the fall-through effective_preset write.
    assert "_row2054_fused" in src, (
        "D-b2: the gate must resolve fused occupancy via _row2054_fused"
    )
    # The gate must have an else-branch preserving the force-away.
    # Regex-lite: check both the gate literal and a following
    # `effective_preset = "away"` in the same file.
    gate_idx = src.index("_row2054_fused")
    window = src[gate_idx: gate_idx + 4000]
    assert 'effective_preset = "away"' in window, (
        "D-b2: after the gate, the fall-through MUST still write "
        "`effective_preset = \"away\"` for the non-gated paths "
        "(empty coast, any shed)"
    )


# ---------------------------------------------------------------------------
# D-b3 — Rung-3 knobs + kill switches
# ---------------------------------------------------------------------------

def test_dbb3_hvac_coordinator_exposes_live_knob_properties():
    """D-b3: HVACCoordinator source declares the 4 live-knob accessors:
    duty_cycle_window_seconds, duty_cycle_coast_pct, duty_cycle_shed_pct,
    d5_enabled — and the corresponding setters."""
    src = _read(os.path.join(_DC, "hvac.py"))
    for name in (
        "def duty_cycle_window_seconds",
        "def set_duty_cycle_window_minutes",
        "def duty_cycle_coast_pct",
        "def set_duty_cycle_coast_pct",
        "def duty_cycle_shed_pct",
        "def set_duty_cycle_shed_pct",
        "def d5_enabled",
        "def set_d5_enabled",
    ):
        assert name in src, f"D-b3: missing accessor/setter `{name}`"


def test_dbb3_accumulator_consults_live_knobs_not_module_constants():
    """D-b3: `_accumulate_zone_runtime` reads the LIVE knob values
    (via self.duty_cycle_*), NOT the module constants directly.

    Mutation anchor: swap the knob reads back to
    `DUTY_CYCLE_WINDOW_SECONDS` / `DUTY_CYCLE_COAST` / `DUTY_CYCLE_SHED`
    inside `_accumulate_zone_runtime` and this test REDs.
    """
    src = _read(os.path.join(_DC, "hvac.py"))
    idx = src.index("def _accumulate_zone_runtime")
    body = src[idx: idx + 3500]
    assert "self.duty_cycle_window_seconds" in body, (
        "D-b3: accumulator must read `self.duty_cycle_window_seconds` "
        "(live knob), not the module constant"
    )
    assert "self.duty_cycle_coast_pct" in body, (
        "D-b3: accumulator must read `self.duty_cycle_coast_pct` (live)"
    )
    assert "self.duty_cycle_shed_pct" in body, (
        "D-b3: accumulator must read `self.duty_cycle_shed_pct` (live)"
    )
    # Kill-switch semantics.
    assert "cap_pct <= 0" in body, (
        "D-b3: `0` on a cap must be a documented kill for that mode "
        "(cap_pct <= 0: continue)"
    )
    assert "if not self.d5_enabled" in body, (
        "D-b3: master enable switch must short-circuit enforcement "
        "in the accumulator"
    )


def test_dbb3_number_and_switch_entities_registered():
    """D-b3: the three Number entities and the master Switch are
    added to their platform registration lists.

    Mutation anchor: comment out any of the 4 registrations and this
    test REDs.
    """
    number_src = _read(os.path.join(_URA, "number.py"))
    assert "HVACDutyCycleWindowMinutesNumber(hass, entry)" in number_src, (
        "D-b3: HVACDutyCycleWindowMinutesNumber must be registered"
    )
    assert "HVACDutyCycleCoastPctNumber(hass, entry)" in number_src, (
        "D-b3: HVACDutyCycleCoastPctNumber must be registered"
    )
    assert "HVACDutyCycleShedPctNumber(hass, entry)" in number_src, (
        "D-b3: HVACDutyCycleShedPctNumber must be registered"
    )
    switch_src = _read(os.path.join(_URA, "switch.py"))
    assert "HVACD5EnableSwitch(hass, entry)" in switch_src, (
        "D-b3: HVACD5EnableSwitch master enable must be registered"
    )


def test_dbb3_knob_defaults_match_pre_cycle_module_constants():
    """D-b3: entity-knob DEFAULT_* values match the pre-cycle module
    constants (20 min window, 75% coast, 50% shed), so a fresh install
    (no persisted options) preserves pre-cycle behavior.

    Mutation anchor: change any DEFAULT_ to a non-matching value and
    this test REDs.
    """
    hvac_const = _read(os.path.join(_DC, "hvac_const.py"))
    # Cross-check defaults against the module constants.
    assert "DEFAULT_HVAC_DUTY_CYCLE_WINDOW_MIN: Final = 20" in hvac_const
    assert "DEFAULT_HVAC_DUTY_CYCLE_COAST_PCT: Final = 75" in hvac_const
    assert "DEFAULT_HVAC_DUTY_CYCLE_SHED_PCT: Final = 50" in hvac_const
    assert "DEFAULT_HVAC_D5_ENABLED: Final = True" in hvac_const


# ---------------------------------------------------------------------------
# D-b1 — operator-facing attribute rename on sensor
# ---------------------------------------------------------------------------

def test_dbb1_zone_status_attr_renamed_to_energy_shed_cap_reached():
    """D-b1: the zone status attribute key (hvac_zones.py:762 area) is
    renamed from `runtime_exceeded` to `energy_shed_cap_reached`.

    Mutation anchor: revert the attribute-key string and this test REDs.
    """
    src = _read(os.path.join(_DC, "hvac_zones.py"))
    # The status attrs dict now carries the new key.
    assert '"energy_shed_cap_reached": zone.runtime_exceeded' in src, (
        "D-b1: hvac_zones.get_zone_status_attrs must expose the "
        "renamed operator-facing key `energy_shed_cap_reached`"
    )
    # And NOT the old key as a dict entry (comments OK).
    # Simple guard: the string `"runtime_exceeded": zone.runtime_exceeded`
    # (attribute dict entry form) must be gone.
    assert '"runtime_exceeded": zone.runtime_exceeded' not in src, (
        "D-b1: the old attribute key `runtime_exceeded` still emitted "
        "as a dict entry in hvac_zones.py"
    )
