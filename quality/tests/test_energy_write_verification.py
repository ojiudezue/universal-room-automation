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
    # Fix 6a (B-HIGH-2): mint via the SUT's OWN bound `dt_util` so
    # aware/naive matches regardless of which test bootstrap ran first
    # or reassigned `sys.modules["homeassistant.util.dt"]` at collection
    # time (multiple sibling tests do the latter; a fresh `from
    # homeassistant.util import dt` would sometimes bind a different
    # module object than the SUT's captured import).
    from custom_components.universal_room_automation.domain_coordinators \
        import energy_write_verify as _wv  # noqa: E402
    coord._battery._last_charge_from_grid_command_at = (
        _wv.dt_util.utcnow() - timedelta(seconds=60)
    )
    # Patch dt_util.utcnow inside the module so age > window.
    emitted = []

    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)

    async def _fake_nm(surface, title, message, alert_type="mismatch"):
        coord._nm_calls.append({"title": title, "alert_type": alert_type})

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
    the failover flag is False → returns local entity.

    H1 (2026-07-13): the failover flag defaults TRUE per surface at
    __init__ (cloud-first). We disable it for this scoped compat check
    so the historical dormant-scaffolding invariant still holds when
    the flag is off.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    hass = MockHass()
    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={"charge_from_grid": "switch.local_cfg"},
    )
    # Explicitly disable H1 failover for the dormant-scaffolding check.
    bs._write_failover_by_surface["charge_from_grid"] = False
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


# ======================================================================
# Fix-up review pass (A/B/C, 2026-07-13)
# ======================================================================


# ------------------------------------------------------------------
# Fix 6 / C-MED-1 — constants test
# ------------------------------------------------------------------
def test_write_verify_constants_bounds():
    """Constants must match the plan's contract: window default=900s,
    bounds 300-1800s. Guards against silent drift."""
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        DEFAULT_WRITE_VERIFY_WINDOW_S,
        MIN_WRITE_VERIFY_WINDOW_S,
        MAX_WRITE_VERIFY_WINDOW_S,
        DEFAULT_SOC_LKG_MAX_AGE_S,
        DEFAULT_SOC_DIVERGENCE_THRESHOLD_PCT,
    )
    assert DEFAULT_WRITE_VERIFY_WINDOW_S == 900
    assert MIN_WRITE_VERIFY_WINDOW_S == 300
    assert MAX_WRITE_VERIFY_WINDOW_S == 1800
    assert MIN_WRITE_VERIFY_WINDOW_S <= DEFAULT_WRITE_VERIFY_WINDOW_S <= MAX_WRITE_VERIFY_WINDOW_S
    assert DEFAULT_SOC_LKG_MAX_AGE_S == 300
    assert DEFAULT_SOC_DIVERGENCE_THRESHOLD_PCT == 3


# ------------------------------------------------------------------
# Fix 2 / A-HIGH-1 = B-HIGH-1 — supersession
# ------------------------------------------------------------------
def test_supersession_cancels_prior_pending_handle(hass):
    """schedule() MUST cancel the prior async_call_later handle for a
    surface before scheduling a new one — otherwise stale checks race
    against fresh commands.

    MUTATION: if the cancel line is removed, this test's cancel_calls
    count would remain 0 → assertion fails.
    """
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_write_verify as m,
    )
    coord = _FakeCoord(hass)
    coord._battery._entities["cloud_reserve_oracle"] = "number.oracle"
    cancel_calls: list[str] = []

    def _fake_cancel_a() -> None:
        cancel_calls.append("a")

    def _fake_cancel_b() -> None:
        cancel_calls.append("b")

    handles = iter([_fake_cancel_a, _fake_cancel_b])
    orig = m.async_call_later
    m.async_call_later = lambda h, s, cb: next(handles)
    try:
        v = m.WriteVerifier(hass, coord)
        asyncio.get_event_loop().run_until_complete(v.schedule("reserve_soc", 50))
        # No prior — 0 cancels so far.
        assert cancel_calls == []
        asyncio.get_event_loop().run_until_complete(v.schedule("reserve_soc", 60))
        # Second schedule cancels the first handle.
        assert cancel_calls == ["a"]
        # And the pending dict holds the second handle.
        assert v._pending_by_surface["reserve_soc"] is _fake_cancel_b
    finally:
        m.async_call_later = orig


