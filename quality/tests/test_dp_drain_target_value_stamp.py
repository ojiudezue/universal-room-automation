"""dp-drain-target-value-stamp — Tier-3 build acceptance tests.

Cycle: `feature/dp-drain-target-value-stamp` — the DP tick + shadow eval
consume THIS-tick's composed off_peak drain-fallback floor via a value
stamped on BatteryStrategy (`_offpeak_drain_branch_target`), NOT the
static R1 `_ev_battery_drain_soc` knob.

Falsifiable invariants exercised:

* **Value-stamp writer** — determine_mode's off_peak drain-fallback
  branch stamps `_offpeak_drain_branch_target` = the final composed
  drain_target (post multi-day-max, post partial_hold clamp).
* **ENTRY-RESET (D2-HIGH-1 anchor)** — determine_mode's FIRST executable
  statement resets the stamp to None so any tick that does NOT reach the
  drain-fallback (full_hold, non-off_peak, arbitrage) leaves a None
  stamp, and DP declines / releases rather than inheriting the prior
  tick's value.
* **Coordinator capture + thread** — energy.py captures the stamp
  synchronously after determine_mode returns (before the first await)
  and threads it into `_dp_decision_tick` + `_run_dp_shadow_eval` as
  `drain_target_soc=`.
* **No helper / no attribute read** — neither `_dp_decision_tick` nor
  `_run_dp_shadow_eval` reads `_ev_battery_drain_soc` or a helper
  accessor. They consume the threaded parameter verbatim.
* **R1 (:5904/:6039) + R3 (:3752, pool :954/:1435) preserved** — the
  static `_ev_battery_drain_soc` knob remains the source at these sites
  unchanged.

Mutation drill C-entry-reset:

* Delete the ENTRY-RESET line from a copy of energy_battery.py and
  re-run the cross-tick reset scenario. The test must FAIL (the stamp
  from tick 1 survives into tick 2 that never re-stamped).
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import re
import subprocess
import sys
import textwrap
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# HA + package bootstrap (mirrors test_battery_inclement_precedence.py)
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
for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)
sys.modules.setdefault("aiosqlite", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)
_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura
_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod
_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc
for _submod_name in (
    "energy_const", "energy_tou", "inclement", "energy_battery",
):
    _full = (
        f"custom_components.universal_room_automation."
        f"domain_coordinators.{_submod_name}"
    )
    _spec = importlib.util.spec_from_file_location(
        _full, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators.energy_const import (  # noqa: E402
    DEFAULT_RESERVE_SOC,
    DEFAULT_RESERVE_SOC_ENTITY,
    DEFAULT_STORAGE_MODE_ENTITY,
    DEFAULT_GRID_ENABLED_ENTITY,
    DEFAULT_CHARGE_FROM_GRID_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_SOLCAST_TOMORROW_ENTITY,
    DEFAULT_WEATHER_ENTITY,
    DEFAULT_OFFPEAK_DRAIN_EXCELLENT,
    CONF_INCLEMENT_NWS_ALERTS_ENTITY,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (  # noqa: E402
    BatteryStrategy,
)

_BATTERY_SOC = "sensor.test_envoy_battery"
_NWS = "sensor.test_nws_alerts"
_NOW = datetime(2026, 6, 11, 22, 30, 0)  # inside off_peak window


def _make_battery(soc=50.0):
    hass = MockHass()
    hass.set_state(_BATTERY_SOC, str(soc))
    hass.set_state(DEFAULT_STORAGE_MODE_ENTITY, "self_consumption")
    hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, "on")
    hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "off")
    hass.set_state(DEFAULT_RESERVE_SOC_ENTITY, "10")
    hass.set_state(DEFAULT_SOLCAST_TODAY_ENTITY, "90")
    hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, "110")
    hass.set_state(DEFAULT_WEATHER_ENTITY, "sunny")
    strat = BatteryStrategy(
        hass,
        reserve_soc=DEFAULT_RESERVE_SOC,
        entity_config={"battery_soc": _BATTERY_SOC},
        solar_classification_mode="custom",
        custom_solar_thresholds={
            "excellent": 100.0, "good": 80.0, "moderate": 50.0, "poor": 30.0,
        },
    )
    strat._inclement_config_override = {}
    return strat, hass


def _arm_alert(strat, hass, event="Tornado Warning", severity="Extreme",
               certainty="Observed", extra_cfg=None):
    hass.set_state(_NWS, "1", attributes={"Alerts": [{
        "Event": event, "Severity": severity, "Certainty": certainty,
        "Status": "Actual",
        "Onset": "2026-06-11T16:00:00-05:00",
        "Ends": "2026-06-12T00:00:00-05:00",
    }]})
    cfg = {CONF_INCLEMENT_NWS_ALERTS_ENTITY: _NWS}
    if extra_cfg:
        cfg.update(extra_cfg)
    strat._inclement_config_override = cfg


# ---------------------------------------------------------------------------
# Value-stamp writer + entry-reset (real determine_mode)
# ---------------------------------------------------------------------------


def test_init_default_is_none():
    """Fresh BatteryStrategy starts with a None stamp — the ONLY safe boot
    default; DP must not consume a stale value from a prior process."""
    strat, _hass = _make_battery(soc=50)
    assert strat._offpeak_drain_branch_target is None


def test_off_peak_drain_branch_stamps_value():
    """Off_peak drain-fallback with a clear-day forecast (excellent →
    drain target 10) stamps `_offpeak_drain_branch_target == 10`."""
    strat, hass = _make_battery(soc=50)
    r = strat.determine_mode("off_peak", "summer", now=_NOW)
    # Regression guard on the fixture: ensure we actually traversed the
    # drain-fallback path (the reason contains "Off-peak drain" or
    # "Off-peak hold").
    assert "Off-peak" in r["reason"]
    assert strat._offpeak_drain_branch_target == int(DEFAULT_OFFPEAK_DRAIN_EXCELLENT)
    assert strat._offpeak_drain_branch_target == 10


def test_off_peak_full_hold_leaves_stamp_none():
    """A warn-tier NWS alert forces full_hold BEFORE the off_peak
    drain-fallback branch runs. The entry-reset already zeroed the
    stamp; the stamp must remain None."""
    strat, hass = _make_battery(soc=80)
    _arm_alert(strat, hass)  # warn / full_hold
    r = strat.determine_mode("off_peak", "summer", now=_NOW)
    # Sanity: this is a full_hold decision, not the drain-fallback.
    attrs = strat._inclement_attrs()
    assert attrs["inclement_hold_depth"] == "full_hold", r["reason"]
    assert strat._offpeak_drain_branch_target is None


def test_cross_tick_reset_non_offpeak_after_drain_leaves_none():
    """D2-HIGH-1 anchor. Tick 1: off_peak drain-fallback stamps 10.
    Tick 2: mid_peak summer branches AWAY from the drain-fallback (holds
    for peak) — the stamp line is NEVER reached. Under the FIX the
    entry-reset clears the tick-1 stamp → tick 2 leaves None. Under the
    buggy pattern (no entry-reset), the tick-1 stamp survives and the DP
    consumer reads a stale value from a period the drain-fallback never
    fired in.

    (Rationale for using mid_peak rather than an off_peak full_hold:
    arming the NWS alert on an already-constructed strategy does not
    reliably retrigger inclement detection mid-test — mid_peak is a
    cleaner short-circuit that exercises the same invariant.)
    """
    strat, _hass = _make_battery(soc=50)
    strat.determine_mode("off_peak", "summer", now=_NOW)
    assert strat._offpeak_drain_branch_target == 10
    # Tick 2 — mid_peak summer holds for the upcoming peak; determine_mode
    # returns before the off_peak drain-fallback branch runs.
    r2 = strat.determine_mode("mid_peak", "summer", now=_NOW)
    assert "holding charge" in r2["reason"].lower() or "peak" in r2["reason"].lower(), r2["reason"]
    assert strat._offpeak_drain_branch_target is None


def test_partial_hold_clamp_stamps_effective_reserve():
    """An uncorroborated watch at off_peak resolves to partial_hold with
    a 50% floor. The stamp must equal the CLAMPED drain_target, i.e.
    `max(drain_excellent=10, effective_reserve=50) == 50` — the SAME
    value the emitter would use for the reserve action. This proves the
    stamp lives AFTER the :5322 clamp, not before it."""
    strat, hass = _make_battery(soc=80)
    _arm_alert(strat, hass, event="Severe Thunderstorm Watch",
               severity="Severe", certainty="Possible")
    strat.determine_mode("off_peak", "summer", now=_NOW)
    attrs = strat._inclement_attrs()
    assert attrs["inclement_hold_depth"] == "partial_hold"
    # partial_hold floor is 50% by default; drain_excellent is 10.
    assert strat._offpeak_drain_branch_target == 50


# ---------------------------------------------------------------------------
# Coordinator side — capture + thread; no attr read in DP tick / shadow
# ---------------------------------------------------------------------------


_ENERGY_PY = Path(_dc_path) / "energy.py"
_ENERGY_BATTERY_PY = Path(_dc_path) / "energy_battery.py"
_ENERGY_POOL_PY = Path(_dc_path) / "energy_pool.py"


def _method_body(source: str, class_name: str, method_name: str) -> str:
    """Return the raw source of the named method inside class_name."""
    import ast as _ast
    tree = _ast.parse(source)
    src_lines = source.splitlines()
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if isinstance(child, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                if child.name == method_name:
                    return "\n".join(
                        src_lines[child.lineno - 1: child.end_lineno]
                    )
    raise AssertionError(
        f"{class_name}.{method_name} not found in source"
    )


_MUTATION_MARKER = "self._offpeak_drain_branch_target = None"


def _mutated_battery_src_without_entry_reset() -> str:
    src = _ENERGY_BATTERY_PY.read_text()
    # There are two occurrences: (1) the ctor init at ~:492 (KEEP), and
    # (2) the ENTRY-RESET inside determine_mode (DELETE). Distinguish by
    # neighborhood: the ENTRY-RESET follows the cycle's ENTRY-RESET
    # comment block.
    marker = "# dp-drain-target-value-stamp — ENTRY-RESET."
    idx = src.find(marker)
    assert idx != -1, "entry-reset comment block not found"
    # Find the reset assignment AFTER the comment block.
    reset_idx = src.find(_MUTATION_MARKER, idx)
    assert reset_idx != -1, "entry-reset assignment not found"
    # Delete the whole line.
    line_start = src.rfind("\n", 0, reset_idx) + 1
    line_end = src.find("\n", reset_idx) + 1
    return src[:line_start] + src[line_end:]


def test_mutation_c_entry_reset_bites():
    """C-entry-reset: mutating the source to REMOVE the entry-reset
    line MUST break `test_cross_tick_reset_full_hold_after_drain_leaves_none`.
    Failure of this drill = the entry-reset line is not load-bearing =
    the D2-HIGH-1 refill hazard is uncovered."""
    mutated = _mutated_battery_src_without_entry_reset()
    # Sanity: no plain-form marker remains in mutated source (the ctor
    # init carries a type annotation and does not match the marker).
    assert mutated.count(_MUTATION_MARKER) == 0
    # And an unmutated source has exactly one plain-form occurrence
    # (the ENTRY-RESET line inside determine_mode).
    assert (
        _ENERGY_BATTERY_PY.read_text().count(_MUTATION_MARKER) == 1
    )

    import tempfile

    # Build a self-contained runner: monkey-copy the mutated module into
    # a fresh interpreter, then run the exact cross-tick scenario. The
    # runner exits 0 IFF the mutation is silent (bug!), and non-zero IFF
    # the assertion catches it (the desired outcome).
    runner = textwrap.dedent(
        r"""
        import os, sys, importlib, importlib.util, types
        from datetime import datetime
        from unittest.mock import MagicMock

        def _mock_module(name, **attrs):
            mod = types.ModuleType(name)
            for k, v in attrs.items():
                setattr(mod, k, v)
            return mod

        _identity = lambda fn: fn
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
                "utcnow": datetime.utcnow, "now": datetime.now,
                "as_local": lambda dt: dt,
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
            "homeassistant.components.button": {
                "ButtonEntity": type("ButtonEntity", (), {}),
            },
        }
        for name, attrs in _mods.items():
            if isinstance(attrs, dict):
                sys.modules.setdefault(name, _mock_module(name, **attrs))
            else:
                sys.modules.setdefault(name, attrs)
        sys.modules.setdefault("aiosqlite", MagicMock())

        _REPO = os.environ["URA_REPO_ROOT"]
        sys.path.insert(0, _REPO)
        sys.path.insert(0, os.path.join(_REPO, "quality/tests"))
        _cc = types.ModuleType("custom_components")
        _cc.__path__ = [os.path.join(_REPO, "custom_components")]
        sys.modules.setdefault("custom_components", _cc)
        _ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
        _ura = types.ModuleType("custom_components.universal_room_automation")
        _ura.__path__ = [_ura_path]
        _ura.__package__ = "custom_components.universal_room_automation"
        sys.modules["custom_components.universal_room_automation"] = _ura
        _const_spec = importlib.util.spec_from_file_location(
            "custom_components.universal_room_automation.const",
            os.path.join(_ura_path, "const.py"),
        )
        _const_mod = importlib.util.module_from_spec(_const_spec)
        sys.modules["custom_components.universal_room_automation.const"] = _const_mod
        _const_spec.loader.exec_module(_const_mod)
        _ura.const = _const_mod
        _dc_path = os.path.join(_ura_path, "domain_coordinators")
        _dc = types.ModuleType(
            "custom_components.universal_room_automation.domain_coordinators"
        )
        _dc.__path__ = [_dc_path]
        _dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
        sys.modules[
            "custom_components.universal_room_automation.domain_coordinators"
        ] = _dc
        _ura.domain_coordinators = _dc

        # Load unaltered dependencies first.
        for name in ("energy_const", "energy_tou", "inclement"):
            full = (
                "custom_components.universal_room_automation."
                f"domain_coordinators.{name}"
            )
            spec = importlib.util.spec_from_file_location(
                full, os.path.join(_dc_path, f"{name}.py"),
            )
            mod = importlib.util.module_from_spec(spec)
            sys.modules[full] = mod
            spec.loader.exec_module(mod)
            setattr(_dc, name, mod)

        # Load MUTATED energy_battery from the tmp path.
        full = (
            "custom_components.universal_room_automation."
            "domain_coordinators.energy_battery"
        )
        spec = importlib.util.spec_from_file_location(
            full, os.environ["URA_MUTATED_EB_PATH"],
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full] = mod
        spec.loader.exec_module(mod)
        setattr(_dc, "energy_battery", mod)

        from conftest import MockHass
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            DEFAULT_RESERVE_SOC, DEFAULT_RESERVE_SOC_ENTITY,
            DEFAULT_STORAGE_MODE_ENTITY, DEFAULT_GRID_ENABLED_ENTITY,
            DEFAULT_CHARGE_FROM_GRID_ENTITY, DEFAULT_SOLCAST_TODAY_ENTITY,
            DEFAULT_SOLCAST_TOMORROW_ENTITY, DEFAULT_WEATHER_ENTITY,
            CONF_INCLEMENT_NWS_ALERTS_ENTITY,
        )
        BatteryStrategy = mod.BatteryStrategy

        _BAT = "sensor.test_envoy_battery"
        _NWS = "sensor.test_nws_alerts"
        _NOW = datetime(2026, 6, 11, 22, 30, 0)

        hass = MockHass()
        hass.set_state(_BAT, "50")
        hass.set_state(DEFAULT_STORAGE_MODE_ENTITY, "self_consumption")
        hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, "on")
        hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "off")
        hass.set_state(DEFAULT_RESERVE_SOC_ENTITY, "10")
        hass.set_state(DEFAULT_SOLCAST_TODAY_ENTITY, "90")
        hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, "110")
        hass.set_state(DEFAULT_WEATHER_ENTITY, "sunny")
        strat = BatteryStrategy(
            hass, reserve_soc=DEFAULT_RESERVE_SOC,
            entity_config={"battery_soc": _BAT},
            solar_classification_mode="custom",
            custom_solar_thresholds={
                "excellent": 100.0, "good": 80.0, "moderate": 50.0, "poor": 30.0,
            },
        )
        strat._inclement_config_override = {}
        strat.determine_mode("off_peak", "summer", now=_NOW)
        assert strat._offpeak_drain_branch_target == 10, "tick-1 didn't stamp"

        # Tick 2 — mid_peak summer holds for peak, short-circuits before
        # the off_peak drain-fallback branch runs.
        strat.determine_mode("mid_peak", "summer", now=_NOW)
        # UNDER THE MUTATION (no entry-reset): the tick-1 stamp survives
        # and this assertion FAILS. That is the drill's success signal.
        assert strat._offpeak_drain_branch_target is None, (
            "MUTATION SILENT — entry-reset is not load-bearing! "
            f"stamp={strat._offpeak_drain_branch_target}"
        )
        print("MUTATION_DRILL: assertion passed (unexpected — drill FAILED)")
        sys.exit(0)
        """
    )
    with tempfile.TemporaryDirectory() as td:
        mutated_path = os.path.join(td, "energy_battery_mutated.py")
        with open(mutated_path, "w") as fh:
            fh.write(mutated)
        runner_path = os.path.join(td, "run.py")
        with open(runner_path, "w") as fh:
            fh.write(runner)
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["URA_REPO_ROOT"] = str(
            Path(__file__).resolve().parents[2]
        )
        env["URA_MUTATED_EB_PATH"] = mutated_path
        proc = subprocess.run(
            [sys.executable, runner_path],
            env=env, capture_output=True, text=True,
        )
    # Under the mutation, the assertion `stamp is None` must FAIL →
    # non-zero exit code. If exit==0 the mutation was silent (bug).
    assert proc.returncode != 0, (
        "C-entry-reset drill did NOT bite — the entry-reset line was "
        f"deleted but the cross-tick assertion still held.\n"
        f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
    )
    # Sanity: the failure is the AssertionError we authored, not a random
    # import blow-up.
    combined = proc.stdout + "\n" + proc.stderr
    # Fix #6 — require the specific "MUTATION SILENT" marker so an
    # import/fixture break cannot masquerade as a bitting drill.
    assert "MUTATION SILENT" in combined, (
        "expected 'MUTATION SILENT' marker in mutated-run output "
        f"(guards against import/fixture breaks masquerading as bites)\n"
        f"combined output:\n{combined}"
    )



# ---------------------------------------------------------------------------
# Fix #2 - BEHAVIORAL anchors (replaces the 5 removed source-string tests).
# These fail on a WRONG VALUE, not on a rename.
# ---------------------------------------------------------------------------

import hashlib as _hashlib
import shutil as _shutil
from datetime import timedelta as _timedelta

import quality.tests.test_evse_drain_precedence_session_b2c1_fixup as _b2c1_dp
import quality.tests.test_evse_drain_precedence_session_b2c2_fixup as _b2c2_dp

_DPState_dp = _b2c1_dp.DPState


def _drive_fresh_transition(coord, drain_stamp):
    """Drive HOLD_ONLY -> TRANSITIONED via two ticks under a frozen clock."""
    anchor = datetime(2026, 7, 20, 22, 0, 0)
    with _b2c2_dp._frozen_dt_now(anchor):
        coord._dp_decision_tick(
            {"soc": 50}, "off_peak", ev_load_w=6000.0,
            drain_target_soc=drain_stamp,
        )
        coord._dp_carrier.hold_started_at = anchor - _timedelta(minutes=60)
        coord._dp_decision_tick(
            {"soc": 50}, "off_peak", ev_load_w=6000.0,
            drain_target_soc=drain_stamp,
        )


def test_dp_transition_consumes_stamped_target_not_static_knob():
    """Behavioral: static knob=20, THIS-tick stamp=40. The fresh DP
    transition must stamp `_dp_decision_soc == 40` (from the stamp),
    NOT 20 (from the R1 static knob). Fails on any wrong-value
    regression, not on a rename."""
    coord, _ev, _bat, _tou = _b2c1_dp._make_coord(
        ids=("garage_a",), charging=("garage_a",), drain_target=20,
    )
    coord._dp_needed_kwh_garage_a = 5.0
    _drive_fresh_transition(coord, drain_stamp=40)
    assert coord._dp_carrier.state == _DPState_dp.TRANSITIONED, (
        f"pre-req: fresh transition did not fire; state="
        f"{coord._dp_carrier.state}"
    )
    assert coord._dp_decision_soc == 40, (
        f"stamp not consumed: _dp_decision_soc="
        f"{coord._dp_decision_soc!r} (expected 40, static knob=20)"
    )


def _drive_transitioned_ready(coord):
    _drive_fresh_transition(coord, drain_stamp=30)
    assert coord._dp_carrier.state == _DPState_dp.TRANSITIONED


def test_debounce_first_none_tick_holds_pause():
    """Fix #4 (5c debounce). 1st None-while-TRANSITIONED tick MUST NOT
    release: state stays TRANSITIONED, streak counter == 1."""
    coord, _ev, _bat, _tou = _b2c1_dp._make_coord(
        ids=("garage_a",), charging=("garage_a",), drain_target=30,
    )
    coord._dp_needed_kwh_garage_a = 5.0
    _drive_transitioned_ready(coord)
    try:
        coord._dp_decision_tick(
            {"soc": 50}, "off_peak", ev_load_w=6000.0,
            drain_target_soc=None,
        )
    except _b2c1_dp._DPSkip:
        pass
    assert coord._dp_carrier.state == _DPState_dp.TRANSITIONED, (
        "released on FIRST None tick (debounce missing)"
    )
    assert getattr(coord, "_dp_none_streak", 0) == 1


def test_debounce_second_consecutive_none_tick_releases():
    """Fix #4: 2nd consecutive None tick releases via the peer reversion
    contract (state -> HOLD_ONLY)."""
    coord, _ev, _bat, _tou = _b2c1_dp._make_coord(
        ids=("garage_a",), charging=("garage_a",), drain_target=30,
    )
    coord._dp_needed_kwh_garage_a = 5.0
    _drive_transitioned_ready(coord)
    for _ in range(2):
        try:
            coord._dp_decision_tick(
                {"soc": 50}, "off_peak", ev_load_w=6000.0,
                drain_target_soc=None,
            )
        except _b2c1_dp._DPSkip:
            pass
    assert coord._dp_carrier.state == _DPState_dp.HOLD_ONLY


def test_debounce_streak_resets_on_non_none_tick():
    """Fix #4: a non-None tick between None ticks resets the streak."""
    coord, _ev, _bat, _tou = _b2c1_dp._make_coord(
        ids=("garage_a",), charging=("garage_a",), drain_target=30,
    )
    coord._dp_needed_kwh_garage_a = 5.0
    _drive_transitioned_ready(coord)
    try:
        coord._dp_decision_tick(
            {"soc": 50}, "off_peak", ev_load_w=6000.0,
            drain_target_soc=None,
        )
    except _b2c1_dp._DPSkip:
        pass
    assert coord._dp_carrier.state == _DPState_dp.TRANSITIONED
    coord._dp_decision_tick(
        {"soc": 50}, "off_peak", ev_load_w=6000.0,
        drain_target_soc=30,
    )
    assert coord._dp_none_streak == 0
    try:
        coord._dp_decision_tick(
            {"soc": 50}, "off_peak", ev_load_w=6000.0,
            drain_target_soc=None,
        )
    except _b2c1_dp._DPSkip:
        pass
    assert coord._dp_carrier.state == _DPState_dp.TRANSITIONED


