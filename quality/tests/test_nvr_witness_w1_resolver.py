"""NVR-WITNESS W1 (PLANNING_nvr_witness_layer.md §5, §8 W1): the resolver pairs a
Frigate camera device with its non-Frigate sibling on REGISTRY evidence only.

Evidence: the Frigate object name from the Frigate DEVICE identifier
``(frigate, "<inst>:<obj>")`` equals HA ``slugify`` of the candidate DEVICE's
registry name (``name_by_user`` else ``name``). No entity_id is parsed for it.
Uniqueness (all must hold): (1) input device is Frigate and obj == slug;
(2) exactly one non-Frigate camera device has that slug; (3) no other Frigate
device has that object name; (4) the candidate has no Frigate identifier.

Part A drives the REAL resolver over hand-built registries (one variable per
test). Part B drives it over the live registry shape (fixture extracted from
the live HA registry 2026-11-13) against a golden produced by develop's
resolver (4b825c50): knob off = byte-identical; knob on = golden plus a
hand-written delta. Part C drives the resolver CALLERS (census
``resolve_cross_platform_sensors`` -> transit subscription, transit
``_path_map_context``, person sightings ``_bind_pick`` / ``_egress_key``,
perimeter ``_resolve_legs``) with the real modules.
"""
from __future__ import annotations

import copy
import importlib.util as _il
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

import _nvr_w1_registry as W
import _sighting_rig as R
from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse

REPO_ROOT = Path(__file__).resolve().parents[2]
_PATH = REPO_ROOT / "custom_components/universal_room_automation/camera_resolver.py"
_spec = _il.spec_from_file_location("camera_resolver_w1_under_test", _PATH)
RW = _il.module_from_spec(_spec)
sys.modules["camera_resolver_w1_under_test"] = RW
_spec.loader.exec_module(RW)

KNOB = "RESOLVER_FRIGATE_OBJECT_NAME_EVIDENCE"


@pytest.fixture
def knob(monkeypatch):
    def _set(mod, value: bool) -> None:
        monkeypatch.setattr(mod, KNOB, value)
    return _set


# ============================================================================
# Part A: hand-built registries
# ============================================================================

class _ER:
    def __init__(self, ents):
        self.entities = {e.entity_id: e for e in ents}

    def async_get(self, eid):
        return self.entities.get(eid)


class _DR:
    def __init__(self, devs):
        self.devices = {d.id: d for d in devs}

    def async_get(self, did):
        return self.devices.get(did)


def dev(did, name, *, idents=(), macs=(), name_by_user=None):
    # identifiers as an ordered tuple so a multi-identifier device infers a
    # deterministic integration (first identifier wins in _infer_integration).
    return SimpleNamespace(id=did, name=name, name_by_user=name_by_user,
                           identifiers=tuple(idents),
                           connections={("mac", m) for m in macs})


def ent(eid, did, platform, *, disabled_by=None):
    return SimpleNamespace(entity_id=eid, device_id=did, platform=platform,
                           disabled_by=disabled_by, domain=eid.split(".", 1)[0],
                           unique_id=f"uid-{eid}", config_entry_id="ce", area_id=None)


def frigate(did, obj, cam_eid, person_eid, *, inst="inst1", name=None):
    return ([dev(did, name or obj.replace("_", " ").title(),
                 idents=[("frigate", f"{inst}:{obj}")])],
            [ent(cam_eid, did, "frigate"), ent(person_eid, did, "frigate")])


def protect(did, name, stem, mac, *, name_by_user=None):
    return ([dev(did, name, macs=[mac], name_by_user=name_by_user)],
            [ent(f"camera.{stem}_high_resolution_channel", did, "unifiprotect"),
             ent(f"binary_sensor.{stem}_person_detected", did, "unifiprotect")])


def build(*parts):
    devs, ents = [], []
    for d, e in parts:
        devs += d
        ents += e
    return RW.CameraResolver(_ER(ents), _DR(devs))


