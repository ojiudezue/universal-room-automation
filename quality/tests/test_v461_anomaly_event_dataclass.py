"""v4.6.1 D0 — AnomalyEvent dataclass field shape, AnomalySeverity IntEnum values,
event_class literal set.

All tests are pure-Python source-grep or import-time checks; no HA runtime needed.
"""

import importlib.util
import sys
import types
from pathlib import Path


# ---------------------------------------------------------------------------
# Source-grep fixture
# ---------------------------------------------------------------------------

def _read_src() -> str:
    p = Path("custom_components/universal_room_automation/domain_coordinators/anomaly_event.py")
    return p.read_text()


def _load_anomaly_event_module():
    """Load anomaly_event.py without HA installed."""
    mod_name = "ura_v461_anomaly_event"
    if mod_name in sys.modules:
        return sys.modules[mod_name]

    src = Path(
        "custom_components/universal_room_automation/domain_coordinators/anomaly_event.py"
    )
    spec = importlib.util.spec_from_file_location(mod_name, str(src))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# AnomalySeverity IntEnum
# ---------------------------------------------------------------------------

def test_anomaly_severity_is_intenum():
    """AnomalySeverity must subclass IntEnum so values are stored as ints in DB."""
    from enum import IntEnum
    mod = _load_anomaly_event_module()
    assert issubclass(mod.AnomalySeverity, IntEnum)


def test_anomaly_severity_values():
    """INFO=0, WARNING=1, CRITICAL=2 — locked decision from planning doc."""
    mod = _load_anomaly_event_module()
    s = mod.AnomalySeverity
    assert s.INFO == 0
    assert s.WARNING == 1
    assert s.CRITICAL == 2


def test_anomaly_severity_three_levels_only():
    """Exactly 3 levels — no extra members (e.g. not the old 4-level NOMINAL/ADVISORY/ALERT/CRITICAL)."""
    mod = _load_anomaly_event_module()
    assert len(list(mod.AnomalySeverity)) == 3


def test_anomaly_severity_names():
    """Members must be named INFO, WARNING, CRITICAL."""
    mod = _load_anomaly_event_module()
    names = {m.name for m in mod.AnomalySeverity}
    assert names == {"INFO", "WARNING", "CRITICAL"}


# ---------------------------------------------------------------------------
# AnomalyEvent dataclass fields
# ---------------------------------------------------------------------------

def test_anomaly_event_required_fields_present():
    src = _read_src()
    for field_name in ("coordinator", "type", "severity", "event_class", "detected_at", "payload"):
        assert field_name in src, f"AnomalyEvent must have field '{field_name}'"


def test_anomaly_event_optional_fields_present():
    src = _read_src()
    for field_name in ("recovery_at", "entity_id", "room_id", "person_id", "correlation_id"):
        assert field_name in src, f"AnomalyEvent must have optional field '{field_name}'"


def test_anomaly_event_is_dataclass():
    src = _read_src()
    assert "@dataclass" in src
    assert "class AnomalyEvent" in src


def test_anomaly_event_instantiation_works():
    """Round-trip: construct AnomalyEvent with all required fields."""
    mod = _load_anomaly_event_module()
    ev = mod.AnomalyEvent(
        coordinator="energy",
        type="energy.crosscheck_divergence",
        severity=mod.AnomalySeverity.WARNING,
        event_class="point_in_time",
        detected_at="2026-05-12T10:00:00",
        payload={"divergence_pct": 20.0},
    )
    assert ev.coordinator == "energy"
    assert ev.severity == mod.AnomalySeverity.WARNING
    assert ev.recovery_at is None
    assert ev.entity_id is None


def test_anomaly_event_optional_fields_default_to_none():
    mod = _load_anomaly_event_module()
    ev = mod.AnomalyEvent(
        coordinator="bayesian",
        type="bayesian.prediction_anomaly",
        severity=mod.AnomalySeverity.INFO,
        event_class="point_in_time",
        detected_at="2026-05-12T10:00:00",
        payload={},
    )
    assert ev.recovery_at is None
    assert ev.entity_id is None
    assert ev.room_id is None
    assert ev.person_id is None
    assert ev.correlation_id is None


# ---------------------------------------------------------------------------
# event_class literal constants
# ---------------------------------------------------------------------------

def test_event_class_constants_exist():
    src = _read_src()
    for const in (
        "EVENT_CLASS_POINT_IN_TIME",
        "EVENT_CLASS_REGIME_SHIFT",
        "EVENT_CLASS_HAZARD",
        "EVENT_CLASS_TRANSITION_INVALID",
    ):
        assert const in src, f"Module must export constant {const}"


def test_event_class_constant_values():
    mod = _load_anomaly_event_module()
    assert mod.EVENT_CLASS_POINT_IN_TIME == "point_in_time"
    assert mod.EVENT_CLASS_REGIME_SHIFT == "regime_shift"
    assert mod.EVENT_CLASS_HAZARD == "hazard"
    assert mod.EVENT_CLASS_TRANSITION_INVALID == "transition_invalid"


def test_severity_int_value_usable_in_db_insert():
    """int(AnomalySeverity.WARNING) must be 1 — used raw in INSERT statements."""
    mod = _load_anomaly_event_module()
    assert int(mod.AnomalySeverity.WARNING) == 1
    assert int(mod.AnomalySeverity.CRITICAL) == 2
