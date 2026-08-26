"""DRAIN-TARGET-DAY-STALENESS-1 fix-up (CF-5) — mutation-anchored tests
for the D6 DP-carrier telemetry helper `_extract_dp_carrier_attrs` and
the D7 per-bay-state helper `_derive_per_bay_state` on
`sensor.ura_ev_charging_status`.

Prior state:
* D6/D7 were exercised by four green-on-neuter sites: a bug in either
  block was invisible to the suite (defensive `except Exception` in the
  entity property + no round-trip fixtures).
* The pre-fix code shipped four narration/state defects that all four
  reviewers converged on but which no test bit:
   - CF-2: D6 emitted `None` sentinels in the default-config (DP OFF)
     path because it only read `last_eval_at` / `last_eval_snapshot`.
   - CF-3: an operator-off / unplugged bay was labelled `paused`.
   - CF-4: a legal sub-48A-nameplate bay was labelled `throttled`
     forever because the discriminator was `commanded < 48` (hardcoded).

Each test in this module names the production-source line whose
inversion / deletion would produce a specific RED. Run the mutation
drills via `PYTHONDONTWRITEBYTECODE=1 pytest`; find the
`# CF-N drill:` comments below and mutate the referenced source lines.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# HA + package bootstrap (mirrors test_offpeak_drain_target_day_staleness.py)
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
    "homeassistant.components.number": {
        "NumberEntity": type("NumberEntity", (), {}),
        "NumberMode": _mock_cls(),
    },
    "homeassistant.components.switch": {"SwitchEntity": type("SwitchEntity", (), {})},
    "homeassistant.components.select": {"SelectEntity": type("SelectEntity", (), {})},
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
sys.modules.setdefault("custom_components.universal_room_automation", _ura)
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
sys.modules.setdefault(
    "custom_components.universal_room_automation.domain_coordinators", _dc,
)
_ura.domain_coordinators = _dc
for _submod_name in ("energy_const",):
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


# Directly load the helpers from sensor.py without triggering the whole
# module's HA-heavy imports. We import them lazily via importlib.
def _load_sensor_helpers():
    """Load `_extract_dp_carrier_attrs` and `_derive_per_bay_state` from
    the production sensor.py. Uses a targeted execution so a mutation to
    either helper's body — the sole surface these tests bind to —
    changes the observed behavior."""
    _sensor_path = os.path.join(_ura_path, "sensor.py")
    # sensor.py is heavy; extract just the two helpers by textual eval
    # into a fresh namespace with the same import machinery. The
    # helpers live between two named marker lines in the source.
    src = open(_sensor_path, "r").read()
    start = src.index("def _extract_dp_carrier_attrs")
    end = src.index("class EnergyEVChargingStatusSensor")
    snippet = src[start:end]
    ns: dict = {}
    # Provide the same relative-import shape the source uses.
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_const,
    )
    _fake_pkg = types.ModuleType("_helpers_pkg")
    _fake_pkg.domain_coordinators = types.SimpleNamespace(
        energy_const=energy_const,
    )
    # The helpers use `from .domain_coordinators.energy_const import ...`
    # inside a try/except. Simulate by pre-populating the mapping so the
    # relative import route resolves against our already-loaded module.
    exec(
        compile(snippet.replace(
            "from .domain_coordinators.energy_const import (",
            "from custom_components.universal_room_automation."
            "domain_coordinators.energy_const import (",
        ), _sensor_path, "exec"),
        ns,
    )
    return ns["_extract_dp_carrier_attrs"], ns["_derive_per_bay_state"]


_extract_dp_carrier_attrs, _derive_per_bay_state = _load_sensor_helpers()


# ---------------------------------------------------------------------------
# Fake DP carrier — mimics the two `to_attrs` outputs we care about.
# ---------------------------------------------------------------------------


class _FakeCarrier:
    """Fake DrainPrecedenceState with just enough shape for D6."""

    def __init__(
        self,
        *,
        live_at=None,
        live_snap=None,
        shadow_at=None,
        shadow_snap=None,
        state="hold_only",
        hold_started_at=None,
    ):
        self.shadow_last_eval_at = shadow_at
        self._live_at = live_at
        self._live_snap = live_snap or {}
        self._shadow_snap = shadow_snap or {}
        self._state = state
        self._hold_started_at = hold_started_at

    def to_attrs(self, now=None):
        eval_age_min = None
        if self._live_at is not None and now is not None:
            try:
                eval_age_min = int((now - self._live_at).total_seconds() // 60)
            except TypeError:
                eval_age_min = None
        return {
            "state": self._state,
            "hold_started_at": self._hold_started_at,
            "last_eval_at": self._live_at,
            "last_eval_snapshot": dict(self._live_snap),
            "eval_age_min": eval_age_min,
            "shadow_last_eval_at": self.shadow_last_eval_at,
            "shadow_last_eval_snapshot": dict(self._shadow_snap),
        }


# ===========================================================================
# CF-2 — D6 DP carrier: shadow-leg fallback + dp_source discriminator.
# ===========================================================================


def test_d6_live_leg_reads_last_eval_snapshot_and_reports_live_source():
    """DP ENABLED (live). CF-2 drill: mutating the helper to only ever
    read `shadow_last_eval_snapshot` would drop `dp_last_eval_soc=57` to
    the shadow snapshot value (None) → this test goes RED.
    """
    now = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
    live_at = now - timedelta(minutes=3)
    carrier = _FakeCarrier(
        live_at=live_at,
        live_snap={"inputs": {"soc": 57, "drain_target_soc": 30}},
        shadow_at=None,
    )
    out = _extract_dp_carrier_attrs(carrier, now)
    assert out["dp_source"] == "live", out
    assert out["dp_last_eval_soc"] == 57, out
    assert out["dp_drain_floor"] == 30, out
    assert out["dp_eval_age_min"] == 3, out


def test_d6_shadow_leg_fallback_when_live_never_ran():
    """DP DISABLED (default). CF-2 drill: the pre-fix code returned
    `dp_last_eval_soc=None` here (only read `last_eval_snapshot`). This
    test binds to the shadow-fallback branch — remove the fallback and
    it goes RED (None instead of 42 / 25). Additionally binds to the
    `dp_source == "shadow"` discriminator so a mutation that stops
    stamping `dp_source` also bites.
    """
    now = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
    shadow_at = now - timedelta(minutes=7)
    carrier = _FakeCarrier(
        live_at=None,
        live_snap={},
        shadow_at=shadow_at,
        shadow_snap={"inputs": {"soc": 42, "drain_target_soc": 25}},
    )
    out = _extract_dp_carrier_attrs(carrier, now)
    assert out["dp_source"] == "shadow", out
    assert out["dp_last_eval_soc"] == 42, out
    assert out["dp_drain_floor"] == 25, out
    # Shadow-leg age computed in-helper (carrier's to_attrs doesn't).
    assert out["dp_eval_age_min"] == 7, out


def test_d6_shadow_leg_no_snapshot_yet_returns_none_safely():
    """Boot / never-evaluated shadow — helper must not crash and must
    still stamp `dp_source='shadow'` so the operator can tell that DP
    is disabled but the shadow leg hasn't run yet."""
    now = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
    carrier = _FakeCarrier(live_at=None, shadow_at=None)
    out = _extract_dp_carrier_attrs(carrier, now)
    assert out["dp_source"] == "shadow"
    assert out["dp_last_eval_soc"] is None
    assert out["dp_drain_floor"] is None
    assert out["dp_eval_age_min"] is None


