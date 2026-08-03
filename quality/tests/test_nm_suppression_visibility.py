"""B-2026-08-03-3(a)+(b): NM suppression visibility.

(a) `messaging_suppressed` + `suppressed_since` are exposed on the NM
    diagnostics/heartbeat sensor's attributes (via `diagnostics_summary`
    which the sensor promotes to `extra_state_attributes`).
(b) While suppressed, one WARNING/day is emitted piggybacking the
    existing 2 AM activity-prune hook — no new timers.

Part (c) (refuse-to-restore-suppressed after 24h) is explicitly out of
scope pending operator decision and is NOT tested here.
"""
from __future__ import annotations

import ast
import inspect
import logging
import os
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


HERE = os.path.dirname(__file__)
NM_PATH = os.path.abspath(
    os.path.join(
        HERE, "..", "..",
        "custom_components", "universal_room_automation",
        "domain_coordinators", "notification_manager.py",
    )
)
INIT_PATH = os.path.abspath(
    os.path.join(
        HERE, "..", "..",
        "custom_components", "universal_room_automation",
        "__init__.py",
    )
)
SENSOR_PATH = os.path.abspath(
    os.path.join(
        HERE, "..", "..",
        "custom_components", "universal_room_automation",
        "sensor.py",
    )
)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# (a) diagnostics_summary must expose messaging_suppressed + suppressed_since
# ---------------------------------------------------------------------------
def test_diagnostics_summary_exposes_suppressed_since():
    src = _read(NM_PATH)
    assert '"messaging_suppressed": self._messaging_suppressed' in src, (
        "messaging_suppressed must remain in diagnostics_summary"
    )
    assert '"suppressed_since"' in src, (
        "suppressed_since must be added to diagnostics_summary"
    )


def test_nm_diagnostics_sensor_publishes_diagnostics_summary():
    """The NM diagnostics sensor already returns nm.diagnostics_summary
    as extra_state_attributes — the suppressed_since key rides along."""
    src = _read(SENSOR_PATH)
    assert "class NMDiagnosticsSensor" in src
    # Sensor must publish diagnostics_summary as attributes.
    assert "attrs = nm.diagnostics_summary" in src, (
        "NMDiagnosticsSensor must publish nm.diagnostics_summary "
        "(which carries messaging_suppressed + suppressed_since)"
    )


def test_suppressed_since_initialized_none():
    src = _read(NM_PATH)
    assert "self._suppressed_since: datetime | None = None" in src


def test_suppress_stamps_since_only_on_flip_edge():
    """The flip-edge guard ensures a restore-on-restart resync path
    (async_suppress_messaging called while already suppressed) does NOT
    clobber the true origin timestamp."""
    src = _read(NM_PATH)
    assert "was_suppressed = self._messaging_suppressed" in src
    # Only set if was NOT already suppressed AND stamp is currently None.
    assert (
        "if not was_suppressed and self._suppressed_since is None:" in src
    )


def test_resume_clears_since():
    src = _read(NM_PATH)
    # Find async_resume_messaging body and confirm it clears _suppressed_since.
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_resume_messaging":
            body_src = ast.get_source_segment(src, node) or ""
            assert "self._suppressed_since = None" in body_src, (
                "async_resume_messaging must clear _suppressed_since"
            )
            return
    raise AssertionError("async_resume_messaging not found")


def test_persistence_roundtrip_includes_suppressed_since():
    src = _read(NM_PATH)
    # get_persistence_state must serialize it; restore_persistence_state
    # must deserialize it with a guarded fromisoformat.
    assert '"suppressed_since": (' in src or '"suppressed_since":' in src
    assert "datetime.fromisoformat(sus)" in src, (
        "restore_persistence_state must parse suppressed_since ISO string"
    )


# ---------------------------------------------------------------------------
# (b) Daily WARNING piggybacks the existing 2 AM activity-prune hook.
# ---------------------------------------------------------------------------
def test_daily_warning_helper_defined():
    src = _read(INIT_PATH)
    assert "def _log_nm_suppression_daily_warning(hass" in src


def test_daily_warning_wired_into_prune_hook_no_new_timer():
    src = _read(INIT_PATH)
    # Both daily activity-prune paths (main + deferred) call the helper.
    # The helper is called from the prune body — NOT scheduled as a new timer.
    for hook in ("_daily_activity_prune", "_daily_prune_deferred"):
        # Locate hook body and confirm the helper call is inside.
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == hook:
                body_src = ast.get_source_segment(src, node) or ""
                assert "_log_nm_suppression_daily_warning(hass)" in body_src, (
                    f"{hook} must call _log_nm_suppression_daily_warning"
                )
                found = True
                break
        assert found, f"{hook} not found in __init__.py"


