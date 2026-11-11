"""FORM-CONDITIONAL-FIELDS-1 release 1 — D2 helpers + harness, D3 sections.

Plan: docs/planning/PLANNING_config_forms_sections_and_conditional_fields.md
rev 4 (§2 invariants, §3 save shapes, §5 D2/D3). Every test drives the REAL
step handlers on HA 2026.2.3 (``data_entry_flow.section`` is the real class
here, asserted in ``test_section_key_collisions_none``).

The moved-field oracle below is hand-written from plan §13.1 (rows 1-8,
14-67), NOT derived from the schema, so a field that silently drops out of
a section turns these tests red.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import voluptuous as vol

import _forms_harness as h
from custom_components.universal_room_automation import config_flow as cf
from custom_components.universal_room_automation.const import (
    CONF_ENTRY_TYPE,
    CONF_LIGHT_EVENING_BRIGHTNESS_PCT,
    CONF_LIGHT_EVENING_COLOR_KELVIN,
    CONF_LIGHT_SCENE_DAY,
    CONF_LIGHT_SCENE_EVENING,
    CONF_LIGHT_SCENE_SLEEP,
    CONF_MOTION_SENSORS,
    CONF_NIGHT_LIGHT_EVENING_BRIGHTNESS,
    CONF_NIGHT_LIGHT_EVENING_COLOR,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TARGET,
    CONF_SENSOR_CAPABILITIES,
    CONF_ZONE_THERMOSTAT,
    ENTRY_TYPE_ZONE_MANAGER,
)

# --- hand-written oracle: plan §13.1 -------------------------------------------

MOVED = {
    ("config", "integration_config"): [
        "outside_temp_sensor", "outside_humidity_sensor", "solar_production_sensor",
        "person_data_retention_days", "transition_detection_window",
        "electricity_rate", "notification_service", "notification_level"],
    ("options", "global_sensors"): ["outdoor_dark_lux", "electricity_rate"],
    ("options", "energy_sensors"): ["house_device_power_sensors"],
    ("options", "person_tracking"): ["person_data_retention_days", "transition_detection_window"],
    ("options", "camera_census"): [
        "census_cross_validation", "census_divergence_downgrade", "enhanced_census",
        "egress_identity_failsafe_strict", "census_ble_cancel_enabled",
        "auto_enable_person_detection", "census_hold_interior", "census_hold_exterior",
        "door_groups", "door_interior_neighbours", "main_entry_door",
        "perimeter_zone_sensors", "face_name_aliases"],
    ("options", "perimeter_alerting"): [
        "perimeter_enrichment_provider", "perimeter_enrichment_person_sensors",
        "perimeter_enrichment_model", "perimeter_enrichment_max_tokens",
        "perimeter_enrichment_provider_id", "exterior_snapshot_offset_s"],
    ("options", "zone_rooms"): ["zone_description"],
    ("options", "zone_media"): ["zone_player_mode"],
    ("options", "zone_hvac"): [
        "hvac_ac_load_sensor", "hvac_ac_ramp_zone_enabled", "hvac_thermostat_min_delta_f"],
    ("options", "zone_energy"): ["zone_power_sensors"],
    ("options", "zone_dynamic_preset"): [
        "zone_dynamic_preset_reset_offset_guest", "zone_dynamic_preset_sleep_enabled"],
    ("options", "sensors"): ["sensor_capabilities_json"],
    ("options", "devices"): [
        "night_light_sleep_brightness", "night_light_sleep_hue", "night_light_sleep_color",
        "night_light_day_brightness", "night_light_day_color"],
    ("options", "options_lighting_behaviour"): [
        "lights_on_entry_dark_only", "light_manual_on_hold_s", "light_manual_off_cooldown_s",
        "light_evening_brightness_pct", "light_evening_color_kelvin",
        "night_light_evening_brightness", "night_light_evening_color",
        "light_scene_day", "light_scene_evening", "light_scene_sleep"],
    ("options", "options_covers"): ["sunrise_offset", "sunset_offset"],
    ("options", "climate"): [
        "fan_speed_low_temp", "fan_speed_med_temp", "fan_speed_high_temp",
        "humidity_fan_max_runtime"],
}
assert sum(len(v) for v in MOVED.values()) == 62  # 48 A rows + 14 B rows (§13)

FAMILY = {
    "global_sensors": "integration", "energy_sensors": "integration",
    "person_tracking": "integration", "camera_census": "integration",
    "perimeter_alerting": "integration",
    "zone_rooms": "zm", "zone_media": "zm", "zone_hvac": "zm", "zone_energy": "zm",
    "zone_dynamic_preset": "zm",
    "sensors": "room", "devices": "room", "options_lighting_behaviour": "room",
    "options_covers": "room", "climate": "room",
}
OPTIONS_STEPS = sorted(FAMILY)
ZONE = "Master Suite"
SIBLING = "Entertainment"
THERMO = "climate.zone_1"
_ROOM_SEED = {CONF_MOTION_SENSORS: ["binary_sensor.room_pir"]}


# --- harness helpers -----------------------------------------------------------

class _ZmEntries:
    """``hass.config_entries`` fake for the Zone Manager save path."""

    def __init__(self, counter: h.ReloadCounter | None):
        self.counter = counter

    def __call__(self, entry, **kw):
        if "options" in kw:
            if self.counter is not None:
                self.counter.save(kw["options"])
            else:
                entry.options = kw["options"]
        if "data" in kw:
            entry.data = kw["data"]
        return True


def _zm_flow(zones: dict, *, count=False):
    entry = h.StubEntry(
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE_MANAGER},
        options={"zones": {k: dict(v) for k, v in zones.items()}},
        entry_id="zm1",
    )
    flow = h.options_flow("zm")
    flow._config_entry = entry
    counter = h.ReloadCounter(entry) if count else None
    flow.hass.config_entries.async_update_entry = MagicMock(
        side_effect=_ZmEntries(counter))
    flow._selected_zone_name = ZONE
    return flow, entry, counter


def _flow_for(step, options):
    fam = FAMILY[step]
    if fam == "zm":
        return _zm_flow({ZONE: options, SIBLING: dict(options)})[0:2]
    flow = h.options_flow(fam, options=options)
    return flow, flow._config_entry


def _stored(step, flow, entry, result):
    if FAMILY[step] == "zm":
        return dict(entry.options["zones"][ZONE])
    assert result["type"] == "create_entry", result
    return dict(result["data"])


def _render(flow, step):
    res = h.run(getattr(flow, f"async_step_{step}")(None))
    assert res["step_id"] == step and res.get("data_schema") is not None, res
    return res


def _save(step, options, *, omit=False, edit=None):
    """Render with ``options`` stored, submit what the frontend submits."""
    flow, entry = _flow_for(step, options)
    res = _render(flow, step)
    sub = h.frontend_submit(res["data_schema"], omit_sections=omit)
    if edit:
        for k, v in edit.items():
            sub.setdefault("advanced", {})[k] = v
    out = h.run(getattr(flow, f"async_step_{step}")(sub))
    return _stored(step, flow, entry, out)


def _seed(step) -> dict:
    base = dict(_ROOM_SEED) if FAMILY[step] == "room" else {}
    if FAMILY[step] == "zm":
        base = {CONF_ZONE_THERMOSTAT: THERMO}
    return _save(step, base)


def _distinct(key, value):
    special = {
        "door_interior_neighbours": {"front": ["camera.edit"]},
        "door_groups": {"camera_front": "front"},
        "face_name_aliases": ["Ojini=guest"],
    }
    if key in special:
        return special[key]
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    if isinstance(value, list):
        return list(value) + ["sensor.edit"]
    if isinstance(value, str) and value:
        return value + "_edit"
    return "sensor.edit"


# ==============================================================================
# D2 — helpers
# ==============================================================================

def _section_schema():
    return vol.Schema({
        vol.Optional("top", default=1): int,
        vol.Optional("advanced"): cf._advanced_section({
            vol.Optional("a", default=5): int,
            vol.Optional("b"): str,
        }),
    })


def test_flatten_sections_merges_section_up():
    flat, present = cf._flatten_sections(
        {"top": 1, "advanced": {"a": 7, "b": "x"}}, _section_schema())
    assert flat == {"top": 1, "a": 7, "b": "x"}
    assert present == frozenset({"advanced"})


@pytest.mark.parametrize("raw", [{"top": 1}, {"top": 1, "advanced": None},
                                 {"top": 1, "advanced": "junk"}])
def test_flatten_sections_ignores_absent_or_non_dict_section(raw):
    flat, present = cf._flatten_sections(raw, _section_schema())
    assert flat == {"top": 1}
    assert present == frozenset()


def test_flatten_sections_section_wins_on_collision():
    flat, _ = cf._flatten_sections({"a": 1, "advanced": {"a": 2}}, _section_schema())
    assert flat == {"a": 2}


def test_flatten_sections_by_name_matches_by_schema():
    raw = {"top": 1, "advanced": {"a": 7}}
    assert cf._flatten_sections(raw, ("advanced",)) == cf._flatten_sections(
        raw, _section_schema())


def test_flatten_sections_does_not_mutate_input():
    raw = {"top": 1, "advanced": {"a": 7}}
    cf._flatten_sections(raw, _section_schema())
    assert raw == {"top": 1, "advanced": {"a": 7}}


def test_absent_field_defaults_unexpanded_section():
    """Case (a): a never-expanded section yields its inner ``default=``
    values; a field with no default yields nothing."""
    assert cf._absent_field_defaults(_section_schema(), {"top": 1}) == {"a": 5}
    assert cf._absent_field_defaults(_section_schema(), {"advanced": None}) == {"a": 5}


def test_absent_field_defaults_present_section_fills_nothing():
    """A section that WAS sent (even with a field cleared) is never filled."""
    assert cf._absent_field_defaults(_section_schema(), {"advanced": {}}) == {}


def test_absent_field_defaults_reads_default_not_suggested_value():
    schema = vol.Schema({
        vol.Optional("advanced"): cf._advanced_section({
            vol.Optional("g", description={"suggested_value": "x"}): str,
        }),
    })
    assert cf._absent_field_defaults(schema, {}) == {}


def _collisions(schema) -> list:
    """Build-time collision checker: a section key equal to a field key, an
    inner key equal to a top-level key, or one key in two sections."""
    out = []
    items = cf._schema_items(schema)
    top = {str(getattr(m, "schema", m)) for m, v in items.items() if not cf._is_section(v)}
    secs = {str(getattr(m, "schema", m)): v for m, v in items.items() if cf._is_section(v)}
    seen: dict = {}
    for sk, sv in secs.items():
        if sk in top:
            out.append(("section_eq_field", sk))
        for inner in cf._collect_schema_defaults(sv.schema):
            if inner in top:
                out.append(("inner_eq_top", inner))
            if inner in seen:
                out.append(("dup_inner", inner))
            seen[inner] = sk
            if inner in secs:
                out.append(("inner_eq_section", inner))
    return out


def test_section_key_collisions_none():
    # L6: the real HA section class must be in use, or the walk is blind.
    from homeassistant.data_entry_flow import section as ha_section
    assert cf._ha_section is ha_section
    # Injected collision is caught (the checker is not vacuous).
    bad = vol.Schema({
        vol.Optional("a", default=1): int,
        vol.Optional("advanced"): cf._advanced_section({vol.Optional("a"): int}),
    })
    assert _collisions(bad) == [("inner_eq_top", "a")]
    for flow, step in MOVED:
        if flow == "config":
            res = _render(h.config_flow(), step)
        else:
            f, _ = _flow_for(step, _ROOM_SEED if FAMILY[step] == "room" else {})
            res = _render(f, step)
        assert _collisions(res["data_schema"]) == [], (flow, step)


# ==============================================================================
# D3 — sections on every restructured step
# ==============================================================================

@pytest.mark.parametrize("flow_step", sorted(MOVED), ids=lambda fs: f"{fs[0]}-{fs[1]}")
def test_moved_fields_live_in_advanced_section(flow_step):
    flow, step = flow_step
    if flow == "config":
        res = _render(h.config_flow(), step)
    else:
        f, _ = _flow_for(step, _ROOM_SEED if FAMILY[step] == "room" else {})
        res = _render(f, step)
    walked = h.walk(res["data_schema"])
    in_adv = {k for k, s in walked.items() if s == "advanced"}
    assert in_adv == set(MOVED[flow_step])


def test_no_advanced_markers_schema_walk():
    """INV-3 (i): no rendered field anywhere carries an ``advanced`` marker."""
    def _walk(schema):
        for marker, val in cf._schema_items(schema).items():
            if cf._is_section(val):
                yield from _walk(val.schema)
            else:
                yield marker

    rendered = 0
    for flow, step in sorted(h.render_all()):
        f = h.config_flow() if flow == "config" else None
        if f is None:
            for kind in h.ENTRY_DATA:
                try:
                    res = h.run(getattr(h.options_flow(kind), f"async_step_{step}")(None))
                except Exception:  # noqa: BLE001
                    continue
                if res.get("step_id") == step and res.get("data_schema") is not None:
                    break
        else:
            res = h.run(getattr(f, f"async_step_{step}")(None))
        for marker in _walk(res["data_schema"]):
            desc = getattr(marker, "description", None)
            assert not (isinstance(desc, dict) and desc.get("advanced")), (step, marker)
        rendered += 1
    assert rendered >= 60


@pytest.mark.parametrize("flow_step", sorted(MOVED), ids=lambda fs: f"{fs[0]}-{fs[1]}")
def test_full_fields_render_without_advanced_mode(flow_step):
    """INV-3 (ii): with the HA flag False (the 2027.6 condition) the full
    field set renders, identical to the flag-True render."""
    flow, step = flow_step

    def _keys(flag):
        if flow == "config":
            f = h.config_flow()
        else:
            f, _ = _flow_for(step, _ROOM_SEED if FAMILY[step] == "room" else {})
        f.context = {"show_advanced_options": flag}
        assert f.show_advanced_options is flag
        return set(h.walk(_render(f, step)["data_schema"]))

    off, on = _keys(False), _keys(True)
    assert off == on
    assert set(MOVED[flow_step]) <= off


def test_no_show_advanced_options_source():
    """Lint only (INV-3 is proven by the two tests above)."""
    import re
    src = (h.COMP / "config_flow.py").read_text()
    for pat in (r"show_advanced_options", r"_show_adv\b", r"advanced_hint",
                r"\b_adv\(", r"_filter_advanced", r"advanced_if_empty",
                r"_hidden_advanced_defaults"):
        assert not re.search(pat, src), pat


# --- INV-1a round trip ------------------------------------------------------

@pytest.mark.parametrize("step", OPTIONS_STEPS)
def test_forms_round_trip_options(step):
    """INV-1a on every restructured Options step: an untouched save stores
    the same dict whether the section is sent or never expanded, and no
    section key is ever stored."""
    s1 = _seed(step)
    assert "advanced" not in s1
    assert not ({"humidity_fan_advanced", "climate_backstop", "reconcile_advanced",
                 "auto_manual_devices"} & set(s1))
    assert _save(step, s1) == s1                 # section sent
    assert _save(step, s1, omit=True) == s1      # section never expanded


def test_forms_round_trip_create_integration_config():
    flow = h.config_flow()
    res = _render(flow, "integration_config")
    sent = h.frontend_submit(res["data_schema"])
    nxt = h.run(flow.async_step_integration_config(sent))
    d_sent = dict(flow._integration_data)
    flow2 = h.config_flow()
    _render(flow2, "integration_config")
    h.run(flow2.async_step_integration_config(
        h.frontend_submit(res["data_schema"], omit_sections=True)))
    d_omit = dict(flow2._integration_data)
    assert d_sent == d_omit
    assert "advanced" not in d_sent
    assert nxt["step_id"] == "energy_setup"


def test_create_unexpanded_section_stores_defaults():
    """Shape 3: a never-expanded section stores its inner defaults (the same
    keys the old Simple-mode backfill stored). Oracle hand-written from the
    const defaults."""
    from custom_components.universal_room_automation import const as c
    flow = h.config_flow()
    h.run(flow.async_step_integration_config({}))
    d = flow._integration_data
    assert d[c.CONF_ELECTRICITY_RATE] == 0.15 == c.DEFAULT_ELECTRICITY_RATE
    assert d[c.CONF_PERSON_DATA_RETENTION] == c.DEFAULT_PERSON_DATA_RETENTION
    assert d[c.CONF_TRANSITION_DETECTION_WINDOW] == c.DEFAULT_TRANSITION_WINDOW
    assert d[c.CONF_NOTIFY_LEVEL] == c.NOTIFY_LEVEL_ERRORS
    for absent in (c.CONF_OUTSIDE_TEMP_SENSOR, c.CONF_SOLAR_PRODUCTION_SENSOR,
                   c.CONF_NOTIFY_SERVICE, "advanced"):
        assert absent not in d, absent


def test_create_section_edit_lands_flat():
    from custom_components.universal_room_automation import const as c
    flow = h.config_flow()
    h.run(flow.async_step_integration_config(
        {"advanced": {c.CONF_ELECTRICITY_RATE: 0.42}}))
    assert flow._integration_data[c.CONF_ELECTRICITY_RATE] == 0.42
    # The present section was not backfilled: no other defaults appear.
    assert c.CONF_NOTIFY_LEVEL not in flow._integration_data


# --- INV-1b edit propagation -------------------------------------------------

_EDIT_CASES = [
    (step, key)
    for (flow, step), keys in sorted(MOVED.items()) if flow == "options"
    for key in keys
    if key != "sensor_capabilities_json"  # form-only; covered by the H2 tests
]


@pytest.mark.parametrize("step,key", _EDIT_CASES)
def test_forms_edit_propagates_options(step, key):
    s1 = _seed(step)
    value = _distinct(key, s1.get(key))
    after = _save(step, s1, edit={key: value})
    assert after.get(key) == value, (step, key)
    assert "advanced" not in after
    others = {k: v for k, v in after.items() if k != key}
    assert others == {k: v for k, v in s1.items() if k != key}


def test_zone_moved_mirror_key_reaches_sibling():
    """Shape 4: a moved zone_hvac key edited in the section reaches the
    sibling zone sharing the thermostat (and is stored flat)."""
    zones = {ZONE: {CONF_ZONE_THERMOSTAT: THERMO},
             SIBLING: {CONF_ZONE_THERMOSTAT: THERMO}}
    flow, entry, _ = _zm_flow(zones)
    res = _render(flow, "zone_hvac")
    sub = h.frontend_submit(res["data_schema"])
    sub["advanced"]["hvac_ac_load_sensor"] = "sensor.ac_power"
    h.run(flow.async_step_zone_hvac(sub))
    for name in (ZONE, SIBLING):
        z = entry.options["zones"][name]
        assert z["hvac_ac_load_sensor"] == "sensor.ac_power", name
        assert "advanced" not in z


def test_zone_dynamic_preset_section_reaches_sibling():
    zones = {ZONE: {CONF_ZONE_THERMOSTAT: THERMO},
             SIBLING: {CONF_ZONE_THERMOSTAT: THERMO}}
    flow, entry, _ = _zm_flow(zones)
    res = _render(flow, "zone_dynamic_preset")
    sub = h.frontend_submit(res["data_schema"])
    sub["advanced"]["zone_dynamic_preset_sleep_enabled"] = True
    h.run(flow.async_step_zone_dynamic_preset(sub))
    for name in (ZONE, SIBLING):
        assert entry.options["zones"][name]["zone_dynamic_preset_sleep_enabled"] is True


# --- H2 clear-on-absent sites ------------------------------------------------

_PIR = "binary_sensor.room_pir"
_CAPS = {_PIR: {"kind": "pir", "trust_class": "strong_evidence"}}


def test_options_sensors_omitted_section_keeps_capabilities():
    stored = {CONF_MOTION_SENSORS: [_PIR], CONF_SENSOR_CAPABILITIES: _CAPS}
    after = _save("sensors", stored, omit=True)
    assert after[CONF_SENSOR_CAPABILITIES] == _CAPS
    assert after[CONF_SENSOR_CAPABILITIES][_PIR]["trust_class"] == "strong_evidence"


def test_options_sensors_present_section_cleared_json_clears():
    """Discriminator: a guard that never clears passes the omitted test and
    fails this one."""
    stored = {CONF_MOTION_SENSORS: [_PIR], CONF_SENSOR_CAPABILITIES: _CAPS}
    flow, entry = _flow_for("sensors", stored)
    res = _render(flow, "sensors")
    sub = h.frontend_submit(res["data_schema"], omit_sections=True)
    sub["advanced"] = {}                       # sent, JSON field cleared
    out = h.run(flow.async_step_sensors(sub))
    # The per-entity "What can it see?" dropdown still carries the kind
    # (it is pre-filled with the stored kind); the JSON-only trust_class
    # is what the cleared JSON removes.
    caps = out["data"].get(CONF_SENSOR_CAPABILITIES) or {}
    assert "trust_class" not in caps.get(_PIR, {}), caps


def test_options_sensors_present_section_round_trips_json():
    stored = {CONF_MOTION_SENSORS: [_PIR], CONF_SENSOR_CAPABILITIES: _CAPS}
    assert _save("sensors", stored)[CONF_SENSOR_CAPABILITIES] == _CAPS


_CLEARABLES = {
    CONF_LIGHT_EVENING_BRIGHTNESS_PCT: 40,
    CONF_LIGHT_EVENING_COLOR_KELVIN: 2700,
    CONF_NIGHT_LIGHT_EVENING_BRIGHTNESS: 5,
    CONF_NIGHT_LIGHT_EVENING_COLOR: 2200,
    CONF_LIGHT_SCENE_DAY: "scene.day",
    CONF_LIGHT_SCENE_EVENING: "scene.evening",
    CONF_LIGHT_SCENE_SLEEP: "scene.sleep",
}


def test_options_lighting_omitted_section_keeps_clearables():
    after = _save("options_lighting_behaviour", dict(_CLEARABLES), omit=True)
    for k, v in _CLEARABLES.items():
        assert after[k] == v, k


def test_options_lighting_section_present_cleared_key_clears():
    flow, entry = _flow_for("options_lighting_behaviour", dict(_CLEARABLES))
    res = _render(flow, "options_lighting_behaviour")
    sub = h.frontend_submit(res["data_schema"])
    del sub["advanced"][CONF_LIGHT_SCENE_DAY]   # operator cleared the field
    out = h.run(flow.async_step_options_lighting_behaviour(sub))
    assert CONF_LIGHT_SCENE_DAY not in out["data"]
    assert out["data"][CONF_LIGHT_SCENE_EVENING] == "scene.evening"


# --- rows 69-70: integration_config branches ----------------------------------

def test_integration_config_energy_step_always_shown():
    for flag in (False, True):
        flow = h.config_flow()
        flow.context = {"show_advanced_options": flag}
        nxt = h.run(flow.async_step_integration_config({}))
        assert nxt["type"] == "form" and nxt["step_id"] == "energy_setup"


def test_integration_config_notify_fallback_blank_service():
    flow = h.config_flow()
    h.run(flow.async_step_integration_config(
        {CONF_NOTIFY_TARGET: "notify.mobile_app_pixel"}))
    assert flow._integration_data[CONF_NOTIFY_SERVICE] == "notify.mobile_app_pixel"
    # Section sent with the service left blank: same fallback.
    flow = h.config_flow()
    h.run(flow.async_step_integration_config(
        {CONF_NOTIFY_TARGET: "notify.mobile_app_pixel", "advanced": {}}))
    assert flow._integration_data[CONF_NOTIFY_SERVICE] == "notify.mobile_app_pixel"


def test_integration_config_notify_explicit_service_kept():
    flow = h.config_flow()
    h.run(flow.async_step_integration_config({
        CONF_NOTIFY_TARGET: "notify.mobile_app_pixel",
        "advanced": {CONF_NOTIFY_SERVICE: "notify.family"},
    }))
    assert flow._integration_data[CONF_NOTIFY_SERVICE] == "notify.family"


def test_integration_config_non_notify_target_no_fallback():
    flow = h.config_flow()
    h.run(flow.async_step_integration_config({CONF_NOTIFY_TARGET: ""}))
    assert CONF_NOTIFY_SERVICE not in flow._integration_data


# --- INV-P: reloads ------------------------------------------------------------

@pytest.mark.parametrize("step", OPTIONS_STEPS)
def test_move_only_save_zero_reloads(step):
    """INV-P (i): an untouched save (section sent or not) reloads nothing,
    driven through HA's write rule and the REAL update listener."""
    s1 = _seed(step)
    for omit in (False, True):
        if FAMILY[step] == "zm":
            zones = {ZONE: dict(s1), SIBLING: dict(s1)}
            flow, entry, counter = _zm_flow(zones, count=True)
            res = _render(flow, step)
            h.run(getattr(flow, f"async_step_{step}")(
                h.frontend_submit(res["data_schema"], omit_sections=omit)))
            assert counter.reloads == 0, (step, omit)
            continue
        flow, entry = _flow_for(step, s1)
        counter = h.ReloadCounter(entry)
        res = _render(flow, step)
        out = h.run(getattr(flow, f"async_step_{step}")(
            h.frontend_submit(res["data_schema"], omit_sections=omit)))
        counter.save(out["data"])
        assert counter.reloads == 0, (step, omit)