def sources(resolver, cam):
    fusions = resolver.resolve_operator_declaration([cam])
    return sorted((s.integration, s.device_id, s.person_binary_sensor, s.correlation_basis)
                  for f in fusions for s in f.sources)


GA_FRIGATE = frigate("f_ga", "garage_a", "camera.garage_a_2",
                     "binary_sensor.garage_a_person_occupancy_2", name="Garage A")
GA_PROTECT = protect("p_ga", "Garage A", "garage_a", "28:70:4e:18:fc:13")
F_ONLY = [("frigate", "f_ga", "binary_sensor.garage_a_person_occupancy_2", "same_device")]
F_PLUS_P = F_ONLY + [("unifiprotect", "p_ga", "binary_sensor.garage_a_person_detected",
                      "frigate_object_name")]


def test_resolver_knob_shipped_default_true():
    assert RW.RESOLVER_FRIGATE_OBJECT_NAME_EVIDENCE is True


def test_resolver_object_name_collapses_unique_protect_sibling(knob):
    """garage_a live shape: Frigate device id `(frigate, inst:garage_a)`, no MAC;
    Protect device with a MAC, no identifiers, name "Garage A". Paired."""
    r = build(GA_FRIGATE, GA_PROTECT)
    assert sources(r, "camera.garage_a_2") == sorted(F_PLUS_P)
    knob(RW, False)
    r_off = build(GA_FRIGATE, GA_PROTECT)
    assert sources(r_off, "camera.garage_a_2") == F_ONLY


def test_resolver_protect_input_direction_unchanged(knob):
    """The Protect -> Frigate direction already paired on develop (Frigate
    object index); W1 does not touch it."""
    on = sources(build(GA_FRIGATE, GA_PROTECT), "camera.garage_a_high_resolution_channel")
    knob(RW, False)
    off = sources(build(GA_FRIGATE, GA_PROTECT), "camera.garage_a_high_resolution_channel")
    assert on == off
    assert {s[1] for s in on} == {"f_ga", "p_ga"}


DW_FRIGATE = frigate("f_dw", "driveway", "camera.driveway_2",
                     "binary_sensor.driveway_person_occupancy_2", name="Driveway")
DW_PROTECT = protect("p_dw", "Driveway", "driveway", "aa:bb:cc:00:00:01")


def test_resolver_object_name_refuses_two_candidates():
    """HA X / X_2 naming, two DISTINCT physical cameras both called "Driveway":
    Protect `camera.driveway_*` and a Reolink "Driveway"; Frigate's camera is
    `camera.driveway_2` (object name `driveway`). Two non-Frigate candidates
    carry the slug -> condition (2) refuses; Frigate stays alone."""
    reolink = ([dev("r_dw", "Driveway", idents=[("reolink", "uid-r")], macs=["aa:bb:cc:00:00:02"])],
               [ent("camera.driveway_fluent", "r_dw", "reolink"),
                ent("binary_sensor.driveway_person", "r_dw", "reolink")])
    r = build(DW_FRIGATE, DW_PROTECT, reolink)
    assert sources(r, "camera.driveway_2") == [
        ("frigate", "f_dw", "binary_sensor.driveway_person_occupancy_2", "same_device")]


def test_resolver_residual_one_name_one_camera_each_side_pairs():
    """Accepted residual (plan §5): ONE Protect and ONE Frigate camera with the
    same name and no other camera of that name pair. Nothing in the registry
    tells this apart from the true pair; pinned so a change is deliberate."""
    r = build(DW_FRIGATE, DW_PROTECT)
    assert ("unifiprotect", "p_dw", "binary_sensor.driveway_person_detected",
            "frigate_object_name") in sources(r, "camera.driveway_2")


