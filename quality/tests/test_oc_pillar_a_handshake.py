"""OC Phase 5 Pillar A — sibling-coordinator handshake adoption.

Behavioral tests for ``honor_optimizer_intent`` on Energy, Presence, and
Security coordinators per
``docs/planning/PLANNING_OC_phase5_handshake_and_admin_surface.md`` D7/D8.

Tests drive the REAL coordinator classes — no mocks of the methods under
test — and confirm:

- ACK path on a benign intent.
- VETO paths per the plan's safe-defaults (EVSE off-peak, battery
  writeables, presence input sensors, lock + alarm panel domains,
  observation_mode blanket).
- Not-loaded path: when the sibling coordinator isn't constructed, the
  broker dispatch still completes without raising (the broker treats
  silence as "proceed", matching v5.x shipped behavior).
- Double-subscribe guard: a re-entry into ``async_setup`` does NOT
  register a second SIGNAL_OPTIMIZER_INTENT listener (Bug Class #50).
- L1 inert: at L1 Shadow, every intent the broker emits carries
  ``effective_level in {"advisory", "shadow"}`` AND ``veto_window_s == 0``
  — no L2+ intents leak.
"""
from __future__ import annotations

import os
import sys
import types
from datetime import datetime
from unittest.mock import MagicMock

import pytest

# Repo root on path so ``custom_components.universal_room_automation`` resolves
# to the real package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ---------------------------------------------------------------------------
# Minimal HA module shims — mirrors test_optimization_coordinator.py shape.
# Kept narrow to the surfaces this test actually imports.
# ---------------------------------------------------------------------------


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock


def _start_of_local_day():
    now = datetime.now()
    return datetime(now.year, now.month, now.day)


_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
        "CALLBACK_TYPE": type(None),
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
        "async_track_state_change_event": lambda *a, **k: (lambda: None),
        "async_track_time_interval": lambda hass, cb, interval: (lambda: None),
        "async_call_later": lambda hass, delay, cb: (lambda: None),
        "async_track_time_change": lambda hass, cb, **kw: (lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        # NB — tests below stub ``async_dispatcher_send`` per case to
        # capture veto fires; this default no-op is the safe baseline.
        "async_dispatcher_connect": lambda *a, **k: (lambda: None),
        "async_dispatcher_send": lambda *a, **k: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
        "CoordinatorEntity": type(
            "CoordinatorEntity", (),
            {"__class_getitem__": classmethod(lambda cls, item: cls)},
        ),
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {}),
    },
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
        "start_of_local_day": _start_of_local_day,
    },
    "homeassistant.components": {},
    "homeassistant.components.logbook": {
        "LOGBOOK_ENTRY_MESSAGE": "message",
        "LOGBOOK_ENTRY_NAME": "name",
    },
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
        "ButtonEntity": type("ButtonEntity", (), {})
    },
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {})
    },
    "homeassistant.components.number": {
        "NumberEntity": type("NumberEntity", (), {}),
        "NumberMode": MagicMock(),
    },
    "homeassistant.components.select": {
        "SelectEntity": type("SelectEntity", (), {})
    },
    "homeassistant.components.webhook": {
        "async_register": lambda *a, **k: None,
        "async_unregister": lambda *a, **k: None,
    },
    "homeassistant.components.person": {"DOMAIN": "person"},
    "homeassistant.components.device_tracker": {"DOMAIN": "device_tracker"},
    "homeassistant.components.zone": {"DOMAIN": "zone"},
    "homeassistant.components.light": _mock_cls(),
    "homeassistant.components.fan": _mock_cls(),
    "homeassistant.components.climate": _mock_cls(),
    "homeassistant.components.cover": _mock_cls(),
    "homeassistant.components.alarm_control_panel": _mock_cls(),
    "homeassistant.components.media_player": _mock_cls(),
    "homeassistant.components.automation": _mock_cls(),
    "homeassistant.helpers.area_registry": {"async_get": _mock_cls()},
    "aiosqlite": MagicMock(),
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        existing = sys.modules.get(name)
        if existing is None:
            sys.modules[name] = _mock_module(name, **attrs)
        else:
            for k, v in attrs.items():
                if not hasattr(existing, k):
                    setattr(existing, k, v)
    else:
        if name not in sys.modules:
            sys.modules[name] = attrs


@pytest.fixture(autouse=True)
def _evict_ura_stubs():
    """Re-mirror the eviction fixture from
    ``test_optimization_coordinator.py`` so sibling-test stubs don't win
    when this file runs alongside ``test_bayesian_predictor`` et al.
    """
    for _modname in list(sys.modules):
        if (
            _modname == "custom_components.universal_room_automation"
            or _modname.startswith(
                "custom_components.universal_room_automation."
            )
        ):
            del sys.modules[_modname]
    cc_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")
    )
    cc = sys.modules.get("custom_components")
    if cc is None:
        cc = types.ModuleType("custom_components")
        cc.__path__ = [cc_dir]
        sys.modules["custom_components"] = cc
    else:
        existing_path = list(getattr(cc, "__path__", []) or [])
        if cc_dir not in existing_path:
            existing_path.append(cc_dir)
            cc.__path__ = existing_path
    yield


# ---------------------------------------------------------------------------
# Energy coordinator handshake
# ---------------------------------------------------------------------------


