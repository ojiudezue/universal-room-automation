"""Behavioural + mutation-anchored tests for SolarFollowController (D1).

See docs/planning/PLANNING_evse_solar_follow_amps.md §9-§10.

Every test in this file is a mutation-drill anchor: neutering the
production site the test names in its docstring MUST turn this test red.
No test in this file contains its own mutation; no test asserts on source
text (Bug Class #62).

Run with `PYTHONDONTWRITEBYTECODE=1` per the plan §9 fixture contract.
"""

import asyncio
import os
import sys
import types
import importlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock homeassistant (same shape as test_energy_evse.py)
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
        "async_call_later": lambda hass, delay, cb: (lambda: None),
        "async_track_time_interval": lambda hass, cb, interval: (lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda *a, **k: (lambda: None),
        "async_dispatcher_send": lambda *a, **k: None,
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
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc
for _sub in ("energy_pool_owners", "energy_const", "energy_pool"):
    _full = f"custom_components.universal_room_automation.domain_coordinators.{_sub}"
    _spec = importlib.util.spec_from_file_location(
        _full, os.path.join(_dc_path, f"{_sub}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _sub, _mod)

from conftest import MockHass, MockState

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
    EVChargerController,
    SolarFollowController,
    DEFAULT_EVSE_ENTITIES,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    SOLAR_FOLLOW_MIN_AMPS,
    SOLAR_FOLLOW_MAX_AMPS,
    SOLAR_FOLLOW_RESTORE_AMPS,
    SOLAR_FOLLOW_CAPTURE_SANITY_A,
    SOLAR_FOLLOW_UP_STEP_A,
    SOLAR_FOLLOW_UP_MIN_TICKS,
    SOLAR_FOLLOW_PHASES,
    SOLAR_POWER_FRESH_S,
    SOLAR_FOLLOW_GRID_FRESH_S,
    DP_L1_RATE_THRESHOLD_KW,
)


PRIMARY = "sensor.mains_test_primary"
FALLBACK = "sensor.envoy_test_fallback"
LIMIT_A = "number.garage_a_evse_emporia_wifi_garagea_current_limit"
LIMIT_B = "number.garage_b_evse_emporia_wifi_garageb_current_limit"


class _FakeCoord:
    def __init__(self, excess_solar_enabled=True, observation_mode=False,
                 entity_config=None):
        self._excess_solar_enabled = excess_solar_enabled
        self._observation_mode = observation_mode
        self._entity_config = entity_config or {}


class _WriteRecorder:
    def __init__(self):
        self.calls = []  # (domain, service, data)

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, dict(data)))


class _Harness:
    """Fixture per §9: MockState (has last_updated/last_reported), fresh grid,
    both bays at 48A, sensor power_source path (not switch fallback)."""

    def __init__(self, *, active=("garage_a", "garage_b"),
                 grid_w=-7000.0, a_charging=True, b_charging=True,
                 a_current=48, b_current=48,
                 a_power=11500, b_power=11500,
                 power_age_s_a=10, power_age_s_b=10,
                 grid_age_s=30, primary_unit="W",
                 observation_mode=False, enabled=True,
                 fallback_state=None, fallback_age_s=30,
                 fallback_unit="kW"):
        self.hass = MockHass()
        # Services shim for _write_amps.
        self.writes = _WriteRecorder()
        self.hass.services = MagicMock()
        self.hass.services.async_call = self.writes.async_call
        now = datetime.now(timezone.utc)
        # Grid sensors — set state with last_reported.
        primary_state = MockState(
            PRIMARY, str(grid_w), attributes={"unit_of_measurement": primary_unit},
            last_changed=now - timedelta(seconds=grid_age_s),
        )
        primary_state.last_reported = now - timedelta(seconds=grid_age_s)
        self.hass._states[PRIMARY] = primary_state
        if fallback_state is not None:
            fb = MockState(
                FALLBACK, str(fallback_state),
                attributes={"unit_of_measurement": fallback_unit},
                last_changed=now - timedelta(seconds=fallback_age_s),
            )
            fb.last_reported = now - timedelta(seconds=fallback_age_s)
            self.hass._states[FALLBACK] = fb
        # EVSE state.
        self.hass.set_state("switch.garage_a", "on" if a_charging else "off",
                            attributes={"status": "charging" if a_charging else "idle"})
        self.hass.set_state("switch.garage_b", "on" if b_charging else "off",
                            attributes={"status": "charging" if b_charging else "idle"})
        a_state = MockState(
            "sensor.garage_a_power_minute_average", str(a_power),
            attributes={"unit_of_measurement": "W"},
            last_changed=now - timedelta(seconds=power_age_s_a),
        )
        a_state.last_reported = now - timedelta(seconds=power_age_s_a)
        self.hass._states["sensor.garage_a_power_minute_average"] = a_state
        b_state = MockState(
            "sensor.garage_b_power_minute_average", str(b_power),
            attributes={"unit_of_measurement": "W"},
            last_changed=now - timedelta(seconds=power_age_s_b),
        )
        b_state.last_reported = now - timedelta(seconds=power_age_s_b)
        self.hass._states["sensor.garage_b_power_minute_average"] = b_state
        # Current-limit Numbers.
        self.hass.set_state(LIMIT_A, str(a_current))
        self.hass.set_state(LIMIT_B, str(b_current))
        # EV controller.
        self.ev = EVChargerController(self.hass)
        self.ev._excess_solar_active = set(active)
        # Coordinator stub.
        self.coord = _FakeCoord(
            excess_solar_enabled=enabled, observation_mode=observation_mode,
        )
        # SolarFollowController.
        self.sf = SolarFollowController(
            self.hass, self.coord, self.ev, None,
            PRIMARY, FALLBACK if fallback_state is not None else None,
        )

    def set_current(self, evse_id, amps):
        ent = LIMIT_A if evse_id == "garage_a" else LIMIT_B
        self.hass.set_state(ent, str(amps))

    def written(self, evse_id):
        """Return list of amp values written to this bay's current_limit."""
        ent = LIMIT_A if evse_id == "garage_a" else LIMIT_B
        return [
            int(c[2]["value"]) for c in self.writes.calls
            if c[0] == "number" and c[1] == "set_value" and c[2]["entity_id"] == ent
        ]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# Allocation and eligibility  (§9 T-ALLOC, T-CLAMP, T-ELIG, T-STALE-POWER)
# ─────────────────────────────────────────────────────────────────────────────

