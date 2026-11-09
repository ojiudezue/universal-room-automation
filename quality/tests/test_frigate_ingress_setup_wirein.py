"""Wire-in anchor (review C-1): the integration entry's REAL
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


def test_setup_entry_creates_frigate_ingress_before_census(monkeypatch):
    init_mod = importlib.import_module("custom_components.universal_room_automation")
    const = importlib.import_module("custom_components.universal_room_automation.const")
    fi = importlib.import_module(
        "custom_components.universal_room_automation.frigate_ingress"
    )
    calls = []

    async def _recorder(hass):
        # Ordering: the census (first ingress consumer) does not exist yet.
        calls.append(("census" in hass.data.get(const.DOMAIN, {}), hass))
        raise _Reached()

    monkeypatch.setattr(fi, "async_setup_frigate_ingress", _recorder)
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
    assert calls == [(False, hass)]
