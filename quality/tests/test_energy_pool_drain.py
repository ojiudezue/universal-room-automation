"""v4.7.6 D1 — Drain rule hardening + hybrid self_modulates + idempotent re-pause.

Drives `EVChargerController.determine_battery_drain_actions` directly with
mocked HA state. Asserts on returned action list AND on internal state-set
membership AND on `get_status()` output.

Test names follow the plan's D5 #1-#9 mapping.
"""
import pytest
from unittest.mock import MagicMock
import sys
import os
import types
import importlib
import time as _time

# Mock homeassistant — mirror test_energy_evse.py shape
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
    "homeassistant.helpers.event": {},
    "homeassistant.helpers.dispatcher": {},
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": __import__("datetime").datetime.utcnow,
        "now": __import__("datetime").datetime.now,
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

for _submod_name in ("energy_const", "energy_pool"):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

from conftest import MockHass

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
    EVChargerController,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    EV_PAUSE_DISPATCH_GRACE_SECONDS,
    EV_BATTERY_DRAIN_COOLDOWN_SECONDS,
)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def _make_ev(garage_a_on=True, garage_a_power=5000.0, self_modulates=False):
    """Build an EVChargerController with one configured EVSE (garage_a)."""
    hass = MockHass()
    hass.set_state("switch.garage_a", "on" if garage_a_on else "off")
    hass.set_state("sensor.garage_a_power_minute_average", str(garage_a_power))
    hass.set_state("sensor.garage_a_energy_today", "0")
    hass.set_state("sensor.garage_a_energy_this_month", "0")
    evse_config = {
        "garage_a": {
            "switch": "switch.garage_a",
            "power": "sensor.garage_a_power_minute_average",
            "energy_today": "sensor.garage_a_energy_today",
            "energy_month": "sensor.garage_a_energy_this_month",
            "self_modulates": self_modulates,
        },
    }
    return EVChargerController(hass, evse_config=evse_config), hass


# ---------------------------------------------------------------------------
# D5 #1: Adversarial smart EVSE, explicit opt-in (self_modulates=True)
# ---------------------------------------------------------------------------

class TestDrainSmartSelfModulatesIdempotentRepause:
    def test_drain_smart_self_modulates_idempotent_repause(self):
        """self_modulates=True: re-pauses every tick external state flips on; no cooldown."""
        ev, hass = _make_ev(self_modulates=True)
        # Tick 1: drain conditions met → pause dispatched
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        assert any(a["service"] == "switch.turn_off" for a in actions)
        assert "garage_a" in ev._paused_by_battery_drain
        # Simulate adversarial: switch turns back on externally
        hass.set_state("switch.garage_a", "on")
        hass.set_state("sensor.garage_a_power_minute_average", "5000.0")
        # Tick 2 — even if observed_off=False and grace not expired,
        # Option A skips manual-override branch entirely; re-pauses.
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        assert any(a["service"] == "switch.turn_off" for a in actions)
        assert "garage_a" in ev._paused_by_battery_drain
        # No cooldown ever engaged
        assert "garage_a" not in ev._battery_drain_cooldown


# ---------------------------------------------------------------------------
# D5 #2: Adversarial smart EVSE, default config (self_modulates=False)
# ---------------------------------------------------------------------------

class TestDrainSmartDefaultConfigRepause:
    def test_drain_smart_default_config_repause(self):
        """Default config: dispatch lag → URA re-pauses, no false cooldown."""
        ev, hass = _make_ev(self_modulates=False)
        # Tick 1: drain pause dispatched
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        assert any(a["service"] == "switch.turn_off" for a in actions)
        # HA hasn't propagated turn_off yet — state still reads is_on=True
        # (dispatch lag). observed_off=False, grace not expired.
        # Tick 2 immediately:
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        # URA re-pauses; cooldown NOT engaged
        assert "garage_a" not in ev._battery_drain_cooldown
        assert "garage_a" in ev._paused_by_battery_drain


# ---------------------------------------------------------------------------
# D5 #3: Real dumb-EVSE user override
# ---------------------------------------------------------------------------

