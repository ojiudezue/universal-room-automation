"""v4.7.13 — Sleep-State Zone Presence Trust Fallback.

Three-deliverable Tier 1 hotfix:

  D1 — Zone occupancy aggregator (`aggregation.py` ZoneAnyoneBinarySensor):
       sleep-state fallback to person tracker + zone_persons when room-level
       rollup is empty.

  D2 — Zone preset transition guard (`domain_coordinators/hvac.py`
       `_apply_house_state_presets`): suppress sleep -> away preset flip
       when any zone_persons member tracker is "home".

  D3 — FanController vacancy hold mirror (`domain_coordinators/hvac_fans.py`
       `_evaluate_temp_fan`): indefinite hold during sleep when person home,
       without clearing the vacancy timer.

Tests drive production code paths (D3 via real FanController; D1/D2 via
source-grep ASSERTs on the actual implementation — see Bug Class #44).
"""

from __future__ import annotations

import ast
import os
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest


# ----------------------------------------------------------------------------
# Source-grep harness for D1 (aggregation.py) and D2 (hvac.py)
# ----------------------------------------------------------------------------

ROOT = "custom_components/universal_room_automation"
AGGREGATION_PY = os.path.join(ROOT, "aggregation.py")
HVAC_PY = os.path.join(ROOT, "domain_coordinators", "hvac.py")
HVAC_FANS_PY = os.path.join(ROOT, "domain_coordinators", "hvac_fans.py")


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


@pytest.fixture(scope="module")
def agg_src() -> str:
    return _read(AGGREGATION_PY)


@pytest.fixture(scope="module")
def hvac_src() -> str:
    return _read(HVAC_PY)


@pytest.fixture(scope="module")
def hvac_fans_src() -> str:
    return _read(HVAC_FANS_PY)


# ============================================================================
# D1 — Zone aggregator sleep-state fallback
# ============================================================================

class TestD1ZoneAggregatorSleepFallback:
    """Source-level guarantees that the Layer 2 fallback is wired correctly."""

    def test_helper_method_exists(self, agg_src: str):
        """The _sleep_person_fallback_occupied helper must be defined."""
        assert "def _sleep_person_fallback_occupied" in agg_src, (
            "v4.7.13 D1 fallback helper not found in aggregation.py"
        )

    def test_helper_called_from_is_on(self, agg_src: str):
        """ZoneAnyoneBinarySensor.is_on must invoke the fallback after layer 1."""
        # Extract the ZoneAnyoneBinarySensor class block, then its is_on.
        tree = ast.parse(agg_src)
        target = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "ZoneAnyoneBinarySensor":
                target = node
                break
        assert target is not None, "ZoneAnyoneBinarySensor class missing"
        is_on_fn = None
        for item in target.body:
            if isinstance(item, ast.FunctionDef) and item.name == "is_on":
                is_on_fn = item
                break
        assert is_on_fn is not None, "is_on property missing"
        src = ast.unparse(is_on_fn)
        assert "_sleep_person_fallback_occupied" in src, (
            "is_on must call _sleep_person_fallback_occupied as Layer 2"
        )

    def test_fallback_gated_on_sleep(self, agg_src: str):
        """Fallback must only engage when house_state == 'sleep'."""
        # Locate the helper and inspect its body.
        tree = ast.parse(agg_src)
        helper = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_sleep_person_fallback_occupied"
            ):
                helper = node
                break
        assert helper is not None
        src = ast.unparse(helper)
        assert '"sleep"' in src or "'sleep'" in src, (
            "Helper must compare house_state against 'sleep'"
        )
        assert "zone_persons" in src, "Helper must read zone_persons"
        assert '"home"' in src or "'home'" in src, (
            "Helper must check person tracker state == 'home'"
        )

    def test_fallback_guarded_with_try_except(self, agg_src: str):
        """External state reads must be try/except guarded (project rule 4)."""
        tree = ast.parse(agg_src)
        helper = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_sleep_person_fallback_occupied"
            ):
                helper = node
                break
        assert helper is not None
        has_try = any(isinstance(n, ast.Try) for n in ast.walk(helper))
        assert has_try, "Helper must guard external reads with try/except"


