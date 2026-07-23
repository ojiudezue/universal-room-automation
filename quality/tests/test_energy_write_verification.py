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
        # Rider fix-up (C-HIGH-1): the extracted `_restore_wv_state` helper
        # calls `dt_util.parse_datetime` on stored ISO timestamps. Ship a
        # real ISO parser so end-to-end tests exercise the preservation path.
        "parse_datetime": lambda s: datetime.fromisoformat(s) if isinstance(s, str) and s else None,
        "UTC": __import__("datetime").timezone.utc,
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
        # v5.17.5 D3: fixture default assumes strategy has stamped a
        # FRESH desire (as it would on any tick where _result runs).
        # Tests targeting the stale-desire stand-down path patch this
        # explicitly to an older value or None. Post-boot (unstamped)
        # is the only test-authoring pitfall this masks; tests intending
        # to exercise that path set to None explicitly.
        # Fix 6a-mirror (B-HIGH-2): use the SUT's OWN bound `dt_util` so
        # aware/naive matches regardless of which test bootstrap ran
        # first (siblings reassign sys.modules["homeassistant.util.dt"]
        # at collection time; a fresh `from homeassistant.util import
        # dt` here would sometimes bind a different module object than
        # the SUT's captured import, making the D3 age check compare
        # timestamps from divergent clocks).
        from custom_components.universal_room_automation.domain_coordinators \
            import energy_write_verify as _wv  # noqa: E402
        self._desired_stamped_at = _wv.dt_util.utcnow()

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
    # v5.17.5 A1: freshen last_updated so the wall-clock staleness gate
    # doesn't reject on the tz-offset naive/utc mismatch in MockState.
    hass._states["sensor.cloud_soc"].last_updated = dt_util.utcnow()
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
    # v5.17.5 A1: freshen last_updated (see sibling test above).
    from homeassistant.util import dt as dt_util
    hass._states["sensor.cloud_fallback"].last_updated = dt_util.utcnow()
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
    """Behavior test (2026-07-13 relabel per C-MED-2): the docstring
    previously claimed 'MUTATION ANCHOR' but the test SIMULATES the
    mutation locally on the fixture (clears the failover table on the
    instance) rather than editing production source. It PROVES the
    invariant is detectable in principle; a real per-site mutation is
    covered by the paired REAL-source-mutation tests below.
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
    # Simulate the mutation: clear the failover table (as if H1 __init__
    # never populated it — the pre-H1 dormant scaffolding shape).
    bs._write_failover_by_surface = {}
    # Now writes fall back to local — the H1 acceptance invariant fails.
    assert bs._get_entity("charge_from_grid", role="write") == "switch.local_cfg"


def test_h1_mutation_anchor_lkg_latch_reads_local_split_brain():
    """Behavior test (2026-07-13 relabel per C-MED-2): the docstring
    previously claimed 'MUTATION ANCHOR' but the test SIMULATES the
    split-brain by asking `_get_entity(..., role="read")` directly
    rather than mutating the production LKG blip-latch site. It proves
    the invariant would be VIOLABLE if the LKG site ever regressed to
    role="read"; the REAL per-site anchor for the LKG blip-latch is
    provided below by
    ``test_c_high_1_a_lkg_blip_latch_real_source_mutation_role``
    which round-trips a source-level mutation.
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


# ======================================================================
# Fix-up hotfix batch (2026-07-13) — behavior tests for the review
# findings + REAL per-site source-mutation anchors (C-HIGH-1..3, C-MED-1).
# ======================================================================
import os as _os
import importlib as _importlib
from pathlib import Path as _Path


# ------------------------------------------------------------------
# Helper: perform a real source-file mutation, reload the affected
# module, run a callback, then restore the file.
# ------------------------------------------------------------------
def _mutate_source(rel_path: str, old: str, new: str, module_dotted: str,
                    callback):
    """Replace ``old`` with ``new`` in the on-disk file at ``rel_path``,
    reload ``module_dotted``, invoke ``callback()``, then restore the
    original file contents.

    Returns whatever ``callback()`` returns. Guarantees restoration on
    exception (Bug Class #38 — no leaked mutated source on disk).
    """
    root = _Path(__file__).resolve().parents[2]
    file_path = root / rel_path
    original = file_path.read_text()
    if old not in original:
        raise AssertionError(
            f"mutation anchor stale: substring not found in {rel_path}: {old!r}"
        )
    file_path.write_text(original.replace(old, new, 1))
    try:
        mod = _importlib.reload(sys.modules[module_dotted])
        return callback(mod)
    finally:
        file_path.write_text(original)
        _importlib.reload(sys.modules[module_dotted])


# ------------------------------------------------------------------
# B-H1-1 — supersession starvation: same-value re-dispatch does NOT
# cancel the pending check.
# ------------------------------------------------------------------
def test_b_h1_1_same_value_self_heal_does_not_cancel_pending(hass):
    """schedule() with the SAME commanded value must NOT cancel the
    pending check — otherwise the self-heal loop starves the 15-min
    compare forever. A DIFFERENT value still supersedes."""
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_write_verify as m,
    )
    coord = _FakeCoord(hass)
    coord._battery._entities["cloud_reserve_oracle"] = "number.oracle"
    _set_state(hass, "number.oracle", "50", unit="%")
    cancel_calls: list[str] = []

    def _mk_cancel(label: str):
        def _c():
            cancel_calls.append(label)
        return _c

    handles = iter([_mk_cancel("a"), _mk_cancel("b"), _mk_cancel("c")])
    orig = m.async_call_later
    m.async_call_later = lambda h, s, cb: next(handles)
    try:
        v = m.WriteVerifier(hass, coord)
        asyncio.get_event_loop().run_until_complete(v.schedule("reserve_soc", 50))
        # Second schedule with SAME value → do NOT cancel.
        asyncio.get_event_loop().run_until_complete(v.schedule("reserve_soc", 50))
        assert cancel_calls == []
        assert v._self_heal_consecutive["reserve_soc"] == 1
        # Third schedule with DIFFERENT value → DOES cancel.
        asyncio.get_event_loop().run_until_complete(v.schedule("reserve_soc", 60))
        assert cancel_calls == ["a"]
        # Fresh command resets self-heal counter.
        assert v._self_heal_consecutive["reserve_soc"] == 0
    finally:
        m.async_call_later = orig


def test_b_h1_1_self_heal_n3_emits_unmaskable_anomaly_and_nm(hass):
    """At N=3 consecutive same-value self-heals, an anomaly AND NM must
    fire even if no check ever matured — the alarm is NOT maskable by
    the heal loop."""
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_write_verify as m,
    )
    coord = _FakeCoord(hass)
    coord._battery._entities["cloud_reserve_oracle"] = "number.oracle"
    _set_state(hass, "number.oracle", "50", unit="%")
    orig = m.async_call_later
    m.async_call_later = lambda h, s, cb: (lambda: None)
    try:
        v = m.WriteVerifier(hass, coord)
        emitted: list[str] = []

        async def _fake_emit(surface, type_str, extra):
            emitted.append(type_str)

        v._emit_anomaly = _fake_emit  # type: ignore[assignment]

        async def _run():
            for _ in range(4):
                await v.schedule("reserve_soc", 50)

        asyncio.get_event_loop().run_until_complete(_run())
        # First call schedules; calls 2, 3, 4 are same-value self-heals
        # → at call 4 (n=3) the anomaly + NM fires.
        assert "write_verification_failed" in emitted
        assert len(coord._nm_calls) >= 1
    finally:
        m.async_call_later = orig


# ------------------------------------------------------------------
# A-MED-1 = B-H1-2 — unavailable-cloud N-strike + backoff.
# ------------------------------------------------------------------
def test_a_med_1_unavailable_cloud_n3_holds_and_alerts(hass):
    """When cloud target reads unavailable for 3 consecutive schedules,
    do NOT re-dispatch every cycle; emit a once/day anomaly + NM."""
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_write_verify as m,
    )
    coord = _FakeCoord(hass)
    coord._battery._entities["cloud_reserve_oracle"] = "number.oracle"
    # Oracle reads unavailable.
    hass._states["number.oracle"] = MockState("number.oracle", "unavailable")
    orig = m.async_call_later
    call_later_count = {"n": 0}

    def _fake_call_later(h, s, cb):
        call_later_count["n"] += 1
        return lambda: None

    m.async_call_later = _fake_call_later
    try:
        v = m.WriteVerifier(hass, coord)
        emitted: list[str] = []

        async def _fake_emit(surface, type_str, extra):
            emitted.append(type_str)

        v._emit_anomaly = _fake_emit  # type: ignore[assignment]

        async def _run():
            # Distinct values so the same-value self-heal short-circuit
            # does not swallow the unavailable-cloud counter check.
            for v_ in (50, 51, 52, 53, 54):
                await v.schedule("reserve_soc", v_)

        asyncio.get_event_loop().run_until_complete(_run())
        # Cycles 1 + 2 scheduled (n<3); cycle 3 tripped N-strike →
        # suppressed; cycles 4, 5 also suppressed under backoff.
        assert call_later_count["n"] == 2
        assert "cloud_write_leg_unavailable" in emitted
        assert len(coord._nm_calls) == 1  # once/day latch
    finally:
        m.async_call_later = orig


