"""FACE-ARRIVAL-REBUILD-1 D7 / INTERIOR-PATH-MAP-1 (plan rev 11 §9 D7, §2B.4).

The REAL EgressDirectionTracker loads ``interior_paths.json`` through the
shared ``json_file_loader`` on a REAL hass (real bus, real config dir), the
REAL CameraResolver over the live-house registry fixture resolves nodes, and
the REAL button presses reload. Scorer goldens are hand-derived timelines.
"""
from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio

import _sighting_rig as R
from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse

EGRESS = [
    "binary_sensor.garage_a_person_occupancy_2",
    "binary_sensor.doorbell_lite_person_occupancy_2",
    "binary_sensor.front_door_aerial_person_occupancy_2",
    "binary_sensor.madrone_g6_entry_person_occupancy_2",
    "binary_sensor.garage_b_person_occupancy",
]
GROUPS = {"garage_a": "garage_a", "doorbell_lite": "garage_a", "front_door_aerial": "front",
          "madrone_g6_entry": "front", "garage_b": "garage_b"}
PERIMETER = ["camera.rear_ptz_2", "camera.g5_bullet", "camera.front_side_ptz",
             "camera.utilities_ptz_2", "camera.sonoffwindow"]

GOOD = {"schema_version": 1, "doors": {"garage_a": {"edges": [
    {"from": "camera.rear_ptz_2", "to": "camera.garage_a_2", "kind": "approach", "lag_p90_s": 25},
    {"from": "camera.garage_a_2", "to": "camera.staircase_2", "kind": "inward"},
    {"from": "camera.staircase_2", "to": "camera.stairs_top_2", "kind": "inward"},
    {"from": "camera.stairs_top_2", "to": "camera.playroom", "kind": "inward"},
], "same_view": []}}}


# This house's map: the committed example the operator installs as
# /config/universal_room_automation/interior_paths.json (the shipped code
# fallback is None: no house entity id in code).
EXAMPLE_PATH = (__import__("pathlib").Path(__file__).resolve().parents[2]
                / "docs" / "examples" / "interior_paths.example.json")
EXAMPLE = json.loads(EXAMPLE_PATH.read_text())


