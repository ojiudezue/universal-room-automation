"""RESACC-1 stage 2 — resolver-accuracy diff.

Measures ``CameraResolver.resolve_detection_legs`` +
``CameraResolver.enumerate_platform_cameras`` output against the HAND-BUILT
ground-truth fixture at ``docs/planning/AUDIT_resolver_ground_truth_manual.md``
(2026-08-07). The audit doc IS the acceptance fixture; every camera-key,
engine leg and canonical room encoded below is a direct transcription of the
"Ground truth — physical cameras with >1 engine" table.

Groups:
  - **Recall** — resolved leg set ⊇ fixture leg set (missing leg = lost
    corroboration).
  - **Precision** — no leg belonging to a *different* camera-key bleeds in.
  - **Adversarial near-miss** — armcrest vs armcrestash41b (fixture A-1),
    stairs_top vs staircase, back_yard substring bleed.
  - **Room attribution** — canonical room per the fixture table (A-2 and
    A-3 are pinned as xfail: expected to FAIL against current code, will
    flip to green automatically when fixed).
  - **Accuracy summary** — machine-readable counts written to
    ``/tmp/resacc1_summary.txt`` so the score is observable, not buried
    in pytest pass/fail.

Test-authority: drives PRODUCTION ``resolve_detection_legs`` /
``enumerate_platform_cameras``. No reimplementation of stem-matching or
leg-collapsing arithmetic. Fixture registries follow the duck-typed shape
already established in ``test_resolver_legs.py`` / ``test_camera_resolver.py``.
"""

from __future__ import annotations

import importlib.util as _il
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Direct-source import of the production resolver (same pattern as
# test_resolver_legs.py — avoids the custom_components package __init__).
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_RESOLVER_PATH = REPO_ROOT / "custom_components/universal_room_automation/camera_resolver.py"
_spec = _il.spec_from_file_location("camera_resolver_accuracy_under_test", _RESOLVER_PATH)
_mod = _il.module_from_spec(_spec)
sys.modules["camera_resolver_accuracy_under_test"] = _mod
_spec.loader.exec_module(_mod)

CameraResolver = _mod.CameraResolver
PLATFORM_FRIGATE = _mod.PLATFORM_FRIGATE
PLATFORM_UNIFI = _mod.PLATFORM_UNIFI
PLATFORM_REOLINK = _mod.PLATFORM_REOLINK
PLATFORM_DAHUA = _mod.PLATFORM_DAHUA


# Aliases from const.py — the two native-AI slug bridges the resolver needs
# via `stem_aliases`. Transcribed verbatim (a stale copy would silently
# unbind the armcrest + reolink-porch fusion, so we assert-match below).
EXTERIOR_CAMERA_KEY_ALIASES = {
    "armcrestpooloverhead": "armcrest",
    "ptzcamreolinktmixpstudybporch": "reolinkstudybporchptz",
}


def test_stem_alias_table_matches_const_module():
    """The alias table this test uses must equal the production one — a
    drift would silently mis-anchor every armcrest / reolink-porch assertion
    below."""
    src = (REPO_ROOT / "custom_components/universal_room_automation/const.py").read_text()
    for k, v in EXTERIOR_CAMERA_KEY_ALIASES.items():
        assert f'"{k}": "{v}"' in src, (k, v)


# ---------------------------------------------------------------------------
# Duck-typed HA registry fixtures (same shape as test_resolver_legs.py).
# ---------------------------------------------------------------------------


@dataclass
class FakeEntity:
    entity_id: str
    device_id: str | None = None
    platform: str = ""
    name: str = ""
    disabled_by: Any = None
    area_id: str | None = None

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]


@dataclass
class FakeDevice:
    id: str
    identifiers: set = field(default_factory=set)
    connections: set = field(default_factory=set)
    area_id: str | None = None


class FakeER:
    def __init__(self, entities):
        self.entities = {e.entity_id: e for e in entities}

    def async_get(self, eid):
        return self.entities.get(eid)


