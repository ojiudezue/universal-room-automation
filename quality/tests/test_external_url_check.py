"""v5.107.3 external-URL reachability self-check.

Drives the real probe (real aiohttp ClientTimeout, fake shared session) and
the real start/unload wiring. Oracles are hardcoded literals.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.universal_room_automation import external_url_check as euc

DOMAIN = "universal_room_automation"
ISSUE = "external_url_unreachable"
URL = "https://madronehaos.phalanxmadrone.com"


class _Resp:
    def __init__(self, status):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    def __init__(self, status=200, exc=None):
        self.status, self.exc = status, exc
        self.calls: list = []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        if self.exc is not None:
            raise self.exc
        return _Resp(self.status)


def _hass(url=URL):
    return SimpleNamespace(config=SimpleNamespace(external_url=url), data={})


def _run(hass, session):
    ir = MagicMock()
    ir.IssueSeverity.WARNING = "warning"
    with patch.object(euc, "ir", ir), patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        lambda _h: session,
    ):
        status = asyncio.new_event_loop().run_until_complete(
            euc.async_check_external_url(hass)
        )
    return status, ir


def _assert_created(ir, hass, url, reason):
    ir.async_create_issue.assert_called_once()
    args, kw = ir.async_create_issue.call_args
    assert args == (hass, DOMAIN, ISSUE)
    assert kw["is_fixable"] is False
    assert kw["severity"] == "warning"
    assert kw["translation_key"] == ISSUE
    assert kw["translation_placeholders"] == {"url": url, "reason": reason}
    ir.async_delete_issue.assert_not_called()


def test_pass_deletes_issue_and_probes_manifest_unauthenticated():
    hass, s = _hass(URL + "/"), _Session(200)
    status, ir = _run(hass, s)
    assert status == {"external_url": URL, "reachable": True, "reason": "HTTP 200"}
    ir.async_delete_issue.assert_called_once_with(hass, DOMAIN, ISSUE)
    ir.async_create_issue.assert_not_called()
    (url, kw), = s.calls
    assert url == URL + "/manifest.json"
    assert "headers" not in kw and "auth" not in kw
    assert kw["timeout"].total == 10


def test_timeout_raises_issue():
    hass = _hass()
    status, ir = _run(hass, _Session(exc=asyncio.TimeoutError()))
    assert status["reachable"] is False
    _assert_created(ir, hass, URL, "TimeoutError")


def test_dns_error_raises_issue():
    import aiohttp

    hass = _hass()
    _status, ir = _run(hass, _Session(exc=aiohttp.ClientConnectionError("dns")))
    _assert_created(ir, hass, URL, "ClientConnectionError")


@pytest.mark.parametrize("code", [404, 502, 301])
def test_non_2xx_raises_issue(code):
    hass = _hass()
    _status, ir = _run(hass, _Session(code))
    _assert_created(ir, hass, URL, f"HTTP {code}")


def test_2xx_boundaries():
    for code, ok in ((199, False), (200, True), (299, True), (300, False)):
        status, _ir = _run(_hass(), _Session(code))
        assert status["reachable"] is ok, code


def test_clear_on_recovery():
    hass = _hass()
    _s, ir1 = _run(hass, _Session(503))
    ir1.async_create_issue.assert_called_once()
    _s, ir2 = _run(hass, _Session(200))
    ir2.async_delete_issue.assert_called_once_with(hass, DOMAIN, ISSUE)
    ir2.async_create_issue.assert_not_called()


@pytest.mark.parametrize("url", [None, ""])
def test_unset_is_noop(url):
    s = _Session(200)
    status, ir = _run(_hass(url), s)
    assert status["reachable"] is None
    assert s.calls == []
    ir.async_create_issue.assert_not_called()
    ir.async_delete_issue.assert_not_called()


def test_start_defers_to_started_then_daily_and_unsubs_on_unload():
    hass = _hass()
    unloads: list = []
    entry = SimpleNamespace(async_on_unload=unloads.append)
    started: list = []
    at_started_unsub = MagicMock(name="at_started_unsub")
    interval_unsub = MagicMock(name="interval_unsub")
    track = MagicMock(return_value=interval_unsub)
    checks: list = []

    async def fake_check(h):
        checks.append(h)

    def fake_at_started(h, cb):
        started.append(cb)
        return at_started_unsub

    with patch("homeassistant.helpers.start.async_at_started", fake_at_started), \
            patch.object(euc, "async_track_time_interval", track), \
            patch.object(euc, "async_check_external_url", fake_check):
        euc.async_start_external_url_check(hass, entry)
        # Deferred: nothing probed until HA has started.
        assert checks == [] and track.call_count == 0
        assert unloads == [at_started_unsub]
        loop = asyncio.new_event_loop()
        loop.run_until_complete(started[0](hass))
        assert checks == [hass]
        _h, tick, interval = track.call_args.args
        assert interval.total_seconds() == 86400
        assert unloads == [at_started_unsub, interval_unsub]
        loop.run_until_complete(tick(None))
        assert checks == [hass, hass]
    # Unload: HA calls every registered unsub.
    for unsub in unloads:
        unsub()
    at_started_unsub.assert_called_once()
    interval_unsub.assert_called_once()


class _StopSetup(BaseException):
    pass


def test_integration_setup_entry_starts_external_url_check():
    """Wire-in anchor: async_setup_entry(integration) starts the check."""
    import importlib
    import sys

    seen: list = []

    def fake_start(h, e):
        seen.append((h, e))
        raise _StopSetup

    async def _noop(*_a, **_k):
        return None

    hass = SimpleNamespace(data={})
    entry = SimpleNamespace(
        data={"entry_type": "integration"}, options={}, entry_id="int1",
        title="URA",
    )
    pkg = "custom_components.universal_room_automation"
    parent = sys.modules.get("custom_components")
    _missing = object()
    orig_attr = getattr(parent, "universal_room_automation", _missing)
    try:
        with patch.dict(sys.modules):
            for key in [k for k in sys.modules if k == pkg or k.startswith(pkg + ".")]:
                del sys.modules[key]
            live_ura = importlib.import_module(pkg)
            live_vc = importlib.import_module(pkg + ".version_check")
            live_euc = importlib.import_module(pkg + ".external_url_check")
            with patch.object(live_vc, "async_start_version_check", _noop), \
                    patch.object(live_euc, "async_start_external_url_check", fake_start), \
                    patch.object(live_ura, "_migrate_room_zone_name_writethrough", lambda *a: None), \
                    patch.object(live_ura, "_check_and_notify_room_name_desync", _noop), \
                    patch(
                        pkg + ".domain_coordinators._loop_stall_watchdog.install",
                        lambda *a: None,
                    ):
                with pytest.raises(_StopSetup):
                    asyncio.new_event_loop().run_until_complete(
                        live_ura.async_setup_entry(hass, entry)
                    )
    finally:
        if parent is not None:
            if orig_attr is _missing:
                parent.__dict__.pop("universal_room_automation", None)
            else:
                parent.universal_room_automation = orig_attr
    assert seen == [(hass, entry)]


def test_translation_strings_present():
    import json
    from pathlib import Path

    root = Path(euc.__file__).parent
    for name in ("strings.json", "translations/en.json"):
        issue = json.loads((root / name).read_text(encoding="utf-8"))["issues"][ISSUE]
        assert "{url}" in issue["description"]
        assert "Settings → System → Network" in issue["description"]