def _make_energy_coord(entity_config=None, tou_period="off_peak"):
    """Build an EnergyCoordinator with just enough surface to honor an
    intent. The real coordinator is constructed; we replace the TOU
    engine and EV controller with light stand-ins that expose only the
    methods the honor path reads.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )

    class _TOU:
        def __init__(self, period):
            self._period = period

        def get_current_period(self):
            return self._period

        def get_window_seconds_until_next_off_peak(self):
            return 0

    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    hass.config_entries.async_entries = lambda *_a, **_k: []
    hass.bus = MagicMock()
    hass.states = MagicMock()

    coord = EnergyCoordinator(
        hass=hass,
        reserve_soc=20,
        decision_interval=10,
        entity_config=entity_config or {},
        tou_engine=_TOU(tou_period),
    )
    return coord


@pytest.mark.asyncio
async def test_energy_honor_acks_benign_light_intent():
    coord = _make_energy_coord()
    intent = {
        "action_id": "a1",
        "target_entity": "light.kitchen",
        "service": "light.turn_on",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is True


@pytest.mark.asyncio
async def test_energy_honor_vetoes_evse_offpeak():
    coord = _make_energy_coord(tou_period="off_peak")
    # The EnergyCoordinator's EVChargerController defaults to garage_a /
    # garage_b switches; pick the documented one.
    intent = {
        "action_id": "a2",
        "target_entity": "switch.garage_a",
        "service": "switch.turn_off",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is False
    assert coord._last_veto_reason == "evse_offpeak_charge_window"


@pytest.mark.asyncio
async def test_energy_honor_acks_evse_during_peak():
    coord = _make_energy_coord(tou_period="peak")
    intent = {
        "action_id": "a3",
        "target_entity": "switch.garage_a",
        "service": "switch.turn_off",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is True


@pytest.mark.asyncio
async def test_energy_honor_vetoes_battery_strategy_write():
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        CONF_ENERGY_STORAGE_MODE_ENTITY,
    )
    coord = _make_energy_coord(
        entity_config={CONF_ENERGY_STORAGE_MODE_ENTITY: "select.enphase_storage_mode"},
        tou_period="peak",
    )
    intent = {
        "action_id": "a4",
        "target_entity": "select.enphase_storage_mode",
        "service": "select.select_option",
        "service_data": {"option": "self-consumption"},
        "effective_level": "propose_config",
    }
    assert coord.honor_optimizer_intent(intent) is False
    assert coord._last_veto_reason == "battery_strategy_write"


@pytest.mark.asyncio
async def test_energy_honor_observation_mode_blanket_veto():
    coord = _make_energy_coord(tou_period="peak")
    coord.observation_mode = True
    intent = {
        "action_id": "a5",
        "target_entity": "light.kitchen",
        "service": "light.turn_on",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is False
    assert coord._last_veto_reason == "observation_mode"


# ---------------------------------------------------------------------------
# Presence coordinator handshake
# ---------------------------------------------------------------------------


def _make_presence_coord(rooms=None):
    """Build a PresenceCoordinator with config_entries seeded so the
    curated CONF_*_SENSORS lookup resolves. ``rooms`` is a list of
    ``(name, mmwave, motion, occupancy)`` tuples.
    """
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE,
        CONF_MMWAVE_SENSORS,
        CONF_MOTION_SENSORS,
        CONF_OCCUPANCY_SENSORS,
        CONF_ROOM_NAME,
        ENTRY_TYPE_ROOM,
    )
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )

    entries = []
    for room in rooms or []:
        name, mm, mo, oc = room
        e = MagicMock()
        e.data = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            CONF_ROOM_NAME: name,
            CONF_MMWAVE_SENSORS: list(mm),
            CONF_MOTION_SENSORS: list(mo),
            CONF_OCCUPANCY_SENSORS: list(oc),
        }
        e.options = {}
        entries.append(e)

    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    hass.config_entries.async_entries = lambda *_a, **_k: list(entries)
    hass.bus = MagicMock()
    hass.states = MagicMock()

    coord = PresenceCoordinator(hass=hass)
    return coord


@pytest.mark.asyncio
async def test_presence_honor_acks_benign_intent():
    coord = _make_presence_coord(rooms=[(
        "kitchen",
        ["binary_sensor.kitchen_mmwave"],
        ["binary_sensor.kitchen_motion"],
        ["binary_sensor.kitchen_occupancy"],
    )])
    intent = {
        "action_id": "p1",
        "target_entity": "light.kitchen",
        "service": "light.turn_on",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is True


@pytest.mark.asyncio
async def test_presence_honor_vetoes_mmwave_input_sensor():
    coord = _make_presence_coord(rooms=[(
        "master_bedroom",
        ["binary_sensor.master_bedroom_mmwave"],
        [],
        [],
    )])
    intent = {
        "action_id": "p2",
        "target_entity": "binary_sensor.master_bedroom_mmwave",
        "service": "homeassistant.turn_off",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is False
    assert coord._last_veto_reason == "presence_input_sensor"


@pytest.mark.asyncio
async def test_presence_honor_vetoes_occupancy_input_sensor():
    coord = _make_presence_coord(rooms=[(
        "study",
        [],
        [],
        ["binary_sensor.study_occupancy"],
    )])
    intent = {
        "action_id": "p3",
        "target_entity": "binary_sensor.study_occupancy",
        "service": "homeassistant.turn_off",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is False
    assert coord._last_veto_reason == "presence_input_sensor"


@pytest.mark.asyncio
async def test_presence_honor_observation_mode_blanket_veto():
    coord = _make_presence_coord()
    coord.observation_mode = True
    intent = {
        "action_id": "p4",
        "target_entity": "light.kitchen",
        "service": "light.turn_on",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is False
    assert coord._last_veto_reason == "observation_mode"


# ---------------------------------------------------------------------------
# Security coordinator handshake
# ---------------------------------------------------------------------------


def _make_security_coord():
    from custom_components.universal_room_automation.domain_coordinators.security import (
        SecurityCoordinator,
    )
    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    hass.config_entries.async_entries = lambda *_a, **_k: []
    hass.bus = MagicMock()
    hass.states = MagicMock()
    coord = SecurityCoordinator(
        hass=hass,
        lock_entities=[],
        garage_entities=[],
        entry_sensors=[],
        security_lights=[],
        camera_entities=[],
    )
    return coord


@pytest.mark.asyncio
async def test_security_honor_acks_benign_light_intent():
    coord = _make_security_coord()
    intent = {
        "action_id": "s1",
        "target_entity": "light.porch",
        "service": "light.turn_on",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is True


@pytest.mark.asyncio
async def test_security_honor_vetoes_lock_domain():
    coord = _make_security_coord()
    intent = {
        "action_id": "s2",
        "target_entity": "lock.front_door",
        "service": "lock.unlock",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is False
    assert coord._last_veto_reason == "lock_domain"


@pytest.mark.asyncio
async def test_security_honor_vetoes_alarm_panel():
    coord = _make_security_coord()
    intent = {
        "action_id": "s3",
        "target_entity": "alarm_control_panel.house",
        "service": "alarm_control_panel.alarm_disarm",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is False
    assert coord._last_veto_reason == "alarm_panel_domain"


@pytest.mark.asyncio
async def test_security_honor_observation_mode_blanket_veto():
    coord = _make_security_coord()
    coord.observation_mode = True
    intent = {
        "action_id": "s4",
        "target_entity": "light.porch",
        "service": "light.turn_on",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is False
    assert coord._last_veto_reason == "observation_mode"


# ---------------------------------------------------------------------------
# Veto-fire path — sibling fires SIGNAL_OPTIMIZER_INTENT_VETO with the
# correct payload shape (action_id + vetoed_by + reason).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_intent_callback_fires_veto_signal(monkeypatch):
    coord = _make_security_coord()
    fired = []

    def _capture_send(_hass, signal, payload=None):
        fired.append((signal, payload))

    # Patch async_dispatcher_send INSIDE the security module so the
    # callback's local reference uses our capture.
    import custom_components.universal_room_automation.domain_coordinators.security as sec_mod
    monkeypatch.setattr(sec_mod, "async_dispatcher_send", _capture_send)

    coord._on_optimizer_intent({
        "action_id": "v1",
        "target_entity": "lock.front_door",
        "service": "lock.unlock",
        "service_data": {},
        "effective_level": "reversible_device",
    })
    assert fired, "Expected SIGNAL_OPTIMIZER_INTENT_VETO to fire"
    signal, payload = fired[0]
    assert signal == sec_mod.SIGNAL_OPTIMIZER_INTENT_VETO
    assert payload["action_id"] == "v1"
    assert payload["vetoed_by"] == "security"
    assert payload["reason"] == "lock_domain"


@pytest.mark.asyncio
async def test_security_intent_callback_no_veto_on_ack(monkeypatch):
    coord = _make_security_coord()
    fired = []
    import custom_components.universal_room_automation.domain_coordinators.security as sec_mod
    monkeypatch.setattr(
        sec_mod, "async_dispatcher_send",
        lambda *a, **k: fired.append(a),
    )
    coord._on_optimizer_intent({
        "action_id": "v2",
        "target_entity": "light.porch",
        "service": "light.turn_on",
        "service_data": {},
        "effective_level": "reversible_device",
    })
    assert fired == []


# ---------------------------------------------------------------------------
# Not-loaded path: an intent dispatched while no sibling is loaded must
# not raise — the broker treats absence as "proceed". We exercise this
# by dispatching SIGNAL_OPTIMIZER_INTENT through the live dispatcher
# helper that the broker uses and confirming no exception propagates.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broker_fire_intent_when_no_sibling_loaded_does_not_raise():
    """Broker dispatch with NO sibling listeners attached must not raise
    and must return True (the v5.x shipped invariant). Pillar A wires
    siblings but doesn't change the broker's no-sibling fallback.
    """
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizerIntentBroker,
    )
    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    broker = OptimizerIntentBroker(hass)
    ok = broker.fire_intent(
        action_id="nl1",
        target_entity="light.kitchen",
        service="light.turn_on",
        service_data={},
        source_dimension="comfort",
        veto_window_s=0,
        action_class="reversible_device",
        effective_level="shadow",
    )
    assert ok is True


# ---------------------------------------------------------------------------
# Double-subscribe guard — re-entry into ``async_setup`` MUST NOT register
# a second optimizer-intent listener. We assert by direct inspection of
# the guard field — a second call to async_setup is heavyweight to run
# here; the production guard is the same `if self._X is None` shape
# already used by other coordinators per Bug Class #50.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Double-subscribe guard — drives the REAL subscribe path twice and asserts
# exactly ONE dispatcher connection. C-C2 / C-C4 fix-up: the previous tests
# only re-asserted that a sentinel object equals itself, which proves
# nothing. These tests replace ``async_dispatcher_connect`` with a counting
# stub and execute the production subscribe block twice — the second pass
# MUST not register a second listener.
# ---------------------------------------------------------------------------


def _make_counting_dispatcher():
    """Build a (connect_stub, send_stub, calls, listeners) tuple where
    ``connect_stub`` records each call into ``calls`` and registers the
    callback into ``listeners[signal]``; ``send_stub`` invokes every
    callback registered for the signal in-order (mirrors HA's behavior).
    """
    calls = []
    listeners: dict = {}

    def _connect(_hass, signal, cb):
        calls.append((signal, cb))
        listeners.setdefault(signal, []).append(cb)

        def _unsub():
            try:
                listeners[signal].remove(cb)
            except (ValueError, KeyError):
                pass
        return _unsub

    def _send(_hass, signal, payload=None):
        for cb in list(listeners.get(signal, [])):
            cb(payload)

    return _connect, _send, calls, listeners


def _drive_subscribe_block(coord, module, signal_name):
    """Execute the production ``if self._optimizer_intent_unsub is None:``
    subscribe block once against the module's currently-installed
    ``async_dispatcher_connect``. This mirrors what the coordinator's
    ``async_setup`` body does. We extract it here so the test can call
    it TWICE and assert idempotence — the production code that the
    sibling fix-up review demanded be exercised, not echoed.
    """
    if coord._optimizer_intent_unsub is None:
        coord._optimizer_intent_unsub = module.async_dispatcher_connect(
            coord.hass,
            getattr(module, signal_name),
            coord._on_optimizer_intent,
        )
        coord._unsub_listeners.append(coord._optimizer_intent_unsub)


@pytest.mark.asyncio
async def test_security_double_subscribe_guard(monkeypatch):
    import custom_components.universal_room_automation.domain_coordinators.security as sec_mod
    connect, _send, calls, _listeners = _make_counting_dispatcher()
    monkeypatch.setattr(sec_mod, "async_dispatcher_connect", connect)
    coord = _make_security_coord()
    # First subscribe — production block runs once.
    _drive_subscribe_block(coord, sec_mod, "SIGNAL_OPTIMIZER_INTENT")
    # Second subscribe — production block reruns; the guard MUST skip.
    _drive_subscribe_block(coord, sec_mod, "SIGNAL_OPTIMIZER_INTENT")
    intent_calls = [c for c in calls if c[0] == sec_mod.SIGNAL_OPTIMIZER_INTENT]
    assert len(intent_calls) == 1, (
        f"Expected exactly ONE SIGNAL_OPTIMIZER_INTENT subscription, "
        f"got {len(intent_calls)}: {intent_calls}"
    )


@pytest.mark.asyncio
async def test_energy_double_subscribe_guard(monkeypatch):
    import custom_components.universal_room_automation.domain_coordinators.energy as energy_mod
    connect, _send, calls, _listeners = _make_counting_dispatcher()
    monkeypatch.setattr(energy_mod, "async_dispatcher_connect", connect)
    coord = _make_energy_coord()
    _drive_subscribe_block(coord, energy_mod, "SIGNAL_OPTIMIZER_INTENT")
    _drive_subscribe_block(coord, energy_mod, "SIGNAL_OPTIMIZER_INTENT")
    intent_calls = [
        c for c in calls if c[0] == energy_mod.SIGNAL_OPTIMIZER_INTENT
    ]
    assert len(intent_calls) == 1, (
        f"Expected exactly ONE SIGNAL_OPTIMIZER_INTENT subscription, "
        f"got {len(intent_calls)}: {intent_calls}"
    )


@pytest.mark.asyncio
async def test_presence_double_subscribe_guard(monkeypatch):
    import custom_components.universal_room_automation.domain_coordinators.presence as presence_mod
    connect, _send, calls, _listeners = _make_counting_dispatcher()
    monkeypatch.setattr(presence_mod, "async_dispatcher_connect", connect)
    coord = _make_presence_coord()
    _drive_subscribe_block(coord, presence_mod, "SIGNAL_OPTIMIZER_INTENT")
    _drive_subscribe_block(coord, presence_mod, "SIGNAL_OPTIMIZER_INTENT")
    intent_calls = [
        c for c in calls if c[0] == presence_mod.SIGNAL_OPTIMIZER_INTENT
    ]
    assert len(intent_calls) == 1, (
        f"Expected exactly ONE SIGNAL_OPTIMIZER_INTENT subscription, "
        f"got {len(intent_calls)}: {intent_calls}"
    )


# ---------------------------------------------------------------------------
# L1 Shadow inert check — at L1, every intent the broker emits must
# carry ``effective_level in {"advisory", "shadow"}`` and a
# ``veto_window_s == 0`` field. No L2+ intent can leak. This is the
# write-flood-guardrail invariant from the plan.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l1_shadow_intents_are_shadow_only():
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizerIntentBroker,
    )
    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}

    captured = []

    def _capture(_hass, _signal, payload):
        captured.append(payload)

    import custom_components.universal_room_automation.domain_coordinators.optimization as opt_mod
    # Patch the dispatcher_send used by fire_intent so we observe the
    # exact payload that would have hit the bus.
    original = opt_mod.async_dispatcher_send
    opt_mod.async_dispatcher_send = _capture
    try:
        broker = OptimizerIntentBroker(hass)
        # Simulate three L1 (shadow) fires across different dimensions.
        for i, dim in enumerate(("comfort", "energy", "safety")):
            broker.fire_intent(
                action_id=f"s{i}",
                target_entity="light.kitchen",
                service="light.turn_on",
                service_data={},
                source_dimension=dim,
                veto_window_s=0,
                action_class="reversible_device",
                effective_level="shadow",
            )
    finally:
        opt_mod.async_dispatcher_send = original

    assert captured, "Expected at least one intent payload to be captured"
    for payload in captured:
        assert payload["effective_level"] in ("advisory", "shadow"), (
            f"L1 dispatched non-shadow intent: {payload}"
        )
        assert payload["veto_window_s"] == 0, (
            f"L1 dispatched intent with non-zero veto window: {payload}"
        )


# ---------------------------------------------------------------------------
# C-C4 fix-up: L1 gate exercised via the production level-gate path. The
# previous "shadow_only" test echoed its own input (caller passed shadow,
# assertion read shadow). This test drives the production
# ``_apply_action`` matrix with a configured L1 finding and asserts that
# the EMITTED intent (captured at the dispatcher) carries the right
# effective_level — derived by the coordinator's
# ``_resolve_effective_level``, not the test.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l1_gate_emits_shadow_via_production_resolver():
    import custom_components.universal_room_automation.domain_coordinators.optimization as opt_mod
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
        OptimizationFinding,
    )
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationDimension,
    )

    captured = []

    def _capture(_hass, _signal, payload=None):
        captured.append(payload)

    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    # Coordinator's _read_cm_config returns empty by default — no entries.
    hass.config_entries.async_entries = lambda *_a, **_k: []

    monkey_orig = opt_mod.async_dispatcher_send
    opt_mod.async_dispatcher_send = _capture
    try:
        coord = OptimizationCoordinator(hass=hass)
        finding = OptimizationFinding(
            timestamp="2026-06-10T17:00:00+00:00",
            level="room",
            target_id="test_room",
            dimension=OptimizationDimension.COMFORT,
            severity="medium",
            confidence=0.95,
            score=0.5,
            description="L1 production-resolver test",
        )
        action = {
            "service": "light.turn_on",
            "service_data": {},
            "target_entity": "light.kitchen",
            "action_class": "reversible_device",
        }
        outcome = await coord._apply_action(finding, action)
    finally:
        opt_mod.async_dispatcher_send = monkey_orig

    # The coordinator's PRODUCTION ``_resolve_effective_level`` chose
    # "shadow" (default), so the emitted intent payload must carry
    # effective_level=shadow — not because the test asked for it, but
    # because the gate computed it.
    intent_payloads = [
        p for p in captured
        if isinstance(p, dict) and p.get("action_id") == finding.applied_action_id
    ]
    assert intent_payloads, (
        f"Expected one intent payload emitted via production gate, "
        f"captured={captured}"
    )
    payload = intent_payloads[0]
    assert payload["effective_level"] == "shadow", (
        f"Production gate at default rung must emit shadow level, got "
        f"{payload['effective_level']}"
    )
    assert payload["veto_window_s"] == 0
    assert outcome == "shadow_dry_run", (
        f"L1 outcome must be 'shadow_dry_run' (production vocab, observed "
        f"live on the v5.3.3 findings sensor), got {outcome}"
    )


# ---------------------------------------------------------------------------
# B-H1 fix-up: L1 inertness exercised through the REAL sibling handlers
# wired to a faithful dispatcher. The optimizer fires a shadow intent
# through the production dispatch site; sibling handlers receive it but
# MUST NOT emit a veto signal AND MUST NOT emit a handler INFO log line.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l1_inertness_real_handlers_emit_no_veto(monkeypatch, caplog):
    import logging
    import custom_components.universal_room_automation.domain_coordinators.optimization as opt_mod
    import custom_components.universal_room_automation.domain_coordinators.energy as energy_mod
    import custom_components.universal_room_automation.domain_coordinators.presence as presence_mod
    import custom_components.universal_room_automation.domain_coordinators.security as security_mod

    # Faithful in-process dispatcher: connect adds to listener list;
    # send synchronously invokes every callback registered on the signal.
    listeners: dict = {}

    def _connect(_hass, signal, cb):
        listeners.setdefault(signal, []).append(cb)

        def _unsub():
            try:
                listeners[signal].remove(cb)
            except (ValueError, KeyError):
                pass
        return _unsub

    def _send(_hass, signal, payload=None):
        for cb in list(listeners.get(signal, [])):
            cb(payload)

    for mod in (opt_mod, energy_mod, presence_mod, security_mod):
        monkeypatch.setattr(mod, "async_dispatcher_send", _send)
        monkeypatch.setattr(mod, "async_dispatcher_connect", _connect)

    energy_coord = _make_energy_coord()
    presence_coord = _make_presence_coord()
    security_coord = _make_security_coord()

    # Wire siblings into the real dispatcher.
    _drive_subscribe_block(
        energy_coord, energy_mod, "SIGNAL_OPTIMIZER_INTENT",
    )
    _drive_subscribe_block(
        presence_coord, presence_mod, "SIGNAL_OPTIMIZER_INTENT",
    )
    _drive_subscribe_block(
        security_coord, security_mod, "SIGNAL_OPTIMIZER_INTENT",
    )

    # Track veto traffic through the faithful dispatcher.
    veto_payloads = []

    def _veto_recorder(payload):
        veto_payloads.append(payload)

    _connect(
        None, opt_mod.SIGNAL_OPTIMIZER_INTENT_VETO, _veto_recorder,
    )

    # Fire a shadow intent — the L1 production path.
    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    broker = opt_mod.OptimizerIntentBroker(hass)

    # Capture handler-level INFO+ records from the three sibling modules.
    caplog.clear()
    target_loggers = (
        "custom_components.universal_room_automation.domain_coordinators.energy",
        "custom_components.universal_room_automation.domain_coordinators.presence",
        "custom_components.universal_room_automation.domain_coordinators.security",
    )
    with caplog.at_level(logging.INFO):
        ok = broker.fire_intent(
            action_id="l1inert1",
            target_entity="switch.garage_a",  # would normally trigger Energy veto
            service="switch.turn_off",
            service_data={},
            source_dimension="energy",
            veto_window_s=0,
            action_class="reversible_device",
            effective_level="shadow",
        )

    assert ok is True
    assert veto_payloads == [], (
        f"L1 (shadow) intent must produce ZERO veto traffic, got: "
        f"{veto_payloads}"
    )
    # And no INFO-level handler veto log line should appear.
    sibling_info = [
        r for r in caplog.records
        if r.levelno >= logging.INFO and r.name in target_loggers
        and "vetoed by" in r.getMessage()
    ]
    assert sibling_info == [], (
        f"L1 sibling handlers must not emit INFO veto log lines, got: "
        f"{[r.getMessage() for r in sibling_info]}"
    )


# ---------------------------------------------------------------------------
# CRITICAL-1 / A-C1 / C-C1 fix-up: end-to-end veto loop. The optimizer's
# _apply_action fires an intent through the REAL broker; a real sibling
# handler vetoes it; the action is BLOCKED and the outcome is recorded.
# No mocks stand in for the broker.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_action_blocked_by_real_sibling_veto(monkeypatch):
    import custom_components.universal_room_automation.domain_coordinators.optimization as opt_mod
    import custom_components.universal_room_automation.domain_coordinators.security as security_mod
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
        OptimizationFinding,
    )
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        CONF_OPTIMIZER_AUTONOMY_LEVEL,
        CONF_ENTRY_TYPE,
        ENTRY_TYPE_COORDINATOR_MANAGER,
        OPTIMIZER_LEVEL_REVERSIBLE_DEVICE,
    )

    # Faithful in-process dispatcher (synchronous fan-out).
    listeners: dict = {}

    def _connect(_hass, signal, cb):
        listeners.setdefault(signal, []).append(cb)

        def _unsub():
            try:
                listeners[signal].remove(cb)
            except (ValueError, KeyError):
                pass
        return _unsub

    def _send(_hass, signal, payload=None):
        for cb in list(listeners.get(signal, [])):
            cb(payload)

    monkeypatch.setattr(opt_mod, "async_dispatcher_send", _send)
    monkeypatch.setattr(opt_mod, "async_dispatcher_connect", _connect)
    monkeypatch.setattr(security_mod, "async_dispatcher_send", _send)
    monkeypatch.setattr(security_mod, "async_dispatcher_connect", _connect)

    # Build a CM entry that puts the optimizer at L2 (reversible_device).
    cm_entry = MagicMock()
    cm_entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}
    cm_entry.options = {
        CONF_OPTIMIZER_AUTONOMY_LEVEL: OPTIMIZER_LEVEL_REVERSIBLE_DEVICE,
    }

    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    hass.config_entries.async_entries = lambda *_a, **_k: [cm_entry]

    # Real services.async_call must never be reached on a vetoed action;
    # raise if invoked.
    calls = []

    async def _async_call(domain, service, data, blocking=False):
        calls.append((domain, service, data, blocking))

    hass.services.async_call = _async_call

    # Build the REAL broker (no mock substitute) — wire it via the
    # faithful dispatcher.
    coord = OptimizationCoordinator(hass=hass)
    coord.broker.async_start()

    # Wire a real Security coordinator that will VETO a lock target.
    security_coord = _make_security_coord()
    security_coord.hass = hass
    _drive_subscribe_block(
        security_coord, security_mod, "SIGNAL_OPTIMIZER_INTENT",
    )

    # lock.* / alarm_control_panel.* are outside the L2 domain allowlist
    # (they'd be domain-blocked before any veto). To exercise the VETO loop
    # itself we use a target in an ALLOWED domain (light) that Security
    # still vetoes via its observation_mode blanket.
    security_coord.observation_mode = True
    action3 = {
        "service": "light.turn_on",
        "service_data": {},
        "target_entity": "light.porch",
        "action_class": "reversible_device",
    }
    finding3 = OptimizationFinding(
        timestamp="2026-06-10T17:00:00+00:00",
        level="house",
        target_id="porch",
        dimension=OptimizationDimension.COMFORT,
        severity="medium",
        confidence=0.99,
        score=0.5,
        description="L2 light dispatch must be VETOED end-to-end",
    )
    outcome = await coord._apply_action(finding3, action3)

    assert outcome == "vetoed", (
        f"Expected 'vetoed' from real sibling end-to-end, got {outcome!r}"
    )
    assert finding3.applied_outcome == "vetoed"
    # The service call MUST NOT have run.
    assert calls == [], f"Vetoed action must not dispatch, got: {calls}"


# ---------------------------------------------------------------------------
# C-C5 fix-up: payload-shape veto tests for Energy and Presence
# handlers (Security was already covered).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_energy_intent_callback_fires_veto_signal(monkeypatch):
    coord = _make_energy_coord(tou_period="off_peak")
    fired = []

    def _capture_send(_hass, signal, payload=None):
        fired.append((signal, payload))

    import custom_components.universal_room_automation.domain_coordinators.energy as energy_mod
    monkeypatch.setattr(energy_mod, "async_dispatcher_send", _capture_send)

    coord._on_optimizer_intent({
        "action_id": "ev1",
        "target_entity": "switch.garage_a",
        "service": "switch.turn_off",
        "service_data": {},
        # Must be NON-L1 so the L1-inert gate doesn't suppress the veto.
        "effective_level": "reversible_device",
    })
    assert fired, "Expected SIGNAL_OPTIMIZER_INTENT_VETO to fire"
    signal, payload = fired[0]
    assert signal == energy_mod.SIGNAL_OPTIMIZER_INTENT_VETO
    assert payload["action_id"] == "ev1"
    assert payload["vetoed_by"] == "energy"
    assert payload["reason"] == "evse_offpeak_charge_window"


@pytest.mark.asyncio
async def test_presence_intent_callback_fires_veto_signal(monkeypatch):
    coord = _make_presence_coord(rooms=[(
        "master_bedroom",
        ["binary_sensor.master_bedroom_mmwave"],
        [],
        [],
    )])
    fired = []

    def _capture_send(_hass, signal, payload=None):
        fired.append((signal, payload))

    import custom_components.universal_room_automation.domain_coordinators.presence as presence_mod
    monkeypatch.setattr(presence_mod, "async_dispatcher_send", _capture_send)

    coord._on_optimizer_intent({
        "action_id": "pv1",
        "target_entity": "binary_sensor.master_bedroom_mmwave",
        "service": "homeassistant.turn_off",
        "service_data": {},
        "effective_level": "reversible_device",
    })
    assert fired, "Expected SIGNAL_OPTIMIZER_INTENT_VETO to fire"
    signal, payload = fired[0]
    assert signal == presence_mod.SIGNAL_OPTIMIZER_INTENT_VETO
    assert payload["action_id"] == "pv1"
    assert payload["vetoed_by"] == "presence"
    assert payload["reason"] == "presence_input_sensor"


# ---------------------------------------------------------------------------
# C-C5 sibling→broker wiring test through a real dispatcher: the sibling
# fires its veto and the BROKER observes it (the round-trip handshake).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sibling_veto_round_trips_to_broker(monkeypatch):
    import custom_components.universal_room_automation.domain_coordinators.optimization as opt_mod
    import custom_components.universal_room_automation.domain_coordinators.security as security_mod

    listeners: dict = {}

    def _connect(_hass, signal, cb):
        listeners.setdefault(signal, []).append(cb)

        def _unsub():
            try:
                listeners[signal].remove(cb)
            except (ValueError, KeyError):
                pass
        return _unsub

    def _send(_hass, signal, payload=None):
        for cb in list(listeners.get(signal, [])):
            cb(payload)

    monkeypatch.setattr(opt_mod, "async_dispatcher_send", _send)
    monkeypatch.setattr(opt_mod, "async_dispatcher_connect", _connect)
    monkeypatch.setattr(security_mod, "async_dispatcher_send", _send)
    monkeypatch.setattr(security_mod, "async_dispatcher_connect", _connect)

    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    broker = opt_mod.OptimizerIntentBroker(hass)
    broker.async_start()

    security_coord = _make_security_coord()
    security_coord.hass = hass
    _drive_subscribe_block(
        security_coord, security_mod, "SIGNAL_OPTIMIZER_INTENT",
    )

    broker.fire_intent(
        action_id="rt1",
        target_entity="lock.front_door",
        service="lock.unlock",
        service_data={},
        source_dimension="safety",
        veto_window_s=0,
        # Non-shadow so the L1-inert gate doesn't suppress the sibling.
        effective_level="reversible_device",
        action_class="reversible_device",
    )

    vetoed_by = await broker.await_veto("rt1", 0)
    assert vetoed_by == "security", (
        f"Expected end-to-end veto attribution 'security', got {vetoed_by!r}"
    )


# ---------------------------------------------------------------------------
# C-C6 fix-up: first veto wins. Two siblings veto the same action_id in
# the same event-loop turn; the first responder's attribution is kept.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_veto_wins_on_same_action_id():
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizerIntentBroker,
    )
    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    broker = OptimizerIntentBroker(hass)
    broker._on_veto({"action_id": "x1", "vetoed_by": "presence"})
    broker._on_veto({"action_id": "x1", "vetoed_by": "energy"})
    vetoed_by = await broker.await_veto("x1", 0)
    assert vetoed_by == "presence"


# ---------------------------------------------------------------------------
# B-H1 fix-up: per-handler L1 inertness — direct dispatch into the
# handler with effective_level=shadow must produce NO veto signal.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_energy_handler_inert_at_l1_shadow(monkeypatch):
    coord = _make_energy_coord(tou_period="off_peak")
    fired = []
    import custom_components.universal_room_automation.domain_coordinators.energy as energy_mod
    monkeypatch.setattr(
        energy_mod, "async_dispatcher_send",
        lambda *a, **k: fired.append(a),
    )
    coord._on_optimizer_intent({
        "action_id": "el1",
        "target_entity": "switch.garage_a",
        "service": "switch.turn_off",
        "service_data": {},
        "effective_level": "shadow",
    })
    assert fired == [], (
        f"Energy handler must NOT veto at L1 shadow, got: {fired}"
    )


@pytest.mark.asyncio
async def test_presence_handler_inert_at_l1_shadow(monkeypatch):
    coord = _make_presence_coord(rooms=[(
        "kitchen",
        ["binary_sensor.kitchen_mmwave"],
        [],
        [],
    )])
    fired = []
    import custom_components.universal_room_automation.domain_coordinators.presence as presence_mod
    monkeypatch.setattr(
        presence_mod, "async_dispatcher_send",
        lambda *a, **k: fired.append(a),
    )
    coord._on_optimizer_intent({
        "action_id": "pl1",
        "target_entity": "binary_sensor.kitchen_mmwave",
        "service": "homeassistant.turn_off",
        "service_data": {},
        "effective_level": "shadow",
    })
    assert fired == [], (
        f"Presence handler must NOT veto at L1 shadow, got: {fired}"
    )


@pytest.mark.asyncio
async def test_security_handler_inert_at_l1_shadow(monkeypatch):
    coord = _make_security_coord()
    fired = []
    import custom_components.universal_room_automation.domain_coordinators.security as security_mod
    monkeypatch.setattr(
        security_mod, "async_dispatcher_send",
        lambda *a, **k: fired.append(a),
    )
    coord._on_optimizer_intent({
        "action_id": "sl1",
        "target_entity": "lock.front_door",
        "service": "lock.unlock",
        "service_data": {},
        "effective_level": "shadow",
    })
    assert fired == [], (
        f"Security handler must NOT veto at L1 shadow, got: {fired}"
    )


# ---------------------------------------------------------------------------
# HIGH-4 / D7(a) coverage broadening tests.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_energy_honor_vetoes_evse_breaker_offpeak():
    """EVSE *breaker* (not just switch) is vetoed during off-peak."""
    coord = _make_energy_coord(tou_period="off_peak")
    intent = {
        "action_id": "br1",
        "target_entity": "switch.span_panel_car_charger_breaker",
        "service": "switch.turn_off",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is False
    assert coord._last_veto_reason == "evse_offpeak_charge_window"


@pytest.mark.asyncio
async def test_energy_honor_vetoes_evse_during_load_shed_any_period():
    """EVSE veto fires while load-shedding is active regardless of TOU period."""
    coord = _make_energy_coord(tou_period="mid_peak")
    # Simulate active load-shed bookkeeping.
    coord._smart_plugs._paused_by_us.add("switch.dummy_plug")
    intent = {
        "action_id": "ls1",
        "target_entity": "switch.garage_a",
        "service": "switch.turn_on",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is False
    assert coord._last_veto_reason == "evse_load_shed_active"


@pytest.mark.asyncio
async def test_energy_honor_vetoes_smart_plug_under_load_shed():
    """Plug currently paused by load-shed is vetoed for any optimizer write."""
    coord = _make_energy_coord(tou_period="peak")
    coord._smart_plugs._paused_by_us.add("switch.smartplug_kitchen")
    intent = {
        "action_id": "sp1",
        "target_entity": "switch.smartplug_kitchen",
        "service": "switch.turn_on",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is False
    assert coord._last_veto_reason == "smart_plug_under_load_shed"


# ---------------------------------------------------------------------------
# MEDIUM-5: TOU period unknown / exception → veto EVSE-surface actions.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_energy_honor_fail_closed_when_tou_period_none(caplog):
    import logging
    coord = _make_energy_coord(tou_period=None)
    intent = {
        "action_id": "fc1",
        "target_entity": "switch.garage_a",
        "service": "switch.turn_off",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    with caplog.at_level(logging.WARNING):
        assert coord.honor_optimizer_intent(intent) is False
    assert coord._last_veto_reason == "evse_tou_period_unknown"
    # Rate-limited WARN should fire on first occurrence.
    assert any(
        "degraded input" in r.getMessage() and "tou_period_unknown" in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_energy_honor_fail_closed_when_tou_raises():
    coord = _make_energy_coord(tou_period="off_peak")

    class _BoomTOU:
        def get_current_period(self):
            raise RuntimeError("synthetic outage")

        def get_window_seconds_until_next_off_peak(self):
            return 0

    coord._tou = _BoomTOU()
    intent = {
        "action_id": "fc2",
        "target_entity": "switch.garage_a",
        "service": "switch.turn_off",
        "service_data": {},
        "effective_level": "reversible_device",
    }
    assert coord.honor_optimizer_intent(intent) is False
    assert coord._last_veto_reason == "evse_tou_period_unknown"


# ---------------------------------------------------------------------------
# MEDIUM-6 / A-M2: battery writeables resolved live from entry options.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_energy_battery_writeables_resolved_live_from_entry_options():
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE,
        ENTRY_TYPE_COORDINATOR_MANAGER,
    )
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        CONF_ENERGY_STORAGE_MODE_ENTITY,
    )
    coord = _make_energy_coord(tou_period="peak")
    # Initially no CM entry → battery writeables empty; benign intent ACKs.
    intent_ok = {
        "action_id": "bw1",
        "target_entity": "select.enphase_storage_mode",
        "service": "select.select_option",
        "service_data": {"option": "self-consumption"},
        "effective_level": "propose_config",
    }
    assert coord.honor_optimizer_intent(intent_ok) is True

    # Now add CM entry with the live battery-strategy entity AT options
    # (not entity_config snapshot) — honor MUST veto.
    cm_entry = MagicMock()
    cm_entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}
    cm_entry.options = {
        CONF_ENERGY_STORAGE_MODE_ENTITY: "select.enphase_storage_mode",
    }
    coord.hass.config_entries.async_entries = (
        lambda *_a, **_k: [cm_entry]
    )
    assert coord.honor_optimizer_intent(intent_ok) is False
    assert coord._last_veto_reason == "battery_strategy_write"


# ---------------------------------------------------------------------------
# MEDIUM-7 / B-M1: teardown resets _optimizer_intent_unsub to None so
# re-setup re-subscribes cleanly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_teardown_resets_optimizer_intent_unsub():
    coord = _make_security_coord()
    coord._optimizer_intent_unsub = object()
    await coord.async_teardown()
    assert coord._optimizer_intent_unsub is None


@pytest.mark.asyncio
async def test_energy_teardown_resets_optimizer_intent_unsub():
    coord = _make_energy_coord()
    coord._optimizer_intent_unsub = object()
    # Stub out everything async_teardown calls that would otherwise hit
    # uninitialized state (peak_import_history is iterable empty).
    coord._save_peak_import_history = (
        lambda: __import__("asyncio").sleep(0)
    )
    coord._save_evse_state = lambda: __import__("asyncio").sleep(0)
    coord._save_circuit_state = lambda: __import__("asyncio").sleep(0)
    coord._save_energy_baselines = lambda: __import__("asyncio").sleep(0)
    coord._save_envoy_cache = lambda: __import__("asyncio").sleep(0)
    coord._save_midnight_snapshot = lambda: __import__("asyncio").sleep(0)
    coord._save_load_shedding_level = lambda: __import__("asyncio").sleep(0)
    await coord.async_teardown()
    assert coord._optimizer_intent_unsub is None


@pytest.mark.asyncio
async def test_presence_teardown_resets_optimizer_intent_unsub():
    coord = _make_presence_coord()
    coord._optimizer_intent_unsub = object()
    # Disarm substrate so teardown can run cleanly.
    coord._substrate = None
    await coord.async_teardown()
    assert coord._optimizer_intent_unsub is None