class FakeDR:
    def __init__(self, devices):
        self.devices = {d.id: d for d in devices}

    def async_get(self, did):
        return self.devices.get(did)


# ---------------------------------------------------------------------------
# GROUND TRUTH — transcribed from AUDIT_resolver_ground_truth_manual.md
# §"Ground truth — physical cameras with >1 engine". Do not edit unless the
# audit doc changes (and cite the audit revision in the commit message).
#
# For each camera-key: the legs the resolver MUST return (recall superset)
# + the canonical room (per fixture table's "canonical room" column).
# Frigate area is None for every exterior perimeter camera per A-3, EXCEPT
# armcrest which is A-2 (frigate area=pool, dahua area=balcony).
# ---------------------------------------------------------------------------


# Camera key -> {
#   "canonical_room": str | None,
#   "primary_camera_entity": str,   # entity to pass to resolve_detection_legs
#   "legs": tuple[str, ...],        # required binary_sensor legs
#   "frigate_area": str | None,     # area on the frigate device (fixture)
#   "protect_area": str | None,     # area on the protect device (fixture)
# }
FIXTURE = {
    # A-1/A-2: pool overhead — 2-source (frigate F2 + dahua). Frigate area
    # per A-2 is `pool`; dahua area per A-2 is `balcony` (the conflict).
    "armcrest": {
        "canonical_room": "pool",
        "primary_camera_entity": "camera.armcrest",
        "legs": (
            "binary_sensor.armcrest_person_occupancy",
            "binary_sensor.armcrestpooloverhead_smart_motion_human",
        ),
        "frigate_area": "pool",
        "dahua_area": "balcony",
    },
    # A-1: SEPARATE camera. Interior Study-A, F1 frigate only (single-engine
    # today; fixture pins it so precision test can assert non-bleed).
    "armcrestash41b": {
        "canonical_room": "study_a",
        "primary_camera_entity": "camera.armcrestash41b",
        "legs": ("binary_sensor.armcrestash41b_person_occupancy",),
        "frigate_area": "study_a",
        "protect_area": None,
    },
    # A-3: frigate area=None for every exterior perimeter camera below.
    "back_yard": {
        "canonical_room": "outside_perimeter",
        "primary_camera_entity": "camera.back_yard_high_resolution_channel",
        "legs": (
            "binary_sensor.back_yard_person_occupancy",
            "binary_sensor.back_yard_person_detected",
        ),
        "frigate_area": None,
        "protect_area": "outside_perimeter",
    },
    "hot_tub": {
        "canonical_room": "outside_perimeter",
        "primary_camera_entity": "camera.hot_tub_high_resolution_channel",
        "legs": (
            "binary_sensor.hot_tub_person_occupancy",
            "binary_sensor.hot_tub_person_detected",
        ),
        "frigate_area": None,
        "protect_area": "outside_perimeter",
    },
    "pool_equipment": {
        "canonical_room": "outside_perimeter",
        "primary_camera_entity": "camera.pool_equipment_high_resolution_channel",
        "legs": (
            "binary_sensor.pool_equipment_person_occupancy",
            "binary_sensor.pool_equipment_person_detected",
        ),
        "frigate_area": None,
        "protect_area": "outside_perimeter",
    },
    "front_side_ptz": {
        "canonical_room": "outside_perimeter",
        "primary_camera_entity": "camera.front_side_ptz_high_resolution_channel",
        "legs": (
            "binary_sensor.front_side_ptz_person_occupancy",
            "binary_sensor.front_side_ptz_person_detected",
        ),
        "frigate_area": None,
        "protect_area": "outside_perimeter",
    },
    "g5_bullet": {
        "canonical_room": "outside_perimeter",
        "primary_camera_entity": "camera.g5_bullet_high_resolution_channel",
        "legs": (
            "binary_sensor.g5_bullet_person_occupancy",
            "binary_sensor.g5_bullet_person_detected",
        ),
        "frigate_area": None,
        "protect_area": "outside_perimeter",
    },
    "rear_ptz": {
        "canonical_room": "outside_perimeter",
        "primary_camera_entity": "camera.rear_ptz_high_resolution_channel",
        "legs": (
            "binary_sensor.rear_ptz_person_occupancy",
            "binary_sensor.rear_ptz_person_detected",
        ),
        "frigate_area": None,
        "protect_area": "outside_perimeter",
    },
    "front_door_aerial": {
        "canonical_room": "front_porch",
        "primary_camera_entity": "camera.front_door_aerial_high_resolution_channel",
        "legs": (
            "binary_sensor.front_door_aerial_person_occupancy",
            "binary_sensor.front_door_aerial_person_detected",
        ),
        "frigate_area": "front_porch",  # "agree" — frigate has real area
        "protect_area": "front_porch",
    },
    "doorbell_lite": {
        # A-3 explicit: frigate area=None for doorbell_lite.
        "canonical_room": "garage_a",
        "primary_camera_entity": "camera.doorbell_lite_high_resolution_channel",
        "legs": (
            "binary_sensor.doorbell_lite_person_occupancy",
            "binary_sensor.doorbell_lite_person_detected",
        ),
        "frigate_area": None,
        "protect_area": "garage_a",
    },
    "madrone_g6_entry": {
        "canonical_room": None,  # fixture: (unset)
        "primary_camera_entity": "camera.madrone_g6_entry_high_resolution_channel",
        "legs": (
            "binary_sensor.madrone_g6_entry_person_occupancy",
            "binary_sensor.madrone_g6_entry_person_detected",
        ),
        "frigate_area": None,
        "protect_area": None,
    },
    # Fixture-table camera-key column says `reolinkstudybporch`; the actual
    # Frigate object slug in the same row is `reolinkstudybporchptz` (the
    # "ptz" suffix on the frigate side; the reolink native slug is
    # `ptzcamreolinktmixpstudybporch` and bridges via the alias table).
    # We key on the frigate slug so registry synthesis stays consistent.
    "reolinkstudybporchptz": {
        "canonical_room": "patio",
        "primary_camera_entity": "camera.reolinkstudybporchptz",
        "legs": (
            "binary_sensor.reolinkstudybporchptz_person_occupancy",
            "binary_sensor.ptzcamreolinktmixpstudybporch_person",
        ),
        "frigate_area": None,   # fixture: frigate area=None
        "reolink_area": "patio",
    },
    "foyer_fisheye": {
        "canonical_room": "entry_way",
        "primary_camera_entity": "camera.foyer_fisheye_high_resolution_channel",
        "legs": (
            "binary_sensor.foyer_fisheye_person_occupancy",
            "binary_sensor.foyer_fisheye_person_detected",
        ),
        "frigate_area": "entry_way",
        "protect_area": "entry_way",
    },
    "family_room": {
        "canonical_room": "living_room",
        "primary_camera_entity": "camera.family_room_high_resolution_channel",
        "legs": (
            "binary_sensor.family_room_person_occupancy",
            "binary_sensor.family_room_person_detected",
        ),
        "frigate_area": "living_room",
        "protect_area": "living_room",
    },
    "garage_a": {
        "canonical_room": "garage_a",
        "primary_camera_entity": "camera.garage_a_high_resolution_channel",
        "legs": (
            "binary_sensor.garage_a_person_occupancy",
            "binary_sensor.garage_a_person_detected",
        ),
        "frigate_area": "garage_a",
        "protect_area": "garage_a",
    },
    "garage_b": {
        "canonical_room": "garage_b",
        "primary_camera_entity": "camera.garage_b_high_resolution_channel",
        "legs": (
            "binary_sensor.garage_b_person_occupancy",
            "binary_sensor.garage_b_person_detected",
        ),
        "frigate_area": "garage_b",
        "protect_area": "garage_b",
    },
    "master_hallway": {
        "canonical_room": "master_hallway",
        "primary_camera_entity": "camera.master_hallway_high_resolution_channel",
        "legs": (
            "binary_sensor.master_hallway_person_occupancy",
            "binary_sensor.master_hallway_person_detected",
        ),
        "frigate_area": "master_hallway",
        "protect_area": "master_hallway",
    },
    "playroom": {
        "canonical_room": "game_room",
        "primary_camera_entity": "camera.playroom_high_resolution_channel",
        "legs": (
            "binary_sensor.playroom_person_occupancy",
            "binary_sensor.playroom_person_detected",
        ),
        "frigate_area": "game_room",
        "protect_area": "game_room",
    },
    "stairs_top": {
        "canonical_room": "stairs",
        "primary_camera_entity": "camera.stairs_top_high_resolution_channel",
        "legs": (
            "binary_sensor.stairs_top_person_occupancy",
            "binary_sensor.stairs_top_person_detected",
        ),
        "frigate_area": "stairs",
        "protect_area": "stairs",
    },
    "upstairs_hall": {
        "canonical_room": "upstairs_hallway",
        "primary_camera_entity": "camera.upstairs_hall_high_resolution_channel",
        "legs": (
            "binary_sensor.upstairs_hall_person_occupancy",
            "binary_sensor.upstairs_hall_person_detected",
        ),
        "frigate_area": "upstairs_hallway",
        "protect_area": "upstairs_hallway",
    },
}