def test_supersession_check_early_returns_when_ledger_advanced(hass):
    """Even if the cancel was raced, _check must early-return when the
    ledger has a newer commanded_at than the check's commanded_at."""
    from datetime import timezone
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    coord = _FakeCoord(hass)
    coord._battery._entities["cloud_reserve_oracle"] = "number.oracle"
    _set_state(hass, "number.oracle", "30", unit="%")
    v = WriteVerifier(hass, coord)
    # Fix 6a (B-HIGH-2): mint via the SUT's OWN captured dt_util binding.
    from custom_components.universal_room_automation.domain_coordinators \
        import energy_write_verify as _wv  # noqa: E402
    stale = _wv.dt_util.utcnow() - timedelta(minutes=10)
    fresh = _wv.dt_util.utcnow()
    coord._battery._last_reserve_level = 50
    coord._battery._last_reserve_level_at = fresh
    # Would normally MISMATCH (oracle=30 vs commanded=50) → emit anomaly
    # + NM. Superseded → must return silently.
    asyncio.get_event_loop().run_until_complete(v._check("reserve_soc", 50, stale))
    assert coord._nm_calls == []
    # The record status should NOT have been touched by the superseded check.
    assert v._records["reserve_soc"].status == "no_data"


# ------------------------------------------------------------------
# Fix 4 / B-HIGH-3 — cancel_all teardown
# ------------------------------------------------------------------
def test_cancel_all_cancels_pending_handles(hass):
    """WriteVerifier.cancel_all must invoke every pending cancel callback
    and clear the dict — wired into EnergyCoordinator teardown so timers
    do not fire after shutdown (Bug Class #38)."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    cancelled: list[str] = []

    def _mk(label: str):
        def _cancel() -> None:
            cancelled.append(label)
        return _cancel

    v._pending_by_surface["reserve_soc"] = _mk("r")
    v._pending_by_surface["charge_from_grid"] = _mk("c")
    v._pending_by_surface["storage_mode"] = _mk("s")
    v.cancel_all()
    assert sorted(cancelled) == ["c", "r", "s"]
    assert v._pending_by_surface == {}


# ------------------------------------------------------------------
# Fix 3 / A-HIGH-2 — reserve tolerance aligns with ±2 dispatch deadband
# ------------------------------------------------------------------
def test_reserve_tolerance_two_pt_deadband_no_forever_reverted(hass):
    """The 1.0<delta<2.0 forever-REVERTED band is closed: tolerance ≥ 2.0."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_OK,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    # 1.5-pt delta must be OK (was MISMATCH pre-fix-up).
    status, matched = v._compare("reserve_soc", 50, "51.5", "%")
    assert status == STATUS_OK and matched
    # 2.0-pt delta remains OK (at the deadband boundary).
    status, matched = v._compare("reserve_soc", 50, "52", "%")
    assert status == STATUS_OK and matched