def test_no_new_time_change_registration_for_nm_warning():
    """B-2026-08-03-3(b) explicitly says 'piggyback an existing daily
    hook — no new timers if avoidable'. Verify no async_track_time_change
    is registered specifically for NM suppression."""
    src = _read(INIT_PATH)
    # Grep for anything like "nm_suppression"-related timer registration.
    assert "nm_suppression" not in src.lower() or (
        "async_track_time_change" not in src.split("nm_suppression")[1].split("\n\n")[0]
        if "nm_suppression" in src.lower() else True
    )


# ---------------------------------------------------------------------------
# Behavioral: the helper logs one WARNING with duration derived from
# nm._suppressed_since when present, else falls back to switch last_changed.
# ---------------------------------------------------------------------------

def _load_helper():
    """Isolate the helper without importing the whole __init__ module.

    The helper contains an inline `from homeassistant.util import dt`
    import. We rewrite that single line to bind a controlled fake before
    exec — no sys.modules mutation, no cross-test pollution.
    """
    src = _read(INIT_PATH)
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_log_nm_suppression_daily_warning":
            code = ast.get_source_segment(src, node)
            _fake_dtu = types.SimpleNamespace(utcnow=lambda: datetime.now(timezone.utc))
            # Replace the inline import with a bind to the fake — keeps
            # source line count for any downstream regex/AST anchors.
            code = code.replace(
                "from homeassistant.util import dt as _dtu",
                "_dtu = _INJECTED_DTU  # test-shim: bypasses inline import",
            )
            _logger = logging.getLogger("test_nm_suppression_visibility")
            ns: dict = {
                "HomeAssistant": object,
                "DOMAIN": "universal_room_automation",
                "_LOGGER": _logger,
                "_INJECTED_DTU": _fake_dtu,
            }
            exec(code, ns)
            return ns["_log_nm_suppression_daily_warning"], _logger
    raise AssertionError("_log_nm_suppression_daily_warning not found")


def _make_hass(nm, switch_state=None):
    hass = MagicMock()
    hass.data = {"universal_room_automation": {"notification_manager": nm}}
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=switch_state)
    return hass


def test_helper_noop_when_not_suppressed(caplog):
    helper, logger = _load_helper()
    nm = types.SimpleNamespace(messaging_suppressed=False, _suppressed_since=None)
    with caplog.at_level(logging.WARNING, logger=logger.name):
        helper(_make_hass(nm))
    assert not any("suppressed" in r.message.lower() for r in caplog.records)


def test_helper_logs_days_from_nm_since(caplog):
    helper, logger = _load_helper()
    since = datetime.now(timezone.utc) - timedelta(days=6, hours=1)
    nm = types.SimpleNamespace(
        messaging_suppressed=True,
        _suppressed_since=since,
    )
    with caplog.at_level(logging.WARNING, logger=logger.name):
        helper(_make_hass(nm))
    matching = [r for r in caplog.records if "NM messaging suppressed" in r.message]
    assert len(matching) == 1
    assert "6 days" in matching[0].message
    assert "nm_suppressed_since" in matching[0].message


def test_helper_falls_back_to_switch_last_changed(caplog):
    helper, logger = _load_helper()
    nm = types.SimpleNamespace(
        messaging_suppressed=True,
        _suppressed_since=None,  # no NM stamp
    )
    switch = MagicMock()
    switch.last_changed = datetime.now(timezone.utc) - timedelta(days=3)
    with caplog.at_level(logging.WARNING, logger=logger.name):
        helper(_make_hass(nm, switch_state=switch))
    matching = [r for r in caplog.records if "NM messaging suppressed" in r.message]
    assert len(matching) == 1
    assert "3 days" in matching[0].message
    assert "switch_last_changed_approx" in matching[0].message


def test_helper_handles_both_sources_missing(caplog):
    helper, logger = _load_helper()
    nm = types.SimpleNamespace(
        messaging_suppressed=True,
        _suppressed_since=None,
    )
    with caplog.at_level(logging.WARNING, logger=logger.name):
        helper(_make_hass(nm, switch_state=None))
    matching = [r for r in caplog.records if "NM messaging suppressed" in r.message]
    assert len(matching) == 1
    assert "duration unknown" in matching[0].message