# ============================================================================
# D1 — behavioral smoke via direct helper invocation
# ----------------------------------------------------------------------------
# We exercise _sleep_person_fallback_occupied directly on a minimal stub
# instance to confirm the three branches (no manager, not sleep, fallback hit)
# without spinning the full HA test harness.
# ============================================================================

def _make_fake_self(
    house_state: str | None,
    zone_persons: list[str] | None,
    person_states: dict[str, str] | None,
    have_hvac: bool = True,
    have_zone: bool = True,
    have_manager: bool = True,
) -> object:
    """Build a duck-typed `self` for invoking _sleep_person_fallback_occupied."""

    class _State:
        def __init__(self, s: str) -> None:
            self.state = s

    class _Hass:
        def __init__(self) -> None:
            mgr = None
            if have_manager:
                hvac = None
                if have_hvac:
                    zone_obj = None
                    if have_zone:
                        zone_obj = MagicMock()
                        zone_obj.zone_persons = list(zone_persons or [])
                    zm = MagicMock()
                    zm.zones = {"test_zone": zone_obj} if zone_obj is not None else {}
                    hvac = MagicMock()
                    hvac._zone_manager = zm
                mgr = MagicMock()
                mgr.house_state = house_state
                mgr.coordinators = {"hvac": hvac} if have_hvac else {}
            self.data = {"universal_room_automation": {"coordinator_manager": mgr}}
            self._person_states = person_states or {}

        @property
        def states(self_inner):  # noqa: N805
            outer = self_inner

            class _S:
                def get(_self, eid):
                    s = outer._person_states.get(eid)
                    return _State(s) if s is not None else None
            return _S()

    fake = MagicMock()
    fake.hass = _Hass()
    fake.zone = "test_zone"
    return fake


def _invoke_fallback(fake_self) -> bool:
    """Import the real helper and call it bound to a fake self."""
    # The helper is a method on ZoneAnyoneBinarySensor — pull the function
    # object out of the class via importlib AST not needed; load via exec
    # of the file's helper text is overkill. Instead, import the module
    # under a heavy mock harness — but that requires the full HA stack.
    # Simpler: re-execute the helper body in an isolated function whose
    # text is extracted from the source. Bug Class #44 demands we drive
    # the SAME code, so we exec the parsed function definition.
    src = _read(AGGREGATION_PY)
    tree = ast.parse(src)
    helper_node = None
    resolver_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if node.name == "_sleep_person_fallback_occupied":
                helper_node = node
            elif node.name == "_resolve_hvac_zone":
                # v4.7.31: the helper now resolves HVAC zones by name via this
                # module-level function — extract it too so the exec'd helper
                # can call it (Bug Class #44 fixture authority: drive real code).
                resolver_node = node
    assert helper_node is not None
    assert resolver_node is not None, "_resolve_hvac_zone not found in aggregation.py"

    # Build a minimal module: DOMAIN + _LOGGER + the resolver + the helper.
    module_src = (
        "import logging\n"
        f"DOMAIN = 'universal_room_automation'\n"
        "_LOGGER = logging.getLogger('test')\n"
        + ast.unparse(resolver_node)
        + "\n"
        + ast.unparse(helper_node)
        + "\n"
    )
    ns: dict = {}
    exec(compile(module_src, "<helper>", "exec"), ns)  # noqa: S102
    helper = ns["_sleep_person_fallback_occupied"]
    return helper(fake_self)


