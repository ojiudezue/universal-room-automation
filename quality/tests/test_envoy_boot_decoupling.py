"""Tests for the EC Envoy boot-decoupling cycle.

Covers D1-D6 per docs/planning/PLANNING_ec_envoy_boot_decoupling.md.

D1 — validate_envoy_config now returns a three-way result:
    - hard fail (V0 missing field / V1 unparseable / registry-absent)
    - degraded   (registry-known but hass.states.get None or unavailable)
    - live       (registry-known + present + not unavailable)

D2 — __init__.py drops the silent `_envoy_validation_ok` gate; EC
registers unless the failure is V0/V1/registry-absent (hard).

D3 — Deferred re-validation at EVENT_HOMEASSISTANT_STARTED fires once,
raises the repair issue iff still hard-failing, clears stale issues
when the device recovers or is degraded.

D6 — RestoreEntity unavailable-coercion guard: when last_state.state is
not in ("on", "off"), skip restore and let the options/constructor
seed win. Applied to _ec_switch_factory and HVACDynamicPresetSwitch.

Test conventions (URA repo rules):
- sys.modules mocks: setdefault-only; never assign over shared module paths.
  Existing modules registered by sibling test files (e.g.
  test_envoy_auto_derive.py) are augmented via setattr on whichever module
  won setdefault, never overwritten.
- Prefer object.__new__ bare-instance technique to drive REAL methods
  over mock-heavy fakes (used for the RestoreEntity guard tests).
- Tests drive production code paths, not their own state mutations.
"""

import os
import sys
import types
from unittest.mock import MagicMock
import pytest

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code. setdefault-only.
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
    "homeassistant.helpers.issue_registry": {
        "async_create_issue": MagicMock(),
        "async_delete_issue": MagicMock(),
        "IssueSeverity": _mock_cls(),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": MagicMock(), "now": MagicMock(), "as_local": lambda dt: dt,
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

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        existing = sys.modules.get(name)
        if existing is None:
            sys.modules[name] = _mock_module(name, **attrs)
        else:
            # Augment the existing stub additively — never overwrite.
            for k, v in attrs.items():
                if not hasattr(existing, k):
                    setattr(existing, k, v)
    else:
        sys.modules.setdefault(name, attrs)


# ---------------------------------------------------------------------------
# Register URA package stubs (mirrors test_envoy_auto_derive.py)
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = sys.modules.get("custom_components")
if _cc is None:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
    sys.modules["custom_components"] = _cc

_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura = sys.modules.get("custom_components.universal_room_automation")
if _ura is None:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_ura_path]
    _ura.__package__ = "custom_components.universal_room_automation"
    sys.modules["custom_components.universal_room_automation"] = _ura

_ura_const = sys.modules.get("custom_components.universal_room_automation.const")
if _ura_const is None:
    _ura_const = types.ModuleType("custom_components.universal_room_automation.const")
    sys.modules["custom_components.universal_room_automation.const"] = _ura_const
if not hasattr(_ura_const, "DOMAIN"):
    _ura_const.DOMAIN = "universal_room_automation"
if not hasattr(_ura_const, "VERSION"):
    _ura_const.VERSION = "5.3.6-boot-decoupling"
if not hasattr(_ura_const, "BOOT_SETTLE_TIMEOUT_SECONDS"):
    _ura_const.BOOT_SETTLE_TIMEOUT_SECONDS = 60

_dc_name = "custom_components.universal_room_automation.domain_coordinators"
_dc = sys.modules.get(_dc_name)
if _dc is None:
    _dc = types.ModuleType(_dc_name)
    _dc.__path__ = [os.path.join(_ura_path, "domain_coordinators")]
    sys.modules[_dc_name] = _dc

_dc_signals_name = _dc_name + ".signals"
_dc_signals = sys.modules.get(_dc_signals_name)
if _dc_signals is None:
    _dc_signals = types.ModuleType(_dc_signals_name)
    sys.modules[_dc_signals_name] = _dc_signals
for sig in [
    "SIGNAL_ENERGY_CONSTRAINT", "SIGNAL_HOUSE_STATE_CHANGED",
    "SIGNAL_PERSON_ARRIVING", "SIGNAL_SAFETY_HAZARD",
    "SIGNAL_ENERGY_COORDINATOR_READY",
]:
    if not hasattr(_dc_signals, sig):
        setattr(_dc_signals, sig, f"ura_{sig.lower()}")
if not hasattr(_dc_signals, "EnergyConstraint"):
    _dc_signals.EnergyConstraint = MagicMock()


# ---------------------------------------------------------------------------
# Import production modules under test (after stub registration)
# ---------------------------------------------------------------------------

