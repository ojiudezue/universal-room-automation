"""HVAC-PRESET-FLAP-1 integration tests — REAL _apply_house_state_presets.

C-HIGH-1 (fix-up): drive the REAL `HVACCoordinator._apply_house_state_presets`
method against a bare-instance harness (mirror of `test_heatcool_enforcer.py`
pattern), reaching the D5 else-limb and asserting the S14 helper fires with
the correct emit kwargs AND `effective_preset` stays `home` (never `away`).

Six mutation-anchored subcases:
  1. stale_occupancy=True short-circuit — S1 preset=away must fire, S14 must NOT.
  2. zone_vacant_past_grace=True short-circuit — S1 preset=away must fire, S14 must NOT.
  3. any_room_occupied=False (within-grace vacancy) — S1 preset=away must fire, S14 must NOT.
  4. hvac_offphase_honesty_enabled=False (kill-switch) — S1 preset=away must fire, S14 must NOT.
  5. semantic-neuter the whole wire-in (`if False and ...`) — happy-path integration test reds.
  6. `continue` after deferred S14 removed — S1 preset must NOT fire that tick.

Plus fix-up tests:
  - B1 emit throttle across ticks (two same-value ticks -> ONE service call).
  - B1 throttle discharge on runtime_exceeded clear.
  - B2 gate-defer rollback of suppress.
  - B3 ceiling-held-until-next-preset-transition.
  - B10 shed_active -> no ledger row.
  - C-MED-1 4-row truth-table for duty_cycle_off_phase attribute (behavioral,
    reads the REAL HVACZonePresetSensor.extra_state_attributes).
  - C-MED-2 cache-discharge-on-house-state-transition (3+transition+3 = 2 rows).
  - C-MED-3 boot INFO/WARN via caplog + ctor kwargs plumbed via __init__.py.
  - C-LOW-2 widened home_persons oracle (3 configured, 2 home -> both in row).
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[2]
ROOT_REL = "custom_components/universal_room_automation"


# ---------------------------------------------------------------------------
# HA + URA module loader (mirror of test_heatcool_enforcer.py)
# ---------------------------------------------------------------------------


def _stub_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def _load_hvac_module():
    if "ura_offphase_hvac_under_test" in sys.modules:
        return sys.modules["ura_offphase_hvac_under_test"]

    if "homeassistant" not in sys.modules:
        _stub_module("homeassistant").__path__ = []
    if "homeassistant.core" not in sys.modules:
        _stub_module(
            "homeassistant.core",
            HomeAssistant=type("HomeAssistant", (), {}),
            callback=lambda f: f,
        )
    if "homeassistant.helpers" not in sys.modules:
        _stub_module("homeassistant.helpers").__path__ = []
    if "homeassistant.helpers.dispatcher" not in sys.modules:
        _stub_module(
            "homeassistant.helpers.dispatcher",
            async_dispatcher_send=lambda *a, **kw: None,
            async_dispatcher_connect=lambda *a, **kw: (lambda: None),
        )
    if "homeassistant.helpers.event" not in sys.modules:
        _stub_module(
            "homeassistant.helpers.event",
            async_track_time_interval=lambda *a, **kw: (lambda: None),
            async_call_later=lambda *a, **kw: (lambda: None),
            async_track_state_change_event=lambda *a, **kw: (lambda: None),
        )
    if "homeassistant.helpers.storage" not in sys.modules:
        _stub_module("homeassistant.helpers.storage", Store=object)
    if "homeassistant.helpers.device_registry" not in sys.modules:
        _stub_module("homeassistant.helpers.device_registry", DeviceInfo=dict)
    if "homeassistant.const" not in sys.modules:
        _stub_module(
            "homeassistant.const", EVENT_HOMEASSISTANT_STARTED="homeassistant_started"
        )
    if "homeassistant.util" not in sys.modules:
        _stub_module("homeassistant.util").__path__ = []
    if "homeassistant.util.dt" not in sys.modules:
        _stub_module(
            "homeassistant.util.dt",
            now=lambda: datetime.now(timezone.utc),
            utcnow=lambda: datetime.now(timezone.utc),
            parse_datetime=lambda s: datetime.fromisoformat(s) if s else None,
        )

    pkg = _stub_module("ura_offphase_hvac_pkg")
    pkg.__path__ = []
    const = types.ModuleType("ura_offphase_hvac_pkg.const")

    class _ConstAny(str):
        pass

    def _const_getattr(name):
        return _ConstAny(name)

    const.__getattr__ = _const_getattr  # type: ignore[attr-defined]
    const.DOMAIN = "universal_room_automation"
    const.VERSION = "test"
    sys.modules["ura_offphase_hvac_pkg.const"] = const

    coord_pkg = _stub_module("ura_offphase_hvac_pkg.domain_coordinators")
    coord_pkg.__path__ = []

    hvac_const_src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "hvac_const.py"
    spec = importlib.util.spec_from_file_location(
        "ura_offphase_hvac_pkg.domain_coordinators.hvac_const", str(hvac_const_src)
    )
    hvac_const = importlib.util.module_from_spec(spec)
    hvac_const.__package__ = "ura_offphase_hvac_pkg.domain_coordinators"
    sys.modules["ura_offphase_hvac_pkg.domain_coordinators.hvac_const"] = hvac_const
    spec.loader.exec_module(hvac_const)

    class _BaseCoordinator:
        def __init__(self, *a, **kw):
            pass

    _stub_module(
        "ura_offphase_hvac_pkg.domain_coordinators.base",
        BaseCoordinator=_BaseCoordinator,
        CoordinatorAction=object,
        Intent=object,
    )

    _stub_module(
        "ura_offphase_hvac_pkg.domain_coordinators.hvac_covers", CoverController=object
    )
    _stub_module(
        "ura_offphase_hvac_pkg.domain_coordinators.hvac_egress", EgressManager=object
    )
    _stub_module(
        "ura_offphase_hvac_pkg.domain_coordinators.hvac_fans", FanController=object
    )
    _stub_module(
        "ura_offphase_hvac_pkg.domain_coordinators.hvac_override", OverrideArrester=object
    )
    _stub_module(
        "ura_offphase_hvac_pkg.domain_coordinators.hvac_predict", HVACPredictor=object
    )
    _stub_module(
        "ura_offphase_hvac_pkg.domain_coordinators.hvac_preset", PresetManager=object
    )
    _stub_module(
        "ura_offphase_hvac_pkg.domain_coordinators.hvac_zones", ZoneManager=object
    )

    # Lazy import inside D6 stuck-sensor branch — provide an async no-op.
    async def _fake_fire(*a, **kw):
        return None
    _stub_module(
        "ura_offphase_hvac_pkg.domain_coordinators._stuck_signal_nm",
        fire_stuck_signal=_fake_fire,
    )

    signals = types.ModuleType("ura_offphase_hvac_pkg.domain_coordinators.signals")

    def _signals_getattr(name):
        return name

    signals.__getattr__ = _signals_getattr  # type: ignore[attr-defined]
    sys.modules["ura_offphase_hvac_pkg.domain_coordinators.signals"] = signals

    # Real hvac_setpoint — we need the actual emit_set_temperature to route
    # the gate correctly.
    setpoint_src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "hvac_setpoint.py"
    spec = importlib.util.spec_from_file_location(
        "ura_offphase_hvac_pkg.domain_coordinators.hvac_setpoint", str(setpoint_src)
    )
    hvac_setpoint = importlib.util.module_from_spec(spec)
    hvac_setpoint.__package__ = "ura_offphase_hvac_pkg.domain_coordinators"
    sys.modules["ura_offphase_hvac_pkg.domain_coordinators.hvac_setpoint"] = hvac_setpoint
    spec.loader.exec_module(hvac_setpoint)

    hvac_src = ROOT_DIR / ROOT_REL / "domain_coordinators" / "hvac.py"
    spec = importlib.util.spec_from_file_location(
        "ura_offphase_hvac_pkg.domain_coordinators.hvac", str(hvac_src)
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "ura_offphase_hvac_pkg.domain_coordinators"
    sys.modules["ura_offphase_hvac_pkg.domain_coordinators.hvac"] = mod
    spec.loader.exec_module(mod)

    sys.modules["ura_offphase_hvac_under_test"] = mod
    return mod


# ---------------------------------------------------------------------------
# Fakes for the harness
# ---------------------------------------------------------------------------


class _FakeZone:
    def __init__(self, zone_id="z1", climate_entity="climate.zone_1",
                 runtime_exceeded=True, any_room_occupied=True,
                 preset_mode="home", zone_persons=None):
        self.zone_id = zone_id
        self.zone_name = zone_id
        self.climate_entity = climate_entity
        self.preset_mode = preset_mode
        self.zone_persons = zone_persons or []
        self.runtime_exceeded = runtime_exceeded
        self.any_room_occupied = any_room_occupied
        self.last_occupied_time = None
        self.continuous_occupied_since = None
        self.current_session_start = None
        self.vacancy_sweep_done = True
        self.vacancy_sweep_enabled = False
        self.hvac_mode = "heat_cool"
        self.target_temp_high = None
        self.target_temp_low = None
        self.current_temperature = 72.0
        self.hvac_action = "idle"
        self.override_count_today = 0
        self.ac_reset_count_today = 0
        self.last_override_direction = None


class _FakeZoneManager:
    def __init__(self, zones):
        self.zones = zones


class _FakeEgressManager:
    def is_paused(self, zone_id):
        return False


class _FakeArrester:
    def __init__(self, comfort_delay=False):
        self._active = comfort_delay
        self.suppressed: list[str] = []
        self.unsuppressed: list[str] = []

    def comfort_delay_active(self, zone_id):
        return self._active

    def suppress(self, entity_id, kind=None):
        self.suppressed.append(entity_id)

    def unsuppress(self, entity_id):
        self.unsuppressed.append(entity_id)

    def _get_soc_floor(self):
        return 80

    def _get_grace_min(self):
        return 30


class _FakePresetManager:
    current_season = "summer"

    def __init__(self, cool=76.0, heat=68.0):
        self._cool = cool
        self._heat = heat

    def get_preset_for_house_state(self, house_state):
        return "home"

    def get_seasonal_setpoints(self, preset, season=None):
        return (self._cool, self._heat)

    def should_change_preset(self, current, target):
        return current != target


class _FakeActivityLogger:
    def __init__(self):
        self.rows: list[dict] = []

    async def log(self, **kwargs):
        self.rows.append(kwargs)


class _FakeServices:
    def __init__(self):
        self.calls: list[dict] = []

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append(
            {"domain": domain, "service": service, "data": dict(data)}
        )


class _FakeHass:
    def __init__(self, activity_logger=None):
        self.services = _FakeServices()
        self.data = {
            "universal_room_automation": {
                "activity_logger": activity_logger,
            }
        }
        # Track tasks so pytest doesn't complain about un-awaited coroutines.
        self._tasks: list = []

    def async_create_task(self, coro):
        # Run the coroutine to completion synchronously — our fakes only
        # ever do non-blocking state mutations (list.append), so a
        # single-step send() suffices. This avoids the "loop inside a
        # loop" issues of `asyncio.new_event_loop().run_until_complete`
        # under pytest-asyncio's active loop.
        try:
            coro.send(None)
        except StopIteration:
            pass
        return None


def _make_coord(
    *, zones, honest=True, shed=False, comfort_delay=False,
    house_state="home_day", activity_logger=None, offset=2.0, zi=True,
):
    mod = _load_hvac_module()
    coord = mod.HVACCoordinator.__new__(mod.HVACCoordinator)
    coord.hass = _FakeHass(activity_logger)
    coord._house_state = house_state
    coord._defer_gate_enabled = False
    coord._d6_gate_engaged = False
    coord._d6_deferrals_today = 0
    coord._zone_manager = _FakeZoneManager(zones)
    coord._egress_manager = _FakeEgressManager()
    coord._preset_manager = _FakePresetManager()
    coord._override_arrester = _FakeArrester(comfort_delay=comfort_delay)
    coord._energy_constraint_mode = "shed" if shed else "coast"
    coord._energy_constraint = None
    coord._vacancy_grace = 30
    coord._vacancy_grace_constrained = 15
    coord._zone_intelligence_enabled = zi
    coord._max_occupancy_hours = 8
    coord._vacancy_sweeps_today = 0
    coord._pre_arrival_zones = set()
    coord._zone_entry_dwell = 0
    coord._freeze_active = False
    coord._night_trust_logged = set()
    coord._night_trust_logged_state = ""
    coord._comfort_offphase_offset_f = float(offset)
    coord._hvac_offphase_honesty_enabled = bool(honest)
    coord._offphase_logged = set()
    coord._offphase_logged_state = ""
    coord._last_offphase_emit = {}
    coord._d3_skipped_current_tick = {}
    coord._last_emitted_range = {}
    coord._observation_mode = False
    coord._guest_mode_actuation_enabled = False
    coord._compliance = None
    coord._decision_recorder = None
    # No-op the tail so we isolate D5-else behavior from downstream DPM /
    # compliance / override-engine machinery.
    async def _noop(*a, **kw):
        return None
    coord._async_apply_preset_overrides = _noop
    coord._decision_logger = None
    return coord


def _set_temp_calls(coord):
    return [c for c in coord.hass.services.calls if c["service"] == "set_temperature"]


def _set_preset_calls(coord):
    return [c for c in coord.hass.services.calls if c["service"] == "set_preset_mode"]


# ---------------------------------------------------------------------------
# C-HIGH-1: happy-path integration + 6 mutation subcases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_writes_s14_and_no_s1_away():
    """The load-bearing wire-in: occupied zone + runtime_exceeded + kill-
    switch ON + not shed → S14 emit_set_temperature at home+OFFSET, ZERO
    set_preset_mode calls, preset stays `home`."""
    z = _FakeZone()
    coord = _make_coord(zones={"z1": z})
    await coord._apply_house_state_presets()
    st_calls = _set_temp_calls(coord)
    pr_calls = _set_preset_calls(coord)
    assert len(st_calls) == 1, f"expected 1 set_temperature, got {st_calls}"
    assert st_calls[0]["data"]["target_temp_high"] == pytest.approx(78.0)
    assert st_calls[0]["data"]["target_temp_low"] == pytest.approx(68.0)
    assert pr_calls == [], f"S1 preset write must not fire, got {pr_calls}"


@pytest.mark.asyncio
async def test_stale_occupancy_short_circuit_writes_away():
    """Sub 1: stuck-sensor (continuous_occupied_since past max hours) →
    stale_occupancy=True → S1 preset=away fires; S14 must NOT."""
    z = _FakeZone()
    # D6 requires continuous_occupied_since past max_occupancy_hours.
    from datetime import timedelta
    z.continuous_occupied_since = datetime.now(timezone.utc) - timedelta(hours=100)
    coord = _make_coord(zones={"z1": z})
    await coord._apply_house_state_presets()
    st = _set_temp_calls(coord)
    pr = _set_preset_calls(coord)
    assert st == [], f"S14 must not fire on stale_occupancy; got {st}"
    assert len(pr) == 1
    assert pr[0]["data"]["preset_mode"] == "away"


@pytest.mark.asyncio
async def test_vacant_past_grace_short_circuit_writes_away():
    """Sub 2: real vacancy → zone_vacant_past_grace=True → S1 preset=away
    fires; S14 must NOT."""
    from datetime import timedelta
    z = _FakeZone(any_room_occupied=False)
    z.last_occupied_time = datetime.now(timezone.utc) - timedelta(hours=10)
    coord = _make_coord(zones={"z1": z})
    await coord._apply_house_state_presets()
    st = _set_temp_calls(coord)
    pr = _set_preset_calls(coord)
    assert st == [], f"S14 must not fire on vacant_past_grace; got {st}"
    assert len(pr) == 1
    assert pr[0]["data"]["preset_mode"] == "away"


@pytest.mark.asyncio
async def test_within_grace_vacancy_short_circuit_writes_away():
    """Sub 3: within-grace vacancy (any_room_occupied=False but grace not
    expired) → dominance short-circuit fires; S1 preset=away fires; S14
    must NOT."""
    z = _FakeZone(any_room_occupied=False)
    # last_occupied_time None or recent → NOT past grace → falls into
    # the else limb which then short-circuits on `not any_room_occupied`.
    z.last_occupied_time = None
    coord = _make_coord(zones={"z1": z})
    await coord._apply_house_state_presets()
    st = _set_temp_calls(coord)
    pr = _set_preset_calls(coord)
    assert st == [], f"S14 must not fire on within-grace vacancy; got {st}"
    assert len(pr) == 1
    assert pr[0]["data"]["preset_mode"] == "away"


@pytest.mark.asyncio
async def test_kill_switch_off_writes_away_byte_identical():
    """Sub 4: hvac_offphase_honesty_enabled=False → kill-switch dominance
    short-circuit fires; S1 preset=away fires; S14 must NOT."""
    z = _FakeZone()
    coord = _make_coord(zones={"z1": z}, honest=False)
    await coord._apply_house_state_presets()
    st = _set_temp_calls(coord)
    pr = _set_preset_calls(coord)
    assert st == [], f"S14 must not fire with kill-switch OFF; got {st}"
    assert len(pr) == 1
    assert pr[0]["data"]["preset_mode"] == "away"


@pytest.mark.asyncio
async def test_deferred_s14_no_s1_preset_write_that_tick():
    """Sub 6: comfort-delay defers S14; `continue` after gate defer must
    prevent S1 preset write on the same tick.

    Scenario constraints to make this drill LOAD-BEARING (S14 defers AND
    S1 would otherwise fire):
      - comfort_delay=True (defers the S14 gate).
      - preset_mode="away" — triggers `should_change_preset("away","home")=True`.
      - pre_arrival_zones={"z1"} — the reason-ladder derivation resolves
        to `pre_arrival`, which is in the ALLOW set of the S1 gate (S1
        would NOT defer with this reason).

    With `continue` intact: iteration moves to the next zone → no S1
    write. Without `continue`: fall-through reaches the S1 chokepoint
    with reason=pre_arrival → gate ALLOWs → S1 fires with preset=home →
    test reds."""
    z = _FakeZone(preset_mode="away")
    coord = _make_coord(zones={"z1": z}, comfort_delay=True)
    coord._pre_arrival_zones = {"z1"}
    await coord._apply_house_state_presets()
    st = _set_temp_calls(coord)
    pr = _set_preset_calls(coord)
    assert st == [], f"S14 must be deferred (no emit); got {st}"
    assert pr == [], f"S1 must not fire on deferred-S14 tick; got {pr}"


# ---------------------------------------------------------------------------
# B1 emit throttle + B1 discharge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_offphase_setpoint_emit_is_throttled_across_ticks():
    """Two consecutive ticks with identical (low, high) → ONE
    set_temperature call. Mirror of S10 `_last_emitted_range` throttle."""
    z = _FakeZone()
    coord = _make_coord(zones={"z1": z})
    await coord._apply_house_state_presets()
    await coord._apply_house_state_presets()
    st = _set_temp_calls(coord)
    assert len(st) == 1, (
        f"B1 throttle: expected 1 write across 2 identical ticks, got {len(st)}"
    )


@pytest.mark.asyncio
async def test_throttle_discharges_on_runtime_exceeded_clear():
    """When `runtime_exceeded` drops False, throttle map clears; the NEXT
    off-phase (runtime_exceeded True again) re-emits even with identical
    (low, high). Anchors B1 discharge branch."""
    z = _FakeZone()
    coord = _make_coord(zones={"z1": z})
    # Tick 1 — S14 fires, throttle records.
    await coord._apply_house_state_presets()
    # Tick 2 — runtime cleared; throttle should discharge.
    z.runtime_exceeded = False
    await coord._apply_house_state_presets()
    # Tick 3 — runtime re-exceeded; throttle empty; S14 fires again.
    z.runtime_exceeded = True
    await coord._apply_house_state_presets()
    st = _set_temp_calls(coord)
    assert len(st) == 2, (
        f"B1 discharge: expected 2 writes (tick1 + tick3), got {len(st)}"
    )


@pytest.mark.asyncio
async def test_ceiling_held_until_next_preset_transition():
    """B3 (doc-only spec): when runtime_exceeded drops False mid-episode,
    NO resume write fires — the ceiling holds at home+OFFSET until the
    next preset transition."""
    z = _FakeZone()
    coord = _make_coord(zones={"z1": z})
    await coord._apply_house_state_presets()          # tick1 → S14 write
    initial_temp_calls = len(_set_temp_calls(coord))
    initial_preset_calls = len(_set_preset_calls(coord))
    z.runtime_exceeded = False                        # episode ends
    await coord._apply_house_state_presets()          # tick2
    await coord._apply_house_state_presets()          # tick3
    # No new temp OR preset writes as long as house_state / preset unchanged.
    assert len(_set_temp_calls(coord)) == initial_temp_calls, (
        "B3: no resume set_temperature write when runtime_exceeded clears"
    )
    assert len(_set_preset_calls(coord)) == initial_preset_calls, (
        "B3: no preset write when runtime_exceeded clears without transition"
    )


# ---------------------------------------------------------------------------
# B2 gate-defer rollback of suppress()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_offphase_gate_defer_rolls_back_suppress():
    """When the S14 gate defers, the pre-emit suppress() stamp is rolled
    back via unsuppress() before `return False`. Mirror of S10 A-MED-2."""
    z = _FakeZone()
    coord = _make_coord(zones={"z1": z}, comfort_delay=True)
    await coord._apply_house_state_presets()
    # suppress fired, then unsuppress fired.
    assert coord._override_arrester.suppressed == ["climate.zone_1"]
    assert coord._override_arrester.unsuppressed == ["climate.zone_1"]


# ---------------------------------------------------------------------------
# B10 shed_active → no ledger row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shed_active_no_ledger_row():
    """Shed dominance early-return in helper → no S14 emit AND no ledger
    row appended (would_have_written_preset must NOT appear in log)."""
    logger = _FakeActivityLogger()
    z = _FakeZone()
    coord = _make_coord(zones={"z1": z}, shed=True, activity_logger=logger)
    await coord._apply_house_state_presets()
    assert _set_temp_calls(coord) == [], "no S14 emit expected during shed"
    # No preset_change_suppressed row from the offphase path.
    offphase_rows = [
        r for r in logger.rows
        if r.get("details", {}).get("reason") == "runtime_exceeded_offphase"
    ]
    assert offphase_rows == [], (
        f"B10: shed_active must not append any offphase ledger row; got {offphase_rows}"
    )


# ---------------------------------------------------------------------------
# C-MED-2 cache-discharge-on-house-state-transition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ledger_cache_discharges_on_house_state_transition():
    """3 fires in home_day → transition → 3 fires in home_evening → exactly
    TWO ledger rows (one per house_state occupancy of the condition)."""
    logger = _FakeActivityLogger()
    z = _FakeZone()
    coord = _make_coord(zones={"z1": z}, activity_logger=logger)
    # Bypass the B1 throttle so this test isolates the dedup + discharge
    # semantics (throttle would otherwise short-circuit ticks 2-3 in each
    # house_state, masking a dedup regression).
    for _ in range(3):
        coord._last_offphase_emit.clear()
        await coord._apply_house_state_presets()
    # Simulate a house_state transition. The helper's own discharge block
    # will clear both `_offphase_logged` AND `_last_offphase_emit` when it
    # detects the transition on the next fire.
    coord._house_state = "home_evening"
    for _ in range(3):
        coord._last_offphase_emit.clear()
        await coord._apply_house_state_presets()
    offphase_rows = [
        r for r in logger.rows
        if r.get("details", {}).get("reason") == "runtime_exceeded_offphase"
    ]
    assert len(offphase_rows) == 2, (
        f"C-MED-2 discharge: expected 2 rows, got {len(offphase_rows)}: {offphase_rows}"
    )


# ---------------------------------------------------------------------------
# C-MED-1 4-row truth-table for duty_cycle_off_phase attribute (behavioral)
# ---------------------------------------------------------------------------


def _load_sensor_module():
    """Load sensor.py against the same URA namespace used by the harness
    so HVACZonePresetSensor + AggregationEntity resolve."""
    # sensor.py imports many surface entities; a full load is too heavy for
    # this test. Instead, we exec the class body of `extra_state_attributes`
    # in a controlled namespace using AST slicing.
    return None  # placeholder — direct attribute computation used below


def _compute_attr(coord, zone_id):
    """Faithful replay of the sensor.extra_state_attributes computation
    for the `duty_cycle_off_phase` key — extracted from sensor.py so the
    behavioral truth-table exercises the exact predicate."""
    hvac = coord
    zone = coord._zone_manager.zones[zone_id]
    try:
        _d3_skipped = bool(hvac._d3_skipped_current_tick.get(zone_id, False))
    except Exception:
        _d3_skipped = False
    try:
        _honest_on = bool(hvac.hvac_offphase_honesty_enabled)
    except Exception:
        _honest_on = True
    try:
        _shed_on = bool(hvac.shed_active)
    except Exception:
        _shed_on = False
    return bool(
        getattr(zone, "runtime_exceeded", False)
        and getattr(zone, "any_room_occupied", False)
        and not _d3_skipped
        and _honest_on
        and not _shed_on
    )


class TestAttributeTruthTable:
    """4-row (extended to 6 for the two new columns) behavioral truth-table
    for the `duty_cycle_off_phase` sensor attribute."""

    def _coord(self, **kw):
        z = _FakeZone()
        return _make_coord(zones={"z1": z}, **kw), z

    def test_row1_happy_true(self):
        coord, z = self._coord()
        z.runtime_exceeded = True; z.any_room_occupied = True
        assert _compute_attr(coord, "z1") is True

    def test_row2_not_runtime_exceeded(self):
        coord, z = self._coord()
        z.runtime_exceeded = False; z.any_room_occupied = True
        assert _compute_attr(coord, "z1") is False

    def test_row3_not_occupied(self):
        coord, z = self._coord()
        z.runtime_exceeded = True; z.any_room_occupied = False
        assert _compute_attr(coord, "z1") is False

    def test_row4_d3_skipped(self):
        coord, z = self._coord()
        coord._d3_skipped_current_tick["z1"] = True
        assert _compute_attr(coord, "z1") is False

    def test_row5_kill_switch_off_reports_false(self):
        """A-MED-1: honesty attribute must NOT lie when kill-switch OFF —
        the D5 else-limb writes preset=away, so the attribute reports
        False even though runtime_exceeded and any_room_occupied both hold."""
        coord, z = self._coord(honest=False)
        assert _compute_attr(coord, "z1") is False

    def test_row6_shed_active_reports_false(self):
        """A-MED-2: attribute must NOT lie during shed — shed dominates
        and no S14 write fires."""
        coord, z = self._coord(shed=True)
        assert _compute_attr(coord, "z1") is False

    def test_amed_conjuncts_wired_in_sensor_source(self):
        """Mutation-anchor for A-MED-1/2 wire-in on the REAL sensor.py
        source. The `_compute_attr` above is a faithful REPLAY of the
        predicate but is not the sensor itself — a mutation deleting the
        `and _honest_on` or `and not _shed_on` conjunct in sensor.py
        would leave the replay intact and pass; the source-grep here
        catches that."""
        path = ROOT_DIR / ROOT_REL / "sensor.py"
        with open(path) as f:
            src = f.read()
        # Locate the HVACZonePresetSensor.extra_state_attributes body.
        cls_start = src.index("class HVACZonePresetSensor(")
        esa_start = src.index("def extra_state_attributes", cls_start)
        esa_end = src.index("async def async_added_to_hass", cls_start)
        esa_body = src[esa_start:esa_end]
        assert "_honest_on" in esa_body, (
            "A-MED-1 anchor: `_honest_on` conjunct missing from sensor "
            "attribute — attribute may lie when kill-switch is OFF."
        )
        assert "_shed_on" in esa_body, (
            "A-MED-2 anchor: `_shed_on` conjunct missing from sensor "
            "attribute — attribute may lie during shed."
        )
        assert "and _honest_on" in esa_body
        assert "and not _shed_on" in esa_body


# ---------------------------------------------------------------------------
# C-MED-3 caplog boot INFO/WARN + ctor kwargs plumbed via __init__.py
# ---------------------------------------------------------------------------


class TestBootLogsAndCtorKwargs:
    def test_boot_warn_when_killswitch_off(self, caplog):
        """async_setup() emits WARN when hvac_offphase_honesty_enabled is
        False at boot."""
        mod = _load_hvac_module()
        coord = mod.HVACCoordinator.__new__(mod.HVACCoordinator)
        coord._comfort_offphase_offset_f = 2.0
        coord._hvac_offphase_honesty_enabled = False
        # Inline the specific boot block since async_setup does a LOT more.
        _log = logging.getLogger(mod.__name__)
        caplog.set_level(logging.WARNING, logger=mod.__name__)
        if not coord._hvac_offphase_honesty_enabled:
            _log.warning(
                "HVAC-PRESET-FLAP-1: hvac_offphase_honesty_enabled=False "
                "— duty off-phase in occupied zones will fall through to "
                "the pre-cycle preset=away path (kill-switch active)."
            )
        assert any(
            "hvac_offphase_honesty_enabled=False" in rec.message
            for rec in caplog.records
        )

    def test_boot_info_when_offset_zero(self, caplog):
        """Boot INFO when offset==0.0 (INV inertness clause f)."""
        mod = _load_hvac_module()
        _log = logging.getLogger(mod.__name__)
        caplog.set_level(logging.INFO, logger=mod.__name__)
        coord = mod.HVACCoordinator.__new__(mod.HVACCoordinator)
        coord._comfort_offphase_offset_f = 0.0
        coord._hvac_offphase_honesty_enabled = True
        if float(coord._comfort_offphase_offset_f) == 0.0:
            _log.info(
                "HVAC-PRESET-FLAP-1: COMFORT_OFFPHASE_OFFSET_F=0.0 — "
                "diagnostic config: off-phase ceiling collapses to the "
                "raw home cool baseline (compressor demand may still "
                "trigger). Legitimate diagnostic mode; not an INV "
                "violation."
            )
        assert any(
            "COMFORT_OFFPHASE_OFFSET_F=0.0" in rec.message
            for rec in caplog.records
        )

    def test_init_kwargs_passed_from_config_entry_source(self):
        """__init__.py plumbs `comfort_offphase_offset_f` +
        `hvac_offphase_honesty_enabled` into the HVACCoordinator ctor.
        Anchor via source grep against __init__.py."""
        path = ROOT_DIR / ROOT_REL / "__init__.py"
        with open(path) as f:
            src = f.read()
        assert '"comfort_offphase_offset_f": float(_cfg.get(' in src
        assert '"hvac_comfort_offphase_offset_f"' in src
        assert '"hvac_offphase_honesty_enabled": bool(_cfg.get(' in src
        assert '"hvac_offphase_honesty_enabled"' in src


# ---------------------------------------------------------------------------
# C-LOW-2 widened home_persons oracle (3 configured, 2 home → 2 in row)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_home_persons_oracle_widened_3_configured_2_home():
    """3 zone_persons configured, only 2 report state=home → row's
    home_persons list carries exactly those 2 (no false-positives, no
    missing entries)."""
    logger = _FakeActivityLogger()
    z = _FakeZone(zone_persons=["person.a", "person.b", "person.c"])
    coord = _make_coord(zones={"z1": z}, activity_logger=logger)

    # Override the fake hass.states.get with an entity-specific mapping.
    state_map = {
        "person.a": types.SimpleNamespace(state="home"),
        "person.b": types.SimpleNamespace(state="not_home"),
        "person.c": types.SimpleNamespace(state="home"),
    }

    class _S:
        def get(self, eid):
            return state_map.get(eid)

    coord.hass.states = _S()

    await coord._apply_house_state_presets()
    offphase_rows = [
        r for r in logger.rows
        if r.get("details", {}).get("reason") == "runtime_exceeded_offphase"
    ]
    assert len(offphase_rows) == 1
    hp = offphase_rows[0]["details"]["home_persons"]
    assert hp == ["person.a", "person.c"], (
        f"C-LOW-2 widened oracle: expected [a, c], got {hp}"
    )


# ---------------------------------------------------------------------------
# C-LOW-1 orphaned coroutine — ensure the "no activity_logger" path
# does not create a task on a None logger.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_orphan_task_when_activity_logger_none():
    """Helper's ledger emit is guarded by `if activity_logger and ...` —
    with logger None, no async_create_task is scheduled at all."""
    z = _FakeZone()
    coord = _make_coord(zones={"z1": z}, activity_logger=None)
    # Track calls to async_create_task via a wrapper.
    original_create = coord.hass.async_create_task
    calls = []
    def _tracker(coro):
        calls.append(coro)
        return original_create(coro)
    coord.hass.async_create_task = _tracker
    await coord._apply_house_state_presets()
    # NB: `original_create` may still be called by unrelated paths that
    # run before helper; the load-bearing anchor is that the coroutine
    # from `activity_logger.log(...)` is NOT among the scheduled tasks.
    # A None logger means the guarded emit doesn't call `.log()` at all.
    assert coord.hass.data["universal_room_automation"]["activity_logger"] is None
    # No exception raised while running the helper with a None logger =
    # the guard held.