def test_resolver_other_frigate_device_with_same_name_not_a_candidate():
    """Condition (2) counts NON-Frigate devices only: a second Frigate device
    (object `garage_a_wide`) whose registry name is also "Garage A" does not
    make the Protect device ambiguous."""
    wide = frigate("f_gw", "garage_a_wide", "camera.garage_a_wide",
                   "binary_sensor.garage_a_wide_person_occupancy", name="Garage A")
    assert sources(build(GA_FRIGATE, wide, GA_PROTECT), "camera.garage_a_2") == sorted(F_PLUS_P)


def test_resolver_object_name_refuses_two_frigate_devices():
    """Two Frigate devices with object name `driveway` (two instances) ->
    condition (3) refuses; the Protect device is not pulled in."""
    second = frigate("f_dw2", "driveway", "camera.driveway_3",
                     "binary_sensor.driveway_person_occupancy_3", inst="inst2", name="Driveway")
    r = build(DW_FRIGATE, second, DW_PROTECT)
    assert "p_dw" not in {s[1] for s in sources(r, "camera.driveway_2")}


def test_resolver_object_name_refuses_candidate_with_frigate_identifier():
    """Condition (4): the only non-Frigate "Driveway" camera device also carries
    a Frigate identifier (object `porch`, so condition (3) still passes)."""
    cand = ([dev("r_dw", "Driveway", idents=[("reolink", "uid-r"), ("frigate", "inst9:porch")],
                 macs=["aa:bb:cc:00:00:02"])],
            [ent("camera.driveway_fluent", "r_dw", "reolink"),
             ent("binary_sensor.driveway_person", "r_dw", "reolink")])
    r = build(DW_FRIGATE, cand)
    assert "r_dw" not in {s[1] for s in sources(r, "camera.driveway_2")}


def test_resolver_object_name_refuses_non_frigate_input():
    """Condition (1), input side: a device whose integration is Reolink but
    which also carries a Frigate identifier `driveway` is not a Frigate input."""
    inp = ([dev("r_in", "Gate", idents=[("reolink", "uid-g"), ("frigate", "inst1:driveway")])],
           [ent("camera.gate", "r_in", "reolink"), ent("binary_sensor.gate_person", "r_in", "reolink")])
    r = build(inp, DW_PROTECT)
    assert "p_dw" not in {s[1] for s in sources(r, "camera.gate")}


def test_resolver_object_name_requires_equal_registry_name():
    """Condition (1), equality: Protect device "Garage Alpha" -> no pair."""
    r = build(GA_FRIGATE, protect("p_ga", "Garage Alpha", "garage_a", "28:70:4e:18:fc:13"))
    assert sources(r, "camera.garage_a_2") == F_ONLY


def test_resolver_pairs_on_device_registry_name_not_entity_id():
    """(a) Protect entity ids renamed, device name unchanged -> still pairs.
    (b) Device renamed by the user (`name_by_user` "Workshop") -> compares the
    new name -> no pair. (c) Generic `name`, user name "Garage A" -> pairs."""
    renamed = ([dev("p_ga", "Garage A", macs=["28:70:4e:18:fc:13"])],
               [ent("camera.side_cam_high_resolution_channel", "p_ga", "unifiprotect"),
                ent("binary_sensor.side_cam_person_detected", "p_ga", "unifiprotect")])
    assert ("unifiprotect", "p_ga", "binary_sensor.side_cam_person_detected",
            "frigate_object_name") in sources(build(GA_FRIGATE, renamed), "camera.garage_a_2")
    user_renamed = protect("p_ga", "Garage A", "garage_a", "28:70:4e:18:fc:13",
                           name_by_user="Workshop")
    assert sources(build(GA_FRIGATE, user_renamed), "camera.garage_a_2") == F_ONLY
    user_named = protect("p_ga", "Cam 7", "garage_a", "28:70:4e:18:fc:13",
                         name_by_user="Garage A")
    assert sources(build(GA_FRIGATE, user_named), "camera.garage_a_2") == sorted(F_PLUS_P)