from custom_components.universal_room_automation.domain_coordinators.energy_const import (  # noqa: E402
    CONF_ENERGY_ENVOY_ENTITY,
    CONF_ENERGY_NET_POWER_ENTITY,
    CONF_ENERGY_SOLAR_ENTITY,
    CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY,
    CONF_ENERGY_LIFETIME_NET_IMPORT_ENTITY,
    ENVOY_DEGRADED_STATE_MISSING,
    ENVOY_DEGRADED_STATE_UNAVAILABLE,
    ENVOY_ERR_ENTITY_MISSING,
    ENVOY_ERR_INVALID_FORMAT,
    ENVOY_ERR_REQUIRED,
    ENVOY_REQUIRED_DERIVED_KEYS,
    derive_envoy_config,
    validate_envoy_config,
)


# ---------------------------------------------------------------------------
# Helpers — fake hass with both state machine and entity registry.
# ---------------------------------------------------------------------------


class _FakeEntReg:
    """Minimal entity registry stub."""
    def __init__(self, known):
        self._known = set(known)

    def async_get(self, entity_id):
        if entity_id in self._known:
            obj = MagicMock()
            obj.entity_id = entity_id
            return obj
        return None


def _make_hass(state_map=None, registry_known=None):
    """Construct a hass-like with state+registry observability.

    state_map: dict eid -> state-string for entries the state machine
        currently exposes. Entries NOT in the map → states.get returns None.
    registry_known: iterable of entity_ids that are in the entity registry.
        If None, defaults to the keys of state_map (live-only fixture).
    """
    state_map = state_map or {}
    if registry_known is None:
        registry_known = set(state_map.keys())

    hass = MagicMock()

    def _get_state(eid):
        if eid in state_map:
            s = MagicMock()
            s.state = state_map[eid]
            s.entity_id = eid
            return s
        return None
    hass.states.get = _get_state

    # Patch entity_registry.async_get(hass) → _FakeEntReg by re-assigning
    # the attribute on the helpers.entity_registry stub. C3 fix: callers
    # MUST restore the previous value via `_restore_er(prev)` in a
    # try/finally to prevent cross-test stub pollution that breaks
    # sibling test files under non-default collection order.
    ent_reg = _FakeEntReg(registry_known)
    er_mod = sys.modules["homeassistant.helpers.entity_registry"]
    hass._test_prev_er_async_get = getattr(er_mod, "async_get", None)
    er_mod.async_get = lambda _hass: ent_reg
    return hass


def _restore_er(hass) -> None:
    """C3 fix: restore the entity_registry.async_get stub captured by
    _make_hass. Safe-noop if hass was not built via _make_hass."""
    prev = getattr(hass, "_test_prev_er_async_get", None)
    if prev is None:
        return
    er_mod = sys.modules["homeassistant.helpers.entity_registry"]
    er_mod.async_get = prev


# ---------------------------------------------------------------------------
# C3 fix: autouse fixture saves+restores shared-module stubs that this file
# mutates (entity_registry.async_get, event.async_call_later,
# issue_registry.async_create_issue / async_delete_issue, bus.async_listen_once).
# Without this, running this file before its siblings poisons their shared
# stubs and breaks order-dependent tests (e.g.
# test_envoy_auto_derive::test_explicit_override_used_in_v4).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_shared_stubs():
    er_mod = sys.modules["homeassistant.helpers.entity_registry"]
    ev_mod = sys.modules["homeassistant.helpers.event"]
    ir_mod = sys.modules["homeassistant.helpers.issue_registry"]
    saved = {
        "er_async_get": getattr(er_mod, "async_get", None),
        "ev_async_call_later": getattr(ev_mod, "async_call_later", None),
        "ir_async_create_issue": getattr(ir_mod, "async_create_issue", None),
        "ir_async_delete_issue": getattr(ir_mod, "async_delete_issue", None),
    }
    try:
        yield
    finally:
        if saved["er_async_get"] is not None:
            er_mod.async_get = saved["er_async_get"]
        if saved["ev_async_call_later"] is not None:
            ev_mod.async_call_later = saved["ev_async_call_later"]
        if saved["ir_async_create_issue"] is not None:
            ir_mod.async_create_issue = saved["ir_async_create_issue"]
        if saved["ir_async_delete_issue"] is not None:
            ir_mod.async_delete_issue = saved["ir_async_delete_issue"]


# ---------------------------------------------------------------------------
# D1 — validate_envoy_config three-way contract
# ---------------------------------------------------------------------------

SERIAL = "482543015950"
ENVOY = f"sensor.envoy_{SERIAL}_battery_capacity"


def _all_derived_present():
    derived = derive_envoy_config(SERIAL)
    return {derived[k]: "ok" for k in ENVOY_REQUIRED_DERIVED_KEYS}


def _all_derived_registry_known():
    derived = derive_envoy_config(SERIAL)
    return [derived[k] for k in ENVOY_REQUIRED_DERIVED_KEYS]


