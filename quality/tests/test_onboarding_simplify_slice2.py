"""ONBOARDING-SIMPLIFY-1 — Slice 2 tests (D3 / D4 / D7).

Covers the reshaped essentials chain (D3), the D4 house->room ribbon
inversion (House minted via `flow.async_init(source="integration_create")`
at the room finale, not via a post-terminate menu route), and D7
Options-flow parity (INV-1 differential — the deferred keys are still
reachable in Options).

Correction (2026-09-12 operator): CONF_ZONE STAYS on essentials
conditionally (shown only when zones already exist, as pre-cycle). It is
NOT a dropped field.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

import pytest

# Reuse the mocked-HA harness already used by test_cycle_b_config_flow.
_cbcf = importlib.import_module("test_cycle_b_config_flow")
_cf = _cbcf._cf
_make_config_flow = _cbcf._make_config_flow

CONF_ROOM_NAME = _cf.CONF_ROOM_NAME
CONF_ROOM_TYPE = _cf.CONF_ROOM_TYPE
CONF_AREA_ID = _cf.CONF_AREA_ID
CONF_WET_ROOM = _cf.CONF_WET_ROOM
CONF_ROOM_IS_GUEST_ROOM = _cf.CONF_ROOM_IS_GUEST_ROOM
CONF_MOTION_SENSORS = _cf.CONF_MOTION_SENSORS
CONF_OCCUPANCY_SENSORS = _cf.CONF_OCCUPANCY_SENSORS
CONF_MMWAVE_SENSORS = _cf.CONF_MMWAVE_SENSORS
CONF_TEMPERATURE_SENSOR = _cf.CONF_TEMPERATURE_SENSOR
CONF_HUMIDITY_SENSOR = _cf.CONF_HUMIDITY_SENSOR
CONF_ILLUMINANCE_SENSOR = _cf.CONF_ILLUMINANCE_SENSOR
CONF_DOOR_SENSORS = _cf.CONF_DOOR_SENSORS
CONF_LIGHTS = _cf.CONF_LIGHTS
CONF_FANS = _cf.CONF_FANS
CONF_COVERS = _cf.CONF_COVERS
CONF_HUMIDITY_FANS = _cf.CONF_HUMIDITY_FANS
CONF_ENTRY_TYPE = _cf.CONF_ENTRY_TYPE
CONF_ROOM_TYPE = _cf.CONF_ROOM_TYPE
CONF_OCCUPANCY_TIMEOUT = _cf.CONF_OCCUPANCY_TIMEOUT
CONF_OCCUPANCY_DEBOUNCE = _cf.CONF_OCCUPANCY_DEBOUNCE
CONF_SHARED_SPACE = _cf.CONF_SHARED_SPACE
CONF_SHARED_SPACE_AUTO_OFF_HOUR = _cf.CONF_SHARED_SPACE_AUTO_OFF_HOUR
CONF_SHARED_SPACE_WARNING = _cf.CONF_SHARED_SPACE_WARNING
CONF_HUMIDITY_FAN_SPIKE_ENABLED = _cf.CONF_HUMIDITY_FAN_SPIKE_ENABLED
CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED = _cf.CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED
CONF_INTEGRATION_ENTRY_ID = _cf.CONF_INTEGRATION_ENTRY_ID
ENTRY_TYPE_INTEGRATION = _cf.ENTRY_TYPE_INTEGRATION
ENTRY_TYPE_ROOM = _cf.ENTRY_TYPE_ROOM
ROOM_TYPE_BATHROOM = _cf.ROOM_TYPE_BATHROOM
ROOM_TYPE_BEDROOM = _cf.ROOM_TYPE_BEDROOM
ROOM_TYPE_GENERIC = _cf.ROOM_TYPE_GENERIC


# ---------------------------------------------------------------------------
# Registry fakes (F1: locally installed — do not read sys.modules)
# ---------------------------------------------------------------------------

def _reg_entry(entity_id, domain, *, device_id=None, area_id=None,
               disabled_by=None, hidden_by=None, entity_category=None,
               platform="mqtt", original_device_class=None, device_class=None):
    return SimpleNamespace(
        entity_id=entity_id, domain=domain, device_id=device_id,
        area_id=area_id, disabled_by=disabled_by, hidden_by=hidden_by,
        entity_category=entity_category, platform=platform,
        original_device_class=original_device_class, device_class=device_class,
    )


class _FakeEntReg:
    def __init__(self, entries):
        self.entities = {e.entity_id: e for e in entries}

    def async_get(self, eid):
        return self.entities.get(eid)


class _FakeDevReg:
    def __init__(self, devices=None):
        self._d = devices or {}

    def async_get(self, dev_id):
        return self._d.get(dev_id)


def _install_registries(entries, devices=None):
    ent_reg = _FakeEntReg(entries)
    dev_reg = _FakeDevReg(devices)
    for parent in ("homeassistant", "homeassistant.helpers"):
        if parent not in sys.modules:
            sys.modules[parent] = types.ModuleType(parent)
    for name, obj in (
        ("homeassistant.helpers.entity_registry", ent_reg),
        ("homeassistant.helpers.device_registry", dev_reg),
    ):
        mod = sys.modules.get(name) or types.ModuleType(name)
        mod.async_get = lambda hass, _o=obj: _o
        sys.modules[name] = mod
        parent = sys.modules["homeassistant.helpers"]
        setattr(parent, name.rsplit(".", 1)[-1], mod)
    return ent_reg, dev_reg


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# D3 — reshaped essentials chain
# ---------------------------------------------------------------------------

def test_essentials_chain_reaches_create_entry_in_4_steps():
    """5 form-submits: room_setup -> room_class -> sensors_confirm ->
    devices_confirm -> room_summary -> create_entry. (4 confirmed data
    steps + a final read-only recap.)"""
    _install_registries([
        _reg_entry("binary_sensor.motion_x", "binary_sensor", area_id="a1",
                   original_device_class="motion"),
    ])
    flow = _make_config_flow()

    r1 = _run(flow.async_step_room_setup(user_input={
        CONF_ROOM_NAME: "Test", CONF_ROOM_TYPE: ROOM_TYPE_BEDROOM,
        CONF_AREA_ID: "a1",
    }))
    assert r1["type"] == "form" and r1["step_id"] == "room_class"

    r2 = _run(flow.async_step_room_class(user_input={
        CONF_WET_ROOM: False, CONF_ROOM_IS_GUEST_ROOM: False,
    }))
    assert r2["type"] == "form" and r2["step_id"] == "sensors_confirm"

    r3 = _run(flow.async_step_sensors_confirm(user_input={
        CONF_MOTION_SENSORS: ["binary_sensor.motion_x"],
    }))
    assert r3["type"] == "form" and r3["step_id"] == "devices_confirm"

    r4 = _run(flow.async_step_devices_confirm(user_input={}))
    assert r4["type"] == "form" and r4["step_id"] == "room_summary"

    r5 = _run(flow.async_step_room_summary(user_input={}))
    assert r5["type"] == "create_entry"
    assert r5["data"][CONF_ROOM_NAME] == "Test"


def test_essentials_chain_confirm_writes_prefilled_values():
    """The auto-detected values that reach room_summary flow into the
    created entry."""
    _install_registries([
        _reg_entry("binary_sensor.motion_a", "binary_sensor", device_id="d1",
                   area_id="a1", original_device_class="motion"),
        _reg_entry("sensor.room_temp", "sensor", device_id="d2", area_id="a1",
                   original_device_class="temperature"),
        _reg_entry("light.main", "light", device_id="d3", area_id="a1"),
    ])
    flow = _make_config_flow()
    flow._data.update({
        CONF_ROOM_NAME: "Confirmed",
        CONF_ROOM_TYPE: ROOM_TYPE_BEDROOM,
        CONF_AREA_ID: "a1",
    })

    _run(flow.async_step_room_class(user_input={
        CONF_WET_ROOM: False, CONF_ROOM_IS_GUEST_ROOM: False,
    }))
    _run(flow.async_step_sensors_confirm(user_input={
        CONF_MOTION_SENSORS: ["binary_sensor.motion_a"],
        CONF_TEMPERATURE_SENSOR: "sensor.room_temp",
    }))
    _run(flow.async_step_devices_confirm(user_input={
        CONF_LIGHTS: ["light.main"],
    }))
    result = _run(flow.async_step_room_summary(user_input={}))
    assert result["type"] == "create_entry"
    data = result["data"]
    assert data[CONF_MOTION_SENSORS] == ["binary_sensor.motion_a"]
    assert data[CONF_TEMPERATURE_SENSOR] == "sensor.room_temp"
    assert data[CONF_LIGHTS] == ["light.main"]


def test_essentials_temperature_empty_selector_persists_empty_not_guess():
    """INV-2: clearing the pre-filled TEMPERATURE selector persists NOTHING
    (no guessed value written) — the operator explicitly said 'none'."""
    _install_registries([
        _reg_entry("binary_sensor.mo", "binary_sensor", area_id="a1",
                   original_device_class="motion"),
        _reg_entry("sensor.pref_temp", "sensor", area_id="a1",
                   original_device_class="temperature"),
    ])
    flow = _make_config_flow()
    flow._data.update({
        CONF_ROOM_NAME: "Empty Temp", CONF_ROOM_TYPE: ROOM_TYPE_GENERIC,
        CONF_AREA_ID: "a1",
    })
    # Operator submits only the required occupancy; TEMPERATURE cleared.
    _run(flow.async_step_sensors_confirm(user_input={
        CONF_MOTION_SENSORS: ["binary_sensor.mo"],
    }))
    _run(flow.async_step_devices_confirm(user_input={}))
    result = _run(flow.async_step_room_summary(user_input={}))
    assert result["type"] == "create_entry"
    data = result["data"]
    # INV-2: the pre-filled guess `sensor.pref_temp` MUST NOT be silently
    # persisted when the operator did not submit that key.
    assert data.get(CONF_TEMPERATURE_SENSOR) in (None, "", []), (
        f"INV-2 violated: temperature auto-committed to {data.get(CONF_TEMPERATURE_SENSOR)!r}"
    )


def test_essentials_room_setup_schema_no_tuning_constants():
    """D3: essentials room_setup form MUST NOT expose CONF_SHARED_SPACE*,
    CONF_OCCUPANCY_TIMEOUT, CONF_OCCUPANCY_DEBOUNCE."""
    _install_registries([])
    flow = _make_config_flow()
    result = _run(flow.async_step_room_setup())
    assert result["type"] == "form" and result["step_id"] == "room_setup"
    keys = {str(k) for k in result["data_schema"].schema}
    forbidden = {
        CONF_SHARED_SPACE, CONF_SHARED_SPACE_AUTO_OFF_HOUR,
        CONF_SHARED_SPACE_WARNING, CONF_OCCUPANCY_TIMEOUT,
        CONF_OCCUPANCY_DEBOUNCE,
    }
    leaked = keys & forbidden
    assert not leaked, f"tuning constants leaked onto essentials: {leaked}"


def test_no_tuning_constant_on_essentials_path():
    """D8/D3 anchor: enumerate schemas of ALL essentials steps
    (room_setup, room_class, sensors_confirm, devices_confirm,
    room_summary) — none may expose relocated tuning knobs."""
    _install_registries([])
    flow = _make_config_flow()
    banned = {
        CONF_SHARED_SPACE, CONF_SHARED_SPACE_AUTO_OFF_HOUR,
        CONF_SHARED_SPACE_WARNING, CONF_OCCUPANCY_TIMEOUT,
        CONF_OCCUPANCY_DEBOUNCE,
    }
    flow._data = {CONF_ROOM_NAME: "n", CONF_ROOM_TYPE: ROOM_TYPE_GENERIC}
    for step in ("async_step_room_setup", "async_step_room_class",
                 "async_step_sensors_confirm", "async_step_devices_confirm",
                 "async_step_room_summary"):
        result = _run(getattr(flow, step)())
        keys = {str(k) for k in result["data_schema"].schema}
        assert not (keys & banned), f"{step} leaks {keys & banned}"


def test_occupancy_timeout_auto_derived_from_room_type():
    """INV-3: OCCUPANCY_TIMEOUT is written on submit even though it's no
    longer a visible field — auto-derived from ROOM_TYPE_TIMEOUTS."""
    _install_registries([])
    flow = _make_config_flow()
    _run(flow.async_step_room_setup(user_input={
        CONF_ROOM_NAME: "T", CONF_ROOM_TYPE: ROOM_TYPE_BATHROOM,
    }))
    assert CONF_OCCUPANCY_TIMEOUT in flow._data, (
        "OCCUPANCY_TIMEOUT must be auto-derived even when field is hidden"
    )


# ---------------------------------------------------------------------------
# D4 — house->room ribbon (corrected mechanism)
# ---------------------------------------------------------------------------

class _FakeIntegrationHass:
    """Hass mock that records flow.async_init calls and can synthesize a
    House entry on demand (so room_summary can look it up)."""
    def __init__(self):
        self._states = {}
        self.states = MagicMock()
        self.states.get = lambda eid: self._states.get(eid)
        self.states.async_entity_ids = MagicMock(return_value=[])
        self.services = MagicMock()
        self.services.async_services = MagicMock(return_value={})
        self.services.async_call = AsyncMock(return_value=None)
        self.config_entries = MagicMock()
        self._entries: list = []
        self.config_entries.async_entries = MagicMock(
            side_effect=lambda *_a, **_k: list(self._entries)
        )
        self.flow_init_calls: list = []

        async def _async_init(domain, *, context=None, data=None):
            self.flow_init_calls.append({
                "domain": domain, "context": context, "data": data,
            })
            # Synthesize a House entry so the caller's lookup succeeds.
            if (data or {}).get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                self._entries.append(SimpleNamespace(
                    entry_id=f"house_{len(self._entries)}",
                    data=dict(data),
                    options={},
                    title="House",
                ))
            return {"type": "create_entry", "title": "House"}

        self.config_entries.flow = MagicMock()
        self.config_entries.flow.async_init = _async_init


def test_first_run_house_to_room_ribbon():
    """D4: first-run House is minted via
    `flow.async_init(source="integration_create")` from inside the room
    flow — NOT via a post-terminate menu route."""
    _install_registries([])
    hass = _FakeIntegrationHass()
    flow = _make_config_flow(hass=hass)
    # Simulate energy_setup finished with pending integration data.
    flow._integration_data = {"electricity_rate": 0.12}
    flow._energy_data = {}

    flow._data.update({
        CONF_ROOM_NAME: "First Room", CONF_ROOM_TYPE: ROOM_TYPE_BEDROOM,
    })
    result = _run(flow.async_step_room_summary(user_input={}))

    assert result["type"] == "create_entry"
    assert result["data"][CONF_ENTRY_TYPE] == ENTRY_TYPE_ROOM
    # The load-bearing invariant: House minted via flow.async_init with
    # source=integration_create.
    assert len(hass.flow_init_calls) == 1
    call = hass.flow_init_calls[0]
    assert call["context"] == {"source": "integration_create"}
    assert call["data"][CONF_ENTRY_TYPE] == ENTRY_TYPE_INTEGRATION
    # And the room was linked to it.
    assert result["data"][CONF_INTEGRATION_ENTRY_ID] is not None


def test_post_integration_setup_no_longer_creates_house_entry():
    """D4: `async_step_post_integration_setup` must not carry a House
    `async_create_entry` — the House-mint moved to room_summary."""
    src = inspect.getsource(
        _cf.UniversalRoomAutomationConfigFlow.async_step_post_integration_setup
    )
    # Strip docstring (which references the removed pattern in prose)
    import ast
    tree = ast.parse(src.lstrip())
    func = tree.body[0]
    if isinstance(func.body[0], ast.Expr) and isinstance(func.body[0].value, ast.Constant):
        body_nodes = func.body[1:]
    else:
        body_nodes = func.body
    body_src = "\n".join(ast.unparse(n) for n in body_nodes)
    assert "async_create_entry" not in body_src, (
        "D4 requires post_integration_setup to NOT create the House entry."
    )


def test_first_run_skip_rooms_still_creates_house():
    """D4 Skip branch: choosing 'skip rooms later' mints House via
    flow.async_init and aborts the flow — no room entry created."""
    _install_registries([])
    hass = _FakeIntegrationHass()
    flow = _make_config_flow(hass=hass)
    flow._integration_data = {"electricity_rate": 0.12}
    result = _run(flow.async_step_skip_rooms_later())
    assert result["type"] == "abort"
    # FIX-1 (Tier-3 fix-up): dedicated 'rooms_skipped' reason so the
    # translation surface can render reassuring copy (House installed,
    # add rooms later) instead of the generic 'not_supported' message.
    assert result["reason"] == "rooms_skipped"
    assert len(hass.flow_init_calls) == 1
    assert hass.flow_init_calls[0]["context"] == {"source": "integration_create"}


# ---------------------------------------------------------------------------
# D7 — Options-flow parity (differential INV-1 style)
# ---------------------------------------------------------------------------

# The set of keys D3 REMOVED from the essentials-visible schema (CONF_ZONE
# is NOT here per the 2026-09-12 operator correction — it stays on
# essentials conditionally).
_D3_DROPPED_ESSENTIALS_KEYS = (
    CONF_SHARED_SPACE,
    CONF_SHARED_SPACE_AUTO_OFF_HOUR,
    CONF_SHARED_SPACE_WARNING,
    CONF_OCCUPANCY_TIMEOUT,
    CONF_OCCUPANCY_DEBOUNCE,
)


def test_all_deferred_fields_reachable_in_options():
    """D7: every field D3 removed from essentials must still be reachable
    somewhere in the Options flow. Read the config_flow.py source from
    disk (mocked-module inspect can't find the class) and verify each
    deferred CONF value string appears inside the OptionsFlow class body.
    """
    import os
    _COMPONENT_DIR = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..",
        "custom_components", "universal_room_automation",
    ))
    with open(os.path.join(_COMPONENT_DIR, "config_flow.py")) as f:
        src = f.read()
    marker = "class UniversalRoomAutomationOptionsFlow"
    opt_start = src.index(marker)
    opt_src = src[opt_start:]
    # deferred keys are stored as string values on the class constants;
    # the CONF_* references appear inside Options steps.
    for key in ("CONF_SHARED_SPACE", "CONF_SHARED_SPACE_AUTO_OFF_HOUR",
                "CONF_SHARED_SPACE_WARNING", "CONF_OCCUPANCY_TIMEOUT",
                "CONF_OCCUPANCY_DEBOUNCE"):
        assert key in opt_src, (
            f"D7 parity: deferred key {key} not reachable in OptionsFlow — "
            f"capability lost."
        )


def test_bathroom_create_path_writes_full_expected_key_set():
    """T4 (Tier-3 fix-up) — INV-1 differential parity via reviewer-A
    fallback: encode the EXPECTED post-create key-set for a bathroom
    room shape and assert `data ∪ options` on the reshaped chain
    contains every key with its expected value.

    A true develop baseline is infeasible in the stub-env suite (develop
    requires the full HA runtime for options-flow reload), so we encode
    the pre-cycle expected keys explicitly. The set comes from:
      (a) fields the essentials chain still writes (room_setup + room_class
          + sensors_confirm + devices_confirm),
      (b) auto-derived INV-3 keys (OCCUPANCY_TIMEOUT from ROOM_TYPE),
      (c) ROOM_TYPE_FEATURE_DEFAULTS seed rows for bathroom (WET_ROOM,
          HUMIDITY_FAN_SPIKE_ENABLED, HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED
          — the P3 fix-up seed),
      (d) create-entry framing keys (ENTRY_TYPE, INTEGRATION_ENTRY_ID).

    The test MUST fail if any of these silently vanishes — the mutation
    drill (drop the ROOM_TYPE_FEATURE_DEFAULTS seed loop in room_summary
    or the OCCUPANCY_TIMEOUT auto-derive) makes it RED. Rename from
    the earlier `test_round_trip_existing_room_differential_parity`
    (which was NOT a true differential) to state what it checks.
    """
    _install_registries([
        _reg_entry("binary_sensor.mo", "binary_sensor", area_id="a1",
                   original_device_class="motion"),
    ])
    flow = _make_config_flow()
    _run(flow.async_step_room_setup(user_input={
        CONF_ROOM_NAME: "Bath", CONF_ROOM_TYPE: ROOM_TYPE_BATHROOM,
        CONF_AREA_ID: "a1",
    }))
    _run(flow.async_step_room_class(user_input={
        CONF_WET_ROOM: True, CONF_ROOM_IS_GUEST_ROOM: False,
    }))
    _run(flow.async_step_sensors_confirm(user_input={
        CONF_MOTION_SENSORS: ["binary_sensor.mo"],
    }))
    _run(flow.async_step_devices_confirm(user_input={}))
    result = _run(flow.async_step_room_summary(user_input={}))
    assert result["type"] == "create_entry"
    data = result["data"]
    options = {}  # Options-flow reload path is not exercisable in stub-env.
    effective = {**options, **data}

    # Expected keys + expected values (bathroom shape). Values ANCHOR each
    # site; a silent drop of any producer will fail on either presence or
    # value.
    expected = {
        # (a) essentials write-through
        CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
        CONF_ROOM_NAME: "Bath",
        CONF_ROOM_TYPE: ROOM_TYPE_BATHROOM,
        CONF_AREA_ID: "a1",
        CONF_MOTION_SENSORS: ["binary_sensor.mo"],
        # (b) INV-3 auto-derived
        # value comparison guarded by presence-only — the map is stable
        # across the cycle; presence is the discriminator.
        CONF_OCCUPANCY_TIMEOUT: None,  # sentinel: check presence only
        # (c) ROOM_TYPE_FEATURE_DEFAULTS seed rows
        CONF_WET_ROOM: True,
        CONF_HUMIDITY_FAN_SPIKE_ENABLED: True,
        CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED: True,
        # room_class writes GUEST_ROOM explicitly (False from user_input above)
        CONF_ROOM_IS_GUEST_ROOM: False,
    }

    missing = [k for k in expected if k not in effective]
    assert not missing, (
        f"T4 INV-1: pre-cycle keys silently vanished from create path: {missing}"
    )
    for k, want in expected.items():
        if want is None:
            continue  # presence-only anchor
        got = effective[k]
        assert got == want, (
            f"T4 INV-1: key {k} value drift — got {got!r}, expected {want!r}"
        )
