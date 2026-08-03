"""hotfix/fan-sweep-trio (2026-08-03).

Three surgical fixes to the HVAC comfort-fan controller + one memory-
instrumentation surface. See the branch-level task contract for full
prose; below are the load-bearing assertions per fix.

FIX A — HVACFanControlSwitch deferred restore
    Old code used ``async_call_later(hass, 5, self._retry_restore)`` —
    a single 5-second one-shot. Ported to the v4.7.3.1 signal pattern
    (SIGNAL_HVAC_COORDINATOR_READY + _deferred_value hygiene). Tests
    mirror the existing test_v4731_hvac_switches_restore.py source-
    contract style.

FIX B — Adopted-fan cooldown + doubled vacancy hold
    Adoption branch (~hvac_fans.py:248-292) now sets
    ``manual_off_cooldown_until = now + DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S``,
    and vacancy-off timing uses ``FAN_ADOPTED_VACANCY_HOLD_MULT (=2.0) *
    DEFAULT_FAN_VACANCY_HOLD`` when ``room_fan.trigger == "external"``.
    URA-lit fans are untouched.

FIX C — actuation_conflict episode
    New registered episode type in const.MEMORY_EPISODE_TYPES.
    ``_set_fan_state(on=False, room_name=...)`` calls the observer
    helper which writes an episode via the DAO IFF
    ``binary_sensor.<slug>_occupied == "on"``.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

# Reuse the HA-module mocking preamble + real-source module loading from
# the 2026-08-01 incident-replay test. Importing it installs the mocked
# `homeassistant.*` modules into sys.modules and loads the real
# hvac_fans / const / hvac_const modules under the canonical package
# path — the same production-code paths this hotfix is instrumenting.
import quality.tests.test_fan_incident_2026_08_01_replay  # noqa: F401

# LOW-B3 / HIGH-B2 fix-up (2026-08-03): load the real memory_facade
# module so the shared _slugify import in hvac_fans works and the
# slug-parity test can compare against it. memory_facade only imports
# from .const + stdlib — safe to load once the HA-mock preamble above
# has installed the mocked homeassistant.* modules.
import importlib.util as _iu  # noqa: E402
import os as _os  # noqa: E402
import sys as _sys  # noqa: E402
_mf_key = "custom_components.universal_room_automation.memory_facade"
if _mf_key not in _sys.modules:
    _mf_path = _os.path.join(
        "custom_components", "universal_room_automation", "memory_facade.py",
    )
    _spec = _iu.spec_from_file_location(_mf_key, _mf_path)
    _mod = _iu.module_from_spec(_spec)
    _sys.modules[_mf_key] = _mod
    _spec.loader.exec_module(_mod)


SWITCH_PY_PATH = os.path.join(
    "custom_components", "universal_room_automation", "switch.py",
)
HVAC_FANS_PY_PATH = os.path.join(
    "custom_components", "universal_room_automation",
    "domain_coordinators", "hvac_fans.py",
)


# ---------------------------------------------------------------------------
# FIX A — HVACFanControlSwitch: source-anchor tests
# ---------------------------------------------------------------------------


class TestFixAHVACFanControlSwitchDeferredRestore:
    """Source-mirror contract for the deferred-restore port."""

    @pytest.fixture
    def switch_body(self) -> str:
        with open(SWITCH_PY_PATH) as f:
            source = f.read()
        start = source.find("class HVACFanControlSwitch")
        assert start > 0, "HVACFanControlSwitch must exist"
        next_class = source.find("\nclass ", start + 1)
        return source[start:next_class] if next_class > 0 else source[start:]

    def test_deferred_value_field_declared(self, switch_body: str) -> None:
        assert "self._deferred_value" in switch_body, (
            "HVACFanControlSwitch must declare self._deferred_value "
            "(FIX A: mirror ECSwitch/HVACOverrideArresterSwitch hygiene)"
        )

    def test_subscribes_to_hvac_coordinator_ready_signal(
        self, switch_body: str,
    ) -> None:
        assert "SIGNAL_HVAC_COORDINATOR_READY" in switch_body, (
            "HVACFanControlSwitch must subscribe to "
            "SIGNAL_HVAC_COORDINATOR_READY (FIX A: replaces one-shot 5s "
            "async_call_later retry)"
        )
        assert "async_dispatcher_connect" in switch_body, (
            "Signal subscription must use async_dispatcher_connect"
        )
        assert "async_on_remove" in switch_body, (
            "Dispatcher unsub must be tracked via async_on_remove "
            "(Bug Class #38)"
        )

    def test_handle_hvac_ready_is_callback(self, switch_body: str) -> None:
        assert "_handle_hvac_ready" in switch_body, (
            "HVACFanControlSwitch must define _handle_hvac_ready"
        )
        handle_pos = switch_body.find("def _handle_hvac_ready")
        pre = switch_body[max(0, handle_pos - 30):handle_pos]
        assert "@callback" in pre, (
            "_handle_hvac_ready must be @callback decorated (Bug Class "
            "#42/#19: bound method + synchronous callback)"
        )

    def test_one_shot_retry_pattern_removed(self, switch_body: str) -> None:
        """The old async_call_later(5s) retry must be gone."""
        assert "async_call_later" not in switch_body, (
            "FIX A: HVACFanControlSwitch must NOT use async_call_later — "
            "replaced by SIGNAL_HVAC_COORDINATOR_READY pattern"
        )
        assert "_retry_restore" not in switch_body, (
            "FIX A: _retry_restore method must be removed"
        )
        assert "_deferred_restore_state" not in switch_body, (
            "FIX A: _deferred_restore_state field must be removed "
            "(replaced by _deferred_value)"
        )

    def test_unavailable_state_guarded(self, switch_body: str) -> None:
        assert 'not in ("on", "off")' in switch_body, (
            "FIX A: MED-1 alignment — 'unavailable'/'unknown' last_state "
            "must not be parsed as False"
        )


# ---------------------------------------------------------------------------
# FIX B + FIX C — behavioral tests via real FanController.update()
# ---------------------------------------------------------------------------

# Import production symbols under test.
from custom_components.universal_room_automation.domain_coordinators.hvac_const import (  # noqa: E402
    DEFAULT_FAN_VACANCY_HOLD,
    FAN_ADOPTED_VACANCY_HOLD_MULT,
)
from custom_components.universal_room_automation.const import (  # noqa: E402
    DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S,
    DOMAIN,
    MEMORY_EPISODE_TYPES,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_fans import (  # noqa: E402
    FanController,
    RoomFanState,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    hvac_fans as _hvac_fans_mod,
)


# ---- Test harness (mirrors test_fan_incident_2026_08_01_replay.py) ----


def _set_now(dt: datetime) -> None:
    fn = lambda: dt  # noqa: E731
    _hvac_fans_mod.dt_util.now = fn
    _hvac_fans_mod.dt_util.utcnow = fn


@pytest.fixture(autouse=True)
def _restore_dt_util():
    yield
    default = lambda: datetime.utcnow()  # noqa: E731
    _hvac_fans_mod.dt_util.now = default
    _hvac_fans_mod.dt_util.utcnow = default


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_controller(
    *,
    entity_on: bool,
    entity_speed: int = 66,
    occupied: bool = False,
    room_temp: float = 85.0,
    setpoint_high: float = 72.0,
    room_slug: str = "study_a",
    occ_binary_on: bool = False,
    db_writes: list | None = None,
):
    """Build a FanController wired up like the incident-replay harness,
    with optional occupancy binary_sensor + a DB spy for FIX C.
    """
    hass = MagicMock()
    hass.services = MagicMock()
    svc_log: list = []

    async def _async_call(domain, service, data=None, **kwargs):
        svc_log.append((domain, service, dict(data or {})))

    hass.services.async_call = _async_call

    state = {"on": entity_on, "pct": entity_speed}

    class _EntState:
        def __init__(self, s, attrs=None):
            self.state = s
            self.attributes = attrs or {}

    fan_entity = "fan.test_fan"
    occ_entity = f"binary_sensor.{room_slug}_occupied"

    def _get_state(entity_id):
        if entity_id == fan_entity:
            return _EntState(
                "on" if state["on"] else "off",
                {"percentage": state["pct"]},
            )
        if entity_id == occ_entity:
            return _EntState("on" if occ_binary_on else "off")
        return None

    hass.states.get = _get_state

    # Wire hass.data for the memory-episode writer (FIX C). Keep
    # log_memory_episode SYNC so the writer's `db.log_memory_episode(**k)`
    # returns immediately with the captured call — and hass.async_create_task
    # can be a no-op that discards whatever it's handed (real prod passes
    # a coroutine; here we've made it synchronous for observability).
    db = MagicMock()
    write_log = db_writes if db_writes is not None else []

    def _log_episode(**kwargs):
        write_log.append(dict(kwargs))
        return None

    db.log_memory_episode = _log_episode
    hass.data = {DOMAIN: {"database": db}}
    hass.async_create_task = lambda _coro: None

    zone_manager = MagicMock()
    zone = MagicMock()
    zone.target_temp_high = setpoint_high
    rc = MagicMock()
    rc.room_name = "Study A"
    rc.temperature = room_temp
    rc.occupied = occupied
    zone.room_conditions = [rc]
    zone.zone_persons = []
    zone_manager.zones = {"zone_1": zone}

    ctrl = FanController(hass, zone_manager)
    ctrl._resolve_live_fan_sleep_policy = lambda rn, rf: "reduce"

    room_fan = RoomFanState(
        room_name="Study A",
        zone_id="zone_1",
        fan_entities=[fan_entity],
        is_on=False,
        trigger="",
        speed_pct=0,
        vacancy_detected_time="",
        last_on_time="",
    )
    ctrl._room_fans["Study A"] = room_fan

    return ctrl, room_fan, svc_log, write_log


# ---- FIX B tests ----


class TestFixBAdoptionSetsCooldown:
    """Adoption sets manual_off_cooldown_until using the existing const."""

    def test_adoption_sets_cooldown_to_manual_off_const(self):
        base = datetime(2026, 8, 3, 12, 0, 0)
        _set_now(base)
        ctrl, room_fan, _svc, _writes = _make_controller(
            entity_on=True, entity_speed=100, occupied=False,
        )
        assert room_fan.manual_off_cooldown_until == ""

        _run(ctrl.update(energy_constraint=None, house_state="home_day"))

        assert room_fan.trigger == "external", "adoption path must fire"
        assert room_fan.manual_off_cooldown_until != "", (
            "FIX B: adoption must stamp manual_off_cooldown_until"
        )
        expected = base + timedelta(seconds=DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S)
        assert room_fan.manual_off_cooldown_until == expected.isoformat(), (
            "cooldown must reuse DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S "
            "(no new const)"
        )


class TestFixBAdoptedFanNotSweptWithinBaseVacancyHold:
    """Externally-adopted fan survives past the URA-lit vacancy hold."""

    def test_adopted_fan_survives_base_vacancy_hold(self):
        assert FAN_ADOPTED_VACANCY_HOLD_MULT == 2.0, (
            "multiplier changed — test values need updating"
        )
        base = datetime(2026, 8, 3, 12, 0, 0)
        _set_now(base)
        ctrl, room_fan, svc_log, _ = _make_controller(
            entity_on=True, entity_speed=100, occupied=False,
        )

        # Tick 1: adopt (occupied=False here — the incident shape).
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        assert room_fan.trigger == "external"

        # Advance to base_hold + small margin — a URA-lit fan would be
        # swept OFF here. Adopted fan must still be ON.
        _set_now(base + timedelta(seconds=DEFAULT_FAN_VACANCY_HOLD + 30))
        turn_offs_before = sum(
            1 for (_d, s, _dat) in svc_log if s == "turn_off"
        )
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        turn_offs_after = sum(
            1 for (_d, s, _dat) in svc_log if s == "turn_off"
        )
        assert turn_offs_after == turn_offs_before, (
            "FIX B: externally-adopted fan must NOT be swept off within "
            "the URA-lit vacancy hold (multiplier=2x)"
        )

    def test_adopted_fan_swept_after_doubled_vacancy_hold(self):
        base = datetime(2026, 8, 3, 12, 0, 0)
        _set_now(base)
        ctrl, room_fan, svc_log, _ = _make_controller(
            entity_on=True, entity_speed=100, occupied=False,
        )
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        assert room_fan.trigger == "external"

        # Past 2x base + margin — sweep should now fire.
        doubled = int(DEFAULT_FAN_VACANCY_HOLD * FAN_ADOPTED_VACANCY_HOLD_MULT)
        turn_offs_before = sum(
            1 for (_d, s, _dat) in svc_log if s == "turn_off"
        )
        _set_now(base + timedelta(seconds=doubled + 60))
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        turn_offs_after = sum(
            1 for (_d, s, _dat) in svc_log if s == "turn_off"
        )
        assert turn_offs_after > turn_offs_before, (
            "Adopted fan must eventually be swept off — 2x window elapsed"
        )


class TestFixBURALitTimingUnchanged:
    """URA-lit (trigger != 'external') sweep timing preserved."""

    def test_ura_lit_fan_swept_at_base_vacancy_hold(self):
        base = datetime(2026, 8, 3, 12, 0, 0)
        _set_now(base)
        # Prime a URA-lit fan (entity ON, RoomFanState says trigger=
        # "temperature"). This bypasses the external-adoption sync
        # branches and lands directly in the vacancy-hold path.
        ctrl, room_fan, svc_log, _ = _make_controller(
            entity_on=True, entity_speed=66, occupied=False, room_temp=85.0,
        )
        room_fan.is_on = True
        room_fan.trigger = "temperature"
        room_fan.speed_pct = 66
        room_fan.last_on_time = base.isoformat()

        turn_offs_before = sum(
            1 for (_d, s, _dat) in svc_log if s == "turn_off"
        )

        # Two ticks: (1) anchor vacancy_detected_time; (2) past-base-hold
        # tick fires OFF for a URA-lit (trigger != "external") fan.
        _set_now(base + timedelta(seconds=1))
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        assert room_fan.vacancy_detected_time != "", (
            "vacancy anchor must land on first vacant tick"
        )
        assert room_fan.trigger != "external", (
            "trigger must remain URA-lit — external means adopted"
        )

        _set_now(base + timedelta(seconds=DEFAULT_FAN_VACANCY_HOLD + 30))
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        turn_offs_after = sum(
            1 for (_d, s, _dat) in svc_log if s == "turn_off"
        )
        assert turn_offs_after > turn_offs_before, (
            "URA-lit sweep timing must be unchanged (base vacancy hold)"
        )


# ---- FIX C tests ----


class TestFixCActuationConflictEpisodeType:
    """New episode type registered in the vocabulary."""

    def test_actuation_conflict_registered(self):
        assert "actuation_conflict" in MEMORY_EPISODE_TYPES, (
            "FIX C: 'actuation_conflict' must be in MEMORY_EPISODE_TYPES"
        )


class TestFixCOccupiedRoomFanOffEmitsEpisode:
    """Turn-off dispatch against an occupied room writes an episode."""

    def test_writes_episode_when_room_occupied(self):
        base = datetime(2026, 8, 3, 12, 0, 0)
        _set_now(base)
        ctrl, room_fan, svc_log, writes = _make_controller(
            entity_on=True, entity_speed=100,
            occupied=False,  # zone says vacant → sweep path
            occ_binary_on=True,  # but the live occupancy binary sensor is ON
        )
        # Prime: adopt + fast-forward past 2x hold so vacancy-off fires.
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        assert room_fan.trigger == "external"

        doubled = int(DEFAULT_FAN_VACANCY_HOLD * FAN_ADOPTED_VACANCY_HOLD_MULT)
        _set_now(base + timedelta(seconds=doubled + 60))
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))

        conflict_writes = [
            w for w in writes if w.get("episode_type") == "actuation_conflict"
        ]
        assert len(conflict_writes) >= 1, (
            "FIX C: turn-off against an occupied room must emit "
            "actuation_conflict episode"
        )
        w = conflict_writes[0]
        assert w["node_id"] == "room:study_a"
        assert w["adjudication"] == "unadjudicated"
        assert w["adjudicated_by"] == "hvac_fan_controller"
        assert w["attrs"].get("action") == "fan_off"
        assert "trigger" in w["attrs"]

    def test_no_episode_when_room_vacant(self):
        base = datetime(2026, 8, 3, 12, 0, 0)
        _set_now(base)
        ctrl, room_fan, svc_log, writes = _make_controller(
            entity_on=True, entity_speed=100,
            occupied=False, occ_binary_on=False,
        )
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))
        doubled = int(DEFAULT_FAN_VACANCY_HOLD * FAN_ADOPTED_VACANCY_HOLD_MULT)
        _set_now(base + timedelta(seconds=doubled + 60))
        _run(ctrl.update(energy_constraint=None, house_state="home_day"))

        conflict_writes = [
            w for w in writes if w.get("episode_type") == "actuation_conflict"
        ]
        assert conflict_writes == [], (
            "FIX C: vacant room (occupancy binary_sensor OFF) must NOT "
            "emit actuation_conflict"
        )


class TestFixCTurnOffAllManagedSuppressed:
    """LOW-A fix-up (2026-08-03): operator-commanded global sweep is NOT
    a controller-decided conflict — it must NOT emit an episode even
    when the room is occupied. Controller-decided OFF paths still emit
    (covered by TestFixCOccupiedRoomFanOffEmitsEpisode).
    """

    def test_turn_off_all_managed_does_NOT_emit_episode(self):
        base = datetime(2026, 8, 3, 12, 0, 0)
        _set_now(base)
        ctrl, room_fan, _svc, writes = _make_controller(
            entity_on=True, entity_speed=100,
            occupied=True, occ_binary_on=True,
        )
        # Directly mark the fan as running so turn_off_all_managed fires.
        room_fan.is_on = True
        _run(ctrl.turn_off_all_managed())

        conflict_writes = [
            w for w in writes if w.get("episode_type") == "actuation_conflict"
        ]
        assert conflict_writes == [], (
            "LOW-A: turn_off_all_managed is operator-commanded, not a "
            "controller conflict — must NOT emit actuation_conflict "
            "(even in an occupied room)"
        )


# ---------------------------------------------------------------------------
# LOW-B3 fix-up — slugify parity between memory_facade and any inline slug
# ---------------------------------------------------------------------------


class TestLowB3SlugifyParity:
    """LOW-B3: pin that hvac_fans and memory_facade produce identical
    slugs across the room-name alphabet actually observed in prod. If
    they diverge on any of these, the inline copy must be replaced by
    an import of the shared helper (which is what the fix-up does).
    """

    def test_slug_parity_across_room_alphabet(self):
        from custom_components.universal_room_automation.memory_facade import (
            _slugify as facade_slug,
        )

        # Inline shape historically used at hvac_fans._record_actuation_conflict:
        def inline(text: str) -> str:
            return (text or "").lower().replace(" ", "_").replace("-", "_")

        alphabet = [
            "Ziri Bedroom (Bedroom 5)",
            "Study A",
            "Jaya-Bedroom",
            "Master  Bedroom",  # deliberate double space
            "",  # empty-string boundary
            "AV Closet",
        ]
        for name in alphabet:
            assert facade_slug(name) == inline(name), (
                f"LOW-B3: slug divergence for {name!r} — "
                f"facade={facade_slug(name)!r} inline={inline(name)!r}"
            )


# ---------------------------------------------------------------------------
# FIX A behavioral tests — HIGH-B2 fix-up
# ---------------------------------------------------------------------------
#
# Reviewer complaint: FIX A had zero behavioral tests; source-mutation of
# the apply line in _handle_hvac_ready left all 5 static anchors green.
# Approach: parse switch.py, extract the _handle_hvac_ready method body,
# exec it in a controlled namespace, and drive it against a shim instance.
# This is genuinely mutation-sensitive — removing / altering the
# `hvac.fan_control_enabled = self._deferred_value` line changes what
# runs, and the assertions below will fail.
#
# Modeled on test_v4731_hvac_switches_restore.py (mirror pattern for
# lifecycle coverage) but with real production-source extraction for the
# critical apply line.


import ast  # noqa: E402
import textwrap  # noqa: E402


def _extract_method_body(class_name: str, method_name: str, path: str) -> str:
    src = open(path).read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for m in node.body:
                if (
                    isinstance(m, (ast.AsyncFunctionDef, ast.FunctionDef))
                    and m.name == method_name
                ):
                    seg = ast.get_source_segment(src, m)
                    # Strip leading decorators (get_source_segment includes
                    # only the def, not the @callback line, but be defensive).
                    return textwrap.dedent(seg)
    raise AssertionError(f"{class_name}.{method_name} not found in {path}")


class _FanSwitchShim:
    """Minimal object with the attributes _handle_hvac_ready reaches for."""

    def __init__(self, get_hvac):
        self._get_hvac = get_hvac
        self._deferred_value = None
        self.state_writes = 0

    def async_write_ha_state(self):
        self.state_writes += 1


def _load_handle_hvac_ready():
    """Extract + compile the real production _handle_hvac_ready as a
    plain function bound to a shim. Mutation-sensitive: source changes
    to the method flow through to the compiled function.
    """
    body = _extract_method_body(
        "HVACFanControlSwitch", "_handle_hvac_ready", SWITCH_PY_PATH,
    )
    # exec expects the def at module level with no decorators.
    ns: dict = {"_LOGGER": MagicMock()}
    exec(compile(body, "<extracted _handle_hvac_ready>", "exec"), ns)
    return ns["_handle_hvac_ready"]


class TestFixAHandleHVACReadyBehavioral:
    """Behavioral tests over REAL production _handle_hvac_ready source."""

    def test_deferred_off_lands_when_signal_fires(self):
        """Deferred OFF (fan-control-was-off) — signal fires after coord
        arrives → hvac.fan_control_enabled must flip to False.
        """
        _handle_hvac_ready = _load_handle_hvac_ready()

        hvac = MagicMock()
        hvac.fan_control_enabled = True  # constructor default
        shim = _FanSwitchShim(get_hvac=lambda: hvac)
        shim._deferred_value = False

        _handle_hvac_ready(shim)

        assert hvac.fan_control_enabled is False, (
            "HIGH-B2: deferred restore must apply — mutation of the "
            "apply line (e.g. `pass`) makes this assertion fail"
        )
        assert shim._deferred_value is None, (
            "deferred value must be cleared after apply"
        )
        assert shim.state_writes >= 1, "state must be written after apply"

    def test_deferred_on_lands_when_signal_fires(self):
        """Symmetric ON — deferred True is applied on signal."""
        _handle_hvac_ready = _load_handle_hvac_ready()

        hvac = MagicMock()
        hvac.fan_control_enabled = False
        shim = _FanSwitchShim(get_hvac=lambda: hvac)
        shim._deferred_value = True

        _handle_hvac_ready(shim)

        assert hvac.fan_control_enabled is True
        assert shim._deferred_value is None

    def test_no_deferred_value_is_safe_noop(self):
        """If no defer pending, _handle_hvac_ready must NOT touch hvac."""
        _handle_hvac_ready = _load_handle_hvac_ready()

        hvac = MagicMock()
        hvac.fan_control_enabled = True
        shim = _FanSwitchShim(get_hvac=lambda: hvac)
        shim._deferred_value = None

        _handle_hvac_ready(shim)

        assert hvac.fan_control_enabled is True, (
            "no-op path must not mutate hvac"
        )

    def test_coord_still_missing_leaves_defer_intact(self):
        """Signal fires but coord still not in hass.data → defer preserved."""
        _handle_hvac_ready = _load_handle_hvac_ready()

        shim = _FanSwitchShim(get_hvac=lambda: None)
        shim._deferred_value = False

        _handle_hvac_ready(shim)

        assert shim._deferred_value is False, (
            "coord-missing path must preserve deferred value for a later "
            "retry (not silently clear it)"
        )

    def test_operator_turn_on_during_defer_wins(self):
        """Operator toggle-on before signal fires — deferred OFF must be
        discarded so the signal handler is a no-op when it later fires.

        Simulates the async_turn_on() path which sets
        hvac.fan_control_enabled=True and nulls _deferred_value. Then the
        signal fires — the no-op branch runs, leaving True in place.
        """
        _handle_hvac_ready = _load_handle_hvac_ready()

        hvac = MagicMock()
        hvac.fan_control_enabled = False
        shim = _FanSwitchShim(get_hvac=lambda: hvac)
        shim._deferred_value = False  # queued to restore OFF

        # Operator turns ON before coord ready (mirrors async_turn_on
        # semantics from switch.py:3304-3311).
        hvac.fan_control_enabled = True
        shim._deferred_value = None

        # Signal now fires — must be a no-op, leaving ON intact.
        _handle_hvac_ready(shim)

        assert hvac.fan_control_enabled is True, (
            "operator ON must win — deferred restore must not overwrite"
        )


class TestFixAAsyncAddedToHassSourceAnchors:
    """Static contract for async_added_to_hass — signal wiring + defer
    stamping + fast-path apply must be present. These stay lightweight
    because the async method is harder to exec (super().async_added...).
    """

    @pytest.fixture
    def method_src(self) -> str:
        return _extract_method_body(
            "HVACFanControlSwitch", "async_added_to_hass", SWITCH_PY_PATH,
        )

    def test_dispatcher_connect_wired(self, method_src: str) -> None:
        assert "async_dispatcher_connect" in method_src
        assert "SIGNAL_HVAC_COORDINATOR_READY" in method_src
        assert "async_on_remove" in method_src

    def test_fast_path_applies_to_hvac(self, method_src: str) -> None:
        assert "hvac.fan_control_enabled = target" in method_src, (
            "fast path must write target to hvac.fan_control_enabled"
        )

    def test_deferred_path_stamps_target(self, method_src: str) -> None:
        assert "self._deferred_value = target" in method_src, (
            "deferred path must stamp target onto self._deferred_value"
        )