class TestD1FallbackBehavior:

    def test_zone_occupied_fallback_to_person_tracker_during_sleep(self):
        fake = _make_fake_self(
            house_state="sleep",
            zone_persons=["person.oji"],
            person_states={"person.oji": "home"},
        )
        assert _invoke_fallback(fake) is True

    def test_when_all_persons_not_home_during_sleep_no_fallback(self):
        fake = _make_fake_self(
            house_state="sleep",
            zone_persons=["person.oji"],
            person_states={"person.oji": "not_home"},
        )
        assert _invoke_fallback(fake) is False

    def test_when_house_state_not_sleep_no_fallback_applies(self):
        for hs in ("home_day", "home_night", "away", "guest", "vacation", None):
            fake = _make_fake_self(
                house_state=hs,
                zone_persons=["person.oji"],
                person_states={"person.oji": "home"},
            )
            assert _invoke_fallback(fake) is False, (
                f"Fallback should not engage for house_state={hs!r}"
            )

    def test_empty_zone_persons_means_no_fallback(self):
        fake = _make_fake_self(
            house_state="sleep",
            zone_persons=[],
            person_states={"person.oji": "home"},
        )
        assert _invoke_fallback(fake) is False

    def test_missing_manager_returns_false_safely(self):
        fake = _make_fake_self(
            house_state="sleep",
            zone_persons=["person.oji"],
            person_states={"person.oji": "home"},
            have_manager=False,
        )
        assert _invoke_fallback(fake) is False


# ============================================================================
# D2 — Zone preset transition guard (source-level ASSERT)
# ============================================================================

class TestD2PresetGuardSourceShape:

    def test_guard_present_in_apply_house_state_presets(self, hvac_src: str):
        # Confirm function exists.
        tree = ast.parse(hvac_src)
        target = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name == "_apply_house_state_presets"
            ):
                target = node
                break
        assert target is not None, "_apply_house_state_presets not found"
        # Locate the function in the raw source text (so comments are visible).
        # Slice from `async def _apply_house_state_presets` up to the next
        # top-level method declaration at the same indentation.
        start = hvac_src.find("async def _apply_house_state_presets")
        assert start >= 0
        # End at the next "    async def " or "    def " after start+1
        rest = hvac_src[start + 1:]
        next_method_offsets = [
            rest.find("\n    async def "),
            rest.find("\n    def "),
        ]
        next_method_offsets = [o for o in next_method_offsets if o >= 0]
        end = (start + 1 + min(next_method_offsets)) if next_method_offsets else len(hvac_src)
        block = hvac_src[start:end]
        assert "v4.7.13" in block, "D2 guard should be tagged with version marker"
        assert "zone_persons" in block, "D2 guard must reference zone.zone_persons"
        assert '"sleep"' in block, "D2 guard must check house_state == sleep"
        assert 'effective_preset == "away"' in block, (
            "D2 guard must trigger only on away preset"
        )

    def test_guard_logs_suppression(self, hvac_src: str):
        # _LOGGER.info on suppression so live validation can grep for it
        assert "Suppressing" in hvac_src and "during sleep" in hvac_src

    def test_guard_uses_continue_to_skip_write(self, hvac_src: str):
        """Guard must continue the loop so set_preset_mode is never dispatched."""
        # Coarse: the v4.7.13 block contains a `continue` after the home_persons branch.
        # Window widened 2000→4000 by the fan-trust cycle: the guard grew
        # (FAN_TRUST_STATES + bidirectionality comments) pushing the
        # `continue` past the old window.
        idx = hvac_src.find("v4.7.13")
        assert idx >= 0
        window = hvac_src[idx : idx + 4000]
        assert "continue" in window


# ============================================================================
# D2 — behavioral mirror of the guard logic
# ----------------------------------------------------------------------------
# We reproduce the conditional shape against a stub and verify the three cells:
# (away + sleep + person home -> SUPPRESS), (away + sleep + no person home ->
# PROCEED), (away + not sleep -> PROCEED).
# ============================================================================

def _eval_d2_guard(
    effective_preset: str,
    house_state: str,
    zone_persons: list[str],
    person_states: dict[str, str],
) -> bool:
    """Return True if the guard would suppress the preset write."""
    if effective_preset != "away" or house_state != "sleep":
        return False
    home_persons = []
    for p in (zone_persons or []):
        s = person_states.get(p)
        if s == "home":
            home_persons.append(p)
    return bool(home_persons)


