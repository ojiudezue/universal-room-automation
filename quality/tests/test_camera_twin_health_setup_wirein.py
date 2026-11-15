"""Person-awareness ship 3b wire-in anchors: the coordinator-manager entry's
REAL ``async_setup_entry`` creates the camera twin owner through
``camera_twin_health.async_setup_camera_twin_health``, and its REAL
``async_unload_entry`` tears it down through
``async_teardown_camera_twin_health``.

Same pattern as test_crossing_vision_setup_wirein.py: the helper is replaced
by a recorder that raises a BaseException sentinel (setup's ``except
Exception`` blocks cannot swallow it), so the path stops exactly at the call
site. Deleting the call means the recorder is never reached -> RED.
"""
from __future__ import annotations

import asyncio
import importlib

import pytest

pytest.importorskip("homeassistant.helpers.frame")

from runtime_harness import StubConfigEntry, StubHass  # noqa: E402


class _Reached(BaseException):
    pass


@pytest.fixture(autouse=True)
def _real_homeassistant_modules():
    """Swap hand-made homeassistant stubs for the real modules and re-import
    the URA package fresh; restore exactly what was there afterwards."""
    import sys
    from unittest.mock import Mock

    def _stub(mod):
        f = getattr(mod, "__file__", None)
        return isinstance(mod, Mock) or not (isinstance(f, str) and f.endswith(".py"))

    pkg = "custom_components.universal_room_automation"

    def _ours(n):
        return n == pkg or n.startswith(pkg + ".")

    def _ha(n):
        return n == "homeassistant" or n.startswith("homeassistant.")

    saved = {n: m for n, m in sys.modules.items()
             if (_ha(n) and _stub(m)) or _ours(n)}
    for n in saved:
        sys.modules.pop(n, None)
    before = set(sys.modules)
    try:
        importlib.import_module("homeassistant.helpers.event")
        importlib.import_module(pkg)
        yield
    finally:
        for n in set(sys.modules) - before:
            if _ha(n) or _ours(n):
                sys.modules.pop(n, None)
        sys.modules.update(saved)


def _mods():
    init_mod = importlib.import_module("custom_components.universal_room_automation")
    const = importlib.import_module("custom_components.universal_room_automation.const")
    cth = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.camera_twin_health"
    )
    return init_mod, const, cth


def test_cm_setup_entry_creates_camera_twin_owner(monkeypatch):
    """The REAL CM-entry setup reaches async_setup_camera_twin_health."""
    init_mod, const, cth = _mods()
    calls = []

    async def _recorder(hass):
        calls.append(const.DOMAIN in hass.data)
        raise _Reached()

    monkeypatch.setattr(cth, "async_setup_camera_twin_health", _recorder)
    # The CM branch stamps its device tree before the owner call; the stub
    # hass has no loaded registries, so hand it inert ones.
    from unittest.mock import MagicMock
    dr_mod = importlib.import_module("homeassistant.helpers.device_registry")
    er_mod = importlib.import_module("homeassistant.helpers.entity_registry")
    monkeypatch.setattr(dr_mod, "async_get", lambda _h: MagicMock())
    monkeypatch.setattr(er_mod, "async_get", lambda _h: MagicMock())
    wd = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators._loop_stall_watchdog"
    )
    monkeypatch.setattr(wd, "install", lambda _hass: None)
    hass = StubHass()
    entry = StubConfigEntry("cm", const.ENTRY_TYPE_COORDINATOR_MANAGER, data={})

    async def _forward(_entry, _platforms):
        return True

    hass.config_entries.async_forward_entry_setups = _forward
    with pytest.raises(_Reached):
        asyncio.run(init_mod.async_setup_entry(hass, entry))
    assert calls == [True]


def test_cm_unload_entry_tears_down_camera_twin_owner(monkeypatch):
    """The REAL CM-entry unload reaches async_teardown_camera_twin_health
    before the platforms unload."""
    init_mod, const, cth = _mods()
    calls = []

    def _recorder(hass):
        calls.append("teardown")
        raise _Reached()

    monkeypatch.setattr(cth, "async_teardown_camera_twin_health", _recorder)
    hass = StubHass()
    entry = StubConfigEntry("cm", const.ENTRY_TYPE_COORDINATOR_MANAGER, data={})
    unloaded = []

    async def _unload_platforms(_entry, _platforms):
        unloaded.append(True)
        return True

    hass.config_entries.async_unload_platforms = _unload_platforms
    with pytest.raises(_Reached):
        asyncio.run(init_mod.async_unload_entry(hass, entry))
    assert calls == ["teardown"]
    assert unloaded == []


def test_owner_setup_and_teardown_real():
    """The real helpers: the owner lands at hass.data[DOMAIN]
    ["camera_twin_health"], set up (first build attempted, map_ready), and
    teardown pops it and marks it torn down."""
    _init, const, cth = _mods()
    hass = StubHass()
    hass.data.setdefault(const.DOMAIN, {})

    async def _go():
        owner = await cth.async_setup_camera_twin_health(hass)
        assert hass.data[const.DOMAIN]["camera_twin_health"] is owner
        assert owner.map_ready is True
        cth.async_teardown_camera_twin_health(hass)
        assert "camera_twin_health" not in hass.data[const.DOMAIN]
        assert owner.torn_down is True

    asyncio.run(_go())
