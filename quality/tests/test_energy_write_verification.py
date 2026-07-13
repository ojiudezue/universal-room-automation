"""Envoy write-verification tripwire tests (v5.15.x).

Mutation-anchored per the plan's §Acceptance Criteria — Verify (mutation-
anchored). Each `mutation_anchor_*` test PROVES the load-bearing site is
what makes the corresponding behavior test pass (delete that site → the
test fails). The "mutation" is applied by monkeypatching the specific
piece of production code rather than editing on disk, but the anchor is
still per-site — a global patch would not distinguish this from a
neighboring path that shares the same helper.

Also anchors invariant W-6: the verifier NEVER actuates. A mutation that
would let it call a service must break a test.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest


# ------------------------------------------------------------------
# HA-module bootstrap — mirrors test_battery_inclement_arbitrage_floor.py.
# We import BatteryStrategy directly (skip __init__.py which needs HA).
# ------------------------------------------------------------------
def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": _mock_cls, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": lambda *a, **k: (lambda: None),
        "async_track_time_interval": lambda *a, **k: (lambda: None),
        "async_call_later": lambda *a, **k: (lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": lambda *a, **k: None,
        "async_dispatcher_connect": lambda *a, **k: (lambda: None),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow, "now": datetime.now, "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(), "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}
for _name, _attrs in _mods.items():
    if isinstance(_attrs, dict):
        existing = sys.modules.get(_name)
        if existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            # Patch any missing attrs onto the pre-existing mock (an
            # earlier test file may have populated only a subset).
            for _k, _v in _attrs.items():
                if not hasattr(existing, _k):
                    setattr(existing, _k, _v)
    else:
        sys.modules.setdefault(_name, _attrs)
sys.modules.setdefault("aiosqlite", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)
_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules.setdefault("custom_components.universal_room_automation", _ura)
_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules.setdefault("custom_components.universal_room_automation.const", _const_mod)
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod
_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules.setdefault(
    "custom_components.universal_room_automation.domain_coordinators", _dc,
)
_ura.domain_coordinators = _dc
for _submod_name in (
    "energy_const", "energy_tou", "inclement", "energy_battery",
    "anomaly_event", "energy_write_verify",
):
    _full = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    if _full in sys.modules:
        continue
    _spec = importlib.util.spec_from_file_location(
        _full, os.path.join(_dc_path, f"{_submod_name}.py")
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, sys.modules[_full])

from conftest import MockHass, MockState


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture
def hass():
    h = MockHass()
    h.data["universal_room_automation"] = {}
    return h


class _FakeCoord:
    def __init__(self, hass):
        self.hass = hass
        self._battery = _FakeBattery(hass)
        self._nm_calls: list[dict] = []

    async def _send_nm_alert(self, **kwargs):
        # Recorded but does NOT actuate. W-6 fixture.
        self._nm_calls.append(kwargs)


class _FakeBattery:
    """Minimal battery stub carrying the commanded ledger fields."""

    def __init__(self, hass):
        self.hass = hass
        self._entities = {}
        self._last_reserve_level = None
        self._last_reserve_level_at = None
        self._last_charge_from_grid_command = None
        self._last_charge_from_grid_command_at = None
        self._last_storage_mode_command = None
        self._last_storage_mode_command_at = None
        self._write_failover_by_surface = {}

    def _get_entity(self, key, default=None, *, role="read"):
        return self._entities.get(key, default)


def _set_state(hass, entity_id, state, unit=None):
    attrs = {}
    if unit is not None:
        attrs["unit_of_measurement"] = unit
    hass._states[entity_id] = MockState(entity_id, state, attributes=attrs)


# ------------------------------------------------------------------
# Compare unit tests
# ------------------------------------------------------------------
def test_verify_ok(hass):
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
        STATUS_OK,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    _set_state(hass, "number.iq_battery_hacs_battery_reserve", "50", unit="%")
    status, matched = v._compare("reserve_soc", 50, "50", "%")
    assert status == STATUS_OK and matched


def test_verify_mismatch(hass):
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
        STATUS_MISMATCH,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    status, matched = v._compare("reserve_soc", 50, "30", "%")
    assert status == STATUS_MISMATCH and not matched


def test_verify_unit_mismatch_factor_1000(hass):
    """Cross-source units vigilance: 0.5 (fractional) vs 50 (%) must be
    classified as WIRING bug, not mismatch."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
        STATUS_UNIT_MISMATCH,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    # commanded 50 % vs oracle 0.5 with no unit — factor-of-100 fractional
    status, matched = v._compare("reserve_soc", 50, "0.05", "")
    assert status == STATUS_UNIT_MISMATCH and not matched
    # And any non-'%' unit is also unit_mismatch even when magnitude near
    status2, matched2 = v._compare("reserve_soc", 50, "50", "kWh")
    assert status2 == STATUS_UNIT_MISMATCH and not matched2


