"""SC-LOCK-SWEEP-EXCLUDE-1 / SC-LOCK-REGIME-DOOR-LOCKS-1 D1 — options flow.

Plan rev 3 D1: drives the REAL ``async_step_coordinator_security`` with a
stand-in ``self`` (same pattern as test_sc_garage_lockout
test_lockout_config_roundtrip) and the REAL HA selector / voluptuous schema
from the venv. No source greps.
"""

from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import pytest

from _lockout_harness import URA, load

const = load("const")
R = load("domain_coordinators.security_lock_regime")
cf = load("config_flow")

DOOR = "lock.doorlock_kwikset_zwave_frontentry"
BED = "lock.master_bedroom_lock"
LOCK_A = "lock.konnected_f0f5bd523b00_lock"
OJI = "person.oji_udezue"
EZ = "person.ezinne"


def _step():
    for name in dir(cf):
        obj = getattr(cf, name)
        if isinstance(obj, type) and hasattr(obj, "async_step_coordinator_security"):
            return obj.async_step_coordinator_security
    raise AssertionError("no options flow with async_step_coordinator_security")


def _fake(options=None):
    current = dict(options or {})
    return SimpleNamespace(
        _config_entry=SimpleNamespace(options=dict(current)),
        _get_current=lambda k, d=None: current.get(k, d),
        async_create_entry=lambda title, data: {"type": "create_entry", "data": data},
        async_show_form=lambda step_id, data_schema, errors=None: {
            "type": "form", "errors": errors, "schema": data_schema},
    )


@pytest.mark.asyncio
async def test_exclude_subset_enforced():
    step = _step()
    res = await step(_fake(), {
        "security_lock_entities": [DOOR],          # valid lock list
        "security_lock_sweep_exclude": [BED],       # BED not a Door lock
    })
    assert res["type"] == "form"
    assert res["errors"] == {"security_lock_sweep_exclude": "exclude_not_in_locks"}


@pytest.mark.asyncio
async def test_exclude_subset_valid_saves():
    res = await _step()(_fake({"x": 1}), {
        "security_lock_entities": [DOOR, BED],
        "security_lock_sweep_exclude": [BED],
    })
    assert res["type"] == "create_entry"
    assert res["data"]["security_lock_sweep_exclude"] == [BED]
    assert res["data"]["x"] == 1


@pytest.mark.asyncio
async def test_away_lock_must_be_excluded():
    res = await _step()(_fake(), {
        "security_lock_entities": [DOOR, BED],
        "security_lock_sweep_exclude": [],
        "security_away_lock_entities": [BED],
    })
    assert res["type"] == "form"
    assert res["errors"] == {"security_away_lock_entities": "away_lock_not_excluded"}
    ok = await _step()(_fake(), {
        "security_lock_entities": [DOOR, BED],
        "security_lock_sweep_exclude": [BED],
        "security_away_lock_entities": [BED],
        "security_away_lock_persons": [OJI, EZ],
    })
    assert ok["type"] == "create_entry"
    assert ok["data"]["security_away_lock_persons"] == [OJI, EZ]


@pytest.mark.asyncio
async def test_lockout_overlap_still_rejected():
    res = await _step()(_fake(), {
        "security_lock_entities": [DOOR, LOCK_A],
        "security_lockout_entities": [LOCK_A],
    })
    assert res["errors"] == {"security_lockout_entities": "lockout_overlaps_locks"}


@pytest.mark.asyncio
async def test_all_errors_reported_together():
    res = await _step()(_fake(), {
        "security_lock_entities": [DOOR, LOCK_A],
        "security_lockout_entities": [LOCK_A],
        "security_lock_sweep_exclude": ["lock.other"],
        "security_away_lock_entities": [BED],
    })
    assert res["type"] == "form"
    assert res["errors"] == {
        "security_lockout_entities": "lockout_overlaps_locks",
        "security_lock_sweep_exclude": "exclude_not_in_locks",
        "security_away_lock_entities": "away_lock_not_excluded",
    }


@pytest.mark.asyncio
async def test_field_order_locks_exclude_lockouts_adjacent():
    form = await _step()(_fake(), None)
    keys = [str(k) for k in form["schema"].schema]
    assert keys[:8] == [
        "security_lock_entities",
        "security_lock_sweep_exclude",
        "security_away_lock_entities",
        "security_away_lock_persons",
        "security_lockout_entities",
        "security_lockout_excluded_persons",
        "security_lockout_distance_sensors",
        "security_lockout_approach_zone",
    ]
    assert keys[8] == "security_garage_entities"


def _selector_for(schema, key):
    for k, v in schema.schema.items():
        if str(k) == key:
            return v
    raise AssertionError(key)


@pytest.mark.asyncio
async def test_distance_selector_filter_proximity_distance():
    form = await _step()(_fake(), None)
    sel = _selector_for(form["schema"], "security_lockout_distance_sensors")
    ser = sel.serialize()["selector"]["entity"]
    assert ser["multiple"] is True
    assert ser["filter"] == [
        {"integration": "proximity", "domain": ["sensor"], "device_class": ["distance"]}
    ]
    # A stored value outside the filter stays valid (HA validates format +
    # top-level domain only).
    assert sel(["sensor.anything_else"]) == ["sensor.anything_else"]


@pytest.mark.asyncio
async def test_new_lock_selectors_are_lock_and_person_domains():
    form = await _step()(_fake(), None)
    for key, dom in (
        ("security_lock_sweep_exclude", ["lock"]),
        ("security_away_lock_entities", ["lock"]),
        ("security_away_lock_persons", ["person"]),
    ):
        ser = _selector_for(form["schema"], key).serialize()["selector"]["entity"]
        assert ser["domain"] == dom, key
        assert ser["multiple"] is True, key


@pytest.mark.asyncio
async def test_exclude_can_be_cleared():
    """Saved [X], then a submit with [] through the REAL schema -> []."""
    step = _step()
    fake = _fake({"security_lock_entities": [DOOR, BED],
                  "security_lock_sweep_exclude": [BED]})
    form = await step(fake, None)
    validated = form["schema"]({
        "security_lock_entities": [DOOR, BED],
        "security_lock_sweep_exclude": [],
    })
    assert validated["security_lock_sweep_exclude"] == []
    res = await step(fake, validated)
    assert res["type"] == "create_entry"
    assert res["data"]["security_lock_sweep_exclude"] == []


def test_lock_exclude_not_subset_helper():
    assert R.lock_exclude_not_subset([DOOR, BED], [BED]) == []
    assert R.lock_exclude_not_subset([DOOR], [BED, DOOR]) == [BED]
    assert R.lock_exclude_not_subset(DOOR, BED) == [BED]
    assert R.lock_exclude_not_subset([DOOR], None) == []


NEW_DATA_KEYS = (
    "security_lock_sweep_exclude",
    "security_away_lock_entities",
    "security_away_lock_persons",
)
NEW_ERRORS = ("exclude_not_in_locks", "away_lock_not_excluded")


def test_strings_have_new_keys():
    blocks = []
    for path in (URA / "strings.json", URA / "translations" / "en.json"):
        data = json.loads(path.read_text())
        step = data["options"]["step"]["coordinator_security"]
        errors = step.get("error", {})
        for key in NEW_DATA_KEYS:
            assert step["data"][key], (path, key)
            assert step["data_description"][key], (path, key)
        for key in NEW_ERRORS:
            assert errors[key], (path, key)
        assert "Only proximity distance sensors are listed." in (
            step["data_description"]["security_lockout_distance_sensors"]
        )
        blocks.append((step["data"], step["data_description"], errors))
    assert blocks[0] == blocks[1]
