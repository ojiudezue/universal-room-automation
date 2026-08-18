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
# D2 — signal-refresh: REAL production handler invocation. HIGH-3 fix
# (Review C, 2026-08-18). Uses stub-package + spy-dispatcher to import
# transit_validator.py without the full HA runtime, then constructs a
# real TransitValidator, runs async_init, captures the ACTUAL callback
# the production code registers, and drives it. For PresenceCoordinator
# we AST-extract the subscription block (async_setup itself is too
# heavy to run in isolation) and exec it on a stub self — but the
# executed CODE is the real production source text, not a mirror.
# ---------------------------------------------------------------------------


def _install_ura_stub_package():
    """Register a shim `custom_components.universal_room_automation` in
    sys.modules whose __path__ points at the real dir but whose __init__
    is not executed — so submodules like `transit_validator` can be
    imported with their real `from .const import ...` resolving to the
    real const.py, WITHOUT triggering the package's real __init__.py
    (which pulls in HA's config_entries at module scope).
    """
    for mod_name in ("custom_components", "custom_components.universal_room_automation",
                     "custom_components.universal_room_automation.domain_coordinators"):
        if mod_name in sys.modules:
            continue
        mod = types.ModuleType(mod_name)
        if mod_name == "custom_components":
            mod.__path__ = [str(PKG.parent)]
        elif mod_name == "custom_components.universal_room_automation":
            mod.__path__ = [str(PKG)]
        else:
            mod.__path__ = [str(PKG / "domain_coordinators")]
        sys.modules[mod_name] = mod
        if "." in mod_name:
            parent = sys.modules[mod_name.rsplit(".", 1)[0]]
            setattr(parent, mod_name.rsplit(".", 1)[1], mod)


def _install_full_ha_stubs():
    """Install the HA modules TransitValidator's module-top imports need."""
    def _stub(name, attrs=None):
        if name in sys.modules:
            m = sys.modules[name]
        else:
            m = types.ModuleType(name)
            m.__path__ = []
            sys.modules[name] = m
        for k, v in (attrs or {}).items():
            if not hasattr(m, k):
                setattr(m, k, v)
        if "." in name:
            parent = sys.modules[name.rsplit(".", 1)[0]]
            setattr(parent, name.rsplit(".", 1)[1], m)
        return m

    _stub("homeassistant")
    _stub("homeassistant.core", {
        "HomeAssistant": type("HomeAssistant", (), {}),
        "callback": lambda f: f,
        "Event": type("Event", (), {}),
    })
    _stub("homeassistant.config_entries", {
        "ConfigEntry": type("ConfigEntry", (), {}),
    })
    _stub("homeassistant.helpers")
    _stub("homeassistant.helpers.dispatcher", {
        "async_dispatcher_send": lambda *a, **kw: None,
        "async_dispatcher_connect": lambda *a, **kw: (lambda: None),
    })
    _stub("homeassistant.helpers.event", {
        "async_track_time_interval": lambda *a, **kw: (lambda: None),
    })
    _stub("homeassistant.helpers.area_registry", {"async_get": lambda *a: None})
    _stub("homeassistant.helpers.entity_registry", {
        "async_get": lambda *a: None,
        "EVENT_ENTITY_REGISTRY_UPDATED": "event_entity_registry_updated",
    })
    _stub("homeassistant.helpers.device_registry", {
        "async_get": lambda *a: None,
        "DeviceInfo": dict,
    })
    _stub("homeassistant.helpers.entity", {
        "EntityCategory": type("EntityCategory", (), {}),
    })
    _stub("homeassistant.helpers.entity_platform", {"AddEntitiesCallback": object})
    _stub("homeassistant.helpers.restore_state", {"RestoreEntity": type("R", (), {})})
    _stub("homeassistant.util")
    _stub("homeassistant.util.dt", {
        "utcnow": lambda: None,
        "now": lambda: None,
        "as_utc": lambda x: x,
        "as_local": lambda x: x,
        "parse_datetime": lambda s: None,
    })
    _stub("homeassistant.const", {"Platform": type("Platform", (), {})})
    _stub("homeassistant.components")
    _stub("homeassistant.components.switch", {"SwitchEntity": type("S", (), {})})


_install_full_ha_stubs()
_install_ura_stub_package()


def _register_const_under_package_name():
    """Register the real const module under
    `custom_components.universal_room_automation.const` so relative
    imports like `from ..const import CONF_FACE_RECOGNITION_ENABLED`
    inside exec'd source blocks resolve correctly."""
    name = "custom_components.universal_room_automation.const"
    if name in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(name, PKG / "const.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    setattr(sys.modules["custom_components.universal_room_automation"],
            "const", mod)


_register_const_under_package_name()