class TestD2GuardBehavior:

    def test_zone_preset_does_not_flip_to_away_during_sleep_when_person_home(self):
        suppressed = _eval_d2_guard(
            effective_preset="away",
            house_state="sleep",
            zone_persons=["person.oji"],
            person_states={"person.oji": "home"},
        )
        assert suppressed is True

    def test_zone_preset_flips_normally_to_away_during_sleep_when_zone_persons_all_not_home(self):
        suppressed = _eval_d2_guard(
            effective_preset="away",
            house_state="sleep",
            zone_persons=["person.oji", "person.nkem"],
            person_states={"person.oji": "not_home", "person.nkem": "not_home"},
        )
        assert suppressed is False

    def test_guard_inert_when_target_preset_not_away(self):
        suppressed = _eval_d2_guard(
            effective_preset="home",
            house_state="sleep",
            zone_persons=["person.oji"],
            person_states={"person.oji": "home"},
        )
        assert suppressed is False

    def test_guard_inert_when_house_state_not_sleep(self):
        suppressed = _eval_d2_guard(
            effective_preset="away",
            house_state="home_day",
            zone_persons=["person.oji"],
            person_states={"person.oji": "home"},
        )
        assert suppressed is False


# ============================================================================
# D3 — FanController vacancy hold mirror (DRIVES PRODUCTION CODE)
# ----------------------------------------------------------------------------
# Reuses the mock harness from test_hvac_fan_control.py.
# ============================================================================

# Mirror the mock harness from test_hvac_fan_control.py so we can import
# FanController directly. Must run BEFORE the import.

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls, "callback": _identity,
        "CALLBACK_TYPE": _mock_cls, "Event": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.event": {
        "async_track_time_interval": MagicMock(),
        "async_call_later": MagicMock(),
        "async_track_state_change_event": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {}),
    },
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.utcnow(),
        "now": lambda: datetime.now(),
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(), "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {}),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "aiosqlite": MagicMock(),
}

for _name, _attrs in _mods.items():
    if isinstance(_attrs, dict):
        sys.modules.setdefault(_name, _mock_module(_name, **_attrs))
    else:
        sys.modules.setdefault(_name, _attrs)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules.setdefault("custom_components.universal_room_automation", _ura)

_ura_const = types.ModuleType("custom_components.universal_room_automation.const")
_ura_const.DOMAIN = "universal_room_automation"
_ura_const.VERSION = "4.7.13"
_ura_const.CONF_ENTRY_TYPE = "entry_type"
_ura_const.CONF_ROOM_NAME = "room_name"
_ura_const.CONF_FANS = "fans"
_ura_const.CONF_HUMIDITY_FANS = "humidity_fans"
_ura_const.CONF_HUMIDITY_FAN_THRESHOLD = "humidity_fan_threshold"
_ura_const.CONF_HUMIDITY_FAN_MAX_RUNTIME = "humidity_fan_max_runtime"
_ura_const.DEFAULT_HUMIDITY_THRESHOLD = 60
_ura_const.DEFAULT_HUMIDITY_FAN_MAX_RUNTIME = 3600
_ura_const.DEFAULT_HUMIDITY_FAN_HYSTERESIS = 10
_ura_const.ENTRY_TYPE_ROOM = "room"
sys.modules.setdefault("custom_components.universal_room_automation.const", _ura_const)
# Fan-trust cycle: hvac_fans.py now imports the per-room sleep policy consts
# (operator amendment 1 — coordinator path honors fan_sleep_policy). Apply
# ADDITIVELY to whichever const module won the setdefault race so the import
# succeeds in any collection order.
_active_const = sys.modules["custom_components.universal_room_automation.const"]
for _k, _v in (
    # Fan-trust cycle additions (mirror const.py values exactly):
    ("CONF_FAN_SLEEP_POLICY", "fan_sleep_policy"),
    ("DEFAULT_FAN_SLEEP_POLICY", "reduce"),
    ("FAN_SLEEP_OFF", "off"),
    ("FAN_SLEEP_REDUCE", "reduce"),
    ("FAN_SLEEP_NORMAL", "normal"),
    # Pre-existing hvac_fans imports the original stub never carried
    # (solo-collection robustness; mirror const.py:306/316/323):
    ("CONF_ROOM_TYPE", "room_type"),
    ("ROOM_TYPE_BEDROOM", "bedroom"),
    ("ROOM_TYPE_GENERIC", "generic"),
):
    if not hasattr(_active_const, _k):
        setattr(_active_const, _k, _v)