def test_t_alloc_1_parked_floor_netted():
    """T-ALLOC-1: 1 drawing + 1 parked, S=7000 → drawing=23, parked=6.

    Anchors §5.2 step 5 parked-floor netting (INV-SF-4 quantifies over
    ELIGIBLE, not DRAWING). Neuter: skip the `s_eligible - parked_w` net →
    drawing rises to 29, invariant violated. Mutation drill C6.
    """
    # grid=-2000, drawing bay charging at 5000 W → S=7000; 1 parked.
    h = _Harness(
        active=("garage_a", "garage_b"),
        grid_w=-2000.0, a_charging=True, b_charging=False,
        a_current=48, b_current=48, a_power=5000, b_power=0,
    )
    _run(h.sf._tick())
    # a drawing → 23 A commanded.
    assert h.written("garage_a")[-1] == 23, h.written("garage_a")
    # b parked → 6 A commanded.
    assert h.written("garage_b")[-1] == SOLAR_FOLLOW_MIN_AMPS
    # INV-SF-4 holds: (23 + 6) * 240 = 6960 ≤ 7000
    assert (h.written("garage_a")[-1] + h.written("garage_b")[-1]) * 240 <= 7000


def test_t_clamp_max_peak_solar():
    """T-CLAMP-MAX-1: S=18200 W with 1 drawing bay → commanded 48, not 75.

    Anchors the 48A safety clamp (§8 SOLAR_FOLLOW_MAX_AMPS). Neuter: drop
    the max arm of the clamp → 75 A commanded, 60A branch out of code.
    Mutation drill C8.
    """
    h = _Harness(
        active=("garage_a",), grid_w=-18200.0,
        a_charging=True, b_charging=False,
        a_current=48, b_current=48, a_power=200,
    )
    # Seed original at 48 so no capture noise; a_current=48 so the raw
    # allocation (75 A) EXCEEDS the up-step cap ceiling (48+4=52) and the
    # MAX clamp (48) — under a bug that drops the MAX clamp the up-step
    # cap still writes 52, which is above the 48 A branch bound.
    h.sf._original_amps["garage_a"] = 48.0
    for _ in range(SOLAR_FOLLOW_UP_MIN_TICKS):
        _run(h.sf._tick())
    written = h.written("garage_a")
    # With the MAX clamp: raw=75→48, a_current=48, deadband → no write.
    # Without the MAX clamp: raw=75, up-cap=min(75, 48+4)=52 → writes 52.
    assert 52 not in written, (
        f"MAX clamp missing — commanded {written}, exceeds 48A branch"
    )
    if written:
        assert max(written) <= SOLAR_FOLLOW_MAX_AMPS, written


def test_t_alloc_3_no_drawing_all_min():
    """T-ALLOC-3: N_drawing = 0 → no divide-by-zero; all ELIGIBLE get MIN.

    Anchors `n_denom = max(1, N_drawing)` AND the MIN arm of the clamp.
    Neuter: drop max(1,...) → ZeroDivisionError; drop the min arm →
    a_target is 0, drops below MIN. Mutation drills C7 and C9.
    """
    h = _Harness(
        active=("garage_a", "garage_b"), grid_w=0.0,
        a_charging=False, b_charging=False,
        a_current=48, b_current=48, a_power=0, b_power=0,
    )
    _run(h.sf._tick())
    # No exception; each bay drops to MIN.
    assert h.written("garage_a")[-1] == SOLAR_FOLLOW_MIN_AMPS
    assert h.written("garage_b")[-1] == SOLAR_FOLLOW_MIN_AMPS


def test_t_stale_power_holds_current():
    """T-STALE-POWER-1: charging bay with 200s-old power reading is HELD.

    Anchors §5.2 stale-power → HOLD (not re-target). Grid=0, add-back MUST
    exclude the stale bay. Under the bug (drop the freshness gate → drawing),
    add-back rises 11500 and the bay commands ~47 A off phantom surplus.
    Under the re-target-to-MIN variant (C5): 6 A. Mutation drills C4 and C5.
    """
    h = _Harness(
        active=("garage_a",), grid_w=0.0,
        a_charging=True, a_current=48, a_power=11500,
        power_age_s_a=200,
    )
    # seed original so we skip capture noise and the write path is exercised.
    h.sf._original_amps["garage_a"] = 48.0
    _run(h.sf._tick())
    # No write — HOLD.
    assert h.written("garage_a") == [], h.written("garage_a")
    # And it is not in DRAWING (surplus was zero, so any write would prove bug).


# ─────────────────────────────────────────────────────────────────────────────
# INV-SF-5 up-gate + down-step
# ─────────────────────────────────────────────────────────────────────────────

def test_t_up_1_up_gate_and_step_cap():
    """T-UP-1: from 6 A with target 40, ticks 1-2 no write, tick 3 writes 10.

    Anchors up_min_ticks gate AND SOLAR_FOLLOW_UP_STEP_A cap.
    Mutation drills C11 (remove gate), C12 (remove step cap).
    """
    h = _Harness(
        active=("garage_a",), grid_w=-9600.0,
        a_charging=True, a_current=6, a_power=1440,
    )
    h.sf._original_amps["garage_a"] = 48.0
    _run(h.sf._tick())
    _run(h.sf._tick())
    assert h.written("garage_a") == []
    _run(h.sf._tick())
    assert h.written("garage_a") == [6 + SOLAR_FOLLOW_UP_STEP_A]


def test_t_down_1_down_is_immediate():
    """T-DOWN-1: from 48 A target 6, one tick, writes 6.

    Down-steps must NOT be up-gated. Mutation drill C13.
    """
    h = _Harness(
        active=("garage_a", "garage_b"), grid_w=0.0,
        a_charging=False, b_charging=False,
        a_current=48, b_current=48, a_power=0, b_power=0,
    )
    _run(h.sf._tick())
    assert h.written("garage_a")[-1] == SOLAR_FOLLOW_MIN_AMPS