def _load_transit_validator_module():
    name = "custom_components.universal_room_automation.transit_validator"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PKG / "transit_validator.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class _FakeBus:
    def async_listen(self, *_a, **_kw):
        return lambda: None


class _FakeStates:
    def get(self, *_a, **_kw):
        return None


def _hass_with_integration_entry(options):
    hass = _FakeHass()
    hass.bus = _FakeBus()
    hass.states = _FakeStates()
    entry = _FakeEntry(options=dict(options))
    hass.config_entries.add(entry)
    return hass, entry


def test_d2_transit_validator_flips_cached_flag_on_signal_without_reload():
    """BEHAVIORAL (HIGH-3 fix): construct a real TransitValidator, run
    the real async_init, capture the REAL callback the production code
    registers with async_dispatcher_connect(SIGNAL_URA_FACE_RECOGNITION_CHANGED, ...),
    flip the entry option to False, invoke the captured callback, and
    assert the cached _face_recognition_enabled flipped WITHOUT a reload.

    If the `async_dispatcher_connect` block for the face-recognition
    signal is deleted from transit_validator.py, `captured` will be
    empty and this test fails at the first `assert captured`.
    """
    tv_mod = _load_transit_validator_module()
    hass, entry = _hass_with_integration_entry({"face_recognition_enabled": True})

    # Spy on the real dispatcher module used by tv_mod. It calls
    # `async_dispatcher_connect` via a function-local import — same
    # module object we stub here.
    disp = sys.modules["homeassistant.helpers.dispatcher"]
    captured: list[tuple] = []
    original_connect = disp.async_dispatcher_connect

    def _spy_connect(_hass, sig, cb):
        captured.append((sig, cb))
        return lambda: None

    disp.async_dispatcher_connect = _spy_connect
    try:
        tv = tv_mod.TransitValidator(hass)
        # _build_and_subscribe touches camera subscriptions we don't
        # need to exercise here; short-circuit it.
        tv._build_and_subscribe = lambda: None
        _run(tv.async_init())
    finally:
        disp.async_dispatcher_connect = original_connect

    # Real production wiring must have registered SIGNAL_URA_FACE_RECOGNITION_CHANGED.
    face_cbs = [cb for sig, cb in captured
                if sig == "ura_face_recognition_changed"]
    assert face_cbs, (
        "TransitValidator.async_init failed to register the face-recognition "
        "signal handler — the wire-in has been neutered (Bug Class #62 "
        "trip-wire)."
    )

    # Initial cached flag reads True (options + new default).
    assert tv._face_recognition_enabled is True

    # Flip the entry option to False and fire the REAL captured handler.
    entry.options["face_recognition_enabled"] = False
    face_cbs[0](entry.entry_id, "face_recognition_enabled")

    assert tv._face_recognition_enabled is False, (
        "cached _face_recognition_enabled did not flip on the signal — "
        "the production handler is broken"
    )
    assert hass.config_entries.reload_calls == [], (
        "signal refresh must NOT cascade a parent-entry reload"
    )


def test_d2_transit_validator_teardown_clears_face_recog_unsub():
    """Bug Class #38 — listener leak. `async_teardown` (or the equivalent
    teardown method) must clear self._face_recog_signal_unsub."""
    tv_mod = _load_transit_validator_module()
    hass, _ = _hass_with_integration_entry({})

    disp = sys.modules["homeassistant.helpers.dispatcher"]
    orig = disp.async_dispatcher_connect
    unsub_calls = {"count": 0}

    def _unsub():
        unsub_calls["count"] += 1

    disp.async_dispatcher_connect = lambda _h, _s, _c: _unsub
    try:
        tv = tv_mod.TransitValidator(hass)
        tv._build_and_subscribe = lambda: None
        _run(tv.async_init())
        # Find the teardown method — name is async_teardown per repo convention.
        teardown = getattr(tv, "async_teardown", None) or getattr(tv, "async_unload", None)
        assert teardown is not None, "TransitValidator must expose a teardown method"
        _run(teardown())
    finally:
        disp.async_dispatcher_connect = orig
    assert unsub_calls["count"] >= 1, (
        "teardown must call at least one unsub — the face-recog signal "
        "unsub is expected to be one of them"
    )
    assert tv._face_recog_signal_unsub is None


# --- PresenceCoordinator: exec the REAL production subscription block ------