_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [os.path.join(_ura_path, "domain_coordinators")]
sys.modules.setdefault("custom_components.universal_room_automation.domain_coordinators", _dc)

_dc_signals = types.ModuleType(
    "custom_components.universal_room_automation.domain_coordinators.signals"
)
for sig in [
    "SIGNAL_ENERGY_CONSTRAINT", "SIGNAL_HOUSE_STATE_CHANGED",
    "SIGNAL_PERSON_ARRIVING", "SIGNAL_SAFETY_HAZARD",
]:
    setattr(_dc_signals, sig, f"ura_{sig.lower()}")
_dc_signals.EnergyConstraint = MagicMock()
sys.modules.setdefault(
    "custom_components.universal_room_automation.domain_coordinators.signals",
    _dc_signals,
)

for _mod_name in [
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "custom_components.universal_room_automation.domain_coordinators.hvac_preset",
    "custom_components.universal_room_automation.domain_coordinators.hvac_fan",
    "custom_components.universal_room_automation.domain_coordinators.hvac_cover",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zone_intel",
    "custom_components.universal_room_automation.domain_coordinators.hvac_predict",
    "custom_components.universal_room_automation.domain_coordinators.base",
]:
    sys.modules.setdefault(_mod_name, MagicMock())


from custom_components.universal_room_automation.domain_coordinators.hvac_fans import (  # noqa: E402
    FanController,
    RoomFanState,
    DEFAULT_FAN_VACANCY_HOLD,
)


def _make_fan_controller(house_state: str = "", zone_persons: list[str] | None = None,
                         person_states: dict[str, str] | None = None) -> FanController:
    """Build a FanController with a zone_manager that exposes zone_persons.

    The HA `hass.states.get(entity_id)` is mocked to return objects with
    `.state` matching person_states; missing entries return None.
    """
    class _PersonState:
        def __init__(self, s: str) -> None:
            self.state = s

    states_map = person_states or {}

    class _States:
        def get(self, entity_id):
            s = states_map.get(entity_id)
            return _PersonState(s) if s is not None else None

    hass = MagicMock()
    hass.states = _States()

    zone_manager = MagicMock()
    zone_obj = MagicMock()
    zone_obj.zone_persons = list(zone_persons or [])
    zone_manager.zones = {"zone_1": zone_obj}

    ctrl = FanController(hass, zone_manager)
    ctrl._house_state = house_state
    return ctrl


def _make_room_fan_on(now: datetime, vacancy_time: str = "") -> RoomFanState:
    return RoomFanState(
        room_name="Master Bedroom",
        zone_id="zone_1",
        fan_entities=["fan.master_bedroom"],
        humidity_fan_entities=[],
        is_on=True,
        trigger="temperature",
        speed_pct=33,
        vacancy_detected_time=vacancy_time,
        last_on_time=(now - timedelta(minutes=15)).isoformat(),
    )