def _write(hass, spec):
    import os
    path = hass.config.path("universal_room_automation", "interior_paths.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    raw = spec if isinstance(spec, str) else json.dumps(spec)
    with open(path, "w") as fh:
        fh.write(raw)
    return raw


def _rm(hass):
    import os
    path = hass.config.path("universal_room_automation", "interior_paths.json")
    if os.path.exists(path):
        os.remove(path)


@pytest_asyncio.fixture
async def tr(mods, hass, monkeypatch):
    c = mods.const
    integ = SimpleNamespace(entry_id="integ", data={c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_INTEGRATION},
                            options={c.CONF_DOOR_GROUPS: dict(GROUPS),
                                     c.CONF_PERIMETER_CAMERAS: list(PERIMETER)})
    R.install_entries(hass, monkeypatch, [integ])
    er_, dr_ = R.registries()
    hass.data[R.DOMAIN] = {"camera_manager": R._Mgr(
        mods.resolver.CameraResolver(er_, dr_, state_getter=hass.states.get))}
    t = mods.transit.EgressDirectionTracker(hass)
    t._egress_entities = list(EGRESS)
    t._load_door_config()
    hass.data[R.DOMAIN]["egress_tracker"] = t
    # The const-fallback mechanism is exercised with this house's example as
    # the const (the shipped const is None; see test_shipped_const_is_no_map).
    monkeypatch.setattr(mods.transit, "INTERIOR_PATH_MAP_FALLBACK", copy.deepcopy(EXAMPLE))
    _rm(hass)
    yield t
    await t.async_teardown()
    _rm(hass)


def _ctx(mods, tr):
    return tr._path_map_context()


# ------------------------------------------------------------- loading
@pytest.mark.asyncio
async def test_file_wins_over_const(tr, hass):
    raw = _write(hass, GOOD)
    await tr.async_load_path_map()
    assert tr.path_map_source == "interior_paths.json (schema 1, 4 edges)"
    assert tr.path_map_validation == "ok"
    assert tr.path_map_sha256 == hashlib.sha256(raw.encode()).hexdigest()
    assert tr.path_map_status()["path_map_doors"] == ["garage_a"]


@pytest.mark.asyncio
async def test_four_load_outcomes(tr, hass, mods, monkeypatch):
    # (2) absent at setup -> validated const (both live doors).
    await tr.async_load_path_map()
    assert tr.path_map_source == "built-in const"
    assert sorted(tr.path_map.doors) == ["front", "garage_a"]
    assert tr.path_map_sha256 is None
    # (1) valid file on a later load -> file.
    _write(hass, GOOD)
    await tr.async_load_path_map()
    assert tr.path_map_source.startswith("interior_paths.json")
    # (4) invalid file on a later load -> previous map kept, sha unchanged.
    sha = tr.path_map_sha256
    _write(hass, {"schema_version": 2})
    await tr.async_load_path_map()
    assert tr.path_map_source.startswith("interior_paths.json")
    assert tr.path_map_sha256 == sha
    assert tr.path_map_validation.endswith("(kept previous)")
    # (3) invalid at the FIRST load, foreign-house const -> none.
    t2 = mods.transit.EgressDirectionTracker(hass)
    t2._egress_entities = list(EGRESS)
    t2._load_door_config()
    monkeypatch.setattr(mods.transit, "INTERIOR_PATH_MAP_FALLBACK", {
        "schema_version": 1, "doors": {"garage_a": {"edges": [
            {"from": "camera.not_here", "to": "camera.garage_a_2", "kind": "approach"}]}}})
    await t2.async_load_path_map()
    assert (t2.path_map_source, t2.path_map) == ("none", None)
    assert "camera.not_here" in t2.path_map_validation
    assert t2.path_map_sha256 is None


@pytest.mark.asyncio
async def test_shipped_const_is_no_map(tr, hass, mods, monkeypatch):
    """Portability: the shipped fallback is None, so with no file there is
    no map on ANY install (no house entity id in code)."""
    assert mods.const.INTERIOR_PATH_MAP_FALLBACK is None
    monkeypatch.setattr(mods.transit, "INTERIOR_PATH_MAP_FALLBACK",
                        mods.const.INTERIOR_PATH_MAP_FALLBACK)
    await tr.async_load_path_map()
    assert (tr.path_map_source, tr.path_map, tr.path_map_validation) == (
        "none", None, "file absent")
    _write(hass, {"schema_version": 2})
    await tr.async_load_path_map()
    assert (tr.path_map_source, tr.path_map) == ("none", None)
    assert tr.path_map_validation.startswith("rejected:")


@pytest.mark.asyncio
async def test_example_file_installs_on_this_house(tr, hass):
    """The committed example, installed as the file, validates against the
    live-house registry fixture: 19 edges, both live doors."""
    raw = _write(hass, EXAMPLE_PATH.read_text())
    await tr.async_load_path_map()
    assert tr.path_map_source == "interior_paths.json (schema 1, 19 edges)"
    assert tr.path_map_validation.startswith("ok")
    assert sorted(tr.path_map.doors) == ["front", "garage_a"]
    assert tr.path_map_sha256 == hashlib.sha256(raw.encode()).hexdigest()


@pytest.mark.asyncio
async def test_sha_names_installed_source(tr, hass):
    _write(hass, '{"schema_version": 1, "doors": {"nope": {}}}')
    await tr.async_load_path_map()           # rejected at first load -> const
    assert tr.path_map_source == "built-in const"
    assert tr.path_map_sha256 is None        # never the rejected file's sha


@pytest.mark.asyncio
async def test_invalid_file_rejected_whole_keeps_previous(tr, hass):
    _write(hass, GOOD)
    await tr.async_load_path_map()
    bad = copy.deepcopy(GOOD)
    bad["doors"]["garage_a"]["edges"].append(
        {"from": "camera.ghost", "to": "camera.playroom", "kind": "inward"})
    _write(hass, bad)
    await tr.async_load_path_map()
    assert len(tr.path_map.doors["garage_a"].edges) == 4  # not partially applied
    assert "camera.ghost" in tr.path_map_validation


@pytest.mark.asyncio
async def test_invalid_source_means_no_map_not_partial(tr, mods):
    ctx = _ctx(mods, tr)
    bad = copy.deepcopy(GOOD)
    bad["doors"]["garage_a"]["edges"][0]["kind"] = "sideways"
    with pytest.raises(mods.paths.PathMapError):
        mods.paths.validate(bad, ctx)


@pytest.mark.asyncio
async def test_unknown_camera_named_in_error(tr, mods):
    bad = copy.deepcopy(GOOD)
    bad["doors"]["garage_a"]["edges"][1]["to"] = "camera.basement_9"
    with pytest.raises(mods.paths.PathMapError, match="camera.basement_9"):
        mods.paths.validate(bad, _ctx(mods, tr))


@pytest.mark.asyncio
async def test_cycle_rejected(tr, mods):
    bad = copy.deepcopy(GOOD)
    bad["doors"]["garage_a"]["edges"].append(
        {"from": "camera.playroom", "to": "camera.staircase_2", "kind": "inward"})
    with pytest.raises(mods.paths.PathMapError, match="rule 5"):
        mods.paths.validate(bad, _ctx(mods, tr))


@pytest.mark.asyncio
async def test_door_key_must_be_live_group(tr, mods):
    bad = {"schema_version": 1, "doors": {"patio": {"edges": []}}}
    with pytest.raises(mods.paths.PathMapError, match="rule 2"):
        mods.paths.validate(bad, _ctx(mods, tr))


@pytest.mark.asyncio
async def test_frigate_and_protect_legs_one_node(tr, mods):
    ctx = _ctx(mods, tr)
    k1, _ = ctx.resolve_node("camera.garage_a_2")
    k2, _ = ctx.resolve_node("camera.garage_a_high_resolution_channel")
    assert k1 == k2
    dup = copy.deepcopy(GOOD)
    dup["doors"]["garage_a"]["edges"].append(
        {"from": "camera.rear_ptz_2", "to": "camera.garage_a_high_resolution_channel",
         "kind": "approach"})
    with pytest.raises(mods.paths.PathMapError, match="duplicate"):
        mods.paths.validate(dup, ctx)


@pytest.mark.asyncio
async def test_detached_door_inward_to_house_rejected(tr, mods):
    spec = copy.deepcopy(GOOD)
    spec["doors"]["garage_b"] = {"edges": [
        {"from": "camera.garage_b_2", "to": "camera.staircase_2", "kind": "inward"}]}
    with pytest.raises(mods.paths.PathMapError, match="rule 10"):
        mods.paths.validate(spec, _ctx(mods, tr))
    ok = copy.deepcopy(GOOD)
    ok["doors"]["garage_b"] = {"edges": [
        {"from": "camera.rear_ptz_2", "to": "camera.garage_b_2", "kind": "approach"}]}
    pmap, _w = mods.paths.validate(ok, _ctx(mods, tr))
    assert "garage_b" in pmap.doors


# ------------------------------------------------------------- scorer
def _golden(mods, tr):
    pmap, _w = mods.paths.validate(GOOD, _ctx(mods, tr))
    ctx = _ctx(mods, tr)
    k = {n: ctx.resolve_node(f"camera.{n}")[0] for n in
         ("rear_ptz_2", "garage_a_2", "staircase_2", "stairs_top_2", "playroom")}
    return pmap, k


@pytest.mark.asyncio
async def test_path_score_entry_order(tr, mods):
    pmap, k = _golden(mods, tr)
    t = 1000.0
    ev = {k["rear_ptz_2"]: [t - 20], k["garage_a_2"]: [t], k["staircase_2"]: [t + 8],
          k["stairs_top_2"]: [t + 25]}
    assert mods.paths.score_path(pmap, "garage_a", "entry", t, t + 45, ev, buffer_s=180) == 3


@pytest.mark.asyncio
async def test_path_score_reverse_order_negative(tr, mods):
    """The same three hops observed in the opposite order inside the same
    windows score -3 for an entry."""
    pmap, k = _golden(mods, tr)
    t = 1000.0
    ev = {k["garage_a_2"]: [t - 20], k["rear_ptz_2"]: [t - 5],
          k["stairs_top_2"]: [t + 8], k["staircase_2"]: [t + 25, t + 10]}
    ev[k["garage_a_2"]].append(t + 30)
    assert mods.paths.score_path(pmap, "garage_a", "entry", t, t + 45, ev, buffer_s=180) == -3


@pytest.mark.asyncio
async def test_path_score_ignores_hops_after_resolution(tr, mods):
    pmap, k = _golden(mods, tr)
    t = 1000.0
    ev = {k["rear_ptz_2"]: [t - 20], k["garage_a_2"]: [t], k["staircase_2"]: [t + 8],
          k["stairs_top_2"]: [t + 25], k["playroom"]: [t + 50]}  # 25 s hop, after T
    assert mods.paths.score_path(pmap, "garage_a", "entry", t, t + 45, ev, buffer_s=180) == 3


@pytest.mark.asyncio
async def test_no_map_for_door_is_skipped_not_zero(tr, mods):
    pmap, _k = _golden(mods, tr)
    assert mods.paths.score_path(pmap, "front", "entry", 0, 45, {}, buffer_s=180) is None
    assert mods.paths.score_path(None, "garage_a", "entry", 0, 45, {}, buffer_s=180) is None
    assert mods.paths.score_path(pmap, "garage_a", "entry", 0, 45, {}, buffer_s=180) == 0


@pytest.mark.asyncio
async def test_egress_pair_same_group_not_scored(tr, mods):
    ctx = _ctx(mods, tr)
    spec = {"schema_version": 1, "doors": {"garage_a": {"edges": [
        {"from": "camera.doorbell_lite", "to": "camera.garage_a_2", "kind": "approach"}]}}}
    pmap, _w = mods.paths.validate(spec, ctx)
    kd, kg = ctx.resolve_node("camera.doorbell_lite")[0], ctx.resolve_node("camera.garage_a_2")[0]
    assert mods.paths.score_path(pmap, "garage_a", "entry", 100, 145,
                                 {kd: [90], kg: [100]}, buffer_s=180) == 0


@pytest.mark.asyncio
async def test_patio_family_room_same_view_not_a_hop(tr, mods):
    """same_view pairs never score (patio camera / family room when the slider
    is open). Exercised on a live door with the family room pair."""
    ctx = _ctx(mods, tr)
    spec = {"schema_version": 1, "doors": {"front": {"edges": [
        {"from": "camera.foyer_fisheye", "to": "camera.family_room", "kind": "inward"}],
        "same_view": [["camera.foyer_fisheye", "camera.family_room"]]}}}
    pmap, _w = mods.paths.validate(spec, ctx)
    kf, kr = ctx.resolve_node("camera.foyer_fisheye")[0], ctx.resolve_node("camera.family_room")[0]
    assert mods.paths.score_path(pmap, "front", "entry", 100, 145,
                                 {kf: [105], kr: [110]}, buffer_s=180) == 0


@pytest.mark.asyncio
async def test_path_score_front_door_dag(tr, mods):
    """Front door DAG from the const: Entry way (aerial) is an approach END
    and an anchor; Foyer is inward. Front PTZ -> aerial (t-10), aerial ->
    foyer (t+10), G6 -> foyer (t+1 -> t+10), foyer -> master hallway (t+30)
    = 4; the aerial/G6 pair (both egress anchors) never scores."""
    pmap, _w = mods.paths.validate(EXAMPLE, _ctx(mods, tr))
    ctx = _ctx(mods, tr)
    k = lambda n: ctx.resolve_node(f"camera.{n}")[0]  # noqa: E731
    t = 500.0
    ev = {k("front_side_ptz"): [t - 10], k("front_door_aerial"): [t],
          k("madrone_g6_entry"): [t + 1], k("foyer_fisheye"): [t + 10],
          k("master_hallway"): [t + 30]}
    assert mods.paths.score_path(pmap, "front", "entry", t, t + 45, ev, buffer_s=180) == 4


def test_probe_and_runtime_share_scorer():
    """The offline D0 scripts execute interior_paths.py itself (concatenated
    into the ssh stdin); it must import nothing outside the standard library."""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2] / "custom_components"
           / "universal_room_automation" / "interior_paths.py").read_text()
    mods_ = {n.module.split(".")[0] if isinstance(n, ast.ImportFrom) and n.module else
             n.names[0].name.split(".")[0]
             for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert mods_ <= {"__future__", "dataclasses", "typing"}


# ------------------------------------------------------- triggers / button
@pytest.mark.asyncio
async def test_cold_boot_valid_file_loads_after_ha_started(tr, hass):
    from homeassistant.core import CoreState
    _write(hass, GOOD)
    hass.set_state(CoreState.not_running)
    tr.async_setup_path_map()
    await hass.async_block_till_done()
    assert tr.path_map_source == "pending"
    hass.set_state(CoreState.running)
    hass.bus.async_fire("homeassistant_started")
    await hass.async_block_till_done()
    assert tr.path_map_source.startswith("interior_paths.json")


@pytest.mark.asyncio
async def test_entry_reload_loads_immediately_when_running(tr, hass):
    _write(hass, GOOD)
    tr.async_setup_path_map()
    await hass.async_block_till_done()
    assert tr.path_map_source.startswith("interior_paths.json")


@pytest.mark.asyncio
async def test_registry_update_upgrades_const_to_file(tr, hass, mods):
    """First load: the file names a camera not yet registered -> const.
    The camera registers; a registry update (debounced, literal 30 s)
    re-validates and upgrades to the file."""
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    spec = copy.deepcopy(GOOD)
    spec["doors"]["garage_a"]["edges"].append(
        {"from": "camera.stairs_top_2", "to": "camera.late_cam", "kind": "inward"})
    _write(hass, spec)
    tr.async_setup_path_map()
    await hass.async_block_till_done()
    assert tr.path_map_source == "built-in const"
    # The late camera appears: add it to the registry the resolver reads.
    res = hass.data[R.DOMAIN]["camera_manager"].resolver
    er_, dr_ = res._er, res._dr
    er_.entities["camera.late_cam"] = R._Ent({"entity_id": "camera.late_cam", "platform": "frigate",
                                              "device_id": "late_dev"})
    er_.entities["binary_sensor.late_cam_person_occupancy"] = R._Ent({
        "entity_id": "binary_sensor.late_cam_person_occupancy", "platform": "frigate",
        "device_id": "late_dev", "unique_id": "x:occupancy_sensor:late_cam_person"})
    dr_.devices["late_dev"] = R._Dev({"id": "late_dev", "name": "Late Cam",
                                       "identifiers": [["frigate", "x:late_cam"]]})
    hass.data[R.DOMAIN]["camera_manager"].resolver = mods.resolver.CameraResolver(er_, dr_)
    hass.bus.async_fire("entity_registry_updated", {"action": "create"})
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=29))
    await hass.async_block_till_done()
    assert tr.path_map_source == "built-in const"
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    assert tr.path_map_source.startswith("interior_paths.json")


@pytest.mark.asyncio
async def test_reload_button_swaps_map(tr, hass, mods):
    await tr.async_load_path_map()
    assert tr.path_map_source == "built-in const"
    _write(hass, GOOD)
    btn = mods.button.ReloadInteriorPathsButton(hass, SimpleNamespace(entry_id="x"))
    await btn.async_press()
    assert tr.path_map_source.startswith("interior_paths.json")