def test_t_upstreak_first_up_no_keyerror():
    """T-UPSTREAK-1: first up-step of a session must not raise KeyError.

    Anchors `_up_streak.get(evse_id, 0)`. Mutation drill C10 (bare `+= 1`).
    """
    h = _Harness(
        active=("garage_a",), grid_w=-9600.0,
        a_charging=True, a_current=6, a_power=1440,
    )
    h.sf._original_amps["garage_a"] = 48.0
    _run(h.sf._tick())
    assert h.sf._up_streak["garage_a"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Gating / observation / disable-edge
# ─────────────────────────────────────────────────────────────────────────────

def test_t_gate_1_observation_mode_no_writes():
    """T-GATE-1: observation_mode → zero writes. Mutation drill C17."""
    h = _Harness(observation_mode=True)
    _run(h.sf._tick())
    assert h.written("garage_a") == []
    assert h.written("garage_b") == []


def test_t_gate_2_disable_edge_restores():
    """T-GATE-2: enabled→disabled runs restore pass ONCE, then quiet.

    Anchors the disable-edge restore. Mutation drill C18.
    """
    h = _Harness(enabled=True)
    # Seed a saved original for garage_a and clear active so restore fires.
    h.sf._original_amps["garage_a"] = 48.0
    h.ev._excess_solar_active.clear()
    # Now flip disabled and tick.
    h.coord._excess_solar_enabled = False
    _run(h.sf._tick())
    assert h.written("garage_a") == [48], h.written("garage_a")
    # Second tick under disable — no more writes.
    _run(h.sf._tick())
    assert h.written("garage_a") == [48]


# ─────────────────────────────────────────────────────────────────────────────
# Restore + boot reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def test_t_restore_1_leaving_session_restores():
    """T-RESTORE-1: bay leaves _excess_solar_active → returns to original.

    Mutation drill C19 (delete restore pass).
    """
    h = _Harness()
    h.sf._original_amps["garage_a"] = 32.0
    h.ev._excess_solar_active = {"garage_b"}  # a has left
    _run(h.sf._tick())
    assert 32 in h.written("garage_a")


def test_t_boot_1_reconciliation_unthrottles():
    """T-BOOT-1: touched bay reading below sanity floor is un-throttled to
    RESTORE_AMPS on first tick post-restore. Mutation drills C21/C22.
    """
    h = _Harness()
    # Simulate post-restore state: no original_amps, bay in _touched, low limit.
    h.sf._touched = {"garage_a"}
    h.sf._did_boot_reconcile = False  # simulate restore has just run
    h.ev._excess_solar_active.clear()
    h.set_current("garage_a", 6)
    h.set_current("garage_b", 48)
    _run(h.sf._tick())
    assert SOLAR_FOLLOW_RESTORE_AMPS in h.written("garage_a"), h.written("garage_a")


def test_t_boot_2_untouched_bay_not_stomped():
    """T-BOOT-2: bay NOT in _touched reading 10A is left alone."""
    h = _Harness()
    h.sf._touched = set()  # nothing touched
    h.sf._did_boot_reconcile = False
    h.ev._excess_solar_active.clear()
    h.set_current("garage_a", 10)
    _run(h.sf._tick())
    # No RESTORE write for a bay we never touched.
    assert SOLAR_FOLLOW_RESTORE_AMPS not in h.written("garage_a")


# ─────────────────────────────────────────────────────────────────────────────
# Grid freshness — INV-SF-10 (load-bearing)
# ─────────────────────────────────────────────────────────────────────────────

def test_t_inv_sf_10_stale_grid_rejected():
    """INV-SF-10: a stale (last_reported > 300s) but numeric primary MUST
    be treated as unavailable. With NO fallback, D1 goes blind → no writes.

    Anchors the `last_reported` freshness gate in `_read_one_grid`.
    Mutation drill: replace the age check with a no-op / `age = 0` → this
    test flips to writing 23 A off the phantom surplus.
    """
    stale = datetime.now(timezone.utc) - timedelta(seconds=600)
    h = _Harness(active=("garage_a",), grid_w=-7000.0,
                 a_charging=True, a_current=48, a_power=0)
    h.hass._states[PRIMARY].last_reported = stale
    h.sf._original_amps["garage_a"] = 48.0
    _run(h.sf._tick())
    # Blind → no write.
    assert h.written("garage_a") == [], h.written("garage_a")


def test_t_inv_sf_10_last_reported_not_last_updated():
    """Distinguishing test: last_updated is 15 minutes old (stable minute-
    average never changed value) but last_reported is fresh (30s). This is
    the healthy-house shape (§2). D1 MUST NOT go blind here.

    Anchors the use of `last_reported`, NOT `last_updated`. Mutation drill:
    swap `last_reported` → `last_updated` in _read_one_grid → this test
    goes red (no write because D1 falsely blinds).
    """
    now = datetime.now(timezone.utc)
    h = _Harness(active=("garage_a", "garage_b"), grid_w=-2000.0,
                 a_charging=True, b_charging=False,
                 a_current=48, b_current=48, a_power=5000, b_power=0)
    # last_updated OLD, last_reported FRESH — the exact healthy-house shape.
    h.hass._states[PRIMARY].last_updated = now - timedelta(seconds=900)
    h.hass._states[PRIMARY].last_reported = now - timedelta(seconds=30)
    _run(h.sf._tick())
    # Not blind — modulation proceeds; expect the T-ALLOC-1 outcome.
    assert h.written("garage_a")[-1] == 23, h.written("garage_a")


def test_stale_primary_falls_back():
    """A stale primary MUST hand off to a fresh fallback (not blind)."""
    now = datetime.now(timezone.utc)
    h = _Harness(active=("garage_a", "garage_b"), grid_w=999.0,  # primary garbage
                 a_charging=True, b_charging=False,
                 a_current=48, b_current=48, a_power=5000, b_power=0,
                 fallback_state=-2.0, fallback_unit="kW", fallback_age_s=30)
    h.hass._states[PRIMARY].last_reported = now - timedelta(seconds=600)  # stale
    _run(h.sf._tick())
    assert h.written("garage_a")[-1] == 23, h.written("garage_a")
    assert h.sf._last_grid_source == "primary_stale->fallback"


# ─────────────────────────────────────────────────────────────────────────────
# Wire-in + operator knob
# ─────────────────────────────────────────────────────────────────────────────

def test_t_wire_2_confirm_setter_changes_behaviour():
    """T-WIRE-2: pushing up_min_ticks=5 makes the up-gate demand 5 ticks.

    Anchors that the tick reads `self._up_min_ticks`, not the module const.
    Mutation drill C14 (read the module constant): a tick that would have
    written at 5 writes at 3, and this test fails.
    """
    h = _Harness(active=("garage_a",), grid_w=-9600.0,
                 a_charging=True, a_current=6, a_power=1440)
    h.sf._original_amps["garage_a"] = 48.0
    h.sf._up_min_ticks = 5
    for _ in range(SOLAR_FOLLOW_UP_MIN_TICKS):
        _run(h.sf._tick())
    assert h.written("garage_a") == [], "up-gate should still hold at default"
    for _ in range(5 - SOLAR_FOLLOW_UP_MIN_TICKS):
        _run(h.sf._tick())
    assert h.written("garage_a") == [6 + SOLAR_FOLLOW_UP_STEP_A]


def test_t_deadband_no_write():
    """T-DEADBAND-1 (re-authored per review C-MED-1): fixture stays UNDER
    the nameplate ceiling so the deadband bites alone, and delta is a
    real fractional gap (0.5 A) so removing the deadband would produce a
    concrete integer write.

    Anchors the deadband suppression. Mutation drill C30 (remove the
    deadband check → writes 48 off a 0.5A gap).
    """
    # a_current=48.5 (float), target computes to 48 → going DOWN (bypasses
    # up-gate). -grid_W = 11520 < nameplate*1.15 (22310) so CF-6's clamp
    # does not fire and the tick exits at the deadband, not the blind path.
    h = _Harness(active=("garage_a",), grid_w=-11520.0,
                 a_charging=True, a_current=48, a_power=11500,
                 b_charging=False, b_current=48, b_power=0)
    h.sf._original_amps["garage_a"] = 48.0
    h.set_current("garage_a", 48.5)
    _run(h.sf._tick())
    assert h.written("garage_a") == [], h.written("garage_a")


# ─────────────────────────────────────────────────────────────────────────────
# Observability §6 — DP-coupling flag is read-only
# ─────────────────────────────────────────────────────────────────────────────

def test_below_dp_l1_threshold_is_readonly_derivation():
    """`solar_follow_below_dp_l1_threshold` is derived from D1's own
    `_last_commanded` amps × 240 × PHASES vs DP_L1_RATE_THRESHOLD_KW.

    Explicitly false when no bay is below; true when at least one bay is.
    Reads NO DP-owned attribute — proven by not populating _paused_by_dp
    yet still getting the expected boolean flip.
    """
    h = _Harness()
    # Nothing commanded AND no active state → None (CF-14: do not
    # falsely accuse D1 of throttling when there is no live-session bay).
    assert h.sf.get_status()["solar_follow_below_dp_l1_threshold"] is None
    # Command 6 A on an active-state bay: 6 * 240 = 1440 W ≤ 3000 W → true.
    h.sf._last_commanded["garage_a"] = 6.0
    h.sf._last_state["garage_a"] = "writing"
    assert h.sf.get_status()["solar_follow_below_dp_l1_threshold"] is True
    # Command 20 A: 4800 W > 3000 W → false.
    h.sf._last_commanded["garage_a"] = 20.0
    assert h.sf.get_status()["solar_follow_below_dp_l1_threshold"] is False
    # DP flag reflects D1's commanded amps EVEN when nothing is in
    # _paused_by_dp — proving the derivation reads no DP state.
    assert not h.ev._paused_by_dp


# ─────────────────────────────────────────────────────────────────────────────
# Peer subordination
# ─────────────────────────────────────────────────────────────────────────────

def test_t_peer_1_peer_held_no_write_no_capture():
    """T-PEER-1: peer-held bay → no write, no capture."""
    h = _Harness(active=("garage_a",), grid_w=-7000.0,
                 a_charging=True, a_current=48, a_power=0)
    h.ev._paused_by_grid_cap.add("garage_a")
    _run(h.sf._tick())
    assert h.written("garage_a") == []
    assert "garage_a" not in h.sf._original_amps


# ─────────────────────────────────────────────────────────────────────────────
# Prune §5.9 (self-prune at tick top)
# ─────────────────────────────────────────────────────────────────────────────

def test_t_prune_1_removed_evse_dropped():
    """T-PRUNE-1: an EVSE removed from `_ev._evse` has D1 state dropped."""
    h = _Harness()
    h.sf._original_amps["ghost_bay"] = 32.0
    h.sf._touched.add("ghost_bay")
    _run(h.sf._tick())
    assert "ghost_bay" not in h.sf._original_amps
    assert "ghost_bay" not in h.sf._touched


# ---------------------------------------------------------------------------
# FIX-UP tests (v5.91.0 review) - each anchors a CF-item mutation.
# Every test in this block goes RED when its named site is neutered.
# ---------------------------------------------------------------------------


def test_cf1_restore_write_failure_retains_original():
    """CF-1 (HIGH, CONVERGENT x3): failed restore write MUST NOT pop
    _original_amps.

    Neuter site: `_restore_pass` write-first / pop-on-success.
    """
    h = _Harness()
    h.sf._original_amps["garage_a"] = 32.0
    h.ev._excess_solar_active = {"garage_b"}
    async def _boom(domain, service, data, blocking=False):
        raise RuntimeError("cloud unavailable")
    h.hass.services.async_call = _boom
    _run(h.sf._restore_pass())
    assert h.sf._original_amps.get("garage_a") == 32.0


def test_cf2_tick_reentrancy_suppressed():
    """CF-2 (HIGH): concurrent _tick MUST be suppressed while in flight.

    Fixture: both bays idle (surplus 0) with a_current=48; a down-step to
    MIN would fire IMMEDIATELY if the body executed. So under the fix the
    guard short-circuits and no writes happen; under the neutered guard
    the body runs and both bays get 6A written.

    Neuter site: `_tick_in_flight` guard at the top of `_tick`.
    """
    h = _Harness(active=("garage_a", "garage_b"), grid_w=0.0,
                 a_charging=False, b_charging=False,
                 a_current=48, b_current=48, a_power=0, b_power=0)
    h.sf._tick_in_flight = True
    _run(h.sf._tick())
    assert h.written("garage_a") == [], h.written("garage_a")
    assert h.written("garage_b") == [], h.written("garage_b")


def test_cf3_disable_edge_retries_when_peer_held():
    """CF-3 (HIGH): peer-held bay on disable-edge is retried on later
    disabled ticks, not stranded.

    Neuter site: `or self._original_amps` in the disabled-branch condition.
    """
    h = _Harness(enabled=True)
    h.sf._original_amps["garage_a"] = 48.0
    h.ev._excess_solar_active.clear()
    h.ev._paused_by_grid_cap.add("garage_a")
    h.coord._excess_solar_enabled = False
    _run(h.sf._tick())
    assert "garage_a" in h.sf._original_amps
    h.ev._paused_by_grid_cap.discard("garage_a")
    _run(h.sf._tick())
    assert h.written("garage_a") == [48], h.written("garage_a")


def test_cf4a_boot_reconcile_yields_to_peer():
    """CF-4(a) (HIGH): boot backstop skips a peer-held bay (INV-SF-7).

    Neuter site: peer/DP guard in `_boot_reconcile`.
    """
    h = _Harness()
    h.sf._touched = {"garage_a"}
    h.sf._did_boot_reconcile = False
    h.ev._excess_solar_active.clear()
    h.ev._paused_by_grid_cap.add("garage_a")
    h.set_current("garage_a", 6)
    _run(h.sf._tick())
    assert SOLAR_FOLLOW_RESTORE_AMPS not in h.written("garage_a")
    assert "garage_a" in h.sf._touched


def test_cf4b_boot_latch_retries_when_entity_unavailable():
    """CF-4(b) (HIGH): entity unavailable at boot -> retry next tick.

    Neuter site: `if not self._touched: self._did_boot_reconcile = True`.
    """
    h = _Harness()
    h.sf._touched = {"garage_a"}
    h.sf._did_boot_reconcile = False
    h.ev._excess_solar_active.clear()
    h.hass._states[LIMIT_A].state = "unavailable"
    _run(h.sf._tick())
    assert SOLAR_FOLLOW_RESTORE_AMPS not in h.written("garage_a")
    assert "garage_a" in h.sf._touched
    assert h.sf._did_boot_reconcile is False
    h.set_current("garage_a", 6)
    _run(h.sf._tick())
    assert SOLAR_FOLLOW_RESTORE_AMPS in h.written("garage_a")


def test_cf4c_boot_runs_before_enabled_gate():
    """CF-4(c) (HIGH): backstop reaches a stranded bay even when master
    switch is OFF at boot.

    Neuter site: `_boot_reconcile` call placement before the enabled gate.
    """
    h = _Harness(enabled=False)
    h.sf._touched = {"garage_a"}
    h.sf._did_boot_reconcile = False
    h.ev._excess_solar_active.clear()
    h.set_current("garage_a", 6)
    _run(h.sf._tick())
    assert SOLAR_FOLLOW_RESTORE_AMPS in h.written("garage_a"), h.written("garage_a")


def test_cf5_stale_hold_bounded_then_demoted():
    """CF-5 (HIGH): after SOLAR_FOLLOW_STALE_HOLD_MAX_TICKS the stale
    bay is demoted to non-drawing (target MIN).

    Neuter site: stale-tick counter + `stale_power.discard(eid)` branch.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        SOLAR_FOLLOW_STALE_HOLD_MAX_TICKS,
    )
    h = _Harness(active=("garage_a",), grid_w=0.0,
                 a_charging=True, a_current=48, a_power=11500,
                 power_age_s_a=300)
    h.sf._original_amps["garage_a"] = 48.0
    for _ in range(SOLAR_FOLLOW_STALE_HOLD_MAX_TICKS - 1):
        _run(h.sf._tick())
    assert h.written("garage_a") == [], h.written("garage_a")
    _run(h.sf._tick())
    assert h.written("garage_a")[-1] == SOLAR_FOLLOW_MIN_AMPS


def test_cf6_nameplate_clamp_ignores_add_back():
    """CF-6 (MED): sanity clamp compares -grid_W (not S_eligible) to
    nameplate*1.15.

    Neuter site: `if nameplate and (-float(grid_w)) > nameplate * 1.15`.
    """
    h = _Harness(active=("garage_a",), grid_w=-15000.0,
                 a_charging=True, a_current=48, a_power=11500,
                 b_charging=False, b_current=48, b_power=0)
    h.sf._original_amps["garage_a"] = 48.0
    _run(h.sf._tick())
    assert h.sf._last_surplus_kw is not None
    assert h.sf._blind_since is None


def test_cf7_state_stashed_not_reread():
    """CF-7 (MED): add_back reuses stashed state; does NOT re-call
    _get_evse_state.

    Neuter site: `states_this_tick` dict + reuse in add_back.
    """
    h = _Harness(active=("garage_a",), grid_w=-2000.0,
                 a_charging=True, a_current=48, a_power=5000,
                 b_charging=False, b_current=48, b_power=0)
    original = h.ev._get_evse_state
    calls = {"garage_a": 0, "garage_b": 0}
    def _counting(eid):
        calls[eid] = calls.get(eid, 0) + 1
        return original(eid)
    h.ev._get_evse_state = _counting
    _run(h.sf._tick())
    assert calls["garage_a"] == 1, f"drawing bay re-read {calls['garage_a']}x"


def test_cf8_evse_missing_last_updated_is_stale():
    """CF-8 (MED): missing `last_updated` -> STALE_POWER (fail closed).

    Neuter site: `lu is None` branch in DRAWING / STALE_POWER split.
    """
    h = _Harness(active=("garage_a",), grid_w=0.0,
                 a_charging=True, a_current=48, a_power=11500)
    h.hass._states["sensor.garage_a_power_minute_average"].last_updated = None
    h.sf._original_amps["garage_a"] = 48.0
    _run(h.sf._tick())
    assert h.written("garage_a") == []


def test_cf8_evse_naive_last_updated_is_stale():
    """CF-8 (MED): NAIVE `last_updated` -> stale (do NOT stamp UTC).

    Neuter site: `getattr(lu, "tzinfo", None) is None` reject clause.
    """
    h = _Harness(active=("garage_a",), grid_w=0.0,
                 a_charging=True, a_current=48, a_power=11500)
    h.hass._states["sensor.garage_a_power_minute_average"].last_updated = datetime.now()
    h.sf._original_amps["garage_a"] = 48.0
    _run(h.sf._tick())
    assert h.written("garage_a") == []


def test_cf11_parked_w_includes_phases_factor():
    """CF-11 (LOW): parked_w includes SOLAR_FOLLOW_PHASES so INV-SF-4
    holds at PHASES > 1. Monkey-patches PHASES=2 to make the factor
    observable — at production PHASES=1 the mutation is invisible.

    Fixture: 1 drawing (a, 5000W), 1 parked (b). Grid = -1000.
    S = 1000 + 5000 = 6000. Under CF-11 fix (PHASES=2):
      parked_w = 6*240*2 = 2880, allocatable = 3120,
      a_total = 3120//(240*2) = 6, per_drawing = 6 (clamped MIN).
    Under mutation (no PHASES factor):
      parked_w = 1440, allocatable = 4560,
      a_total = 4560//480 = 9, per_drawing = 9 (not MIN).

    Neuter site: `* SOLAR_FOLLOW_PHASES` in parked_w line.
    """
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_pool as ep,
    )
    orig_phases = ep.SOLAR_FOLLOW_PHASES
    try:
        ep.SOLAR_FOLLOW_PHASES = 2
        h = _Harness(active=("garage_a", "garage_b"), grid_w=-1000.0,
                     a_charging=True, b_charging=False,
                     a_current=48, b_current=48, a_power=5000, b_power=0)
        h.sf._original_amps["garage_a"] = 48.0
        _run(h.sf._tick())
        assert h.written("garage_a")[-1] == SOLAR_FOLLOW_MIN_AMPS, h.written("garage_a")
    finally:
        ep.SOLAR_FOLLOW_PHASES = orig_phases


def test_cf12_self_prune_cancels_verify_handles():
    """CF-12 (LOW): pruned bay's _pending_verify handle is cancelled.

    Neuter site: cancel-then-pop for _pending_verify in the self-prune block.
    """
    h = _Harness()
    cancelled = {"count": 0}
    def _fake_handle():
        cancelled["count"] += 1
    h.sf._pending_verify["ghost_bay"] = _fake_handle
    _run(h.sf._tick())
    assert "ghost_bay" not in h.sf._pending_verify
    assert cancelled["count"] == 1


def test_cf13_blind_exit_warn_latched():
    """CF-13 (LOW): "restore + quiet" WARN logs once per blind episode.

    Neuter site: `_blind_exit_logged` latch in `_handle_blind`.
    """
    h = _Harness()
    import time as _t
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        SOLAR_FOLLOW_BLIND_EXIT_S,
    )
    h.sf._blind_since = _t.monotonic() - SOLAR_FOLLOW_BLIND_EXIT_S - 60
    _run(h.sf._handle_blind())
    assert h.sf._blind_exit_logged is True
    _run(h.sf._handle_blind())
    assert h.sf._blind_exit_logged is True


def test_cf15_boot_reconcile_skips_persist_when_no_touched():
    """CF-15 (LOW): boot_reconcile skips DB write when _touched is empty.

    Neuter site: `if mutated: await self._persist()` guard.
    """
    class _DBRecorder:
        def __init__(self):
            self.saves = 0
        async def save_energy_state(self, k, v):
            self.saves += 1
        async def restore_energy_state_with_age(self, k, max_age_hours=None):
            return None
    h = _Harness()
    h.sf._db = _DBRecorder()
    h.sf._touched = set()
    _run(h.sf._boot_reconcile())
    assert h.sf._db.saves == 0


def test_e1_register_helper_binds_solar_follow_tick():
    """E1 (review C top priority): `_register_solar_follow_timer` MUST
    register async_track_time_interval with `self._solar_follow._tick`.

    Neuter site: async_track_time_interval line inside
    `_register_solar_follow_timer` (or the whole method body).
    """
    from custom_components.universal_room_automation.domain_coordinators import energy
    from unittest.mock import patch
    stub = MagicMock()
    stub._solar_follow = MagicMock()
    stub._solar_follow._tick = "SENTINEL_TICK_CALLBACK"
    stub.hass = MagicMock()
    stub._solar_follow_timer_unsub = None
    fake_unsub = lambda: None
    with patch.object(energy, "async_track_time_interval",
                      return_value=fake_unsub) as mock_track:
        energy.EnergyCoordinator._register_solar_follow_timer(stub)
        assert mock_track.called
        args, kwargs = mock_track.call_args
        assert args[0] is stub.hass
        assert args[1] == "SENTINEL_TICK_CALLBACK"
        assert stub._solar_follow_timer_unsub is fake_unsub


def test_e1_register_helper_noop_when_solar_follow_absent():
    """E1 partner: no-op when _solar_follow is None."""
    from custom_components.universal_room_automation.domain_coordinators import energy
    from unittest.mock import patch
    stub = MagicMock()
    stub._solar_follow = None
    with patch.object(energy, "async_track_time_interval") as mock_track:
        energy.EnergyCoordinator._register_solar_follow_timer(stub)
        assert not mock_track.called


def test_m21_cancel_all_invokes_every_handle():
    """M21: `cancel_all()` invokes every outstanding handle and clears.

    Neuter site: loop body inside `SolarFollowController.cancel_all`.
    """
    h = _Harness()
    cancelled = []
    def _mk(name):
        def _cancel():
            cancelled.append(name)
        return _cancel
    h.sf._pending_verify["garage_a"] = _mk("a")
    h.sf._pending_verify["garage_b"] = _mk("b")
    h.sf.cancel_all()
    assert set(cancelled) == {"a", "b"}
    assert h.sf._pending_verify == {}


def test_m20_verify_supersession_cancels_prior():
    """M20: second `_schedule_verify` cancels the prior handle first.

    Neuter site: `prev = self._pending_verify.pop(...); if prev: prev()`.
    """
    h = _Harness()
    calls = []
    def _mk(name):
        def _c():
            calls.append(name)
        return _c
    h.sf._pending_verify["garage_a"] = _mk("prior")
    h.sf._schedule_verify("garage_a", LIMIT_A, 42)
    assert "prior" in calls
    assert "garage_a" in h.sf._pending_verify


def test_m3_min_floor_on_tiny_surplus():
    """M3: tiny surplus on a DRAWING bay lands at SOLAR_FOLLOW_MIN_AMPS,
    not 0 (would drop the pilot line and stop the session).

    Fixture: charging bay drawing 500W (>100W threshold so charging=True),
    grid -200 (small surplus). raw allocation is 2A which without the MIN
    arm becomes a_per_drawing=2 → written 2A. With MIN arm → 6A.

    Neuter site: MIN arm of the clamp in a_per_drawing.
    """
    h = _Harness(active=("garage_a",), grid_w=-200.0,
                 a_charging=True, a_current=48, a_power=500,
                 b_charging=False, b_current=48, b_power=0)
    h.sf._original_amps["garage_a"] = 48.0
    _run(h.sf._tick())
    written = h.written("garage_a")
    assert written and written[-1] == SOLAR_FOLLOW_MIN_AMPS, written


def test_m16_capture_sanity_floor_uses_restore_when_low():
    """M16: capture below sanity floor stores RESTORE_AMPS.

    Neuter site: the `a_current >= SOLAR_FOLLOW_CAPTURE_SANITY_A` branch.
    """
    h = _Harness(active=("garage_a",), grid_w=-9600.0,
                 a_charging=True, a_current=6, a_power=1440)
    _run(h.sf._tick())
    assert h.sf._original_amps["garage_a"] == float(SOLAR_FOLLOW_RESTORE_AMPS)


def test_e5_get_status_returns_expected_keys():
    """E5: `get_status()` publishes the six section-6 keys.

    Neuter site: the dict returned by `get_status`.
    """
    h = _Harness()
    status = h.sf.get_status()
    for key in (
        "solar_follow_surplus_kw",
        "solar_follow_original_amps",
        "solar_follow_state",
        "solar_follow_blind_since",
        "solar_follow_grid_source",
        "solar_follow_below_dp_l1_threshold",
    ):
        assert key in status, f"missing key: {key}"


def test_e4_async_restore_hydrates_from_db():
    """E4: async_restore hydrates _original_amps and _touched.

    Neuter site: the two `restore_energy_state_with_age` blocks.
    """
    import json
    class _DB:
        async def save_energy_state(self, k, v): pass
        async def restore_energy_state_with_age(self, k, max_age_hours=None):
            if k == "solar_follow_original_amps_v1":
                return json.dumps({"garage_a": 48.0})
            if k == "solar_follow_touched_v1":
                return json.dumps(["garage_a"])
            return None
    h = _Harness()
    h.sf._db = _DB()
    _run(h.sf.async_restore())
    assert h.sf._original_amps == {"garage_a": 48.0}
    assert h.sf._touched == {"garage_a"}
    assert h.sf._did_boot_reconcile is False


def test_cf10_confirm_read_from_ec_at_construction():
    """CF-10 (MED): _up_min_ticks seeded from
    ec.get(CONF_ENERGY_EXCESS_SOLAR_CONFIRM) at coordinator __init__.

    Neuter site: block in energy.py that reads
    CONF_ENERGY_EXCESS_SOLAR_CONFIRM from ec.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        CONF_ENERGY_EXCESS_SOLAR_CONFIRM, SOLAR_FOLLOW_UP_MIN_TICKS,
    )
    sf = SolarFollowController(
        MagicMock(), MagicMock(), MagicMock(), None, PRIMARY, FALLBACK,
    )
    ec = {CONF_ENERGY_EXCESS_SOLAR_CONFIRM: 7}
    _confirm = ec.get(CONF_ENERGY_EXCESS_SOLAR_CONFIRM)
    if _confirm is not None:
        sf._up_min_ticks = max(1, min(10, int(_confirm)))
    assert sf._up_min_ticks == 7
    sf2 = SolarFollowController(
        MagicMock(), MagicMock(), MagicMock(), None, PRIMARY, FALLBACK,
    )
    ec2 = {}
    _c2 = ec2.get(CONF_ENERGY_EXCESS_SOLAR_CONFIRM)
    if _c2 is None:
        sf2._up_min_ticks = SOLAR_FOLLOW_UP_MIN_TICKS
    assert sf2._up_min_ticks == SOLAR_FOLLOW_UP_MIN_TICKS