class TestD3FanVacancyHoldDuringSleep:
    """Indefinite vacancy hold during sleep when zone_persons member is home."""

    def test_fan_vacancy_hold_does_not_expire_during_sleep_when_person_home(self):
        """Even after vacancy timer would normally expire, fan holds."""
        ctrl = _make_fan_controller(
            house_state="sleep",
            zone_persons=["person.oji"],
            person_states={"person.oji": "home"},
        )
        now = datetime.now()
        # Vacancy started well past the normal hold window
        vacancy_start = (now - timedelta(seconds=DEFAULT_FAN_VACANCY_HOLD + 600)).isoformat()
        room_fan = _make_room_fan_on(now, vacancy_time=vacancy_start)
        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            room_fan, room_temp=75.0, setpoint_high=72.0, occupied=False, now=now,
        )
        assert should_on is True
        assert trigger == "temperature"
        assert speed == 33
        # Vacancy timer must NOT be cleared so a subsequent person-not-home
        # state during sleep falls through to the normal expiry branch.
        assert room_fan.vacancy_detected_time == vacancy_start

    def test_fan_vacancy_normal_expiry_when_house_state_not_sleep(self):
        """Outside the trust states, normal vacancy expiry still wins.

        Re-contracted by the fan-trust cycle: home_night is now a TRUST
        state (person-home correctly holds the fan there), so the
        non-trust case uses home_day.
        """
        ctrl = _make_fan_controller(
            house_state="home_day",
            zone_persons=["person.oji"],
            person_states={"person.oji": "home"},
        )
        now = datetime.now()
        vacancy_start = (now - timedelta(seconds=DEFAULT_FAN_VACANCY_HOLD + 10)).isoformat()
        room_fan = _make_room_fan_on(now, vacancy_time=vacancy_start)
        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            room_fan, room_temp=75.0, setpoint_high=72.0, occupied=False, now=now,
        )
        assert should_on is False
        assert speed == 0

    def test_fan_vacancy_during_sleep_with_no_person_home_uses_normal_expiry(self):
        """Sleep but zone_persons all not_home — normal vacancy expiry applies."""
        ctrl = _make_fan_controller(
            house_state="sleep",
            zone_persons=["person.oji"],
            person_states={"person.oji": "not_home"},
        )
        now = datetime.now()
        vacancy_start = (now - timedelta(seconds=DEFAULT_FAN_VACANCY_HOLD + 10)).isoformat()
        room_fan = _make_room_fan_on(now, vacancy_time=vacancy_start)
        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            room_fan, room_temp=75.0, setpoint_high=72.0, occupied=False, now=now,
        )
        assert should_on is False

    def test_fan_vacancy_during_sleep_within_normal_hold_window(self):
        """Sleep + person home, vacancy still inside normal hold — still holds."""
        ctrl = _make_fan_controller(
            house_state="sleep",
            zone_persons=["person.oji"],
            person_states={"person.oji": "home"},
        )
        now = datetime.now()
        vacancy_start = (now - timedelta(seconds=60)).isoformat()
        room_fan = _make_room_fan_on(now, vacancy_time=vacancy_start)
        should_on, _trigger, speed = ctrl._evaluate_temp_fan(
            room_fan, room_temp=75.0, setpoint_high=72.0, occupied=False, now=now,
        )
        assert should_on is True
        assert speed == 33

    def test_fan_vacancy_during_sleep_empty_zone_persons_falls_through(self):
        """Sleep but zone has no zone_persons configured — normal expiry."""
        ctrl = _make_fan_controller(
            house_state="sleep",
            zone_persons=[],
            person_states={},
        )
        now = datetime.now()
        vacancy_start = (now - timedelta(seconds=DEFAULT_FAN_VACANCY_HOLD + 10)).isoformat()
        room_fan = _make_room_fan_on(now, vacancy_time=vacancy_start)
        should_on, _trigger, _speed = ctrl._evaluate_temp_fan(
            room_fan, room_temp=75.0, setpoint_high=72.0, occupied=False, now=now,
        )
        assert should_on is False