# Near-miss cameras present in the registry to prove non-bleed. These are
# NOT in the multi-engine fusion table — they exist so precision tests can
# assert their legs never fold into another camera's fusion.
NEAR_MISS_INTERIOR = {
    # `staircase` — Protect-only interior camera whose stem shares the
    # "stair" family with `stairs_top`. Must NOT fuse.
    "staircase": {
        "canonical_room": "staircase",
        "leg": "binary_sensor.staircase_person_detected",
    },
    # A `back_yard_grill` interior stub — a name that SHARES the `back_yard`
    # prefix but is a separate physical camera. Must NOT fuse with back_yard.
    "back_yard_grill": {
        "canonical_room": "kitchen",
        "leg": "binary_sensor.back_yard_grill_person_detected",
    },
}


# ---------------------------------------------------------------------------
# Registry builder — one call, one CameraResolver against the whole fixture.
# ---------------------------------------------------------------------------


def _build_fixture_registry() -> tuple[list[FakeEntity], list[FakeDevice]]:
    ents: list[FakeEntity] = []
    devs: list[FakeDevice] = []
    host_counter = {"frigate": 0}

    for key, spec in FIXTURE.items():
        f_area = spec.get("frigate_area")
        p_area = spec.get("protect_area")

        # Frigate device (always present for keys in the fixture table).
        host_counter["frigate"] += 1
        host = f"h{host_counter['frigate']}"
        f_did = f"dev_f_{key}"
        # The frigate object-name in identifiers is the camera-key.
        devs.append(FakeDevice(
            id=f_did,
            identifiers={(PLATFORM_FRIGATE, f"{host}:{key}")},
            area_id=f_area,
        ))
        # Frigate camera entity uses raw key as slug.
        ents.append(FakeEntity(
            entity_id=f"camera.{key}",
            device_id=f_did,
            platform=PLATFORM_FRIGATE,
            area_id=f_area,
        ))
        # Frigate person_occupancy leg.
        ents.append(FakeEntity(
            entity_id=f"binary_sensor.{key}_person_occupancy",
            device_id=f_did,
            platform=PLATFORM_FRIGATE,
            area_id=f_area,
        ))

        # Protect leg if the fixture lists one.
        if key not in ("armcrest", "armcrestash41b", "reolinkstudybporchptz"):
            p_did = f"dev_p_{key}"
            devs.append(FakeDevice(
                id=p_did,
                identifiers={(PLATFORM_UNIFI, f"pr-{key}")},
                area_id=p_area,
            ))
            ents.append(FakeEntity(
                entity_id=f"camera.{key}_high_resolution_channel",
                device_id=p_did,
                platform=PLATFORM_UNIFI,
                area_id=p_area,
            ))
            ents.append(FakeEntity(
                entity_id=f"binary_sensor.{key}_person_detected",
                device_id=p_did,
                platform=PLATFORM_UNIFI,
                area_id=p_area,
            ))

    # armcrest — add dahua native-AI leg on its own device.
    dahua_did = "dev_d_armcrestpooloverhead"
    devs.append(FakeDevice(
        id=dahua_did,
        identifiers={(PLATFORM_DAHUA, "amc-armcrestpooloverhead")},
        connections={("mac", "a0:60:32:06:34:8e")},
        area_id=FIXTURE["armcrest"]["dahua_area"],
    ))
    ents.append(FakeEntity(
        entity_id="camera.armcrestpooloverhead_main",
        device_id=dahua_did,
        platform=PLATFORM_DAHUA,
        area_id=FIXTURE["armcrest"]["dahua_area"],
    ))
    ents.append(FakeEntity(
        entity_id="binary_sensor.armcrestpooloverhead_smart_motion_human",
        device_id=dahua_did,
        platform=PLATFORM_DAHUA,
        area_id=FIXTURE["armcrest"]["dahua_area"],
    ))

    # reolinkstudybporch — add reolink native-AI leg on its own device.
    reo_did = "dev_r_reolinkstudybporchptz"
    devs.append(FakeDevice(
        id=reo_did,
        identifiers={(PLATFORM_REOLINK, "reo-porchptz")},
        connections={("mac", "b0:b0:b0:b0:b0:b0")},
        area_id=FIXTURE["reolinkstudybporchptz"]["reolink_area"],
    ))
    ents.append(FakeEntity(
        entity_id="camera.ptzcamreolinktmixpstudybporch",
        device_id=reo_did,
        platform=PLATFORM_REOLINK,
        area_id=FIXTURE["reolinkstudybporchptz"]["reolink_area"],
    ))
    ents.append(FakeEntity(
        entity_id="binary_sensor.ptzcamreolinktmixpstudybporch_person",
        device_id=reo_did,
        platform=PLATFORM_REOLINK,
        area_id=FIXTURE["reolinkstudybporchptz"]["reolink_area"],
    ))

    # Near-miss interior cameras (staircase, back_yard_grill).
    for nm_key, nm_spec in NEAR_MISS_INTERIOR.items():
        nm_did = f"dev_p_{nm_key}"
        devs.append(FakeDevice(
            id=nm_did,
            identifiers={(PLATFORM_UNIFI, f"pr-{nm_key}")},
            area_id=nm_spec["canonical_room"],
        ))
        ents.append(FakeEntity(
            entity_id=f"camera.{nm_key}_high_resolution_channel",
            device_id=nm_did,
            platform=PLATFORM_UNIFI,
            area_id=nm_spec["canonical_room"],
        ))
        ents.append(FakeEntity(
            entity_id=nm_spec["leg"],
            device_id=nm_did,
            platform=PLATFORM_UNIFI,
            area_id=nm_spec["canonical_room"],
        ))

    return ents, devs


