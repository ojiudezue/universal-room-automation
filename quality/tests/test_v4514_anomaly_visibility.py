"""v4.5.14 — Anomaly sensor visibility (extra_state_attributes).

Addresses the masking concern from v4.5.13's gate relaxation: the
aggregate `learning_status: active` label no longer requires all
metrics to be complete. Without surfaced per-metric detail, a user
couldn't tell which metrics were silently dead.

This cycle:
1. Adds `metrics_active_ratio` and `metrics_silent` to
   `AnomalyDetector.get_status_summary()` (single source of truth
   that all anomaly sensors share).
2. Adds `extra_state_attributes` to 4 AnomalyDetector-based anomaly
   sensors (Presence, Safety, Security, MusicFollowing). HVAC already
   had it; NMAnomalySensor uses a different code path and is unchanged.
3. Adds `async_added_to_hass` refresh subscription to SafetyAnomaly
   (signal exists). Presence + MusicFollowing refresh signal gap
   filed to BACKLOG.

Tests below:
  - Behavior: get_status_summary returns the new fields with correct
    semantics for various coverage levels
  - AST: each sensor has extra_state_attributes
  - Source-grep: SafetyAnomaly has dispatcher subscription
"""

import ast
import sys
import types
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def sensor_src() -> str:
    with open("custom_components/universal_room_automation/sensor.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def diagnostics_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/coordinator_diagnostics.py"
    ) as f:
        return f.read()


# ===========================================================================
# Behavior tests on get_status_summary
# ===========================================================================