def test_resolver_slugify_matches_ha_device_name_punctuation():
    """Live device "Stairs - top" (Protect) vs Frigate object `stairs_top`: HA
    slugify gives `stairs_top`; a naive lower/replace would give `stairs_-_top`."""
    st_f = frigate("f_st", "stairs_top", "camera.stairs_top_2",
                   "binary_sensor.stairs_top_person_occupancy", name="Stairs Top")
    st_p = protect("p_st", "Stairs - top", "stairs_top", "28:70:4e:18:0f:67")
    assert "p_st" in {s[1] for s in sources(build(st_f, st_p), "camera.stairs_top_2")}


def test_resolver_object_name_ignores_device_with_only_disabled_camera():
    """A candidate whose only camera entity is disabled is not a camera device."""
    p = ([dev("p_ga", "Garage A", macs=["28:70:4e:18:fc:13"])],
         [ent("camera.garage_a_high_resolution_channel", "p_ga", "unifiprotect",
              disabled_by="user"),
          ent("binary_sensor.garage_a_person_detected", "p_ga", "unifiprotect")])
    assert sources(build(GA_FRIGATE, p), "camera.garage_a_2") == F_ONLY


# ============================================================================
# Part B: live registry shape vs develop golden
# ============================================================================

def _golden():
    return json.loads(W.GOLDEN.read_text())["cameras"]


def test_resolver_knob_off_byte_identical_all_callers(knob):
    """Knob off: every surface the callers consume (resolve_operator_declaration,
    resolve_pick_to_fusions, resolve_detection_legs x 3 families) for all 105
    live cameras equals develop's resolver output."""
    knob(RW, False)
    er, dr = W.registries()
    assert W.snapshot(RW, er, dr) == _golden()


# Hand-written delta (oracle). Each Frigate camera below has a Protect device
# with the same registry name, a MAC, no identifiers; develop never paired it
# in the Frigate -> Protect direction. key = min(device ids) of the fusion.
_DELTA = {
    "camera.garage_a_2": ("f84347c3bdb5ae35165371bc6b0ef46d",
                          "binary_sensor.garage_a_person_detected",
                          "7c45bd09807dc95870bc7e747e5a3225"),
    "camera.garage_b_2": ("da2ea2728aa39a4607f875fb7a0ca1da",
                          "binary_sensor.garage_b_person_detected",
                          "590cae754d03a07ee4a335847f5cdacd"),
    "camera.foyer_fisheye": ("fb4e9a02e2886aa9ba0f4eb00feee1a1",
                             "binary_sensor.foyer_fisheye_person_detected",
                             "f095ee1afbb60cd69699623eef1d3706"),
    "camera.rear_ptz_2": ("c62cb38727b5a8e0747ca42c2878cebc",
                          "binary_sensor.rear_ptz_person_detected",
                          "c62cb38727b5a8e0747ca42c2878cebc"),
    "camera.stairs_top_2": ("74f1d0a01d1af703634f541c7db596e1",
                            "binary_sensor.stairs_top_person_detected",
                            "74f1d0a01d1af703634f541c7db596e1"),
    "camera.upstairs_hall_2": ("b063bbf5881d859b456429b6f3d41575",
                               "binary_sensor.upstairs_hall_person_detected",
                               "b063bbf5881d859b456429b6f3d41575"),
    "camera.utilities_ptz_2": ("eeab47f71d4653e8a08179d11483a5fa",
                               "binary_sensor.utilities_ptz_person_detected",
                               "7fafaf02752b565a43df4ed175b8ceb3"),
}