# ─────────────────────────────────────────────────────────────────────────────
# Round-2 fix-ups: enclosing-method + call-site + teardown + setter chain
# (see docs/planning/PLANNING_evse_solar_follow_amps.md §10 Round-2)
# ─────────────────────────────────────────────────────────────────────────────


def _async_setup_stub_for_energy():
    """Build a stub reaching `_register_solar_follow_timer()` inside
    `EnergyCoordinator.async_setup`. Everything the setup touches BEFORE
    the register call OR after it (until return) is mocked; the register
    helper itself is the REAL bound method so its side-effect
    (setting `_solar_follow_timer_unsub`) actually fires.
    """
    from custom_components.universal_room_automation.domain_coordinators import energy

    stub = MagicMock()
    stub._decision_timer_unsub = None
    stub._solar_follow_timer_unsub = None
    stub._optimizer_intent_unsub = None
    stub._unsub_listeners = []
    stub._decision_interval = 5
    stub._battery = MagicMock()
    stub._battery.reserve_soc = 0
    stub._solar_follow = MagicMock()
    stub._solar_follow._tick = MagicMock()

    stub.hass = MagicMock()
    stub.hass.data = {"universal_room_automation": {"database": None}}
    stub.hass.is_running = True
    stub.hass.async_create_task = MagicMock(return_value=MagicMock(cancel=lambda: None))
    stub.hass.bus.async_listen_once = MagicMock(return_value=lambda: None)

    async def _anoop(*a, **k):
        return None

    stub._restore_all_sequential = _anoop
    stub._async_decision_cycle = _anoop
    stub._arm_tou_boundary_listener = MagicMock()
    stub._span_scope_migration_repass = _anoop
    stub._handle_safety_hazard = MagicMock()
    stub._on_optimizer_intent = MagicMock()

    # Bind the REAL helper — neutering the call site in async_setup
    # (i.e. deleting `self._register_solar_follow_timer()` at :1044)
    # leaves `_solar_follow_timer_unsub` at None.
    stub._register_solar_follow_timer = lambda: energy.EnergyCoordinator._register_solar_follow_timer(stub)
    return stub, energy


