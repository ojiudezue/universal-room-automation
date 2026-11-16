"""VISION-INTERIOR-SIGHTINGS-1 ship 2 surfaces and budget rules (plan §12,
§9.D3, closure N9): ``select.ura_interior_describe_access`` (Q2),
``number.ura_interior_vision_daily_calls`` / ``_daily_cost_usd``, their CM
reload-suppress membership, the episode type, and the pure budget rule
(caps, cost cap, describe reserve). REAL HA core and REAL select / number
modules (shared sighting-rig import scope). Boundaries use literals."""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse

PKG = "custom_components.universal_room_automation"


def _iv():
    return importlib.import_module(f"{PKG}.interior_vision")


def _skip(**kw):
    base = dict(switch_on=True, kill=False, cap=60, cost_cap=0.5, calls_today=0,
                cost_today=0.0, est_cost=0.0003, reserved=10, purpose="describe")
    base.update(kw)
    return _iv().budget_skip(**base)


# ---------------------------------------------------------------- budget
def test_budget_switch_kill_and_caps():
    assert _skip() is None
    assert _skip(switch_on=False) == "switch_off"
    assert _skip(kill=True) == "kill"
    assert _skip(cap=0) == "cap_reached"
    assert _skip(calls_today=59) is None
    assert _skip(calls_today=60) == "cap_reached"
    assert _skip(cost_cap=0.0) == "cost_cap_reached"
    assert _skip(cost_today=0.4997) is None
    assert _skip(cost_today=0.4998) == "cost_cap_reached"


def test_sampling_leaves_describe_reserve():
    """Closure N9: with cap 60 and 10 reserved, sampling stops at 50 calls
    (49 still samples); describe still calls at 50 and stops only at 60.
    The same share of the cost cap is kept (0.5 x 10/60 = 0.0833)."""
    s = "sampling"
    assert _skip(purpose=s, calls_today=49) is None
    assert _skip(purpose=s, calls_today=50) == "reserved_for_describe"
    assert _skip(calls_today=50) is None
    assert _skip(calls_today=59) is None
    assert _skip(purpose=s, cost_today=0.4163) is None
    assert _skip(purpose=s, cost_today=0.4170) == "reserved_for_describe"
    assert _skip(purpose=s, calls_today=50, reserved=0) is None


# ---------------------------------------------------------------- select
@pytest.mark.asyncio
async def test_describe_access_select_publishes_and_persists(mods, hass, monkeypatch):  # noqa: F811
    sel_mod = importlib.import_module(f"{PKG}.select")
    C = mods.const
    writes = []
    monkeypatch.setattr(hass.config_entries, "async_update_entry",
                        lambda entry, **kw: writes.append(kw) or True)
    entry = SimpleNamespace(entry_id="cm", data={}, options={})
    sel = sel_mod.InteriorDescribeAccessSelect(hass, entry)
    sel.async_write_ha_state = lambda: None
    assert sel.entity_id == "select.ura_interior_describe_access"
    assert sel.current_option == "operator"
    assert sel.options == ["operator", "operator_affect", "residents", "any_resolved"]
    assert hass.data[C.DOMAIN][C.INTERIOR_DESCRIBE_ACCESS_HASS_KEY] == "operator"
    await sel.async_select_option("residents")
    assert hass.data[C.DOMAIN][C.INTERIOR_DESCRIBE_ACCESS_HASS_KEY] == "residents"
    assert writes[-1]["options"]["interior_describe_access"] == "residents"
    await sel.async_select_option("bogus")
    assert sel.current_option == "residents" and len(writes) == 1
    stored = SimpleNamespace(entry_id="cm", data={}, options={"interior_describe_access": "any_resolved"})
    assert sel_mod.InteriorDescribeAccessSelect(hass, stored).current_option == "any_resolved"
    bad = SimpleNamespace(entry_id="cm", data={}, options={"interior_describe_access": "x"})
    assert sel_mod.InteriorDescribeAccessSelect(hass, bad).current_option == "operator"


# --------------------------------------------------------------- numbers
@pytest.mark.asyncio
@pytest.mark.parametrize("cls, key, conf, default, setv, clamp_in, clamp_out", [
    ("InteriorVisionDailyCallsNumber", "interior_vision_daily_calls",
     "interior_vision_daily_calls", 60, 12, 9999, 500),
    ("InteriorVisionDailyCostNumber", "interior_vision_daily_cost_usd",
     "interior_vision_daily_cost_usd", 0.5, 1.25, 99.0, 20.0),
])
async def test_cap_numbers_publish_and_persist(mods, hass, monkeypatch, cls, key, conf,  # noqa: F811
                                               default, setv, clamp_in, clamp_out):
    num_mod = importlib.import_module(f"{PKG}.number")
    C = mods.const
    writes = []
    monkeypatch.setattr(hass.config_entries, "async_update_entry",
                        lambda entry, **kw: writes.append(kw) or True)
    entry = SimpleNamespace(entry_id="cm", data={}, options={})
    n = getattr(num_mod, cls)(hass, entry)
    n.async_write_ha_state = lambda: None
    assert hass.data[C.DOMAIN][key] == default
    await n.async_set_native_value(setv)
    assert hass.data[C.DOMAIN][key] == setv and writes[-1]["options"][conf] == setv
    await n.async_set_native_value(clamp_in)
    assert hass.data[C.DOMAIN][key] == clamp_out
    assert getattr(num_mod, cls)(
        hass, SimpleNamespace(entry_id="cm", data={}, options={conf: 0})).native_value == 0