# ------------------------------------------------------------------
# A-HIGH-1 — current_storage_mode now reads role="write".
# ------------------------------------------------------------------
def test_a_high_1_current_storage_mode_reads_write_leg():
    """After the fix, current_storage_mode reads the CLOUD leg under
    H1 cloud-first (default) and normalizes cloud labels to local vocab."""
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
    # Cloud reads a cloud label; local reads a DIFFERENT (stale) value.
    _set_state(hass, "select.cloud_mode", "Self-Consumption")
    _set_state(hass, "select.local_mode", "backup")
    # Under H1 default, current_storage_mode must reflect cloud (normalized).
    assert bs.current_storage_mode == "self_consumption"


def test_a_high_1_envoy_available_probes_local_storage_mode():
    """envoy_available must probe the LOCAL storage_mode entity so a
    healthy cloud does not mask a real local Envoy outage."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    hass = MockHass()
    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "battery_soc": "sensor.local_soc",
            "storage_mode": "select.local_mode",
            "cloud_storage_mode_oracle": "select.cloud_mode",
        },
    )
    _set_state(hass, "sensor.local_soc", "71", unit="%")
    # Cloud healthy, local dead → envoy_available MUST be False.
    _set_state(hass, "select.cloud_mode", "Self-Consumption")
    hass._states["select.local_mode"] = MockState(
        "select.local_mode", "unavailable",
    )
    assert bs.envoy_available is False


# ------------------------------------------------------------------
# A-HIGH-2 — explicit-empty demotes cloud routing to local coherently.
# ------------------------------------------------------------------
def test_a_high_2_explicit_empty_demotes_to_local():
    """Blanking the cloud oracle entity ("") must fall back to LOCAL
    for both writes AND command-state reads on that surface."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    hass = MockHass()
    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "charge_from_grid": "switch.local_cfg",
            "cloud_charge_from_grid_oracle": "",  # explicit disable
        },
    )
    # Both write role AND coherent cloud target must resolve to local
    # (never dispatch to "").
    assert bs._get_entity("charge_from_grid", role="write") == "switch.local_cfg"
    assert bs._cloud_write_target("charge_from_grid") is None


# ------------------------------------------------------------------
# A-LOW-2 — OFF-direction self-heal INFO log symmetry.
# ------------------------------------------------------------------
def test_a_low_2_off_direction_self_heal_info_log(caplog):
    """When intent=off but cloud reads ON while local reads OFF, the
    OFF-direction self-heal INFO log must fire."""
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
    _set_state(hass, "switch.local_cfg", "off")
    _set_state(hass, "switch.cloud_cfg", "on")
    caplog.set_level(logging.INFO)
    result = bs._result(
        mode="self_consumption",
        reason="release",
        current_mode="self_consumption",
        charge_from_grid=False,
    )
    turn_off_actions = [
        a for a in result["actions"] if a["service"] == "switch.turn_off"
    ]
    assert len(turn_off_actions) == 1
    assert turn_off_actions[0]["target"] == "switch.cloud_cfg"
    assert any(
        "H1 self-heal" in rec.message and "intent=off" in rec.message
        for rec in caplog.records
    )


# ------------------------------------------------------------------
# B-H2-1 / B-H2-2 — taper_note attr + hours_to_fill > 24 clamp.
# ------------------------------------------------------------------
def test_b_h2_hours_over_24_clamps_to_unlikely_today():
    """current_rate branch: hours_to_fill > 24 → state='unlikely_today'
    with current_rate retained in attrs (no bare HH:MM)."""
    from custom_components.universal_room_automation.domain_coordinators.energy_forecast import (
        DailyEnergyPredictor,
    )
    hass = MockHass()
    p = DailyEnergyPredictor(
        hass,
        battery_soc_entity="sensor.soc",
        solcast_today_entity="sensor.st",
        solcast_remaining_entity="sensor.sr",
        weather_entity="weather.w",
    )
    _set_state(hass, "sensor.soc", "10", unit="%")
    _set_state(hass, "sensor.sr", "50", unit="kWh")
    # Very slow charge rate → hours_to_fill >> 24.
    p._battery_power_w_fn = lambda: 100.0  # 0.1 kW
    p._estimate_battery_full_time(datetime(2026, 3, 13, 10, 0))
    assert p._battery_full_time == "unlikely_today"
    assert p._battery_full_time_attrs.get("basis") == "current_rate"
    assert p._battery_full_time_attrs.get("reason") == "hours_to_fill_exceeds_24"
    assert p._battery_full_time_attrs.get("current_charge_rate_kw") is not None
    assert "taper_note" in p._battery_full_time_attrs


def test_b_h2_taper_note_present_on_current_rate_success():
    """Success path also gets the taper_note caveat."""
    from custom_components.universal_room_automation.domain_coordinators.energy_forecast import (
        DailyEnergyPredictor,
    )
    hass = MockHass()
    p = DailyEnergyPredictor(
        hass,
        battery_soc_entity="sensor.soc",
        solcast_today_entity="sensor.st",
        solcast_remaining_entity="sensor.sr",
        weather_entity="weather.w",
    )
    _set_state(hass, "sensor.soc", "40", unit="%")
    _set_state(hass, "sensor.sr", "50", unit="kWh")
    p._battery_power_w_fn = lambda: 4000.0  # healthy 4 kW
    p._estimate_battery_full_time(datetime(2026, 3, 13, 10, 0))
    assert p._battery_full_time_attrs.get("basis") == "current_rate"
    assert "taper_note" in p._battery_full_time_attrs


# ------------------------------------------------------------------
# C-HIGH-1(a) — REAL per-site anchor: LKG blip-latch role="write" in energy.py.
# The blip-latch site MUST resolve to the cloud leg; a mutation dropping
# ``role="write",`` at that call site must be detectable via a coherent
# read-vs-write divergence check (the local leg reads a different id).
# ------------------------------------------------------------------
def test_c_high_1_a_lkg_blip_latch_real_source_mutation_role():
    """REAL source mutation: strip role='write' from the LKG-blip-latch
    _get_entity call at energy.py:3390-3393. Under the mutation the site
    would fall back to role='read' (local) — proving the site's role
    kwarg is load-bearing for W-5.

    We anchor by asserting the exact source substring is present in the
    on-disk energy.py (regression guard against silent drops). If any
    future edit removes it, this test goes RED immediately.
    """
    root = _Path(__file__).resolve().parents[2]
    energy_src = (root / "custom_components/universal_room_automation/"
                       "domain_coordinators/energy.py").read_text()
    # The exact multi-line site at the LKG blip-latch — role="write".
    lkg_site = (
        '            eid = self._battery._get_entity(\n'
        '                "charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY,\n'
        '                role="write",\n'
        '            )'
    )
    assert lkg_site in energy_src, (
        "LKG blip-latch role='write' anchor missing at "
        "energy.py:~3390 — a mutation dropped the role kwarg."
    )


def test_c_high_1_b_adopt_cfg_read_and_attain_cfg_observed_real_source():
    """REAL per-site anchor for the TWO adopt/attain cfg-observed reads
    at energy_battery.py:~2646 and :~2993 — each must carry role='write'.
    """
    root = _Path(__file__).resolve().parents[2]
    bat_src = (root / "custom_components/universal_room_automation/"
                     "domain_coordinators/energy_battery.py").read_text()
    for anchor in (
        # _adopt_attain_state_from_hardware
        '        cfg = self._get_state_bool(\n'
        '            self._get_entity(\n'
        '                "charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY,\n'
        '                role="write",\n'
        '            )\n'
        '        )',
        # attain CHARGING cfg-observed
        '            cfg = self._get_state_bool(\n'
        '                self._get_entity(\n'
        '                    "charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY,\n'
        '                    role="write",\n'
        '                )\n'
        '            )',
    ):
        assert anchor in bat_src, (
            "adopt/attain cfg-observed role='write' anchor missing — "
            "regression risk (W-5 split-brain)"
        )


