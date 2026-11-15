"""VISION-INTERIOR-SIGHTINGS-1 ship 1 surfaces: ``switch.ura_interior_vision``
(RestoreEntity, options-flow default), its Camera Census form field and
reload-suppress membership, and ``sensor.ura_interior_awareness`` (display).

REAL HA core and REAL switch / sensor / config_flow modules (shared
sighting-rig import scope). Oracles are literals.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse

PKG = "custom_components.universal_room_automation"
SWITCH = "switch.ura_interior_vision"


class _St:
    def __init__(self, s):
        self.state = s


def _integration_entry(C, enabled):
    opts = {} if enabled is None else {C.CONF_INTERIOR_VISION_ENABLED: enabled}
    return SimpleNamespace(entry_id="integ", data={
        C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_INTEGRATION}, options=opts)


@pytest.mark.asyncio
@pytest.mark.parametrize("stored, option, expect", [
    ("on", False, True), ("off", None, False), ("off", True, False),
    ("unavailable", None, True), ("unknown", False, False),
    (None, None, True), (None, False, False), (None, True, True),
])
async def test_interior_vision_switch_restore_and_default(
    mods, hass, monkeypatch, stored, option, expect,  # noqa: F811
):
    """A stored on / off wins; otherwise the Camera Census option, whose
    default is ON (no option -> ON)."""
    sw_mod = importlib.import_module(f"{PKG}.switch")
    C = mods.const
    ent = _integration_entry(C, option)
    monkeypatch.setattr(hass.config_entries, "async_entries",
                        lambda domain=None, *a, **k: [ent])
    hass.data.setdefault(C.DOMAIN, {}).pop(C.INTERIOR_VISION_SWITCH_HASS_KEY, None)
    sw = sw_mod.InteriorVisionSwitch(hass, SimpleNamespace(entry_id="cm"))
    sw.async_write_ha_state = lambda: None

    async def _last():
        return _St(stored) if stored is not None else None

    sw.async_get_last_state = _last
    await sw.async_added_to_hass()
    assert sw.is_on is expect
    assert sw.entity_id == SWITCH and sw.name == "Interior Vision"
    await sw.async_turn_off()
    assert sw.is_on is False
    assert hass.data[C.DOMAIN][C.INTERIOR_VISION_SWITCH_HASS_KEY] is False
    await sw.async_turn_on()
    assert sw.is_on is True


@pytest.mark.asyncio
async def test_switch_platform_registers_interior_vision(mods, hass):  # noqa: F811
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    sw_mod = importlib.import_module(f"{PKG}.switch")
    C = mods.const
    e = MockConfigEntry(domain=C.DOMAIN, entry_id="cm_iv", data={
        C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_COORDINATOR_MANAGER})
    e.add_to_hass(hass)
    added: list = []
    await sw_mod.async_setup_entry(hass, e, lambda ents, *a, **k: added.extend(ents))
    hits = [x for x in added if type(x).__name__ == "InteriorVisionSwitch"]
    assert len(hits) == 1 and hits[0].entity_id == SWITCH


def test_camera_census_form_has_interior_vision_field_default_on(mods):  # noqa: F811
    """The switch has a config-flow entry (operator: "Switches should have a
    config flow entry"): the Camera Census options step offers
    `interior_vision_enabled`, default ON, and saving it never reloads the
    parent entry (reload-suppress allowlist)."""
    import asyncio

    import voluptuous as vol

    cf = importlib.import_module(f"{PKG}.config_flow")
    init = importlib.import_module(PKG)
    C = mods.const
    assert C.CONF_INTERIOR_VISION_ENABLED == "interior_vision_enabled"
    assert C.DEFAULT_INTERIOR_VISION_ENABLED is True
    assert C.CONF_INTERIOR_VISION_ENABLED in init.INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS

    flow = cf.UniversalRoomAutomationOptionsFlow.__new__(cf.UniversalRoomAutomationOptionsFlow)
    entry = SimpleNamespace(entry_id="integ", data={C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_INTEGRATION},
                            options={})
    flow._config_entry = entry
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda d=None: []))
    shown = {}
    flow.async_show_form = lambda **kw: shown.update(kw) or kw
    asyncio.run(flow.async_step_camera_census())
    schema = shown["data_schema"].schema
    keys = {str(k): k for k in schema}
    assert C.CONF_INTERIOR_VISION_ENABLED in keys
    marker = keys[C.CONF_INTERIOR_VISION_ENABLED]
    assert isinstance(marker, vol.Optional) and marker.default() is True


def test_interior_awareness_sensor_reads_records(mods):  # noqa: F811
    """State = unnamed in rooms with a LIVE reading (missing rooms excluded);
    attributes per room; every attribute unrecorded."""
    sensor = importlib.import_module(f"{PKG}.sensor")
    sig = importlib.import_module(f"{PKG}.person_sighting")

    def _r(room, bodies, unnamed, status, live):
        return sig.RoomSighting(
            room=room, area_id=None, group_key=room, bodies=bodies, bodies_nvr=bodies,
            bodies_vision=None, bodies_source="nvr" if bodies is not None else None,
            named=(), named_sources=(), unnamed=unnamed, status=status,
            provenance="nvr" if bodies is not None else None, liveness=live,
            entered_via=("garage_a", "t") if room == "Family Room" else None,
            census_as_of=None, as_of=0.0)

    recs = (_r("Family Room", 2, 1, "unnamed_present", "live"),
            _r("Foyer", 3, 2, "unnamed_present", "live"),
            _r("Playroom", None, None, "missing", "held"))
    path = sig.PathRecord("r", "garage_a", 0.0, 2, "first_hop",
                          (("k", "Family Room", 1.0, 2, None),))
    presence = SimpleNamespace(get_room_sightings=lambda: recs,
                               get_last_path_records=lambda: (path,))
    hass_ = SimpleNamespace(data={mods.const.DOMAIN: {
        "coordinator_manager": SimpleNamespace(coordinators={"presence": presence})}})
    s = sensor.InteriorAwarenessSensor(hass_, SimpleNamespace(entry_id="integ"))
    assert s.native_value == 3
    attrs = s.extra_state_attributes
    assert attrs["rooms"]["Family Room"] == {
        "status": "unnamed_present", "bodies": 2, "unnamed": 1, "named_count": 0,
        "provenance": "nvr", "liveness": "live", "entered_via": ["garage_a", "t"]}
    assert attrs["rooms"]["Playroom"]["status"] == "missing"
    assert attrs["last_path"] == {"door": "garage_a", "n": 2, "n_source": "first_hop",
                                  "rooms": ["Family Room"]}
    assert set(attrs) <= set(sensor.InteriorAwarenessSensor._unrecorded_attributes)
    assert s.entity_id == "sensor.ura_interior_awareness"
    # No presence -> 0, never an error.
    s2 = sensor.InteriorAwarenessSensor(SimpleNamespace(data={}), SimpleNamespace(entry_id="i"))
    assert s2.native_value == 0