@pytest.fixture(scope="module")
def resolver() -> CameraResolver:
    ents, devs = _build_fixture_registry()
    return CameraResolver(FakeER(ents), FakeDR(devs))


# All non-primary leg entity_ids across the fixture, keyed by camera-key.
# Used by the precision test to build the "wrong-camera" leg pool.
def _all_leg_pool() -> dict[str, set[str]]:
    pool: dict[str, set[str]] = {}
    for key, spec in FIXTURE.items():
        pool[key] = set(spec["legs"])
    for nm_key, nm_spec in NEAR_MISS_INTERIOR.items():
        pool[nm_key] = {nm_spec["leg"]}
    return pool


# ---------------------------------------------------------------------------
# GROUP 1 — recall (parametrized: one test per multi-engine camera).
# ---------------------------------------------------------------------------


_MULTI_ENGINE_KEYS = [
    k for k, s in FIXTURE.items() if len(s["legs"]) > 1
]


@pytest.mark.parametrize("cam_key", _MULTI_ENGINE_KEYS)
def test_recall_resolves_all_fixture_legs(resolver, cam_key):
    """Resolved leg set must be a superset of the fixture's listed legs.

    A missing leg = lost corroboration; a real fusion regression.
    """
    spec = FIXTURE[cam_key]
    legs = resolver.resolve_detection_legs(
        spec["primary_camera_entity"], "person",
        stem_aliases=EXTERIOR_CAMERA_KEY_ALIASES,
    )
    got = {l.entity_id for l in legs}
    expected = set(spec["legs"])
    missing = expected - got
    assert not missing, (
        f"camera-key={cam_key!r}: resolver missed {sorted(missing)}. "
        f"resolved={sorted(got)}"
    )