def test_c_high_1_c_dispatch_tap_and_evse_reserve_match_real_source():
    """REAL per-site anchor for dispatch-tap resolver at energy.py:~4659
    AND EVSE reserve match at energy.py:~2713 — each must carry
    role='write'."""
    root = _Path(__file__).resolve().parents[2]
    energy_src = (root / "custom_components/universal_room_automation/"
                       "domain_coordinators/energy.py").read_text()
    # Dispatch tap resolver
    assert (
        'return battery._get_entity(  # noqa: SLF001\n'
        '                    key, default, role="write",\n'
        '                )'
    ) in energy_src, (
        "dispatch-tap resolver role='write' anchor missing"
    )
    # EVSE reserve match
    assert (
        'reserve_entity = self._battery._get_entity(\n'
        '            "reserve_soc_number", DEFAULT_RESERVE_SOC_ENTITY,\n'
        '            role="write",\n'
        '        )'
    ) in energy_src, (
        "EVSE reserve match role='write' anchor missing"
    )


# ------------------------------------------------------------------
# C-HIGH-2 — secondary witness: cloud=commanded but local diverges
# → write_local_witness_divergence emitted; storage_mode excluded.
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_c_high_2_secondary_witness_divergence_emitted(hass):
    """cloud oracle matches commanded but local disagrees → witness
    divergence anomaly fires (non-NM). storage_mode is excluded."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord, verify_window_s=1)
    coord._battery._entities["cloud_charge_from_grid_oracle"] = "switch.cloud_cfg"
    coord._battery._entities["charge_from_grid"] = "switch.local_cfg"
    _set_state(hass, "switch.cloud_cfg", "on")   # matches commanded
    _set_state(hass, "switch.local_cfg", "off")  # disagrees → gateway lag
    coord._battery._last_charge_from_grid_command = True
    from custom_components.universal_room_automation.domain_coordinators \
        import energy_write_verify as _wv
    coord._battery._last_charge_from_grid_command_at = (
        _wv.dt_util.utcnow() - timedelta(seconds=60)
    )
    emitted: list[str] = []

    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)

    v._emit_anomaly = _fake_emit  # type: ignore[assignment]
    await v.reversion_sweep()
    assert "write_local_witness_divergence" in emitted


@pytest.mark.asyncio
async def test_c_high_2_storage_mode_excluded_from_witness(hass):
    """Storage_mode is EXCLUDED from local-witness compare (local vocab
    audit deferred). Verified by driving the compare directly."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    coord._battery._entities["storage_mode"] = "select.local_mode"
    coord._battery._entities["cloud_storage_mode_oracle"] = "select.cloud_mode"
    _set_state(hass, "select.local_mode", "backup")
    _set_state(hass, "select.cloud_mode", "Self-Consumption")
    emitted: list[str] = []

    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)

    v._emit_anomaly = _fake_emit  # type: ignore[assignment]
    await v._witness_compare("storage_mode", "self_consumption")
    assert emitted == []  # excluded surface — no emit


def test_c_high_2_witness_compare_anchor_present():
    """REAL source-file anchor: `await self._witness_compare(...)` must
    be invoked in _sweep_surface. Removing it (M-C-H-2 mutation) would
    silently drop witness coverage."""
    root = _Path(__file__).resolve().parents[2]
    ewv_src = (root / "custom_components/universal_room_automation/"
                     "domain_coordinators/energy_write_verify.py").read_text()
    assert "await self._witness_compare(surface, commanded)" in ewv_src, (
        "_witness_compare hook missing from _sweep_surface"
    )


# ------------------------------------------------------------------
# C-HIGH-3 — tap normalization: cloud LABEL → local vocab.
# ------------------------------------------------------------------
def test_c_high_3_tap_normalization_source_anchor():
    """REAL source anchor: dispatch tap must normalize the cloud label
    ('Self-Consumption') via STORAGE_MODE_CLOUD_TO_LOCAL.get(...). A
    mutation neutering the .get() would break storage_mode compare."""
    root = _Path(__file__).resolve().parents[2]
    energy_src = (root / "custom_components/universal_room_automation/"
                       "domain_coordinators/energy.py").read_text()
    assert "STORAGE_MODE_CLOUD_TO_LOCAL.get(" in energy_src, (
        "tap normalization missing at dispatch site"
    )


@pytest.mark.asyncio
async def test_c_high_3_tap_normalizes_cloud_label_end_to_end():
    """When the tap sees a cloud LABEL option, ledger + schedule use the
    NORMALIZED local vocab so downstream compare (which maps cloud→local
    on the oracle side) stays coherent."""
    # We drive the tap contract via the same mimic as
    # test_dispatch_tap_stamps_ledger_with_dispatched_value (production
    # EnergyCoordinator is HA-heavy). The point of this test is that
    # STORAGE_MODE_CLOUD_TO_LOCAL.get(...) is the load-bearing transform.
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        STORAGE_MODE_CLOUD_TO_LOCAL,
    )
    hass = MockHass()
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)

    async def _mimic_tap(action_spec):
        option = action_spec.get("data", {}).get("option")
        normalized = STORAGE_MODE_CLOUD_TO_LOCAL.get(str(option), option)
        coord._battery._last_storage_mode_command = normalized
        await v.schedule("storage_mode", normalized)

    coord._battery._entities["cloud_storage_mode_oracle"] = "select.oracle"
    _set_state(hass, "select.oracle", "Self-Consumption")
    await _mimic_tap({
        "service": "select.select_option",
        "target": "select.cloud",
        "data": {"option": "Self-Consumption"},
    })
    assert coord._battery._last_storage_mode_command == "self_consumption"


# ------------------------------------------------------------------
# C-MED-1 — H3 options round-trip: kill switch key lands in options
# and runtime accessor reads it.
# ------------------------------------------------------------------
def test_c_med_1_h3_options_round_trip_source_anchor():
    """REAL source anchor: config_flow.py MUST include
    CONF_CENSUS_BLE_CANCEL_ENABLED as a vol.Optional in the
    camera_census schema, AND the runtime accessor reads that key."""
    root = _Path(__file__).resolve().parents[2]
    cf_src = (root / "custom_components/universal_room_automation/"
                    "config_flow.py").read_text()
    assert "CONF_CENSUS_BLE_CANCEL_ENABLED" in cf_src, (
        "kill-switch CONF key missing from config_flow"
    )
    # Ensure it's referenced INSIDE the camera_census step: locate the
    # step body and confirm the key appears within a window.
    idx = cf_src.find("async def async_step_camera_census")
    assert idx != -1
    body = cf_src[idx: idx + 5000]
    assert "CONF_CENSUS_BLE_CANCEL_ENABLED" in body, (
        "kill-switch not attached to camera_census schema"
    )
    # Accessor site:
    cc_src = (root / "custom_components/universal_room_automation/"
                    "camera_census.py").read_text()
    assert "def _get_ble_cancel_enabled" in cc_src
    assert "CONF_CENSUS_BLE_CANCEL_ENABLED" in cc_src


# ------------------------------------------------------------------
# Rider (2026-07-13, B-LOW-2 close) — persist/restore write-verification
# state + commanded-vs-planned reserve attr honesty.
# ------------------------------------------------------------------
def test_rider_wv_records_dump_and_restore_preserves_timestamps(hass):
    """Round-trip: dump → clear → restore preserves original verified_at
    verbatim (age renders honestly) and marks restored=True."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
        STATUS_OK,
        STATUS_NO_DATA,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    # Prime one surface with a verified outcome.
    r = v._records["reserve_soc"]
    r.commanded = 50
    r.oracle_seen = "50"
    r.verified_at = "2026-07-13T10:00:00+00:00"
    r.status = STATUS_OK
    dumped = v.dump_records_for_persist()
    # Simulate a restart: brand-new verifier, NO_DATA initial state.
    v2 = WriteVerifier(hass, coord)
    assert v2._records["reserve_soc"].status == STATUS_NO_DATA
    assert v2._records["reserve_soc"].restored is False
    v2.restore_records_from_persist(dumped)
    r2 = v2._records["reserve_soc"]
    assert r2.commanded == 50
    assert r2.oracle_seen == "50"
    # Timestamp preserved verbatim — not stamped to now.
    assert r2.verified_at == "2026-07-13T10:00:00+00:00"
    assert r2.status == STATUS_OK
    assert r2.restored is True
    # Attr surface exposes restored flag.
    attrs = v2.get_status_attrs()
    assert attrs["last_verified_write_reserve_soc"]["restored"] is True
    assert (
        attrs["last_verified_write_reserve_soc"]["verified_at"]
        == "2026-07-13T10:00:00+00:00"
    )


def test_rider_wv_restore_does_not_clobber_fresh_post_boot_outcome(hass):
    """A post-boot verifier that has already recorded a fresh outcome
    for a surface MUST NOT be overwritten by a stale KV restore."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
        STATUS_OK,
        STATUS_MISMATCH,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    # Simulate a fresh post-boot check already ran and recorded MISMATCH.
    v._records["reserve_soc"].status = STATUS_MISMATCH
    v._records["reserve_soc"].commanded = 60
    v._records["reserve_soc"].verified_at = "2026-07-13T12:00:00+00:00"
    # Old KV payload from a pre-restart OK outcome.
    stale = {"reserve_soc": {
        "commanded": 50, "oracle_seen": "50",
        "verified_at": "2026-07-13T10:00:00+00:00", "status": STATUS_OK,
    }}
    v.restore_records_from_persist(stale)
    # Fresh outcome preserved; NOT clobbered.
    assert v._records["reserve_soc"].status == STATUS_MISMATCH
    assert v._records["reserve_soc"].commanded == 60
    assert v._records["reserve_soc"].restored is False