class TestValidateEnvoyThreeWay:
    """D1 — validator three-way contract."""

    def test_validate_envoy_registry_known_state_missing(self):
        """Registered + states.get returns None → ok=True, degraded, reason=state_missing."""
        # State map is empty (state machine has nothing yet),
        # but registry knows the envoy + all required derived entities.
        registry = [ENVOY] + _all_derived_registry_known()
        hass = _make_hass(state_map={}, registry_known=registry)
        result = validate_envoy_config(
            hass, {CONF_ENERGY_ENVOY_ENTITY: ENVOY},
        )
        assert result["ok"] is True
        assert result["degraded"] is True
        assert result["degraded_reason"] == ENVOY_DEGRADED_STATE_MISSING
        assert result["entity_registry_known"] is True
        assert result["errors"] == {}

    def test_validate_envoy_registry_known_state_unavailable(self):
        """Registered + state=unavailable → ok=True, degraded, reason=state_unavailable."""
        present = {ENVOY: "unavailable"}
        present.update(_all_derived_present())
        registry = [ENVOY] + _all_derived_registry_known()
        hass = _make_hass(state_map=present, registry_known=registry)
        result = validate_envoy_config(
            hass, {CONF_ENERGY_ENVOY_ENTITY: ENVOY},
        )
        assert result["ok"] is True
        assert result["degraded"] is True
        assert result["degraded_reason"] == ENVOY_DEGRADED_STATE_UNAVAILABLE
        assert result["entity_registry_known"] is True

    def test_validate_envoy_registry_absent(self):
        """Not in registry → hard fail, entity_registry_known=False."""
        hass = _make_hass(state_map={}, registry_known=[])
        result = validate_envoy_config(
            hass, {CONF_ENERGY_ENVOY_ENTITY: ENVOY},
        )
        assert result["ok"] is False
        assert result["entity_registry_known"] is False
        assert result["errors"][CONF_ENERGY_ENVOY_ENTITY] == ENVOY_ERR_ENTITY_MISSING

    def test_validate_envoy_live_pass(self):
        """Registered + state ok + derived present → live."""
        present = {ENVOY: "ok"}
        present.update(_all_derived_present())
        registry = [ENVOY] + _all_derived_registry_known()
        hass = _make_hass(state_map=present, registry_known=registry)
        result = validate_envoy_config(
            hass, {CONF_ENERGY_ENVOY_ENTITY: ENVOY},
        )
        assert result["ok"] is True
        assert result["degraded"] is False
        assert result["degraded_reason"] is None
        assert result["entity_registry_known"] is True
        assert result["serial"] == SERIAL

    def test_validate_envoy_v0_required_still_hard_fails(self):
        hass = _make_hass()
        result = validate_envoy_config(hass, {})
        assert result["ok"] is False
        assert result["errors"][CONF_ENERGY_ENVOY_ENTITY] == ENVOY_ERR_REQUIRED
        assert result["entity_registry_known"] is False

    def test_validate_envoy_v1_invalid_serial_still_hard_fails(self):
        hass = _make_hass()
        result = validate_envoy_config(
            hass, {CONF_ENERGY_ENVOY_ENTITY: "sensor.not_an_envoy"},
        )
        assert result["ok"] is False
        assert result["errors"][CONF_ENERGY_ENVOY_ENTITY] == ENVOY_ERR_INVALID_FORMAT


# ---------------------------------------------------------------------------
# D5 inventory tests — the plan-numbered cases.
# ---------------------------------------------------------------------------


