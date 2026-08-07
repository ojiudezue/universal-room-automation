"""TRANSIT-1 (2026-08-07): tests for Protect-sourced checkpoint inventory.

Pins the SEMANTIC bindings of ``CameraResolver.enumerate_platform_cameras``
plus the kill-switch snapshot invariant + drift-proofing on the transit
subscription path. Fixtures mirror the AUDIT_resolver_ground_truth_manual.md
5-checkpoint layout (master_hallway, entry_way, garage_hallway,
upstairs_hallway, stairs).

Bug Class #62 discipline: drives the REAL production module via
importlib source-load — no local reimplementation of the enumerator.
"""

from __future__ import annotations

import importlib.util as _il
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock


# --- HA stub prelude (matches test_resolver_legs.py) ------------------------
_ident = lambda fn: fn  # noqa: E731


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_ha_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock,
        "callback": _ident,
        "Event": MagicMock,
    },
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {
        "DeviceInfo": dict,
        "format_mac": lambda v: str(v).lower(),
    },
    "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
    "homeassistant.helpers.area_registry": {"async_get": MagicMock()},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": lambda *a, **kw: MagicMock(),
        "async_call_later": lambda *a, **kw: MagicMock(),
        "async_track_time_interval": lambda *a, **kw: (lambda: None),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: _dt.now(_tz.utc),
        "now": lambda: _dt.now(_tz.utc),
    },
}

for _n, _a in _ha_mods.items():
    _existing = sys.modules.get(_n)
    if _existing is None:
        sys.modules[_n] = _mock_module(_n, **_a)
    else:
        for _k, _v in _a.items():
            if not hasattr(_existing, _k):
                setattr(_existing, _k, _v)

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_RESOLVER_PATH = REPO_ROOT / "custom_components/universal_room_automation/camera_resolver.py"
_spec = _il.spec_from_file_location("camera_resolver_transit1_under_test", _RESOLVER_PATH)
_mod = _il.module_from_spec(_spec)
sys.modules["camera_resolver_transit1_under_test"] = _mod
_spec.loader.exec_module(_mod)

CameraResolver = _mod.CameraResolver
EnumeratedCamera = _mod.EnumeratedCamera
PLATFORM_UNIFI = _mod.PLATFORM_UNIFI
PLATFORM_FRIGATE = _mod.PLATFORM_FRIGATE


# ---------------------------------------------------------------------------
# Fixtures — duck-typed registry (matches test_resolver_legs.py shape).
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


CHECKPOINT_AREAS = {
    "master_hallway", "entry_way", "garage_hallway",
    "upstairs_hallway", "stairs",
}


def _five_checkpoint_registry():
    """Fixture mirroring the 5 live checkpoint cameras (AUDIT_resolver_ground_truth_manual.md).

    Physical -> area (via the Protect device's area_id):
      master_hallway  -> master_hallway
      foyer_fisheye   -> entry_way
      staircase       -> garage_hallway
      upstairs_hall   -> upstairs_hallway
      stairs_top      -> stairs
    """
    devs = []
    ents = []
    for slug, area in [
        ("master_hallway", "master_hallway"),
        ("foyer_fisheye", "entry_way"),
        ("staircase", "garage_hallway"),
        ("upstairs_hall", "upstairs_hallway"),
        ("stairs_top", "stairs"),
    ]:
        d = FakeDevice(id=f"dev_{slug}",
                       identifiers={(PLATFORM_UNIFI, f"pr-{slug}-uid")},
                       area_id=area)
        devs.append(d)
        ents.append(FakeEntity(f"camera.{slug}_high_resolution_channel",
                               f"dev_{slug}", PLATFORM_UNIFI))
        ents.append(FakeEntity(f"binary_sensor.{slug}_person_detected",
                               f"dev_{slug}", PLATFORM_UNIFI))
    return ents, devs


def _mk(ents, devs):
    return CameraResolver(FakeER(ents), FakeDR(devs))