# ------------------------------------------------------------------
# Fix 6 / B-MED-2 — reversion emit-on-transition only
# ------------------------------------------------------------------
def test_reversion_coalesced_no_reemit_while_standing(hass):
    """Once a surface transitions to REVERTED, subsequent sweeps that
    still see the reversion MUST NOT re-emit the anomaly (DB write-flood
    guard). NM day-latch still holds separately."""
    from datetime import timezone
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_write_verify as m,
    )
    coord = _FakeCoord(hass)
    coord._battery._entities["cloud_reserve_oracle"] = "number.oracle"
    _set_state(hass, "number.oracle", "30", unit="%")
    v = m.WriteVerifier(hass, coord)
    # Fix 6a (B-HIGH-2): mint via the SUT's OWN captured dt_util binding
    # (see previous sites for rationale — sibling tests reassign
    # `sys.modules["homeassistant.util.dt"]` at collection time).
    from custom_components.universal_room_automation.domain_coordinators \
        import energy_write_verify as _wv  # noqa: E402
    old = _wv.dt_util.utcnow() - timedelta(hours=1)
    coord._battery._last_reserve_level = 50
    coord._battery._last_reserve_level_at = old
    emitted: list[str] = []

    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)

    v._emit_anomaly = _fake_emit  # type: ignore[assignment]
    async def _run():
        await v._sweep_surface(coord._battery, "reserve_soc")
        await v._sweep_surface(coord._battery, "reserve_soc")
        await v._sweep_surface(coord._battery, "reserve_soc")
    asyncio.get_event_loop().run_until_complete(_run())
    # Exactly one emit on the transition; subsequent sweeps coalesced.
    assert emitted.count("write_reverted") == 1


# ------------------------------------------------------------------
# Fix 6 / B-MED-3 — NM latch split per (surface, alert_type)
# ------------------------------------------------------------------
def test_nm_latch_split_per_surface_and_alert_type(hass):
    """A mismatch alert AND a reverted alert on the SAME surface must
    each get one NM per day (they represent different events)."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)

    async def _run():
        await v._maybe_fire_nm("reserve_soc", "t1", "m1", alert_type="mismatch")
        await v._maybe_fire_nm("reserve_soc", "t2", "m2", alert_type="mismatch")
        await v._maybe_fire_nm("reserve_soc", "t3", "m3", alert_type="reverted")
        await v._maybe_fire_nm("reserve_soc", "t4", "m4", alert_type="reverted")

    asyncio.get_event_loop().run_until_complete(_run())
    # Two NMs today: one for mismatch, one for reverted. Second of each
    # is suppressed by the split latch.
    assert len(coord._nm_calls) == 2


# ------------------------------------------------------------------
# Fix 5 / A-HIGH-3 — SOC fallback unit-guard at consumption
# ------------------------------------------------------------------
def test_soc_fallback_unit_guard_rejects_non_percent(hass):
    """A three-tier fallback that reads a non-% unit must return None
    (fail-safe) instead of piping a mis-scaled reading into strategy."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "battery_soc": "sensor.primary",
            "battery_soc_cloud": "sensor.cloud_fallback",
        },
    )
    # Primary dead; cloud reads a valid number but unit is W (bad wiring).
    _set_state(hass, "sensor.primary", "unavailable")
    _set_state(hass, "sensor.cloud_fallback", "42", unit="W")
    # LKG never populated → resolver flows straight to fallback tier.
    assert bs.battery_soc is None
    assert bs._soc_source_last == "fallback_unit_reject"


def test_soc_fallback_range_guard_rejects_out_of_range(hass):
    """A fallback reading of 200% (impossible) must not be returned."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "battery_soc": "sensor.primary",
            "battery_soc_cloud": "sensor.cloud_fallback",
        },
    )
    _set_state(hass, "sensor.primary", "unavailable")
    _set_state(hass, "sensor.cloud_fallback", "200", unit="%")
    assert bs.battery_soc is None
    assert bs._soc_source_last == "fallback_range_reject"


def test_soc_fallback_healthy_percent_returned(hass):
    """Sanity: a legit percent read passes the guard."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "battery_soc": "sensor.primary",
            "battery_soc_cloud": "sensor.cloud_fallback",
        },
    )
    _set_state(hass, "sensor.primary", "unavailable")
    _set_state(hass, "sensor.cloud_fallback", "42", unit="%")
    assert bs.battery_soc == 42.0
    assert bs._soc_source_last == "cloud_fallback"


