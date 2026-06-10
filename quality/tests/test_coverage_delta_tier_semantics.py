"""Tests for D2: 4-tier attribution TODAY-scope semantics.

Drives the production today-delta helper
(``domain_coordinators._units.today_delta_kwh``) which
EnergyCoverageDeltaSensor._today_delta_kwh delegates to. The class
method delegating to a top-level helper makes the rebasing logic
testable without a full Home Assistant environment.

Covers:
- first observation establishes baseline (delta = 0)
- subsequent same-date observations return raw delta
- new local date triggers re-anchor
- negative delta (counter reset / sensor swap) re-anchors
- Wh-vs-kWh normalization happens BEFORE the helper (so deltas in kWh)
"""
import importlib.util
import os
import sys

import pytest


_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_units():
    path = os.path.join(
        _REPO,
        "custom_components",
        "universal_room_automation",
        "domain_coordinators",
        "_units.py",
    )
    spec = importlib.util.spec_from_file_location("_ura_units_tier", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_u = _load_units()


# ---------------------------------------------------------------------------
# today_delta_kwh behavioral tests
# ---------------------------------------------------------------------------

def test_first_observation_returns_zero_delta():
    tracker: dict = {}
    assert _u.today_delta_kwh(tracker, "s1", 100.0, "2026-06-09") == 0.0
    assert tracker["s1"]["baseline_kwh"] == 100.0
    assert tracker["s1"]["anchor_date"] == "2026-06-09"


def test_second_observation_returns_increment():
    tracker = {"s1": {"baseline_kwh": 100.0, "anchor_date": "2026-06-09"}}
    assert _u.today_delta_kwh(tracker, "s1", 102.5, "2026-06-09") == pytest.approx(2.5)
    # Baseline unchanged.
    assert tracker["s1"]["baseline_kwh"] == 100.0


def test_new_date_re_anchors():
    tracker = {"s1": {"baseline_kwh": 100.0, "anchor_date": "2026-06-09"}}
    # New day with cumulative counter now at 105.
    assert _u.today_delta_kwh(tracker, "s1", 105.0, "2026-06-10") == 0.0
    assert tracker["s1"]["baseline_kwh"] == 105.0
    assert tracker["s1"]["anchor_date"] == "2026-06-10"


def test_negative_delta_re_anchors_safely():
    tracker = {"s1": {"baseline_kwh": 100.0, "anchor_date": "2026-06-09"}}
    # Counter reset (e.g. firmware reboot, sensor swap).
    assert _u.today_delta_kwh(tracker, "s1", 5.0, "2026-06-09") == 0.0
    # Re-anchored to current.
    assert tracker["s1"]["baseline_kwh"] == 5.0


def test_zero_delta_returned():
    tracker = {"s1": {"baseline_kwh": 100.0, "anchor_date": "2026-06-09"}}
    assert _u.today_delta_kwh(tracker, "s1", 100.0, "2026-06-09") == 0.0


def test_multiple_sensors_independent():
    tracker: dict = {}
    _u.today_delta_kwh(tracker, "s1", 100.0, "d")
    _u.today_delta_kwh(tracker, "s2", 50.0, "d")
    assert _u.today_delta_kwh(tracker, "s1", 110.0, "d") == 10.0
    assert _u.today_delta_kwh(tracker, "s2", 55.0, "d") == 5.0


# ---------------------------------------------------------------------------
# Regression: today_delta_kwh MUST preserve unknown keys on date rollover
# (fix-up pass A-C1/C2 — the prior implementation replaced the dict and
# dropped `scope`, KeyError-ing the whole-house caller after midnight).
# ---------------------------------------------------------------------------

def test_date_rollover_preserves_unknown_keys():
    """A caller (whole-house tier) places extra keys like `scope` on the
    tracker entry. ``today_delta_kwh`` must MUTATE the existing entry on
    date rollover, preserving those keys — not replace the dict.
    """
    tracker = {
        "s1": {
            "baseline_kwh": 100.0,
            "anchor_date": "2026-06-09",
            "scope": "today_derived",
        },
    }
    _u.today_delta_kwh(tracker, "s1", 105.0, "2026-06-10")
    assert tracker["s1"]["baseline_kwh"] == 105.0
    assert tracker["s1"]["anchor_date"] == "2026-06-10"
    # The unknown `scope` key MUST survive the rollover.
    assert tracker["s1"]["scope"] == "today_derived"


def test_negative_delta_re_anchor_preserves_unknown_keys():
    """Counter-reset path also mutates in place (preserves scope etc.)."""
    tracker = {
        "s1": {
            "baseline_kwh": 100.0,
            "anchor_date": "2026-06-09",
            "scope": "today_derived",
        },
    }
    _u.today_delta_kwh(tracker, "s1", 5.0, "2026-06-09")
    assert tracker["s1"]["baseline_kwh"] == 5.0
    assert tracker["s1"]["scope"] == "today_derived"


# ---------------------------------------------------------------------------
# Source-level verification that EnergyCoverageDeltaSensor uses the helper
# (drives production code path — would fail if a future refactor diverged).
# ---------------------------------------------------------------------------

def test_aggregation_delegates_to_helper():
    path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "aggregation.py",
    )
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    assert "today_delta_kwh" in src, "aggregation must use the shared helper"
    # The class method body delegates rather than re-implements.
    cls_idx = src.find("class EnergyCoverageDeltaSensor")
    method_idx = src.find("def _today_delta_kwh(self,", cls_idx)
    assert method_idx > 0
    # Next method/class boundary
    end_idx = src.find("\n    def ", method_idx + 1)
    body = src[method_idx:end_idx]
    assert "today_delta_kwh(" in body


def test_aggregation_sum_sensors_uses_unit_helper():
    """EnergyCoverageDeltaSensor._sum_sensors routes through energy_state_to_kwh."""
    path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "aggregation.py",
    )
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    # Target the EnergyCoverageDeltaSensor class specifically — multiple
    # classes define `_sum_sensors`; the power-class one (WholeHousePower)
    # is intentionally out of scope per the planning doc.
    cls_idx = src.find("class EnergyCoverageDeltaSensor")
    assert cls_idx > 0
    next_cls = src.find("\nclass ", cls_idx + 1)
    body = src[cls_idx:next_cls if next_cls > 0 else len(src)]
    assert "def _sum_sensors(self" in body
    assert "energy_state_to_kwh(state)" in body, (
        "EnergyCoverageDeltaSensor._sum_sensors must normalize via the helper"
    )


def test_whole_house_heuristic_threshold_defined():
    path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "aggregation.py",
    )
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    assert "WHOLE_HOUSE_CUMULATIVE_THRESHOLD_KWH" in src


def test_whole_house_scope_attribute_exposed():
    path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "aggregation.py",
    )
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    # Both flag and attribute output.
    assert "self._whole_house_scope" in src
    assert "\"whole_house_scope\":" in src or '"whole_house_scope":' in src
    assert "scope_mismatch_warning" in src
    assert "baseline_anchor" in src


def test_coverage_rating_anomalous_const_used():
    path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "aggregation.py",
    )
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    assert "COVERAGE_RATING_ANOMALOUS" in src
