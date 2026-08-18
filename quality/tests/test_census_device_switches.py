"""CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 (2026-08-18).

Planning doc:
`docs/planning/PLANNING_census_toggles_to_device_switches.md`.

Tier 2-DB. INV-1: for each of `CONF_FACE_RECOGNITION_ENABLED` and
`CONF_EGRESS_IDENTITY_ENABLED`, switch `is_on` <=> `entry.options[KEY]`
<=> every consumer's read, immediately after a toggle (via signal for
the cached consumer; fresh-read for egress) AND across restart, WITHOUT
a parent-entry reload.

Style: AST-slice + LIGHT-MOCK (matches `test_reload_watchdog_hazard.py`
and `test_part2_ec_hc_writeback.py`). We import `const.py` directly by
file path (its imports are stdlib only) and exec only the pieces of
`switch.py` / `__init__.py` we exercise, so tests don't need the real
HA runtime.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"


# ---------------------------------------------------------------------------
# Load const.py directly (stdlib-only imports) so we don't pull in the
# full `custom_components.universal_room_automation` package (which
# imports homeassistant.const at package-init time).
# ---------------------------------------------------------------------------

def _load_const_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ura_const_under_test", PKG / "const.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


CONST = _load_const_module()


# ---------------------------------------------------------------------------
# AST-slice: pull the pieces of __init__.py + switch.py we test into
# clean namespaces without executing the real HA imports.
# ---------------------------------------------------------------------------

INIT_SRC = (PKG / "__init__.py").read_text()
SWITCH_SRC = (PKG / "switch.py").read_text()
TV_SRC = (PKG / "transit_validator.py").read_text()
PRESENCE_SRC = (PKG / "domain_coordinators" / "presence.py").read_text()
CENSUS_SRC = (PKG / "camera_census.py").read_text()
CONFIG_FLOW_SRC = (PKG / "config_flow.py").read_text()


def _slice_names_and_funcs(src: str, names: set[str], funcs: set[str]) -> ast.Module:
    tree = ast.parse(src)
    body = []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            t = getattr(node.target, "id", None)
            if t in names:
                body.append(node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in names:
                    body.append(node)
                    break
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.ClassDef)):
            if node.name in funcs:
                body.append(node)
    return ast.Module(body=body, type_ignores=[])


# ---------------------------------------------------------------------------
# D0 / D1 — const-level anchors
# ---------------------------------------------------------------------------

def test_d1_signal_constant_defined():
    assert CONST.SIGNAL_URA_FACE_RECOGNITION_CHANGED == "ura_face_recognition_changed"


def test_d0_defaults_flipped_on():
    assert CONST.DEFAULT_FACE_RECOGNITION_ENABLED is True
    assert CONST.DEFAULT_EGRESS_IDENTITY_ENABLED is True


def test_d0_allowlist_contains_new_keys():
    """AST-slice the frozenset literal from __init__.py."""
    mod = _slice_names_and_funcs(
        INIT_SRC,
        names={"INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS",
               "_INTEGRATION_KEY_SIGNAL_TABLE"},
        funcs=set(),
    )
    ns = {
        "frozenset": frozenset,
        "dict": dict,
        "tuple": tuple,
        "CONF_CAMERA_PERSON_ENTITIES": "camera_person_entities",
        "CONF_FACE_RECOGNITION_ENABLED": "face_recognition_enabled",
        "CONF_EGRESS_IDENTITY_ENABLED": "egress_identity_enabled",
        "SIGNAL_URA_TRANSIT_CONFIG_CHANGED": "ura_transit_config_changed",
        "SIGNAL_URA_FACE_RECOGNITION_CHANGED": "ura_face_recognition_changed",
    }
    exec(compile(mod, str(PKG / "__init__.py"), "exec"), ns)
    allow = ns["INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS"]
    assert "face_recognition_enabled" in allow
    assert "egress_identity_enabled" in allow
    assert "camera_person_entities" in allow


def test_d0_signal_table_has_face_recog_only():
    mod = _slice_names_and_funcs(
        INIT_SRC,
        names={"INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS",
               "_INTEGRATION_KEY_SIGNAL_TABLE"},
        funcs=set(),
    )
    ns = {
        "frozenset": frozenset,
        "CONF_CAMERA_PERSON_ENTITIES": "camera_person_entities",
        "CONF_FACE_RECOGNITION_ENABLED": "face_recognition_enabled",
        "CONF_EGRESS_IDENTITY_ENABLED": "egress_identity_enabled",
        "SIGNAL_URA_TRANSIT_CONFIG_CHANGED": "ura_transit_config_changed",
        "SIGNAL_URA_FACE_RECOGNITION_CHANGED": "ura_face_recognition_changed",
    }
    exec(compile(mod, str(PKG / "__init__.py"), "exec"), ns)
    table = ns["_INTEGRATION_KEY_SIGNAL_TABLE"]
    assert table["face_recognition_enabled"] == ("ura_face_recognition_changed",)
    # Egress identity is fresh-read → intentionally absent (no discharge).
    assert "egress_identity_enabled" not in table


# ---------------------------------------------------------------------------
# D3 — switch class: load _IntegrationOptionsSwitch via AST slice, stub
# out SwitchEntity + DeviceInfo, exercise the real code paths.
# ---------------------------------------------------------------------------

def _load_switch_class():
    mod = _slice_names_and_funcs(
        SWITCH_SRC, names=set(), funcs={"_IntegrationOptionsSwitch"},
    )

    class _StubSwitch:
        _attr_has_entity_name = False
        _attr_should_poll = True
        _attr_name = None
        _attr_icon = None
        _attr_unique_id = None
        _attr_translation_key = None
        _attr_device_info = None
        entity_id = None
        hass = None

        def async_write_ha_state(self):
            pass

    ns = {
        "SwitchEntity": _StubSwitch,
        "DeviceInfo": dict,
        "DOMAIN": "universal_room_automation",
        "VERSION": "test",
        "HomeAssistant": type("HomeAssistant", (), {}),
        "ConfigEntry": type("ConfigEntry", (), {}),
        "_LOGGER": MagicMock(),
        "Any": object,
    }
    # Install a dispatcher stub the function-local import can find.
    sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    ha = sys.modules["homeassistant"]
    if not hasattr(ha, "__path__"):
        ha.__path__ = []
    helpers = sys.modules.get("homeassistant.helpers") or types.ModuleType("homeassistant.helpers")
    helpers.__path__ = getattr(helpers, "__path__", [])
    sys.modules["homeassistant.helpers"] = helpers
    ha.helpers = helpers
    disp = sys.modules.get("homeassistant.helpers.dispatcher") or types.ModuleType(
        "homeassistant.helpers.dispatcher"
    )
    sys.modules["homeassistant.helpers.dispatcher"] = disp
    helpers.dispatcher = disp
    disp.async_dispatcher_send = getattr(
        disp, "async_dispatcher_send", lambda *a, **kw: None,
    )
    exec(compile(mod, str(PKG / "switch.py"), "exec"), ns)
    return ns["_IntegrationOptionsSwitch"], disp


_IntegrationOptionsSwitch, _DISPATCHER = _load_switch_class()


class _FakeConfigEntries:
    def __init__(self):
        self.reload_calls: list[str] = []
        self._entries: list = []

    def add(self, entry):
        self._entries.append(entry)

    def async_update_entry(self, entry, *, options=None):
        if options is not None:
            entry.options = dict(options)
        return True

    def async_entries(self, _domain=None):
        return list(self._entries)

    def async_reload(self, entry_id):
        self.reload_calls.append(entry_id)

        async def _done():
            return None
        return _done()


class _FakeHass:
    def __init__(self):
        self.data = {}
        self.config_entries = _FakeConfigEntries()


class _FakeEntry:
    def __init__(self, *, entry_id="int_1", options=None):
        self.entry_id = entry_id
        self.title = "URA"
        self.data = {"entry_type": "integration"}
        self.options = options or {}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_face_switch(hass, entry):
    return _IntegrationOptionsSwitch(
        hass, entry,
        conf_key=CONST.CONF_FACE_RECOGNITION_ENABLED,
        default=CONST.DEFAULT_FACE_RECOGNITION_ENABLED,
        translation_key="presence_face_matching",
        fallback_name="Presence Face Matching",
        object_id="ura_presence_face_matching",
        unique_suffix="presence_face_matching",
        icon="mdi:face-recognition",
        fire_signal=CONST.SIGNAL_URA_FACE_RECOGNITION_CHANGED,
    )


def _make_egress_switch(hass, entry):
    return _IntegrationOptionsSwitch(
        hass, entry,
        conf_key=CONST.CONF_EGRESS_IDENTITY_ENABLED,
        default=CONST.DEFAULT_EGRESS_IDENTITY_ENABLED,
        translation_key="name_people_at_doors",
        fallback_name="Name People at Doors",
        object_id="ura_name_people_at_doors",
        unique_suffix="name_people_at_doors",
        icon="mdi:badge-account-horizontal",
        fire_signal=None,
    )


def test_d3_face_switch_entity_id_and_unique_id_pinned():
    hass, entry = _FakeHass(), _FakeEntry()
    sw = _make_face_switch(hass, entry)
    assert sw.entity_id == "switch.ura_presence_face_matching"
    assert sw._attr_unique_id == "universal_room_automation_presence_face_matching"


def test_d3_egress_switch_entity_id_and_unique_id_pinned():
    hass, entry = _FakeHass(), _FakeEntry()
    sw = _make_egress_switch(hass, entry)
    assert sw.entity_id == "switch.ura_name_people_at_doors"
    assert sw._attr_unique_id == "universal_room_automation_name_people_at_doors"


def test_d3_initial_is_on_reads_default_true_when_options_unset():
    hass, entry = _FakeHass(), _FakeEntry(options={})
    assert _make_face_switch(hass, entry).is_on is True
    assert _make_egress_switch(hass, entry).is_on is True


def test_d3_toggle_writes_back_to_options():
    hass, entry = _FakeHass(), _FakeEntry(options={"face_recognition_enabled": True})
    sw = _make_face_switch(hass, entry)
    assert sw.is_on is True
    _run(sw.async_turn_off())
    assert entry.options["face_recognition_enabled"] is False
    assert sw.is_on is False
    _run(sw.async_turn_on())
    assert entry.options["face_recognition_enabled"] is True
    assert sw.is_on is True


def test_d3_face_toggle_fires_signal_from_switch():
    hass, entry = _FakeHass(), _FakeEntry(options={})
    fired = []
    _DISPATCHER.async_dispatcher_send = lambda h, sig, *a, **kw: fired.append((sig, a))
    _run(_make_face_switch(hass, entry).async_turn_off())
    assert any(sig == "ura_face_recognition_changed" for sig, _ in fired)


def test_d3_egress_toggle_does_not_fire_any_signal():
    hass, entry = _FakeHass(), _FakeEntry(options={})
    fired = []
    _DISPATCHER.async_dispatcher_send = lambda h, sig, *a, **kw: fired.append(sig)
    _run(_make_egress_switch(hass, entry).async_turn_off())
    assert fired == [], (
        "egress-identity is fresh-read at all consumers; the switch "
        "must NOT emit a signal (would be a dead dispatch)"
    )


def test_d3_switch_does_not_call_async_reload():
    """INV-1 point 4 (non-hollow): the switch never touches async_reload."""
    hass, entry = _FakeHass(), _FakeEntry(options={})
    hass.config_entries.add(entry)
    _run(_make_face_switch(hass, entry).async_turn_off())
    _run(_make_egress_switch(hass, entry).async_turn_off())
    assert hass.config_entries.reload_calls == []
    # Belt: source anchor — no async_reload call in _IntegrationOptionsSwitch.
    cls_src = ast.get_source_segment(SWITCH_SRC, next(
        n for n in ast.parse(SWITCH_SRC).body
        if isinstance(n, ast.ClassDef) and n.name == "_IntegrationOptionsSwitch"
    ))
    # Source anchor: no CALL to async_reload (the docstring may mention it
    # in prose; the CALL forms are `.async_reload(` and `await *async_reload`).
    assert ".async_reload(" not in cls_src, (
        "_IntegrationOptionsSwitch must not call async_reload — the "
        "INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS branch short-circuits reload."
    )


# ---------------------------------------------------------------------------
# D5 — restart persistence
# ---------------------------------------------------------------------------

def test_d5_switch_state_survives_restart():
    hass, entry = _FakeHass(), _FakeEntry(options={})
    _run(_make_face_switch(hass, entry).async_turn_off())
    assert entry.options["face_recognition_enabled"] is False
    # New instance on the same persisted entry (simulates restart).
    sw2 = _make_face_switch(hass, entry)
    assert sw2.is_on is False
    # Fresh install (options unset) reads the True default.
    assert _make_face_switch(hass, _FakeEntry(options={})).is_on is True


# ---------------------------------------------------------------------------
# D2 — signal-refresh: mirror the handler production registers and prove
# the flip happens WITHOUT a reload. AST anchors keep the mirror honest.
# ---------------------------------------------------------------------------

def test_d2_transit_validator_registers_signal_handler():
    """AST anchor — non-hollow: the handler + subscription + unsub must
    all exist in transit_validator.py by name. Removing any of them
    breaks this test (mutation-drill-ready)."""
    assert "_on_face_recognition_changed" in TV_SRC
    assert "SIGNAL_URA_FACE_RECOGNITION_CHANGED" in TV_SRC
    assert "self._face_recog_signal_unsub = async_dispatcher_connect(" in TV_SRC
    # Teardown clears the unsub (Bug Class #38 — listener leak).
    assert "self._face_recog_signal_unsub()" in TV_SRC


def test_d2_presence_registers_signal_handler():
    assert "SIGNAL_URA_FACE_RECOGNITION_CHANGED" in PRESENCE_SRC
    assert "_on_face_recog_changed" in PRESENCE_SRC
    # Wired via the coordinator's existing _unsub_listeners collection so
    # teardown happens with _cancel_listeners.
    assert (
        "self._unsub_listeners.append(\n                    async_dispatcher_connect("
        in PRESENCE_SRC
    ) or (
        "self._unsub_listeners.append("
        in PRESENCE_SRC and "SIGNAL_URA_FACE_RECOGNITION_CHANGED" in PRESENCE_SRC
    )


def test_d2_handler_effect_flips_cached_flag_without_reload():
    """Mirror the handler body from transit_validator.py._on_face_recognition_changed."""
    hass = _FakeHass()
    entry = _FakeEntry(options={"face_recognition_enabled": True})
    hass.config_entries.add(entry)

    class _StubCoord:
        pass
    stub = _StubCoord()
    stub._face_recognition_enabled = True

    def _handler():
        for cfg in hass.config_entries.async_entries():
            if cfg.data.get("entry_type") == "integration":
                merged = {**cfg.data, **cfg.options}
                stub._face_recognition_enabled = merged.get(
                    "face_recognition_enabled",
                    CONST.DEFAULT_FACE_RECOGNITION_ENABLED,
                )
                break

    # Toggle via the real switch → then handler fires.
    _run(_make_face_switch(hass, entry).async_turn_off())
    _handler()
    assert stub._face_recognition_enabled is False
    assert hass.config_entries.reload_calls == []


# ---------------------------------------------------------------------------
# D3 — dual-fire idempotency (switch fires signal, listener fires it
# again a moment later; both refresh to the same fresh value).
# ---------------------------------------------------------------------------

def test_d3_dual_fire_is_idempotent():
    hass, entry = _FakeHass(), _FakeEntry(options={"face_recognition_enabled": True})
    hass.config_entries.add(entry)

    cached = {"val": True}

    def _refresh():
        for cfg in hass.config_entries.async_entries():
            if cfg.data.get("entry_type") == "integration":
                cached["val"] = cfg.options.get("face_recognition_enabled", True)

    fires = []
    _DISPATCHER.async_dispatcher_send = lambda h, sig, *a, **kw: (
        fires.append(sig), _refresh()
    )
    _run(_make_face_switch(hass, entry).async_turn_off())
    # Simulate the listener's second fire (belt-and-suspenders):
    _DISPATCHER.async_dispatcher_send(hass, "ura_face_recognition_changed",
                                      entry.entry_id, "face_recognition_enabled")
    assert fires.count("ura_face_recognition_changed") == 2
    assert cached["val"] is False


# ---------------------------------------------------------------------------
# D4 — default-flip parity with existing consumers
# ---------------------------------------------------------------------------

def test_d4_camera_census_reads_default_egress_identity():
    """The fresh-read consumer honors the new True default via its
    imported DEFAULT_EGRESS_IDENTITY_ENABLED (source anchor)."""
    assert CONST.DEFAULT_EGRESS_IDENTITY_ENABLED is True
    assert "DEFAULT_EGRESS_IDENTITY_ENABLED" in CENSUS_SRC


def test_d4_config_flow_default_uses_new_constant():
    assert "DEFAULT_FACE_RECOGNITION_ENABLED" in CONFIG_FLOW_SRC
    assert (
        "_get_current(CONF_FACE_RECOGNITION_ENABLED, "
        "DEFAULT_FACE_RECOGNITION_ENABLED)"
    ) in CONFIG_FLOW_SRC


def test_d4_transit_validator_uses_new_default_constant():
    """transit_validator.py should read via DEFAULT_FACE_RECOGNITION_ENABLED
    so a future default flip flows through in one place."""
    assert "DEFAULT_FACE_RECOGNITION_ENABLED" in TV_SRC
    assert "merged.get(\n                    CONF_FACE_RECOGNITION_ENABLED,\n                    DEFAULT_FACE_RECOGNITION_ENABLED,\n                )" in TV_SRC


def test_d4_presence_uses_new_default_constant():
    assert "DEFAULT_FACE_RECOGNITION_ENABLED" in PRESENCE_SRC


# ---------------------------------------------------------------------------
# Enhanced-census gets NO switch (parked per plan MED-5).
# ---------------------------------------------------------------------------

def test_enhanced_census_not_exposed_as_switch():
    tree = ast.parse(SWITCH_SRC)
    async_setup = next(
        n for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry"
    )
    body_src = ast.get_source_segment(SWITCH_SRC, async_setup)
    assert "CONF_ENHANCED_CENSUS" not in body_src, (
        "enhanced_census is intentionally NOT exposed as a switch this "
        "cycle (parked). Trigger to revisit: __init__.py:2253 becomes "
        "re-runnable in-place."
    )
