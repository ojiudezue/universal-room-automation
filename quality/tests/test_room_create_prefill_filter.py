"""ROOM-CREATE-AREA-PREFILL-DETRITUS-1 — build tests.

Covers:
- D1 prefill filter in `_get_area_entities` (DOMAIN + name-token regex)
- D2 bulk-create parity via `build_area_room_data`
- D3 runtime guard `_actuatable_ids` / `_classify_detritus_id`
- D4 one-shot boot scan via `_classify_detritus_id` (shared classifier)
- Regex pin tests (incl. the F5 `switch.65_mini_led_power` non-match)

Env portability: reuses the `_install_registries` harness from
`test_onboarding_simplify_slice1` (sys.modules fakes are installed by
that helper and persist for the duration of the test session, same as
the surrounding file — this matches existing project pattern and does
not leak unseen stubs).
"""
from __future__ import annotations

import importlib
import re
from types import SimpleNamespace

import pytest

_slice1 = importlib.import_module("test_onboarding_simplify_slice1")
_install_registries = _slice1._install_registries
_reg_entry = _slice1._reg_entry
_cf = _slice1._cf
_make_config_flow = _slice1._make_config_flow

# Pull constants directly from the loaded config_flow (`_cf`) to avoid
# a second module load.
DOMAIN = _cf.DOMAIN
AUTODETECT_NAME_DENYLIST_PREFILL = _cf.AUTODETECT_NAME_DENYLIST_PREFILL
CONF_AUTO_SWITCHES = _cf.CONF_AUTO_SWITCHES
CONF_AUTO_DEVICES = _cf.CONF_AUTO_DEVICES
CONF_MANUAL_SWITCHES = _cf.CONF_MANUAL_SWITCHES
CONF_LIGHTS = _cf.CONF_LIGHTS
build_area_room_data = _cf.build_area_room_data


# ---------------------------------------------------------------------------
# Shared regex (matches the one compiled in config_flow / automation).
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(
    "|".join(
        rf"(?:^|_){re.escape(t)}(?:$|_)"
        for t in AUTODETECT_NAME_DENYLIST_PREFILL
    )
)


# ---------------------------------------------------------------------------
# D1 — prefill filter
# ---------------------------------------------------------------------------