@pytest.mark.parametrize("step,key,expected", [
    # live-apply keys (in the entry's suppress set today, plan §13.1)
    ("climate", "fan_speed_low_temp", 0),
    ("climate", "humidity_fan_max_runtime", 0),
    ("camera_census", "census_cross_validation", 0),
    ("perimeter_alerting", "exterior_snapshot_offset_s", 0),
    # reload keys: exactly one (the save reached the listener)
    ("options_covers", "sunrise_offset", 1),
    ("camera_census", "census_hold_interior", 1),
])
def test_live_apply_key_stays_live_after_move(step, key, expected):
    """INV-P (ii): a moved live-apply key edited in its section still
    reloads nothing; a moved reload key reloads exactly once."""
    s1 = _seed(step)
    flow, entry = _flow_for(step, s1)
    counter = h.ReloadCounter(entry)
    res = _render(flow, step)
    sub = h.frontend_submit(res["data_schema"])
    sub["advanced"][key] = _distinct(key, sub["advanced"].get(key))
    out = h.run(getattr(flow, f"async_step_{step}")(sub))
    counter.save(out["data"])
    assert counter.reloads == expected


@pytest.mark.parametrize("step", OPTIONS_STEPS)
def test_step_render_no_extra_registry_scans(step, monkeypatch):
    """INV-P (iii): restructured Options steps do no area-entity scan on
    render (sections are static schema). Oracle: 0, hand-written."""
    calls = []
    monkeypatch.setattr(
        cf.UniversalRoomAutomationOptionsFlow, "_get_area_entities",
        lambda self, *a, **k: calls.append(a) or [], raising=False)
    f, _ = _flow_for(step, _ROOM_SEED if FAMILY[step] == "room" else {})
    _render(f, step)
    assert calls == []