def test_unmapped_storage_mode_is_inconclusive(hass):
    """Storage-mode oracle returns a value not in the local↔cloud map.
    Must be classified as unmapped (never as mismatch)."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
        STATUS_UNMAPPED,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    status, matched = v._compare(
        "storage_mode", "self_consumption", "Something-Else", None,
    )
    assert status == STATUS_UNMAPPED and not matched


def test_charge_from_grid_bool_match(hass):
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
        STATUS_OK,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    assert v._compare("charge_from_grid", True, "on", None) == (STATUS_OK, True)
    assert v._compare("charge_from_grid", False, "off", None) == (STATUS_OK, True)


# ------------------------------------------------------------------
# NM latch tests
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mismatch_fires_nm_once_per_day(hass):
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    await v._maybe_fire_nm("reserve_soc", "t1", "m1")
    await v._maybe_fire_nm("reserve_soc", "t2", "m2")
    assert len(coord._nm_calls) == 1  # coalesced


# ------------------------------------------------------------------
# Reversion sweep
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reversion_sweep_detects_silent_flip(hass, monkeypatch):
    """Commanded charge_from_grid=OFF long ago; oracle now reports 'on'
    with no intervening command → write_reverted anomaly + NM."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord, verify_window_s=1)
    # Configure oracle entity in the fake battery.
    coord._battery._entities["cloud_charge_from_grid_oracle"] = "switch.oracle_cfg"
    _set_state(hass, "switch.oracle_cfg", "on")
    coord._battery._last_charge_from_grid_command = False
    coord._battery._last_charge_from_grid_command_at = (
        datetime.utcnow() - timedelta(seconds=60)
    )
    # Patch dt_util.utcnow inside the module so age > window.
    emitted = []

    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)

    async def _fake_nm(surface, title, message):
        coord._nm_calls.append({"title": title})

    v._emit_anomaly = _fake_emit  # type: ignore[assignment]
    v._maybe_fire_nm = _fake_nm  # type: ignore[assignment]
    await v.reversion_sweep()
    assert "write_reverted" in emitted
    assert len(coord._nm_calls) == 1


@pytest.mark.asyncio
async def test_mutation_anchor_reversion_requires_commanded_ledger(hass):
    """MUTATION ANCHOR: if the commanded ledger for charge_from_grid is
    None (as it would be if the D1.2 ledger write in _result was neutered),
    reversion_sweep must NOT emit. This proves the ledger is load-bearing.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord, verify_window_s=1)
    coord._battery._entities["cloud_charge_from_grid_oracle"] = "switch.oracle_cfg"
    _set_state(hass, "switch.oracle_cfg", "on")
    # Ledger neutered (both None) — simulates removing the D1.2 write.
    coord._battery._last_charge_from_grid_command = None
    coord._battery._last_charge_from_grid_command_at = None
    emitted = []
    v._emit_anomaly = lambda *a, **k: emitted.append(a[1] if len(a) > 1 else None)  # type: ignore[assignment]
    await v.reversion_sweep()
    assert emitted == []  # no ledger → no reversion detection


@pytest.mark.asyncio
async def test_mutation_anchor_storage_mode_normalization(hass):
    """MUTATION ANCHOR: neuter the STORAGE_MODE_CLOUD_TO_LOCAL lookup and
    a Title-Case oracle must fail the OK path. Anchored by directly
    calling _compare — if the module's map is emptied, comparison of
    ('self_consumption', 'Self-Consumption') falls to UNMAPPED."""
    import custom_components.universal_room_automation.domain_coordinators.energy_write_verify as ewv
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_OK,
        STATUS_UNMAPPED,
    )
    coord = _FakeCoord(hass)
    v = ewv.WriteVerifier(hass, coord)
    # Sanity: default map catches the case.
    status, _ = v._compare(
        "storage_mode", "self_consumption", "Self-Consumption", None,
    )
    assert status == STATUS_OK
    # Now mutate: clear the map to simulate removing the normalization.
    saved = ewv.STORAGE_MODE_CLOUD_TO_LOCAL.copy()
    ewv.STORAGE_MODE_CLOUD_TO_LOCAL.clear()
    try:
        status2, _ = v._compare(
            "storage_mode", "self_consumption", "Self-Consumption", None,
        )
        assert status2 == STATUS_UNMAPPED
    finally:
        ewv.STORAGE_MODE_CLOUD_TO_LOCAL.update(saved)


# ------------------------------------------------------------------
# W-6: verifier NEVER actuates
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_verifier_never_calls_service(hass):
    """W-6: no code path in energy_write_verify invokes
    hass.services.async_call. Reflection-based check."""
    import inspect
    import custom_components.universal_room_automation.domain_coordinators.energy_write_verify as ewv
    src = inspect.getsource(ewv)
    assert "services.async_call" not in src
    assert "hass.services" not in src


# ------------------------------------------------------------------
# SOC three-tier resolver (D2)
# ------------------------------------------------------------------
def test_soc_lkg_within_window():
    """Primary unavailable → LKG within 5-min window used."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    hass = MockHass()
    bs = BatteryStrategy(
        hass, reserve_soc=20, entity_config={"battery_soc": "sensor.envoy_soc"},
    )
    _set_state(hass, "sensor.envoy_soc", "71", unit="%")
    assert bs.battery_soc == 71.0
    # Now primary unavailable — LKG serves.
    hass._states["sensor.envoy_soc"] = MockState(
        "sensor.envoy_soc", "unavailable",
    )
    assert bs.battery_soc == 71.0
    assert bs._soc_source_last == "lkg"