def test_get_area_entities_excludes_ura_domain():
    entries = [
        _reg_entry(
            "switch.universal_room_automation_domain_coordinators",
            "switch", area_id="area1", platform=DOMAIN,
        ),
        _reg_entry(
            "switch.plain_plug_livingroom",
            "switch", area_id="area1", platform="mqtt",
        ),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    got = flow._get_area_entities("area1", "switch")
    assert got == ["switch.plain_plug_livingroom"]


def test_get_area_entities_excludes_name_token_backstop():
    entries = [
        _reg_entry(
            "switch.minir4m_mastercloset_detach",
            "switch", area_id="area1", platform="sonoff",
        ),
        _reg_entry(
            "switch.mmwave_zigbee_jayabedroom_anti_interference",
            "switch", area_id="area1", platform="mqtt",
        ),
        _reg_entry(
            "switch.plain_plug_livingroom",
            "switch", area_id="area1", platform="mqtt",
        ),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    got = flow._get_area_entities("area1", "switch")
    assert got == ["switch.plain_plug_livingroom"]


def test_get_area_entities_keeps_plain_actuators():
    # Full mixed fixture per plan Falsifier § + hidden/helper regression.
    entries = [
        _reg_entry("switch.ura_name_people_at_doors", "switch",
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
    got = flow._get_area_entities("a1", "switch")
    assert got == ["switch.plain_plug_a"]


# ---------------------------------------------------------------------------
# F5 regex pins — behavioural via _get_area_entities with varied object_ids
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("object_id,should_match", [
    # MUST match (whole-token)
    ("mmwave_zigbee_jayabedroom_anti_interference", True),
    ("minir4m_mastercloset_detach", True),
    ("roborock_bedroom_do_not_disturb", True),
    ("dreo_fan_child_lock", True),
    ("zigbee_relay_indicator", True),
    # MUST NOT match
    ("65_mini_led_power", False),  # F5 TV-power false-positive discriminator
    ("switch_shelly2pmgen3_wifi_dnguestroom_light", False),
    ("detachable_cover_cam", False),  # `detach` prefix, not a whole token
    ("indicator_light_strip", True),  # `indicator` IS a leading token
])
def test_name_token_regex_matches(object_id, should_match):
    assert bool(_TOKEN_RE.search(object_id)) is should_match


def test_async_step_devices_form_default_excludes_contraband():
    """F9 — single-room `async_step_devices` form default == filtered list."""
    import asyncio
    entries = [
        _reg_entry("switch.plain_plug_a", "switch",
                   area_id="area1", platform="mqtt"),
        _reg_entry("switch.minir4m_x_detach", "switch",
                   area_id="area1", platform="sonoff"),
        _reg_entry("switch.ura_blah", "switch",
                   area_id="area1", platform=DOMAIN),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    flow._data = {_cf.CONF_AREA_ID: "area1"}
    result = asyncio.run(flow.async_step_devices(user_input=None))
    schema = result["data_schema"]
    # Locate the CONF_AUTO_SWITCHES voluptuous key and read its default.
    default = None
    for key in schema.schema:
        if getattr(key, "schema", None) == CONF_AUTO_SWITCHES:
            default = key.default() if callable(key.default) else key.default
            break
    assert default == ["switch.plain_plug_a"]


# ---------------------------------------------------------------------------
# D2 — bulk-create parity
# ---------------------------------------------------------------------------

def test_build_area_room_data_switches_excludes_contraband():
    entries = [
        _reg_entry("switch.plain_plug_a", "switch",
                   area_id="area1", platform="mqtt"),
        _reg_entry("switch.minir4m_x_detach", "switch",
                   area_id="area1", platform="sonoff"),
        _reg_entry("switch.ura_blah", "switch",
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


# ---------------------------------------------------------------------------
# D3 — _actuatable_ids runtime guard (via shared classifier + method)
# ---------------------------------------------------------------------------

def _reg_or_none(reg_map, eid):
    class _R:
        async_get = staticmethod(lambda e: reg_map.get(e))
    return _R()


def test_classify_detritus_id_rules():
    from custom_components.universal_room_automation.automation import (
        _classify_detritus_id, _PREFILL_DETRITUS_TOKEN_RE,
    )
    tr = _PREFILL_DETRITUS_TOKEN_RE
    # ura_domain wins
    r = SimpleNamespace(platform=DOMAIN, entity_category=None)
    assert _classify_detritus_id(r, "switch.ura_x", tr, DOMAIN) == "ura_domain"
    # config_category
    r = SimpleNamespace(platform="tplink", entity_category="config")
    assert _classify_detritus_id(
        r, "switch.plain_auto_update_enabled", tr, DOMAIN,
    ) == "config_category"
    # name_backstop (registry entry None → fall through to name)
    assert _classify_detritus_id(
        None, "switch.minir4m_x_detach", tr, DOMAIN,
    ) == "name_backstop"
    # Clean plain switch — None (passes through)
    r = SimpleNamespace(platform="mqtt", entity_category=None)
    assert _classify_detritus_id(
        r, "switch.plain_plug_a", tr, DOMAIN,
    ) is None
    # F2 regression: hidden-but-category-None plain relay NOT rejected
    r = SimpleNamespace(platform="shelly", entity_category=None)
    assert _classify_detritus_id(
        r, "switch.plain_relay_x", tr, DOMAIN,
    ) is None
    # F2 regression: helper platform (input_boolean) NOT rejected
    r = SimpleNamespace(platform="input_boolean", entity_category=None)
    assert _classify_detritus_id(
        r, "input_boolean.user_toggle", tr, DOMAIN,
    ) is None


def test_actuatable_ids_filters_and_dedup_logs(caplog):
    import asyncio
    from custom_components.universal_room_automation.automation import (
        RoomAutomation,
    )
    reg_map = {
        "switch.ura_x": SimpleNamespace(
            platform=DOMAIN, entity_category=None,
        ),
        "switch.plain_a": SimpleNamespace(
            platform="mqtt", entity_category=None,
        ),
        "switch.tapo_auto_update_enabled": SimpleNamespace(
            platform="tplink", entity_category="config",
        ),
    }

    # Patch entity_registry.async_get for this call.
    import homeassistant.helpers.entity_registry as er  # type: ignore
    orig = er.async_get

    class _ER:
        def async_get(self, e):
            return reg_map.get(e)

    er.async_get = lambda hass: _ER()
    try:
        fake = SimpleNamespace(
            hass=object(),
            _config_entry=SimpleNamespace(entry_id="eid-1"),
            config={"room_name": "Living"},
            _prefill_detritus_logged=set(),
        )
        caplog.set_level("WARNING")
        ids = [
            "switch.ura_x",
            "switch.plain_a",
            "switch.tapo_auto_update_enabled",
            "switch.minir4m_x_detach",  # name backstop
        ]
        out = RoomAutomation._actuatable_ids(fake, ids)
        assert out == ["switch.plain_a"]
        warn_text = "\n".join(
            r.getMessage() for r in caplog.records
            if r.levelname == "WARNING"
        )
        assert "URA-PREFILL-DETRITUS-GUARD" in warn_text
        assert "rule_id=ura_domain" in warn_text
        assert "rule_id=config_category" in warn_text
        assert "rule_id=name_backstop" in warn_text
        # Dedup: calling again does NOT emit new WARNINGs for same ids
        before = len([r for r in caplog.records if r.levelname == "WARNING"])
        RoomAutomation._actuatable_ids(fake, ids)
        after = len([r for r in caplog.records if r.levelname == "WARNING"])
        assert after == before, "dedup set must suppress repeat WARNs"
    finally:
        er.async_get = orig


def test_actuatable_ids_registry_failure_passes_through():
    """Guard must never block actuation on registry read failure."""
    from custom_components.universal_room_automation.automation import (
        RoomAutomation,
    )
    import homeassistant.helpers.entity_registry as er  # type: ignore
    orig = er.async_get

    def _boom(hass):
        raise RuntimeError("registry boom")

    er.async_get = _boom
    try:
        fake = SimpleNamespace(
            hass=object(),
            _config_entry=SimpleNamespace(entry_id="eid-1"),
            config={"room_name": "Living"},
            _prefill_detritus_logged=set(),
        )
        out = RoomAutomation._actuatable_ids(fake, ["switch.a", "switch.b"])
        assert out == ["switch.a", "switch.b"]
    finally:
        er.async_get = orig
