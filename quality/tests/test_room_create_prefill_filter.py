"""ROOM-CREATE-AREA-PREFILL-DETRITUS-1 — build tests (Rev 2 wire-in).

Covers:
- D1 prefill filter in `_get_area_entities` (DOMAIN + name-token regex)
- D1 regex pins (incl. the F5 `switch.65_mini_led_power` non-match)
- D1 F9 single-room async_step_devices form default
- D2 bulk-create parity via `build_area_room_data`
- D3 FOUR per-site behavioral tests driving the real actuation methods
  on a minimally wired RoomAutomation (private-package loader, pattern
  borrowed from test_hvac_batch_d_shared_space_fans.py). Each site's
  `_actuatable_ids(...)` call is the mutation drill target.
- D4 one-shot boot scan via `_scan_prefill_detritus` behavioral test +
  AST-anchored wire-in test on `async_setup_entry`.
"""
from __future__ import annotations

import asyncio
import ast
import importlib
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Shared private-package loader (same scheme as
# test_hvac_batch_d_shared_space_fans.py — avoids sys.modules collisions
# with other tests that load the integration under a different name).
# ---------------------------------------------------------------------------
_URA = (
    Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation"
)
_PKG = "ura_prefill_detritus_pkg"


def _load():
    if f"{_PKG}.automation" not in sys.modules:
        pkg = types.ModuleType(_PKG)
        pkg.__path__ = [str(_URA)]
        sys.modules[_PKG] = pkg
        dc = types.ModuleType(f"{_PKG}.domain_coordinators")
        dc.__path__ = [str(_URA / "domain_coordinators")]
        sys.modules[f"{_PKG}.domain_coordinators"] = dc
    return (
        importlib.import_module(f"{_PKG}.const"),
        importlib.import_module(f"{_PKG}.automation"),
    )


C, A = _load()
DOMAIN = C.DOMAIN
CONF_AUTO_SWITCHES = C.CONF_AUTO_SWITCHES
CONF_MANUAL_SWITCHES = C.CONF_MANUAL_SWITCHES
CONF_AUTO_DEVICES = C.CONF_AUTO_DEVICES
CONF_MANUAL_DEVICES = C.CONF_MANUAL_DEVICES
CONF_LIGHTS = C.CONF_LIGHTS
AUTODETECT_NAME_DENYLIST_PREFILL = C.AUTODETECT_NAME_DENYLIST_PREFILL

# ---------------------------------------------------------------------------
# D1/D2 harness (borrowed from test_onboarding_simplify_slice1).
# ---------------------------------------------------------------------------
_slice1 = importlib.import_module("test_onboarding_simplify_slice1")
_install_registries = _slice1._install_registries
_reg_entry = _slice1._reg_entry
_cf = _slice1._cf
_make_config_flow = _slice1._make_config_flow
build_area_room_data = _cf.build_area_room_data


# Production regex object — tests pin against this, NOT a local rebuild.
_TOKEN_RE = C.PREFILL_DETRITUS_TOKEN_RE
assert _TOKEN_RE is not None


# ===========================================================================
# D1 — prefill filter
# ===========================================================================

def test_get_area_entities_excludes_ura_domain():
    entries = [
        _reg_entry("switch.universal_room_automation_x", "switch",
                   area_id="area1", platform=DOMAIN),
        _reg_entry("switch.plain_plug_a", "switch",
                   area_id="area1", platform="mqtt"),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    assert flow._get_area_entities("area1", "switch") == [
        "switch.plain_plug_a",
    ]


def test_get_area_entities_excludes_name_token_backstop():
    entries = [
        _reg_entry("switch.minir4m_mastercloset_detach", "switch",
                   area_id="area1", platform="sonoff"),
        _reg_entry("switch.mmwave_zigbee_jayabedroom_anti_interference",
                   "switch", area_id="area1", platform="mqtt"),
        _reg_entry("switch.plain_plug_a", "switch",
                   area_id="area1", platform="mqtt"),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    assert flow._get_area_entities("area1", "switch") == [
        "switch.plain_plug_a",
    ]


def test_get_area_entities_keeps_plain_actuators():
    entries = [
        _reg_entry("switch.ura_x", "switch",
                   area_id="a1", platform=DOMAIN),
        _reg_entry("switch.minir4m_mastercloset_detach", "switch",
                   area_id="a1", platform="sonoff"),
        _reg_entry("switch.mmwave_zigbee_jayabedroom_anti_interference",
                   "switch", area_id="a1", platform="mqtt"),
        _reg_entry("switch.plain_plug_a", "switch",
                   area_id="a1", platform="mqtt"),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    assert flow._get_area_entities("a1", "switch") == ["switch.plain_plug_a"]


# ===========================================================================
# F5 regex pins — behavioural
# ===========================================================================

@pytest.mark.parametrize("object_id,should_match", [
    ("mmwave_zigbee_jayabedroom_anti_interference", True),
    ("minir4m_mastercloset_detach", True),
    ("roborock_bedroom_do_not_disturb", True),
    ("dreo_fan_child_lock", True),
    ("zigbee_relay_indicator", True),
    ("indicator_light_strip", True),
    # MUST NOT match
    ("65_mini_led_power", False),  # F5 TV-power false-positive discriminator
    ("switch_shelly2pmgen3_wifi_dnguestroom_light", False),
    ("detachable_cover_cam", False),
])
def test_name_token_regex_matches(object_id, should_match):
    assert bool(_TOKEN_RE.search(object_id)) is should_match


# ===========================================================================
# F9 — single-room async_step_devices default
# ===========================================================================

def test_async_step_devices_form_default_excludes_contraband():
    entries = [
        _reg_entry("switch.plain_plug_a", "switch",
                   area_id="area1", platform="mqtt"),
        _reg_entry("switch.minir4m_x_detach", "switch",
                   area_id="area1", platform="sonoff"),
        _reg_entry("switch.ura_x", "switch",
                   area_id="area1", platform=DOMAIN),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    flow._data = {_cf.CONF_AREA_ID: "area1"}
    result = asyncio.run(flow.async_step_devices(user_input=None))
    schema = result["data_schema"]
    default = None
    for key in schema.schema:
        if getattr(key, "schema", None) == CONF_AUTO_SWITCHES:
            default = key.default() if callable(key.default) else key.default
            break
    assert default == ["switch.plain_plug_a"]


# ===========================================================================
# D2 — bulk-create parity
# ===========================================================================

def test_build_area_room_data_switches_excludes_contraband():
    entries = [
        _reg_entry("switch.plain_plug_a", "switch",
                   area_id="area1", platform="mqtt"),
        _reg_entry("switch.minir4m_x_detach", "switch",
                   area_id="area1", platform="sonoff"),
        _reg_entry("switch.ura_x", "switch",
                   area_id="area1", platform=DOMAIN),
        _reg_entry("switch.z2m_anti_interference_x", "switch",
                   area_id="area1", platform="mqtt"),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    prefill = flow._area_prefill("area1")
    data = build_area_room_data(
        name="X", room_type="generic", area_id="area1", prefill=prefill,
    )
    assert data[CONF_AUTO_SWITCHES] == ["switch.plain_plug_a"]


# ===========================================================================
# D3 — FOUR per-site behavioural tests (private-pkg harness).
# ===========================================================================

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _patch_registry(monkeypatch, reg_map):
    """Install a fake entity_registry.async_get for the ura_prefill pkg's
    automation module. Teardown is handled by monkeypatch."""
    import homeassistant.helpers.entity_registry as er  # type: ignore

    class _R:
        def async_get(self, eid):
            return reg_map.get(eid)

    monkeypatch.setattr(er, "async_get", lambda hass: _R())


def _make_room(config):
    """Minimal RoomAutomation instance — mirrors
    test_hvac_batch_d_shared_space_fans._room() but focused on the
    actuation-site tests."""
    hass = MagicMock()
    hass.config_entries.async_entries = lambda domain=None: []
    coord = MagicMock()
    coord.entry = SimpleNamespace(entry_id="eid-test", data=config, options={})
    auto = A.RoomAutomation(hass=hass, config=config, coordinator=coord)
    log: list[tuple[str, str, dict]] = []

    async def _svc(domain, service, data=None, **_):
        log.append((domain, service, dict(data or {})))

    auto._safe_service_call = _svc
    # Prevent HVAC-owned filter from touching our fake switches.
    auto._fan_hvac_owned_elsewhere = lambda f: False
    return auto, log


def _switch_turn_off_ids(log, domain=None, service=None):
    out: list[str] = []
    for dom, svc, data in log:
        if domain is not None and dom != domain:
            continue
        if service is not None and svc != service:
            continue
        ids = data.get("entity_id")
        if isinstance(ids, list):
            out += ids
        elif ids:
            out.append(ids)
    return out


# Shared reg_map for D3 site tests: contraband + plain relay.
def _d3_reg_map():
    return {
        "switch.ura_x": SimpleNamespace(
            platform=DOMAIN, entity_category=None,
        ),
        "switch.plain_relay": SimpleNamespace(
            platform="mqtt", entity_category=None,
        ),
        "switch.minir4m_x_detach": SimpleNamespace(
            platform="sonoff", entity_category=None,
        ),
    }


def test_site1_control_auto_switches_filters_contraband(monkeypatch):
    """Site 1: `_control_auto_switches(True)` — includes CONF_AUTO_DEVICES merge."""
    _patch_registry(monkeypatch, _d3_reg_map())
    config = {
        "room_name": "Site1",
        CONF_AUTO_DEVICES: ["switch.ura_x"],              # URA domain
        CONF_AUTO_SWITCHES: [
            "switch.plain_relay", "switch.minir4m_x_detach",
        ],
    }
    auto, log = _make_room(config)
    _run(auto._control_auto_switches(True))
    ids = _switch_turn_off_ids(log, domain="homeassistant", service="turn_on")
    assert ids == ["switch.plain_relay"], ids


def test_site2_control_manual_switches_off_filters_contraband(monkeypatch):
    """Site 2: `_control_manual_switches_off()` — covers CONF_MANUAL_DEVICES merge."""
    _patch_registry(monkeypatch, _d3_reg_map())
    config = {
        "room_name": "Site2",
        CONF_MANUAL_DEVICES: ["switch.ura_x"],
        CONF_MANUAL_SWITCHES: [
            "switch.plain_relay", "switch.minir4m_x_detach",
        ],
    }
    auto, log = _make_room(config)
    _run(auto._control_manual_switches_off())
    ids = _switch_turn_off_ids(log, domain="homeassistant", service="turn_off")
    assert ids == ["switch.plain_relay"], ids


def _make_shared_space_room(auto_switches, manual_switches, reg_map):
    """Shared-space harness: Fan Mode = OFF, no lights, so sites 3+4 are
    reached without perturbing the fans / lights branches."""
    config = {
        "room_name": "SharedExit",
        CONF_AUTO_SWITCHES: list(auto_switches),
        CONF_MANUAL_SWITCHES: list(manual_switches),
        C.CONF_ROOM_FAN_MODE: C.FAN_MODE_OFF,
    }
    auto, log = _make_room(config)
    return auto, log


def test_site3_shared_space_auto_switches_filters_contraband(monkeypatch):
    """Site 3: shared-space exit — CONF_AUTO_SWITCHES."""
    _patch_registry(monkeypatch, _d3_reg_map())
    auto, log = _make_shared_space_room(
        auto_switches=["switch.plain_relay", "switch.ura_x",
                       "switch.minir4m_x_detach"],
        manual_switches=[],
        reg_map=_d3_reg_map(),
    )
    _run(auto._shared_space_turn_off_all())
    ids = _switch_turn_off_ids(log, domain="switch", service="turn_off")
    assert ids == ["switch.plain_relay"], ids


def test_site4_shared_space_manual_switches_filters_contraband(monkeypatch):
    """Site 4: shared-space exit — CONF_MANUAL_SWITCHES."""
    _patch_registry(monkeypatch, _d3_reg_map())
    auto, log = _make_shared_space_room(
        auto_switches=[],
        manual_switches=["switch.plain_relay", "switch.ura_x",
                         "switch.minir4m_x_detach"],
        reg_map=_d3_reg_map(),
    )
    _run(auto._shared_space_turn_off_all())
    ids = _switch_turn_off_ids(log, domain="switch", service="turn_off")
    assert ids == ["switch.plain_relay"], ids


def test_actuatable_ids_preserves_helper_platforms_and_hidden(monkeypatch):
    """F2 regression — rules 3 and 4 do NOT apply at runtime."""
    reg_map = {
        "switch.hidden_relay": SimpleNamespace(
            platform="shelly", entity_category=None, hidden_by="user",
        ),
        "input_boolean.user_toggle": SimpleNamespace(
            platform="input_boolean", entity_category=None, hidden_by=None,
        ),
    }
    _patch_registry(monkeypatch, reg_map)
    config = {
        "room_name": "F2",
        CONF_AUTO_DEVICES: [
            "switch.hidden_relay", "input_boolean.user_toggle",
        ],
    }
    auto, log = _make_room(config)
    _run(auto._control_auto_switches(True))
    ids = _switch_turn_off_ids(log, domain="homeassistant", service="turn_on")
    assert set(ids) == {"switch.hidden_relay", "input_boolean.user_toggle"}


def test_actuatable_ids_dedup_logs_once(monkeypatch, caplog):
    _patch_registry(monkeypatch, _d3_reg_map())
    config = {
        "room_name": "Dedup",
        CONF_AUTO_DEVICES: ["switch.ura_x", "switch.minir4m_x_detach",
                            "switch.plain_relay"],
    }
    auto, _log = _make_room(config)
    caplog.set_level("WARNING")
    _run(auto._control_auto_switches(True))
    warn1 = [r for r in caplog.records if "URA-PREFILL-DETRITUS-GUARD" in r.getMessage()]
    _run(auto._control_auto_switches(False))
    warn2 = [r for r in caplog.records if "URA-PREFILL-DETRITUS-GUARD" in r.getMessage()]
    assert len(warn2) == len(warn1), "dedup set must suppress repeat WARNs"
    # Rules present on first call
    joined = "\n".join(r.getMessage() for r in warn1)
    assert "rule_id=ura_domain" in joined
    assert "rule_id=name_backstop" in joined


# ===========================================================================
# Substring-vs-whole-word DISAGREEMENT — behavioural through BOTH routes
# ===========================================================================
#
# These object_ids CONTAIN a denylist token as a substring but NOT as a
# whole `_`-delimited word. Under whole-word matching they must SURVIVE
# both the prefill filter AND the runtime guard. A substring regex would
# reject them. Drill: swap the shared regex to substring → these tests
# go RED.

_SUBSTRING_SURVIVORS = [
    "switch.detachable_cover_cam",   # "detach" as prefix inside "detachable"
    "switch.porch_indicators",       # "indicator" as prefix inside "indicators"
]
_WHOLE_WORD_CONTRABAND = [
    "switch.x_detach",
    "switch.y_anti_interference",
]


def test_prefill_whole_word_vs_substring_disagree_prefill_route():
    entries = [
        _reg_entry(eid, "switch", area_id="area1", platform="mqtt")
        for eid in _SUBSTRING_SURVIVORS + _WHOLE_WORD_CONTRABAND
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    got = flow._get_area_entities("area1", "switch")
    assert sorted(got) == sorted(_SUBSTRING_SURVIVORS)


def test_runtime_whole_word_vs_substring_disagree_runtime_guard(monkeypatch):
    reg_map = {
        eid: SimpleNamespace(platform="mqtt", entity_category=None)
        for eid in _SUBSTRING_SURVIVORS + _WHOLE_WORD_CONTRABAND
    }
    _patch_registry(monkeypatch, reg_map)
    config = {
        "room_name": "Disagree",
        CONF_AUTO_DEVICES: list(
            _SUBSTRING_SURVIVORS + _WHOLE_WORD_CONTRABAND
        ),
    }
    auto, log = _make_room(config)
    _run(auto._control_auto_switches(True))
    ids = _switch_turn_off_ids(log, domain="homeassistant", service="turn_on")
    assert sorted(ids) == sorted(_SUBSTRING_SURVIVORS)


def test_actuatable_ids_registry_failure_passes_through(monkeypatch):
    """LOW — a registry read raise must NOT block actuation; the raw ids
    are passed through so the house keeps actuating. Drill: return [] on
    failure → this test fails."""
    import homeassistant.helpers.entity_registry as er  # type: ignore

    def _boom(_hass):
        raise RuntimeError("registry boom")

    monkeypatch.setattr(er, "async_get", _boom)
    config = {
        "room_name": "RegFail",
        CONF_AUTO_DEVICES: ["switch.a", "switch.b", "switch.c"],
    }
    auto, log = _make_room(config)
    _run(auto._control_auto_switches(True))
    ids = _switch_turn_off_ids(log, domain="homeassistant", service="turn_on")
    assert ids == ["switch.a", "switch.b", "switch.c"]


# ===========================================================================
# D4 — one-shot boot scan behavioural + AST wire-in anchor
# ===========================================================================

def _scan_module():
    """Load `_scan_prefill_detritus` from the real `__init__.py` source
    without pulling the integration's full top-level import closure
    (coordinator, database, etc. — not available in this stub env).
    Executes a lightly-wrapped namespace preloaded with the globals the
    function references (D4 constants + _classify_detritus_id + DOMAIN).
    """
    src = (_URA / "__init__.py").read_text()
    tree = ast.parse(src)
    body: list = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_scan_prefill_detritus":
            body.append(node)
            break
    mod = types.ModuleType("ura_prefill_detritus_scan_module")
    import logging as _logging
    pkg_const = importlib.import_module(f"{_PKG}.const")
    pkg_auto = importlib.import_module(f"{_PKG}.automation")
    import re as _re
    token_re = _re.compile(
        "|".join(
            rf"(?:^|_){_re.escape(t)}(?:$|_)"
            for t in pkg_const.AUTODETECT_NAME_DENYLIST_PREFILL
        )
    )
    mod.__dict__.update({
        "_LOGGER": _logging.getLogger("ura_prefill_detritus_scan_module"),
        "DOMAIN": pkg_const.DOMAIN,
        "_classify_detritus_id": pkg_auto._classify_detritus_id,
        "_PREFILL_DETRITUS_SCAN_TOKEN_RE": token_re,
        "_CONF_AUTO_DEVICES_D4": pkg_const.CONF_AUTO_DEVICES,
        "_CONF_AUTO_SWITCHES_D4": pkg_const.CONF_AUTO_SWITCHES,
        "_CONF_MANUAL_DEVICES_D4": pkg_const.CONF_MANUAL_DEVICES,
        "_CONF_MANUAL_SWITCHES_D4": pkg_const.CONF_MANUAL_SWITCHES,
        "_CONF_LIGHTS_D4": pkg_const.CONF_LIGHTS,
        "_CONF_NIGHT_LIGHTS_D4": pkg_const.CONF_NIGHT_LIGHTS,
        "_CONF_FANS_D4": pkg_const.CONF_FANS,
        "_CONF_HUMIDITY_FANS_D4": pkg_const.CONF_HUMIDITY_FANS,
        "_CONF_COVERS_D4": pkg_const.CONF_COVERS,
        "_CONF_ROOM_NAME_D4": pkg_const.CONF_ROOM_NAME,
    })
    exec(compile(ast.Module(body=body, type_ignores=[]), "__init__.py", "exec"),
         mod.__dict__)
    return mod


def test_scan_prefill_detritus_logs_once_per_rule(monkeypatch, caplog):
    pkg = _scan_module()
    reg_map = {
        "switch.ura_x": SimpleNamespace(
            platform=DOMAIN, entity_category=None,
        ),
        "switch.tapo_auto_update_enabled": SimpleNamespace(
            platform="tplink", entity_category="config",
        ),
        "switch.plain_relay": SimpleNamespace(
            platform="mqtt", entity_category=None,
        ),
    }
    _patch_registry(monkeypatch, reg_map)
    hass = MagicMock()
    entry = SimpleNamespace(
        entry_id="eid-7",
        title="Kitchen Hallway Garage",
        data={
            "room_name": "Kitchen Hallway Garage",
            CONF_AUTO_SWITCHES: [
                "switch.ura_x",
                "switch.tapo_auto_update_enabled",
                "switch.minir4m_x_detach",
                "switch.plain_relay",
            ],
        },
        options={},
    )
    caplog.set_level("WARNING")
    pkg._scan_prefill_detritus(hass, entry)
    warns = [
        r for r in caplog.records
        if "URA-PREFILL-DETRITUS-GUARD" in r.getMessage()
    ]
    rules = [m for r in warns for m in [r.getMessage()]
             if "rule_id=" in m]
    text = "\n".join(rules)
    assert "rule_id=ura_domain" in text
    assert "rule_id=config_category" in text
    assert "rule_id=name_backstop" in text
    # Exactly 3 contraband rows; plain_relay must NOT appear.
    assert len(warns) == 3, [r.getMessage() for r in warns]
    assert "plain_relay" not in text


def test_scan_prefill_detritus_wire_in_called_from_async_setup_entry():
    """Real-call-path wire-in anchor (AST) — the mutation drill: remove
    the `_scan_prefill_detritus(hass, entry)` call line inside
    `async_setup_entry` and this test goes RED. Not a text grep: walks
    the parsed AST, scoped to the function body, finds a Call node
    whose func.id == '_scan_prefill_detritus'.
    """
    src = (
        _URA / "__init__.py"
    ).read_text()
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    f = sub.func
                    name = getattr(f, "id", None) or getattr(f, "attr", None)
                    if name == "_scan_prefill_detritus":
                        found = True
                        break
            break
    assert found, (
        "wire-in missing: async_setup_entry does not call "
        "_scan_prefill_detritus — the D4 scan would never run"
    )