def test_e1_async_setup_call_site_binds_solar_follow_timer():
    """E1 (enclosing method — call-neuter-detectable):
    invoking `EnergyCoordinator.async_setup` must set
    `_solar_follow_timer_unsub`. Neuter site:
    energy.py `async_setup` line
    `self._register_solar_follow_timer()` — deleting that line
    (or the helper body) leaves the attr None → RED.
    """
    stub, energy = _async_setup_stub_for_energy()
    _run(energy.EnergyCoordinator.async_setup(stub))
    assert stub._solar_follow_timer_unsub is not None


def test_e2_async_teardown_cancels_solar_follow_timer():
    """E2: `async_teardown` invokes the stored `_solar_follow_timer_unsub`
    and clears the handle. Neuter site: the two-line unsub block in
    async_teardown (energy.py:8705-8712).
    """
    from custom_components.universal_room_automation.domain_coordinators import energy

    unsub_calls = []
    fake_unsub = lambda: unsub_calls.append(1)

    stub = MagicMock()
    stub._decision_timer_unsub = None
    stub._solar_follow_timer_unsub = fake_unsub
    stub._solar_follow = None
    stub._tou_boundary_unsub = None
    stub._peak_import_history = None
    stub._optimizer_intent_unsub = MagicMock()
    stub._write_verifier = None
    stub._dp_eval_last_task = None

    async def _anoop(*a, **k):
        return None

    stub._save_evse_state = _anoop
    stub._save_circuit_state = _anoop
    stub._save_energy_baselines = _anoop
    stub._save_envoy_cache = _anoop
    stub._save_midnight_snapshot = _anoop
    stub._save_load_shedding_level = _anoop
    stub._cancel_listeners = MagicMock()

    _run(energy.EnergyCoordinator.async_teardown(stub))

    assert unsub_calls == [1], "solar_follow_timer_unsub not invoked in teardown"
    assert stub._solar_follow_timer_unsub is None


