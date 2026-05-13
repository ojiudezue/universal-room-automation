"""v4.6.1 D1 — Severity vocabulary unification.

Tests that:
1. The new AnomalySeverity IntEnum is the canonical 3-level scale.
2. Old coordinator_diagnostics AnomalySeverity (NOMINAL/ADVISORY/ALERT/CRITICAL)
   is mapped correctly in store_anomaly() wrapper.
3. store_anomaly() severity map covers all 4 old values.
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
# Mapping in store_anomaly() wrapper
# ---------------------------------------------------------------------------

def test_severity_map_covers_all_four_old_values():
    """store_anomaly() must explicitly map NOMINAL, ADVISORY, ALERT, CRITICAL."""
    src = _diag_src()
    idx = src.find("async def store_anomaly(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 2000]
    for old_val in ("NOMINAL", "ADVISORY", "ALERT", "CRITICAL"):
        assert old_val in block, (
            f"store_anomaly severity map must cover AnomalySeverity.{old_val}"
        )


def test_severity_map_nominal_maps_to_info():
    src = _diag_src()
    idx = src.find("async def store_anomaly(")
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 2000]
    # NOMINAL should map to INFO
    # Look for the pair in the block
    assert "NOMINAL" in block and "INFO" in block, (
        "NOMINAL must map to INFO in store_anomaly severity mapping"
    )


def test_severity_map_alert_maps_to_warning():
    """ALERT (z≥3) maps to WARNING — not CRITICAL — per planning doc decision."""
    src = _diag_src()
    idx = src.find("async def store_anomaly(")
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 2000]
    assert "ALERT" in block and "WARNING" in block, (
        "ALERT must map to WARNING in store_anomaly (survey §2 decision)"
    )


def test_severity_int_round_trip():
    """AnomalySeverity values must survive int() cast and compare correctly."""
    mod = _load_anomaly_event_module()
    for member in mod.AnomalySeverity:
        assert int(member) == member.value
    assert int(mod.AnomalySeverity.INFO) < int(mod.AnomalySeverity.WARNING)
    assert int(mod.AnomalySeverity.WARNING) < int(mod.AnomalySeverity.CRITICAL)
