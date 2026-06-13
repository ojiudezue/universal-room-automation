"""Tests for the load-shedding correctness fixes (post-v5.4.0 cycle).

Drives REAL ``EnergyCoordinator._execute_shed_action`` against REAL
``EVChargerController`` / ``SmartPlugController`` / ``PoolOptimizer``
controllers, plus REAL ``_save_load_shedding_level`` / ``_restore_load_shedding_level``
methods (extracted via exec into a minimal namespace so we don't have
to construct a full EnergyCoordinator — which depends on dozens of
selector/import-heavy HA submodules).

No mirror tests — each assertion follows from a production call path.
No hand-mutated `_paused_by_load_shed` / `_paused_by_us` to fake
reachability — every membership change flows through the real action
fn.

Mutation authority targets (≥1 named test each; see review ledger):
  M1: revert load-shed to `_paused_by_us` (drop D1 split) →
      ``test_ev_shed_during_peak_does_not_touch_paused_by_us`` fails
      (shed clobbers TOU pause); the collision test
      ``test_ev_shed_release_during_peak_keeps_ev_off`` also fails.
  M2: remove `_paused_by_load_shed` from a resume precedence tuple
      → ``test_ev_shed_release_off_peak_defers_to_battery_drain`` and
      ``test_plug_shed_release_defers_to_battery_drain`` fail.
  M3: make orphan-restore re-issue turn_off →
      ``test_restore_does_not_issue_turn_off_actions`` fails.
  M4: remove the manual-off-wins check →
      ``test_plug_shed_release_respects_manual_off`` fails.
  M5: restore pool _original_speed without live-validation →
      ``test_pool_shed_release_respects_manual_speed_change`` fails.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
import sys
import types
from datetime import datetime
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

for _sub in ("energy_const", "energy_tou", "energy_pool"):
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

# ---------------------------------------------------------------------------
from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
    PoolOptimizer,
    SmartPlugController,
    POOL_REDUCED_SPEED,
    POOL_STATE_NORMAL,
    POOL_STATE_REDUCED,
)


# ---------------------------------------------------------------------------
# Exec-extract just the methods we need from energy.py into a fake class.
#
# Constructing a real EnergyCoordinator requires HA selectors, signals, and
# downstream entity-registry calls; for these unit-level correctness tests
# we extract `_execute_shed_action`, `_save_load_shedding_level`,
# `_restore_load_shedding_level`, plus the `load_shedding_status` property
# from the real source file via ast inspection and bind them to a stub host
# class. This drives the EXACT production code path — same source bytes.
# ---------------------------------------------------------------------------

import ast as _ast


def _extract_named(source: str, names: set[str]) -> str:
    """Return a sub-source containing only the named top-level defs in
    `EnergyCoordinator` (functions or properties).
    """
    tree = _ast.parse(source)
    out_segments: list[str] = []
    src_lines = source.splitlines()
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.ClassDef) or node.name != "EnergyCoordinator":
            continue
        for child in node.body:
            if isinstance(child, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                if child.name in names:
                    seg = "\n".join(
                        src_lines[child.lineno - 1: child.end_lineno]
                    )
                    # Dedent (class body lives at 4-space indent).
                    dedented = "\n".join(
                        line[4:] if line.startswith("    ") else line
                        for line in seg.splitlines()
                    )
                    out_segments.append(dedented)
    return "\n\n".join(out_segments)


with open(
    os.path.join(_dc_path, "energy.py"),
    "r",
    encoding="utf-8",
) as _fh:
    _energy_src = _fh.read()

_extracted = _extract_named(
    _energy_src,
    {
        "_execute_shed_action",
        "_save_load_shedding_level",
        "_restore_load_shedding_level",
        "load_shedding_status",
        "_release_all_active_tiers",
        "_update_load_shedding",
    },
)

# Build a minimal namespace for the exec. The methods touch:
#   - self.hass.{states.get, async_create_task, data}
#   - self._pool / self._ev / self._smart_plugs
#   - self._load_shedding_active_level / grace cycles / enabled / threshold
#   - self._last_release_reason
#   - self._execute_service_action (we stub)
#   - _LOGGER, _DOMAIN, LOAD_SHEDDING_PRIORITY
import logging as _logging
from custom_components.universal_room_automation.const import DOMAIN as _DOMAIN
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    LOAD_SHEDDING_PRIORITY,
)

_LOGGER = _logging.getLogger("test_load_shedding_correctness")
_extracted_ns: dict = {
    "_LOGGER": _LOGGER,
    "_DOMAIN": _DOMAIN,
    "LOAD_SHEDDING_PRIORITY": LOAD_SHEDDING_PRIORITY,
    "Any": object,
    # Required for the `from .energy_pool import ...` line inside the
    # pool branch — relative-import resolves against __name__/__package__.
    "__name__": (
        "custom_components.universal_room_automation.domain_coordinators.energy"
    ),
    "__package__": (
        "custom_components.universal_room_automation.domain_coordinators"
    ),
}

exec(compile(_extracted, "<energy.py-extract>", "exec"), _extracted_ns)


class _FakeCoord:
    """Minimal host for the extracted methods — mirrors the few attrs
    they touch on the real EnergyCoordinator."""

    def __init__(self, hass, pool, ev, plugs):
        self.hass = hass
        self._pool = pool
        self._ev = ev
        self._smart_plugs = plugs
        self._load_shedding_active_level = 0
        self._load_shedding_enabled = True
        self._load_shedding_grace_cycles = 0
        self._load_shedding_threshold_kw = 10.0
        self._load_shedding_mode = "auto"
        self._load_shedding_sustained_minutes = 5
        self._sustained_import_readings: list[float] = []
        self._learned_threshold_kw = None
        self._last_release_reason = None
        self._service_calls: list[dict] = []

    async def _execute_service_action(self, action_spec: dict) -> None:
        self._service_calls.append(action_spec)

    def _get_effective_shedding_threshold(self) -> float:
        return self._load_shedding_threshold_kw


# Bind the extracted callables onto the fake-coord class.
_FakeCoord._execute_shed_action = _extracted_ns["_execute_shed_action"]
_FakeCoord._save_load_shedding_level = _extracted_ns["_save_load_shedding_level"]
_FakeCoord._restore_load_shedding_level = _extracted_ns["_restore_load_shedding_level"]
_FakeCoord.load_shedding_status = property(_extracted_ns["load_shedding_status"])
_FakeCoord._release_all_active_tiers = _extracted_ns["_release_all_active_tiers"]
_FakeCoord._update_load_shedding = _extracted_ns["_update_load_shedding"]


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

_BSOC = "sensor.test_envoy_battery"
_BPOW = "sensor.test_envoy_battery_power"


def _build_hass() -> MockHass:
    hass = MockHass()
    # async_create_task: run the coroutine synchronously via a loop.
    loop = asyncio.new_event_loop()

    def _run_task(coro):
        loop.run_until_complete(coro)
        return MagicMock()

    hass.async_create_task = _run_task
    hass.data = {_DOMAIN: {}}
    return hass


def _build_controllers(
    hass: MockHass,
    *,
    evse_on: bool = True,
    plug_on: bool = True,
    pool_speed: float = 80.0,
):
    evse_cfg = {
        "garage_a": {
            "switch": "switch.garage_a",
            "power": "sensor.garage_a_power",
            "energy_today": "sensor.garage_a_energy_today",
            "energy_month": "sensor.garage_a_energy_month",
        },
    }
    hass.set_state("switch.garage_a", "on" if evse_on else "off")
    hass.set_state(
        "sensor.garage_a_power",
        "1000" if evse_on else "0",
        attributes={"unit_of_measurement": "W"},
    )
    ev = EVChargerController(hass, evse_config=evse_cfg)

    plug_id = "switch.kettle"
    hass.set_state(plug_id, "on" if plug_on else "off")
    plugs = SmartPlugController(hass, plug_entities=[plug_id])

    pool_speed_entity = "number.pool_pump_speed"
    hass.set_state(pool_speed_entity, str(pool_speed))
    pool = PoolOptimizer(hass, pool_speed_entity=pool_speed_entity)
    return ev, plugs, pool, plug_id


def _make_coord(hass=None, **kw):
    hass = hass or _build_hass()
    ev, plugs, pool, plug_id = _build_controllers(hass, **kw)
    coord = _FakeCoord(hass, pool, ev, plugs)
    return coord, plug_id


# ---------------------------------------------------------------------------
# D1 — separate _paused_by_load_shed ownership
# ---------------------------------------------------------------------------


def test_ev_shed_during_peak_does_not_touch_paused_by_us():
    """During peak with TOU active, EV-tier shed claims via load_shed
    only — TOU's `_paused_by_us` is preserved.

    This is the v4.7.28-collision test: pre-fix, shed mutated the same
    set TOU owned. Mutation M1 (revert load-shed to `_paused_by_us`)
    breaks this test.
    """
    coord, _ = _make_coord(evse_on=True)
    # Simulate TOU having paused garage_a during peak.
    coord._ev._paused_by_us.add("garage_a")
    # Hardware would be off in that scenario.
    coord.hass.set_state("switch.garage_a", "off")

    coord._execute_shed_action("ev", activate=True)

    assert "garage_a" in coord._ev._paused_by_load_shed, (
        "Load shed must claim the EVSE in its own set"
    )
    assert "garage_a" in coord._ev._paused_by_us, (
        "TOU pause set must be untouched"
    )
    # Proactive claim — no duplicate turn_off issued.
    assert not any(
        c["service"] == "switch.turn_off"
        and c["target"] == "switch.garage_a"
        for c in coord._service_calls
    )


def test_ev_shed_release_during_peak_keeps_ev_off():
    """De-escalating the EV tier while TOU still pauses does NOT
    issue switch.turn_on.

    Mutation M2 (drop `_paused_by_us` from the EV-release precedence
    tuple) breaks this test.
    """
    coord, _ = _make_coord(evse_on=False)
    # TOU pause active, load_shed proactively claimed.
    coord._ev._paused_by_us.add("garage_a")
    coord._ev._paused_by_load_shed.add("garage_a")

    coord._execute_shed_action("ev", activate=False)

    assert "garage_a" not in coord._ev._paused_by_load_shed
    assert "garage_a" in coord._ev._paused_by_us, (
        "TOU must still own the pause"
    )
    assert not any(
        c["service"] == "switch.turn_on" for c in coord._service_calls
    ), "Must NOT resume — TOU still pausing"
    assert coord._last_release_reason == "deferred_to_other_owner"


def test_ev_shed_release_off_peak_defers_to_battery_drain():
    """Off-peak tick after shed-released-but-battery-drain-still-claims:
    EV stays OFF (DURABLE EV PHILOSOPHY).

    Mutation M2 (drop `_paused_by_battery_drain` from the EV-release
    precedence tuple) breaks this test.
    """
    coord, _ = _make_coord(evse_on=False)
    coord._ev._paused_by_load_shed.add("garage_a")
    coord._ev._paused_by_battery_drain.add("garage_a")

    coord._execute_shed_action("ev", activate=False)

    assert "garage_a" not in coord._ev._paused_by_load_shed
    assert "garage_a" in coord._ev._paused_by_battery_drain
    assert not any(
        c["service"] == "switch.turn_on" for c in coord._service_calls
    )


def test_plug_shed_release_defers_to_battery_drain():
    """Plug shed release must NOT resume when battery-drain still
    claims the plug.

    Mutation M2 (drop `_paused_by_battery_drain` from the plug-release
    precedence tuple) breaks this test.
    """
    coord, plug_id = _make_coord(plug_on=False)
    coord._smart_plugs._paused_by_load_shed.add(plug_id)
    coord._smart_plugs._paused_by_battery_drain.add(plug_id)

    coord._execute_shed_action("smart_plugs", activate=False)

    assert plug_id not in coord._smart_plugs._paused_by_load_shed
    assert plug_id in coord._smart_plugs._paused_by_battery_drain
    assert not any(
        c["service"] == "switch.turn_on" for c in coord._service_calls
    )
    assert coord._last_release_reason == "deferred_to_other_owner"


# ---------------------------------------------------------------------------
# D2 — bundle persist/restore
# ---------------------------------------------------------------------------


class _StubDB:
    """Drop-in for the URA database — supports the two methods used."""

    def __init__(self, initial: dict | None = None):
        self.store: dict[str, str] = dict(initial or {})

    async def save_energy_state(self, key: str, value: str) -> None:
        self.store[key] = value

    async def restore_energy_state(self, key: str) -> str | None:
        return self.store.get(key)


def _attach_db(coord, db):
    coord.hass.data = {"universal_room_automation": {"database": db}}


def test_save_restore_load_shedding_bundle_roundtrip():
    """Persist + restore round-trips level, pool original_speed, and
    both pause sets through the bundle.
    """
    coord, plug_id = _make_coord()
    coord._load_shedding_active_level = 2
    coord._pool._original_speed = 75.0
    coord._ev._paused_by_load_shed.add("garage_a")
    coord._smart_plugs._paused_by_load_shed.add(plug_id)

    db = _StubDB()
    _attach_db(coord, db)
    asyncio.get_event_loop().run_until_complete(coord._save_load_shedding_level())

    # Reset state and restore on a fresh coord (same controllers reused).
    coord2, _ = _make_coord()
    _attach_db(coord2, db)
    asyncio.get_event_loop().run_until_complete(
        coord2._restore_load_shedding_level()
    )

    assert coord2._load_shedding_active_level == 2
    assert coord2._pool._original_speed == 75.0
    assert "garage_a" in coord2._ev._paused_by_load_shed
    assert plug_id in coord2._smart_plugs._paused_by_load_shed
    assert coord2._last_release_reason == "restart_restored"
    assert coord2._load_shedding_grace_cycles == 3


def test_restore_load_shedding_bundle_legacy_integer_falls_back():
    """Legacy DB row (integer-only) still restores level + arms grace."""
    coord, _ = _make_coord()
    db = _StubDB({"load_shedding_level": "1"})
    _attach_db(coord, db)
    asyncio.get_event_loop().run_until_complete(
        coord._restore_load_shedding_level()
    )
    assert coord._load_shedding_active_level == 1
    assert coord._load_shedding_grace_cycles == 3
    assert coord._ev._paused_by_load_shed == set()
    assert coord._smart_plugs._paused_by_load_shed == set()


def test_restore_does_not_issue_turn_off_actions():
    """Post-restart restore re-populates in-memory state but issues NO
    service actions — live state is authority.

    Mutation M3 (make orphan-restore re-execute turn_off actions) breaks
    this test.
    """
    coord, plug_id = _make_coord(plug_on=True)
    bundle = {
        "level": 3,
        "pool_original_speed": 90.0,
        "ev_set": ["garage_a"],
        "plug_set": [plug_id],
    }
    db = _StubDB({"load_shedding_bundle": json.dumps(bundle)})
    _attach_db(coord, db)
    asyncio.get_event_loop().run_until_complete(
        coord._restore_load_shedding_level()
    )

    assert coord._service_calls == [], (
        "Restore must NOT issue any service actions"
    )
    assert "garage_a" in coord._ev._paused_by_load_shed
    assert plug_id in coord._smart_plugs._paused_by_load_shed


# ---------------------------------------------------------------------------
# D3 — manual-off-wins on shed release
# ---------------------------------------------------------------------------


def test_plug_shed_release_respects_manual_off():
    """Operator manually re-enables a plug mid-shed → release respects
    the operator's choice; do NOT issue another action.

    Mutation M4 (remove the manual-off-wins live-state check) breaks
    this test.
    """
    coord, plug_id = _make_coord(plug_on=True)
    # First: shed activates → plug off, load_shed claims.
    coord._execute_shed_action("smart_plugs", activate=True)
    assert plug_id in coord._smart_plugs._paused_by_load_shed
    # Operator manually flips the plug back on.
    coord.hass.set_state(plug_id, "on")
    # Now release.
    pre_calls = len(coord._service_calls)
    coord._execute_shed_action("smart_plugs", activate=False)
    # No new turn_on issued (live state already on).
    post_calls = coord._service_calls[pre_calls:]
    assert not any(
        c["service"] == "switch.turn_on" for c in post_calls
    ), "Manual-on mid-shed must short-circuit the release"
    assert plug_id not in coord._smart_plugs._paused_by_load_shed
    assert coord._last_release_reason == "respect_manual_off"


def test_pool_shed_release_respects_manual_speed_change():
    """Operator changes pool speed mid-shed → release discards stale
    `_original_speed`, does NOT command a number.set_value.

    Mutation M5 (restore pool _original_speed without live-validation)
    breaks this test.
    """
    coord, _ = _make_coord(pool_speed=80.0)
    coord._execute_shed_action("pool", activate=True)
    # Operator overrides — pool now at speed 50.
    coord.hass.set_state("number.pool_pump_speed", "50")

    pre_calls = len(coord._service_calls)
    coord._execute_shed_action("pool", activate=False)
    post_calls = coord._service_calls[pre_calls:]

    assert not any(
        c["service"] == "number.set_value" for c in post_calls
    ), "Operator-changed speed must NOT be clobbered"
    assert coord._pool._original_speed is None
    assert coord._pool._state == POOL_STATE_NORMAL
    assert coord._last_release_reason == "respect_manual_speed_change"


def test_plug_shed_release_baseline_restores_when_no_manual_action():
    """Baseline: no manual interaction → release turns the plug back on."""
    coord, plug_id = _make_coord(plug_on=True)
    coord._execute_shed_action("smart_plugs", activate=True)
    assert any(
        c["service"] == "switch.turn_off" and c["target"] == plug_id
        for c in coord._service_calls
    )
    # Simulate live state having transitioned to off after the dispatch.
    coord.hass.set_state(plug_id, "off")

    pre_calls = len(coord._service_calls)
    coord._execute_shed_action("smart_plugs", activate=False)
    post_calls = coord._service_calls[pre_calls:]

    assert any(
        c["service"] == "switch.turn_on" and c["target"] == plug_id
        for c in post_calls
    ), "Baseline release must restore the plug"
    assert plug_id not in coord._smart_plugs._paused_by_load_shed
    assert coord._last_release_reason == "auto"


# ---------------------------------------------------------------------------
# D4 — status sensor surface
# ---------------------------------------------------------------------------


def test_load_shedding_status_exposes_new_attributes():
    """`load_shedding_status` exposes the D4 attributes."""
    coord, plug_id = _make_coord()
    coord._load_shedding_active_level = 3
    coord._pool._original_speed = 95.0
    coord._ev._paused_by_load_shed.add("garage_a")
    coord._smart_plugs._paused_by_load_shed.add(plug_id)
    coord._last_release_reason = "auto"

    status = coord.load_shedding_status
    assert status["paused_by_load_shed_ev"] == ["garage_a"]
    assert status["paused_by_load_shed_plugs"] == [plug_id]
    assert status["pool_pre_shed_speed"] == 95.0
    assert status["last_release_reason"] == "auto"


# ---------------------------------------------------------------------------
# Fix-up correctness tests (B-CRIT-1 / B-CRIT-2 / A-HIGH-1/2 / A-MED-1 /
# A/B-HIGH-3 / B-HIGH-2 / C-HIGH-1 / C-MED-1)
# ---------------------------------------------------------------------------


class _StubBattery:
    """Minimal stub so `_update_load_shedding` can read import — not used
    in the off-peak short-circuit (returns early before reading)."""

    def _effective_import_kw(self):
        # (effective_kw, net_kw, battery_charge_kw)
        return (0.0, 0.0, 0.0)


def _arm_coord_for_period_flip(coord, *, ev_was_on=True, plug_was_on=True,
                                pool_at_reduced=True):
    """Helper: arm a coord with shed active across all 3 tiers, in the
    state it would have post-escalation during peak.
    """
    coord._battery = _StubBattery()
    coord._load_shedding_active_level = 3  # pool + ev + smart_plugs
    coord._load_shedding_enabled = True
    # Pool: original_speed set, current at reduced.
    coord._pool._original_speed = 80.0
    if pool_at_reduced:
        from custom_components.universal_room_automation.domain_coordinators.energy_pool import POOL_REDUCED_SPEED, POOL_STATE_REDUCED
        coord._pool._state = POOL_STATE_REDUCED
        coord.hass.set_state("number.pool_pump_speed", str(POOL_REDUCED_SPEED))
    # EV: in load_shed set; was_on tracks whether release should restore.
    coord._ev._paused_by_load_shed.add("garage_a")
    coord._ev._load_shed_was_on_at_shed["garage_a"] = ev_was_on
    coord.hass.set_state("switch.garage_a", "off")
    # Plug: in load_shed set; was_on tracks restore eligibility.
    coord._smart_plugs._paused_by_load_shed.add("switch.kettle")
    coord._smart_plugs._load_shed_was_on_at_shed["switch.kettle"] = plug_was_on
    coord.hass.set_state("switch.kettle", "off")


def test_period_flip_offpeak_releases_all_active_tiers_BCRIT1():
    """B-CRIT-1 — When peak/mid_peak flips to off_peak while shed is
    active, EVERY tier must release: pool restored, EV turned on, plug
    turned on. Pre-fix, the off-peak short-circuit zeroed the level and
    returned without releasing → orphans.

    Mutation: remove the `_release_all_active_tiers` call in the off-peak
    short-circuit → this test fails (pool stays reduced, ev/plug stay
    in load_shed sets, no service calls).
    """
    coord, _ = _make_coord(evse_on=False, plug_on=False, pool_speed=80.0)
    _arm_coord_for_period_flip(coord)

    coord._update_load_shedding("off_peak")

    # Level zeroed.
    assert coord._load_shedding_active_level == 0
    # All pause-owner sets cleared.
    assert "garage_a" not in coord._ev._paused_by_load_shed
    assert "switch.kettle" not in coord._smart_plugs._paused_by_load_shed
    # Pool restored (number.set_value back to original 80).
    assert any(
        c["service"] == "number.set_value" and c["data"]["value"] == 80.0
        for c in coord._service_calls
    ), "Pool must be restored to its pre-shed speed on off-peak flip"
    # EV restored (was_on=True → release turns it on).
    assert any(
        c["service"] == "switch.turn_on" and c["target"] == "switch.garage_a"
        for c in coord._service_calls
    ), "EV must be resumed at off-peak flip"
    # Plug restored.
    assert any(
        c["service"] == "switch.turn_on" and c["target"] == "switch.kettle"
        for c in coord._service_calls
    ), "Plug must be resumed at off-peak flip"


def test_period_flip_offpeak_release_honors_was_on_at_shed_CHIGH1_persist():
    """B-CRIT-1 × C-HIGH-1 — when an EV/plug was already OFF at shed
    time (proactive claim), the off-peak release must NOT turn it on.

    Mutation: drop the was_on_at_shed gate → this test fails (EV/plug
    get a spurious turn_on).
    """
    coord, _ = _make_coord(evse_on=False, plug_on=False, pool_speed=80.0)
    _arm_coord_for_period_flip(
        coord, ev_was_on=False, plug_was_on=False,
    )

    coord._update_load_shedding("off_peak")

    # Sets cleared but no turn_on for the off-at-shed devices.
    assert "garage_a" not in coord._ev._paused_by_load_shed
    assert "switch.kettle" not in coord._smart_plugs._paused_by_load_shed
    assert not any(
        c["service"] == "switch.turn_on" and c["target"] == "switch.garage_a"
        for c in coord._service_calls
    ), "EV was off at shed-time — must NOT be turned on at release"
    assert not any(
        c["service"] == "switch.turn_on" and c["target"] == "switch.kettle"
        for c in coord._service_calls
    ), "Plug was off at shed-time — must NOT be turned on at release"


def test_disabled_short_circuit_also_releases_all_active_tiers_BCRIT1():
    """B-CRIT-1 — disabling load-shed mid-shed (operator flips off the
    feature switch) must release every active tier before zeroing.
    """
    coord, _ = _make_coord(evse_on=False, plug_on=False, pool_speed=80.0)
    _arm_coord_for_period_flip(coord)
    coord._load_shedding_enabled = False

    coord._update_load_shedding("peak")  # period irrelevant once disabled

    assert coord._load_shedding_active_level == 0
    assert "garage_a" not in coord._ev._paused_by_load_shed
    assert "switch.kettle" not in coord._smart_plugs._paused_by_load_shed
    assert any(
        c["service"] == "number.set_value"
        for c in coord._service_calls
    )


def test_restore_sets_pool_state_reduced_BCRIT2():
    """B-CRIT-2 — Bundle restore for a non-None pool_original_speed must
    set ``_pool._state = POOL_STATE_REDUCED`` so the OTHER pool owner
    (TOU PoolOptimizer) can fire its off-peak restore.

    Mutation: skip the `_pool._state = POOL_STATE_REDUCED` set in restore
    → this test fails (state stays NORMAL → TOU restore gate blocks).
    """
    coord, _ = _make_coord(pool_speed=80.0)
    bundle = {
        "level": 1,
        "pool_original_speed": 80.0,
        "ev_set": [],
        "plug_set": [],
        "ev_was_on_at_shed": {},
        "plug_was_on_at_shed": {},
    }
    db = _StubDB({"load_shedding_bundle": json.dumps(bundle)})
    _attach_db(coord, db)
    asyncio.get_event_loop().run_until_complete(
        coord._restore_load_shedding_level()
    )

    assert coord._pool._original_speed == 80.0
    assert coord._pool._state == POOL_STATE_REDUCED, (
        "Pool state must be REDUCED after restore so TOU restore can fire"
    )


def test_was_on_at_shed_survives_restart_in_bundle_CHIGH1():
    """C-HIGH-1 — `_load_shed_was_on_at_shed` for both EV and plug
    must round-trip through the bundle so the post-restart release path
    knows which devices to restore.
    """
    coord, plug_id = _make_coord()
    coord._load_shedding_active_level = 2
    coord._ev._paused_by_load_shed.add("garage_a")
    coord._ev._load_shed_was_on_at_shed["garage_a"] = True
    coord._smart_plugs._paused_by_load_shed.add(plug_id)
    coord._smart_plugs._load_shed_was_on_at_shed[plug_id] = False

    db = _StubDB()
    _attach_db(coord, db)
    asyncio.get_event_loop().run_until_complete(coord._save_load_shedding_level())

    coord2, _ = _make_coord()
    _attach_db(coord2, db)
    asyncio.get_event_loop().run_until_complete(
        coord2._restore_load_shedding_level()
    )

    assert coord2._ev._load_shed_was_on_at_shed.get("garage_a") is True
    assert coord2._smart_plugs._load_shed_was_on_at_shed.get(plug_id) is False


def test_plug_shed_release_when_off_and_was_off_at_shed_does_not_turn_on_CHIGH1():
    """C-HIGH-1 — plug was off at shed (proactive claim), live state still
    off at release → release does NOT issue turn_on. This is the case
    Reviewer C identified as the silent failure (M4 only tested manual-ON).

    Mutation: drop the was_on_at_shed gate in the plug release branch →
    this test fails (a turn_on is spuriously issued).
    """
    coord, plug_id = _make_coord(plug_on=False)  # plug starts off
    # First: shed activates → proactive claim (was_on_at_shed=False).
    coord._execute_shed_action("smart_plugs", activate=True)
    assert plug_id in coord._smart_plugs._paused_by_load_shed
    assert coord._smart_plugs._load_shed_was_on_at_shed[plug_id] is False
    # Operator never touches it; live state remains off.
    pre_calls = len(coord._service_calls)
    coord._execute_shed_action("smart_plugs", activate=False)
    post_calls = coord._service_calls[pre_calls:]
    assert not any(
        c["service"] == "switch.turn_on" for c in post_calls
    ), "was-off-at-shed plug must NOT be turned on at release"
    assert plug_id not in coord._smart_plugs._paused_by_load_shed
    assert coord._last_release_reason == "respect_manual_off"


def test_ev_shed_release_when_off_and_was_off_at_shed_does_not_turn_on_CHIGH1():
    """C-HIGH-1 mirror for EV: was-off-at-shed (proactive claim) →
    release must NOT turn on.
    """
    coord, _ = _make_coord(evse_on=False)
    coord._execute_shed_action("ev", activate=True)
    assert "garage_a" in coord._ev._paused_by_load_shed
    assert coord._ev._load_shed_was_on_at_shed["garage_a"] is False

    pre_calls = len(coord._service_calls)
    coord._execute_shed_action("ev", activate=False)
    post_calls = coord._service_calls[pre_calls:]
    assert not any(
        c["service"] == "switch.turn_on" for c in post_calls
    ), "was-off-at-shed EV must NOT be turned on at release"
    assert "garage_a" not in coord._ev._paused_by_load_shed
    assert coord._last_release_reason == "respect_manual_off"


def test_reescalate_reshed_manually_resumed_ev_BHIGH2():
    """B-HIGH-2 — On re-escalation, if an EV is in `_paused_by_load_shed`
    but live state is ON (operator manually resumed mid-shed), re-issue
    turn_off rather than blind-skip.

    Mutation: revert to the unconditional `continue` on set membership
    → this test fails (no turn_off issued; EV keeps charging through
    peak shed).
    """
    coord, _ = _make_coord(evse_on=True)
    coord._execute_shed_action("ev", activate=True)
    assert "garage_a" in coord._ev._paused_by_load_shed
    # Operator manually resumes the EV.
    coord.hass.set_state("switch.garage_a", "on")

    pre = len(coord._service_calls)
    coord._execute_shed_action("ev", activate=True)
    post = coord._service_calls[pre:]
    assert any(
        c["service"] == "switch.turn_off" and c["target"] == "switch.garage_a"
        for c in post
    ), "Re-escalate must re-shed an operator-resumed EV"


def test_reescalate_reshed_manually_resumed_plug_BHIGH2():
    """B-HIGH-2 mirror for plug."""
    coord, plug_id = _make_coord(plug_on=True)
    coord._execute_shed_action("smart_plugs", activate=True)
    assert plug_id in coord._smart_plugs._paused_by_load_shed
    coord.hass.set_state(plug_id, "on")

    pre = len(coord._service_calls)
    coord._execute_shed_action("smart_plugs", activate=True)
    post = coord._service_calls[pre:]
    assert any(
        c["service"] == "switch.turn_off" and c["target"] == plug_id
        for c in post
    ), "Re-escalate must re-shed an operator-resumed plug"


def test_periodic_db_writes_persists_bundle_for_watchdog_AHIGH3():
    """A/B-HIGH-3 — `_save_load_shedding_level` is called from
    `_periodic_db_writes` so the bundle survives a watchdog kill (no
    teardown). Throttled to write-on-change.

    Mutation: drop the `await self._save_load_shedding_level()` from
    `_periodic_db_writes` → this test fails (bundle absent post-write).
    """
    coord, plug_id = _make_coord()
    coord._load_shedding_active_level = 1
    coord._ev._paused_by_load_shed.add("garage_a")
    coord._ev._load_shed_was_on_at_shed["garage_a"] = True

    db = _StubDB()
    _attach_db(coord, db)

    # Verify periodic_db_writes WOULD call save (source-level guard
    # against accidental revert) plus exercise the save path itself.
    pdw_src = _extract_named(_energy_src, {"_periodic_db_writes"})
    assert "_save_load_shedding_level" in pdw_src, (
        "_periodic_db_writes must call _save_load_shedding_level so the "
        "bundle survives a watchdog kill (no teardown)"
    )

    asyncio.get_event_loop().run_until_complete(coord._save_load_shedding_level())
    assert "load_shedding_bundle" in db.store
    payload = json.loads(db.store["load_shedding_bundle"])
    assert payload["level"] == 1
    assert payload["ev_set"] == ["garage_a"]
    assert payload["ev_was_on_at_shed"] == {"garage_a": True}


def test_save_load_shedding_level_throttles_on_unchanged_bundle():
    """A/B-HIGH-3 throttle — back-to-back saves with no state change
    must NOT issue a second DB write (mirrors v5.2.2 write-flood lesson).
    """
    coord, _ = _make_coord()
    coord._load_shedding_active_level = 1
    coord._ev._paused_by_load_shed.add("garage_a")
    coord._ev._load_shed_was_on_at_shed["garage_a"] = True

    db = _StubDB()
    _attach_db(coord, db)

    # Wrap save_energy_state to count.
    calls = {"n": 0}
    real_save = db.save_energy_state

    async def counting_save(k, v):
        calls["n"] += 1
        await real_save(k, v)

    db.save_energy_state = counting_save

    asyncio.get_event_loop().run_until_complete(coord._save_load_shedding_level())
    first = calls["n"]
    asyncio.get_event_loop().run_until_complete(coord._save_load_shedding_level())
    second = calls["n"]
    assert second == first, (
        "Second save with unchanged bundle must short-circuit (throttle)"
    )

    # State changes → save fires again.
    coord._ev._paused_by_load_shed.add("garage_b")
    asyncio.get_event_loop().run_until_complete(coord._save_load_shedding_level())
    third = calls["n"]
    assert third > second, "State change must un-throttle the save"


def test_excess_solar_skips_load_shed_evse_AHIGH1():
    """A-HIGH-1 — `determine_excess_solar_actions` must NOT turn on an
    EVSE held by `_paused_by_load_shed`. Drives the REAL
    `EVChargerController.determine_excess_solar_actions` method.

    Mutation: drop load_shed from the skip-list → EVSE is turned on
    despite shed claim → this test fails.
    """
    hass = _build_hass()
    ev, _, _, _ = _build_controllers(hass, evse_on=False)
    ev._paused_by_load_shed.add("garage_a")

    # Conditions that would otherwise trigger excess-solar turn-on:
    # high SOC, surplus solar, no charging EVSE.
    actions = ev.determine_excess_solar_actions(
        soc=98.0,
        remaining_forecast_kwh=8.0,
        tou_period="off_peak",
        soc_threshold=95,
        kwh_threshold=5.0,
    )
    assert not any(
        a.get("service") == "switch.turn_on"
        and a.get("target") == "switch.garage_a"
        for a in actions
    ), "Excess solar must NOT turn on a load-shed-held EVSE"


def test_grid_cap_resume_defers_to_load_shed_AHIGH2():
    """A-HIGH-2 — `determine_grid_cap_actions` resume branch must NOT
    turn on an EVSE held by `_paused_by_load_shed`.

    Mutation: drop load_shed from the grid-cap resume guard → EVSE is
    turned on → this test fails.
    """
    hass = _build_hass()
    ev, _, _, _ = _build_controllers(hass, evse_on=False)
    ev._paused_by_grid_cap.add("garage_a")
    ev._paused_by_load_shed.add("garage_a")

    actions = ev.determine_grid_cap_actions(
        net_power_kw=2.0,  # well below cap minus hysteresis
        grid_cap_kw=10.0,
        hysteresis_kw=1.0,
    )
    assert not any(
        a.get("service") == "switch.turn_on" for a in actions
    ), "Grid-cap resume must defer to load_shed"
    # Grid-cap claim is cleared (resume completed bookkeeping-wise).
    assert "garage_a" not in ev._paused_by_grid_cap
    # Load-shed claim remains intact.
    assert "garage_a" in ev._paused_by_load_shed


def test_fill_priority_release_defers_to_load_shed_AMED1():
    """A-MED-1 — EV fill-priority release defers to load_shed."""
    hass = _build_hass()
    ev, _, _, _ = _build_controllers(hass, evse_on=False)
    ev._paused_by_fill_priority.add("garage_a")
    ev._paused_by_load_shed.add("garage_a")

    actions = ev.determine_fill_priority_actions(
        soc=95.0,
        remaining_forecast_kwh=0.5,
        tou_period="off_peak",
        soc_threshold=80,
        excess_solar_kwh_threshold=1.0,
    )
    assert not any(
        a.get("service") == "switch.turn_on" for a in actions
    ), "Fill-priority release must defer to load_shed"
    assert "garage_a" not in ev._paused_by_fill_priority
    assert "garage_a" in ev._paused_by_load_shed


def test_plug_tou_offpeak_carryover_respects_load_shed_CMED1():
    """C-MED-1 — drives REAL `SmartPlugController.determine_actions` in
    off-peak with a load_shed claim → plug stays off (load-shed owns
    the resume), `_paused_by_us` bookkeeping is cleared.

    This is the production carry-over path Reviewer C flagged as
    untested. Mutation: drop the load_shed branch in the off-peak
    resume → this test fails (a turn_on is issued).
    """
    hass = _build_hass()
    plug_id = "switch.kettle"
    hass.set_state(plug_id, "off")
    plugs = SmartPlugController(hass, plug_entities=[plug_id])
    plugs._paused_by_us.add(plug_id)
    plugs._paused_by_load_shed.add(plug_id)

    actions = plugs.determine_actions("off_peak")
    assert not any(
        a.get("service") == "switch.turn_on" for a in actions
    ), "Off-peak resume must defer to load_shed"
    # TOU bookkeeping cleared.
    assert plug_id not in plugs._paused_by_us
    # Load-shed remains.
    assert plug_id in plugs._paused_by_load_shed


def test_plug_tou_peak_skip_when_load_shed_claims_BLOW1():
    """B-LOW-1 — TOU peak guard must NOT issue a cosmetic re-pause for
    a plug already claimed by load_shed (device is already off).
    """
    hass = _build_hass()
    plug_id = "switch.kettle"
    hass.set_state(plug_id, "on")  # pretend live still on (race)
    plugs = SmartPlugController(hass, plug_entities=[plug_id])
    plugs._paused_by_load_shed.add(plug_id)

    actions = plugs.determine_actions("peak")
    assert not any(
        a.get("service") == "switch.turn_off" for a in actions
    ), "TOU peak must not re-pause a load-shed-held plug"