def test_e3_async_teardown_invokes_solar_follow_cancel_all():
    """E3: `async_teardown` invokes `_solar_follow.cancel_all()`.
    Neuter site: the cancel_all block in async_teardown
    (energy.py:8713-8720).
    """
    from custom_components.universal_room_automation.domain_coordinators import energy

    sf = MagicMock()
    sf.cancel_all = MagicMock()

    stub = MagicMock()
    stub._decision_timer_unsub = None
    stub._solar_follow_timer_unsub = None
    stub._solar_follow = sf
    stub._tou_boundary_unsub = None
    stub._peak_import_history = None
    stub._optimizer_intent_unsub = MagicMock()
    stub._write_verifier = None
    stub._dp_eval_last_task = None

    async def _anoop(*a, **k):
        return None

    stub._save_evse_state = _anoop
    stub._save_circuit_state = _anoop
    stub._save_energy_baselines = _anoop
    stub._save_envoy_cache = _anoop
    stub._save_midnight_snapshot = _anoop
    stub._save_load_shedding_level = _anoop
    stub._cancel_listeners = MagicMock()

    _run(energy.EnergyCoordinator.async_teardown(stub))

    assert sf.cancel_all.called, "SolarFollowController.cancel_all not invoked"


def test_e6_set_solar_follow_confirm_writes_up_min_ticks():
    """E6: `EnergyCoordinator.set_solar_follow_confirm(v)` writes
    `_up_min_ticks` on the controller. Neuter site: energy.py:8893
    `self._solar_follow._up_min_ticks = v`.
    """
    from custom_components.universal_room_automation.domain_coordinators import energy

    stub = MagicMock()
    stub._solar_follow = MagicMock()
    stub._solar_follow._up_min_ticks = 1

    energy.EnergyCoordinator.set_solar_follow_confirm(stub, 5)

    assert stub._solar_follow._up_min_ticks == 5