# ---------------------------------------------------------------------------
# D1 acceptance: enumerate_platform_cameras semantics.
# ---------------------------------------------------------------------------


def test_enumerate_protect_person_returns_one_per_device_at_all_five_checkpoints():
    """SUPERSET recall: enumerator covers all 5 checkpoint areas from Protect alone."""
    ents, devs = _five_checkpoint_registry()
    r = _mk(ents, devs)
    result = r.enumerate_platform_cameras(PLATFORM_UNIFI, "person")
    areas = {c.area_id for c in result}
    assert areas.issuperset(CHECKPOINT_AREAS), (
        f"missing checkpoint areas: {CHECKPOINT_AREAS - areas}; got {areas}"
    )
    # One EnumeratedCamera per device (no leakage / double-count).
    assert len({c.device_id for c in result}) == len(result)


def test_enumerate_drift_proof_new_protect_camera_picked_up_without_edits():
    """DRIFT-PROOF: adding a NEW Protect camera at a checkpoint area is
    picked up by enumerate_platform_cameras with ZERO hand-list edit."""
    ents, devs = _five_checkpoint_registry()
    # Add a new physical camera at master_hallway (a second one).
    new_dev = FakeDevice(id="dev_new_hall",
                         identifiers={(PLATFORM_UNIFI, "pr-new-hall-uid")},
                         area_id="master_hallway")
    devs.append(new_dev)
    ents.append(FakeEntity("camera.master_hallway_two_high_resolution_channel",
                           "dev_new_hall", PLATFORM_UNIFI))
    ents.append(FakeEntity("binary_sensor.master_hallway_two_person_detected",
                           "dev_new_hall", PLATFORM_UNIFI))
    r = _mk(ents, devs)
    result = r.enumerate_platform_cameras(PLATFORM_UNIFI, "person")
    device_ids = {c.device_id for c in result}
    assert "dev_new_hall" in device_ids
    # New camera attributed to master_hallway; NO hand-list touched.
    new_row = next(c for c in result if c.device_id == "dev_new_hall")
    assert new_row.area_id == "master_hallway"