# ==============================================================================
# Strings: section labels moved, not copied (rev 4, M1)
# ==============================================================================

@pytest.mark.parametrize("rel", h.STRING_FILES)
@pytest.mark.parametrize("flow_step", sorted(MOVED), ids=lambda fs: f"{fs[0]}-{fs[1]}")
def test_section_strings_moved_not_copied(rel, flow_step):
    flow, step = flow_step
    st = h.load_strings()[rel][flow]["step"][step]
    adv = st["sections"]["advanced"]
    assert adv["name"]
    for key in MOVED[flow_step]:
        assert adv["data"].get(key), (rel, step, key)
        assert key not in (st.get("data") or {}), (rel, step, key, "copied")
        assert key not in (st.get("data_description") or {}), (rel, step, key, "copied")
        assert adv.get("data_description", {}).get(key), (rel, step, key, "help")


# --- FORMS-RELEASE-1 fix-up: climate step A-L1 + climate_backstop clear rule ---
# Literal keys (not the imported constants) so a renamed constant cannot move
# the oracle with it.
_CAP = "humidity_fan_presence_runtime_cap_s"
_MAXRT = "humidity_fan_max_runtime"
_HOLD_D = "hvac_vacancy_hold"
_HOLD_N = "hvac_vacancy_hold_night"