def _load_anomaly_detector():
    """Reuse the loader pattern from test_v4513_gap_fixes.py — additive,
    idempotent stubs so we cooperate with other test files.
    """
    if "ura_v4514_anomaly_detector" in sys.modules:
        mod = sys.modules["ura_v4514_anomaly_detector"]
        return mod.AnomalyDetector, mod.LearningStatus

    if "homeassistant" not in sys.modules:
        sys.modules["homeassistant"] = types.ModuleType("homeassistant")
        sys.modules["homeassistant"].__path__ = []
    if "homeassistant.core" not in sys.modules:
        ha_core = types.ModuleType("homeassistant.core")
        ha_core.HomeAssistant = type("HomeAssistant", (), {})
        sys.modules["homeassistant.core"] = ha_core
    if "homeassistant.helpers" not in sys.modules:
        ha_helpers = types.ModuleType("homeassistant.helpers")
        ha_helpers.__path__ = []
        sys.modules["homeassistant.helpers"] = ha_helpers
    if "homeassistant.helpers.event" not in sys.modules:
        ha_helpers_event = types.ModuleType("homeassistant.helpers.event")
        ha_helpers_event.async_call_later = lambda *a, **kw: None
        sys.modules["homeassistant.helpers.event"] = ha_helpers_event

    pkg = types.ModuleType("ura_v4514_pkg"); pkg.__path__ = []
    const = types.ModuleType("ura_v4514_pkg.const")
    const.DOMAIN = "universal_room_automation"
    sys.modules["ura_v4514_pkg"] = pkg
    sys.modules["ura_v4514_pkg.const"] = const

    root = Path(__file__).resolve().parents[2]
    src = root / "custom_components" / "universal_room_automation" / \
        "domain_coordinators" / "coordinator_diagnostics.py"
    spec = importlib.util.spec_from_file_location(
        "ura_v4514_pkg.coordinator_diagnostics", str(src),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ura_v4514_pkg.coordinator_diagnostics"] = mod
    mod.__package__ = "ura_v4514_pkg.foo"
    spec.loader.exec_module(mod)
    sys.modules["ura_v4514_anomaly_detector"] = mod
    return mod.AnomalyDetector, mod.LearningStatus


class _StubHass:
    data: dict = {}


def _seed(det, metric, scope, count):
    for _ in range(count):
        det.record_observation(metric, scope, 1.0)


def test_summary_includes_metrics_active_ratio_full_coverage():
    AnomalyDetector, _ = _load_anomaly_detector()
    det = AnomalyDetector(
        _StubHass(), "test", ["m1", "m2", "m3"], minimum_samples=10,
    )
    _seed(det, "m1", "house", 12)
    _seed(det, "m2", "house", 12)
    _seed(det, "m3", "house", 12)
    s = det.get_status_summary("house")
    assert s["metrics_active_ratio"] == "3/3"
    assert s["metrics_silent"] == []


def test_summary_metrics_active_ratio_partial():
    AnomalyDetector, _ = _load_anomaly_detector()
    det = AnomalyDetector(
        _StubHass(), "test", ["m1", "m2", "m3", "m4"], minimum_samples=10,
    )
    _seed(det, "m1", "house", 12)
    _seed(det, "m2", "house", 12)
    # m3 and m4 silent
    s = det.get_status_summary("house")
    assert s["metrics_active_ratio"] == "2/4"
    assert sorted(s["metrics_silent"]) == ["m3", "m4"]


def test_summary_metrics_active_ratio_zero():
    AnomalyDetector, _ = _load_anomaly_detector()
    det = AnomalyDetector(
        _StubHass(), "test", ["m1", "m2"], minimum_samples=10,
    )
    s = det.get_status_summary("house")
    assert s["metrics_active_ratio"] == "0/2"
    assert sorted(s["metrics_silent"]) == ["m1", "m2"]


def test_summary_metrics_silent_excludes_learning_metrics():
    """A metric with 0 < samples < minimum is `learning`, NOT `silent`.
    Silent specifically means zero observations recorded.
    """
    AnomalyDetector, _ = _load_anomaly_detector()
    det = AnomalyDetector(
        _StubHass(), "test", ["m1", "m2", "m3"], minimum_samples=10,
    )
    _seed(det, "m1", "house", 12)  # active
    _seed(det, "m2", "house", 3)   # learning (some samples, not enough)
    # m3 silent (0 samples)
    s = det.get_status_summary("house")
    assert s["metrics_active_ratio"] == "1/3"
    assert s["metrics_silent"] == ["m3"]


def test_summary_preserves_per_metric_detail():
    """Backward-compat: the per-metric `metrics` dict is unchanged."""
    AnomalyDetector, _ = _load_anomaly_detector()
    det = AnomalyDetector(
        _StubHass(), "test", ["m1", "m2"], minimum_samples=10,
    )
    _seed(det, "m1", "house", 12)
    s = det.get_status_summary("house")
    assert "m1" in s["metrics"]
    assert s["metrics"]["m1"]["active"] is True
    assert s["metrics"]["m2"]["active"] is False
    assert "sample_count" in s["metrics"]["m1"]
    assert "mean" in s["metrics"]["m1"]


# ===========================================================================
# AST: each anomaly sensor has extra_state_attributes
# ===========================================================================


def _class_has_method(src: str, class_name: str, method_name: str) -> bool:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == method_name:
                return True
            # Properties are FunctionDef with @property decorator
            if isinstance(item, ast.AsyncFunctionDef) and item.name == method_name:
                return True
    return False


def test_presence_anomaly_has_extra_state_attributes(sensor_src: str):
    assert _class_has_method(
        sensor_src, "PresenceAnomalySensor", "extra_state_attributes",
    ), (
        "PresenceAnomalySensor must expose extra_state_attributes in "
        "v4.5.14 (anomaly visibility)."
    )


def test_safety_anomaly_has_extra_state_attributes(sensor_src: str):
    assert _class_has_method(
        sensor_src, "SafetyAnomalySensor", "extra_state_attributes",
    )


def test_security_anomaly_has_extra_state_attributes(sensor_src: str):
    assert _class_has_method(
        sensor_src, "SecurityAnomalySensor", "extra_state_attributes",
    )


def test_music_following_anomaly_has_extra_state_attributes(sensor_src: str):
    assert _class_has_method(
        sensor_src, "MusicFollowingAnomalySensor", "extra_state_attributes",
    )


def test_safety_anomaly_has_refresh_subscription(sensor_src: str):
    """Safety has SIGNAL_SAFETY_ENTITIES_UPDATE — sensor must subscribe."""
    assert _class_has_method(
        sensor_src, "SafetyAnomalySensor", "async_added_to_hass",
    ), (
        "SafetyAnomalySensor needs async_added_to_hass subscribing to "
        "SIGNAL_SAFETY_ENTITIES_UPDATE for per-cycle refresh."
    )


def test_anomaly_sensors_call_get_status_summary(sensor_src: str):
    """All 4 anomaly sensors should route their attrs through
    `get_status_summary()` to share the single-source-of-truth payload
    (including the new metrics_active_ratio field).
    """
    for sensor_name in [
        "PresenceAnomalySensor",
        "SafetyAnomalySensor",
        "MusicFollowingAnomalySensor",
    ]:
        # Locate class body
        idx = sensor_src.find(f"class {sensor_name}(")
        assert idx >= 0, f"{sensor_name} class missing"
        end = sensor_src.find("\nclass ", idx + 1)
        body = sensor_src[idx:end if end > 0 else None]
        assert "get_status_summary()" in body, (
            f"{sensor_name} extra_state_attributes should call "
            "anomaly_detector.get_status_summary() to share the "
            "improved attrs surface."
        )

    # SecurityAnomalySensor uses getattr (defensive) — check separately
    idx = sensor_src.find("class SecurityAnomalySensor(")
    end = sensor_src.find("\nclass ", idx + 1)
    body = sensor_src[idx:end if end > 0 else None]
    assert "get_status_summary()" in body