def test_inv_dp_drain_1e_stranded_release_after_two_none_ticks():
    """INV-DP-DRAIN-1e end-to-end: carrier TRANSITIONED with an EVSE
    paused; two consecutive None-while-TRANSITIONED off_peak ticks
    -> EVSE released, carrier back to HOLD_ONLY."""
    coord, ev, _bat, _tou = _b2c1_dp._make_coord(
        ids=("garage_a",), charging=("garage_a",), drain_target=30,
    )
    coord._dp_needed_kwh_garage_a = 5.0
    _drive_transitioned_ready(coord)
    assert "garage_a" in ev._paused_by_dp
    for _ in range(2):
        try:
            coord._dp_decision_tick(
                {"soc": 50}, "off_peak", ev_load_w=6000.0,
                drain_target_soc=None,
            )
        except _b2c1_dp._DPSkip:
            pass
    assert coord._dp_carrier.state == _DPState_dp.HOLD_ONLY
    assert "garage_a" not in ev._paused_by_dp


# ---------------------------------------------------------------------------
# Mutation drills on the new value-stamp / debounce anchors.
# ---------------------------------------------------------------------------

_HERE_DP = os.path.dirname(os.path.abspath(__file__))

_CAPTURE_ANCHOR = (
    '_drain_target = getattr(\n'
    '                self._battery, "_offpeak_drain_branch_target", None,\n'
    '            )'
)
_CAPTURE_MUTATED = _CAPTURE_ANCHOR + "\n            _drain_target = 999"

