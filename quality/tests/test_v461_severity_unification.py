"""v4.6.1 D1 — Severity vocabulary unification.
v4.6.3 D7/D9 update: store_anomaly() wrapper deleted; tests updated.

Tests that:
1. The new AnomalySeverity IntEnum is the canonical 3-level scale.
2. Old coordinator_diagnostics z-score classifier uses NOMINAL/ADVISORY/ALERT/CRITICAL.
3. v4.6.3: store_anomaly() wrapper is deleted; callers construct AnomalyEvent directly.
4. INT storage round-trips correctly.
"""

import importlib.util
import sys
from pathlib import Path


def _load_anomaly_event_module():
    mod_name = "ura_v461_ae_sev"
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


def _diag_src() -> str:
    return Path(
        "custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py"
    ).read_text()


# ---------------------------------------------------------------------------
# New unified enum
# ---------------------------------------------------------------------------

def test_new_severity_is_intenum():
    from enum import IntEnum
    mod = _load_anomaly_event_module()
    assert issubclass(mod.AnomalySeverity, IntEnum)


def test_new_severity_info_is_zero():
    mod = _load_anomaly_event_module()
    assert mod.AnomalySeverity.INFO == 0


def test_new_severity_warning_is_one():
    mod = _load_anomaly_event_module()
    assert mod.AnomalySeverity.WARNING == 1


def test_new_severity_critical_is_two():
    mod = _load_anomaly_event_module()
    assert mod.AnomalySeverity.CRITICAL == 2


# ---------------------------------------------------------------------------
# Old coordinator_diagnostics AnomalySeverity (StrEnum, kept for z-score logic)
# ---------------------------------------------------------------------------

def test_old_severity_nominal_still_exists_in_diagnostics():
    """Old AnomalySeverity StrEnum must still be present (used by z-score classifier)."""
    src = _diag_src()
    assert "NOMINAL" in src, (
        "Old AnomalySeverity.NOMINAL must survive — used by _classify_severity()"
    )


def test_old_severity_advisory_still_exists():
    src = _diag_src()
    assert "ADVISORY" in src


def test_old_severity_alert_still_exists():
    src = _diag_src()
    assert "ALERT" in src


# ---------------------------------------------------------------------------
# v4.6.3 D7/D9: store_anomaly() wrapper deleted; severity mapping is now
# each emit site's responsibility when constructing AnomalyEvent.
# ---------------------------------------------------------------------------

def test_severity_map_wrapper_deleted_v463():
    """v4.6.3 D7: store_anomaly() wrapper is deleted; no centralized severity mapping.

    v4.6.1 tested that store_anomaly() mapped NOMINAL→INFO/ADVISORY/ALERT→WARNING.
    v4.6.3 deleted that wrapper — each emit site now constructs AnomalyEvent with
    the correct AnomalySeverity directly.  The canonical 3-level scale
    (INFO/WARNING/CRITICAL) is defined by AnomalySeverity in anomaly_event.py.
    """
    src = _diag_src()
    assert "async def store_anomaly(" not in src, (
        "v4.6.3 D7: store_anomaly() wrapper must be deleted from coordinator_diagnostics.py"
    )


def test_classifier_uses_old_severity_internally():
    """_classify_severity() uses NOMINAL/ADVISORY/ALERT/CRITICAL for z-score thresholds.

    These internal constants survive D7 — they're used by the z-score classifier,
    not by the store_anomaly() wrapper which is now gone.
    """
    src = _diag_src()
    # _classify_severity or z-score logic still references these constants
    assert "ADVISORY" in src, (
        "coordinator_diagnostics must still define/use ADVISORY for z-score classification"
    )
    assert "ALERT" in src, (
        "coordinator_diagnostics must still define/use ALERT for z-score classification"
    )


def test_new_severity_scale_has_info_warning_critical():
    """The new AnomalySeverity scale (INFO/WARNING/CRITICAL) is defined in anomaly_event.py.

    Callers use this when constructing AnomalyEvent — they map from their domain
    context (e.g., ALERT z-score → WARNING severity) when constructing the event.
    """
    mod = _load_anomaly_event_module()
    sev = mod.AnomalySeverity
    assert sev.INFO == 0
    assert sev.WARNING == 1
    assert sev.CRITICAL == 2


def test_severity_int_round_trip():
    """AnomalySeverity values must survive int() cast and compare correctly."""
    mod = _load_anomaly_event_module()
    for member in mod.AnomalySeverity:
        assert int(member) == member.value
    assert int(mod.AnomalySeverity.INFO) < int(mod.AnomalySeverity.WARNING)
    assert int(mod.AnomalySeverity.WARNING) < int(mod.AnomalySeverity.CRITICAL)