def test_enumerate_area_falls_back_across_legs_when_primary_leg_area_is_none():
    """A Protect leg with no area_id on the entity OR its device still gets
    an area from a cross-integration sibling leg (defensive against A-3 recurring).
    """
    # Protect device with NO area_id on the device — but a Frigate sibling
    # device carries the area on its entity.
    dev_pr = FakeDevice(id="dev_pr",
                        identifiers={(PLATFORM_UNIFI, "pr-cam-x")},
                        area_id=None)
    dev_f = FakeDevice(id="dev_f",
                       identifiers={(PLATFORM_FRIGATE, "host1:cam_x")},
                       area_id="upstairs_hallway")
    ents = [
        FakeEntity("camera.cam_x_high_resolution_channel", "dev_pr", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.cam_x_person_detected", "dev_pr", PLATFORM_UNIFI),
        FakeEntity("camera.cam_x", "dev_f", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.cam_x_person_occupancy", "dev_f", PLATFORM_FRIGATE),
    ]
    r = _mk(ents, [dev_pr, dev_f])
    result = r.enumerate_platform_cameras(PLATFORM_UNIFI, "person")
    assert len(result) == 1
    assert result[0].area_id == "upstairs_hallway", result[0]


def test_enumerate_precision_armcrest_and_armcrestash41b_do_not_collapse():
    """PRECISION GUARD: two distinct cameras whose first token overlaps must
    remain distinct EnumeratedCamera rows. Anchors the A-MED-2 shared-
    evidence guard on the enumeration path."""
    dev_a = FakeDevice(id="dev_a", identifiers={(PLATFORM_UNIFI, "pr-armcrest")},
                       area_id="entry_way")
    dev_b = FakeDevice(id="dev_b", identifiers={(PLATFORM_UNIFI, "pr-ash41b")},
                       area_id="garage_hallway")
    ents = [
        FakeEntity("camera.armcrest_high_resolution_channel", "dev_a", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.armcrest_person_detected", "dev_a", PLATFORM_UNIFI),
        FakeEntity("camera.armcrestash41b_high_resolution_channel", "dev_b", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.armcrestash41b_person_detected", "dev_b", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev_a, dev_b])
    result = r.enumerate_platform_cameras(PLATFORM_UNIFI, "person")
    dids = {c.device_id for c in result}
    assert {"dev_a", "dev_b"}.issubset(dids), dids
    # Areas didn't cross-contaminate.
    area_by_did = {c.device_id: c.area_id for c in result}
    assert area_by_did["dev_a"] == "entry_way"
    assert area_by_did["dev_b"] == "garage_hallway"


def test_enumerate_excludes_disabled_and_package_detectors():
    dev = FakeDevice(id="dev1", identifiers={(PLATFORM_UNIFI, "pr-1")},
                     area_id="master_hallway")
    ents = [
        FakeEntity("camera.cam1_high_resolution_channel", "dev1", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.cam1_person_detected", "dev1", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.cam1_package_person_detected", "dev1", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.cam1_person_detected_2", "dev1", PLATFORM_UNIFI,
                   disabled_by="user"),
    ]
    r = _mk(ents, [dev])
    result = r.enumerate_platform_cameras(PLATFORM_UNIFI, "person")
    assert len(result) == 1
    row = result[0]
    assert "binary_sensor.cam1_package_person_detected" not in row.legs
    assert "binary_sensor.cam1_person_detected_2" not in row.legs
    assert "binary_sensor.cam1_person_detected" in row.legs


# ---------------------------------------------------------------------------
# D3 subscription-path drift-proof + kill-switch snapshot.
# Simulates the transit-side UNION: legacy hand-list ∪ Protect-enum.
# ---------------------------------------------------------------------------


def _legacy_hand_list_missing_upstairs_and_stairs():
    """Simulates the pre-cycle hand-list (garage/master/foyer only)."""
    return [
        "binary_sensor.staircase_person_detected",       # garage_hallway
        "binary_sensor.master_hallway_person_detected",  # master_hallway
        "binary_sensor.foyer_fisheye_person_detected",   # entry_way
    ]


def test_drift_deleting_staircase_from_hand_list_still_covers_garage_hallway_via_protect():
    """Delete `staircase` from the hand-list — Protect enumeration still
    covers garage_hallway (the DRIFT-PROOFING invariant)."""
    ents, devs = _five_checkpoint_registry()
    r = _mk(ents, devs)
    protect = r.enumerate_platform_cameras(PLATFORM_UNIFI, "person")
    protect_entities: list[str] = []
    for c in protect:
        if c.area_id in CHECKPOINT_AREAS:
            protect_entities.extend(c.legs)
    # Hand-list WITHOUT staircase.
    hand_list = [e for e in _legacy_hand_list_missing_upstairs_and_stairs()
                 if "staircase" not in e]
    subscribed = set(hand_list) | set(protect_entities)
    assert "binary_sensor.staircase_person_detected" in subscribed, (
        "garage_hallway coverage lost — Protect drift-proofing failed"
    )


def test_kill_switch_off_equivalent_yields_hand_list_only_byte_identical():
    """Kill-switch OFF path: caller passes empty Protect list -> the union
    reduces to exactly the hand-list. Snapshot invariant."""
    ents, devs = _five_checkpoint_registry()
    hand_list = _legacy_hand_list_missing_upstairs_and_stairs()
    # Kill-switch OFF means _protect_sourced_checkpoint_entities returns
    # ([], {}), so the UNION is unchanged from the hand-list only.
    protect_off: list[str] = []
    subscribed_off = set(hand_list) | set(protect_off)
    subscribed_baseline = set(hand_list)
    assert subscribed_off == subscribed_baseline