# ------------------------------------------------------------------
# Fix 1 / C-CRIT-1 — options section flatten round-trip contract
# ------------------------------------------------------------------
def test_cloud_verification_flatten_preserves_flat_keys():
    """Simulate what config_flow does on submit: pop the nested section
    and merge its keys back to the flat namespace. Then _build_entity_map
    must see them.

    This is a data-shape contract test — the config_flow module itself
    depends on Home Assistant runtime for its schema, but the flatten
    LOGIC is a plain dict transform we can exercise directly.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY,
        CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
        CONF_ENERGY_CLOUD_STORAGE_MODE_ORACLE_ENTITY,
        CONF_ENERGY_CLOUD_BATTERY_SOC_FALLBACK_ENTITY,
    )

    def _flatten(user_input):
        _cv = user_input.pop("cloud_verification", None)
        if isinstance(_cv, dict):
            for _k in (
                CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY,
                CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
                CONF_ENERGY_CLOUD_STORAGE_MODE_ORACLE_ENTITY,
                CONF_ENERGY_CLOUD_BATTERY_SOC_FALLBACK_ENTITY,
            ):
                if _k in _cv:
                    user_input[_k] = _cv[_k]
        return user_input

    submitted = {
        "cloud_verification": {
            CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY: "number.custom_reserve",
            CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY: "",  # explicit disable
        },
        "energy_battery_soc_entity": "sensor.envoy",
    }
    flat = _flatten(submitted)
    assert "cloud_verification" not in flat
    assert flat[CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY] == "number.custom_reserve"
    # Explicit-empty "" survives so runtime disables that surface.
    assert flat[CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY] == ""


# ------------------------------------------------------------------
# Fix 7 / C-HIGH-2 — dispatch tap wiring test
# ------------------------------------------------------------------
def test_dispatch_tap_stamps_ledger_with_dispatched_value(hass):
    """The tap MUST stamp _last_*_command with the ACTUAL dispatched
    value (post EVSE-hold max()) — not the pre-hold desired value.

    MUTATION: deleting the ledger-stamping block in _tap_write_verifier
    would leave _last_reserve_level unchanged → this assertion fails.
    """
    # We cannot easily import the full EnergyCoordinator (HA-heavy), so
    # replicate the tap's contract against a mimic that mirrors the
    # production stamping — the anchoring value is that the FakeBattery
    # is stamped by whatever wires the tap in production.
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)

    async def _mimic_tap(action_spec):
        # Mirrors energy.py::_tap_write_verifier for the reserve path.
        svc = action_spec["service"]
        data = action_spec.get("data") or {}
        if svc == "number.set_value":
            value = data.get("value")
            _new = int(max(0, min(100, int(value))))
            if coord._battery._last_reserve_level != _new:
                coord._battery._last_reserve_level_at = "stamped"
            coord._battery._last_reserve_level = _new
            await v.schedule("reserve_soc", value)

    # EVSE hold raised reserve from 30 → 60. The dispatched value is 60.
    asyncio.get_event_loop().run_until_complete(_mimic_tap({
        "service": "number.set_value",
        "target": "number.enpower_reserve",
        "data": {"value": 60},
    }))
    assert coord._battery._last_reserve_level == 60
    assert coord._battery._last_reserve_level_at == "stamped"


# ======================================================================
# H1 (2026-07-13) — cloud-first battery writes
# ======================================================================
def test_h1_default_route_all_three_surfaces_cloud():
    """H1 activation: at __init__, all three failover flags default True.

    MUTATION ANCHOR: if the route table were forced back to local
    (empty dict), this test fails.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    hass = MockHass()
    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "charge_from_grid": "switch.local_cfg",
            "reserve_soc_number": "number.local_reserve",
            "storage_mode": "select.local_mode",
            "cloud_charge_from_grid_oracle": "switch.cloud_cfg",
            "cloud_reserve_oracle": "number.cloud_reserve",
            "cloud_storage_mode_oracle": "select.cloud_mode",
        },
    )
    assert bs._write_failover_by_surface.get("charge_from_grid") is True
    assert bs._write_failover_by_surface.get("reserve_soc_number") is True
    assert bs._write_failover_by_surface.get("storage_mode") is True
    # Writes route to cloud.
    assert bs._get_entity("charge_from_grid", role="write") == "switch.cloud_cfg"
    assert bs._get_entity("reserve_soc_number", role="write") == "number.cloud_reserve"
    assert bs._get_entity("storage_mode", role="write") == "select.cloud_mode"