def _climate_submit(stored, *, sections=True):
    flow, entry = _flow_for("climate", {**_ROOM_SEED, **stored})
    res = _render(flow, "climate")
    return flow, h.frontend_submit(res["data_schema"], omit_sections=not sections)


def test_climate_cap_checked_against_stored_max_when_section_unsent():
    """A-L1 repro: stored max runtime 900, Advanced section not sent, cap set
    to 1800 → the save is rejected (the pair the form rejects when both are
    on screen)."""
    flow, sub = _climate_submit({_MAXRT: 900, _CAP: 600}, sections=False)
    assert "advanced" not in sub and _MAXRT not in sub
    sub[_CAP] = 1800
    out = h.run(flow.async_step_climate(sub))
    assert out["type"] == "form", out
    assert out["errors"] == {"base": "presence_runtime_cap_above_max"}


def test_climate_cap_below_stored_max_section_unsent_saves():
    flow, sub = _climate_submit({_MAXRT: 900, _CAP: 600}, sections=False)
    sub[_CAP] = 899
    out = h.run(flow.async_step_climate(sub))
    assert out["type"] == "create_entry", out
    assert out["data"][_CAP] == 899 and out["data"][_MAXRT] == 900


def test_climate_cap_checked_against_sent_max():
    """Section sent: the SUBMITTED max wins over the stored one (both ways)."""
    flow, sub = _climate_submit({_MAXRT: 900, _CAP: 600})
    sub["advanced"][_MAXRT] = 3600
    sub[_CAP] = 1800
    out = h.run(flow.async_step_climate(sub))
    assert out["type"] == "create_entry", out
    assert out["data"][_MAXRT] == 3600 and out["data"][_CAP] == 1800

    flow, sub = _climate_submit({_MAXRT: 3600, _CAP: 600})
    sub["advanced"][_MAXRT] = 900
    sub[_CAP] = 1800
    out = h.run(flow.async_step_climate(sub))
    assert out["errors"] == {"base": "presence_runtime_cap_above_max"}