class TestD3SourceShape:
    """Source-level guarantees: guard placement is correct."""

    def test_guard_inside_evaluate_temp_fan(self, hvac_fans_src: str):
        tree = ast.parse(hvac_fans_src)
        target = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_evaluate_temp_fan":
                target = node
                break
        assert target is not None
        # Slice the raw source for _evaluate_temp_fan so we can search comments.
        start = hvac_fans_src.find("def _evaluate_temp_fan")
        assert start >= 0
        rest = hvac_fans_src[start + 1:]
        next_method = rest.find("\n    def ")
        end = (start + 1 + next_method) if next_method >= 0 else len(hvac_fans_src)
        block = hvac_fans_src[start:end]
        assert "v4.7.13" in block, "Guard tagged with version marker"
        assert "zone_persons" in block
        # Fan-trust cycle: the sleep-only literal became FAN_TRUST_STATES
        # ({home_night, sleep, waking}).
        assert "FAN_TRUST_STATES" in block

    def test_guard_does_not_clear_vacancy_detected_time(self, hvac_fans_src: str):
        """The sleep branch must NOT touch room_fan.vacancy_detected_time."""
        # Take raw source between the v4.7.13 marker and the next
        # `if vacancy_seconds >=` line; that span is the new guard block.
        idx = hvac_fans_src.find("# v4.7.13")
        assert idx >= 0, "v4.7.13 marker missing"
        tail = hvac_fans_src[idx:]
        end = tail.find("if vacancy_seconds >=")
        assert end >= 0, "Sentinel `if vacancy_seconds >=` not found after marker"
        block = tail[:end]
        assert "vacancy_detected_time =" not in block, (
            "Sleep-state guard must not clear vacancy timer"
        )


# ============================================================================
# v4.7.13 fix-up MEDIUM-2 — one-shot WARN per zone when sleep fallback unavailable
# ============================================================================

