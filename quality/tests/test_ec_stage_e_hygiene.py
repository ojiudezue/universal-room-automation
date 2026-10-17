"""EC storm Stage E E3 — fetch timeouts (parent §16 B-LOW-5).

Drives the ENCLOSING refresh methods (`_refresh_all_providers`,
`_refresh_hourly`) with a provider whose `weather.get_forecasts` hangs: the
pass must finish within the bound and release `_refresh_lock`.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from test_ec_stage_c_hourly_outlook import (  # noqa: F401 — fixtures
    OWM,
    T0,
    clock,
    wm_mod,
)
from conftest import MockHass, MockState
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_ENERGY_WEATHER_ENTITY,
)


@pytest.mark.parametrize("kind", ["daily", "hourly"])
def test_fetch_timeout_releases_refresh_lock(wm_mod, clock, monkeypatch, kind):
    monkeypatch.setattr(wm_mod, "FORECAST_FETCH_TIMEOUT_S", 0.05)
    clock.t = T0
    hass = MockHass()
    st = MockState(OWM, "snowy", {"temperature_unit": "°F"})
    st.last_changed = st.last_updated = T0
    hass._states[OWM] = st
    seen = []

    async def _hang(domain, svc, data, blocking=False, return_response=False):
        seen.append(data.get("type"))
        await asyncio.sleep(30)
        return {}
    hass.services = SimpleNamespace(async_call=_hang)
    m = wm_mod.WeatherProviderManager(hass, {CONF_ENERGY_WEATHER_ENTITY: OWM})
    m.async_write_ha_state = lambda: None
    run = m._refresh_hourly if kind == "hourly" else m._refresh_all_providers
    loop = asyncio.new_event_loop()
    try:
        t = time.monotonic()
        loop.run_until_complete(asyncio.wait_for(run(), 5))
        assert time.monotonic() - t < 2.0
    finally:
        loop.close()
    assert kind in seen  # the hung call was actually made
    assert not m._refresh_lock.locked()
    if kind == "hourly":
        assert m.hourly_providers_ok == 0