def test_fusion_callers_golden_except_garage_shape():
    """Knob on (shipped): every live camera equals develop except the seven
    Frigate-side cameras in _DELTA, and each of those changes ONLY by gaining
    its one Protect source (basis `frigate_object_name`), its key as written,
    and (detection legs) only foyer_fisheye gains a person leg: every other
    camera's legs already reached Protect on develop through the unguarded
    `_N` stem bridge in resolve_detection_legs."""
    er, dr = W.registries()
    snap = W.snapshot(RW, er, dr)
    gold = _golden()
    assert set(snap) == set(gold)
    for cam in sorted(set(snap) - set(_DELTA)):
        assert snap[cam] == gold[cam], cam
    for cam, (p_did, p_bs, key) in _DELTA.items():
        g, s = gold[cam], snap[cam]
        assert len(g["decl"]) == len(s["decl"]) == 1, cam
        added = [x for x in s["decl"][0]["sources"] if x not in g["decl"][0]["sources"]]
        assert [(a["integration"], a["device_id"], a["person_binary_sensor"],
                 a["correlation_basis"]) for a in added] == [
            ("unifiprotect", p_did, p_bs, "frigate_object_name")], cam
        assert all(x in s["decl"][0]["sources"] for x in g["decl"][0]["sources"]), cam
        assert s["decl"][0]["key"] == key, cam
        assert s["decl"][0]["physical_camera_id"] == g["decl"][0]["physical_camera_id"], cam
        assert s["pick"]["fusions"][0]["sources"] == s["decl"][0]["sources"], cam
        for fam in W.FAMILIES:
            if cam == "camera.foyer_fisheye" and fam == "person":
                extra = [x for x in s["legs"][fam] if x not in g["legs"][fam]]
                assert extra == [{"device_id": p_did, "engine": "protect",
                                  "entity_id": p_bs, "integration": "unifiprotect"}]
                assert all(x in s["legs"][fam] for x in g["legs"][fam])
            else:
                assert s["legs"][fam] == g["legs"][fam], (cam, fam)
    # Plan W1 verify: garage_a_2 now carries the Protect person sensor.
    ga = [x["person_binary_sensor"] for x in snap["camera.garage_a_2"]["decl"][0]["sources"]]
    assert "binary_sensor.garage_a_person_detected" in ga


# ============================================================================
# Part C: resolver callers (real modules, live registry shape, live config)
# ============================================================================

# Live integration-entry options, 2026-11-13 (core.config_entries).
EGRESS_CAMERAS = ["camera.madrone_g6_entry", "camera.doorbell_lite",
                  "camera.front_door_aerial", "camera.garage_a_2"]
PERIMETER_CAMERAS = ["camera.reolinkstudybporchptz", "camera.rear_ptz_high_resolution_channel",
                     "camera.utilities_ptz_high_resolution_channel", "camera.front_side_ptz",
                     "camera.armcrest", "camera.hot_tub", "camera.pool_equipment",
                     "camera.g5_bullet", "camera.back_yard", "camera.madroneptultra",
                     "camera.sonoffwindow", "camera.garage_b_2"]
CAMERA_PERSON_ENTITIES = [
    "camera.playroom_high_resolution_channel", "camera.master_hallway",
    "camera.staircase_high_resolution_channel", "camera.playroom", "camera.foyer_fisheye",
    "camera.family_room", "camera.family_room_high_resolution_channel",
    "camera.foyer_fisheye_high_resolution_channel", "camera.master_hallway_high_resolution_channel",
    "camera.upstairs_hall_high_resolution_channel", "camera.stairs_top_high_resolution_channel",
    "camera.stairs_top_2"]
ZONE_PICKS = {"Entertainment": ["binary_sensor.foyer_fisheye_person_occupancy"],
              "Upstairs": ["binary_sensor.upstairs_hall_person_occupancy_2",
                           "binary_sensor.stairs_top_person_occupancy"]}


def _census_rows(mods, hass, monkeypatch, cams):
    er_, dr_ = W.registries()
    monkeypatch.setattr(mods.census.er, "async_get", lambda _h: er_)
    import homeassistant.helpers.device_registry as _dr_mod
    monkeypatch.setattr(_dr_mod, "async_get", lambda _h: dr_)
    mgr = mods.census.CameraIntegrationManager(hass)
    resolver = mods.resolver.CameraResolver(er_, dr_)
    monkeypatch.setattr(mgr, "_get_resolver", lambda: resolver)
    return sorted((i.entity_id, i.platform) for i in mgr.resolve_cross_platform_sensors(cams))


