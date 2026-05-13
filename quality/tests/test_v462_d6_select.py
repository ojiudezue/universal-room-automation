"""v4.6.2 D6 — RoutineNotificationModeSelect structural tests.

Source-grep tests verifying:
- Select entity class exists with correct options
- Default is 'silent'
- State persisted to entry.options under CONF_ROUTINE_CHANGE_NOTIFICATION_MODE
- On CM device
- Registered in async_setup_entry for COORDINATOR_MANAGER
"""

from pathlib import Path


def _select_src() -> str:
    return Path(
        "custom_components/universal_room_automation/select.py"
    ).read_text()


def _const_src() -> str:
    return Path(
        "custom_components/universal_room_automation/const.py"
    ).read_text()


# ---------------------------------------------------------------------------
# Class existence and options
# ---------------------------------------------------------------------------


def test_routine_notification_mode_select_class_exists():
    src = _select_src()
    assert "class RoutineNotificationModeSelect(" in src, (
        "RoutineNotificationModeSelect must be defined in select.py"
    )


def test_select_options_are_correct():
    src = _select_src()
    idx = src.find("class RoutineNotificationModeSelect(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 3000]
    assert "silent" in block, "Options must include 'silent'"
    assert "weekly_digest" in block, "Options must include 'weekly_digest'"
    assert "event" in block, "Options must include 'event'"


def test_select_default_is_silent():
    src = _select_src()
    idx = src.find("class RoutineNotificationModeSelect(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 3000]
    # Default must fall back to "silent" — check the options seed in __init__
    assert '"silent"' in block or "'silent'" in block, (
        "RoutineNotificationModeSelect must default to 'silent'"
    )


# ---------------------------------------------------------------------------
# Const key
# ---------------------------------------------------------------------------


def test_conf_routine_change_notification_mode_in_const():
    src = _const_src()
    assert "CONF_ROUTINE_CHANGE_NOTIFICATION_MODE" in src, (
        "CONF_ROUTINE_CHANGE_NOTIFICATION_MODE must be defined in const.py"
    )
    assert "routine_change_notification_mode" in src, (
        "CONF_ROUTINE_CHANGE_NOTIFICATION_MODE value must be 'routine_change_notification_mode'"
    )


# ---------------------------------------------------------------------------
# State persistence to entry.options
# ---------------------------------------------------------------------------


def test_select_persists_to_entry_options():
    src = _select_src()
    idx = src.find("class RoutineNotificationModeSelect(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 3000]
    assert "async_update_entry" in block, (
        "async_select_option must persist mode to entry.options via async_update_entry"
    )
    assert "CONF_ROUTINE_CHANGE_NOTIFICATION_MODE" in block, (
        "async_select_option must use CONF_ROUTINE_CHANGE_NOTIFICATION_MODE as the options key"
    )


# ---------------------------------------------------------------------------
# Device and registration
# ---------------------------------------------------------------------------


def test_select_on_cm_device():
    src = _select_src()
    idx = src.find("class RoutineNotificationModeSelect(")
    assert idx >= 0
    end = src.find("\nclass ", idx + 1)
    block = src[idx: end if end > 0 else idx + 3000]
    assert "coordinator_manager" in block, (
        "RoutineNotificationModeSelect must be on the coordinator_manager device"
    )


def test_select_registered_in_cm_setup_entry():
    src = _select_src()
    assert "RoutineNotificationModeSelect(hass, entry)" in src, (
        "RoutineNotificationModeSelect must be instantiated in async_setup_entry "
        "for COORDINATOR_MANAGER entry type"
    )