# ---------------------------------------------------------------------------
# GROUP 2 — precision (no bleed from other camera-keys' legs).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cam_key", list(FIXTURE.keys()))
def test_precision_no_cross_camera_bleed(resolver, cam_key):
    """The resolved leg set contains NO leg belonging to a different
    camera-key."""
    spec = FIXTURE[cam_key]
    legs = resolver.resolve_detection_legs(
        spec["primary_camera_entity"], "person",
        stem_aliases=EXTERIOR_CAMERA_KEY_ALIASES,
    )
    got = {l.entity_id for l in legs}
    own = set(spec["legs"])
    pool = _all_leg_pool()
    foreign: set[str] = set()
    for other_key, other_legs in pool.items():
        if other_key == cam_key:
            continue
        foreign |= (other_legs - own)
    bleed = got & foreign
    assert not bleed, (
        f"camera-key={cam_key!r}: resolver pulled foreign legs {sorted(bleed)}. "
        f"resolved={sorted(got)}"
    )


# ---------------------------------------------------------------------------
# GROUP 3 — adversarial near-miss (the most important precision assertions).
# ---------------------------------------------------------------------------


def test_near_miss_armcrest_vs_armcrestash41b_do_not_fuse(resolver):
    """AUDIT §A-1: `armcrest` (pool overhead: F2 + dahua) and
    `armcrestash41b` (interior Study-A, F1) share a brand prefix but are
    DIFFERENT physical cameras. A prefix/substring stem match would merge
    the pool camera with a Study-A interior camera and mis-route alerts.
    """
    armcrest_legs = {
        l.entity_id for l in resolver.resolve_detection_legs(
            "camera.armcrest", "person",
            stem_aliases=EXTERIOR_CAMERA_KEY_ALIASES,
        )
    }
    ash_leg = "binary_sensor.armcrestash41b_person_occupancy"
    assert ash_leg not in armcrest_legs, (
        f"PRECISION HAZARD (A-1): armcrestash41b interior leg bled into "
        f"armcrest fusion. legs={sorted(armcrest_legs)}"
    )
    # Symmetric direction: armcrestash41b must not pull the pool legs.
    ash_legs = {
        l.entity_id for l in resolver.resolve_detection_legs(
            "camera.armcrestash41b", "person",
            stem_aliases=EXTERIOR_CAMERA_KEY_ALIASES,
        )
    }
    pool_pool = {
        "binary_sensor.armcrest_person_occupancy",
        "binary_sensor.armcrestpooloverhead_smart_motion_human",
    }
    bleed = ash_legs & pool_pool
    assert not bleed, (
        f"PRECISION HAZARD (A-1 symmetric): pool legs bled into "
        f"armcrestash41b. bleed={sorted(bleed)}"
    )


