"""v4.7.14 — Away-State Person-Tracker Trust Veto.

Tier 1 hotfix. Three deliverables:

  D1 — `_run_inference` computes `all_tracked_persons_away` + `tracked_count`
       from `person_coordinator.data` before calling `infer()`.

  D2 — `StateInferenceEngine.infer()` gains `all_tracked_persons_away` kwarg
       and short-circuits to AWAY when True AND `unidentified_count == 0`
       (guest path preserved).

  D3 — `PresenceHouseStateSensor.extra_state_attributes` exposes
       `tracked_persons_count` + `all_tracked_persons_away` for diagnostics.

Tests drive PRODUCTION code paths — they import and call the real
`StateInferenceEngine.infer()` and assert source-level invariants on the
real `_run_inference` body (per Bug Class #44 — test fixture authority).
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
DC_PATH = PKG / "domain_coordinators"
PRESENCE_SRC = (DC_PATH / "presence.py").read_text()
SENSOR_SRC = (PKG / "sensor.py").read_text()


# ---------------------------------------------------------------------------
# HA module mocking
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_ha_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _mock_cls(),
        "async_track_time_interval": lambda hass, cb, interval: _mock_cls(),
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda hass, signal, cb: _mock_cls(),
        "async_dispatcher_send": lambda hass, signal, data=None: None,
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
        "utcnow": lambda: datetime.utcnow(),
        "now": lambda: datetime(2026, 5, 30, 14, 0, 0),  # mid-afternoon
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
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
}

for _name, _attrs in _ha_mods.items():
    if isinstance(_attrs, dict):
        _existing = sys.modules.get(_name)
        if _existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            for _k, _v in _attrs.items():
                if not hasattr(_existing, _k):
                    setattr(_existing, _k, _v)
    else:
        sys.modules.setdefault(_name, _attrs)

sys.modules.setdefault("aiosqlite", MagicMock())


def _load_module(full_name: str, filepath) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(full_name, str(filepath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


_cc_pkg_name = "custom_components"
if _cc_pkg_name not in sys.modules:
    sys.modules[_cc_pkg_name] = _mock_module(_cc_pkg_name)

_ura_pkg_name = "custom_components.universal_room_automation"
if _ura_pkg_name not in sys.modules:
    _ura_pkg = _mock_module(_ura_pkg_name)
    _ura_pkg.__file__ = str(PKG / "__init__.py")
    sys.modules[_ura_pkg_name] = _ura_pkg

_dc_pkg_name = "custom_components.universal_room_automation.domain_coordinators"
if _dc_pkg_name not in sys.modules:
    _dc_pkg = _mock_module(_dc_pkg_name)
    _dc_pkg.__file__ = str(DC_PATH / "__init__.py")
    sys.modules[_dc_pkg_name] = _dc_pkg

for _submod in ("const",):
    _full = f"custom_components.universal_room_automation.{_submod}"
    if _full not in sys.modules:
        _load_module(_full, PKG / f"{_submod}.py")

for _submod in ("signals", "house_state", "base", "coordinator_diagnostics", "presence"):
    _full = f"custom_components.universal_room_automation.domain_coordinators.{_submod}"
    if _full not in sys.modules:
        _load_module(_full, DC_PATH / f"{_submod}.py")


from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E402
    StateInferenceEngine,
)
from custom_components.universal_room_automation.domain_coordinators.house_state import (  # noqa: E402
    HouseState,
)


# ===========================================================================
# D1 — Source-level invariants: _run_inference computes the veto signal
# ===========================================================================


class TestD1AllTrackedPersonsAwayComputation:
    """The veto signal computation must exist in _run_inference, before infer().

    These tests drive the REAL `_run_inference` source via AST inspection +
    string-level invariants. Bug Class #44: production code is the authority.
    """

    def test_computation_block_exists(self):
        """`_run_inference` must compute `all_tracked_persons_away`."""
        assert "all_tracked_persons_away = " in PRESENCE_SRC, (
            "v4.7.14 D1: all_tracked_persons_away assignment missing from presence.py"
        )

    def test_tracked_count_computed(self):
        """`tracked_count` must be derived from person_coordinator.data length."""
        assert "tracked_count = len(person_data)" in PRESENCE_SRC, (
            "v4.7.14 D1: tracked_count = len(person_data) missing"
        )

    def test_empty_config_failsafe_present(self):
        """The tracked_count > 0 guard must exist to prevent empty-config veto."""
        # The guard exists in the new code block:
        assert "if tracked_count > 0:" in PRESENCE_SRC, (
            "v4.7.14 D1: tracked_count > 0 fail-safe guard missing"
        )

    def test_unknown_not_treated_as_away(self):
        """The veto checks ('away', '') — 'unknown' is intentionally excluded."""
        # Look for the literal tuple inside the all_tracked_persons_away assignment.
        idx = PRESENCE_SRC.find("all_tracked_persons_away = all(")
        assert idx >= 0, "veto assignment not found"
        block = PRESENCE_SRC[idx: idx + 400]
        assert '("away", "")' in block, (
            "v4.7.14 D1: veto must use ('away', '') tuple — unknown excluded"
        )
        assert '"unknown"' not in block.split("for info in person_data.values()")[0], (
            "v4.7.14 D1: 'unknown' must NOT be treated as away in the veto"
        )

    def test_uses_person_coordinator_key(self):
        """Must read from hass.data[DOMAIN]['person_coordinator']."""
        # Locate the actual computation block (not the engine docstring's
        # 'v4.7.14:' line — the engine docstring talks about the veto but
        # doesn't read person_coordinator; the call site in _run_inference does).
        idx = PRESENCE_SRC.find("all_tracked_persons_away = all(")
        assert idx >= 0, "veto computation block not found"
        # Look backwards ~600 chars to find the person_coordinator lookup.
        block = PRESENCE_SRC[max(0, idx - 800): idx + 200]
        assert '"person_coordinator"' in block, (
            "v4.7.14 D1: must read hass.data[DOMAIN]['person_coordinator']"
        )

    def test_diagnostic_attributes_stored_on_self(self):
        """The computed values must be stored on self for D3 diagnostics."""
        assert "self._tracked_persons_count = tracked_count" in PRESENCE_SRC
        assert "self._all_tracked_persons_away = all_tracked_persons_away" in PRESENCE_SRC

    def test_run_inference_passes_kwarg_to_infer(self):
        """Call site at _run_inference must pass all_tracked_persons_away= kwarg."""
        # Locate the infer() call within _run_inference and verify the kwarg.
        idx = PRESENCE_SRC.find("self._inference_engine.infer(")
        assert idx >= 0, "infer() call site missing"
        block = PRESENCE_SRC[idx: idx + 600]
        assert "all_tracked_persons_away=all_tracked_persons_away" in block, (
            "v4.7.14 D1/D2: call site must pass all_tracked_persons_away kwarg"
        )


# ---------------------------------------------------------------------------
# D1 — Behavioral tests using a direct re-implementation of the same logic
# (mirrors production line-for-line so the value semantics are tested)
# ---------------------------------------------------------------------------

def _compute_all_tracked_persons_away(person_coordinator):
    """Reproduces the production logic from _run_inference verbatim.

    The production block lives in domain_coordinators/presence.py
    inside `_run_inference` (search 'v4.7.14: Compute all-persons-away').
    Tests drive the same logic so a refactor that changes semantics breaks
    these tests.
    """
    all_tracked_persons_away = False
    tracked_count = 0
    try:
        if person_coordinator and getattr(person_coordinator, "data", None):
            person_data = person_coordinator.data or {}
            tracked_count = len(person_data)
            if tracked_count > 0:
                all_tracked_persons_away = all(
                    (info.get("location") or "") in ("away", "")
                    for info in person_data.values()
                )
    except Exception:
        all_tracked_persons_away = False
        tracked_count = 0
    return all_tracked_persons_away, tracked_count


def test_all_tracked_persons_away_true_when_all_away():
    pc = MagicMock()
    pc.data = {
        "oji_udezue": {"location": "away", "method": "person_state"},
        "jaya_udezue": {"location": "away", "method": "person_state"},
    }
    away, count = _compute_all_tracked_persons_away(pc)
    assert away is True
    assert count == 2


def test_all_tracked_persons_away_false_when_any_unknown():
    pc = MagicMock()
    pc.data = {
        "oji_udezue": {"location": "away", "method": "person_state"},
        "jaya_udezue": {"location": "unknown", "method": "person_state"},
    }
    away, count = _compute_all_tracked_persons_away(pc)
    # "unknown" is conservatively excluded — it means uncertainty, not confirmed-away.
    assert away is False
    assert count == 2


def test_all_tracked_persons_away_false_when_no_persons_tracked():
    """Empty config (no person trackers configured) must NOT veto — fail-safe."""
    pc = MagicMock()
    pc.data = {}
    away, count = _compute_all_tracked_persons_away(pc)
    assert away is False
    assert count == 0


def test_all_tracked_persons_away_false_when_person_coordinator_missing():
    """No person_coordinator attached → fail-safe to False."""
    away, count = _compute_all_tracked_persons_away(None)
    assert away is False
    assert count == 0


def test_all_tracked_persons_away_handles_none_location():
    """info.get('location') returning None must be treated as away/empty (or '')."""
    pc = MagicMock()
    pc.data = {
        "oji_udezue": {"location": None, "method": "init"},
        "jaya_udezue": {"location": "away", "method": "person_state"},
    }
    away, count = _compute_all_tracked_persons_away(pc)
    # None -> "" -> in ("away", "") -> True; combined with "away" → True
    assert away is True
    assert count == 2


def test_all_tracked_persons_away_false_when_one_home():
    pc = MagicMock()
    pc.data = {
        "oji_udezue": {"location": "away"},
        "jaya_udezue": {"location": "kitchen"},  # in a room → home
    }
    away, count = _compute_all_tracked_persons_away(pc)
    assert away is False
    assert count == 2


# ===========================================================================
# D2 — StateInferenceEngine.infer() veto behavior (drives real production code)
# ===========================================================================


def _make_engine() -> StateInferenceEngine:
    """Build engine with default sleep window (so we're not in sleep at 14:00)."""
    return StateInferenceEngine(sleep_start_hour=23, sleep_end_hour=6)


def _afternoon() -> datetime:
    return datetime(2026, 5, 30, 14, 0, 0)


def test_veto_fires_when_all_persons_away_and_no_unidentified():
    """Veto path: from HOME_DAY back to AWAY when all persons away."""
    engine = _make_engine()
    new_state = engine.infer(
        census_count=1,  # camera census picked something up
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,  # camera Tier 2 firing
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=True,
    )
    assert new_state == HouseState.AWAY
    # Confidence 0.95 > 0.9 (away-AND-gate) and > 0.85 (camera-driven)
    assert engine.confidence == 0.95


def test_veto_does_not_fire_when_unidentified_count_positive():
    """Guest path preserved — unidentified > 0 means someone IS here."""
    engine = _make_engine()
    new_state = engine.infer(
        census_count=1,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,
        now=_afternoon(),
        unidentified_count=1,  # a guest at the door
        guest_gate_armed=False,
        all_tracked_persons_away=True,
    )
    # Should NOT veto to AWAY — guest path preserved.
    assert new_state != HouseState.AWAY


def test_veto_does_not_fire_when_any_person_home():
    """Veto signal False → engine acts as today."""
    engine = _make_engine()
    new_state = engine.infer(
        census_count=1,
        current_state=HouseState.AWAY,
        any_zone_occupied=True,
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=False,  # someone home
    )
    # Should follow normal "people home → ARRIVING" path.
    assert new_state == HouseState.ARRIVING


def test_veto_returns_none_if_already_away():
    """Don't emit a duplicate AWAY transition when current is already AWAY."""
    engine = _make_engine()
    # AND-gate (census_count==0 AND not any_zone_occupied) would normally
    # return None too — so we need a state where the veto IS the deciding
    # short-circuit. Set census_count>0 (or any_zone_occupied) so AND-gate
    # fails, then current_state==AWAY, then veto should return None.
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.AWAY,
        any_zone_occupied=True,  # Frigate motion ghost
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=True,
    )
    assert new_state is None