class TestPlanInventory:
    """Plan-inventory tests 1-10 (D1+D2+D3 covered; D6 is its own class)."""

    def test_envoy_late_boot_registered_state_missing(self):
        """Test 1 — registry-known + state=None → degraded, EC would register."""
        registry = [ENVOY] + _all_derived_registry_known()
        hass = _make_hass(state_map={}, registry_known=registry)
        result = validate_envoy_config(
            hass, {CONF_ENERGY_ENVOY_ENTITY: ENVOY},
        )
        # EC registration gate in __init__.py is now `not _envoy_hard_fail`.
        # ok=True implies _envoy_hard_fail=False → EC registers.
        assert result["ok"] is True
        assert result["degraded"] is True
        # Confirm production gate logic explicitly (mirror of __init__.py).
        envoy_hard_fail = not result["ok"]
        assert envoy_hard_fail is False

    def test_envoy_late_boot_registered_state_unavailable(self):
        """Test 2 — registry-known + unavailable → degraded, EC would register."""
        present = {ENVOY: "unavailable"}
        present.update(_all_derived_present())
        registry = [ENVOY] + _all_derived_registry_known()
        hass = _make_hass(state_map=present, registry_known=registry)
        result = validate_envoy_config(
            hass, {CONF_ENERGY_ENVOY_ENTITY: ENVOY},
        )
        assert result["ok"] is True
        assert result["degraded"] is True
        envoy_hard_fail = not result["ok"]
        assert envoy_hard_fail is False

    def test_envoy_absent_not_in_registry(self):
        """Test 3 — registry-absent → hard fail; gate would BLOCK EC."""
        hass = _make_hass(state_map={}, registry_known=[])
        result = validate_envoy_config(
            hass, {CONF_ENERGY_ENVOY_ENTITY: ENVOY},
        )
        assert result["ok"] is False
        envoy_hard_fail = not result["ok"]
        assert envoy_hard_fail is True
        assert result["entity_registry_known"] is False

    def test_envoy_v0_no_entity_configured(self):
        """Test 4 — V0 hard fail; gate blocks EC; repair issue would be raised immediately."""
        hass = _make_hass()
        result = validate_envoy_config(hass, {})
        envoy_hard_fail = not result["ok"]
        assert envoy_hard_fail is True
        assert result["errors"][CONF_ENERGY_ENVOY_ENTITY] == ENVOY_ERR_REQUIRED

    def test_envoy_v1_unparseable_serial(self):
        """Test 5 — V1 hard fail; gate blocks EC."""
        hass = _make_hass()
        result = validate_envoy_config(
            hass, {CONF_ENERGY_ENVOY_ENTITY: "sensor.not_real"},
        )
        envoy_hard_fail = not result["ok"]
        assert envoy_hard_fail is True

    def test_runtime_blip_holds_state_path_untouched(self):
        """Test 6 — confirm runtime None-handling pathway is reachable.

        Drives the EC's existing tolerance: when validate passes degraded,
        the entity_config dict is still wired (key present), so downstream
        EC code can call hass.states.get and get None, which energy_battery.py
        handles. We don't import energy.py here (heavy deps); we assert the
        contract that allows it to run.
        """
        # No state present, but registry-known: degraded path.
        registry = [ENVOY] + _all_derived_registry_known()
        hass = _make_hass(state_map={}, registry_known=registry)
        cfg = {CONF_ENERGY_ENVOY_ENTITY: ENVOY}
        result = validate_envoy_config(hass, cfg)
        assert result["ok"] is True
        # The resolved derived entities are populated so EC's
        # entity_config contains the keys it will hass.states.get(...) at runtime.
        assert CONF_ENERGY_NET_POWER_ENTITY in result["resolved"]
        assert CONF_ENERGY_SOLAR_ENTITY in result["resolved"]
        # And hass.states.get on them returns None — runtime must handle.
        assert hass.states.get(result["resolved"][CONF_ENERGY_NET_POWER_ENTITY]) is None

    def test_hvac_net_power_entity_passed_when_envoy_degraded(self):
        """Test 10 — when validation is ok=True (incl. degraded),
        HVAC receives the net_power_entity_id (not None).

        Mirrors the production gate in __init__.py:
            if not _envoy_hard_fail:
                _hvac_net_power_entity = energy_entity_config.get(NET_POWER)
        """
        registry = [ENVOY] + _all_derived_registry_known()
        hass = _make_hass(state_map={}, registry_known=registry)
        result = validate_envoy_config(
            hass, {CONF_ENERGY_ENVOY_ENTITY: ENVOY},
        )
        envoy_hard_fail = not result["ok"]
        assert envoy_hard_fail is False
        # The validator resolves the derived net_power entity.
        net_power_eid = result["resolved"].get(CONF_ENERGY_NET_POWER_ENTITY)
        assert net_power_eid is not None
        assert SERIAL in net_power_eid


# ---------------------------------------------------------------------------
# D3 — deferred re-validation listener semantics.
# We exercise the helper directly. The helper is module-level and pure-ish
# but the hass.bus / async_call_later are heavily mocked. We assert the
# wiring (one-shot, idempotent, unload-tracked) and the post-fire behavior.
# ---------------------------------------------------------------------------


def _make_entry(entry_id="cm_entry_001"):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.async_on_unload = MagicMock()
    return entry


