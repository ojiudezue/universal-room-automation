"""EC-CFG-SELFHEAL-FALSE-CRITICAL-1 — re-read the cloud oracle before the
same-value self-heal CRITICAL.

11-07/11-08: switch.iq_battery_hacs_charge_battery_from_grid flipped to the
commanded value 0.2-0.3 s before the 'self-heal loop' page. The n>=3 branch
of WriteVerifier.schedule must now re-read the oracle and stay quiet if it
confirms the command; it must still page when the oracle stays wrong.
"""
from __future__ import annotations

import test_energy_write_verification  # noqa: F401 — side-effect bootstrap

import pytest

from test_energy_behavioral_write_verify import _Coord, _set, hass  # noqa: F401

from custom_components.universal_room_automation.domain_coordinators import (
    energy_write_verify as ewv,
)

CFG = "charge_from_grid"


@pytest.fixture(autouse=True)
def _pending_handle(monkeypatch):
    """Make async_call_later return a real cancel handle so the first
    schedule() leaves a pending check (the self-heal branch keys on it)."""
    monkeypatch.setattr(ewv, "async_call_later", lambda h, s, cb: (lambda: None))
# Independent oracle: the live entity id from the incident (not imported).
CFG_ORACLE = "switch.iq_battery_hacs_charge_battery_from_grid"


def _verifier(hass):
    coord = _Coord(hass)
    bat = coord._battery
    prev = bat._get_entity

    def _get_entity(key, default=None, *, role="read"):
        if key == "cloud_charge_from_grid_oracle":
            return CFG_ORACLE
        return prev(key, default, role=role)

    bat._get_entity = _get_entity
    v = ewv.WriteVerifier(hass, coord)
    emitted: list[tuple[str, dict]] = []
    nm: list[str] = []

    async def _emit(surface, type_str, extra):
        emitted.append((type_str, extra))

    async def _nm(surface, *, title, message, alert_type):
        nm.append(alert_type)

    v._emit_anomaly = _emit  # type: ignore[assignment]
    v._maybe_fire_nm = _nm  # type: ignore[assignment]
    return v, emitted, nm


@pytest.mark.asyncio
async def test_oracle_flips_to_commanded_on_third_tick_no_page(hass):
    v, emitted, nm = _verifier(hass)
    _set(hass, CFG_ORACLE, "off", unit=None)
    await v.schedule(CFG, True)  # arms the pending check
    await v.schedule(CFG, True)  # self-heal 1
    await v.schedule(CFG, True)  # self-heal 2
    # Cloud catches up right before the 3rd self-heal (the 11-08 shape).
    _set(hass, CFG_ORACLE, "on", unit=None)
    await v.schedule(CFG, True)  # self-heal 3 -> n>=3 branch
    assert nm == []
    assert emitted == []
    assert v._self_heal_consecutive[CFG] == 0
    v.cancel_all()


@pytest.mark.asyncio
async def test_oracle_flips_to_commanded_false_no_page(hass):
    """11-07 shape: commanded False, oracle on->off just before the page."""
    v, emitted, nm = _verifier(hass)
    _set(hass, CFG_ORACLE, "on", unit=None)
    for _ in range(3):
        await v.schedule(CFG, False)
    _set(hass, CFG_ORACLE, "off", unit=None)
    await v.schedule(CFG, False)
    assert nm == []
    assert emitted == []
    v.cancel_all()


@pytest.mark.asyncio
async def test_oracle_stays_wrong_still_pages(hass):
    v, emitted, nm = _verifier(hass)
    _set(hass, CFG_ORACLE, "off", unit=None)
    for _ in range(4):
        await v.schedule(CFG, True)
    assert nm == ["self_heal_starvation"]
    assert [t for t, _ in emitted] == ["write_verification_failed"]
    assert emitted[0][1]["reason"] == "self_heal_starvation"
    assert emitted[0][1]["consecutive_self_heals"] == 3
    assert v._self_heal_consecutive[CFG] == 3
    v.cancel_all()


@pytest.mark.asyncio
async def test_streak_restarts_after_confirmed_reread(hass):
    """After a confirmed re-read resets the streak, a later wrong oracle
    needs 3 more self-heals before paging (counter really reset)."""
    v, emitted, nm = _verifier(hass)
    _set(hass, CFG_ORACLE, "off", unit=None)
    for _ in range(3):
        await v.schedule(CFG, True)
    _set(hass, CFG_ORACLE, "on", unit=None)
    await v.schedule(CFG, True)  # n=3 confirmed -> reset to 0
    _set(hass, CFG_ORACLE, "off", unit=None)
    await v.schedule(CFG, True)  # n=1
    await v.schedule(CFG, True)  # n=2
    assert nm == []
    await v.schedule(CFG, True)  # n=3, oracle wrong -> page
    assert nm == ["self_heal_starvation"]
    v.cancel_all()