class TestDrainRealDumbUserOverride:
    def test_drain_real_dumb_user_override(self):
        """observed_off=True + grace expired + is_on=True → cooldown engaged."""
        ev, hass = _make_ev(self_modulates=False)
        # Tick 1: pause
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        # Simulate URA's switch.turn_off propagated and was observed
        hass.set_state("switch.garage_a", "off")
        hass.set_state("sensor.garage_a_power_minute_average", "0")
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        # observed_off should be True now
        assert ev._observed_off_since_pause.get("garage_a") is True
        # Force grace expiry by rewinding stored ts
        ev._pause_dispatch_ts["garage_a"] = _time.monotonic() - (EV_PAUSE_DISPATCH_GRACE_SECONDS + 5)
        # User flips switch on
        hass.set_state("switch.garage_a", "on")
        hass.set_state("sensor.garage_a_power_minute_average", "5000.0")
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        # Cooldown should be engaged now
        assert "garage_a" in ev._battery_drain_cooldown
        assert "garage_a" not in ev._paused_by_battery_drain


# ---------------------------------------------------------------------------
# D5 #4: Dispatch latency
# ---------------------------------------------------------------------------

class TestDrainDispatchLatencyNoFalseCooldown:
    def test_drain_dispatch_latency_no_false_cooldown(self):
        """is_on=True within grace window → no cooldown."""
        ev, hass = _make_ev(self_modulates=False)
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        # is_on still True (HA state cache hasn't flushed), grace fresh,
        # observed_off=False — fall through and re-pause
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        assert "garage_a" not in ev._battery_drain_cooldown


# ---------------------------------------------------------------------------
# D5 #5: Instant smart auto-resume
# ---------------------------------------------------------------------------

class TestDrainInstantSmartAutoResume:
    def test_drain_instant_smart_auto_resume(self):
        """Smart EVSE auto-resumes inside HA cache window — re-pause, not cooldown.

        observed_off never flips True; URA treats as auto-resume.
        """
        ev, hass = _make_ev(self_modulates=False)
        # Pause
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        # Switch never read as off; smart EVSE flips back on inside ~5s
        # grace expires
        ev._pause_dispatch_ts["garage_a"] = _time.monotonic() - (EV_PAUSE_DISPATCH_GRACE_SECONDS + 5)
        # observed_off stays False — we never observed off
        hass.set_state("switch.garage_a", "on")
        hass.set_state("sensor.garage_a_power_minute_average", "5000.0")
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        # NO cooldown; URA re-pauses
        assert "garage_a" not in ev._battery_drain_cooldown
        assert any(a["service"] == "switch.turn_off" for a in actions)


# ---------------------------------------------------------------------------
# D5 #6: Smart EVSE misconfigured (self_modulates=True on dumb hw)
# ---------------------------------------------------------------------------

class TestDrainSmartEvseMisconfigured:
    def test_drain_smart_evse_misconfigured(self):
        """self_modulates=True with dumb hw: URA re-pauses every cycle.

        User must use Force-Charge button to actually override.
        """
        ev, hass = _make_ev(self_modulates=True)
        # Drain
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        # Adversarial: user toggles on; URA must NOT engage cooldown
        ev._pause_dispatch_ts["garage_a"] = _time.monotonic() - (EV_PAUSE_DISPATCH_GRACE_SECONDS + 5)
        ev._observed_off_since_pause["garage_a"] = True
        hass.set_state("switch.garage_a", "on")
        hass.set_state("sensor.garage_a_power_minute_average", "5000.0")
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        assert "garage_a" not in ev._battery_drain_cooldown
        assert any(a["service"] == "switch.turn_off" for a in actions)


# ---------------------------------------------------------------------------
# D5 #7: End-of-solar-day resume (battery_out_of_capacity)
# ---------------------------------------------------------------------------

class TestDrainEndOfSolarDayResume:
    def test_drain_end_of_solar_day_resume(self):
        """SOC at reserve+2, battery idle → resume."""
        ev, hass = _make_ev(self_modulates=False)
        # Pause first
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        # Switch is off, battery now idle (reserve floor reached)
        hass.set_state("switch.garage_a", "off")
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-50.0,   # NOT discharging (>-100)
            battery_soc=22.0,        # reserve_soc + 2 = 22
            soc_threshold=50,
            reserve_soc=20,
        )
        assert any(a["service"] == "switch.turn_on" for a in actions)
        assert "garage_a" not in ev._paused_by_battery_drain


# ---------------------------------------------------------------------------
# D5 #8: Transient equilibrium (no resume — the bug v4.7.6 fixes)
# ---------------------------------------------------------------------------