def test_near_miss_stairs_top_vs_staircase_do_not_fuse(resolver):
    """`stairs_top` (perimeter stair-landing camera) vs `staircase`
    (interior Protect camera). Same "stair" family, different physical
    cameras — must not fuse."""
    stairs_top_legs = {
        l.entity_id for l in resolver.resolve_detection_legs(
            "camera.stairs_top_high_resolution_channel", "person",
            stem_aliases=EXTERIOR_CAMERA_KEY_ALIASES,
        )
    }
    assert "binary_sensor.staircase_person_detected" not in stairs_top_legs, (
        f"stairs_top pulled staircase leg. legs={sorted(stairs_top_legs)}"
    )


def test_near_miss_back_yard_substring_bleed(resolver):
    """`back_yard_grill` is a separate physical camera sharing a stem
    prefix with `back_yard`. Substring/prefix stem match would merge them."""
    back_yard_legs = {
        l.entity_id for l in resolver.resolve_detection_legs(
            "camera.back_yard_high_resolution_channel", "person",
            stem_aliases=EXTERIOR_CAMERA_KEY_ALIASES,
        )
    }
    assert "binary_sensor.back_yard_grill_person_detected" not in back_yard_legs, (
        f"back_yard pulled back_yard_grill leg. legs={sorted(back_yard_legs)}"
    )