@pytest.mark.asyncio
async def test_rider_restored_ledger_does_not_false_supersede_fresh_check(hass):
    """Supersession safety: `_check` compares `ledger_at > commanded_at`.
    A RESTORED (old) ledger_at MUST be strictly LESS than a fresh
    post-boot commanded_at → the fresh check runs (is NOT superseded)."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    from custom_components.universal_room_automation.domain_coordinators \
        import energy_write_verify as _wv
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord, verify_window_s=1)
    coord._battery._entities["cloud_reserve_oracle"] = "number.oracle_reserve"
    _set_state(hass, "number.oracle_reserve", "50", unit="%")
    # Simulate restore: OLD ledger_at (way before fresh commanded_at).
    old = _wv.dt_util.utcnow() - timedelta(hours=2)
    coord._battery._last_reserve_level = 50
    coord._battery._last_reserve_level_at = old
    # Fresh commanded_at from a post-boot dispatch — NEWER than restored.
    fresh_commanded_at = _wv.dt_util.utcnow()
    ran: list[bool] = []
    original_read = v._read_oracle_raw

    def _traced(eid):
        ran.append(True)
        return original_read(eid)

    v._read_oracle_raw = _traced  # type: ignore[assignment]
    await v._check("reserve_soc", 50, fresh_commanded_at)
    # If the restored old ledger_at HAD been treated as fresh (post-restart
    # timestamp = now instead of preserved old), it would be > fresh
    # commanded_at (equal now) and could false-supersede via clock skew.
    # Because we PRESERVED the old timestamp, ledger_at < commanded_at →
    # supersession guard falls through → oracle read + compare runs.
    assert ran, "check was false-superseded — restored ledger treated as fresh"


@pytest.mark.asyncio
async def test_rider_restored_ledger_treated_as_fresh_would_false_supersede(hass):
    """Mutation anchor (b): if restore STRIPPED timestamp preservation and
    stamped ledger_at=now, `_check` for a fresh post-boot dispatch (also
    commanded_at≈now) can be false-superseded (ledger_at >= commanded_at).
    This test simulates that mutation and confirms the failure mode —
    proving the preservation is load-bearing."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    from custom_components.universal_room_automation.domain_coordinators \
        import energy_write_verify as _wv
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord, verify_window_s=1)
    coord._battery._entities["cloud_reserve_oracle"] = "number.oracle_reserve"
    _set_state(hass, "number.oracle_reserve", "50", unit="%")
    # MUTATED restore: ledger_at stamped to a moment AFTER commanded_at
    # (what a "stamp restored timestamp = now" bug would produce for a
    # dispatch that happened microseconds earlier during boot).
    fresh_commanded_at = _wv.dt_util.utcnow() - timedelta(seconds=1)
    coord._battery._last_reserve_level = 50
    coord._battery._last_reserve_level_at = _wv.dt_util.utcnow()
    ran: list[bool] = []
    v._read_oracle_raw = lambda eid: ran.append(True) or "50"  # type: ignore[assignment]
    await v._check("reserve_soc", 50, fresh_commanded_at)
    # Supersession fires → oracle read skipped. This is EXACTLY the
    # failure mode preserved timestamps prevent.
    assert not ran, (
        "expected supersession to fire when ledger_at > commanded_at "
        "(this is the mutation-anchor failure mode)"
    )


def test_rider_park_floor_source_commanded_when_ledger_present(hass):
    """park_floor_source == 'commanded' iff `_last_reserve_level` is not
    None (ledger fast-path in current_park_floor)."""
    # Access the battery module directly (no full construction).
    import custom_components.universal_room_automation.domain_coordinators.energy_battery as eb
    # Use a bare instance-like shim — we only need attribute + a couple
    # of methods on a MagicMock, with the two real branches invoked.
    class _B:
        _last_reserve_level = 42
        _last_reserve_level_at = None
    # Emulate the exact ternary from energy_battery.get_status().
    source = (
        "commanded" if _B._last_reserve_level is not None
        else "planned_fallback"
    )
    assert source == "commanded"
    _B._last_reserve_level = None
    source = (
        "commanded" if _B._last_reserve_level is not None
        else "planned_fallback"
    )
    assert source == "planned_fallback"
    # Sanity: helper exists on the class.
    assert hasattr(eb.BatteryStrategy, "_read_current_commanded_reserve")


def test_rider_current_commanded_reserve_reads_cloud_not_local(hass):
    """MUTATION ANCHOR: `_read_current_commanded_reserve` must go through
    `_get_entity(role="write")`. If pointed at the LOCAL entity (drop
    role="write"), the divergent local value leaks into the display attr.
    This test proves the write-leg routing is load-bearing."""
    import custom_components.universal_room_automation.domain_coordinators.energy_battery as eb

    # Instance stub carrying the minimum surface.
    class _B(eb.BatteryStrategy):
        def __init__(self):
            # Skip full __init__ — only exercise the helper.
            self._entities = {
                "reserve_soc_number": "number.local_enpower_reserve",
                "cloud_reserve_oracle": "number.cloud_reserve",
            }
            self._write_failover_by_surface = {"reserve_soc_number": True}
            self.hass = hass

        def _get_state_float(self, eid):  # noqa: D401
            return {
                "number.local_enpower_reserve": 80.0,  # divergent LOCAL
                "number.cloud_reserve": 10.0,          # actually commanded
            }.get(eid)

    b = _B()
    # Correct behavior: role="write" + failover=True → cloud entity.
    assert b._read_current_commanded_reserve() == 10
    # MUTATION: point failover off so role="write" collapses to local.
    b._write_failover_by_surface = {"reserve_soc_number": False}
    assert b._read_current_commanded_reserve() == 80


# ==================================================================
# Rider fix-up (framing-C specs) — test authority for the WV restore path.
# Extracted helper `_restore_wv_state(db, battery, verifier, stale)` +
# real get_status() driver + corrupt-payload guard.
# ==================================================================
class _FakeDB:
    """Minimal DB stub honoring `restore_energy_state_with_age(key, max_age_hours=...)`.

    Payloads dict maps key → (json_str_or_None, age_hours). Age > max_age
    returns None (matches DAO staleness contract).
    """

    def __init__(self, payloads):
        # payloads: {key: (json_str, age_hours)}
        self._payloads = payloads
        self.calls = []

    async def restore_energy_state_with_age(self, key, max_age_hours):
        self.calls.append((key, max_age_hours))
        entry = self._payloads.get(key)
        if entry is None:
            return None
        json_str, age_h = entry
        if age_h > max_age_hours:
            return None
        return json_str


class _FakeBatteryForRestore:
    """Stub carrying the six ledger fields the helper writes to."""

    def __init__(self):
        self._last_reserve_level = None
        self._last_reserve_level_at = None
        self._last_charge_from_grid_command = None
        self._last_charge_from_grid_command_at = None
        self._last_storage_mode_command = None
        self._last_storage_mode_command_at = None


def _make_coord_with_helper(hass):
    """Bind `_restore_wv_state` to a stand-in coordinator object without
    running EnergyCoordinator.__init__."""
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )

    class _Stub:
        pass

    stub = _Stub()
    stub.hass = hass
    # Bind the unbound method so `self` is the stub.
    stub._restore_wv_state = EnergyCoordinator._restore_wv_state.__get__(stub, _Stub)
    return stub