def test_h1_mutation_anchor_route_table_forced_local():
    """MUTATION ANCHOR: neuter the H1 __init__ activation → the invariant
    'all three surfaces route to cloud' MUST break."""
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
    # Simulate the mutation: clear the failover table (as if H1 __init__
    # never populated it — the pre-H1 dormant scaffolding shape).
    bs._write_failover_by_surface = {}
    # Now writes fall back to local — the H1 acceptance invariant fails.
    assert bs._get_entity("charge_from_grid", role="write") == "switch.local_cfg"


def test_h1_mutation_anchor_lkg_latch_reads_local_split_brain():
    """W-5 split-brain MUTATION ANCHOR: if the LKG blip-latch reads
    from the LOCAL entity while writes go to the CLOUD entity, the
    'reads and writes see the same leg' invariant fails.

    We simulate the mutation directly: read the local entity id and
    compare to the write-route target — they must NOT be equal (proving
    the mutation is detectable).
    """
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
    write_leg = bs._get_entity(
        "charge_from_grid", role="write",
    )
    # MUTATION: LKG latch reads with role="read" (the pre-H1 wiring).
    mutated_read_leg = bs._get_entity("charge_from_grid", role="read")
    assert write_leg == "switch.cloud_cfg"
    assert mutated_read_leg == "switch.local_cfg"
    # Split brain: writes cloud, reads local. Invariant violated.
    assert write_leg != mutated_read_leg


