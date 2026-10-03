"""ZONE-DIALOGS-CLEANUP-1 D2 + HOUSE-DIALOGS-CLEANUP-1 D4 (slice B).

Simple/Advanced markers on the Zone Manager and House options steps,
reusing the room mechanism (``_adv`` / ``_filter_advanced`` /
``advanced_hint_for``):

- Advanced-only keys are absent in Simple mode and present in Advanced mode.
- I2: a stored non-default value is rendered in Simple mode anyway, so no
  stored value is ever unreachable. Dead fields (O1) follow the same rule.
- I3: a Simple-mode save never drops or overwrites a value that was not on
  the form (zone saves merge into the zone dict, House saves merge options),
  and a shared-thermostat sibling zone is not touched for hidden keys.
- Reload safety: a Simple-mode House save that changes one allowlisted key
  stays inside ``INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`` (no reload).

Drives the REAL ``UniversalRoomAutomationOptionsFlow`` handlers with a stub
entry + MagicMock hass (same harness as the room trimmed-menu tests).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import voluptuous as vol

from _room_menu_helpers import StubEntry, make_hass, render, run, schema_keys
from custom_components.universal_room_automation import config_flow as cf
from custom_components.universal_room_automation.const import (
    CONF_AUTO_ENABLE_PERSON_DETECTION,
    CONF_CAMERA_PERSON_ENTITIES,
    CONF_CENSUS_BLE_CANCEL_ENABLED,
    CONF_CENSUS_CROSS_VALIDATION,
    CONF_CENSUS_DIVERGENCE_DOWNGRADE,
    CONF_CENSUS_HOLD_EXTERIOR,
    CONF_CENSUS_HOLD_INTERIOR,
    CONF_EGRESS_CAMERAS,
    CONF_EGRESS_IDENTITY_ENABLED,
    CONF_EGRESS_IDENTITY_FAILSAFE_STRICT,
    CONF_ELECTRICITY_RATE,
    CONF_ENHANCED_CENSUS,
    CONF_ENTRY_TYPE,
    CONF_EXTERIOR_SNAPSHOT_OFFSET_S,
    CONF_FACE_RECOGNITION_ENABLED,
    CONF_GUEST_VLAN_SSID,
    CONF_HOUSE_DEVICE_POWER_SENSORS,
    CONF_KNOWN_FACE_GUESTS,
    CONF_OUTDOOR_DARK_LUX,
    CONF_PERIMETER_ALERT_HOURS_END,
    CONF_PERIMETER_ALERT_HOURS_START,
    CONF_PERIMETER_ALERT_NOTIFY_SERVICE,
    CONF_PERIMETER_ALERT_NOTIFY_TARGET,
    CONF_PERIMETER_CAMERAS,
    CONF_PERIMETER_ENRICHMENT_ENABLED,
    CONF_PERIMETER_ENRICHMENT_MAX_TOKENS,
    CONF_PERIMETER_ENRICHMENT_MODEL,
    CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS,
    CONF_PERIMETER_ENRICHMENT_PROVIDER,
    CONF_PERIMETER_ENRICHMENT_PROVIDER_ID,
    CONF_PERIMETER_VEHICLE_HOURS_END,
    CONF_PERIMETER_VEHICLE_HOURS_START,
    CONF_PERSON_DATA_RETENTION,
    CONF_TRANSITION_DETECTION_WINDOW,
    CONF_ZONE_DESCRIPTION,
    CONF_ZONE_ENERGY_SENSORS,
    CONF_ZONE_PLAYER_MODE,
    CONF_ZONE_POWER_SENSORS,
    CONF_ZONE_ROOMS,
    CONF_ZONE_THERMOSTAT,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ZONE,
    ENTRY_TYPE_ZONE_MANAGER,
    ZONE_PLAYER_MODE_FALLBACK,
    ZONE_PLAYER_MODE_INDEPENDENT,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST,
    CONF_ZONE_DYNAMIC_PRESET_SLEEP_ENABLED,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_const import (
    CONF_HVAC_AC_LOAD_SENSOR,
    CONF_HVAC_AC_RAMP_ZONE_ENABLED,
    DEFAULT_HVAC_AC_RAMP_ZONE_ENABLED,
)

ZONE = "Master Suite"
SIBLING = "Entertainment"
THERMO = "climate.zone_1"

# (step, key, non-default value) — D2 Advanced keys + O1 dead fields.
ZONE_ADVANCED = [
    ("zone_rooms", CONF_ZONE_DESCRIPTION, "a note"),
    ("zone_media", CONF_ZONE_PLAYER_MODE, ZONE_PLAYER_MODE_INDEPENDENT),
    ("zone_hvac", CONF_HVAC_AC_LOAD_SENSOR, "sensor.ac_power"),
    ("zone_hvac", CONF_HVAC_AC_RAMP_ZONE_ENABLED, not DEFAULT_HVAC_AC_RAMP_ZONE_ENABLED),
    ("zone_energy", CONF_ZONE_POWER_SENSORS, ["sensor.zone_power"]),
    ("zone_dynamic_preset", CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST, False),
    ("zone_dynamic_preset", CONF_ZONE_DYNAMIC_PRESET_SLEEP_ENABLED, True),
]

# Factory-default stored zone (every Advanced key present AT its default).
ZONE_DEFAULTS = {
    CONF_ZONE_DESCRIPTION: "",
    CONF_ZONE_ROOMS: [],
    CONF_ZONE_PLAYER_MODE: ZONE_PLAYER_MODE_FALLBACK,
    CONF_ZONE_THERMOSTAT: THERMO,
    CONF_HVAC_AC_LOAD_SENSOR: "",
    CONF_HVAC_AC_RAMP_ZONE_ENABLED: DEFAULT_HVAC_AC_RAMP_ZONE_ENABLED,
    CONF_ZONE_POWER_SENSORS: [],
    CONF_ZONE_ENERGY_SENSORS: ["sensor.zone_energy"],
    CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST: True,
    CONF_ZONE_DYNAMIC_PRESET_SLEEP_ENABLED: False,
}

# (step, key, non-default value) — D4 Advanced keys + O1 dead fields.
HOUSE_ADVANCED = [
    ("global_sensors", CONF_OUTDOOR_DARK_LUX, 123.0),
    ("global_sensors", CONF_ELECTRICITY_RATE, 0.31),
    ("energy_sensors", CONF_HOUSE_DEVICE_POWER_SENSORS, ["sensor.dev_power"]),
    ("person_tracking", CONF_PERSON_DATA_RETENTION, 30),
    ("person_tracking", CONF_TRANSITION_DETECTION_WINDOW, 60),
    ("camera_census", CONF_CENSUS_CROSS_VALIDATION, False),
    ("camera_census", CONF_CENSUS_DIVERGENCE_DOWNGRADE, False),
    ("camera_census", CONF_ENHANCED_CENSUS, False),
    ("camera_census", CONF_EGRESS_IDENTITY_FAILSAFE_STRICT, False),
    ("camera_census", CONF_CENSUS_BLE_CANCEL_ENABLED, False),
    ("camera_census", CONF_AUTO_ENABLE_PERSON_DETECTION, False),
    ("camera_census", CONF_CENSUS_HOLD_INTERIOR, 17),
    ("camera_census", CONF_CENSUS_HOLD_EXTERIOR, 11),
    ("perimeter_alerting", CONF_PERIMETER_ENRICHMENT_PROVIDER, "other"),
    ("perimeter_alerting", CONF_PERIMETER_ENRICHMENT_MODEL, "other-model"),
    ("perimeter_alerting", CONF_PERIMETER_ENRICHMENT_MAX_TOKENS, 900),
    ("perimeter_alerting", CONF_PERIMETER_ENRICHMENT_PROVIDER_ID, "prov-1"),
    ("perimeter_alerting", CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS, ["binary_sensor.p"]),
    ("perimeter_alerting", CONF_EXTERIOR_SNAPSHOT_OFFSET_S, 9),
]

# A full prior House save at factory defaults (every Advanced key present).
HOUSE_DEFAULTS = {
    CONF_OUTDOOR_DARK_LUX: cf.DEFAULT_OUTDOOR_DARK_LUX,
    CONF_ELECTRICITY_RATE: cf.DEFAULT_ELECTRICITY_RATE,
    CONF_HOUSE_DEVICE_POWER_SENSORS: [],
    CONF_PERSON_DATA_RETENTION: cf.DEFAULT_PERSON_DATA_RETENTION,
    CONF_TRANSITION_DETECTION_WINDOW: cf.DEFAULT_TRANSITION_WINDOW,
    CONF_CAMERA_PERSON_ENTITIES: ["camera.living"],
    CONF_EGRESS_CAMERAS: ["camera.front_door"],
    CONF_PERIMETER_CAMERAS: ["camera.yard"],
    CONF_FACE_RECOGNITION_ENABLED: cf.DEFAULT_FACE_RECOGNITION_ENABLED,
    CONF_EGRESS_IDENTITY_ENABLED: cf.DEFAULT_EGRESS_IDENTITY_ENABLED,
    CONF_KNOWN_FACE_GUESTS: [],
    CONF_GUEST_VLAN_SSID: "",
    CONF_CENSUS_CROSS_VALIDATION: True,
    CONF_CENSUS_DIVERGENCE_DOWNGRADE: cf.DEFAULT_CENSUS_DIVERGENCE_DOWNGRADE,
    CONF_ENHANCED_CENSUS: True,
    CONF_EGRESS_IDENTITY_FAILSAFE_STRICT: cf.DEFAULT_EGRESS_IDENTITY_FAILSAFE_STRICT,
    CONF_CENSUS_BLE_CANCEL_ENABLED: cf.DEFAULT_CENSUS_BLE_CANCEL_ENABLED,
    CONF_AUTO_ENABLE_PERSON_DETECTION: cf.DEFAULT_AUTO_ENABLE_PERSON_DETECTION,
    CONF_CENSUS_HOLD_INTERIOR: cf.DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES,
    CONF_CENSUS_HOLD_EXTERIOR: cf.DEFAULT_CENSUS_HOLD_EXTERIOR_MINUTES,
    CONF_PERIMETER_VEHICLE_HOURS_START: cf.DEFAULT_PERIMETER_VEHICLE_HOURS_START,
    CONF_PERIMETER_VEHICLE_HOURS_END: cf.DEFAULT_PERIMETER_VEHICLE_HOURS_END,
    CONF_PERIMETER_ENRICHMENT_ENABLED: cf.DEFAULT_PERIMETER_ENRICHMENT_ENABLED,
    CONF_PERIMETER_ENRICHMENT_PROVIDER: cf.DEFAULT_PERIMETER_ENRICHMENT_PROVIDER,
    CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS: [],
    CONF_PERIMETER_ENRICHMENT_MODEL: cf.DEFAULT_PERIMETER_ENRICHMENT_MODEL,
    CONF_PERIMETER_ENRICHMENT_MAX_TOKENS: cf.DEFAULT_PERIMETER_ENRICHMENT_MAX_TOKENS,
    CONF_PERIMETER_ENRICHMENT_PROVIDER_ID: "",
    CONF_EXTERIOR_SNAPSHOT_OFFSET_S: cf.DEFAULT_EXTERIOR_SNAPSHOT_OFFSET_S,
}


# --- harness ---------------------------------------------------------------

def _zm_flow(zones: dict, adv: bool = False):
    entry = StubEntry(
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE_MANAGER},
        options={"zones": {k: dict(v) for k, v in zones.items()}},
        entry_id="zm1",
    )
    hass = make_hass()

    def _update(e, **kw):
        if "options" in kw:
            e.options = kw["options"]
        if "data" in kw:
            e.data = kw["data"]
        return True

    hass.config_entries.async_update_entry = MagicMock(side_effect=_update)
    flow = cf.UniversalRoomAutomationOptionsFlow(entry)
    flow.hass = hass
    flow.context = {"show_advanced_options": adv}
    flow._selected_zone_name = ZONE
    return flow, entry


def _house_flow(options: dict, adv: bool = False):
    entry = StubEntry(
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION},
        options=dict(options),
        entry_id="house1",
    )
    flow = cf.UniversalRoomAutomationOptionsFlow(entry)
    flow.hass = make_hass()
    flow.context = {"show_advanced_options": adv}
    return flow, entry


def _simple_submission(result) -> dict:
    """What the frontend would submit for a rendered form: every field's
    default, skipping fields with no default (left empty)."""
    out = {}
    for key, val in cf._collect_schema_defaults(result["data_schema"]).items():
        if val is vol.UNDEFINED:
            continue
        out[key] = val() if callable(val) else val
    return out


def _submit(flow, step, user_input):
    return run(getattr(flow, f"async_step_{step}")(dict(user_input)))


# --- D2 zone: classification ----------------------------------------------

@pytest.mark.parametrize("step,key,_val", ZONE_ADVANCED)
def test_zone_advanced_key_hidden_in_simple_shown_in_advanced(step, key, _val):
    flow, _ = _zm_flow({ZONE: ZONE_DEFAULTS}, adv=False)
    off = render(flow, step)
    assert key not in schema_keys(off), (step, key)
    flow, _ = _zm_flow({ZONE: ZONE_DEFAULTS}, adv=True)
    on = render(flow, step)
    assert key in schema_keys(on), (step, key)


@pytest.mark.parametrize("step,key,val", ZONE_ADVANCED)
def test_zone_i2_non_default_value_forces_render(step, key, val):
    flow, _ = _zm_flow({ZONE: {**ZONE_DEFAULTS, key: val}}, adv=False)
    assert key in schema_keys(render(flow, step)), (step, key, val)


def test_zone_absent_key_counts_as_default():
    flow, _ = _zm_flow({ZONE: {CONF_ZONE_THERMOSTAT: THERMO}}, adv=False)
    keys = schema_keys(render(flow, "zone_hvac"))
    assert keys == {CONF_ZONE_THERMOSTAT}


def test_zone_hvac_simple_shows_hint_and_thermostat_only():
    flow, _ = _zm_flow({ZONE: ZONE_DEFAULTS}, adv=False)
    res = render(flow, "zone_hvac")
    assert schema_keys(res) == {CONF_ZONE_THERMOSTAT}
    assert res["description_placeholders"]["advanced_hint"] == cf.ADVANCED_HINT_HIDDEN
    flow, _ = _zm_flow({ZONE: ZONE_DEFAULTS}, adv=True)
    res = render(flow, "zone_hvac")
    assert len(schema_keys(res)) == 3
    assert res["description_placeholders"]["advanced_hint"] == cf.ADVANCED_HINT_SHOWN


def test_zone_legacy_entry_i2_and_hidden():
    """Legacy ENTRY_TYPE_ZONE entries use the same rule on merged data."""
    entry = StubEntry(
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE, "zone_name": ZONE},
        options={CONF_ZONE_PLAYER_MODE: ZONE_PLAYER_MODE_FALLBACK},
        entry_id="z1",
    )
    flow = cf.UniversalRoomAutomationOptionsFlow(entry)
    flow.hass = make_hass()
    flow.context = {"show_advanced_options": False}
    flow._selected_zone_name = None
    flow._selected_zone_entry_id = None
    assert CONF_ZONE_PLAYER_MODE not in schema_keys(render(flow, "zone_media"))
    entry.options = {CONF_ZONE_PLAYER_MODE: ZONE_PLAYER_MODE_INDEPENDENT}
    assert CONF_ZONE_PLAYER_MODE in schema_keys(render(flow, "zone_media"))


# --- D2 zone: I3 save guard -------------------------------------------------

ZONE_SAVE_STEPS = ["zone_rooms", "zone_media", "zone_hvac", "zone_energy",
                   "zone_dynamic_preset"]


@pytest.mark.parametrize("step", ZONE_SAVE_STEPS)
def test_zone_i3_simple_save_keeps_hidden_values(step):
    flow, entry = _zm_flow({ZONE: ZONE_DEFAULTS}, adv=False)
    sub = _simple_submission(render(flow, step))
    hidden = {k for s, k, _ in ZONE_ADVANCED if s == step}
    assert not (hidden & set(sub)), "fixture: hidden keys must not be submitted"
    if step == "zone_rooms":
        sub["zone_name"] = ZONE
    _submit(flow, step, sub)
    saved = entry.options["zones"][ZONE]
    for key in hidden:
        assert key in saved, (step, key)
        assert saved[key] == ZONE_DEFAULTS[key], (step, key, saved[key])


def test_zone_rooms_save_keeps_description_when_not_submitted():
    """A stored description survives a save whose form did not carry it."""
    flow, entry = _zm_flow({ZONE: {**ZONE_DEFAULTS, CONF_ZONE_DESCRIPTION: "kept"}})
    _submit(flow, "zone_rooms", {"zone_name": ZONE, "zone_is_outdoor": False})
    assert entry.options["zones"][ZONE][CONF_ZONE_DESCRIPTION] == "kept"


def test_zone_rooms_legacy_save_keeps_description_when_not_submitted():
    entry = StubEntry(
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE, "zone_name": ZONE},
        options={CONF_ZONE_DESCRIPTION: "kept"},
        entry_id="z1",
    )
    flow = cf.UniversalRoomAutomationOptionsFlow(entry)
    hass = make_hass()
    hass.config_entries.async_update_entry = MagicMock()
    flow.hass = hass
    flow.context = {"show_advanced_options": False}
    flow._selected_zone_name = None
    flow._selected_zone_entry_id = None
    _submit(flow, "zone_rooms", {"zone_name": ZONE})
    opts = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert opts[CONF_ZONE_DESCRIPTION] == "kept"


@pytest.mark.parametrize("step", ["zone_hvac", "zone_energy", "zone_dynamic_preset"])
def test_zone_i3_sibling_hidden_values_untouched(step):
    """A shared-thermostat sibling with DIFFERENT hidden values keeps them:
    the mirror only carries keys that were on the form."""
    sib = dict(ZONE_DEFAULTS)
    for s, key, val in ZONE_ADVANCED:
        if s == step:
            sib[key] = val
    flow, entry = _zm_flow({ZONE: ZONE_DEFAULTS, SIBLING: sib}, adv=False)
    sub = _simple_submission(render(flow, step))
    _submit(flow, step, sub)
    saved_sib = entry.options["zones"][SIBLING]
    for s, key, val in ZONE_ADVANCED:
        if s == step:
            assert saved_sib[key] == val, (step, key, saved_sib[key])


def test_zone_mirror_sets_unchanged():
    assert cf.MIRROR_KEYS_ZONE_HVAC == frozenset({
        "zone_thermostat", "hvac_ac_load_sensor", "hvac_ac_ramp_zone_enabled",
        "zone_vacancy_sweep_enabled",
    })
    assert cf.MIRROR_KEYS_ZONE_ENERGY == frozenset({
        "zone_power_sensors", "zone_energy_sensors",
    })
    assert cf.MIRROR_KEYS_ZONE_DPM == frozenset({
        "zone_dynamic_preset_enabled", "zone_dynamic_preset_offset",
        "zone_dynamic_preset_reset_offset_guest",
        "zone_dynamic_preset_sleep_enabled",
    })
    for name in ("ROOMS", "MEDIA", "PERSONS", "CAMERAS"):
        assert getattr(cf, f"MIRROR_KEYS_ZONE_{name}") == frozenset()


# --- D4 House: classification ----------------------------------------------

@pytest.mark.parametrize("step,key,_val", HOUSE_ADVANCED)
def test_house_advanced_key_hidden_in_simple_shown_in_advanced(step, key, _val):
    flow, _ = _house_flow(HOUSE_DEFAULTS, adv=False)
    assert key not in schema_keys(render(flow, step)), (step, key)
    flow, _ = _house_flow(HOUSE_DEFAULTS, adv=True)
    assert key in schema_keys(render(flow, step)), (step, key)


@pytest.mark.parametrize("step,key,val", HOUSE_ADVANCED)
def test_house_i2_non_default_value_forces_render(step, key, val):
    flow, _ = _house_flow({**HOUSE_DEFAULTS, key: val}, adv=False)
    assert key in schema_keys(render(flow, step)), (step, key, val)


def test_house_i2_value_in_entry_data_also_forces_render():
    entry = StubEntry(
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION, CONF_OUTDOOR_DARK_LUX: 50.0},
        options={}, entry_id="house1",
    )
    flow = cf.UniversalRoomAutomationOptionsFlow(entry)
    flow.hass = make_hass()
    flow.context = {"show_advanced_options": False}
    assert CONF_OUTDOOR_DARK_LUX in schema_keys(render(flow, "global_sensors"))


def test_camera_census_simple_has_at_most_seven_fields():
    flow, _ = _house_flow({}, adv=False)
    keys = schema_keys(render(flow, "camera_census"))
    assert len(keys) <= 7, sorted(keys)
    assert keys == {
        CONF_CAMERA_PERSON_ENTITIES, CONF_EGRESS_CAMERAS, CONF_PERIMETER_CAMERAS,
        CONF_FACE_RECOGNITION_ENABLED, CONF_EGRESS_IDENTITY_ENABLED,
        CONF_KNOWN_FACE_GUESTS, CONF_GUEST_VLAN_SSID,
    }
    flow, _ = _house_flow({}, adv=True)
    assert len(schema_keys(render(flow, "camera_census"))) == 15


def test_camera_census_field_order():
    flow, _ = _house_flow({}, adv=True)
    order = [getattr(m, "schema", m)
             for m in render(flow, "camera_census")["data_schema"].schema]
    assert order[:7] == [
        CONF_CAMERA_PERSON_ENTITIES, CONF_EGRESS_CAMERAS, CONF_PERIMETER_CAMERAS,
        CONF_FACE_RECOGNITION_ENABLED, CONF_EGRESS_IDENTITY_ENABLED,
        CONF_KNOWN_FACE_GUESTS, CONF_GUEST_VLAN_SSID,
    ]


def test_house_hint_placeholder_present():
    for step in ("global_sensors", "energy_sensors", "person_tracking",
                 "camera_census", "perimeter_alerting"):
        flow, _ = _house_flow(HOUSE_DEFAULTS, adv=False)
        res = render(flow, step)
        assert res["description_placeholders"]["advanced_hint"] == cf.ADVANCED_HINT_HIDDEN, step


# --- D4 House: I3 save guard ------------------------------------------------

@pytest.mark.parametrize("step", sorted({s for s, _, _ in HOUSE_ADVANCED}))
def test_house_i3_simple_save_keeps_hidden_values(step):
    flow, _ = _house_flow(HOUSE_DEFAULTS, adv=False)
    sub = _simple_submission(render(flow, step))
    hidden = {k for s, k, _ in HOUSE_ADVANCED if s == step}
    assert not (hidden & set(sub))
    res = _submit(flow, step, sub)
    for key in hidden:
        assert key in res["data"], (step, key)
        assert res["data"][key] == HOUSE_DEFAULTS[key], (step, key)


# --- D4 House: reload safety ------------------------------------------------

def _listener_reloads(pre: dict, post: dict) -> bool:
    """Drive the real integration branch of ``_async_update_listener``.

    Returns True when it schedules a reload. The per-key dispatch is stubbed
    to succeed (fresh-read keys are vacuous there anyway)."""
    import custom_components.universal_room_automation as ura

    hass = MagicMock()
    hass.data = {ura.DOMAIN: {"integration_last_applied_options": {"house1": dict(pre)}}}
    entry = MagicMock()
    entry.entry_id = "house1"
    entry.title = "URA"
    entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION}
    entry.options = dict(post)
    orig = ura._dispatch_integration_key_signals
    ura._dispatch_integration_key_signals = lambda h, e, keys: set(keys)
    try:
        run(ura._async_update_listener(hass, entry))
    finally:
        ura._dispatch_integration_key_signals = orig
    reloaded = hass.async_create_task.called
    if reloaded:
        hass.async_create_task.call_args.args[0].close()
    return reloaded


@pytest.mark.parametrize("step,key,val", [
    ("camera_census", CONF_KNOWN_FACE_GUESTS, ["Ojini"]),
    ("perimeter_alerting", CONF_PERIMETER_ENRICHMENT_ENABLED, True),
])
def test_house_simple_save_one_allowlisted_key_does_not_reload(step, key, val):
    import custom_components.universal_room_automation as ura

    assert key in ura.INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS
    flow, _ = _house_flow(HOUSE_DEFAULTS, adv=False)
    sub = _simple_submission(render(flow, step))
    sub[key] = val
    post = _submit(flow, step, sub)["data"]
    changed = {k for k in HOUSE_DEFAULTS.keys() | post.keys()
               if HOUSE_DEFAULTS.get(k) != post.get(k)}
    assert changed == {key}, sorted(changed)
    assert changed <= ura.INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS
    assert _listener_reloads(HOUSE_DEFAULTS, post) is False


def test_perimeter_save_with_retired_keys_reloads_once():
    """Plan review finding 3: an entry still holding the 4 retired keys
    reloads on its first perimeter save (the pop changes them). Accepted,
    pre-existing, one-time."""
    pre = {
        **HOUSE_DEFAULTS,
        CONF_PERIMETER_ALERT_NOTIFY_SERVICE: "notify.x",
        CONF_PERIMETER_ALERT_NOTIFY_TARGET: "t",
        CONF_PERIMETER_ALERT_HOURS_START: 22,
        CONF_PERIMETER_ALERT_HOURS_END: 6,
    }
    flow, _ = _house_flow(pre, adv=False)
    sub = _simple_submission(render(flow, "perimeter_alerting"))
    post = _submit(flow, "perimeter_alerting", sub)["data"]
    assert _listener_reloads(pre, post) is True
    # Second save from the cleaned state does not reload.
    flow, _ = _house_flow(post, adv=False)
    sub = _simple_submission(render(flow, "perimeter_alerting"))
    sub[CONF_PERIMETER_ENRICHMENT_ENABLED] = True
    post2 = _submit(flow, "perimeter_alerting", sub)["data"]
    assert _listener_reloads(post, post2) is False


# --- shared helper: vol.All back-reference ----------------------------------

def test_schema_walkers_treat_vol_all_as_leaf():
    """vol.All keeps a back-reference to its parent schema in ``.schema``;
    the walkers must not recurse into it (the weather-comfort form has a
    vol.All offset field next to Advanced-marked fields)."""
    schema = vol.Schema({
        vol.Optional("offset", default=1.0): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
        vol.Optional("flag", default=True, description={"advanced": True}): bool,
    })
    assert cf._schema_has_advanced(schema) is True
    assert cf._collect_schema_defaults(schema) == {"offset": 1.0, "flag": True}