@pytest.mark.asyncio
async def test_census_cross_platform_garage_a_gains_protect(mods, hass, monkeypatch):
    """camera_census:857 (feeds transit's egress subscription,
    transit_validator.py:1093/1180 and the :417 rescan rebuild). Live egress
    list (get_transit_egress_entities, :1700): on adds exactly the garage_a
    Protect person sensor. Live camera-person list (get_transit_interior_entities,
    :1707): unchanged, because its Protect cameras are already configured
    inputs and the merge dedups by (integration, device, stem). The perimeter
    list never reaches this method (census reads it through
    resolve_configured_cameras, same-device only)."""
    on = {name: _census_rows(mods, hass, monkeypatch, cams)
          for name, cams in (("egress", EGRESS_CAMERAS),
                             ("person", CAMERA_PERSON_ENTITIES))}
    monkeypatch.setattr(mods.resolver, KNOB, False)
    off = {name: _census_rows(mods, hass, monkeypatch, cams)
           for name, cams in (("egress", EGRESS_CAMERAS),
                              ("person", CAMERA_PERSON_ENTITIES))}
    assert set(on["egress"]) - set(off["egress"]) == {
        ("binary_sensor.garage_a_person_detected", "unifiprotect")}
    assert set(off["egress"]) <= set(on["egress"])
    assert on["person"] == off["person"]
    # Plan W1 verify, by the census entry point the plan names.
    assert _census_rows(mods, hass, monkeypatch, ["camera.garage_a_2"]) == [
        ("binary_sensor.garage_a_person_occupancy_2", "frigate")]  # knob off
    monkeypatch.setattr(mods.resolver, KNOB, True)
    assert _census_rows(mods, hass, monkeypatch, ["camera.garage_a_2"]) == [
        ("binary_sensor.garage_a_person_detected", "unifiprotect"),
        ("binary_sensor.garage_a_person_occupancy_2", "frigate")]


def _tracker(mods, hass, monkeypatch):
    c = mods.const
    integ = SimpleNamespace(entry_id="integ", data={c.CONF_ENTRY_TYPE: c.ENTRY_TYPE_INTEGRATION},
                            options={c.CONF_PERIMETER_CAMERAS: list(PERIMETER_CAMERAS)})
    R.install_entries(hass, monkeypatch, [integ])
    er_, dr_ = W.registries()
    hass.data[R.DOMAIN] = {"camera_manager": R._Mgr(mods.resolver.CameraResolver(er_, dr_))}
    t = mods.transit.EgressDirectionTracker(hass)
    t._egress_entities = list(EGRESS_CAMERAS)
    t._load_door_config()
    return t


@pytest.mark.asyncio
async def test_transit_path_map_context_keys_unchanged(mods, hass, monkeypatch):
    """transit_validator.py:2407 (`_path_map_context.resolve_node`): live egress
    and perimeter keys are identical on and off; garage_a keeps its Frigate
    device key (7c45... < f843...), and its node still has a person leg."""
    def ctx_view():
        t = _tracker(mods, hass, monkeypatch)
        ctx = t._path_map_context()
        return (sorted((g, sorted(k)) for g, k in ctx.egress_keys_by_group.items()),
                sorted(ctx.exterior_keys), ctx.resolve_node("camera.garage_a_2"))
    on = ctx_view()
    monkeypatch.setattr(mods.resolver, KNOB, False)
    off = ctx_view()
    assert on == off
    assert on[2] == ("7c45bd09807dc95870bc7e747e5a3225", True)