def _extract_presence_subscription_block() -> str:
    """Extract the exact source text of the presence.py face-recog
    subscription try/except (lines starting at the CENSUS-TOGGLES marker,
    ending at the matching `exc_info=True,\\n                )`).

    Executing this source in a controlled namespace proves the REAL
    production text is capable of registering and refreshing. Deleting
    or renaming any line inside the block changes the extracted text and
    the mutation-drill will bite.
    """
    start_marker = "# CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 (2026-08-18): subscribe"
    src_lines = PRESENCE_SRC.splitlines(keepends=True)
    start_idx = None
    for i, line in enumerate(src_lines):
        if start_marker in line:
            start_idx = i
            break
    assert start_idx is not None, (
        "presence.py missing the face-recog subscription block marker"
    )
    # Find the block's closing `)` of the except block: search forward
    # for the line that begins the next unrelated section ("# v3.6.0.3").
    end_idx = None
    for j in range(start_idx + 1, len(src_lines)):
        if "# v3.6.0.3: Wrap discovery/subscription" in src_lines[j]:
            end_idx = j
            break
    assert end_idx is not None, "could not locate end of block"
    # Dedent uniformly by the leading whitespace of the marker line.
    marker_line = src_lines[start_idx]
    indent = len(marker_line) - len(marker_line.lstrip())
    block = "".join(line[indent:] if len(line) > indent else line
                    for line in src_lines[start_idx:end_idx])
    return block


def test_d2_presence_subscription_block_flips_cached_flag_on_signal():
    """BEHAVIORAL (HIGH-3 fix): exec the REAL presence.py subscription
    block (extracted verbatim from source) against a stub self, capture
    the callback via a spy async_dispatcher_connect, flip entry options,
    invoke callback, assert cached flag flipped. If the block is deleted
    from presence.py, `_extract_presence_subscription_block` fails first.
    """
    block_src = _extract_presence_subscription_block()

    captured: list[tuple] = []

    def _spy_connect(_hass, sig, cb):
        captured.append((sig, cb))
        return lambda: None

    hass, entry = _hass_with_integration_entry({"face_recognition_enabled": True})

    class _StubPresence:
        pass
    stub_self = _StubPresence()
    stub_self.hass = hass
    stub_self._face_recognition_enabled = True
    stub_self._unsub_listeners = []

    ns = {
        "self": stub_self,
        "async_dispatcher_connect": _spy_connect,
        "DOMAIN": "universal_room_automation",
        "_LOGGER": MagicMock(),
        # `from ..const import ...` inside the block needs a package
        # context to resolve; anchoring to domain_coordinators makes
        # `..const` resolve to the real const module registered above.
        "__package__": "custom_components.universal_room_automation.domain_coordinators",
        "__name__": "custom_components.universal_room_automation.domain_coordinators.presence",
    }
    # Wrap in a fake enclosing scope. The block uses top-level `try:` so
    # we can exec directly (indent-preserved for the try body).
    exec(compile(block_src, "<presence-face-recog-block>", "exec"), ns)

    face_cbs = [cb for sig, cb in captured
                if sig == "ura_face_recognition_changed"]
    assert face_cbs, (
        "presence.py face-recog subscription block did not register the "
        "signal handler — the wire-in has been neutered"
    )
    # Real production callback executed against real entry.options change.
    entry.options["face_recognition_enabled"] = False
    face_cbs[0](entry.entry_id, "face_recognition_enabled")
    assert stub_self._face_recognition_enabled is False
    assert hass.config_entries.reload_calls == []
    # The unsub must be tracked in _unsub_listeners for teardown by
    # _cancel_listeners (Bug Class #38).
    assert len(stub_self._unsub_listeners) == 1


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
# D4 — default-flip parity: BEHAVIORAL (MED-2 fix, Review C 2026-08-18).
# Each consumer is exercised with EMPTY options; the resolved value must
# be True. If a consumer reverts its inline default to False, its D4 test
# fails. Mutation drill confirmed in the review report.
# ---------------------------------------------------------------------------


def test_d4_camera_census_egress_identity_reader_returns_true_on_empty_options():
    """AST-slice the `_is_egress_identity_enabled` method body and exec
    it against a stub self with an integration entry that has EMPTY
    options. Result must be True (post-default-flip)."""
    tree = ast.parse(CENSUS_SRC)
    method = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.FunctionDef)
                and node.name == "_is_egress_identity_enabled"):
            method = node
            break
    assert method is not None, "_is_egress_identity_enabled missing from camera_census.py"
    # Compile the method as a standalone def, then call it.
    method_src = ast.get_source_segment(CENSUS_SRC, method)
    ns = {
        "DOMAIN": "universal_room_automation",
        "CONF_ENTRY_TYPE": "entry_type",
        "ENTRY_TYPE_INTEGRATION": "integration",
        "CONF_EGRESS_IDENTITY_ENABLED": CONST.CONF_EGRESS_IDENTITY_ENABLED,
        "DEFAULT_EGRESS_IDENTITY_ENABLED": CONST.DEFAULT_EGRESS_IDENTITY_ENABLED,
    }
    # Dedent the method (it's inside a class in the source).
    import textwrap
    method_src = textwrap.dedent(method_src)
    exec(compile(method_src, "<census-egress-reader>", "exec"), ns)
    reader = ns["_is_egress_identity_enabled"]

    hass, _ = _hass_with_integration_entry({})  # EMPTY options
    class _StubCensus:
        pass
    stub = _StubCensus()
    stub.hass = hass
    assert reader(stub) is True, (
        "camera_census._is_egress_identity_enabled must return True on empty "
        "options (default-flip live). If this fails, a consumer default has "
        "silently drifted back to False."
    )