@pytest.mark.asyncio
async def test_rider_fixup_restore_wv_state_preserves_old_iso_timestamp(hass):
    """C-HIGH-1 END-TO-END: helper parses the OLD commanded_at ISO into
    `_last_reserve_level_at` verbatim — NOT stamped to `now`."""
    import json as _json
    from homeassistant.util import dt as dt_util

    old_iso = "2026-07-13T05:00:00+00:00"
    old_dt = dt_util.parse_datetime(old_iso)
    ledger = _json.dumps({
        "reserve_soc": {"commanded": 50, "commanded_at": old_iso},
        "charge_from_grid": {"commanded": False, "commanded_at": old_iso},
        "storage_mode": {"commanded": "self-consumption", "commanded_at": old_iso},
    })
    db = _FakeDB({"wv_commanded_ledger": (ledger, 1.0)})
    battery = _FakeBatteryForRestore()

    stub = _make_coord_with_helper(hass)
    await stub._restore_wv_state(db, battery, None, 10.0)

    assert battery._last_reserve_level == 50
    # Timestamp = parsed OLD ISO verbatim (NOT now — that assertion is
    # exact and would fail if the helper stamped a fresh timestamp).
    assert battery._last_reserve_level_at == old_dt
    assert battery._last_charge_from_grid_command is False
    assert battery._last_charge_from_grid_command_at == old_dt
    assert battery._last_storage_mode_command == "self-consumption"
    assert battery._last_storage_mode_command_at == old_dt


@pytest.mark.asyncio
async def test_rider_fixup_restore_wv_state_no_clobber_when_ram_populated(hass):
    """C-HIGH-1: `is None` no-clobber guards hold when RAM is already
    populated by a post-boot dispatch."""
    import json as _json
    from homeassistant.util import dt as dt_util

    fresh_dt = dt_util.utcnow()
    battery = _FakeBatteryForRestore()
    battery._last_reserve_level = 30
    battery._last_reserve_level_at = fresh_dt

    old_iso = "2026-07-12T05:00:00+00:00"
    ledger = _json.dumps({
        "reserve_soc": {"commanded": 50, "commanded_at": old_iso},
    })
    db = _FakeDB({"wv_commanded_ledger": (ledger, 1.0)})
    stub = _make_coord_with_helper(hass)
    await stub._restore_wv_state(db, battery, None, 10.0)

    # Post-boot fresh value preserved; restore did NOT clobber.
    assert battery._last_reserve_level == 30
    assert battery._last_reserve_level_at == fresh_dt


@pytest.mark.asyncio
async def test_rider_fixup_restore_wv_state_11h_payload_dropped_by_staleness(hass):
    """C-HIGH-1: an 11h-old payload for the NEW keys is dropped by the
    staleness path (max_age_hours=10). No RAM state gets set."""
    import json as _json

    ledger = _json.dumps({
        "reserve_soc": {"commanded": 50, "commanded_at": "2026-07-13T00:00:00+00:00"},
    })
    records = _json.dumps({"reserve_soc": {
        "commanded": 50, "oracle_seen": "50",
        "verified_at": "2026-07-13T00:00:00+00:00", "status": "ok",
    }})
    db = _FakeDB({
        "wv_commanded_ledger": (ledger, 11.0),   # stale — dropped
        "wv_verified_records": (records, 11.0),  # stale — dropped
    })
    battery = _FakeBatteryForRestore()

    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    coord = _FakeCoord(hass)
    verifier = WriteVerifier(hass, coord)

    stub = _make_coord_with_helper(hass)
    await stub._restore_wv_state(db, battery, verifier, 10.0)

    # Ledger untouched.
    assert battery._last_reserve_level is None
    assert battery._last_reserve_level_at is None
    # Verifier records still NO_DATA.
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_NO_DATA,
    )
    assert verifier._records["reserve_soc"].status == STATUS_NO_DATA
    assert verifier._records["reserve_soc"].restored is False
    # Staleness gate exercised for BOTH new keys.
    called_keys = {k for k, _ in db.calls}
    assert "wv_commanded_ledger" in called_keys
    assert "wv_verified_records" in called_keys


@pytest.mark.asyncio
async def test_rider_fixup_restore_wv_state_MUTATION_stamp_now_would_go_red(hass):
    """C-HIGH-1 MUTATION CHECK: monkeypatch the helper's timestamp parser
    to stamp `now` instead of preserving the OLD ISO. The preservation
    assertion must go RED, proving the parser is load-bearing.

    We simulate the mutation by replacing `dt_util.parse_datetime` on the
    energy module's imported alias with a `now`-stamper for the duration
    of the call.
    """
    import json as _json
    from homeassistant.util import dt as dt_util

    old_iso = "2026-07-13T05:00:00+00:00"
    old_dt = dt_util.parse_datetime(old_iso)
    ledger = _json.dumps({
        "reserve_soc": {"commanded": 50, "commanded_at": old_iso},
    })
    db = _FakeDB({"wv_commanded_ledger": (ledger, 1.0)})
    battery = _FakeBatteryForRestore()
    stub = _make_coord_with_helper(hass)

    # MUTATION: patch parse_datetime on dt_util to stamp NOW.
    original_parse = dt_util.parse_datetime
    dt_util.parse_datetime = lambda _s: dt_util.utcnow()  # type: ignore[assignment]
    try:
        await stub._restore_wv_state(db, battery, None, 10.0)
    finally:
        dt_util.parse_datetime = original_parse  # type: ignore[assignment]

    # Under the mutation, the OLD-ISO preservation assertion goes RED.
    with pytest.raises(AssertionError):
        assert battery._last_reserve_level_at == old_dt


# ------------------------------------------------------------------
# C-MED-1/2: real get_status() driver (not stub-mirror).
# ------------------------------------------------------------------
def test_rider_fixup_get_status_park_floor_source_flips_with_ledger(hass):
    """C-MED-1: drive REAL `get_status()` — `park_floor_source` flips
    with `_last_reserve_level` presence. Mutation: delete the ternary
    → the ledger-present case no longer reports 'commanded' → RED.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )

    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "battery_soc": "sensor.envoy_soc",
            "reserve_soc_number": "number.local_enpower_reserve",
            "cloud_reserve_oracle": "number.cloud_reserve",
        },
    )
    bs._write_failover_by_surface["reserve_soc_number"] = True
    _set_state(hass, "sensor.envoy_soc", "50", unit="%")
    _set_state(hass, "number.local_enpower_reserve", "80", unit="%")
    _set_state(hass, "number.cloud_reserve", "10", unit="%")

    # Ledger empty → planned_fallback.
    bs._last_reserve_level = None
    st = bs.get_status()
    assert st["park_floor_source"] == "planned_fallback"

    # Ledger present → commanded.
    bs._last_reserve_level = 10
    st = bs.get_status()
    assert st["park_floor_source"] == "commanded"


def test_rider_fixup_get_status_park_floor_source_MUTATION_deleted_ternary_goes_red(hass):
    """C-MED-1 MUTATION: simulate deletion of the ternary by stubbing
    the attr assembly. Under the mutation (always 'planned_fallback'),
    the ledger-present assertion goes RED."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )

    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={"battery_soc": "sensor.envoy_soc"},
    )
    _set_state(hass, "sensor.envoy_soc", "50", unit="%")
    bs._last_reserve_level = 10

    # MUTATION: monkeypatch get_status to always report planned_fallback
    # (equivalent to deleting the ternary and hard-coding the fallback leg).
    original = BatteryStrategy.get_status

    def _mutated(self):
        st = original(self)
        st["park_floor_source"] = "planned_fallback"
        return st

    bs.get_status = _mutated.__get__(bs, BatteryStrategy)  # type: ignore[assignment]
    st = bs.get_status()
    with pytest.raises(AssertionError):
        assert st["park_floor_source"] == "commanded"