# ===========================================================================
# CF-3 / CF-4 — D7 per-bay-state: paused-owner / off-vs-idle / throttled
# discriminated by per-bay captured baseline (not a hardcoded 48A).
# ===========================================================================


def _bay(*, is_on, charging, power=0.0):
    return {"is_on": is_on, "charging": charging, "power": power}


def test_d7_paused_only_when_owner_present():
    """CF-3 drill: revert the branch to
    `if owner is not None or not entry.get("is_on"): state = 'paused'`
    and this test goes RED (`off` becomes `paused`).
    """
    attrs = {
        "garage_a": _bay(is_on=False, charging=False),
        "paused_by_battery_drain": [],
    }
    per_bay = _derive_per_bay_state(attrs)
    assert per_bay["garage_a"]["state"] == "off", per_bay
    assert per_bay["garage_a"]["owner"] is None, per_bay


def test_d7_paused_when_owner_present_even_if_on():
    attrs = {
        "garage_a": _bay(is_on=True, charging=False, power=0),
        "paused_by_battery_drain": ["garage_a"],
    }
    per_bay = _derive_per_bay_state(attrs)
    assert per_bay["garage_a"]["state"] == "paused"
    assert per_bay["garage_a"]["owner"] == "battery_drain"


def test_d7_charging_at_bay_nameplate_not_throttled():
    """CF-4 drill: the pre-fix compared `commanded < 48` hardcoded.
    A legal 40A@32A-nameplate bay at commanded=32 (== baseline) would
    have read `throttled` forever. With the per-bay-baseline fix the
    same setup reads `charging`; hard-code the discriminator back to
    48 and this test goes RED.
    """
    attrs = {
        "garage_b": _bay(is_on=True, charging=True, power=7680.0),
        "solar_follow_last_commanded": {"garage_b": 32.0},
        "solar_follow_original_amps": {"garage_b": 32.0},
        "paused_by_battery_drain": [],
    }
    per_bay = _derive_per_bay_state(attrs)
    assert per_bay["garage_b"]["state"] == "charging", per_bay


def test_d7_throttled_when_commanded_below_captured_baseline():
    """Same 40A@32A bay under solar-follow throttle: commanded=16
    against baseline=32 → `throttled`."""
    attrs = {
        "garage_b": _bay(is_on=True, charging=True, power=3840.0),
        "solar_follow_last_commanded": {"garage_b": 16.0},
        "solar_follow_original_amps": {"garage_b": 32.0},
        "paused_by_battery_drain": [],
    }
    per_bay = _derive_per_bay_state(attrs)
    assert per_bay["garage_b"]["state"] == "throttled", per_bay


def test_d7_no_baseline_captured_falls_back_to_default_nameplate():
    """When solar-follow hasn't captured a baseline for this bay yet,
    fall back to SOLAR_FOLLOW_RESTORE_AMPS (48) so we don't
    mis-report `throttled` for a random low commanded value on a
    brand-new bay before its first session."""
    attrs = {
        "garage_c": _bay(is_on=True, charging=True, power=11520.0),
        "solar_follow_last_commanded": {"garage_c": 48.0},
        "solar_follow_original_amps": {},  # not yet captured
        "paused_by_battery_drain": [],
    }
    per_bay = _derive_per_bay_state(attrs)
    assert per_bay["garage_c"]["state"] == "charging", per_bay


def test_d7_idle_when_on_but_not_charging_and_no_owner():
    attrs = {
        "garage_a": _bay(is_on=True, charging=False),
        "paused_by_battery_drain": [],
    }
    per_bay = _derive_per_bay_state(attrs)
    assert per_bay["garage_a"]["state"] == "idle"