def test_d4_config_flow_face_recognition_default_resolves_true_on_empty_options():
    """Behavioral: the schema default the config-flow renders for
    CONF_FACE_RECOGNITION_ENABLED with EMPTY options must be True.

    We can't easily build the full options-flow schema, but we CAN
    invoke `_get_current` semantics directly by mirroring one line
    against the same constants — using dict-lookup shape identical to
    the config_flow.py `_get_current` helper (returns options.get(key,
    fallback)). This is byte-identical to what config_flow does at line
    :2960.
    """
    empty_options: dict = {}
    resolved = empty_options.get(
        CONST.CONF_FACE_RECOGNITION_ENABLED,
        CONST.DEFAULT_FACE_RECOGNITION_ENABLED,
    )
    assert resolved is True
    # And belt: config_flow.py MUST pass DEFAULT_FACE_RECOGNITION_ENABLED
    # as the second arg (a merge-slip that reintroduced `False` would flip
    # the schema default silently — the mutation drill confirmed this in
    # the review report).
    tree = ast.parse(CONFIG_FLOW_SRC)
    hit = False
    for call in ast.walk(tree):
        if (isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "_get_current"
                and len(call.args) == 2
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id == "CONF_FACE_RECOGNITION_ENABLED"):
            second = call.args[1]
            assert isinstance(second, ast.Name), (
                "config_flow.py passes a literal instead of the DEFAULT_* "
                "constant to _get_current — default-flip fragile"
            )
            assert second.id == "DEFAULT_FACE_RECOGNITION_ENABLED"
            hit = True
    assert hit, "config_flow.py no longer calls _get_current for face-recog"


def test_d4_transit_validator_reads_true_on_empty_options():
    """BEHAVIORAL: construct a real TransitValidator, call the REAL
    async_init against an integration entry with EMPTY options, and
    assert `_face_recognition_enabled is True` — proves the read at
    line 266-269 uses DEFAULT_FACE_RECOGNITION_ENABLED (True), not
    False. Reverting the default to False in const.py or replacing
    the constant with `False` at the read site would fail this test.
    """
    tv_mod = _load_transit_validator_module()
    hass, _ = _hass_with_integration_entry({})  # EMPTY options
    tv = tv_mod.TransitValidator(hass)
    tv._build_and_subscribe = lambda: None
    _run(tv.async_init())
    assert tv._face_recognition_enabled is True


def test_d4_presence_initial_read_returns_true_on_empty_options():
    """BEHAVIORAL: exec the REAL presence.py initial-read block
    (AST-sliced from `async_setup`) with EMPTY options and assert the
    cached flag lands True."""
    # The initial read is the small block just before the CENSUS-TOGGLES
    # subscription block. Extract it by markers.
    src_lines = PRESENCE_SRC.splitlines(keepends=True)
    start_marker = "# v3.19.0: Read face recognition toggle from integration config"
    end_marker = "# CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 (2026-08-18): subscribe"
    start_idx = end_idx = None
    for i, line in enumerate(src_lines):
        if start_marker in line and start_idx is None:
            start_idx = i
        if end_marker in line and start_idx is not None:
            end_idx = i
            break
    assert start_idx is not None and end_idx is not None
    marker_line = src_lines[start_idx]
    indent = len(marker_line) - len(marker_line.lstrip())
    block = "".join(line[indent:] if len(line) > indent else line
                    for line in src_lines[start_idx:end_idx])

    hass, _ = _hass_with_integration_entry({})  # EMPTY options

    class _StubPresence:
        pass
    stub = _StubPresence()
    stub.hass = hass
    stub._face_recognition_enabled = None  # Sentinel; must land True.

    ns = {
        "self": stub,
        "DOMAIN": "universal_room_automation",
        "_LOGGER": MagicMock(),
        "__package__": "custom_components.universal_room_automation.domain_coordinators",
        "__name__": "custom_components.universal_room_automation.domain_coordinators.presence",
    }
    exec(compile(block, "<presence-face-recog-initial-read>", "exec"), ns)
    assert stub._face_recognition_enabled is True, (
        "presence.py initial read of CONF_FACE_RECOGNITION_ENABLED on empty "
        "options must resolve to True — a merge slip that reverts the "
        "second arg to `False` would fail here (MED-2 mutation-drill anchor)."
    )


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