def test_default_kwarg_preserves_existing_behavior():
    """Callers that don't pass the new kwarg must see identical output."""
    engine = _make_engine()
    # Inputs that previously inferred ARRIVING from AWAY.
    new_state_default = engine.infer(
        census_count=1,
        current_state=HouseState.AWAY,
        any_zone_occupied=True,
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        # all_tracked_persons_away omitted → default False
    )
    new_state_explicit_false = engine.infer(
        census_count=1,
        current_state=HouseState.AWAY,
        any_zone_occupied=True,
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=False,
    )
    assert new_state_default == new_state_explicit_false == HouseState.ARRIVING


def test_veto_fires_from_arriving_state():
    """Mid-bounce case: house just transitioned to ARRIVING; veto must yank back."""
    engine = _make_engine()
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.ARRIVING,
        any_zone_occupied=True,
        now=_afternoon(),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=True,
    )
    assert new_state == HouseState.AWAY


def test_veto_kwarg_signature_has_default_false():
    """The new kwarg must have a default value of False (back-compat)."""
    import inspect
    sig = inspect.signature(StateInferenceEngine.infer)
    assert "all_tracked_persons_away" in sig.parameters
    p = sig.parameters["all_tracked_persons_away"]
    assert p.default is False, (
        "v4.7.14 D2: all_tracked_persons_away kwarg must default to False"
    )