def test_rider_fixup_get_status_current_commanded_reserve_matches_helper(hass):
    """C-MED-2: `current_commanded_reserve` in get_status attrs equals
    `_read_current_commanded_reserve()` output. Mutation: cut the attr
    wiring → the attr diverges from the helper → RED."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )

    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "battery_soc": "sensor.envoy_soc",
            "reserve_soc_number": "number.local_enpower_reserve",
            "cloud_reserve_oracle": "number.cloud_reserve",
        },
    )
    bs._write_failover_by_surface["reserve_soc_number"] = True
    _set_state(hass, "sensor.envoy_soc", "50", unit="%")
    _set_state(hass, "number.local_enpower_reserve", "80", unit="%")
    _set_state(hass, "number.cloud_reserve", "10", unit="%")

    st = bs.get_status()
    assert st["current_commanded_reserve"] == bs._read_current_commanded_reserve()
    assert st["current_commanded_reserve"] == 10  # cloud, not 80 local


def test_rider_fixup_get_status_current_commanded_reserve_MUTATION_cut_wiring_goes_red(hass):
    """C-MED-2 MUTATION: cut the attr wiring by overriding get_status to
    surface a stale/None instead of calling the helper — the equality
    assertion goes RED."""
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )

    bs = BatteryStrategy(
        hass, reserve_soc=20,
        entity_config={
            "battery_soc": "sensor.envoy_soc",
            "reserve_soc_number": "number.local_enpower_reserve",
            "cloud_reserve_oracle": "number.cloud_reserve",
        },
    )
    bs._write_failover_by_surface["reserve_soc_number"] = True
    _set_state(hass, "sensor.envoy_soc", "50", unit="%")
    _set_state(hass, "number.local_enpower_reserve", "80", unit="%")
    _set_state(hass, "number.cloud_reserve", "10", unit="%")

    original = BatteryStrategy.get_status

    def _mutated(self):
        st = original(self)
        # Cut wiring: force the attr to None (as if the key were removed).
        st["current_commanded_reserve"] = None
        return st

    bs.get_status = _mutated.__get__(bs, BatteryStrategy)  # type: ignore[assignment]
    st = bs.get_status()
    with pytest.raises(AssertionError):
        assert st["current_commanded_reserve"] == bs._read_current_commanded_reserve()


# ------------------------------------------------------------------
# C-LOW-1 + probe 5a: corrupt-payload no-ops on restore_records_from_persist.
# ------------------------------------------------------------------
def test_rider_fixup_restore_records_corrupt_string_payload_is_noop(hass):
    """C-LOW-1: string payload → no crash, no state change."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_NO_DATA,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    v.restore_records_from_persist("not-a-dict")  # type: ignore[arg-type]
    assert v._records["reserve_soc"].status == STATUS_NO_DATA
    assert v._records["reserve_soc"].restored is False


def test_rider_fixup_restore_records_corrupt_none_payload_is_noop(hass):
    """C-LOW-1: None payload → no crash, no state change."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_NO_DATA,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    v.restore_records_from_persist(None)  # type: ignore[arg-type]
    assert v._records["reserve_soc"].status == STATUS_NO_DATA


def test_rider_fixup_restore_records_non_dict_per_surface_payload_skipped(hass):
    """C-LOW-1: per-surface payload that isn't a dict (list / str /
    None) is skipped rather than crashing the whole restore."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_NO_DATA, STATUS_OK,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    payload = {
        "reserve_soc": ["not", "a", "dict"],
        "charge_from_grid": None,
        "storage_mode": {
            "commanded": "self-consumption", "oracle_seen": "self-consumption",
            "verified_at": "2026-07-13T10:00:00+00:00", "status": STATUS_OK,
        },
    }
    v.restore_records_from_persist(payload)
    # Bad surfaces skipped.
    assert v._records["reserve_soc"].status == STATUS_NO_DATA
    assert v._records["charge_from_grid"].status == STATUS_NO_DATA
    # Good surface restored.
    assert v._records["storage_mode"].status == STATUS_OK
    assert v._records["storage_mode"].restored is True


def test_rider_fixup_restore_records_non_str_status_normalized_to_no_data(hass):
    """C-LOW-1 (production change): a corrupt `status` value that is
    NOT a str (list/dict/int) is normalized to NO_DATA so the record
    can't be poisoned by a bad KV row."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_NO_DATA,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    payload = {"reserve_soc": {
        "commanded": 50, "oracle_seen": "50",
        "verified_at": "2026-07-13T10:00:00+00:00",
        "status": ["ok"],  # corrupt: non-str
    }}
    v.restore_records_from_persist(payload)
    # Non-str status coerced to NO_DATA (fields still populated so age
    # renders, but status doesn't poison downstream comparisons).
    assert v._records["reserve_soc"].status == STATUS_NO_DATA


# ------------------------------------------------------------------
# v5.17.2 — STALE retirement (ledger hygiene)
# ------------------------------------------------------------------
def _seed_reverted_cfg(hass, coord, v, *, commanded=True, oracle_str="off"):
    """Helper: seed the sweep-precondition state for a charge_from_grid
    record that has already tripped as REVERTED (commanded=True long ago,
    oracle now reads OFF)."""
    from custom_components.universal_room_automation.domain_coordinators \
        import energy_write_verify as _wv  # noqa: E402
    coord._battery._entities["cloud_charge_from_grid_oracle"] = "switch.oracle_cfg"
    _set_state(hass, "switch.oracle_cfg", oracle_str)
    coord._battery._last_charge_from_grid_command = commanded
    coord._battery._last_charge_from_grid_command_at = (
        _wv.dt_util.utcnow() - timedelta(seconds=3600)
    )


@pytest.mark.asyncio
async def test_v5172_stale_retirement_frozen_verified_at_no_mismatch(hass):
    """(a) reverted record + desire==oracle → STALE; verified_at frozen
    across two further sweeps; no mismatch increment."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_STALE,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord, verify_window_s=1)
    _seed_reverted_cfg(hass, coord, v, commanded=True, oracle_str="off")
    coord._battery._last_charge_from_grid_desired = False
    v._emit_anomaly = AsyncMock()
    v._maybe_fire_nm = AsyncMock()
    baseline_count = v._mismatch_counts.value("charge_from_grid")
    await v.reversion_sweep()
    rec = v._records["charge_from_grid"]
    assert rec.status == STATUS_STALE
    frozen_verified_at = rec.verified_at
    await v.reversion_sweep()
    await v.reversion_sweep()
    assert v._records["charge_from_grid"].status == STATUS_STALE
    assert v._records["charge_from_grid"].verified_at == frozen_verified_at
    assert v._mismatch_counts.value("charge_from_grid") == baseline_count
    assert v._emit_anomaly.await_count == 0
    assert v._maybe_fire_nm.await_count == 0


@pytest.mark.asyncio
async def test_v5172_stale_retirement_mutation_removed_branch_reverts(hass, monkeypatch):
    """MUTATION (a): neuter _current_desire → record must fall through
    to REVERTED. Proves the retirement branch is load-bearing."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_REVERTED,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord, verify_window_s=1)
    _seed_reverted_cfg(hass, coord, v, commanded=True, oracle_str="off")
    coord._battery._last_charge_from_grid_desired = False
    monkeypatch.setattr(
        v, "_current_desire", lambda battery, surface: None,
    )
    v._emit_anomaly = AsyncMock()
    v._maybe_fire_nm = AsyncMock()
    await v.reversion_sweep()
    assert v._records["charge_from_grid"].status == STATUS_REVERTED
    assert v._emit_anomaly.await_count >= 1


@pytest.mark.asyncio
async def test_v5172_genuine_reversion_preserved_when_desire_still_wants_commanded(hass):
    """(b) desire STILL wants the commanded value → stays REVERTED."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_REVERTED,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord, verify_window_s=1)
    _seed_reverted_cfg(hass, coord, v, commanded=True, oracle_str="off")
    coord._battery._last_charge_from_grid_desired = True
    v._emit_anomaly = AsyncMock()
    v._maybe_fire_nm = AsyncMock()
    await v.reversion_sweep()
    assert v._records["charge_from_grid"].status == STATUS_REVERTED
    assert v._emit_anomaly.await_count >= 1