# ---------------------------------------------------------------------------
# GROUP 4 — room attribution.
#
# Strategy: enumerate cameras of platform=unifiprotect (the authoritative
# area source per fixture) and diff each returned camera's area_id against
# the fixture's canonical_room. Then a SEPARATE test enumerates on Frigate
# for the exterior perimeter set — those are the A-3 xfail cases.
# ---------------------------------------------------------------------------


def test_room_attribution_protect_enumeration(resolver):
    """Enumerating on `unifiprotect` returns the canonical room per fixture
    for every camera-key that has a Protect leg. This is the WORKING path —
    Protect area is authoritative per fixture A-3."""
    cams = resolver.enumerate_platform_cameras("unifiprotect", "person")
    by_stem = {}
    for c in cams:
        # Grouping is by (device_id, stem); we recover the stem by
        # stripping the person suffix from the primary entity.
        name = c.primary_entity.split(".", 1)[1]
        stem = name[: -len("_person_detected")] if name.endswith("_person_detected") else name
        by_stem[stem] = c
    mismatches: list[tuple[str, str | None, str | None]] = []
    for key, spec in FIXTURE.items():
        if key in ("armcrest", "armcrestash41b", "reolinkstudybporchptz"):
            continue  # no protect leg
        got = by_stem.get(key)
        assert got is not None, f"protect enumeration missing camera-key {key!r}"
        if got.area_id != spec["canonical_room"]:
            mismatches.append((key, got.area_id, spec["canonical_room"]))
    assert not mismatches, f"room mismatches (got, expected): {mismatches}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "AUDIT §A-3: every exterior perimeter camera's Frigate leg carries "
        "area=None while the Protect sibling carries the real area. "
        "enumerate_platform_cameras('frigate') restricts the cross-leg area "
        "fallback to same-integration (F4 fix, line ~1133) so exterior "
        "cameras enumerate with area=None. Fixture calls this "
        "'the single highest-impact accuracy bug in the current data'."
    ),
)
def test_room_attribution_frigate_enumeration_A3(resolver):
    """A-3: Frigate enumeration for exterior perimeter cameras must yield
    the canonical room. Currently returns area=None."""
    cams = resolver.enumerate_platform_cameras("frigate", "person")
    by_stem = {}
    for c in cams:
        name = c.primary_entity.split(".", 1)[1]
        stem = name[: -len("_person_occupancy")] if name.endswith("_person_occupancy") else name
        by_stem[stem] = c
    A3_EXTERIOR = (
        "back_yard", "hot_tub", "pool_equipment", "front_side_ptz",
        "g5_bullet", "rear_ptz", "doorbell_lite",
    )
    mismatches: list[tuple[str, str | None, str | None]] = []
    for key in A3_EXTERIOR:
        got = by_stem.get(key)
        assert got is not None, f"frigate enumeration missing {key!r}"
        if got.area_id != FIXTURE[key]["canonical_room"]:
            mismatches.append((key, got.area_id, FIXTURE[key]["canonical_room"]))
    assert not mismatches, mismatches