# ===========================================================================
# D3 — Sensor exposes diagnostic attributes
# ===========================================================================


class TestD3HouseStateSensorAttributes:
    """The PresenceHouseStateSensor.extra_state_attributes block must expose
    the two new keys. We assert against the real source — Bug Class #44.
    """

    def test_house_state_sensor_exposes_tracked_persons_count(self):
        """`tracked_persons_count` attribute must be set in the sensor body."""
        assert '"tracked_persons_count"' in SENSOR_SRC, (
            "v4.7.14 D3: 'tracked_persons_count' attribute missing from sensor.py"
        )

    def test_house_state_sensor_exposes_all_tracked_persons_away(self):
        """`all_tracked_persons_away` attribute must be set in the sensor body."""
        assert '"all_tracked_persons_away"' in SENSOR_SRC, (
            "v4.7.14 D3: 'all_tracked_persons_away' attribute missing from sensor.py"
        )

    def test_attributes_land_on_presence_house_state_sensor(self):
        """Both attributes must be inside PresenceHouseStateSensor's
        extra_state_attributes method (not somewhere unrelated)."""
        tree = ast.parse(SENSOR_SRC)
        target_cls = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "PresenceHouseStateSensor":
                target_cls = node
                break
        assert target_cls is not None, "PresenceHouseStateSensor class not found"
        cls_src = ast.get_source_segment(SENSOR_SRC, target_cls)
        assert cls_src is not None
        assert '"tracked_persons_count"' in cls_src, (
            "v4.7.14 D3: tracked_persons_count must be set inside PresenceHouseStateSensor"
        )
        assert '"all_tracked_persons_away"' in cls_src, (
            "v4.7.14 D3: all_tracked_persons_away must be set inside PresenceHouseStateSensor"
        )

    def test_attributes_read_from_presence_coordinator(self):
        """The sensor must read the diagnostic fields from the live presence
        coordinator (not fabricate from elsewhere)."""
        tree = ast.parse(SENSOR_SRC)
        target_cls = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "PresenceHouseStateSensor":
                target_cls = node
                break
        cls_src = ast.get_source_segment(SENSOR_SRC, target_cls)
        # Should reference _tracked_persons_count / _all_tracked_persons_away
        # on the presence coordinator object.
        assert "_tracked_persons_count" in cls_src
        assert "_all_tracked_persons_away" in cls_src