class TestDeferredRevalidation:
    """D3 — _schedule_envoy_revalidation."""

    def _import_helper(self):
        # __init__.py is enormous (4000+ lines) and triggers the full
        # coordinator import tree. We avoid that by extracting just the
        # _schedule_envoy_revalidation function source from disk and
        # exec'ing it in an isolated namespace seeded with the stubs we
        # already have. The function calls validate_envoy_config /
        # async_call_later / issue_registry — all already mocked above.
        init_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation", "__init__.py",
        )
        with open(init_path, "r") as fh:
            src = fh.read()
        marker = "def _schedule_envoy_revalidation"
        idx = src.index(marker)
        # Find end: next top-level `def ` or `async def ` at column 0.
        tail = src[idx:]
        end = len(tail)
        for needle in ("\nasync def ", "\ndef ", "\nclass "):
            p = tail.find(needle, 1)
            if 0 < p < end:
                end = p
        fn_src = tail[:end]

        # Build the exec namespace. Replace the `from .const import DOMAIN`
        # etc. style imports inside the function body by pre-injecting
        # `DOMAIN` etc. into the namespace. The function does the imports
        # locally so we just need the target modules already in sys.modules.
        # `callback` must be in the exec namespace — the helper's nested
        # _on_ha_started / _on_failsafe_timeout carry @callback decorators
        # (A1/B1 fix). Use identity so the decoration is a no-op in tests.
        ns = {
            "_LOGGER": MagicMock(),
            "HomeAssistant": MagicMock,
            "ConfigEntry": MagicMock,
            "DOMAIN": "universal_room_automation",
            "callback": lambda fn: fn,
        }
        # Patch the relative imports the function does. The function uses
        # `from .const import BOOT_SETTLE_TIMEOUT_SECONDS` and
        # `from .domain_coordinators.energy_const import validate_envoy_config`.
        # We need those packages to resolve as already-stubbed modules.
        # They are stubbed (`custom_components.universal_room_automation.const`),
        # but the function's `from .` syntax requires execution inside a
        # package context. Easiest fix: rewrite the two `from .` lines to
        # absolute imports for the exec.
        fn_src_for_exec = fn_src.replace(
            "from .const import",
            "from custom_components.universal_room_automation.const import",
        ).replace(
            "from .domain_coordinators.energy_const import",
            "from custom_components.universal_room_automation.domain_coordinators.energy_const import",
        )
        exec(compile(fn_src_for_exec, "<_schedule_envoy_revalidation>", "exec"), ns)
        return ns["_schedule_envoy_revalidation"]

    def test_revalidation_clears_stale_issue_when_envoy_recovers(self):
        """Booted with stale repair issue; deferred run sees live → clear."""
        schedule = self._import_helper()
        # State now LIVE (envoy + derived all good).
        present = {ENVOY: "ok"}
        present.update(_all_derived_present())
        registry = [ENVOY] + _all_derived_registry_known()
        hass = _make_hass(state_map=present, registry_known=registry)
        # Force not-running so the cold-boot path fires.
        hass.is_running = False
        # async_listen_once must be callable and return an unsub.
        captured_started_cb = {}
        def _listen_once(event, cb):
            captured_started_cb["cb"] = cb
            return MagicMock()
        hass.bus.async_listen_once = _listen_once
        entry = _make_entry()

        # Patch issue_registry to observe calls.
        ir = sys.modules["homeassistant.helpers.issue_registry"]
        ir.async_create_issue = MagicMock()
        ir.async_delete_issue = MagicMock()

        schedule(hass, entry, {CONF_ENERGY_ENVOY_ENTITY: ENVOY})
        # Simulate HA_STARTED firing.
        assert "cb" in captured_started_cb, "listener was not registered"
        captured_started_cb["cb"](MagicMock())  # fire event

        # Live → stale issue cleared, no new create.
        assert ir.async_delete_issue.called
        assert not ir.async_create_issue.called

    def test_revalidation_raises_issue_when_envoy_genuinely_absent(self):
        """Registry-absent at the deferred fire → raise repair issue."""
        schedule = self._import_helper()
        hass = _make_hass(state_map={}, registry_known=[])
        hass.is_running = False
        captured = {}
        def _listen_once(event, cb):
            captured["cb"] = cb
            return MagicMock()
        hass.bus.async_listen_once = _listen_once
        entry = _make_entry()

        ir = sys.modules["homeassistant.helpers.issue_registry"]
        ir.async_create_issue = MagicMock()
        ir.async_delete_issue = MagicMock()

        schedule(hass, entry, {CONF_ENERGY_ENVOY_ENTITY: ENVOY})
        captured["cb"](MagicMock())

        assert ir.async_create_issue.called
        # Issue id is entry-scoped.
        args, kwargs = ir.async_create_issue.call_args
        assert any(
            "energy_envoy_invalid_cm_entry_001" in str(a)
            for a in list(args) + list(kwargs.values())
        )

    def test_revalidation_does_not_double_fire_after_unload(self):
        """If both HA-started AND failsafe-timeout fire, revalidation
        runs only ONCE due to the internal `fired` latch."""
        schedule = self._import_helper()
        registry = [ENVOY] + _all_derived_registry_known()
        present = {ENVOY: "ok"}
        present.update(_all_derived_present())
        hass = _make_hass(state_map=present, registry_known=registry)
        hass.is_running = False

        captured = {"started": None, "timeout": None}
        def _listen_once(event, cb):
            captured["started"] = cb
            return MagicMock()
        hass.bus.async_listen_once = _listen_once

        ev_mod = sys.modules["homeassistant.helpers.event"]
        def _async_call_later(_hass, _delay, cb):
            captured["timeout"] = cb
            return MagicMock()
        ev_mod.async_call_later = _async_call_later

        entry = _make_entry()
        ir = sys.modules["homeassistant.helpers.issue_registry"]
        ir.async_create_issue = MagicMock()
        ir.async_delete_issue = MagicMock()

        schedule(hass, entry, {CONF_ENERGY_ENVOY_ENTITY: ENVOY})
        # Fire both — second should be a no-op due to fired latch.
        captured["started"](MagicMock())
        first_delete_count = ir.async_delete_issue.call_count
        captured["timeout"](MagicMock())
        assert ir.async_delete_issue.call_count == first_delete_count, (
            "deferred re-validation must be one-shot"
        )

        # And async_on_unload was wired for both unsubs.
        assert entry.async_on_unload.call_count >= 2