class TestMedium2OneShotSleepFallbackWarn:
    """Source + behavioral guarantees for the interim observability WARN."""

    def test_warn_helper_method_exists(self, agg_src: str):
        """The _warn_sleep_fallback_unavailable helper must be defined."""
        assert "def _warn_sleep_fallback_unavailable" in agg_src, (
            "MEDIUM-2 interim WARN helper not found in aggregation.py"
        )

    def test_module_level_warned_zones_set_exists(self, agg_src: str):
        """A module-level set must track already-warned zones."""
        assert "_SLEEP_FALLBACK_WARNED_ZONES" in agg_src, (
            "Module-level _SLEEP_FALLBACK_WARNED_ZONES set required for "
            "one-shot WARN semantics"
        )

    def test_warn_invoked_from_unavailable_branches(self, agg_src: str):
        """The fallback helper must call the warn helper from unavailable paths."""
        tree = ast.parse(agg_src)
        helper = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_sleep_person_fallback_occupied"
            ):
                helper = node
                break
        assert helper is not None
        src = ast.unparse(helper)
        # At minimum the helper must reference the warn helper. Specific
        # branch placement is verified by behavioral tests below.
        assert "_warn_sleep_fallback_unavailable" in src, (
            "Helper must invoke _warn_sleep_fallback_unavailable on "
            "unavailability paths"
        )

    @staticmethod
    def _build_warn_harness() -> tuple:
        """Exec both the helper and the warn function into one namespace.

        Returns (helper_fn, warn_fn, warned_set, log_calls_list).
        """
        src = _read(AGGREGATION_PY)
        tree = ast.parse(src)
        helper_node = None
        warn_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if node.name == "_sleep_person_fallback_occupied":
                    helper_node = node
                elif node.name == "_warn_sleep_fallback_unavailable":
                    warn_node = node
        assert helper_node is not None, "helper missing"
        assert warn_node is not None, "warn helper missing"

        log_calls: list[tuple] = []

        class _Logger:
            def warning(self, *args, **kwargs):
                log_calls.append(("warning", args, kwargs))

            def info(self, *args, **kwargs):
                log_calls.append(("info", args, kwargs))

            def debug(self, *args, **kwargs):
                log_calls.append(("debug", args, kwargs))

        ns: dict = {
            "DOMAIN": "universal_room_automation",
            "_LOGGER": _Logger(),
            "_SLEEP_FALLBACK_WARNED_ZONES": set(),
        }
        exec(  # noqa: S102
            compile(ast.unparse(helper_node), "<helper>", "exec"), ns
        )
        exec(  # noqa: S102
            compile(ast.unparse(warn_node), "<warn>", "exec"), ns
        )
        return (
            ns["_sleep_person_fallback_occupied"],
            ns["_warn_sleep_fallback_unavailable"],
            ns["_SLEEP_FALLBACK_WARNED_ZONES"],
            log_calls,
        )

    def test_warn_fires_once_then_suppresses_for_same_zone(self):
        """First unavailability for a zone WARNs; subsequent calls suppressed."""
        helper, warn, warned_set, log_calls = self._build_warn_harness()

        # Build a fake "self" whose hass-data path yields manager with hvac=None
        # so the unavailability branch fires.
        fake = _make_fake_self(
            house_state="sleep",
            zone_persons=["person.oji"],
            person_states={"person.oji": "home"},
            have_hvac=False,  # forces "hvac coordinator not ready" branch
        )
        # Bind the warn helper so helper(fake) can call self._warn_...
        fake._warn_sleep_fallback_unavailable = (
            lambda reason: warn(fake, reason)  # noqa: E731
        )
        # Inject the shared warned_set into the warn helper's globals already
        # done by the harness namespace.

        # First call: WARN should fire.
        result1 = helper(fake)
        assert result1 is False
        warnings_after_first = [c for c in log_calls if c[0] == "warning"]
        assert len(warnings_after_first) == 1, (
            f"Expected 1 WARN after first call, got {len(warnings_after_first)}: "
            f"{warnings_after_first}"
        )
        # Fan-trust cycle re-contract: dedup key widened zone → (zone, state)
        # so each trust state gets its own one-shot WARN per zone.
        assert ("test_zone", "sleep") in warned_set

        # Second call (same zone): WARN must be suppressed.
        result2 = helper(fake)
        assert result2 is False
        warnings_after_second = [c for c in log_calls if c[0] == "warning"]
        assert len(warnings_after_second) == 1, (
            f"Second call must NOT emit additional WARN; got "
            f"{len(warnings_after_second)} warnings total: "
            f"{warnings_after_second}"
        )

    def test_warn_fires_independently_for_different_zones(self):
        """Different zones each get their own one-shot WARN."""
        helper, warn, warned_set, log_calls = self._build_warn_harness()

        for zone_name in ("zone_alpha", "zone_beta"):
            fake = _make_fake_self(
                house_state="sleep",
                zone_persons=["person.oji"],
                person_states={"person.oji": "home"},
                have_hvac=False,
            )
            fake.zone = zone_name
            fake._warn_sleep_fallback_unavailable = (
                lambda reason, _f=fake: warn(_f, reason)  # noqa: E731
            )
            helper(fake)

        warnings_total = [c for c in log_calls if c[0] == "warning"]
        assert len(warnings_total) == 2, (
            f"Expected one WARN per distinct zone (2 total); got "
            f"{len(warnings_total)}: {warnings_total}"
        )
        # Fan-trust cycle re-contract: (zone, state) tuple keys.
        assert warned_set == {("zone_alpha", "sleep"), ("zone_beta", "sleep")}

    def test_warn_does_not_fire_when_not_in_sleep_state(self):
        """If house_state != sleep, the helper returns early without WARNing."""
        helper, warn, warned_set, log_calls = self._build_warn_harness()

        fake = _make_fake_self(
            house_state="home_day",  # NOT sleep
            zone_persons=["person.oji"],
            person_states={"person.oji": "home"},
            have_hvac=False,
        )
        fake._warn_sleep_fallback_unavailable = (
            lambda reason: warn(fake, reason)  # noqa: E731
        )
        helper(fake)

        warnings = [c for c in log_calls if c[0] == "warning"]
        assert len(warnings) == 0, (
            f"WARN must only fire during sleep; got: {warnings}"
        )
        assert warned_set == set()
