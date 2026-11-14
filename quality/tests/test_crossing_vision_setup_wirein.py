"""VISION-CROSSING-SHADOW-1 wire-in anchor, copied from the ingress anchor
below. Original docstring:

Wire-in anchor (review C-1): the integration entry's REAL
`async_setup_entry` creates the FrigateEventIngress through
`frigate_ingress.async_setup_frigate_ingress`, BEFORE the census exists
(the census face bridge, perimeter and linker register on it).

Same pattern as test_person_coordinator_setup_wirein.py: the helper is
replaced by a recorder that raises a BaseException sentinel (setup's
`except Exception` blocks cannot swallow it), so setup stops exactly at the
ingress site. Deleting the call means the recorder is never reached -> RED.
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
    """Order-independence (copied from the person-coordinator wire-in): swap
    hand-made homeassistant stubs for the real modules and re-import the URA
    package fresh; restore exactly what was there afterwards."""
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



def test_setup_entry_creates_crossing_vision_after_linker(monkeypatch):
    """The REAL integration-entry setup reaches
    crossing_vision.async_setup_crossing_vision, after the Frigate ingress
    and the exterior linker exist. Deleting the call -> setup never reaches
    the recorder -> RED."""
    init_mod = importlib.import_module("custom_components.universal_room_automation")
    const = importlib.import_module("custom_components.universal_room_automation.const")
    cv = importlib.import_module(
        "custom_components.universal_room_automation.crossing_vision"
    )
    calls = []

    async def _recorder(hass):
        d = hass.data.get(const.DOMAIN, {})
        calls.append(("exterior_track_linker" in d, "frigate_ingress" in d))
        raise _Reached()

    monkeypatch.setattr(cv, "async_setup_crossing_vision", _recorder)
    wd = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators._loop_stall_watchdog"
    )
    monkeypatch.setattr(wd, "install", lambda _hass: None)
    hass = StubHass()
    entry = StubConfigEntry(
        "integ", const.ENTRY_TYPE_INTEGRATION,
        data={const.CONF_TRACKED_PERSONS: ["person.oji_udezue"]},
    )
    with pytest.raises(_Reached):
        asyncio.run(init_mod.async_setup_entry(hass, entry))
    assert calls == [(True, True)]


def test_unload_entry_tears_down_crossing_vision_before_ingress(monkeypatch):
    """The REAL integration-entry unload reaches
    crossing_vision.async_teardown_crossing_vision while the Frigate ingress
    is still present (teardown order). Deleting the call -> RED."""
    init_mod = importlib.import_module("custom_components.universal_room_automation")
    const = importlib.import_module("custom_components.universal_room_automation.const")
    cv = importlib.import_module(
        "custom_components.universal_room_automation.crossing_vision"
    )
    fi = importlib.import_module(
        "custom_components.universal_room_automation.frigate_ingress"
    )
    calls = []

    async def _recorder(hass):
        calls.append("frigate_ingress" in hass.data.get(const.DOMAIN, {}))
        raise _Reached()

    monkeypatch.setattr(cv, "async_teardown_crossing_vision", _recorder)
    hass = StubHass()
    entry = StubConfigEntry("integ", const.ENTRY_TYPE_INTEGRATION, data={})
    hass.data.setdefault(const.DOMAIN, {})[fi.FRIGATE_INGRESS_HASS_KEY] = object()

    async def _unload_platforms(_entry, _platforms):
        return True

    hass.config_entries.async_unload_platforms = _unload_platforms
    with pytest.raises(_Reached):
        asyncio.run(init_mod.async_unload_entry(hass, entry))
    assert calls == [True]


def test_unload_entry_awaits_real_producer_teardown(monkeypatch):
    """Review C M122 / M121 through the REAL unload path: neither
    async_unload_entry nor async_teardown_crossing_vision is stubbed. A
    published producer's own async_teardown must be awaited (it raises the
    BaseException sentinel, so reaching it stops the unload there) and its
    hass.data key popped. Not awaiting it -> the sentinel never fires ->
    RED."""
    init_mod = importlib.import_module("custom_components.universal_room_automation")
    const = importlib.import_module("custom_components.universal_room_automation.const")
    fi = importlib.import_module(
        "custom_components.universal_room_automation.frigate_ingress"
    )
    hass = StubHass()
    entry = StubConfigEntry("integ", const.ENTRY_TYPE_INTEGRATION, data={})
    seen = []

    class _Producer:
        async def async_teardown(self):
            seen.append(const.CROSSING_VISION_HASS_KEY in hass.data[const.DOMAIN])
            raise _Reached()

    hass.data.setdefault(const.DOMAIN, {})[fi.FRIGATE_INGRESS_HASS_KEY] = object()
    hass.data[const.DOMAIN][const.CROSSING_VISION_HASS_KEY] = _Producer()

    async def _unload_platforms(_entry, _platforms):
        return True

    hass.config_entries.async_unload_platforms = _unload_platforms
    with pytest.raises(_Reached):
        asyncio.run(init_mod.async_unload_entry(hass, entry))
    assert seen == [False]  # popped BEFORE the producer teardown runs