@pytest.mark.asyncio
async def test_person_sighting_bind_and_egress_key(mods, hass, monkeypatch):
    """person_sighting.py:305/:334 (`_bind_pick`) and :503 (`_egress_key`) over
    the live zone picks: each Frigate pick's view gains its Protect person
    sensor; the two picks whose Protect device id sorts first get that key;
    garage_a's egress key is unchanged."""
    monkeypatch.setattr(R, "registries", W.registries)

    async def views():
        rig = await R.build(mods, hass, monkeypatch, zones=copy.deepcopy(ZONE_PICKS))
        try:
            p = rig.producer
            out = {pick: (k, sorted(p._views[k].person_sensors))
                   for k in p._views for pick in p._views[k].picks}
            return out, p._egress_key("camera.garage_a_2")
        finally:
            await R.teardown(rig)

    on, on_eg = await views()
    monkeypatch.setattr(mods.resolver, KNOB, False)
    off, off_eg = await views()
    assert on_eg == off_eg == "7c45bd09807dc95870bc7e747e5a3225"
    exp = {  # pick -> (key on, added Protect sensor)
        "binary_sensor.foyer_fisheye_person_occupancy": (
            "f095ee1afbb60cd69699623eef1d3706", "binary_sensor.foyer_fisheye_person_detected"),
        "binary_sensor.upstairs_hall_person_occupancy_2": (
            "b063bbf5881d859b456429b6f3d41575", "binary_sensor.upstairs_hall_person_detected"),
        "binary_sensor.stairs_top_person_occupancy": (
            "74f1d0a01d1af703634f541c7db596e1", "binary_sensor.stairs_top_person_detected"),
    }
    assert set(on) == set(off) == set(exp)
    for pick, (key, added) in exp.items():
        assert on[pick][0] == key, pick
        assert set(on[pick][1]) - set(off[pick][1]) == {added}, pick
        assert set(off[pick][1]) <= set(on[pick][1]), pick


def test_perimeter_resolve_legs_unchanged(mods, monkeypatch):
    """perimeter_alert.py:2341 (`_resolve_legs` -> resolve_detection_legs): for
    every live perimeter camera AND garage_a_2 the leg set is identical on and
    off. W1 does not change perimeter Part A input on this house: develop's
    resolve_detection_legs already reached garage_a's Protect leg."""
    pa = mods.perimeter

    def legs():
        er_, dr_ = W.registries()
        mgr = pa.PerimeterAlertManager.__new__(pa.PerimeterAlertManager)
        mgr.hass = MagicMock()
        mgr.hass.data = {pa.DOMAIN: {"camera_manager": R._Mgr(
            mods.resolver.CameraResolver(er_, dr_))}}
        return {cam: sorted((l.entity_id, l.engine) for l in mgr._resolve_legs(cam, "person"))
                for cam in PERIMETER_CAMERAS + ["camera.garage_a_2"]}

    on = legs()
    monkeypatch.setattr(mods.resolver, KNOB, False)
    off = legs()
    assert on == off
    assert ("binary_sensor.garage_a_person_detected", "protect") in on["camera.garage_a_2"]


# ============================================================================
# Fix-up: B-L1 pairing INFO log, C-1 slugify import fail-closed
# ============================================================================

def test_resolver_pairing_info_log_once_per_pairing(caplog, monkeypatch):
    monkeypatch.setattr(RW, "_LOGGED_OBJECT_NAME_PAIRINGS", set())
    caplog.set_level("INFO", logger=RW._LOGGER.name)
    for _ in range(3):
        r = build(GA_FRIGATE, GA_PROTECT)
        sources(r, "camera.garage_a_2")
    hits = [rec.getMessage() for rec in caplog.records
            if "object-name pairing accepted" in rec.getMessage()]
    assert hits == ["CameraResolver: Frigate object-name pairing accepted: "
                    "frigate_device=f_ga protect_device=p_ga object_name=garage_a"]


def test_resolver_slugify_import_failure_fails_closed(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def _imp(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "homeassistant.util" and fromlist and "slugify" in fromlist:
            raise ImportError("no slugify")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _imp)
    r = build(GA_FRIGATE, GA_PROTECT)
    assert sources(r, "camera.garage_a_2") == F_ONLY