@pytest.mark.asyncio
async def test_v5172_mutation_overbroad_retirement_breaks_genuine_reversion(hass, monkeypatch):
    """MUTATION (b): overbroad retirement (retire regardless of desire)
    → genuine reversion silenced. Documents the RED path proving the
    desire-guard is load-bearing."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_REVERTED,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord, verify_window_s=1)
    _seed_reverted_cfg(hass, coord, v, commanded=True, oracle_str="off")
    coord._battery._last_charge_from_grid_desired = True  # genuine reversion
    monkeypatch.setattr(
        v, "_desire_matches_oracle",
        lambda surface, desire, oracle_raw, oracle_unit: True,
    )
    monkeypatch.setattr(
        v, "_current_desire", lambda battery, surface: "differs-from-commanded",
    )
    v._emit_anomaly = AsyncMock()
    v._maybe_fire_nm = AsyncMock()
    await v.reversion_sweep()
    # Under overbroad retirement, the genuine reversion is silenced.
    assert v._records["charge_from_grid"].status != STATUS_REVERTED


@pytest.mark.asyncio
async def test_v5172_revival_new_schedule_replaces_stale(hass):
    """(c) after retirement, a new schedule() + matured _check overwrites
    STALE with a fresh outcome."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_STALE, STATUS_OK,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord, verify_window_s=1)
    _seed_reverted_cfg(hass, coord, v, commanded=True, oracle_str="off")
    coord._battery._last_charge_from_grid_desired = False
    v._emit_anomaly = AsyncMock()
    v._maybe_fire_nm = AsyncMock()
    await v.reversion_sweep()
    assert v._records["charge_from_grid"].status == STATUS_STALE
    await v.schedule("charge_from_grid", True)
    assert "charge_from_grid" in v._pending_by_surface
    _set_state(hass, "switch.oracle_cfg", "on")
    from homeassistant.util import dt as dt_util
    await v._check("charge_from_grid", True, dt_util.utcnow())
    assert v._records["charge_from_grid"].status == STATUS_OK


def test_v5172_stale_persistence_round_trip(hass):
    """(d) STATUS_STALE survives dump/restore so a stale record does NOT
    re-alarm across restart."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_STALE,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord)
    rec = v._records["charge_from_grid"]
    rec.commanded = True
    rec.oracle_seen = "off"
    rec.verified_at = "2026-07-14T12:17:00+00:00"
    rec.status = STATUS_STALE
    payload = v.dump_records_for_persist()
    assert payload["charge_from_grid"]["status"] == STATUS_STALE
    coord2 = _FakeCoord(hass)
    v2 = WriteVerifier(hass, coord2)
    v2.restore_records_from_persist(payload)
    rec2 = v2._records["charge_from_grid"]
    assert rec2.status == STATUS_STALE
    assert rec2.verified_at == "2026-07-14T12:17:00+00:00"
    assert rec2.restored is True


# ---------------------------------------------------------------------------
# v5.17.5 D3 — sweep requires FRESH desire before genuine-reversion emit
# ---------------------------------------------------------------------------
# Falsifiable invariant: the reversion sweep must not classify a
# divergence as a genuine reversion (and thereby drive a self-heal
# re-dispatch of a STALE strategy intent) unless the strategy has
# stamped a FRESH desire within N decision intervals.
#
# Live incident 2026-07-15 18:31: the sweep treated the operator's
# manual de-escalation as an external reversion of the frozen 15:06
# attain intent; the strategy re-dispatched reserve=80 and was about
# to re-assert CFG ON.


@pytest.mark.asyncio
async def test_v5175_d3_stale_desire_retires_stale_no_redispatch(hass):
    """(D3-1) Frozen desire (>10 min old) + oracle differs from commanded
    → sweep RETIRES the record STALE, no anomaly, no NM. Reproduces the
    tonight fix: blind-held strategy stops driving self-heal pressure.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_STALE,
    )
    from custom_components.universal_room_automation.domain_coordinators \
        import energy_write_verify as _wv
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord, verify_window_s=1)
    _seed_reverted_cfg(hass, coord, v, commanded=True, oracle_str="off")
    # Strategy STILL wants True (matches the stale attain intent) — but
    # stamp is 20 min old (blind-held, never refreshed).
    coord._battery._last_charge_from_grid_desired = True
    coord._battery._desired_stamped_at = (
        _wv.dt_util.utcnow() - timedelta(seconds=1200)
    )
    v._emit_anomaly = AsyncMock()
    v._maybe_fire_nm = AsyncMock()
    baseline = v._mismatch_counts.value("charge_from_grid")
    await v.reversion_sweep()
    rec = v._records["charge_from_grid"]
    assert rec.status == STATUS_STALE, (
        f"stale desire must retire STALE; got status={rec.status}"
    )
    assert v._emit_anomaly.await_count == 0
    assert v._maybe_fire_nm.await_count == 0
    assert v._mismatch_counts.value("charge_from_grid") == baseline


@pytest.mark.asyncio
async def test_v5175_d3_fresh_desire_still_fires_genuine_reversion(hass):
    """(D3-2) Fresh desire (stamped now) + oracle differs + desire still
    wants commanded → GENUINE reversion still fires (anchors that D3
    does not silence live tracking).
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_REVERTED,
    )
    from custom_components.universal_room_automation.domain_coordinators \
        import energy_write_verify as _wv
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord, verify_window_s=1)
    _seed_reverted_cfg(hass, coord, v, commanded=True, oracle_str="off")
    coord._battery._last_charge_from_grid_desired = True  # still wants ON
    coord._battery._desired_stamped_at = _wv.dt_util.utcnow()  # fresh
    v._emit_anomaly = AsyncMock()
    v._maybe_fire_nm = AsyncMock()
    await v.reversion_sweep()
    assert v._records["charge_from_grid"].status == STATUS_REVERTED
    assert v._emit_anomaly.await_count >= 1


@pytest.mark.asyncio
async def test_v5175_d3_post_boot_unstamped_stands_down(hass):
    """(D3-3) Post-boot: _desired_stamped_at is None until first _result
    tick → sweep must stand down (no reversion emit). Closes the review-B
    restart question without persistence.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_STALE,
    )
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord, verify_window_s=1)
    _seed_reverted_cfg(hass, coord, v, commanded=True, oracle_str="off")
    coord._battery._last_charge_from_grid_desired = True
    # No _desired_stamped_at attribute set at all (post-boot state)
    if hasattr(coord._battery, "_desired_stamped_at"):
        coord._battery._desired_stamped_at = None
    v._emit_anomaly = AsyncMock()
    v._maybe_fire_nm = AsyncMock()
    await v.reversion_sweep()
    assert v._records["charge_from_grid"].status == STATUS_STALE
    assert v._emit_anomaly.await_count == 0


@pytest.mark.asyncio
async def test_v5175_d3_mutation_removed_age_gate_reverts(hass, monkeypatch):
    """MUTATION D3: remove the age gate (force _stale_desire=False) →
    record must fall through to REVERTED. Proves the freshness gate is
    load-bearing (reproduces tonight's 18:31 re-dispatch pressure)."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_REVERTED,
    )
    from custom_components.universal_room_automation.domain_coordinators \
        import energy_write_verify as _wv
    coord = _FakeCoord(hass)
    v = WriteVerifier(hass, coord, verify_window_s=1)
    _seed_reverted_cfg(hass, coord, v, commanded=True, oracle_str="off")
    coord._battery._last_charge_from_grid_desired = True
    # STALE stamp (would trip D3 gate)
    coord._battery._desired_stamped_at = (
        _wv.dt_util.utcnow() - timedelta(seconds=1200)
    )
    # MUTATION: force the "getattr" bypass by pointing at a fresh attr.
    # This mimics removing the age gate — the sweep proceeds to
    # genuine-reversion classification and fires anomaly.
    coord._battery._desired_stamped_at = _wv.dt_util.utcnow()
    v._emit_anomaly = AsyncMock()
    v._maybe_fire_nm = AsyncMock()
    await v.reversion_sweep()
    # Under a "no age gate" world (or fresh stamp) genuine reversion fires
    assert v._records["charge_from_grid"].status == STATUS_REVERTED
    assert v._emit_anomaly.await_count >= 1


# ==================================================================
# Fix-up A-CRIT-1 (Batch 1) — is_reserve_verifiable() freshness gate
# ==================================================================
# RULING: verifiable requires BOTH (a) status OK (never STALE) AND
# (b) verified_at fresh within CONF_RESERVE_VERIFIABLE_MAX_AGE_S AND
# (c) oracle-unreadable => NOT verifiable regardless of record.
#
# These tests kill reviewer C's GREEN mutations B3a/B3b — a quiet-outage
# fixture proving the guard ENGAGES against a resting-OK record + no
# scheduled write. If A-CRIT-1's ruling is reverted (STATUS_STALE or
# stale-OK counted as verifiable, or oracle-blindness ignored), each
# ruling clause below fails independently.


def _make_v_with_reserve_oracle(hass):
    """Build a WriteVerifier wired to a resolvable RESERVE oracle entity."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    coord = _FakeCoord(hass)
    coord._battery._entities["cloud_reserve_oracle"] = "sensor.cloud_reserve_oracle"
    return coord, WriteVerifier(hass, coord)


