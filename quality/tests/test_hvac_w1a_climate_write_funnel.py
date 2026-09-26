"""HVAC-W1-A Stage A — behavioural tests for the write governance funnel.

Covers D1 (`emit_set_hvac_mode`), D2 (row-schedule helper, C2 fields,
excursion_id forwarding, wire-raise semantics, dedup-off, ts_issued),
D4 (resume-then-pin site naming).

The tests own their clock (monkeypatch ``dt_util.utcnow`` where read).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


ROOT = Path(__file__).resolve().parents[2]
URA = ROOT / "custom_components" / "universal_room_automation"


def _stub(name, **attrs):
    if name in sys.modules and hasattr(sys.modules[name], "__file__"):
        return sys.modules[name]
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _load_setpoint():
    """Load domain_coordinators.hvac_setpoint as a package member so
    its relative imports (``.hvac_const``, ``..const``) resolve."""
    _stub("homeassistant")
    _stub("homeassistant.core", HomeAssistant=type("H", (), {}))
    _stub("homeassistant.util")
    _stub(
        "homeassistant.util.dt",
        utcnow=lambda: datetime(2026, 9, 26, 0, 0, 0, tzinfo=timezone.utc),
    )
    # Register package skeletons so relative imports work.
    if "custom_components" not in sys.modules:
        cc = types.ModuleType("custom_components")
        cc.__path__ = [str(URA.parent)]
        sys.modules["custom_components"] = cc
    if "custom_components.universal_room_automation" not in sys.modules:
        p = types.ModuleType("custom_components.universal_room_automation")
        p.__path__ = [str(URA)]
        sys.modules["custom_components.universal_room_automation"] = p
    if "custom_components.universal_room_automation.const" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "custom_components.universal_room_automation.const",
            str(URA / "const.py"),
        )
        m = importlib.util.module_from_spec(spec)
        sys.modules["custom_components.universal_room_automation.const"] = m
        spec.loader.exec_module(m)
    if (
        "custom_components.universal_room_automation.domain_coordinators"
        not in sys.modules
    ):
        dc = types.ModuleType(
            "custom_components.universal_room_automation.domain_coordinators"
        )
        dc.__path__ = [str(URA / "domain_coordinators")]
        sys.modules[
            "custom_components.universal_room_automation.domain_coordinators"
        ] = dc
    for name, fname in [
        (
            "custom_components.universal_room_automation.domain_coordinators.hvac_const",
            "domain_coordinators/hvac_const.py",
        ),
        (
            "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
            "domain_coordinators/hvac_setpoint.py",
        ),
    ]:
        if name in sys.modules and getattr(sys.modules[name], "__file__", None):
            continue
        spec = importlib.util.spec_from_file_location(name, str(URA / fname))
        m = importlib.util.module_from_spec(spec)
        sys.modules[name] = m
        spec.loader.exec_module(m)
    return sys.modules[
        "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint"
    ]


hvac_setpoint = _load_setpoint()
DOMAIN = "universal_room_automation"


# --------------------------------------------------------------------------
# Test doubles.
# --------------------------------------------------------------------------


class _FakeState:
    def __init__(self, state="heat_cool", **attrs):
        self.state = state
        self.attributes = attrs


class _FakeStates:
    def __init__(self, mapping):
        self._m = mapping

    def get(self, eid):
        return self._m.get(eid)


class _FakeDB:
    def __init__(self):
        self.rows = []

    async def log_activity(self, **kw):
        # Immediate synchronous capture into an in-memory list; no dedup.
        self.rows.append(kw)


class _FakeHass:
    def __init__(self, states_map=None, db=None, raise_on_call=None):
        self.data = {DOMAIN: {}}
        if db is not None:
            self.data[DOMAIN]["database"] = db
        self.states = _FakeStates(states_map or {})
        self._call_log = []
        self._raise = raise_on_call
        self._tasks = []
        self.services = types.SimpleNamespace(
            async_call=self._async_call,
        )

    async def _async_call(self, domain, service, data, blocking=False):
        self._call_log.append((domain, service, dict(data), blocking))
        if self._raise is not None:
            raise self._raise

    def async_create_task(self, coro):
        # Run it eagerly so the row lands during the test.
        t = asyncio.get_event_loop().create_task(coro)
        self._tasks.append(t)
        return t


async def _drain(hass):
    for t in list(hass._tasks):
        await t
    hass._tasks.clear()


# --------------------------------------------------------------------------
# D1 tests.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_set_hvac_mode_happy_path():
    db = _FakeDB()
    hass = _FakeHass(
        states_map={
            "climate.z1": _FakeState(
                state="heat_cool",
                preset_mode="home",
                hold_activity="home",
                target_temp_low=70,
                target_temp_high=76,
            )
        },
        db=db,
    )
    ok = await hvac_setpoint.emit_set_hvac_mode(
        hass, "climate.z1", "off",
        site="B2_egress_pause", zone_id="zone_1",
        reason="egress_pause", blocking=True,
    )
    await _drain(hass)
    assert ok is True
    assert hass._call_log == [
        ("climate", "set_hvac_mode",
         {"entity_id": "climate.z1", "hvac_mode": "off"}, True),
    ]
    assert len(db.rows) == 1
    row = db.rows[0]
    assert row["action"] == "climate_write"
    assert row["importance"] == "notable"
    assert row["zone"] == "zone_1"
    d = json.loads(row["details_json"])
    assert d["verb"] == "set_hvac_mode"
    assert d["site"] == "B2_egress_pause"
    assert d["reason"] == "egress_pause"
    assert d["blocking"] is True
    assert d["wire_ok"] is True
    assert d["exc"] is None
    assert d["excursion_id"] is None
    assert d["values_before"]["preset_mode"] == "home"
    assert d["values_before"]["hold_activity"] == "home"
    assert d["values_after"] == {
        "entity_id": "climate.z1", "hvac_mode": "off",
    }
    assert d["ts_issued"] <= d["ts_returned"]


@pytest.mark.asyncio
async def test_emit_set_hvac_mode_wire_raises_propagates_and_logs_row():
    db = _FakeDB()
    boom = RuntimeError("cloud 504")
    hass = _FakeHass(
        states_map={
            "climate.z1": _FakeState(preset_mode="home", hold_activity="home"),
        },
        db=db,
        raise_on_call=boom,
    )
    with pytest.raises(RuntimeError, match="cloud 504"):
        await hvac_setpoint.emit_set_hvac_mode(
            hass, "climate.z1", "off",
            site="B5_ac_reset_off", zone_id="zone_1",
            reason="ac_reset_off", blocking=True,
        )
    await _drain(hass)
    assert len(db.rows) == 1
    d = json.loads(db.rows[0]["details_json"])
    assert d["wire_ok"] is False
    assert d["exc"] == "RuntimeError"


def test_emit_set_hvac_mode_missing_kwargs_typeerror():
    """F3 + F10: site/zone_id/reason/blocking are REQUIRED keyword-only."""
    hass = _FakeHass()
    with pytest.raises(TypeError):
        # No site/zone_id/reason/blocking → TypeError at call time.
        asyncio.get_event_loop().run_until_complete(
            hvac_setpoint.emit_set_hvac_mode(hass, "climate.z1", "off")
        )


@pytest.mark.asyncio
async def test_emit_set_hvac_mode_never_awaits_log(monkeypatch):
    """F2: row-schedule is fire-and-forget. Mutating async_create_task
    to raise proves it is the ONLY logging path (any `await` would
    surface the raise)."""
    db = _FakeDB()
    hass = _FakeHass(
        states_map={"climate.z1": _FakeState(preset_mode="home")},
        db=db,
    )
    # If the funnel awaited the row, this would poison the wire path.
    hass.async_create_task = MagicMock(side_effect=lambda c: c.close() or MagicMock())
    ok = await hvac_setpoint.emit_set_hvac_mode(
        hass, "climate.z1", "heat_cool",
        site="B1", zone_id="zone_1", reason="drift", blocking=True,
    )
    assert ok is True
    hass.async_create_task.assert_called_once()


# --------------------------------------------------------------------------
# D2 tests (row helper).
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_row_shape_has_all_required_keys():
    db = _FakeDB()
    hass = _FakeHass(
        states_map={"climate.z1": _FakeState(preset_mode="home", hold_activity="home")},
        db=db,
    )
    await hvac_setpoint.emit_set_temperature(
        hass, "climate.z1",
        target_temp_low=70, target_temp_high=76,
        site="S5_nudge_start", zone_id="zone_1",
        reason="soft_nudge_start", blocking=False,
    )
    await _drain(hass)
    d = json.loads(db.rows[0]["details_json"])
    required = {
        "verb", "site", "reason", "blocking", "wire_ok", "exc",
        "excursion_id", "values_before", "values_after",
        "ts_issued", "ts_returned",
    }
    assert required.issubset(d.keys())
    for k in ("preset_mode", "hold_activity", "target_low",
              "target_high", "hvac_mode"):
        assert k in d["values_before"]


@pytest.mark.asyncio
async def test_c2_fields_read_synchronously_before_wire():
    """F6: values_before snapshot is captured BEFORE the await, so a
    concurrent state mutation after the call is invisible."""
    db = _FakeDB()
    state = _FakeState(preset_mode="home", hold_activity="home")
    hass = _FakeHass(states_map={"climate.z1": state}, db=db)

    # Mutate the state inside the wire call to simulate a late echo.
    orig_call = hass.services.async_call

    async def _mutating_call(domain, service, data, blocking=False):
        state.attributes["preset_mode"] = "manual"
        state.attributes["hold_activity"] = "manual"
        await orig_call(domain, service, data, blocking=blocking)

    hass.services.async_call = _mutating_call
    await hvac_setpoint.emit_set_temperature(
        hass, "climate.z1",
        target_temp_low=70, target_temp_high=76,
        site="S5_nudge_start", zone_id="zone_1",
        reason="nudge", blocking=False,
    )
    await _drain(hass)
    d = json.loads(db.rows[0]["details_json"])
    assert d["values_before"]["preset_mode"] == "home"
    assert d["values_before"]["hold_activity"] == "home"


@pytest.mark.asyncio
async def test_dedup_off_two_identical_1s_apart():
    """F4: bypassing ActivityLogger → two identical writes are TWO rows."""
    db = _FakeDB()
    hass = _FakeHass(
        states_map={"climate.z1": _FakeState(preset_mode="home")},
        db=db,
    )
    for _ in range(2):
        await hvac_setpoint.emit_set_hvac_mode(
            hass, "climate.z1", "off",
            site="B5_ac_reset_off", zone_id="zone_1",
            reason="ac_reset_off", blocking=True,
        )
    await _drain(hass)
    assert len(db.rows) == 2


@pytest.mark.asyncio
async def test_row_helper_never_raises_when_hass_data_missing():
    """F14: absent hass.data[DOMAIN]['database'] → wire still succeeds,
    no row, no raise."""
    hass = _FakeHass(
        states_map={"climate.z1": _FakeState(preset_mode="home")},
        db=None,  # deliberately missing
    )
    ok = await hvac_setpoint.emit_set_hvac_mode(
        hass, "climate.z1", "off",
        site="X", zone_id="zone_1", reason="r", blocking=True,
    )
    await _drain(hass)
    assert ok is True
    assert hass._call_log  # wire still fired


@pytest.mark.asyncio
async def test_excursion_id_forwarded_from_borrow_site():
    db = _FakeDB()
    hass = _FakeHass(
        states_map={"climate.z1": _FakeState(preset_mode="home")},
        db=db,
    )
    await hvac_setpoint.emit_set_temperature(
        hass, "climate.z1",
        target_temp_low=70, target_temp_high=76,
        site="S5_nudge_start", zone_id="zone_1", reason="nudge",
        blocking=False, excursion_id="nudge:zone_1:abc",
    )
    await hvac_setpoint.emit_set_hvac_mode(
        hass, "climate.z1", "heat_cool",
        site="B1", zone_id="zone_1", reason="drift", blocking=True,
    )
    await _drain(hass)
    d0 = json.loads(db.rows[0]["details_json"])
    d1 = json.loads(db.rows[1]["details_json"])
    assert d0["excursion_id"] == "nudge:zone_1:abc"
    assert d1["excursion_id"] is None


# --------------------------------------------------------------------------
# D4 tests (resume-then-pin site naming).
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_then_pin_schedules_two_rows_in_order():
    db = _FakeDB()
    # Entity advertises `resume` capability + is on an anonymous manual hold.
    state = _FakeState(
        preset_mode="manual",
        preset_modes=("home", "sleep", "manual", "resume"),
        hold_activity="manual",
    )
    hass = _FakeHass(states_map={"climate.z1": state}, db=db)
    await hvac_setpoint.emit_set_preset_mode(
        hass, "climate.z1", "home",
        site="S1_reason_ladder", zone_id="zone_1",
        reason="occupancy_flip", blocking=False,
    )
    await _drain(hass)
    # Two rows: resume (blocking=True forced), then pin.
    sites = [json.loads(r["details_json"])["site"] for r in db.rows]
    assert sites == ["S1_reason_ladder+resume", "S1_reason_ladder+pin"]


@pytest.mark.asyncio
async def test_no_resume_route_uses_bare_site_name():
    db = _FakeDB()
    # No anonymous hold → direct pin, no resume, site stays bare.
    state = _FakeState(preset_mode="home", hold_activity="home")
    hass = _FakeHass(states_map={"climate.z1": state}, db=db)
    await hvac_setpoint.emit_set_preset_mode(
        hass, "climate.z1", "sleep",
        site="S1_reason_ladder", zone_id="zone_1",
        reason="house_state", blocking=False,
    )
    await _drain(hass)
    sites = [json.loads(r["details_json"])["site"] for r in db.rows]
    assert sites == ["S1_reason_ladder"]
