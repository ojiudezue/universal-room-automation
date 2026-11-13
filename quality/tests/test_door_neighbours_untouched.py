"""FACE-ARRIVAL-REBUILD-1 D7 / INV-ACCESS rev 9: the path map never feeds
`door_interior_neighbours` or its readers. The lock regime's entry areas
(`arrival_edges.door_entry_areas`), perimeter `_near_areas`, the tracker's
`_get_interior_cameras_near` and the resolved direction of a replayed crossing
are identical with and without a map loaded (REAL tracker, real loader)."""
from __future__ import annotations

from datetime import timedelta

import pytest

import _sighting_rig as R
from test_interior_paths import GOOD, _write, tr  # noqa: F401 — fixture reuse
from test_person_sighting import hass, mods  # noqa: F401


async def _snapshot(mods, tr, hass):
    tr._interior_entities = ["binary_sensor.staircase_person_occupancy",
                             "binary_sensor.family_room_person_occupancy"]
    areas = mods.arrival_edges.door_entry_areas(
        tr, lambda eid: {"binary_sensor.staircase_person_occupancy": "stairs",
                         "binary_sensor.garage_a_person_occupancy_2": "garage"}.get(eid, ""))
    near = tr._get_interior_cameras_near("binary_sensor.garage_a_person_occupancy_2")
    from homeassistant.util import dt as dt_util
    t = dt_util.utcnow()
    tr._recent_interior_events = {"binary_sensor.staircase_person_occupancy": [t + timedelta(seconds=5)]}
    tr._last_resolved.clear()
    fired = []
    unsub = hass.bus.async_listen("ura_person_egress_event", lambda e: fired.append(e.data["direction"]))
    await tr._resolve_direction("binary_sensor.garage_a_person_occupancy_2", t)
    await hass.async_block_till_done()
    unsub()
    return areas, near, fired


@pytest.mark.asyncio
async def test_entry_areas_near_areas_direction_identical_with_map(tr, hass, mods):
    tr._interior_neighbours_by_group = {
        "garage_a": ["binary_sensor.staircase_person_occupancy"]}
    before = await _snapshot(mods, tr, hass)
    _write(hass, GOOD)
    await tr.async_load_path_map()
    assert tr.path_map is not None
    after = await _snapshot(mods, tr, hass)
    assert before == after
    assert after[2] == ["entry"]
    assert tr._interior_neighbours_by_group == {
        "garage_a": ["binary_sensor.staircase_person_occupancy"]}
    assert "binary_sensor.playroom_person_occupancy_2" not in after[1]