# ---------------------------------------------------------------------------
# D6 — RestoreEntity unavailable-coercion guard tests.
# Uses object.__new__ bare-instance to drive the REAL async_added_to_hass.
# ---------------------------------------------------------------------------


class _FakeLastState:
    def __init__(self, state):
        self.state = state


class _FakeEnergy:
    """Tiny coordinator-stand-in used to detect a clobbering setattr."""
    grid_arbitrage = True  # options-seeded ON
    dynamic_preset_enabled = True  # default ON

    def __init__(self):
        self._notified_count = 0
        self._registered_count = 0

    def notify_sub_switch_restore_complete(self):
        # Production code calls this on a successful restore.
        self._notified = True
        self._notified_count += 1

    def register_sub_switch_for_restore_accounting(self, _unique_suffix):
        self._registered_count += 1


class _FakeHass:
    """Minimal hass for D6 entity tests."""
    def __init__(self, energy=None):
        self.data = {
            "universal_room_automation": {
                "coordinator_manager": MagicMock(
                    coordinators={"energy": energy} if energy is not None else {}
                ),
            },
        }


class _LastStateProvider:
    """Mixin that lets us shim async_get_last_state on a real entity."""
    def __init__(self, last_state):
        self._last_state_value = last_state

    async def async_get_last_state(self):
        return self._last_state_value


import asyncio  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# Read switch.py source from disk (avoid heavy HA import chain).
_SWITCH_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation", "switch.py",
)
with open(_SWITCH_PATH, "r") as _f:
    _SWITCH_SRC_FULL = _f.read()


def _extract_function_source(src: str, marker: str) -> str:
    """Extract a contiguous slice of src starting at `marker`. Used to
    isolate _ec_switch_factory's inner async_added_to_hass and
    HVACDynamicPresetSwitch's async_added_to_hass for the guard checks.

    Returns up to the next top-level class or `def ` at column 0/4 after
    the marker, to avoid bleeding into adjacent functions.
    """
    idx = src.index(marker)
    tail = src[idx:]
    # Stop at the next class definition at module column 0.
    next_class = tail.find("\nclass ")
    if next_class > 0:
        tail = tail[:next_class]
    return tail


_SWITCH_SRC = _SWITCH_SRC_FULL  # used by D6 tests; full file is fine.