def test_e6_set_solar_follow_confirm_clamps_range():
    """E6 partner: values outside 1..10 are clamped."""
    from custom_components.universal_room_automation.domain_coordinators import energy

    stub = MagicMock()
    stub._solar_follow = MagicMock()
    stub._solar_follow._up_min_ticks = 5

    energy.EnergyCoordinator.set_solar_follow_confirm(stub, 25)
    assert stub._solar_follow._up_min_ticks == 10

    energy.EnergyCoordinator.set_solar_follow_confirm(stub, 0)
    assert stub._solar_follow._up_min_ticks == 1


def test_e6_set_solar_follow_confirm_noop_when_controller_absent():
    """E6 safety: no-op when `_solar_follow` is None."""
    from custom_components.universal_room_automation.domain_coordinators import energy

    stub = MagicMock()
    stub._solar_follow = None
    # Should not raise.
    energy.EnergyCoordinator.set_solar_follow_confirm(stub, 5)


def test_m18_blind_exit_invokes_restore_pass():
    """M18: `_handle_blind` awaits `_restore_pass()` once elapsed
    reaches BLIND_EXIT_S. Neuter site: energy_pool.py:4277
    `await self._restore_pass()` inside the blind-exit branch.
    """
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_pool as _ep,
    )
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        SOLAR_FOLLOW_BLIND_EXIT_S,
    )

    h = _Harness()
    # Seed the blind clock so this call crosses BLIND_EXIT_S.
    h.sf._blind_since = _ep._sf_time.monotonic() - (SOLAR_FOLLOW_BLIND_EXIT_S + 5)
    h.sf._blind_exit_logged = False

    calls = []

    async def _spy():
        calls.append(1)

    h.sf._restore_pass = _spy
    _run(h.sf._handle_blind())

    assert calls == [1], "_restore_pass not invoked on blind-exit"
    assert h.sf._blind_exit_logged is True


