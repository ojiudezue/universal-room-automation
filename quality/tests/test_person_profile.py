"""Arc step 8 D1 + pick_media (PLANNING_identity_actions_v6.md §5.1-§5.3).

Drives the REAL People options-flow steps (``_forms_harness`` stub entries +
MagicMock hass, the pattern of the form tests), the REAL CM options-update
listener, the REAL profile sensor class and the pure ``person_profiles``
module. Oracles are written by hand from the plan, never recomputed.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import voluptuous as vol

from _forms_harness import StubEntry, make_hass, options_flow, run
from custom_components.universal_room_automation import config_flow as cf
from custom_components.universal_room_automation import person_profiles as pp
from custom_components.universal_room_automation.const import (
    CONF_ENTRY_TYPE,
    CONF_MUSIC_ON_ARRIVAL_START,
    CONF_PERSON_PROFILES,
    CONF_ROOM_MEDIA_PLAYER,
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
    CONF_TRACKED_PERSONS,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ROOM,
    ROOM_TYPE_BATHROOM,
    ROOM_TYPE_BEDROOM,
)

DOMAIN = "universal_room_automation"
MEDIA_A = {"entity_id": "media_player.ma_kitchen", "media_content_id": "library://playlist/1",
           "media_content_type": "playlist"}
MEDIA_D = {"media_content_id": "library://playlist/day", "media_content_type": "playlist"}
MEDIA_E = {"media_content_id": "library://playlist/eve", "media_content_type": "playlist"}
MEDIA_R = {"media_content_id": "library://playlist/room", "media_content_type": "playlist"}


def _play(m):
    return {"media_content_id": m["media_content_id"], "media_content_type": m["media_content_type"]}


# ---------------------------------------------------------------------------
# Rig
# ---------------------------------------------------------------------------

def _rooms():
    return [
        StubEntry({CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "Master Bedroom",
                   CONF_ROOM_TYPE: ROOM_TYPE_BEDROOM, CONF_ROOM_MEDIA_PLAYER: "media_player.sonos"},
                  entry_id="r_master"),
        StubEntry({CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "Master Bath",
                   CONF_ROOM_TYPE: ROOM_TYPE_BATHROOM}, entry_id="r_bath"),
        StubEntry({CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "Kitchen",
                   CONF_ROOM_TYPE: "kitchen", CONF_ROOM_MEDIA_PLAYER: "media_player.k"},
                  entry_id="r_kitchen"),
    ]


def _hass(tracked=("Oji Udezue", "person.ezinne"), visits=None):
    hass = make_hass()
    integ = StubEntry({CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
                       CONF_TRACKED_PERSONS: list(tracked)}, entry_id="integ")
    entries = [integ, *_rooms()]
    hass.config_entries.async_entries = lambda domain=None: entries
    hass.data = {DOMAIN: {}}
    if visits is not None:
        class _DB:
            def __init__(self):
                self.calls = []

            async def get_closed_person_visits(self, since, until, limit):
                self.calls.append((since, until, limit))
                return visits
        hass.data[DOMAIN]["database"] = _DB()
    return hass


def _flow(options=None, hass=None):
    return options_flow("cm", options=options or {}, hass=hass or _hass())


def _submit_profile(flow, rooms=None, automate=None):
    ui = {}
    if rooms is not None:
        ui["my_rooms"] = rooms
    if automate is not None:
        ui["automate"] = automate
    return run(flow.async_step_people_profile(ui))


def _open_person(flow, person):
    return run(flow.async_step_people({"person": person}))


def _saved_profiles(result):
    assert result["type"] == "create_entry", result
    return result["data"][CONF_PERSON_PROFILES]


# ---------------------------------------------------------------------------
# Keying, owners, store
# ---------------------------------------------------------------------------

def test_profile_keyed_by_one_id_rule():
    """Display-name and entity-id tracked_persons address the same profile."""
    opts = {CONF_PERSON_PROFILES: {"person.oji_udezue": {"auto_music": True}}}
    assert pp.get_person_profile(opts, "Oji Udezue") == {"auto_music": True}
    assert pp.get_person_profile(opts, "person.oji_udezue") == {"auto_music": True}
    # A profile saved under a display-name key normalises to the same id.
    opts2 = {CONF_PERSON_PROFILES: {"Oji Udezue": {"auto_scene": True}}}
    assert set(pp.profiles_from_options(opts2)) == {"person.oji_udezue"}
    # The People step stores under the person.* id whatever the config form.
    flow = _flow(hass=_hass(tracked=("Oji Udezue",)))
    _open_person(flow, "person.oji_udezue")
    res = _submit_profile(flow, rooms={"rooms_bedroom": ["r_master"], "rooms_bathroom": []},
                          automate={"auto_music": False, "auto_scene": False})
    assert set(_saved_profiles(res)) == {"person.oji_udezue"}


def test_owners_derived_shared_master():
    profiles = {
        "person.oji_udezue": {"rooms_bedroom": ["r_master"], "rooms_bathroom": ["r_bath"]},
        "person.ezinne": {"rooms_bedroom": ["r_master"]},
        "person.jaya": {"rooms_bedroom": ["r_jaya"]},
    }
    assert pp.room_owners(profiles, "r_master") == {"person.oji_udezue", "person.ezinne"}
    assert pp.room_owners(profiles, "r_bath") == {"person.oji_udezue"}
    assert pp.room_owners(profiles, "r_kitchen") == set()


def test_people_save_writes_no_room_entry_field():
    """Owners are derived: a save writes ONLY the CM person_profiles key."""
    hass = _hass()
    flow = _flow(options={"other": 1}, hass=hass)
    _open_person(flow, "person.ezinne")
    res = _submit_profile(flow, rooms={"rooms_bedroom": ["r_master"]},
                          automate={"auto_music": False})
    assert set(res["data"]) == {"other", CONF_PERSON_PROFILES}
    hass.config_entries.async_update_entry.assert_not_called()


def test_room_name_maps_to_entry_id():
    m = {"Master Bedroom": "r_master", "Kitchen": "r_kitchen"}
    assert pp.room_entry_id_for_name(m, "Master Bedroom") == "r_master"
    for bad in ("unknown", "away", "", None, "Garage"):
        assert pp.room_entry_id_for_name(m, bad) is None


# ---------------------------------------------------------------------------
# Master
# ---------------------------------------------------------------------------

def test_master_defaults_on_when_unset():
    assert pp.arrival_master_on({}) is True
    assert pp.arrival_master_on(None) is True
    flow = _flow(options={})
    form = run(flow.async_step_signal_responses())
    marker = next(k for k in form["data_schema"].schema if str(k) == CONF_MUSIC_ON_ARRIVAL_START)
    assert marker.default() is True


def test_master_false_respected():
    assert pp.arrival_master_on({CONF_MUSIC_ON_ARRIVAL_START: False}) is False
    flow = _flow(options={CONF_MUSIC_ON_ARRIVAL_START: False})
    form = run(flow.async_step_signal_responses())
    marker = next(k for k in form["data_schema"].schema if str(k) == CONF_MUSIC_ON_ARRIVAL_START)
    assert marker.default() is False


# ---------------------------------------------------------------------------
# No reload
# ---------------------------------------------------------------------------

def test_people_save_in_reload_suppress_allowlist():
    import custom_components.universal_room_automation as pkg
    assert "person_profiles" == CONF_PERSON_PROFILES
    assert CONF_PERSON_PROFILES in pkg.OPTIONS_RELOAD_SUPPRESS_KEYS
    assert CONF_PERSON_PROFILES in pkg._NO_LIVE_ATTR_KEYS
    applied = pkg._apply_in_place(SimpleNamespace(data={DOMAIN: {}}), None,
                                  {CONF_PERSON_PROFILES}, {CONF_PERSON_PROFILES: {}})
    assert applied == {CONF_PERSON_PROFILES}


class _CMEntry:
    def __init__(self, options):
        self.entry_id = "cm1"
        self.title = "CM"
        self.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}
        self.options = dict(options)


def _listener_hass(cm_entry):
    hass = MagicMock()
    hass.data = {DOMAIN: {"cm_last_applied_options": {cm_entry.entry_id: dict(cm_entry.options)}}}
    hass.async_create_task = MagicMock(side_effect=lambda c: c.close())
    return hass


def test_people_save_no_reload_real_options_update():
    """A real People save -> the real CM listener -> no reload, snapshot advances.

    Discriminator: the same listener reloads for a key not on the allowlist."""
    import custom_components.universal_room_automation as pkg
    cm = _CMEntry({"presence_enabled": True})
    flow = _flow(options=cm.options)
    _open_person(flow, "person.ezinne")
    res = _submit_profile(flow, rooms={"rooms_bedroom": ["r_master"]},
                          automate={"auto_music": True, "music_default": MEDIA_A})
    hass = _listener_hass(cm)
    cm.options = dict(res["data"])                      # what HA persists
    asyncio.new_event_loop().run_until_complete(pkg._async_update_listener(hass, cm))
    assert hass.async_create_task.call_count == 0
    snap = hass.data[DOMAIN]["cm_last_applied_options"]["cm1"]
    assert snap[CONF_PERSON_PROFILES] == res["data"][CONF_PERSON_PROFILES]
    # Discriminator: a non-allowlisted change reloads.
    hass2 = _listener_hass(cm)
    cm.options = {**cm.options, "presence_enabled": False}
    asyncio.new_event_loop().run_until_complete(pkg._async_update_listener(hass2, cm))
    assert hass2.async_create_task.call_count == 1


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

def test_suggestions_never_stored():
    visits = [
        ("Ezinne", "Master Bedroom", "2026-11-01 22:00:00", "2026-11-02 06:00:00"),  # 8 h
        ("person.ezinne", "Kitchen", "2026-11-02 07:00:00", "2026-11-02 09:00:00"),   # 2 h
        ("Oji Udezue", "Study A", "2026-11-02 09:00:00", "2026-11-02 19:00:00"),      # other person
    ]
    hass = _hass(visits=visits)
    flow = _flow(hass=hass)
    form = _open_person(flow, "person.ezinne")
    assert form["type"] == "form" and form["step_id"] == "people_profile"
    assert form["description_placeholders"]["suggestions"] == (
        "Suggested rooms from the last 30 days: Master Bedroom (80%), Kitchen (20%)."
    )
    res = _submit_profile(flow, rooms={"rooms_bedroom": []}, automate={"auto_music": False})
    blob = json.dumps(res["data"])
    assert "Suggested" not in blob and "Kitchen" not in blob and "Master Bedroom" not in blob
    assert hass.data[DOMAIN]["database"].calls[0][2] == 5000


# ---------------------------------------------------------------------------
# _cond / visible
# ---------------------------------------------------------------------------

@pytest.fixture
def no_marker(monkeypatch):
    monkeypatch.setattr(cf, "_VISIBLE_MARKER_CACHE", [None])


class _StubVisibleOptional(vol.Optional):
    """HA 2026.11-shaped marker: an Optional that accepts ``visible``."""

    def __init__(self, schema, visible=None, **kw):
        super().__init__(schema, **kw)
        self.visible = visible


@pytest.fixture
def stub_marker(monkeypatch):
    monkeypatch.setattr(cf, "_VISIBLE_MARKER_CACHE", [_StubVisibleOptional])


def test_cond_helper_falls_back_without_visible(no_marker):
    m = cf._cond("music_volume", {"field": "auto_music", "value": True}, default=0.3)
    assert type(m) is vol.Optional
    assert m.default() == 0.3
    assert not hasattr(m, "visible")
    # The real venv (HA 2026.2.3) has no visible marker: detection reads None.
    cache = list(cf._VISIBLE_MARKER_CACHE)
    cf._VISIBLE_MARKER_CACHE.clear()
    try:
        assert cf._visible_marker() is None
    finally:
        cf._VISIBLE_MARKER_CACHE[:] = cache


def test_cond_helper_passes_visible(stub_marker):
    cond = [{"field": "auto_music", "value": True}, {"field": "music_vary_time", "value": True}]
    m = cf._cond("music_day", cond)
    assert isinstance(m, _StubVisibleOptional)
    assert m.visible == cond


def _section_schema(form, section):
    return form["data_schema"].schema[next(
        k for k in form["data_schema"].schema if str(k) == section)].schema


def _visible_by_field(form):
    out = {}
    for sec in ("my_rooms", "automate"):
        for k in _section_schema(form, sec).schema:
            out[str(k)] = getattr(k, "visible", "ALWAYS")
    return out


EXPECTED_VISIBLE = {
    "rooms_bedroom": "ALWAYS",
    "rooms_bathroom": "ALWAYS",
    "auto_music": "ALWAYS",
    "music_default": {"field": "auto_music", "value": True},
    "music_volume": {"field": "auto_music", "value": True},
    "music_vary_time": {"field": "auto_music", "value": True},
    "music_day": [{"field": "auto_music", "value": True},
                  {"field": "music_vary_time", "value": True}],
    "music_evening": [{"field": "auto_music", "value": True},
                      {"field": "music_vary_time", "value": True}],
    "music_vary_room": {"field": "auto_music", "value": True},
    "auto_scene": "ALWAYS",
    "welcome_scene": {"field": "auto_scene", "value": True},
}


def test_people_schema_with_marker_serializes(stub_marker):
    import voluptuous_serialize
    from homeassistant.helpers import config_validation as cv
    flow = _flow()
    form = _open_person(flow, "person.ezinne")
    assert _visible_by_field(form) == EXPECTED_VISIBLE
    # Four fields show with every toggle off (the plan's §5.2 mock lists
    # exactly these four; its "5 visible" count is a plan miscount).
    assert sum(1 for v in _visible_by_field(form).values() if v == "ALWAYS") == 4
    voluptuous_serialize.convert(form["data_schema"], custom_serializer=cv.custom_serializer)


def test_people_form_matches_live_fixture(stub_marker):
    fx = Path(__file__).parent / "fixtures" / "people_form_visible_2026_11_1.json"
    if not fx.exists():
        pytest.skip("D1 B0 live spike PENDING: fixture not recorded yet")
    live = json.loads(fx.read_text())
    form = _open_person(_flow(), "person.ezinne")
    emitted = {k: v for k, v in _visible_by_field(form).items() if v != "ALWAYS"}
    assert emitted == live


def test_people_form_visible_conditions():
    from homeassistant import data_entry_flow
    import inspect
    opt = getattr(data_entry_flow, "Optional", None)
    if opt is None or "visible" not in inspect.signature(opt.__init__).parameters:
        pytest.skip("HA < 2026.11: no visible marker in this venv")
    cache = list(cf._VISIBLE_MARKER_CACHE)
    cf._VISIBLE_MARKER_CACHE.clear()
    try:
        form = _open_person(_flow(), "person.ezinne")
        assert _visible_by_field(form) == EXPECTED_VISIBLE
    finally:
        cf._VISIBLE_MARKER_CACHE[:] = cache


def test_fallback_form_shows_every_field(no_marker):
    form = _open_person(_flow(), "person.ezinne")
    assert set(_visible_by_field(form).values()) == {"ALWAYS"}
    assert len(_visible_by_field(form)) == 11


# ---------------------------------------------------------------------------
# Save validation (review 3.1 L2), merge, toggles
# ---------------------------------------------------------------------------

def test_music_on_without_pick_rejected():
    flow = _flow()
    _open_person(flow, "person.ezinne")
    res = _submit_profile(flow, rooms={"rooms_bedroom": ["r_master"]},
                          automate={"auto_music": True})
    assert res["type"] == "form"
    assert res["errors"] == {"base": "people_music_needs_pick"}


def test_scene_on_without_scene_rejected():
    flow = _flow()
    _open_person(flow, "person.ezinne")
    res = _submit_profile(flow, rooms={"rooms_bedroom": ["r_master"]},
                          automate={"auto_scene": True})
    assert res["errors"] == {"base": "people_scene_needs_pick"}


def test_hidden_fields_dropped_keep_stored_values():
    stored = {"auto_music": True, "music_default": MEDIA_A, "music_volume": 0.5,
              "music_vary_time": True, "music_day": MEDIA_D, "rooms_bedroom": ["r_master"]}
    flow = _flow(options={CONF_PERSON_PROFILES: {"person.ezinne": stored}})
    _open_person(flow, "person.ezinne")
    # 2026.11 drops hidden fields: only the toggle comes back, turned off.
    res = _submit_profile(flow, automate={"auto_music": False})
    prof = _saved_profiles(res)["person.ezinne"]
    assert prof["auto_music"] is False
    assert prof["music_default"] == MEDIA_A and prof["music_day"] == MEDIA_D
    assert prof["music_volume"] == 0.5 and prof["rooms_bedroom"] == ["r_master"]


def test_toggle_off_ignores_stale_fields():
    base = {"auto_music": True, "music_default": MEDIA_A, "rooms_bedroom": ["r_master"],
            "music_vary_time": False, "music_day": MEDIA_D, "music_evening": MEDIA_E,
            "music_vary_room": False, "music_by_room": {"r_master": MEDIA_R}}
    assert pp.pick_media(base, "r_master", "evening") == _play(MEDIA_A)
    assert pp.pick_media(base, "r_master", "day") == _play(MEDIA_A)
    off = {**base, "auto_music": False}
    assert pp.pick_media(off, "r_master", "day") is None
    assert pp.automated_action_count(off) == 0


def test_volume_bounded_on_save():
    assert pp.merge_profile_save({}, {"music_volume": 3})["music_volume"] == 1.0
    assert pp.merge_profile_save({}, {"music_volume": 0})["music_volume"] == 0.05
    assert pp.music_volume({}) == 0.30


# ---------------------------------------------------------------------------
# pick_media (§5.3)
# ---------------------------------------------------------------------------

FULL = {"auto_music": True, "music_default": MEDIA_A, "rooms_bedroom": ["r_master"],
        "rooms_bathroom": ["r_bath"], "music_vary_time": True, "music_day": MEDIA_D,
        "music_evening": MEDIA_E, "music_vary_room": True,
        "music_by_room": {"r_master": MEDIA_R}}


def test_pick_media_precedence():
    assert pp.pick_media(FULL, "r_master", "day") == _play(MEDIA_R)      # 1 room
    assert pp.pick_media(FULL, "r_bath", "evening") == _play(MEDIA_E)    # 2 time (no room pick)
    assert pp.pick_media(FULL, "r_bath", "day") == _play(MEDIA_D)
    no_time = {**FULL, "music_vary_time": False}
    assert pp.pick_media(no_time, "r_bath", "evening") == _play(MEDIA_A)  # 3 default


def test_pick_media_room_pick_needs_toggle_and_own_room():
    assert pp.pick_media({**FULL, "music_vary_room": False}, "r_master", "day") == _play(MEDIA_D)
    stale = {**FULL, "rooms_bedroom": []}                       # room removed from My rooms
    assert pp.pick_media(stale, "r_master", "day") == _play(MEDIA_D)


def test_pick_media_blank_or_invalid_falls_through():
    p = {**FULL, "music_by_room": {"r_master": {"media_content_id": "", "media_content_type": "x"}},
         "music_day": {"media_content_id": "x"}}
    assert pp.pick_media(p, "r_master", "day") == _play(MEDIA_A)
    none = {"auto_music": True}
    assert pp.pick_media(none, "r_master", "day") is None


def test_pick_media_sleep_slot_never_plays():
    assert pp.pick_media(FULL, "r_master", "sleep") is None


def test_pick_media_drops_browse_entity_id():
    got = pp.pick_media({"auto_music": True, "music_default": MEDIA_A}, "r_x", "day")
    assert got == {"media_content_id": "library://playlist/1", "media_content_type": "playlist"}


def test_stored_pick_keeps_browse_player_for_redisplay():
    """MediaSelector (no accept) rejects a value without entity_id
    (helpers/selector.py MediaSelector.__call__, 2026.2.3): the stored pick
    keeps it, so an unchanged re-save validates."""
    from homeassistant.helpers import selector
    saved = pp.merge_profile_save({}, {"music_default": MEDIA_A})["music_default"]
    selector.MediaSelector(selector.MediaSelectorConfig())(saved)
    with pytest.raises(vol.Invalid):
        selector.MediaSelector(selector.MediaSelectorConfig())(_play(MEDIA_A))


# ---------------------------------------------------------------------------
# Rooms music step
# ---------------------------------------------------------------------------

def test_room_step_one_field_per_player_room():
    flow = _flow()
    _open_person(flow, "person.ezinne")
    res = _submit_profile(
        flow, rooms={"rooms_bedroom": ["r_master"], "rooms_bathroom": ["r_bath"]},
        automate={"auto_music": True, "music_default": MEDIA_A, "music_vary_room": True},
    )
    assert res["type"] == "form" and res["step_id"] == "people_rooms_music"
    assert [str(k) for k in res["data_schema"].schema] == ["r_master"]
    assert res["description_placeholders"]["no_speaker"] == "Master Bath has no speaker."
    done = run(flow.async_step_people_rooms_music({"r_master": MEDIA_R}))
    prof = _saved_profiles(done)["person.ezinne"]
    assert prof["music_by_room"] == {"r_master": MEDIA_R}
    assert prof["music_vary_room"] is True


def test_room_step_skipped_without_vary_room():
    flow = _flow()
    _open_person(flow, "person.ezinne")
    res = _submit_profile(flow, rooms={"rooms_bedroom": ["r_master"]},
                          automate={"auto_music": True, "music_default": MEDIA_A})
    assert res["type"] == "create_entry"


def test_bathroom_picker_lists_only_bathrooms():
    form = _open_person(_flow(), "person.ezinne")
    sch = _section_schema(form, "my_rooms").schema
    bath = next(v for k, v in sch.items() if str(k) == "rooms_bathroom")
    bed = next(v for k, v in sch.items() if str(k) == "rooms_bedroom")
    assert [o["value"] for o in bath.config["options"]] == ["r_bath"]
    assert [o["value"] for o in bed.config["options"]] == ["r_kitchen", "r_bath", "r_master"]  # by name


def test_people_menu_entry_and_person_picker():
    flow = _flow()
    assert "people" in flow._cm_menu_options()
    form = run(flow.async_step_people())
    sel = form["data_schema"].schema[next(iter(form["data_schema"].schema))]
    assert [o["value"] for o in sel.config["options"]] == ["person.oji_udezue", "person.ezinne"]


def test_no_tracked_persons_aborts():
    res = run(_flow(hass=_hass(tracked=())).async_step_people())
    assert res["type"] == "abort" and res["reason"] == "people_no_persons"


# ---------------------------------------------------------------------------
# Profile sensor
# ---------------------------------------------------------------------------

def test_profile_sensor_state_and_attributes():
    from custom_components.universal_room_automation import sensor as s
    hass = _hass()
    cm = StubEntry({CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}, options={
        CONF_PERSON_PROFILES: {
            "person.oji_udezue": {"rooms_bedroom": ["r_master"], "auto_music": True,
                                  "music_default": MEDIA_A, "auto_scene": True,
                                  "welcome_scene": "scene.welcome"},
            "person.ezinne": {"rooms_bedroom": ["r_master"]},
        }}, entry_id="cm")
    sensors = s._person_profile_sensors(hass, cm)
    assert [x.entity_id for x in sensors] == ["sensor.ura_person_profile_oji_udezue",
                                              "sensor.ura_person_profile_ezinne"]
    oji, ez = sensors
    assert oji.native_value == 2 and ez.native_value == 0
    attrs = oji.extra_state_attributes
    assert attrs["rooms"] == ["Master Bedroom"]
    assert attrs["shared_room_owners"] == {"Master Bedroom": ["Ezinne", "Oji Udezue"]}
    assert attrs["music"] == {"music_default": "library://playlist/1"}
    assert attrs["welcome_scene"] == "scene.welcome"
    assert set(attrs) <= set(s.PersonProfileSensor._unrecorded_attributes)
    # Fresh read: a save shows with no reload.
    cm.options[CONF_PERSON_PROFILES]["person.ezinne"]["auto_scene"] = True
    assert ez.native_value == 1


def test_cm_sensor_setup_creates_profile_sensors():
    """Wire-in anchor: the REAL CM branch of sensor.async_setup_entry adds one
    profile sensor per tracked person."""
    from custom_components.universal_room_automation import sensor as s
    hass = _hass()
    cm = StubEntry({CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}, entry_id="cm")
    cm.async_on_unload = lambda *_a, **_k: None
    got: list = []
    run(s.async_setup_entry(hass, cm, lambda ents, *a, **k: got.extend(ents)))
    ids = [e.entity_id for e in got if isinstance(e, s.PersonProfileSensor)]
    assert ids == ["sensor.ura_person_profile_oji_udezue", "sensor.ura_person_profile_ezinne"]


# ---------------------------------------------------------------------------
# D6 episode types
# ---------------------------------------------------------------------------

def test_episode_types_registered():
    from custom_components.universal_room_automation import const as c
    assert c.ARRIVAL_MUSIC_EPISODE_TYPE == "arrival_music"
    assert c.WELCOME_SCENE_EPISODE_TYPE == "welcome_scene"
    assert {"arrival_music", "welcome_scene"} <= c.MEMORY_EPISODE_TYPES
    # No writer yet (D2/D3): not in the writer-health set, or it would page.
    assert not ({"arrival_music", "welcome_scene"} & c.MEMORY_WRITER_BACKED_EPISODE_TYPES)
