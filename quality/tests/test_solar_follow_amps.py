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
    """T-DEADBAND-1: a target within deadband of current produces no write.

    Anchors the deadband suppression. Mutation drill C30.
    """
    # Surplus that would compute to exactly 48 A → equals current, no write.
    h = _Harness(active=("garage_a",), grid_w=-11520.0,
                 a_charging=True, a_current=48, a_power=11520,
                 b_charging=False, b_current=48, b_power=0)
    h.sf._original_amps["garage_a"] = 48.0
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
    # Nothing commanded → false.
    assert h.sf.get_status()["solar_follow_below_dp_l1_threshold"] is False
    # Command 6 A: 6 * 240 = 1440 W ≤ 3000 W → true.
    h.sf._last_commanded["garage_a"] = 6.0
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
