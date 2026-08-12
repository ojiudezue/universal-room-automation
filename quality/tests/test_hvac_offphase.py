"""HVAC-PRESET-FLAP-1 behavioral tests — duty off-phase honesty.

Covers D1 (`_apply_duty_off_phase` helper + D5 else-limb rewire), D2
(episode-gated ledger row + distinct reason `runtime_exceeded_offphase`),
D3 (`duty_cycle_off_phase` sensor attribute), D4 (knobs + kill-switch).

Loads the real ``hvac.py`` module under a light HA stub (mirrors the
sibling ``test_arrester_comfort_delay.py`` bootstrap) and drives
``_apply_duty_off_phase`` directly against a lightweight coordinator +
mock zone. Full ``_apply_house_state_presets`` behavioral drills are
carried out at review time via per-site source mutation.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import timezone
from datetime import datetime
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# HA stubs (setdefault-only so sibling tests keep their registrations)
# ---------------------------------------------------------------------------

def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731


def _utcnow_real() -> datetime:
    return datetime.now(timezone.utc)


def _now_real() -> datetime:
    return datetime.now()


_mods: dict[str, dict] = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock,
        "Event": MagicMock,
        "CALLBACK_TYPE": object,
        "callback": _identity,
    },
    "homeassistant.helpers": {},
    "homeassistant.helpers.event": {
        "async_call_later": MagicMock(return_value=lambda: None),
        "async_track_state_change_event": MagicMock(return_value=lambda: None),
        "async_track_time_interval": MagicMock(return_value=lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": MagicMock(),
        "async_dispatcher_connect": MagicMock(return_value=lambda: None),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": _utcnow_real,
        "now": _now_real,
        "UTC": timezone.utc,
    },
    "homeassistant.components": {},
    "homeassistant.components.recorder": {"get_instance": MagicMock()},
    "homeassistant.components.recorder.history": {
        "get_significant_states": MagicMock(),
    },
}
for _name, _attrs in _mods.items():
    sys.modules.setdefault(_name, _mock_module(_name, **_attrs))


_HERE = os.path.dirname(__file__)
_URA_PATH = os.path.join(_HERE, "..", "..", "custom_components",
                         "universal_room_automation")
sys.path.insert(0, os.path.join(_HERE, "..", ".."))

if "custom_components" not in sys.modules:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(_HERE, "..", "..", "custom_components")]
    sys.modules["custom_components"] = _cc
if "custom_components.universal_room_automation" not in sys.modules:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_URA_PATH]
    sys.modules["custom_components.universal_room_automation"] = _ura


def _load(modname: str, relpath: str) -> types.ModuleType:
    cached = sys.modules.get(modname)
    if cached is not None and getattr(cached, "__file__", None):
        return cached
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(_URA_PATH, relpath),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


_load("custom_components.universal_room_automation.const", "const.py")
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc = types.ModuleType(
        "custom_components.universal_room_automation.domain_coordinators"
    )
    _dc.__path__ = [os.path.join(_URA_PATH, "domain_coordinators")]
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc

# Force-clean any lightweight stand-ins from sibling files so we load real.
for _m in (
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
):
    _c = sys.modules.get(_m)
    if _c is not None and not getattr(_c, "__file__", None):
        del sys.modules[_m]

hvac_const = _load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "domain_coordinators/hvac_const.py",
)
hvac_setpoint = _load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
    "domain_coordinators/hvac_setpoint.py",
)


# ---------------------------------------------------------------------------
# Const sanity — the knob block is present, defaults are sane.
# ---------------------------------------------------------------------------

class TestOffphaseConsts:
    def test_offset_default_is_2f(self):
        assert hvac_const.COMFORT_OFFPHASE_OFFSET_F == 2.0
        assert hvac_const.DEFAULT_COMFORT_OFFPHASE_OFFSET_F == 2.0

    def test_offset_bounds_include_zero(self):
        # Rev-2 M7: MIN 0.0 is a documented diagnostic — must be reachable.
        assert hvac_const.MIN_COMFORT_OFFPHASE_OFFSET_F == 0.0
        assert hvac_const.MAX_COMFORT_OFFPHASE_OFFSET_F == 6.0

    def test_conf_keys_exist(self):
        assert hvac_const.CONF_COMFORT_OFFPHASE_OFFSET_F == \
            "hvac_comfort_offphase_offset_f"
        assert hvac_const.CONF_HVAC_OFFPHASE_HONESTY_ENABLED == \
            "hvac_offphase_honesty_enabled"
        assert hvac_const.DEFAULT_HVAC_OFFPHASE_HONESTY_ENABLED is True


# ---------------------------------------------------------------------------
# Fixtures for the helper drill.
# ---------------------------------------------------------------------------

class _FakeZone:
    def __init__(self, zone_id="z1", climate_entity="climate.zone_1"):
        self.zone_id = zone_id
        self.zone_name = zone_id
        self.climate_entity = climate_entity
        self.preset_mode = "home"
        self.zone_persons: list[str] = []
        self.runtime_exceeded = True
        self.any_room_occupied = True


class _FakeArrester:
    def __init__(self, comfort_delay=False):
        self._active = comfort_delay
        self.suppressed_with: list[tuple] = []

    def comfort_delay_active(self, zone_id):
        return self._active

    def suppress(self, entity_id, kind=None):
        self.suppressed_with.append((entity_id, kind))


class _FakePresetManager:
    def __init__(self, cool=76.0, heat=68.0):
        self._cool = cool
        self._heat = heat
        self.calls: list[str] = []

    def get_seasonal_setpoints(self, preset, season=None):
        self.calls.append(preset)
        # Vacation cool baseline is intentionally higher — used by the
        # vacation test.
        if preset == "vacation":
            return (self._cool + 4.0, self._heat - 2.0)
        return (self._cool, self._heat)


class _FakeCoord:
    """Lightweight stand-in that carries only the fields
    ``_apply_duty_off_phase`` reads."""

    def __init__(self, *, offset=2.0, honest=True, shed=False,
                 comfort_delay=False, freeze=False, season="summer",
                 baselines=(76.0, 68.0), activity_logger=None):
        self.hass = MagicMock()
        # states.get returns objects whose .state is "home" so we can flow
        # zone_persons through the ledger's home_persons filter.
        _state = MagicMock()
        _state.state = "home"
        self.hass.states.get = MagicMock(return_value=_state)
        # async_create_task synchronously records the coroutine so the
        # test suite can await / close it, and inspect that the ledger
        # was scheduled.
        self.scheduled: list = []
        def _create_task(coro):
            self.scheduled.append(coro)
            return MagicMock()
        self.hass.async_create_task = _create_task

        self._comfort_offphase_offset_f = float(offset)
        self._hvac_offphase_honesty_enabled = bool(honest)
        self._energy_constraint_mode = "shed" if shed else "coast"
        self._freeze_active = bool(freeze)
        self._house_state = "home_day"
        self._preset_manager = _FakePresetManager(*baselines)
        self._override_arrester = _FakeArrester(comfort_delay=comfort_delay)
        self._offphase_logged: set[tuple[str, str]] = set()
        self._offphase_logged_state = ""
        # B1 fix-up: throttle map (helper reads/writes this).
        self._last_offphase_emit: dict[str, tuple[float, float]] = {}

    # Properties the helper reads via `self.<name>`.
    @property
    def shed_active(self):
        return self._energy_constraint_mode == "shed"


# Load hvac module with FULL heavy deps stubbed. We only need the helper
# text, not the class-level dependencies. To avoid pulling the full class
# graph, we exec the helper's source into a shim class.

def _extract_helper():
    """Compile ``_apply_duty_off_phase`` out of hvac.py into a callable
    bound to _FakeCoord — dodges the heavy import graph."""
    src_path = os.path.join(
        _URA_PATH, "domain_coordinators", "hvac.py",
    )
    with open(src_path) as f:
        src = f.read()
    start = src.index("async def _apply_duty_off_phase(")
    # find matching def _execute_vacancy_sweep (the anchor immediately after)
    end = src.index("async def _execute_vacancy_sweep(", start)
    fn_src = src[start:end]
    # Dedent from method-body indentation (4 spaces) to top-level.
    lines = fn_src.splitlines()
    dedented = "\n".join(line[4:] if line.startswith("    ") else line
                          for line in lines)
    ns = {
        "emit_set_temperature": hvac_setpoint.emit_set_temperature,
        "_LOGGER": types.SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            debug=lambda *a, **k: None,
        ),
    }
    exec(compile(dedented, "hvac.py::_apply_duty_off_phase", "exec"), ns)
    return ns["_apply_duty_off_phase"]


_APPLY = _extract_helper()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else \
        asyncio.new_event_loop().run_until_complete(coro)


class _RecordingLogger:
    def __init__(self):
        self.rows: list[dict] = []

    async def log(self, **kwargs):
        self.rows.append(kwargs)


# ---------------------------------------------------------------------------
# D1 tests — helper behavior + shed early return + gate defer.
# ---------------------------------------------------------------------------

class TestDutyOffPhaseSetpoint:
    def test_writes_home_plus_offset(self):
        coord = _FakeCoord(offset=2.0, baselines=(76.0, 68.0))
        zone = _FakeZone()
        called: list[dict] = []
        async def _fake_emit(hass, entity_id, **kw):
            called.append({"entity_id": entity_id, **kw})
            return True
        # Monkey-patch the helper's emit reference.
        import types as _t
        ns = _APPLY.__globals__
        prev = ns["emit_set_temperature"]
        ns["emit_set_temperature"] = _fake_emit
        try:
            out = _run(_APPLY(coord, zone, "home", _RecordingLogger()))
        finally:
            ns["emit_set_temperature"] = prev
        assert out is True
        assert len(called) == 1
        assert called[0]["target_temp_high"] == pytest.approx(78.0)
        assert called[0]["target_temp_low"] == pytest.approx(68.0)
        assert called[0]["site"] == "S14_duty_off_phase"
        assert called[0]["reason"] == "runtime_exceeded_offphase"
        # Suppress on arrester fired.
        assert coord._override_arrester.suppressed_with, \
            "arrester.suppress not called on S14 path"

    def test_shed_short_circuits(self):
        coord = _FakeCoord(shed=True)
        zone = _FakeZone()
        called: list = []
        async def _fake_emit(*a, **kw):
            called.append(kw); return True
        ns = _APPLY.__globals__
        prev = ns["emit_set_temperature"]
        ns["emit_set_temperature"] = _fake_emit
        try:
            out = _run(_APPLY(coord, zone, "home", _RecordingLogger()))
        finally:
            ns["emit_set_temperature"] = prev
        # Shed dominance: silent True return, NO emit, NO ledger.
        assert out is True
        assert called == []

    def test_gate_defers_returns_false(self):
        coord = _FakeCoord(comfort_delay=True)
        zone = _FakeZone()
        # Use REAL emit_set_temperature so the gate parameter is honored.
        # It defers by calling `gate()` -> True -> returns False.
        logger = _RecordingLogger()
        out = _run(_APPLY(coord, zone, "home", logger))
        assert out is False
        # No ledger row appended (defer path).
        assert logger.rows == []

    def test_vacation_target_preset(self):
        coord = _FakeCoord(offset=2.0, baselines=(76.0, 68.0))
        zone = _FakeZone()
        called: list = []
        async def _fake_emit(hass, entity_id, **kw):
            called.append(kw); return True
        ns = _APPLY.__globals__
        prev = ns["emit_set_temperature"]
        ns["emit_set_temperature"] = _fake_emit
        try:
            _run(_APPLY(coord, zone, "vacation", _RecordingLogger()))
        finally:
            ns["emit_set_temperature"] = prev
        # Vacation baselines are (80, 66) per _FakePresetManager.
        assert called[0]["target_temp_high"] == pytest.approx(82.0)

    def test_freeze_active_flag_passthrough(self):
        coord = _FakeCoord(freeze=True)
        zone = _FakeZone()
        seen: list = []
        async def _fake_emit(hass, entity_id, **kw):
            seen.append(kw); return True
        ns = _APPLY.__globals__
        prev = ns["emit_set_temperature"]
        ns["emit_set_temperature"] = _fake_emit
        try:
            _run(_APPLY(coord, zone, "home", _RecordingLogger()))
        finally:
            ns["emit_set_temperature"] = prev
        assert seen[0]["freeze_active"] is True

    def test_preset_manager_none_returns_false(self):
        coord = _FakeCoord()
        # Force the preset manager to return None.
        coord._preset_manager.get_seasonal_setpoints = lambda p, s=None: None
        zone = _FakeZone()
        out = _run(_APPLY(coord, zone, "home", _RecordingLogger()))
        assert out is False


# ---------------------------------------------------------------------------
# D2 tests — ledger row shape + episode gating + live home_persons.
# ---------------------------------------------------------------------------

class TestOffphaseLedger:
    def _run_once(self, coord, zone, logger):
        called: list = []
        async def _fake_emit(hass, entity_id, **kw):
            called.append(kw); return True
        ns = _APPLY.__globals__
        prev = ns["emit_set_temperature"]
        ns["emit_set_temperature"] = _fake_emit
        try:
            _run(_APPLY(coord, zone, "home", logger))
        finally:
            ns["emit_set_temperature"] = prev
        # Drain scheduled coroutines so we can inspect ledger.rows.
        loop = asyncio.new_event_loop()
        try:
            while coord.scheduled:
                coro = coord.scheduled.pop(0)
                loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_one_row_per_episode(self):
        coord = _FakeCoord()
        zone = _FakeZone()
        logger = _RecordingLogger()
        # Fire the helper 5 times in the same house_state — exactly ONE
        # ledger row should be appended (episode dedup).
        # NB: clear the B1 throttle between calls so the dedup guard is
        # the SOLE mechanism preventing multi-row emission. Without this,
        # the throttle short-circuits before the ledger emit and masks a
        # bug in the dedup predicate.
        for _ in range(5):
            coord._last_offphase_emit.clear()
            self._run_once(coord, zone, logger)
        assert len(logger.rows) == 1

    def test_reason_string_is_offphase(self):
        coord = _FakeCoord()
        zone = _FakeZone()
        logger = _RecordingLogger()
        self._run_once(coord, zone, logger)
        assert logger.rows, "expected one ledger row"
        row = logger.rows[0]
        assert row["action"] == "preset_change_suppressed"
        details = row["details"]
        assert details["reason"] == "runtime_exceeded_offphase"
        assert details["duty_cycle_off_phase"] is True
        assert details["would_have_written_preset"] == "away"
        assert details["setpoint_high_written"] == pytest.approx(78.0)

    def test_home_persons_live_not_static_config(self):
        coord = _FakeCoord()
        zone = _FakeZone()
        # Static config lists two persons; live state says only p1 is home.
        zone.zone_persons = ["person.p1", "person.p2"]
        # coord.hass.states.get returns state "home" for anything (default
        # mock). Override to filter one.
        def _state_for(entity_id):
            s = MagicMock()
            s.state = "home" if entity_id == "person.p1" else "not_home"
            return s
        coord.hass.states.get = _state_for
        logger = _RecordingLogger()
        self._run_once(coord, zone, logger)
        row = logger.rows[0]
        # Live filter: only p1 makes it into the row.
        assert row["details"]["home_persons"] == ["person.p1"]


# ---------------------------------------------------------------------------
# D4 tests — knob live-read + kill-switch semantics + zero-offset diagnostic.
# ---------------------------------------------------------------------------

class TestOffphaseKnobs:
    def test_offset_live_read(self):
        coord = _FakeCoord(offset=3.0, baselines=(76.0, 68.0))
        zone = _FakeZone()
        called: list = []
        async def _fake_emit(hass, entity_id, **kw):
            called.append(kw); return True
        ns = _APPLY.__globals__
        prev = ns["emit_set_temperature"]
        ns["emit_set_temperature"] = _fake_emit
        try:
            _run(_APPLY(coord, zone, "home", _RecordingLogger()))
        finally:
            ns["emit_set_temperature"] = prev
        assert called[0]["target_temp_high"] == pytest.approx(79.0)

    def test_offset_zero_is_diagnostic_not_violation(self):
        # Rev-2 M7: offset 0 = INV inertness clause (f). Helper still
        # emits — no error, no exception — and ceiling collapses to home
        # cool baseline exactly.
        coord = _FakeCoord(offset=0.0, baselines=(76.0, 68.0))
        zone = _FakeZone()
        called: list = []
        async def _fake_emit(hass, entity_id, **kw):
            called.append(kw); return True
        ns = _APPLY.__globals__
        prev = ns["emit_set_temperature"]
        ns["emit_set_temperature"] = _fake_emit
        try:
            out = _run(_APPLY(coord, zone, "home", _RecordingLogger()))
        finally:
            ns["emit_set_temperature"] = prev
        assert out is True
        assert called[0]["target_temp_high"] == pytest.approx(76.0)


# ---------------------------------------------------------------------------
# D5 else-limb wiring / mutation anchors — grep the SOURCE to prove the
# dominance short-circuit + shed early return + S14 gate wiring are present.
# ---------------------------------------------------------------------------

class TestD5ElseLimbAnchors:
    """Source-anchor guards. Each fires when a specific load-bearing
    fragment is removed, catching accidental deletion during future
    refactors. These are NOT a substitute for per-site source mutation
    (Tier 2-DB Review C) — they are floor-level safety anchors."""

    def _src(self):
        with open(os.path.join(_URA_PATH, "domain_coordinators", "hvac.py")) as f:
            return f.read()

    def test_dominance_shortcircuit_predicates_present(self):
        src = self._src()
        # All four exhaustive short-circuit predicates from plan §3.2 must
        # appear in the D5 else-limb short-circuit block.
        assert "stale_occupancy" in src
        assert "zone_vacant_past_grace" in src
        assert "not zone.any_room_occupied" in src
        assert "not self._hvac_offphase_honesty_enabled" in src

    def test_apply_duty_off_phase_helper_defined(self):
        assert "async def _apply_duty_off_phase(" in self._src()

    def test_s14_site_tag_and_reason_wired(self):
        src = self._src()
        assert '"S14_duty_off_phase"' in src
        assert '"runtime_exceeded_offphase"' in src

    def test_shed_early_return_present(self):
        # Helper opens with `if self.shed_active: return True` — mutating
        # this line reddens both this anchor and the shed test above.
        src = self._src()
        assert "if self.shed_active:" in src
        # And the helper is the one containing the shed guard.
        helper_start = src.index("async def _apply_duty_off_phase(")
        helper_end = src.index("async def _execute_vacancy_sweep(", helper_start)
        assert "self.shed_active" in src[helper_start:helper_end]

    def test_ledger_reason_string_present_in_helper(self):
        src = self._src()
        helper_start = src.index("async def _apply_duty_off_phase(")
        helper_end = src.index("async def _execute_vacancy_sweep(", helper_start)
        body = src[helper_start:helper_end]
        assert '"runtime_exceeded_offphase"' in body
        assert '"duty_cycle_off_phase"' in body


# ---------------------------------------------------------------------------
# D3 sensor attribute anchor — attribute is added to HVACZonePresetSensor's
# extra_state_attributes.
# ---------------------------------------------------------------------------

class TestDutyOffPhaseAttr:
    def test_attribute_added_to_extra_state_attributes(self):
        with open(os.path.join(_URA_PATH, "sensor.py")) as f:
            src = f.read()
        cls_start = src.index("class HVACZonePresetSensor(")
        # Get the extra_state_attributes body of THIS class.
        esa_start = src.index("def extra_state_attributes", cls_start)
        esa_end = src.index("async def async_added_to_hass", cls_start)
        esa_body = src[esa_start:esa_end]
        assert "duty_cycle_off_phase" in esa_body
        assert "runtime_exceeded" in esa_body
        assert "any_room_occupied" in esa_body
        assert "_d3_skipped_current_tick" in esa_body


# ---------------------------------------------------------------------------
# D0 anchor — S14 row lives in ARREST-COMFORT §3.7 table.
# ---------------------------------------------------------------------------

class TestSiblingPlanS14Row:
    def test_s14_row_in_sibling_plan(self):
        path = os.path.join(
            _HERE, "..", "..", "docs", "planning",
            "PLANNING_arrester_comfort_delay.md",
        )
        with open(path) as f:
            content = f.read()
        # S14 row keyed by DEFER + reason string + site tag.
        assert "| S14 |" in content
        assert "runtime_exceeded_offphase" in content
        assert "S14_duty_off_phase" in content