_R2_FRESH_ANCHOR = "_dts_fresh = int(drain_target_soc)"
_R2_FRESH_MUTATED = "_dts_fresh = int(drain_target_soc) + 7"

_1E_STREAK_ANCHOR = (
    'self._dp_none_streak = getattr(\n'
    '                    self, "_dp_none_streak", 0,\n'
    '                ) + 1\n'
    '                if self._dp_none_streak >= 2:'
)
_1E_STREAK_MUTATED = _1E_STREAK_ANCHOR.replace(">= 2", ">= 1")


def _md5_dp(p):
    return _hashlib.md5(Path(p).read_bytes()).hexdigest()


def _clear_pycache_dp():
    for root, dirs, _ in os.walk(_dc_path):
        for d in list(dirs):
            if d == "__pycache__":
                _shutil.rmtree(os.path.join(root, d), ignore_errors=True)


def _run_named_test_subprocess_dp(test_name):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.abspath(os.path.join(_HERE_DP, ".."))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable, "-m", "pytest",
            f"{os.path.abspath(__file__)}::{test_name}",
            "-x", "--tb=short", "-q",
        ],
        env=env, capture_output=True, text=True,
        cwd=os.path.abspath(os.path.join(_HERE_DP, "..", "..")),
    )


def _mutate_energy_expect_red(swap_from, swap_to, test_name):
    src_path = Path(_ENERGY_PY)
    original = src_path.read_text(encoding="utf-8")
    assert swap_from in original, f"anchor missing in energy.py: {swap_from!r}"
    mutated = original.replace(swap_from, swap_to, 1)
    assert mutated != original, "mutation was a no-op"
    src_path.write_text(mutated, encoding="utf-8")
    md5_after = _md5_dp(src_path)
    try:
        _clear_pycache_dp()
        result = _run_named_test_subprocess_dp(test_name)
        assert result.returncode != 0, (
            f"MUTATION SILENT: {test_name} passed under mutation\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    finally:
        src_path.write_text(original, encoding="utf-8")
        _clear_pycache_dp()
        assert _md5_dp(src_path) != md5_after
        assert src_path.read_text(encoding="utf-8") == original


def test_capture_is_last_binding_before_dp_tick_call():
    """Wire-integrity anchor for the CAPTURE. The block between
    `_drain_target = getattr(self._battery, ...)` and the
    `self._dp_decision_tick(...)` call must contain EXACTLY ONE binding
    of `_drain_target`. Any rebinding (e.g. an override `_drain_target =
    999` inserted between the two) makes this test RED — which is what
    the CAPTURE mutation drill below exploits."""
    src = Path(_ENERGY_PY).read_text()
    start = src.index("_drain_target = getattr(")
    end = src.index("self._dp_decision_tick(", start)
    between = src[start:end]
    rebindings = re.findall(r"^\s*_drain_target\s*=\s*", between, re.M)
    assert len(rebindings) == 1, (
        f"expected exactly ONE binding of _drain_target between capture "
        f"and DP tick call; found {len(rebindings)} — an interposed "
        f"rebinding would silently break the value-stamp thread"
    )


def test_MUTATION_capture_override_makes_capture_wire_test_red():
    """Mutating the CAPTURE (append `_drain_target = 999`) makes
    test_capture_is_last_binding_before_dp_tick_call RED (two rebindings
    detected instead of one)."""
    _mutate_energy_expect_red(
        _CAPTURE_ANCHOR, _CAPTURE_MUTATED,
        test_name="test_capture_is_last_binding_before_dp_tick_call",
    )


def test_MUTATION_r2_fresh_actuation_offset_makes_stamp_test_red():
    """Mutating R2 fresh-actuation (`int(drain_target_soc)+7`) makes the
    stamp anchor RED (expects 40, gets 47)."""
    _mutate_energy_expect_red(
        _R2_FRESH_ANCHOR, _R2_FRESH_MUTATED,
        test_name="test_dp_transition_consumes_stamped_target_not_static_knob",
    )


def test_MUTATION_1e_no_debounce_makes_debounce_test_red():
    """Mutating the 1e branch to release on the FIRST None tick (`>= 1`
    instead of `>= 2`) makes test_debounce_first_none_tick_holds_pause
    RED - proves the debounce is load-bearing."""
    _mutate_energy_expect_red(
        _1E_STREAK_ANCHOR, _1E_STREAK_MUTATED,
        test_name="test_debounce_first_none_tick_holds_pause",
    )