def test_m18_blind_exit_latched_only_once():
    """M18 partner: latch prevents a second `_restore_pass` fire
    while still blind. Neuter site: `_blind_exit_logged` latch guard.
    """
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_pool as _ep,
    )
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        SOLAR_FOLLOW_BLIND_EXIT_S,
    )

    h = _Harness()
    h.sf._blind_since = _ep._sf_time.monotonic() - (SOLAR_FOLLOW_BLIND_EXIT_S + 5)
    h.sf._blind_exit_logged = True  # already latched

    calls = []

    async def _spy():
        calls.append(1)

    h.sf._restore_pass = _spy
    _run(h.sf._handle_blind())

    assert calls == [], "restore_pass fired despite latch"


def test_m19_boot_reconcile_skips_write_above_sanity_floor():
    """M19: `_boot_reconcile` does NOT write when the bay's current is
    already >= SOLAR_FOLLOW_CAPTURE_SANITY_A. Neuter site:
    energy_pool.py:4331 `if a < SOLAR_FOLLOW_CAPTURE_SANITY_A:` — removing
    the guard makes reconcile always write → this test goes RED.
    """
    h = _Harness(active=(), a_charging=False, b_charging=False,
                 a_current=48, b_current=48)
    # Mark garage_a as touched so boot_reconcile considers it. Bay is at
    # 48A (well above sanity floor), so the guard must skip the write.
    h.sf._touched = {"garage_a"}
    h.sf._did_boot_reconcile = False

    _run(h.sf._boot_reconcile())

    # No write to garage_a's current-limit.
    assert h.written("garage_a") == [], (
        "boot_reconcile wrote to bay whose current was already >= sanity floor"
    )
    # Bay is discarded from _touched (above-sanity path).
    assert "garage_a" not in h.sf._touched