class TestRestorePoisoningGuards:
    """D6 — last_state.state not in ('on','off') must skip restore.

    C2 fix: behavioral tests that drive the REAL `async_added_to_hass`
    extracted from switch.py via the same exec-extraction technique the
    D3 tests use. Each test instantiates a bare object and runs the
    coroutine to verify:
      - the coordinator attr is NOT clobbered on skip,
      - `_deferred_restore` is NOT left True (would defeat the fix),
      - `notify_sub_switch_restore_complete` IS called on skip (ties C1).
    """

    def _extract_factory_async_added(self) -> str:
        """Extract the REAL async_added_to_hass body from _ec_switch_factory.

        Returns Python source for a top-level async function
        `_ec_async_added(self)` equivalent to the inner method:
          - closure refs (`unique_suffix` / `attr_name`) → self attrs
          - `await super().async_added_to_hass()` → no-op coroutine
            attached on `self`, since `super()` resolution fails outside
            a real class hierarchy
          - relative imports → absolute (no package context in exec)
        """
        marker = "        async def async_added_to_hass(self):"
        idx = _SWITCH_SRC_FULL.index(marker)
        tail = _SWITCH_SRC_FULL[idx:]
        # Stop at the END of THIS method only — i.e. at the next sibling
        # method header at column 8 (`        @callback` or `        def `
        # or `        async def ` AFTER the first line). Earlier versions
        # ran past the method end and pulled in `_handle_ec_ready` etc.,
        # which produced unindent errors when the body was wrapped in a
        # top-level `async def`.
        first_newline = tail.index("\n") + 1
        rest = tail[first_newline:]
        end_candidates = []
        for needle in (
            "\n        @callback\n",
            "\n        def ",
            "\n        async def ",
            "\n        @property\n",
        ):
            p = rest.find(needle)
            if p >= 0:
                end_candidates.append(first_newline + p)
        end = min(end_candidates) if end_candidates else len(tail)
        body = tail[:end]
        lines = body.splitlines()
        # Drop the `async def` line; dedent body by 4 to fit a top-level def.
        body_lines = [
            (line[4:] if line.startswith("    ") else line)
            for line in lines[1:]
        ]
        rewritten = "\n".join(body_lines)
        # Closure refs → bound attrs on the bare self.
        rewritten = rewritten.replace("unique_suffix", "self._unique_suffix")
        rewritten = rewritten.replace("attr_name", "self._attr_name_for_test")
        # super() not callable outside a class — route through a self method.
        rewritten = rewritten.replace(
            "await super().async_added_to_hass()",
            "await self._super_async_added_to_hass()",
        )
        # Inline-replace imports rather than rewriting them as absolute
        # imports — the sibling test_envoy_auto_derive.py imports the real
        # signals module without `__file__`, which causes "unknown
        # location" import failures when both files are collected. Robust:
        # define the signal constant inline; stub the dispatcher.
        rewritten = rewritten.replace(
            "from .domain_coordinators.signals import "
            "SIGNAL_ENERGY_COORDINATOR_READY",
            "SIGNAL_ENERGY_COORDINATOR_READY = "
            "'ura_signal_energy_coordinator_ready'",
        )
        rewritten = rewritten.replace(
            "from homeassistant.helpers.dispatcher import "
            "async_dispatcher_connect",
            "async_dispatcher_connect = lambda *a, **kw: (lambda: None)",
        )
        wrapper = "async def _ec_async_added(self):\n" + rewritten + "\n"
        return wrapper

    def _extract_hvac_async_added(self) -> str:
        """Extract REAL HVACDynamicPresetSwitch.async_added_to_hass body."""
        class_idx = _SWITCH_SRC_FULL.index("class HVACDynamicPresetSwitch")
        sub = _SWITCH_SRC_FULL[class_idx:]
        marker = "    async def async_added_to_hass(self) -> None:"
        m_idx = sub.index(marker)
        tail = sub[m_idx:]
        end_candidates = []
        for needle in (
            "\n    def _fire_default_on_nm_notification",
            "\n    @callback\n    def _handle_ec_ready",
        ):
            p = tail.find(needle)
            if p > 0:
                end_candidates.append(p)
        end = min(end_candidates) if end_candidates else len(tail)
        body = tail[:end]
        lines = body.splitlines()
        # Drop `async def` line; dedent 4 spaces.
        body_lines = [
            (line[4:] if line.startswith("    ") else line)
            for line in lines[1:]
        ]
        rewritten = "\n".join(body_lines)
        rewritten = rewritten.replace(
            "await super().async_added_to_hass()",
            "await self._super_async_added_to_hass()",
        )
        # See _extract_factory_async_added for the cross-file pollution
        # rationale behind inline import stubbing.
        rewritten = rewritten.replace(
            "from .domain_coordinators.signals import "
            "SIGNAL_ENERGY_COORDINATOR_READY",
            "SIGNAL_ENERGY_COORDINATOR_READY = "
            "'ura_signal_energy_coordinator_ready'",
        )
        rewritten = rewritten.replace(
            "from homeassistant.helpers.dispatcher import "
            "async_dispatcher_connect",
            "async_dispatcher_connect = lambda *a, **kw: (lambda: None)",
        )
        wrapper = "async def _hvac_async_added(self):\n" + rewritten + "\n"
        return wrapper

    def _make_bare(self, last_state_value, energy, *, is_hvac=False):
        """Construct a minimal `self` stand-in supplying every attribute /
        method the extracted production body touches. Returns (bare, fn)
        where fn is the executed top-level async function.
        """
        ns = {
            "_LOGGER": MagicMock(),
            "callback": lambda fn: fn,
            "async_call_later": lambda *a, **kw: MagicMock(),
            "DOMAIN": "universal_room_automation",
        }
        src = (
            self._extract_hvac_async_added()
            if is_hvac
            else self._extract_factory_async_added()
        )
        exec(compile(src, "<extracted>", "exec"), ns)
        fn = ns["_hvac_async_added" if is_hvac else "_ec_async_added"]

        # Capture notify / register accounting + writes for assertions.
        write_log = []
        nm_calls = []

        class _Bare:
            async def async_get_last_state(self):
                return last_state_value

            def async_write_ha_state(self):
                write_log.append("write")

            async def _super_async_added_to_hass(self):
                pass

            def async_on_remove(self, _u):
                pass

            def _get_energy(self):
                return energy

            def _register_for_restore_accounting(self):
                if energy is not None:
                    try:
                        energy.register_sub_switch_for_restore_accounting(
                            getattr(self, "_unique_suffix",
                                    "hvac_dynamic_preset"),
                        )
                    except Exception:
                        pass

            def _fire_default_on_nm_notification(self):
                nm_calls.append("nm")

            def _handle_ec_ready(self):
                # Referenced by async_dispatcher_connect in both extracted
                # bodies; the dispatcher is stubbed to a no-op lambda so
                # this only needs to be a present attribute.
                pass

            def _retry_restore(self, _now=None):
                pass

        bare = _Bare()
        bare._unique_suffix = (
            "hvac_dynamic_preset" if is_hvac else "grid_arbitrage"
        )
        bare._attr_name_for_test = (
            "dynamic_preset_enabled" if is_hvac else "grid_arbitrage"
        )
        bare._default = True
        bare._deferred_restore = False
        bare._deferred_value = True
        bare._default_flip_pending_nm = False
        bare._retry_index = 0
        bare._RETRY_DELAYS_S = [1, 2, 3]
        bare.hass = _FakeHass(energy=energy)
        bare._write_log = write_log
        bare._nm_calls = nm_calls
        return bare, fn

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    # ----- Test 11: unavailable skip preserves coordinator attr + notifies.
    def test_ec_sub_switch_restore_skips_unavailable_last_state(self):
        """Drives the REAL extracted _ec_switch_factory async_added_to_hass
        body. Bug Class #52 skip path: coordinator attr untouched + notify.
        """
        energy = _FakeEnergy()
        energy.grid_arbitrage = True  # options seed
        bare, fn = self._make_bare(
            _FakeLastState("unavailable"), energy,
        )
        self._run(fn(bare))
        # Coordinator attr UNCHANGED — production guard prevented False-clobber.
        assert energy.grid_arbitrage is True
        # C1 — notify fired on skip so ECSubSwitchesSyncedSensor converges.
        assert energy._notified_count == 1

    # ----- Test 12: unknown skip preserves coordinator attr + notifies.
    def test_ec_sub_switch_restore_skips_unknown_last_state(self):
        energy = _FakeEnergy()
        energy.grid_arbitrage = True
        bare, fn = self._make_bare(_FakeLastState("unknown"), energy)
        self._run(fn(bare))
        assert energy.grid_arbitrage is True
        assert energy._notified_count == 1

    # ----- Test 13: 'on'/'off' apply path drives REAL production code.
    def test_ec_sub_switch_restore_applies_off_state(self):
        """Valid 'off' last_state must be APPLIED to the coordinator attr."""
        energy = _FakeEnergy()
        energy.grid_arbitrage = True
        bare, fn = self._make_bare(_FakeLastState("off"), energy)
        self._run(fn(bare))
        assert energy.grid_arbitrage is False
        assert energy._notified_count == 1

    def test_ec_sub_switch_restore_applies_on_state(self):
        """Valid 'on' last_state must apply True (regression of apply path)."""
        energy = _FakeEnergy()
        energy.grid_arbitrage = False
        bare, fn = self._make_bare(_FakeLastState("on"), energy)
        self._run(fn(bare))
        assert energy.grid_arbitrage is True
        assert energy._notified_count == 1

    # ----- Test 14: HVACDynamicPresetSwitch skip preserves default + notifies.
    def test_hvac_dynamic_preset_switch_restore_skips_unavailable_last_state(
        self,
    ):
        energy = _FakeEnergy()
        energy.dynamic_preset_enabled = True  # default ON
        bare, fn = self._make_bare(
            _FakeLastState("unavailable"), energy, is_hvac=True,
        )
        self._run(fn(bare))
        assert energy.dynamic_preset_enabled is True
        assert energy._notified_count == 1

    # ----- Test 15: first-install (last_state is None) → no clobber + notify
    # symmetric with skip path (D2 fix-up — counter must not leak).
    def test_ec_sub_switch_first_install_no_last_state_unchanged(self):
        """Review D D2: registration/notify must be SYMMETRIC on first-install.
        The factory's `async_added_to_hass` calls
        `_register_for_restore_accounting()` BEFORE the `last_state is None`
        check, so the first-install branch must notify or the EC pending
        counter is left >0 forever. This drives the REAL extracted body
        and asserts symmetry: register_count == notify_count.
        """
        energy = _FakeEnergy()
        energy.grid_arbitrage = True  # constructor seed
        bare, fn = self._make_bare(None, energy)
        self._run(fn(bare))
        # Seed UNCHANGED (no setattr in first-install branch).
        assert energy.grid_arbitrage is True
        # D2 SYMMETRY — register and notify must balance, otherwise the
        # EC pending-restore counter is stuck >0 and ECSubSwitchesSynced
        # PROBLEM sensor sticks True until restart on fresh installs.
        assert energy._registered_count == 1, "expected one register call"
        assert energy._notified_count == 1, (
            "first-install must notify to balance the register call "
            "(D2 fix — register/notify symmetry)"
        )

    def test_hvac_dynamic_preset_first_install_register_notify_symmetric(self):
        """Review D D2 sibling: HVACDynamicPresetSwitch first-install path."""
        energy = _FakeEnergy()
        energy.dynamic_preset_enabled = False  # will be flipped to True
        bare, fn = self._make_bare(None, energy, is_hvac=True)
        self._run(fn(bare))
        # Default-ON applied.
        assert energy.dynamic_preset_enabled is True
        # Symmetric register / notify.
        assert energy._registered_count == 1
        assert energy._notified_count == 1
        # NM notification fired exactly once for the default-flip.
        assert bare._nm_calls == ["nm"]
