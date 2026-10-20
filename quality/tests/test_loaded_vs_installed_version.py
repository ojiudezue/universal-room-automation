"""EC-LOADED-VS-INSTALLED-VERSION-1 — loaded (const.VERSION) vs installed
(manifest.json on disk) version check + repair issue + sensor attributes.

Oracles are hardcoded literals (never derived from the code under test).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import custom_components.universal_room_automation as ura
from custom_components.universal_room_automation import version_check as vc

DOMAIN = "universal_room_automation"


class _Hass:
    """Minimal hass: records executor jobs and runs them synchronously."""

    def __init__(self) -> None:
        self.data: dict = {}
        self.executor_calls: list = []

    async def async_add_executor_job(self, func, *args):
        self.executor_calls.append((func, args))
        return func(*args)


def _manifest(tmp_path: Path, version) -> Path:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"domain": DOMAIN, "version": version}))
    return p


def _run(hass, path, loaded="v5.103.72"):
    ir = MagicMock()
    ir.IssueSeverity.WARNING = "warning"
    with patch.object(vc, "ir", ir), patch.object(vc, "VERSION", loaded):
        import asyncio

        status = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            vc.async_check_version(hass, path)
        )
    return status, ir


def test_mismatch_creates_issue_with_both_versions(tmp_path):
    hass = _Hass()
    status, ir = _run(hass, _manifest(tmp_path, "5.103.74"))
    assert status == {
        "loaded_version": "5.103.72",
        "installed_version": "5.103.74",
        "restart_pending": True,
    }
    ir.async_create_issue.assert_called_once()
    args, kwargs = ir.async_create_issue.call_args
    assert args[1] == DOMAIN
    assert args[2] == "restart_pending_version_mismatch"
    assert kwargs["is_fixable"] is False
    assert kwargs["severity"] == "warning"
    assert kwargs["translation_key"] == "restart_pending_version_mismatch"
    assert kwargs["translation_placeholders"] == {
        "loaded": "5.103.72", "installed": "5.103.74",
    }
    ir.async_delete_issue.assert_not_called()
    assert hass.data[DOMAIN]["version_status"]["restart_pending"] is True


def test_match_deletes_issue(tmp_path):
    hass = _Hass()
    status, ir = _run(hass, _manifest(tmp_path, "5.103.74"), loaded="v5.103.74")
    assert status["restart_pending"] is False
    ir.async_create_issue.assert_not_called()
    ir.async_delete_issue.assert_called_once_with(
        hass, DOMAIN, "restart_pending_version_mismatch",
    )


@pytest.mark.parametrize("content", [None, "{not json", "missing"])
def test_unreadable_manifest_is_noop(tmp_path, content):
    hass = _Hass()
    p = tmp_path / "manifest.json"
    if content == "missing":
        pass
    elif content is None:
        p.write_text(json.dumps({"domain": DOMAIN}))
    else:
        p.write_text(content)
    status, ir = _run(hass, p)
    assert status["installed_version"] is None
    assert status["restart_pending"] is False
    ir.async_create_issue.assert_not_called()
    ir.async_delete_issue.assert_not_called()


def test_manifest_read_goes_through_executor(tmp_path):
    hass = _Hass()
    path = _manifest(tmp_path, "5.103.74")
    _run(hass, path)
    assert hass.executor_calls == [(vc._read_manifest_version, (path,))]


def test_executor_failure_never_raises(tmp_path):
    hass = _Hass()

    async def boom(*_a):
        raise RuntimeError("executor down")

    hass.async_add_executor_job = boom
    status, ir = _run(hass, _manifest(tmp_path, "5.103.74"))
    assert status["installed_version"] is None
    ir.async_create_issue.assert_not_called()


@pytest.mark.parametrize("raw,expected", [
    ("v5.103.74", "5.103.74"),
    ("V5.103.74", "5.103.74"),
    ("5.103.74", "5.103.74"),
    (" v5.103.74 ", "5.103.74"),
    ("", None),
    (None, None),
])
def test_v_prefix_normalisation(raw, expected):
    assert vc.normalize_version(raw) == expected


def test_v_prefix_only_difference_is_not_pending(tmp_path):
    hass = _Hass()
    status, ir = _run(hass, _manifest(tmp_path, "v5.103.74"), loaded="v5.103.74")
    assert status["restart_pending"] is False
    ir.async_create_issue.assert_not_called()


def test_real_manifest_matches_const_version():
    """The shipped tree must be self-consistent (deploy bumps both)."""
    hass = _Hass()
    import asyncio

    ir = MagicMock()
    with patch.object(vc, "ir", ir):
        status = asyncio.new_event_loop().run_until_complete(
            vc.async_check_version(hass)
        )
    assert status["installed_version"] is not None
    assert status["restart_pending"] is False


def test_start_runs_check_and_arms_hourly_timer():
    hass = _Hass()
    calls: list = []

    async def fake_check(h, *_a):
        calls.append(h)
        return {}

    unsub = MagicMock()
    track = MagicMock(return_value=unsub)
    entry = SimpleNamespace(async_on_unload=MagicMock())
    import asyncio

    with patch.object(vc, "async_check_version", fake_check), \
            patch.object(vc, "async_track_time_interval", track):
        asyncio.new_event_loop().run_until_complete(
            vc.async_start_version_check(hass, entry)
        )
        assert calls == [hass]  # immediate check at setup
        _h, tick, interval = track.call_args.args
        assert interval.total_seconds() == 3600
        entry.async_on_unload.assert_called_once_with(unsub)
        asyncio.new_event_loop().run_until_complete(tick(None))
        assert calls == [hass, hass]  # timer tick runs the check


class _StopSetup(BaseException):
    pass


def test_integration_setup_entry_calls_version_check():
    """Wire-in anchor: async_setup_entry(integration) must start the check."""
    seen: list = []

    async def fake_start(h, e):
        seen.append((h, e))
        raise _StopSetup  # BaseException: escapes the non-fatal guard

    hass = SimpleNamespace(data={})
    entry = SimpleNamespace(
        data={"entry_type": "integration"}, options={}, entry_id="int1",
        title="URA",
    )
    import asyncio

    async def _noop(*_a, **_k):
        return None

    with patch.object(vc, "async_start_version_check", fake_start), \
            patch.object(ura, "_migrate_room_zone_name_writethrough", lambda *a: None), \
            patch.object(ura, "_check_and_notify_room_name_desync", _noop), \
            patch(
                "custom_components.universal_room_automation.domain_coordinators"
                "._loop_stall_watchdog.install", lambda *a: None,
            ):
        with pytest.raises(_StopSetup):
            asyncio.new_event_loop().run_until_complete(
                ura.async_setup_entry(hass, entry)
            )
    assert seen == [(hass, entry)]


def test_coordinator_manager_sensor_exposes_version_attrs():
    from custom_components.universal_room_automation import sensor as sensor_mod

    hass = SimpleNamespace(data={DOMAIN: {
        "coordinator_manager": SimpleNamespace(
            coordinators={}, decisions_today=0, conflicts_resolved_today=0,
        ),
        "version_status": {
            "loaded_version": "5.103.72",
            "installed_version": "5.103.74",
            "restart_pending": True,
        },
    }})
    ent = object.__new__(sensor_mod.CoordinatorManagerSensor)
    ent.hass = hass
    attrs = ent.extra_state_attributes
    assert attrs["loaded_version"] == "5.103.72"
    assert attrs["installed_version"] == "5.103.74"
    assert attrs["restart_pending"] is True