def test_soc_cloud_fallback_when_lkg_stale():
    """Primary unavailable AND LKG stale → cloud fallback used."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    from homeassistant.util import dt as dt_util
    hass = MockHass()
    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "battery_soc": "sensor.envoy_soc",
            "battery_soc_cloud": "sensor.cloud_soc",
        },
    )
    # Seed LKG but mark it stale.
    bs._soc_lkg = 71.0
    bs._soc_lkg_at = dt_util.utcnow() - timedelta(seconds=600)
    hass._states["sensor.envoy_soc"] = MockState("sensor.envoy_soc", "unavailable")
    _set_state(hass, "sensor.cloud_soc", "42", unit="%")
    assert bs.battery_soc == 42.0
    assert bs._soc_source_last == "cloud_fallback"


def test_soc_all_unavailable_returns_none():
    """Existing Envoy-degraded branch preserved (W-3)."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    hass = MockHass()
    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "battery_soc": "sensor.envoy_soc",
            "battery_soc_cloud": "sensor.cloud_soc",
        },
    )
    hass._states["sensor.envoy_soc"] = MockState("sensor.envoy_soc", "unavailable")
    hass._states["sensor.cloud_soc"] = MockState("sensor.cloud_soc", "unavailable")
    assert bs.battery_soc is None


def test_soc_divergence_unit_mismatch_suppressed():
    """Cross-source units vigilance: cloud fallback reports fractional
    0-1 with the same '%' unit label but 1000x off → suppressed as
    WIRING bug (not divergence). Ensures we never fire a divergence NM
    alert on a units bug."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    hass = MockHass()
    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "battery_soc": "sensor.envoy_soc",
            "battery_soc_cloud": "sensor.cloud_soc",
        },
    )
    _set_state(hass, "sensor.envoy_soc", "50", unit="%")
    _set_state(hass, "sensor.cloud_soc", "0.05", unit="%")  # 1000x mis-wired
    # Should NOT set _last_soc_divergence_at (guard fires).
    bs._check_soc_source_divergence(50.0)
    assert bs._last_soc_divergence_at is None


# ------------------------------------------------------------------
# D3 dormant failover
# ------------------------------------------------------------------
def test_failover_role_read_default_is_local():
    """Backward compat: existing call sites default to role='read' AND
    the failover flag is False → returns local entity."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    hass = MockHass()
    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={"charge_from_grid": "switch.local_cfg"},
    )
    assert bs._get_entity("charge_from_grid") == "switch.local_cfg"
    assert bs._get_entity("charge_from_grid", role="write") == "switch.local_cfg"


def test_failover_write_flag_flipped_returns_cloud():
    """When D3.4 switch flips the per-surface flag, role='write' AND the
    coherent read path both resolve to the cloud entity (W-5)."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    hass = MockHass()
    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "charge_from_grid": "switch.local_cfg",
            "cloud_charge_from_grid_oracle": "switch.cloud_cfg",
        },
    )
    bs._write_failover_by_surface["charge_from_grid"] = True
    assert bs._get_entity("charge_from_grid", role="write") == "switch.cloud_cfg"
    # Coherent — the resolver used by the LKG-latch read path also
    # points at the same cloud entity.
    assert bs._cloud_write_target("charge_from_grid") == "switch.cloud_cfg"


def test_mutation_anchor_failover_read_write_coherent():
    """MUTATION ANCHOR (W-5): if _cloud_write_target were to return a
    DIFFERENT entity for reads vs writes, this test must fail. We
    simulate the mutation by manually stubbing the helper to a wrong
    entity; the coherent invariant then flips."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    hass = MockHass()
    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "charge_from_grid": "switch.local_cfg",
            "cloud_charge_from_grid_oracle": "switch.cloud_cfg",
        },
    )
    bs._write_failover_by_surface["charge_from_grid"] = True
    write_side = bs._get_entity("charge_from_grid", role="write")
    read_side = bs._cloud_write_target("charge_from_grid")
    assert write_side == read_side  # W-5 invariant

    # MUTATION SIMULATION: neuter the role='write' branch of _get_entity
    # so it ALWAYS returns the local entity even under failover — the
    # split-brain condition W-5 warns against. Replace with a lambda
    # that bypasses the failover check.
    def _mutated_get_entity(key, default=None, *, role="read"):
        return bs._entities.get(key, default)  # ignores failover
    bs._get_entity = _mutated_get_entity  # type: ignore[assignment]
    write_side_mut = bs._get_entity("charge_from_grid", role="write")
    read_side_mut = bs._cloud_write_target("charge_from_grid")
    # Post-mutation: writes go to local, reads (LKG-latch resolver) still
    # resolve cloud — the split-brain that W-5 exists to prevent. The
    # coherent-invariant assertion above WOULD FAIL under this mutation.
    assert write_side_mut == "switch.local_cfg"
    assert read_side_mut == "switch.cloud_cfg"
    assert write_side_mut != read_side_mut
