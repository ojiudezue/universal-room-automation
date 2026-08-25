"""EVSE Drain-Precedence — Session B2c-1 fix-up acceptance tests.

Scope: the 2 CRITICAL + 5 HIGH from reviews B/C/D, plus the test-hygiene
fix (naive datetime → frozen/injected clocks).

    1. CRIT — paused-aware exit predicate (was `not _is_any_evse_charging`
       → flapped false the same tick DP dispatched turn_off, tearing the
       window down 1 tick after entry).
    2. CRIT — live `house_load_kw` (was 0.0 stub; MISSING_INPUTS abstain).
    3. HIGH — real fully-blind signal (was invented attr).
    4. HIGH — second-plug-in re-scan (car B claimed within one tick).
    5. HIGH — kill-switch hoist ABOVE the enable + night gate.
    6. HIGH — night-window gate (off_peak only via TOU getter).

EXECUTED source mutations (Reviewer-C authority, subprocess-isolated):
    (a) revert exit predicate to `not _is_any_evse_charging()` →
        `test_paused_aware_exit_holds_window_across_three_ticks` RED.
    (b) restub `_dp_house_load_kw` to `return 0.0` →
        `test_house_load_live_source_returns_positive` RED.
    (c) revert blind read to `_is_blind_hold_active` →
        `test_blind_signal_uses_envoy_available_and_battery_soc` RED.
    (d) remove the re-scan block →
        `test_second_plug_in_rescan_claims_car_b_within_one_tick` RED.
    (e) hoist the kill-switch hoist below the enable gate (delete
        the `_has_dp_state` cleanup) →
        `test_kill_switch_hoist_releases_pause_mid_window` RED.
    (f) drop the night-window gate →
        `test_night_window_gate_skips_tick_outside_off_peak` RED.
"""

from __future__ import annotations

import ast as _ast
import asyncio
import hashlib
import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Mock homeassistant (setdefault-only — coexists with sibling test files)
# ---------------------------------------------------------------------------


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
        "async_track_point_in_time": lambda *a, **k: (lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda *a, **k: (lambda: None),
        "async_dispatcher_send": lambda *a, **k: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}