@pytest.mark.xfail(
    strict=True,
    reason=(
        "AUDIT §A-2: armcrest dahua leg area=`balcony`, frigate legs "
        "area=`pool`. Same camera, two rooms. Resolver must pick `pool` "
        "canonically. enumerate_platform_cameras('dahua') on the pool "
        "overhead primary entity returns `balcony` because the cross-leg "
        "area fallback is restricted to same-integration and the dahua "
        "primary's own area is `balcony`."
    ),
)
def test_room_attribution_armcrest_A2_dahua_primary(resolver):
    """A-2: Enumerating armcrest via its dahua primary must resolve to
    canonical room `pool`. Currently returns `balcony`."""
    cams = resolver.enumerate_platform_cameras("dahua", "person")
    # Only one dahua camera in the fixture.
    assert len(cams) == 1, [c.primary_entity for c in cams]
    assert cams[0].area_id == "pool", (
        f"armcrest dahua enumeration area_id={cams[0].area_id!r}, "
        f"expected 'pool' (canonical per fixture A-2)"
    )


# ---------------------------------------------------------------------------
# GROUP 5 — machine-readable accuracy summary.
# ---------------------------------------------------------------------------


def test_accuracy_summary_emit(resolver, capsys, tmp_path):
    """Compute + emit an accuracy score across the fixture. Writes to
    stdout (visible under `pytest -s`) AND to a fixed path so the score is
    observable and re-runnable, not buried in pytest pass/fail counts.

    NOTE: this test always PASSES — it exists to publish the numbers. The
    accuracy failures are asserted by the parametrized recall/precision
    tests above.
    """
    pool = _all_leg_pool()
    cameras_checked = 0
    recall_hits = 0
    recall_misses = 0
    precision_violations = 0
    room_matches = 0
    room_mismatches = 0
    per_camera: list[str] = []

    for key, spec in FIXTURE.items():
        cameras_checked += 1
        legs = resolver.resolve_detection_legs(
            spec["primary_camera_entity"], "person",
            stem_aliases=EXTERIOR_CAMERA_KEY_ALIASES,
        )
        got = {l.entity_id for l in legs}
        expected = set(spec["legs"])
        missing = expected - got
        if missing:
            recall_misses += len(missing)
        recall_hits += len(expected & got)
        foreign: set[str] = set()
        for other_key, other_legs in pool.items():
            if other_key == key:
                continue
            foreign |= (other_legs - expected)
        bleed = got & foreign
        if bleed:
            precision_violations += len(bleed)
        per_camera.append(
            f"  {key:24s} recall={len(expected & got)}/{len(expected)} "
            f"precision_bleed={len(bleed)} missing={sorted(missing)} "
            f"bleed={sorted(bleed)}"
        )

    # Room attribution via Protect enumeration (working path).
    cams_p = {
        c.primary_entity.rsplit("_person_detected", 1)[0].split(".", 1)[1]: c
        for c in resolver.enumerate_platform_cameras("unifiprotect", "person")
    }
    for key, spec in FIXTURE.items():
        if key in ("armcrest", "armcrestash41b", "reolinkstudybporchptz"):
            continue
        got = cams_p.get(key)
        if got is not None and got.area_id == spec["canonical_room"]:
            room_matches += 1
        else:
            room_mismatches += 1

    summary_lines = [
        "===== RESACC-1 accuracy summary =====",
        f"cameras_checked          : {cameras_checked}",
        f"recall_hits              : {recall_hits}",
        f"recall_misses            : {recall_misses}",
        f"precision_violations     : {precision_violations}",
        f"room_matches   (Protect) : {room_matches}",
        f"room_mismatches(Protect) : {room_mismatches}",
        "per-camera:",
        *per_camera,
        "=====================================",
    ]
    summary = "\n".join(summary_lines)
    print("\n" + summary)
    # Fixed path (best-effort — a read-only FS is not a test failure).
    try:
        out = Path("/tmp/resacc1_summary.txt")
        out.write_text(summary + "\n")
    except Exception:
        pass