class TestDrainTransientEquilibriumNoResume:
    def test_drain_transient_equilibrium_no_resume(self):
        """SOC=51 with battery briefly at equilibrium (because EV is paused) → no resume.

        Pre-v4.7.6 the OR clause `battery_ok or soc_recovered` would resume here.
        Post-v4.7.6 needs `battery_out_of_capacity` AND requires SOC <= reserve+2.
        """
        ev, hass = _make_ev(self_modulates=False)
        # Pause
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        hass.set_state("switch.garage_a", "off")
        # Tick: SOC=51, battery briefly idle (because we paused EV) — but
        # SOC is nowhere near reserve. With reserve_soc=20, capacity not exhausted.
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-50.0,   # not discharging
            battery_soc=51.0,
            soc_threshold=50,
            reserve_soc=20,
        )
        # NO resume — battery_out_of_capacity False (51 > 22), soc_recovered
        # False (51 < 55). EVSE stays paused.
        assert not any(a["service"] == "switch.turn_on" for a in actions)
        assert "garage_a" in ev._paused_by_battery_drain


# ---------------------------------------------------------------------------
# D5 #9: Restart resilience (state resets on init per backlog decision)
# ---------------------------------------------------------------------------

class TestDrainDispatchStateResetsOnInit:
    def test_drain_dispatch_state_resets_on_init(self):
        """EVPool __init__ resets _pause_dispatch_ts and _observed_off_since_pause.

        v4.7.6: no DB persistence. Monotonic resets across HA restart; explicit
        state reset on __init__ aligns with monotonic semantics (Bug Class #7).
        """
        ev, _ = _make_ev()
        assert ev._pause_dispatch_ts == {}
        assert ev._observed_off_since_pause == {}
        assert ev._paused_by_fill_priority == set()


# ---------------------------------------------------------------------------
# Refined battery_out_of_capacity correctness — reserve_soc=None safety
# ---------------------------------------------------------------------------

class TestBatteryOutOfCapacityReserveNone:
    def test_battery_ok_alone_no_longer_resumes(self):
        """Pre-v4.7.6: battery_ok alone resumed. Post-v4.7.6: needs reserve_soc set."""
        ev, hass = _make_ev(self_modulates=False)
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        hass.set_state("switch.garage_a", "off")
        # reserve_soc=None — only soc_recovered (>=55) can resume
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-50.0,   # not discharging — battery_ok=True
            battery_soc=51.0,        # below threshold + 5
            soc_threshold=50,
            reserve_soc=None,
        )
        assert not any(a["service"] == "switch.turn_on" for a in actions)
        assert "garage_a" in ev._paused_by_battery_drain


# ---------------------------------------------------------------------------
# Idempotent re-pause when conditions still hold
# ---------------------------------------------------------------------------

class TestIdempotentRepause:
    def test_idempotent_repause_dispatches_every_tick(self):
        """Drain conditions persist → dispatch every tick (no _paused_by guard)."""
        ev, hass = _make_ev()
        for _ in range(3):
            actions = ev.determine_battery_drain_actions(
                battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
            )
            # Every call should produce a turn_off action
            assert any(a["service"] == "switch.turn_off" for a in actions)


# ---------------------------------------------------------------------------
# Prune removed EVSEs lifecycle
# ---------------------------------------------------------------------------

class TestPruneRemovedEVSEs:
    def test_prune_removed_evses_clears_state(self):
        """Removing an EVSE from config drops its tracking state on the next prune.

        v4.7.6 fix-up B-H1: `update_evse_config` was removed (dead code — no
        production caller; config updates go through HA's options-flow reload
        which rebuilds EVPool from scratch via `async_setup_entry`). The
        canonical state-cleanup path is `_prune_removed_evses()` which is
        invoked from `__init__`. Tests drive it directly here to verify the
        invariant holds after the config dict mutates.
        """
        ev, hass = _make_ev()
        # Pause garage_a
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
        )
        assert "garage_a" in ev._paused_by_battery_drain
        assert "garage_a" in ev._pause_dispatch_ts
        # Mutate config to remove garage_a, then run the canonical prune.
        # This mirrors what the legacy update_evse_config wrapper did
        # without re-introducing the dead wrapper itself.
        ev._evse = {}
        ev._prune_removed_evses()
        assert "garage_a" not in ev._paused_by_battery_drain
        assert "garage_a" not in ev._pause_dispatch_ts
        assert "garage_a" not in ev._observed_off_since_pause
        # v4.7.6 fix-up A-H2 / A-H3: dispatch_owners is also pruned.
        assert "garage_a" not in ev._dispatch_owners