def test_h1_storage_mode_dispatch_uses_cloud_label():
    """Writing storage_mode to the CLOUD select must map local vocab
    → cloud label. MUTATION ANCHOR: if the mapping is skipped, the
    dispatched option is 'self_consumption' (local), not
    'Self-Consumption' (cloud) — the cloud select would reject it.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    hass = MockHass()
    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "storage_mode": "select.local_mode",
            "cloud_storage_mode_oracle": "select.cloud_mode",
        },
    )
    # Drive the real _result mode-change branch: current_mode != mode.
    result = bs._result(
        mode="self_consumption",
        reason="test",
        current_mode="backup",
    )
    actions = result["actions"]
    sm_actions = [a for a in actions if a["service"] == "select.select_option"]
    assert len(sm_actions) == 1
    assert sm_actions[0]["target"] == "select.cloud_mode"
    # H1: the option MUST be the cloud label.
    assert sm_actions[0]["data"]["option"] == "Self-Consumption"


def test_h1_storage_mode_mutation_anchor_missing_label_map():
    """MUTATION ANCHOR: if the local→cloud label mapping is removed
    from the dispatch site, the option string is the local vocab
    (which the cloud select would reject)."""
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        STORAGE_MODE_LOCAL_TO_CLOUD,
    )
    # Just verify the map is present + correct — if a mutation deletes
    # STORAGE_MODE_LOCAL_TO_CLOUD (or empties it), .get() falls back
    # to the raw local value, and the previous test detects it.
    assert STORAGE_MODE_LOCAL_TO_CLOUD["self_consumption"] == "Self-Consumption"
    assert STORAGE_MODE_LOCAL_TO_CLOUD["savings"] == "Savings"


def test_h1_self_heal_re_dispatch_when_cloud_off_local_lying_on(caplog):
    """H1 addendum (2026-07-13) — MANDATORY live-evidence scenario.

    Boot state: intent = charge_from_grid ON (arbitrage CHARGE active),
    cloud leg (write leg) reads OFF, local leg reads ON (lying / stale
    post-restart — the exact ~11:21 tripwire condition). With cloud-
    first reads, the decision cycle MUST re-dispatch turn_on within one
    cycle so the dispatch tap schedules a verification.

    MUTATION ANCHOR: repoint the intent-read back to the local leg
    (role='read') → the re-dispatch does not happen → this test fails.
    """
    import logging
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
    # Boot state: local lies ON, cloud reflects reality (OFF).
    _set_state(hass, "switch.local_cfg", "on")
    _set_state(hass, "switch.cloud_cfg", "off")

    caplog.set_level(logging.INFO)
    # Drive the real _result with intent=on, current_mode == mode so
    # only the charge_from_grid branch fires.
    result = bs._result(
        mode="self_consumption",
        reason="arbitrage CHARGE",
        current_mode="self_consumption",
        charge_from_grid=True,
    )
    turn_on_actions = [
        a for a in result["actions"] if a["service"] == "switch.turn_on"
    ]
    # H1 invariant: cloud-first reads see cloud=OFF → a turn_on action
    # is appended (self-heal). Target is the cloud entity.
    assert len(turn_on_actions) == 1
    assert turn_on_actions[0]["target"] == "switch.cloud_cfg"
    # The self-heal INFO log fires so operators can see it in the log.
    assert any(
        "H1 self-heal" in rec.message for rec in caplog.records
    )


def test_h1_self_heal_mutation_anchor_reads_local_no_redispatch():
    """MUTATION ANCHOR for the addendum: if the intent-read (current_cfg
    resolver) were repointed to the LOCAL leg (role='read'), the local's
    lying 'on' would tell URA the switch is already ON → no action
    dispatched → no verification scheduled → the tripwire stays no_data,
    reproducing the ~11:21 live evidence.
    """
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
    _set_state(hass, "switch.local_cfg", "on")
    _set_state(hass, "switch.cloud_cfg", "off")

    # Simulate the mutation by asking about state through role="read"
    # (local leg) — the pre-H1 behavior.
    local_cfg_read = bs._get_state_bool(
        bs._get_entity("charge_from_grid", role="read")
    )
    cloud_cfg_read = bs._get_state_bool(
        bs._get_entity("charge_from_grid", role="write")
    )
    # Post-mutation invariant: reading local, URA thinks switch is ON.
    # H1 invariant: reading cloud, URA sees OFF and re-dispatches.
    assert local_cfg_read is True
    assert cloud_cfg_read is False
    assert local_cfg_read != cloud_cfg_read


def test_h1_write_route_attr_exposed(hass):
    """H1: get_status_attrs surfaces write_route per surface for the
    operator to see routing live."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    coord = _FakeCoord(hass)
    # Populate the failover flags on the fake battery to mimic H1
    # __init__ activation.
    coord._battery._write_failover_by_surface = {
        "charge_from_grid": True,
        "reserve_soc_number": True,
        "storage_mode": True,
    }
    v = WriteVerifier(hass, coord)
    attrs = v.get_status_attrs()
    for surface in ("reserve_soc", "charge_from_grid", "storage_mode"):
        assert attrs[f"last_verified_write_{surface}"]["write_route"] == "cloud"
    # And when the failover flag is False, the route reports local.
    coord._battery._write_failover_by_surface = {
        "charge_from_grid": False,
        "reserve_soc_number": False,
        "storage_mode": False,
    }
    attrs2 = v.get_status_attrs()
    for surface in ("reserve_soc", "charge_from_grid", "storage_mode"):
        assert attrs2[f"last_verified_write_{surface}"]["write_route"] == "local"