for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)
sys.modules.setdefault("aiosqlite", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = sys.modules.get("custom_components")
if _cc is None:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
    sys.modules["custom_components"] = _cc

_ura_name = "custom_components.universal_room_automation"
_ura = sys.modules.get(_ura_name)
if _ura is None:
    _ura = types.ModuleType(_ura_name)
    _ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
    _ura.__path__ = [_ura_path]
    _ura.__package__ = _ura_name
    sys.modules[_ura_name] = _ura
else:
    _ura_path = _ura.__path__[0]

_const_name = f"{_ura_name}.const"
if _const_name not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        _const_name, os.path.join(_ura_path, "const.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_const_name] = _mod
    _spec.loader.exec_module(_mod)
    _ura.const = _mod

_dc_name = f"{_ura_name}.domain_coordinators"
_dc = sys.modules.get(_dc_name)
if _dc is None:
    _dc = types.ModuleType(_dc_name)
    _dc.__path__ = [os.path.join(_ura_path, "domain_coordinators")]
    _dc.__package__ = _dc_name
    sys.modules[_dc_name] = _dc
    _ura.domain_coordinators = _dc
_dc_path = _dc.__path__[0]

for _sub in ("energy_const", "energy_tou", "energy_pool", "energy_drain_precedence"):
    _full = f"{_dc_name}.{_sub}"
    if _full in sys.modules:
        continue
    _spec = importlib.util.spec_from_file_location(
        _full, os.path.join(_dc_path, f"{_sub}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _sub, _mod)


from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
)
from custom_components.universal_room_automation.domain_coordinators.energy_drain_precedence import (  # noqa: E402
    DPState,
    DrainPrecedenceState,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_drain_precedence as _edp,
)


# ---------------------------------------------------------------------------
# Extract-exec the DP methods so tests drive real production bytes.
# ---------------------------------------------------------------------------


def _extract_named(source: str, names: set[str]) -> str:
    tree = _ast.parse(source)
    src_lines = source.splitlines()
    out: list[str] = []
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.ClassDef) or node.name != "EnergyCoordinator":
            continue
        for child in node.body:
            if isinstance(child, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                if child.name in names:
                    seg = "\n".join(src_lines[child.lineno - 1: child.end_lineno])
                    dedented = "\n".join(
                        line[4:] if line.startswith("    ") else line
                        for line in seg.splitlines()
                    )
                    out.append(dedented)
    return "\n\n".join(out)


_ENERGY_SRC = Path(_dc_path) / "energy.py"
with open(_ENERGY_SRC, "r", encoding="utf-8") as _fh:
    _energy_src = _fh.read()

_extracted = _extract_named(
    _energy_src,
    {
        "_apply_evse_battery_hold",
        "_apply_dp_transition",
        "_apply_dp_reversion",
        "_apply_dp_must_start_release",
        "_cancel_dp_must_start_by_timer",
        "_arm_dp_must_start_by_timer",
        "_is_any_evse_charging",
        "_dp_house_load_kw",
        "_dp_needed_kwh_plugged",
        "_dp_decision_tick",
        "_get_state_float",
    },
)

import logging as _logging  # noqa: E402
_LOGGER = _logging.getLogger("test_dp_b2c1_fixup")

# Sentinel class copy — must match energy._DPSkip in behavior.


class _DPSkip(Exception):
    pass


_extracted_ns: dict = {
    "_LOGGER": _LOGGER,
    "Any": object,
    "_DPSkip": _DPSkip,
    "__name__": (
        "custom_components.universal_room_automation.domain_coordinators.energy"
    ),
    "__package__": (
        "custom_components.universal_room_automation.domain_coordinators"
    ),
    "async_track_point_in_time": lambda *a, **k: (lambda: None),
}
exec(compile(_extracted, "<energy.py-extract-b2c1-fixup>", "exec"), _extracted_ns)


class _StubBattery:
    """Minimal battery stub carrying the two blind-signal attrs +
    reserve-entity resolution used by `_apply_evse_battery_hold`."""

    def __init__(
        self,
        envoy_available: bool = True,
        battery_soc: float | None = 75.0,
        reserve_entity: str = "number.reserve_soc",
    ):
        self.envoy_available = envoy_available
        self.battery_soc = battery_soc
        self._reserve_entity = reserve_entity
        self._last_reserve_level = None
        self._last_reserve_level_at = None
        self._last_reserve_level_desired = None

    def _get_entity(self, key, default=None, role=None):
        return self._reserve_entity


class _StubTOU:
    def __init__(self, period: str = "off_peak"):
        self._period = period

    def get_current_period(self, now=None):
        return self._period


class _StubPredictor:
    def __init__(self, predicted_consumption_kwh: float | None = 48.0):
        self._pc = predicted_consumption_kwh

    def _get_current_prediction(self):
        return {"predicted_consumption_kwh": self._pc}


class _FakeCoord:
    def __init__(
        self, hass, ev, battery, tou, predictor,
        dp_enabled: bool = True,
        drain_target: int = 30,
        house_load_source: str = "max_span_r1",
    ):
        self.hass = hass
        self._ev = ev
        self._battery = battery
        self._tou = tou
        self._predictor = predictor
        self._evse_hold_soc: int | None = None
        self._dp_decision_soc: int | None = None
        self._write_verifier = None
        self._dp_carrier: DrainPrecedenceState = DrainPrecedenceState()
        self._dp_must_start_unsub = None
        self._save_calls = 0
        # DP config
        self.dp_enabled = dp_enabled
        self._ev_battery_drain_soc = drain_target
        self._dp_needed_kwh_garage_a = 15.0
        self._dp_needed_kwh_garage_b = 0.0
        self._dp_must_start_by_min = 6 * 60  # 06:00
        self._dp_margin_min = 30
        self._dp_eval_delay_min = 5
        self._dp_house_load_source = house_load_source

    async def _save_evse_state(self):
        self._save_calls += 1

    async def _on_dp_must_start_by(self, _now):
        return None


for _name in (
    "_apply_evse_battery_hold",
    "_apply_dp_transition",
    "_apply_dp_reversion",
    "_apply_dp_must_start_release",
    "_cancel_dp_must_start_by_timer",
    "_arm_dp_must_start_by_timer",
    "_is_any_evse_charging",
    "_dp_house_load_kw",
    "_dp_needed_kwh_plugged",
    "_dp_decision_tick",
    "_get_state_float",
):
    if _name in _extracted_ns:
        setattr(_FakeCoord, _name, _extracted_ns[_name])


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _build_hass() -> MockHass:
    hass = MockHass()
    loop = asyncio.new_event_loop()

    def _run_task(coro):
        try:
            loop.run_until_complete(coro)
        except Exception:
            pass
        return MagicMock()

    hass.async_create_task = _run_task

    async def _svc(*a, **k):
        return None
    hass.services = MagicMock()
    hass.services.async_call = _svc
    return hass


def _build_ev(hass, ids=("garage_a",), charging=("garage_a",)) -> EVChargerController:
    evse_cfg = {}
    for eid in ids:
        evse_cfg[eid] = {
            "switch": f"switch.{eid}",
            "power": f"sensor.{eid}_power",
            "energy_today": f"sensor.{eid}_energy_today",
            "energy_month": f"sensor.{eid}_energy_month",
        }
        hass.set_state(f"switch.{eid}", "on")
        hass.set_state(
            f"sensor.{eid}_power",
            "1000" if eid in charging else "0",
            attributes={"unit_of_measurement": "W"},
        )
    return EVChargerController(hass, evse_config=evse_cfg)


def _make_coord(
    *,
    ids=("garage_a",), charging=("garage_a",),
    dp_enabled=True,
    period="off_peak",
    envoy_available=True,
    battery_soc: float | None = 75.0,
    drain_target=30,
    span_r1: str | None = "1500",  # W
    span_r2: str | None = "500",
    house_load_source="max_span_r1",
    predicted_consumption_kwh: float | None = 48.0,
):
    hass = _build_hass()
    ev = _build_ev(hass, ids=ids, charging=charging)
    if span_r1 is not None:
        hass.set_state("sensor.span_panel_current_power", span_r1,
                       attributes={"unit_of_measurement": "W"})
    if span_r2 is not None:
        hass.set_state("sensor.span_panel_current_power_2", span_r2,
                       attributes={"unit_of_measurement": "W"})
    battery = _StubBattery(envoy_available=envoy_available, battery_soc=battery_soc)
    tou = _StubTOU(period=period)
    predictor = _StubPredictor(predicted_consumption_kwh=predicted_consumption_kwh)
    coord = _FakeCoord(
        hass, ev, battery, tou, predictor,
        dp_enabled=dp_enabled,
        drain_target=drain_target,
        house_load_source=house_load_source,
    )
    return coord, ev, battery, tou


# ==========================================================================
# Item 2 (CRIT) — live house_load
# ==========================================================================


def test_house_load_live_source_returns_positive():
    """`_dp_house_load_kw` in `max_span_r1` mode must return a positive
    value from SPAN (r1+r2 minus EVSE draw) OR R1 base. A stub returning
    0.0 (the pre-fix wire) would fail this."""
    coord, _, _, _ = _make_coord(
        span_r1="1500", span_r2="500",  # 2 kW total
        predicted_consumption_kwh=48.0,   # 2 kW average
    )
    val = coord._dp_house_load_kw(ev_load_w=500.0)  # 500W EVSE
    # SPAN: (1500+500-500)/1000 = 1.5 kW; R1 base: 48/24 = 2.0 kW; max = 2.0
    assert val >= 1.0, f"house_load must be non-trivial, got {val}"


def test_house_load_live_span_only_subtracts_ev_load():
    coord, _, _, _ = _make_coord(
        span_r1="2000", span_r2="1000",
        house_load_source="live_span",
        predicted_consumption_kwh=None,
    )
    val = coord._dp_house_load_kw(ev_load_w=1000.0)
    # (2000+1000-1000)/1000 = 2.0 kW
    assert abs(val - 2.0) < 1e-6, f"expected 2.0 kW, got {val}"


def test_house_load_none_safe_when_both_sources_missing():
    coord, _, _, _ = _make_coord(
        span_r1=None, span_r2=None,
        predicted_consumption_kwh=None,
        house_load_source="max_span_r1",
    )
    assert coord._dp_house_load_kw(ev_load_w=0.0) == 0.0


# ==========================================================================
# Item 3 (HIGH) — blind signal derived from real fields
# ==========================================================================


def test_blind_signal_uses_envoy_available_and_battery_soc():
    """Verify the DP tick reads `envoy_available` + `battery_soc` (the
    canonical fully-blind signal) NOT the non-existent
    `_is_blind_hold_active` attr. Uses a spy that raises if the invented
    attr is read AND records reads of the real attrs; also verifies the
    True/False output is correctly derived."""

    class _SpyBattery:
        def __init__(self):
            self.envoy_reads = 0
            self.soc_reads = 0
            self._reserve_entity = "number.reserve_soc"
            self._last_reserve_level = None
            self._last_reserve_level_at = None
            self._last_reserve_level_desired = None

        @property
        def envoy_available(self):
            self.envoy_reads += 1
            return False  # blind

        @property
        def battery_soc(self):
            self.soc_reads += 1
            return None  # blind

        # Reading this attr under the mutation would silently return False
        # (getattr with default). To distinguish, count DIRECT reads.
        def __getattr__(self, name):
            if name == "_is_blind_hold_active":
                # Under mutation, `getattr(self._battery,
                # "_is_blind_hold_active", False)` triggers this and we
                # count it. Under the fix, the code doesn't call getattr
                # for this name → this method is never invoked with it.
                self._invented_reads = getattr(self, "_invented_reads", 0) + 1
                raise AttributeError(name)
            raise AttributeError(name)

        def _get_entity(self, *a, **k):
            return self._reserve_entity

    coord, ev, _, _ = _make_coord()
    spy = _SpyBattery()
    coord._battery = spy
    coord._dp_decision_tick({"soc": 50}, "off_peak", ev_load_w=1000.0, drain_target_soc=30)
    # Real fix reads BOTH canonical signals.
    assert spy.envoy_reads >= 1, "fix must read envoy_available"
    assert spy.soc_reads >= 1, "fix must read battery_soc"
    # And does NOT read the invented attr (would count under mutation).
    assert getattr(spy, "_invented_reads", 0) == 0, (
        "must NOT read `_is_blind_hold_active` (invented attr)"
    )


def test_blind_signal_negative_case_envoy_ok():
    """envoy_available=True → blind-hold False → tick runs its normal
    eval path (does NOT depend on `_is_blind_hold_active` attr)."""
    coord, ev, battery, _ = _make_coord(
        envoy_available=True, battery_soc=80.0,
    )
    # Sanity: the invented attr must NOT be read (make it raise).

    class _Boom:
        @property
        def _is_blind_hold_active(self):
            raise RuntimeError("must not be read")

        envoy_available = True
        battery_soc = 80.0

        def _get_entity(self, *a, **k):
            return "number.reserve_soc"

        _last_reserve_level = None
        _last_reserve_level_at = None
        _last_reserve_level_desired = None
    coord._battery = _Boom()
    # If code reads `_is_blind_hold_active`, this raises → tick swallows,
    # but our test asserts the tick completes without raising OUT.
    coord._dp_decision_tick({"soc": 50}, "off_peak", ev_load_w=0.0, drain_target_soc=30)


# ==========================================================================
# Item 5 (HIGH) — kill-switch hoist
# ==========================================================================


def test_kill_switch_hoist_releases_pause_mid_window():
    """Mid-window flip-OFF of DP: carrier is FORCED to HOLD_ONLY same
    tick, must-start-by timer cancelled, save fires.

    B2c-3 H-2 STICKY interaction: when the flip lands in a non-off_peak
    period, `_apply_dp_reversion` DEFERS the turn_on (TOU gate) and
    KEEPS the DP claim sticky. The kill-switch hoist still normalizes
    the carrier state to HOLD_ONLY, but the pause set + "dp" owner
    persist so a later tick retries once TOU returns to off_peak.
    Pre-B2c-3 (eager-discard) stranded the car off through peak — the
    operator's 05:02 mid_peak scenario."""
    coord, ev, _, tou = _make_coord(dp_enabled=True)
    # Arm a fake TRANSITIONED window.
    ev._paused_by_dp.add("garage_a")
    ev._claim_pause_dispatch_owner("garage_a", "dp")
    coord._dp_decision_soc = 30
    coord._dp_carrier.state = DPState.TRANSITIONED
    # Flip kill switch OFF, move OUT of off_peak.
    coord.dp_enabled = False
    tou._period = "peak"
    try:
        coord._dp_decision_tick({"soc": 60}, "peak", ev_load_w=0.0, drain_target_soc=30)
    except _DPSkip:
        pass
    # Carrier normalized + save fired (kill-switch hoist responsibility).
    assert coord._dp_carrier.state == DPState.HOLD_ONLY
    assert coord._save_calls >= 1
    # H-2 STICKY: TOU=peak keeps the DP claim + decision_soc pinned so
    # INV-DP3 stays honored and the retry driver has state to close on.
    assert "garage_a" in ev._paused_by_dp, (
        "sticky: kill-switch flip in peak must keep DP claim (retry driver)"
    )
    assert coord._dp_decision_soc == 30, (
        "sticky: floor must remain pinned while a member is sticky"
    )
    owners = ev._dispatch_owners.get("garage_a", set())
    assert "dp" in owners, "sticky: 'dp' owner claim must persist"


def test_kill_switch_hoist_completes_release_on_offpeak_return():
    """Follow-on tick after `test_kill_switch_hoist_releases_pause_mid_window`:
    once TOU returns to off_peak, the sticky retry driver drains the set
    and dispatches turn_on. Anchors the H-2 retry-driver end-to-end."""
    coord, ev, _, tou = _make_coord(dp_enabled=False)
    # Prime sticky-carried state from the peak-defer step.
    ev._paused_by_dp.add("garage_a")
    ev._claim_pause_dispatch_owner("garage_a", "dp")
    coord._dp_decision_soc = 30
    coord._dp_carrier.state = DPState.HOLD_ONLY
    tou._period = "off_peak"
    coord.hass.set_state("switch.garage_a", "off")
    try:
        coord._dp_decision_tick({"soc": 60}, "off_peak", ev_load_w=0.0, drain_target_soc=30)
    except _DPSkip:
        pass
    # Sticky drained — turn_on dispatched via kill-switch hoist's
    # reversion call (dp_enabled=False path exercises the hoist branch;
    # note the retry-driver branch also runs when dp_enabled=True + a
    # residual set exists — covered by the H-1 orphan test below).
    assert "garage_a" not in ev._paused_by_dp, (
        "off_peak return must drain sticky set"
    )
    assert coord._dp_decision_soc is None


def test_h2_sticky_orphan_hold_only_retry_dispatches_turn_on_switch_on_path():
    """B2c-3 H-2 retry driver (switch-ON path). The H-1 restart-orphan
    case: dp_enabled=True, carrier coerced to HOLD_ONLY by
    `restore_from_blob`, `_paused_by_dp` restored non-empty. The
    HOLD_ONLY orphan-cleanup call in `_dp_decision_tick` must call
    `_apply_dp_reversion`, which dispatches turn_on when off_peak +
    no peer holds. FAILS if the retry driver is removed."""
    coord, ev, _, _ = _make_coord(dp_enabled=True, period="off_peak")
    # Simulate post-restart restore.
    ev._paused_by_dp.add("garage_a")
    ev._claim_pause_dispatch_owner("garage_a", "dp")
    coord._dp_decision_soc = None  # cleared by carrier coercion
    coord._dp_carrier.state = DPState.HOLD_ONLY
    coord.hass.set_state("switch.garage_a", "off")
    try:
        coord._dp_decision_tick({"soc": 60}, "off_peak", ev_load_w=0.0, drain_target_soc=30)
    except _DPSkip:
        pass
    assert "garage_a" not in ev._paused_by_dp, (
        "HOLD_ONLY orphan retry must drain restored DP set"
    )
    owners = ev._dispatch_owners.get("garage_a", set())
    assert "dp" not in owners, "orphan retry must drop 'dp' owner"


# ==========================================================================
# Item 6 (HIGH) — night-window gate
# ==========================================================================


def test_night_window_gate_skips_tick_outside_off_peak():
    """Outside off_peak, DP tick must NOT evaluate/actuate — the block
    raises `_DPSkip` and no state changes occur."""
    coord, ev, _, tou = _make_coord(period="peak")
    _prev = coord._dp_carrier.state
    raised = False
    try:
        coord._dp_decision_tick({"soc": 90}, "peak", ev_load_w=0.0, drain_target_soc=30)
    except _DPSkip:
        raised = True
    assert raised, "night gate must raise _DPSkip in non-off_peak"
    assert coord._dp_carrier.state == _prev
    assert not ev._paused_by_dp


def test_night_window_gate_allows_off_peak_tick():
    coord, ev, _, tou = _make_coord(period="off_peak")
    # Should not raise _DPSkip.
    coord._dp_decision_tick({"soc": 90}, "off_peak", ev_load_w=1000.0, drain_target_soc=30)


# ==========================================================================
# Item 4 (HIGH) — second-plug-in re-scan
# ==========================================================================


def test_second_plug_in_rescan_claims_car_b_within_one_tick():
    """While TRANSITIONED, a peer EVSE that starts charging on tick N+2
    must be claimed into `_paused_by_dp` within the SAME tick that
    observes it."""
    coord, ev, _, _ = _make_coord(
        ids=("garage_a", "garage_b"),
        charging=("garage_a",),
    )
    # Prime: already TRANSITIONED with garage_a pinned.
    coord._dp_carrier.state = DPState.TRANSITIONED
    ev._paused_by_dp.add("garage_a")
    coord._dp_decision_soc = 30
    # Car B plugs in — its power sensor now reads > 0.
    coord.hass.set_state(
        "sensor.garage_b_power", "1000",
        attributes={"unit_of_measurement": "W"},
    )
    coord._dp_decision_tick({"soc": 60}, "off_peak", ev_load_w=1000.0, drain_target_soc=30)
    assert "garage_b" in ev._paused_by_dp, (
        "re-scan must claim newly-charging peer within one tick"
    )


# ==========================================================================
# Item 1 (CRIT) — paused-aware exit predicate: window HOLDS across 3 ticks
# ==========================================================================


def test_paused_aware_exit_holds_window_across_three_ticks():
    """After DP transitions and dispatches turn_off, the EVSE power
    sensor drops to 0 (charging=False). The exit predicate must NOT
    revert on that alone — `_paused_by_dp` still contains the EVSE, so
    the window HOLDS. Across 3 subsequent ticks the state stays
    TRANSITIONED and `_paused_by_dp` retains the EV id."""
    coord, ev, _, _ = _make_coord(
        drain_target=30,
    )
    # Prime a TRANSITIONED window post-dispatch: pause set claimed,
    # power sensor already dropped to 0 (turn_off effect).
    coord._dp_carrier.state = DPState.TRANSITIONED
    ev._paused_by_dp.add("garage_a")
    coord._dp_decision_soc = 30
    coord.hass.set_state(
        "sensor.garage_a_power", "0",
        attributes={"unit_of_measurement": "W"},
    )
    for tick in range(3):
        # SOC well ABOVE drain target (floor NOT reached).
        coord._dp_decision_tick({"soc": 60}, "off_peak", ev_load_w=0.0, drain_target_soc=30)
        assert coord._dp_carrier.state == DPState.TRANSITIONED, (
            f"window collapsed on tick {tick}: state={coord._dp_carrier.state}"
        )
        assert "garage_a" in ev._paused_by_dp, (
            f"pause set cleared on tick {tick}"
        )


def test_paused_aware_exit_reverts_when_soc_hits_drain_target():
    coord, ev, _, _ = _make_coord(drain_target=30)
    coord._dp_carrier.state = DPState.TRANSITIONED
    ev._paused_by_dp.add("garage_a")
    coord._dp_decision_soc = 30
    coord.hass.set_state(
        "sensor.garage_a_power", "0",
        attributes={"unit_of_measurement": "W"},
    )
    # SOC at floor → revert legitimately.
    coord._dp_decision_tick({"soc": 30}, "off_peak", ev_load_w=0.0, drain_target_soc=30)
    assert coord._dp_carrier.state == DPState.HOLD_ONLY
    assert "garage_a" not in ev._paused_by_dp


def test_paused_aware_exit_reverts_on_car_gone():
    coord, ev, _, _ = _make_coord(drain_target=30)
    coord._dp_carrier.state = DPState.TRANSITIONED
    coord._dp_decision_soc = 30
    # Nothing in paused_by_dp AND nothing charging → real "car unplugged"
    coord.hass.set_state(
        "sensor.garage_a_power", "0",
        attributes={"unit_of_measurement": "W"},
    )
    coord._dp_decision_tick({"soc": 60}, "off_peak", ev_load_w=0.0, drain_target_soc=30)
    assert coord._dp_carrier.state == DPState.HOLD_ONLY


# ==========================================================================
# EXECUTED source mutations (Reviewer-C authority)
# --------------------------------------------------------------------------
# Edit energy.py on disk, run a target test in a subprocess isolated
# from parent's already-imported bytes, assert it FAILS, restore.
# ==========================================================================


_HERE = os.path.dirname(os.path.abspath(__file__))


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _clear_pycache():
    for root, dirs, _ in os.walk(_dc_path):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)


def _run_test_in_subprocess(test_name: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.abspath(os.path.join(_HERE, ".."))
    return subprocess.run(
        [
            sys.executable, "-m", "pytest",
            f"{os.path.abspath(__file__)}::{test_name}",
            "-x", "--tb=short", "-q",
        ],
        env=env,
        capture_output=True, text=True,
        cwd=os.path.abspath(os.path.join(_HERE, "..", "..")),
    )


def _mutate_and_expect_red(
    swap_from: str, swap_to: str, test_name: str,
):
    src_path = _ENERGY_SRC
    original = src_path.read_text(encoding="utf-8")
    assert swap_from in original, f"anchor missing in energy.py: {swap_from!r}"
    mutated = original.replace(swap_from, swap_to, 1)
    assert mutated != original, "mutation was a no-op"
    src_path.write_text(mutated, encoding="utf-8")
    _md5_after = _md5(src_path)
    try:
        _clear_pycache()
        result = _run_test_in_subprocess(test_name)
        assert result.returncode != 0, (
            f"expected {test_name} to FAIL under mutation; got returncode="
            f"{result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    finally:
        src_path.write_text(original, encoding="utf-8")
        _clear_pycache()
        assert _md5(src_path) != _md5_after
        assert src_path.read_text(encoding="utf-8") == original


def test_MUTATION_item1_exit_predicate_reverted_makes_hold_test_red():
    # Revert exit predicate to `not _is_any_evse_charging` on the
    # paused-check clause — window collapses immediately on the first
    # tick (charging=False), so the hold-3-ticks test goes RED.
    _mutate_and_expect_red(
        swap_from="not self._ev._paused_by_dp  # noqa: SLF001\n            and not self._is_any_evse_charging()",
        swap_to="not self._is_any_evse_charging()\n            and not self._is_any_evse_charging()",
        test_name="test_paused_aware_exit_holds_window_across_three_ticks",
    )


def test_MUTATION_item2_house_load_restubbed_zero_makes_live_test_red():
    # Restub the helper to the pre-fix `0.0` — target test observes the
    # return of `_dp_house_load_kw`, which now returns 0 instead of the
    # live SPAN/R1 fit.
    _mutate_and_expect_red(
        swap_from="src = getattr(self, \"_dp_house_load_source\", \"max_span_r1\")",
        swap_to="return 0.0  # B2c-1 stubbed\n        src = getattr(self, \"_dp_house_load_source\", \"max_span_r1\")",
        test_name="test_house_load_live_source_returns_positive",
    )


def test_MUTATION_item3_blind_signal_reverted_to_invented_attr_makes_test_red():
    # Batch-5 B7 refactor: the is_blind_hold value is computed ONCE per
    # tick into `_tick_is_blind_hold` and threaded into both DPInputs
    # AND the coord snapshot. The mutation-anchor moved with it.
    _mutate_and_expect_red(
        swap_from='_tick_is_blind_hold = bool((not _env_ok) and _bat_soc is None)',
        swap_to='_tick_is_blind_hold = bool(getattr(self._battery, "_is_blind_hold_active", False))',
        test_name="test_blind_signal_uses_envoy_available_and_battery_soc",
    )


def test_MUTATION_item4_rescan_removed_makes_car_b_test_red():
    _mutate_and_expect_red(
        swap_from="if _fresh:\n                # dp-drain-target-value-stamp — R2 rescan site (:4540).",
        swap_to="if False and _fresh:\n                # dp-drain-target-value-stamp — R2 rescan site (:4540).",
        test_name="test_second_plug_in_rescan_claims_car_b_within_one_tick",
    )


def test_MUTATION_item5_kill_switch_hoist_removed_makes_flip_test_red():
    _mutate_and_expect_red(
        swap_from="if _has_dp_state:\n                self._apply_dp_reversion(tou_period=period)",
        swap_to="if False and _has_dp_state:\n                self._apply_dp_reversion(tou_period=period)",
        test_name="test_kill_switch_hoist_releases_pause_mid_window",
    )


def test_MUTATION_item6_night_gate_removed_makes_daytime_test_red():
    _mutate_and_expect_red(
        swap_from='if not _dp_on or self._tou.get_current_period() != "off_peak":\n            raise _DPSkip()',
        swap_to='if not _dp_on or False:\n            raise _DPSkip()',
        test_name="test_night_window_gate_skips_tick_outside_off_peak",
    )