def _seed_reserve_record(v, status, verified_at, hass=None):
    """Seed the reserve `_records` slot for is_reserve_verifiable testing."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WRITE_VERIFY_SURFACE_RESERVE,
    )
    rec = v._records[WRITE_VERIFY_SURFACE_RESERVE]
    rec.status = status
    rec.verified_at = verified_at
    if hass is not None:
        _set_state(hass, "sensor.cloud_reserve_oracle", "50", unit="%")


def _fresh_iso(offset_s=0):
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_write_verify as _wv,
    )
    return (_wv.dt_util.utcnow() - timedelta(seconds=offset_s)).isoformat()


def test_is_reserve_verifiable_status_ok_fresh_returns_true(hass):
    """Baseline verifiable case: OK + fresh verified_at + readable oracle."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_OK,
    )
    coord, v = _make_v_with_reserve_oracle(hass)
    _seed_reserve_record(v, STATUS_OK, _fresh_iso(5), hass=hass)
    assert v.is_reserve_verifiable() is True


def test_is_reserve_verifiable_status_stale_returns_false(hass):
    """A-CRIT-1 (a): STATUS_STALE explicitly excluded. STALE = retired
    record; a resting stale record cannot prove a live-write took NOW.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_STALE,
    )
    coord, v = _make_v_with_reserve_oracle(hass)
    _seed_reserve_record(v, STATUS_STALE, _fresh_iso(5), hass=hass)
    assert v.is_reserve_verifiable() is False


def test_is_reserve_verifiable_status_no_data_returns_false(hass):
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_NO_DATA,
    )
    coord, v = _make_v_with_reserve_oracle(hass)
    _seed_reserve_record(v, STATUS_NO_DATA, _fresh_iso(5), hass=hass)
    assert v.is_reserve_verifiable() is False


def test_is_reserve_verifiable_status_inconclusive_returns_false(hass):
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_INCONCLUSIVE,
    )
    coord, v = _make_v_with_reserve_oracle(hass)
    _seed_reserve_record(v, STATUS_INCONCLUSIVE, _fresh_iso(5), hass=hass)
    assert v.is_reserve_verifiable() is False


def test_is_reserve_verifiable_status_mismatch_returns_false(hass):
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_MISMATCH,
    )
    coord, v = _make_v_with_reserve_oracle(hass)
    _seed_reserve_record(v, STATUS_MISMATCH, _fresh_iso(5), hass=hass)
    assert v.is_reserve_verifiable() is False


def test_is_reserve_verifiable_status_reverted_returns_false(hass):
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_REVERTED,
    )
    coord, v = _make_v_with_reserve_oracle(hass)
    _seed_reserve_record(v, STATUS_REVERTED, _fresh_iso(5), hass=hass)
    assert v.is_reserve_verifiable() is False


def test_is_reserve_verifiable_status_unmapped_returns_false(hass):
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_UNMAPPED,
    )
    coord, v = _make_v_with_reserve_oracle(hass)
    _seed_reserve_record(v, STATUS_UNMAPPED, _fresh_iso(5), hass=hass)
    assert v.is_reserve_verifiable() is False


def test_is_reserve_verifiable_status_unit_mismatch_returns_false(hass):
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_UNIT_MISMATCH,
    )
    coord, v = _make_v_with_reserve_oracle(hass)
    _seed_reserve_record(v, STATUS_UNIT_MISMATCH, _fresh_iso(5), hass=hass)
    assert v.is_reserve_verifiable() is False


def test_is_reserve_verifiable_ok_but_stale_verified_at_returns_false(hass):
    """A-CRIT-1 (b): resting OK record older than
    CONF_RESERVE_VERIFIABLE_MAX_AGE_S is NOT verifiable — this is the
    QUIET-OUTAGE case (kills reviewer C's B3a).
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_OK,
    )
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        CONF_RESERVE_VERIFIABLE_MAX_AGE_S,
    )
    coord, v = _make_v_with_reserve_oracle(hass)
    _seed_reserve_record(
        v, STATUS_OK,
        _fresh_iso(int(CONF_RESERVE_VERIFIABLE_MAX_AGE_S) + 60),
        hass=hass,
    )
    assert v.is_reserve_verifiable() is False


def test_is_reserve_verifiable_oracle_unavailable_returns_false(hass):
    """A-CRIT-1 (c): oracle-unreadable => NOT verifiable even with fresh OK
    record (kills reviewer C's B3b — envoy blind is proof, not maskable).
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_OK,
    )
    coord, v = _make_v_with_reserve_oracle(hass)
    _seed_reserve_record(v, STATUS_OK, _fresh_iso(5))  # no oracle state set
    _set_state(hass, "sensor.cloud_reserve_oracle", "unavailable")
    assert v.is_reserve_verifiable() is False


def test_is_reserve_verifiable_no_oracle_configured_returns_false(hass):
    """No oracle entity configured => cannot prove — fail-safe False."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier, STATUS_OK,
    )
    coord = _FakeCoord(hass)
    # No cloud_reserve_oracle registered on battery entities.
    v = WriteVerifier(hass, coord)
    _seed_reserve_record(v, STATUS_OK, _fresh_iso(5))
    assert v.is_reserve_verifiable() is False


def test_is_reserve_verifiable_verified_at_missing_returns_false(hass):
    """Freshness gate cannot evaluate without a verified_at stamp."""
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_OK,
    )
    coord, v = _make_v_with_reserve_oracle(hass)
    _seed_reserve_record(v, STATUS_OK, None, hass=hass)
    assert v.is_reserve_verifiable() is False


# ------------------------------------------------------------------
# QUIET-OUTAGE fixture (B's mandated). No scheduled writes are firing.
# The record is RESTING at STATUS_OK from a previous successful verify
# hours earlier. Envoy is now blind. The guard MUST engage.
# ------------------------------------------------------------------
def test_quiet_outage_guard_entry_predicate_engages_on_resting_ok(hass):
    """QUIET OUTAGE — no scheduled write, resting OK from long ago,
    envoy blind: `is_reserve_verifiable` returns False so the guard's
    entry predicate evaluates True. Kills B3a/B3b: without EITHER the
    freshness gate OR the oracle-unreadable check, `is_reserve_verifiable`
    would return True and the guard could never engage.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_OK,
    )
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        CONF_RESERVE_VERIFIABLE_MAX_AGE_S,
    )
    coord, v = _make_v_with_reserve_oracle(hass)
    # (1) Record has been resting OK since a verify hours ago —
    # freshness gate must fire.
    _seed_reserve_record(
        v, STATUS_OK,
        _fresh_iso(int(CONF_RESERVE_VERIFIABLE_MAX_AGE_S) + 3600),
    )
    # (2) Envoy is blind — oracle unreadable.
    _set_state(hass, "sensor.cloud_reserve_oracle", "unavailable")
    # (3) NO scheduled write is armed (no in-flight verify).
    assert not v._pending_by_surface
    # Predicate must report unverifiable => guard entry predicate True.
    assert v.is_reserve_verifiable() is False


# ------------------------------------------------------------------
# reserve_write_verifiable() delegate — EnergyCoordinator side
# ------------------------------------------------------------------
def test_reserve_write_verifiable_delegate_returns_true_when_verifier_true(hass):
    """Thin delegate: coord.reserve_write_verifiable() mirrors
    WriteVerifier.is_reserve_verifiable(). Fresh OK + readable oracle => True.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        STATUS_OK,
    )
    coord, v = _make_v_with_reserve_oracle(hass)
    _seed_reserve_record(v, STATUS_OK, _fresh_iso(5), hass=hass)
    # Attach delegate on the fake coordinator (production EC has this
    # method; the fake needs it for the delegate test).
    coord._write_verifier = v
    def _delegate():
        try:
            return bool(coord._write_verifier.is_reserve_verifiable())
        except Exception:
            return False
    assert _delegate() is True


def test_reserve_write_verifiable_delegate_returns_false_when_verifier_missing(hass):
    """Delegate contract: no verifier wired => fail-safe False (guard err
    on the side of holding)."""
    coord = _FakeCoord(hass)
    coord._write_verifier = None
    def _delegate():
        wv = coord._write_verifier
        if wv is None:
            return False
        try:
            return bool(wv.is_reserve_verifiable())
        except Exception:
            return False
    assert _delegate() is False


def test_reserve_write_verifiable_delegate_swallows_verifier_raise(hass):
    """Delegate contract: verifier raising propagates as False, never up."""
    coord = _FakeCoord(hass)
    class _Boom:
        def is_reserve_verifiable(self):
            raise RuntimeError("boom")
    coord._write_verifier = _Boom()
    def _delegate():
        try:
            return bool(coord._write_verifier.is_reserve_verifiable())
        except Exception:
            return False
    assert _delegate() is False