def test_climate_backstop_omitted_keeps_hvac_holds():
    """CLIMATE-BACKSTOP-SECTION-CLEAR-ON-ABSENT-1: an unsent climate_backstop
    section keeps the stored per-room HVAC hold overrides."""
    flow, sub = _climate_submit({_HOLD_D: 300, _HOLD_N: 1200}, sections=False)
    assert "climate_backstop" not in sub
    out = h.run(flow.async_step_climate(sub))
    assert out["type"] == "create_entry", out
    assert out["data"][_HOLD_D] == 300
    assert out["data"][_HOLD_N] == 1200


def test_climate_backstop_sent_cleared_hold_clears():
    """Discriminator: a guard that never clears passes the omitted test and
    fails this one; the untouched sibling is kept."""
    flow, sub = _climate_submit({_HOLD_D: 300, _HOLD_N: 1200})
    assert sub["climate_backstop"][_HOLD_D] == 300
    del sub["climate_backstop"][_HOLD_D]          # operator blanked it
    out = h.run(flow.async_step_climate(sub))
    assert out["type"] == "create_entry", out
    assert _HOLD_D not in out["data"]
    assert out["data"][_HOLD_N] == 1200


def test_climate_stored_inverted_hold_pair_does_not_block_unrelated_save():
    """The day/night pair keeps its same-submit rule. A stored inverted pair
    (legal: one-sided edits; the runtime clamp is the backstop) must not
    block a save that never sent the climate_backstop section."""
    flow, sub = _climate_submit({_HOLD_D: 900, _HOLD_N: 600}, sections=False)
    out = h.run(flow.async_step_climate(sub))
    assert out["type"] == "create_entry", out
    assert out["data"][_HOLD_D] == 900 and out["data"][_HOLD_N] == 600