@pytest.mark.asyncio
async def test_cm_platforms_register_ship2_entities(mods, hass):  # noqa: F811
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    C = mods.const
    e = MockConfigEntry(domain=C.DOMAIN, entry_id="cm_iv2", data={
        C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_COORDINATOR_MANAGER})
    e.add_to_hass(hass)
    for mod_name, want in (("select", {"InteriorDescribeAccessSelect"}),
                           ("number", {"InteriorVisionDailyCallsNumber",
                                       "InteriorVisionDailyCostNumber"})):
        mod = importlib.import_module(f"{PKG}.{mod_name}")
        added: list = []
        await mod.async_setup_entry(hass, e, lambda ents, *a, **k: added.extend(ents))
        assert want <= {type(x).__name__ for x in added}, mod_name


def test_ship2_options_never_reload_the_cm(mods):  # noqa: F811
    init = importlib.import_module(PKG)
    for key in ("interior_vision_daily_calls", "interior_vision_daily_cost_usd",
                "interior_describe_access"):
        assert key in init.OPTIONS_RELOAD_SUPPRESS_KEYS, key
        assert key in init._NO_LIVE_ATTR_KEYS, key


def test_description_episode_type_registered_not_writer_backed(mods):  # noqa: F811
    C = mods.const
    assert "interior_description" in C.MEMORY_EPISODE_TYPES
    assert "interior_description" not in C.MEMORY_WRITER_BACKED_EPISODE_TYPES


@pytest.mark.asyncio
async def test_cap_number_identity_device_and_clamps(mods, hass, monkeypatch):  # noqa: F811
    num_mod = importlib.import_module(f"{PKG}.number")
    C = mods.const
    monkeypatch.setattr(hass.config_entries, "async_update_entry", lambda e, **kw: True)
    n = num_mod.InteriorVisionDailyCallsNumber(hass, SimpleNamespace(entry_id="cm", data={},
                                                                     options={}))
    n.async_write_ha_state = lambda: None
    assert n.unique_id == "universal_room_automation_interior_vision_daily_calls"
    assert n.entity_id == "number.ura_interior_vision_daily_calls"
    assert n.device_info["identifiers"] == {(C.DOMAIN, "coordinator_manager")}
    await n.async_set_native_value(-4)
    assert hass.data[C.DOMAIN][C.INTERIOR_VISION_CAP_HASS_KEY] == 0
    await n.async_set_native_value(3.7)
    assert hass.data[C.DOMAIN][C.INTERIOR_VISION_CAP_HASS_KEY] == 3


def _bare_sampler(C, data, options):
    entry = SimpleNamespace(data={C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_INTEGRATION}, options=options)
    other = SimpleNamespace(data={C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_ROOM},
                            options={C.CONF_INTERIOR_VISION_ENABLED: True})
    hass_ = SimpleNamespace(data={C.DOMAIN: data},
                            config_entries=SimpleNamespace(async_entries=lambda d: [other, entry]))
    return _iv().InteriorVisionSampler(
        hass_, now_fn=lambda: 0.0, emit=lambda f: None, log_row=lambda *a: None,
        fire=lambda *a: None, names_fn=list, provider_fn=lambda: None)


def test_sampler_switch_default_and_bad_cap_fallbacks(mods):  # noqa: F811
    """Before the switch entity loads, the integration entry's option is
    the default (a room entry's key is ignored); an unreadable cap falls
    back to the rung-3 defaults."""
    C = mods.const
    s = _bare_sampler(C, {}, {C.CONF_INTERIOR_VISION_ENABLED: False})
    assert s.switch_on() is False
    assert _bare_sampler(C, {}, {}).switch_on() is True
    assert _bare_sampler(C, {C.INTERIOR_VISION_SWITCH_HASS_KEY: True},
                         {C.CONF_INTERIOR_VISION_ENABLED: False}).switch_on() is True
    bad = _bare_sampler(C, {C.INTERIOR_VISION_CAP_HASS_KEY: "x",
                            C.INTERIOR_VISION_COST_HASS_KEY: "y"}, {})
    assert (bad.daily_cap(), bad.cost_cap()) == (60, 0.5)
