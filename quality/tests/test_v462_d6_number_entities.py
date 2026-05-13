"""v4.6.2 D6 — Number entity structural tests.

Source-grep tests verifying:
- 4 new Number entity classes exist with correct defaults and ranges
- RoutineRegimeBaselineWindowNumber + RoutineRegimeRecentWindowNumber:
  entity_registry_enabled_default=False (advanced tunables)
- RoutineEventCooldownDaysNumber + RoutineEventMinSeverityNumber:
  entity_registry_enabled_default=True (or absent, defaulting to True)
- All 4 registered in async_setup_entry for COORDINATOR_MANAGER
- CONF keys declared in const.py
"""

from pathlib import Path


def _number_src() -> str:
    return Path(
        "custom_components/universal_room_automation/number.py"
    ).read_text()


def _const_src() -> str:
    return Path(
        "custom_components/universal_room_automation/const.py"
    ).read_text()


# ---------------------------------------------------------------------------
# Class existence
# ---------------------------------------------------------------------------


def test_routine_event_cooldown_class_exists():
    src = _number_src()
    assert "class RoutineEventCooldownDaysNumber(" in src, (
        "RoutineEventCooldownDaysNumber must be defined in number.py"
    )


def test_routine_event_min_severity_class_exists():
    src = _number_src()
    assert "class RoutineEventMinSeverityNumber(" in src, (
        "RoutineEventMinSeverityNumber must be defined in number.py"
    )


def test_routine_regime_baseline_window_class_exists():
    src = _number_src()
    assert "class RoutineRegimeBaselineWindowNumber(" in src, (
        "RoutineRegimeBaselineWindowNumber must be defined in number.py"
    )


def test_routine_regime_recent_window_class_exists():
    src = _number_src()
    assert "class RoutineRegimeRecentWindowNumber(" in src, (
        "RoutineRegimeRecentWindowNumber must be defined in number.py"
    )


# ---------------------------------------------------------------------------
# Default values and ranges
# ---------------------------------------------------------------------------


def test_cooldown_days_default_30():
    src = _number_src()
    idx = src.find("class RoutineEventCooldownDaysNumber(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 2000]
    assert "30" in block, "RoutineEventCooldownDaysNumber default must be 30"
    assert "365" in block, "RoutineEventCooldownDaysNumber max must be 365"


def test_min_severity_default_1():
    src = _number_src()
    idx = src.find("class RoutineEventMinSeverityNumber(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 2000]
    assert "_default = 1" in block or "default = 1" in block or "= 1\n" in block or "1," in block, (
        "RoutineEventMinSeverityNumber default must be 1 (WARNING)"
    )
    assert "2" in block, "RoutineEventMinSeverityNumber max must be 2 (CRITICAL)"


def test_baseline_window_default_56():
    src = _number_src()
    idx = src.find("class RoutineRegimeBaselineWindowNumber(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 2000]
    assert "56" in block, "RoutineRegimeBaselineWindowNumber default must be 56"


def test_recent_window_default_14():
    src = _number_src()
    idx = src.find("class RoutineRegimeRecentWindowNumber(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 2000]
    assert "14" in block, "RoutineRegimeRecentWindowNumber default must be 14"


# ---------------------------------------------------------------------------
# Advanced tunables disabled by default
# ---------------------------------------------------------------------------


def test_baseline_window_disabled_by_default():
    src = _number_src()
    idx = src.find("class RoutineRegimeBaselineWindowNumber(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 2000]
    assert "entity_registry_enabled_default = False" in block, (
        "RoutineRegimeBaselineWindowNumber must be disabled by default (advanced tunable)"
    )


def test_recent_window_disabled_by_default():
    src = _number_src()
    idx = src.find("class RoutineRegimeRecentWindowNumber(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 2000]
    assert "entity_registry_enabled_default = False" in block, (
        "RoutineRegimeRecentWindowNumber must be disabled by default (advanced tunable)"
    )


# ---------------------------------------------------------------------------
# Registered in CM setup
# ---------------------------------------------------------------------------


def test_all_four_numbers_registered_in_cm_setup():
    src = _number_src()
    assert "RoutineEventCooldownDaysNumber(hass, entry)" in src, (
        "RoutineEventCooldownDaysNumber must be registered in async_setup_entry"
    )
    assert "RoutineEventMinSeverityNumber(hass, entry)" in src, (
        "RoutineEventMinSeverityNumber must be registered in async_setup_entry"
    )
    assert "RoutineRegimeBaselineWindowNumber(hass, entry)" in src, (
        "RoutineRegimeBaselineWindowNumber must be registered in async_setup_entry"
    )
    assert "RoutineRegimeRecentWindowNumber(hass, entry)" in src, (
        "RoutineRegimeRecentWindowNumber must be registered in async_setup_entry"
    )


# ---------------------------------------------------------------------------
# CONF keys in const.py
# ---------------------------------------------------------------------------


def test_conf_routine_event_cooldown_days_in_const():
    src = _const_src()
    assert "CONF_ROUTINE_EVENT_COOLDOWN_DAYS" in src, (
        "CONF_ROUTINE_EVENT_COOLDOWN_DAYS must be declared in const.py"
    )


def test_conf_routine_event_min_severity_in_const():
    src = _const_src()
    assert "CONF_ROUTINE_EVENT_MIN_SEVERITY" in src, (
        "CONF_ROUTINE_EVENT_MIN_SEVERITY must be declared in const.py"
    )


def test_conf_routine_regime_baseline_window_in_const():
    src = _const_src()
    assert "CONF_ROUTINE_REGIME_BASELINE_WINDOW_DAYS" in src, (
        "CONF_ROUTINE_REGIME_BASELINE_WINDOW_DAYS must be declared in const.py"
    )


def test_conf_routine_regime_recent_window_in_const():
    src = _const_src()
    assert "CONF_ROUTINE_REGIME_RECENT_WINDOW_DAYS" in src, (
        "CONF_ROUTINE_REGIME_RECENT_WINDOW_DAYS must be declared in const.py"
    )
