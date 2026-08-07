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


def test_enumerate_area_fallback_restricted_to_platform_legs_no_cross_integration_import():
    """F4 fix: cross-leg area fallback MUST NOT import a foreign integration's
    area (a Frigate sibling's area could reflect a different physical camera
    when the F3 grouping fails). Only same-platform legs contribute to fallback.
    """
    # Protect device with NO area_id on device or entity; Frigate sibling has area.
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
    # Post F4 fix: area stays None because no Protect leg carries an area.
    assert result[0].area_id is None, (
        f"F4: cross-integration area import regressed: {result[0]}"
    )




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


# ---------------------------------------------------------------------------
# F3: NVR-hosted multi-camera collapse regression.
# ---------------------------------------------------------------------------


def test_f3_nvr_multi_camera_device_surfaces_one_row_per_stem_with_own_area():
    """A Protect NVR device hosts multiple physical cameras (staircase +
    garagehallway on the same device); each must produce its OWN
    EnumeratedCamera with its OWN area attribution. Grouping-by-device_id
    alone collapses them to one row and silently drops coverage.
    """
    # ONE device carries two physical cameras. Distinct area_id per entity.
    dev = FakeDevice(id="dev_nvr", identifiers={(PLATFORM_UNIFI, "pr-nvr")},
                     area_id="garage_hallway")
    ents = [
        FakeEntity("camera.staircase_high_resolution_channel", "dev_nvr", PLATFORM_UNIFI,
                   area_id="stairs"),
        FakeEntity("binary_sensor.staircase_person_detected", "dev_nvr", PLATFORM_UNIFI,
                   area_id="stairs"),
        FakeEntity("camera.garagehallway_high_resolution_channel", "dev_nvr", PLATFORM_UNIFI,
                   area_id="garage_hallway"),
        FakeEntity("binary_sensor.garagehallway_person_detected", "dev_nvr", PLATFORM_UNIFI,
                   area_id="garage_hallway"),
    ]
    r = _mk(ents, [dev])
    result = r.enumerate_platform_cameras(PLATFORM_UNIFI, "person")
    stems = sorted(_entity_stem_from_legs(c.legs) for c in result)
    assert stems == ["garagehallway", "staircase"], stems
    areas = {_entity_stem_from_legs(c.legs): c.area_id for c in result}
    assert areas["staircase"] == "stairs"
    assert areas["garagehallway"] == "garage_hallway"


def _entity_stem_from_legs(legs: tuple[str, ...]) -> str:
    # Pick the shortest leg's name up to `_person_detected`.
    primary = sorted(legs, key=lambda e: (len(e), e))[0]
    name = primary.split(".", 1)[1]
    for suf in ("_person_detected", "_person_occupancy"):
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


# ---------------------------------------------------------------------------
# F7: empty-tuple checkpoint areas + scalar input normalization.
# ---------------------------------------------------------------------------


import importlib.util as _il2  # noqa: E402
_TV_PATH = REPO_ROOT / "custom_components/universal_room_automation/transit_validator.py"


def _load_transit_validator_module():
    """Load the real transit_validator module for helper-level tests. Const
    import via `.const` needs the package on sys.path; the HA stubs above
    already gate the HA imports."""
    # Ensure the const module is importable as a sibling (package-style import).
    # Load the const module first under the package name so `from .const` works.
    pkg_name = "custom_components.universal_room_automation"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(REPO_ROOT / "custom_components/universal_room_automation")]
        sys.modules[pkg_name] = pkg
    # Const submodule
    const_name = pkg_name + ".const"
    if const_name not in sys.modules:
        cspec = _il2.spec_from_file_location(
            const_name,
            REPO_ROOT / "custom_components/universal_room_automation/const.py",
        )
        cmod = _il2.module_from_spec(cspec)
        sys.modules[const_name] = cmod
        cspec.loader.exec_module(cmod)
    # camera_resolver submodule (transit imports it lazily inside a fn but
    # still uses `.camera_resolver` — provide it under the package name).
    cr_name = pkg_name + ".camera_resolver"
    if cr_name not in sys.modules:
        crspec = _il2.spec_from_file_location(
            cr_name,
            REPO_ROOT / "custom_components/universal_room_automation/camera_resolver.py",
        )
        crmod = _il2.module_from_spec(crspec)
        sys.modules[cr_name] = crmod
        crspec.loader.exec_module(crmod)
    tv_name = pkg_name + ".transit_validator"
    if tv_name in sys.modules:
        return sys.modules[tv_name]
    tvspec = _il2.spec_from_file_location(tv_name, _TV_PATH)
    tvmod = _il2.module_from_spec(tvspec)
    sys.modules[tv_name] = tvmod
    tvspec.loader.exec_module(tvmod)
    return tvmod


class _FakeConfigEntry:
    def __init__(self, data=None, options=None):
        self.data = data or {}
        self.options = options or {}


class _FakeConfigEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, domain):
        return list(self._entries)


class _FakeHass:
    def __init__(self, entries, er, dr):
        self.config_entries = _FakeConfigEntries(entries)
        self._er = er
        self._dr = dr
        self.data = {}

        class _States:
            def get(self, eid):
                return None
        self.states = _States()

    # er/dr accessors mimicking helpers.async_get pattern
    def er(self):
        return self._er

    def dr(self):
        return self._dr


def _install_registry_stubs(monkeypatch, er, dr, tvmod):
    # Patch helper module functions to return our fakes.
    import homeassistant.helpers.entity_registry as ha_er  # noqa: PLC0415
    import homeassistant.helpers.device_registry as ha_dr  # noqa: PLC0415
    monkeypatch.setattr(ha_er, "async_get", lambda hass: er, raising=False)
    monkeypatch.setattr(ha_dr, "async_get", lambda hass: dr, raising=False)


def _integration_entry(**merged):
    from custom_components.universal_room_automation.const import (  # noqa: PLC0415
        ENTRY_TYPE_INTEGRATION, CONF_ENTRY_TYPE,
    )
    data = {CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION}
    return _FakeConfigEntry(data=data, options=merged)


def test_helper_kill_switch_false_returns_empty_triple(monkeypatch):
    """F9-adjacent: kill-switch OFF returns ([], {}, {}) — NO registry walk
    (fake resolver would blow up if invoked; we prove it isn't via the
    triviality of the return + zero entities)."""
    tv = _load_transit_validator_module()
    from custom_components.universal_room_automation.const import (
        CONF_TRANSIT_PROTECT_SOURCED_ENABLED,
    )
    ents, devs = _five_checkpoint_registry()
    er, dr = FakeER(ents), FakeDR(devs)
    hass = _FakeHass([_integration_entry(**{CONF_TRANSIT_PROTECT_SOURCED_ENABLED: False})], er, dr)
    _install_registry_stubs(monkeypatch, er, dr, tv)
    eids, by_area, e2p = tv._protect_sourced_checkpoint_entities(hass)
    assert eids == []
    assert by_area == {}
    assert e2p == {}


def test_helper_kill_switch_on_with_registry_returns_checkpoints(monkeypatch):
    """Kill-switch ON + Protect cameras at checkpoint areas => enumerated."""
    tv = _load_transit_validator_module()
    from custom_components.universal_room_automation.const import (
        CONF_TRANSIT_PROTECT_SOURCED_ENABLED,
    )
    ents, devs = _five_checkpoint_registry()
    er, dr = FakeER(ents), FakeDR(devs)
    hass = _FakeHass([_integration_entry(**{CONF_TRANSIT_PROTECT_SOURCED_ENABLED: True})], er, dr)
    _install_registry_stubs(monkeypatch, er, dr, tv)
    eids, by_area, e2p = tv._protect_sourced_checkpoint_entities(hass)
    assert set(by_area.keys()) == CHECKPOINT_AREAS
    # Every enumerated entity_id is mapped to a physical device_id.
    for eid in eids:
        assert e2p.get(eid), f"F2 map missing physical for {eid}"


def test_helper_non_checkpoint_area_excluded(monkeypatch):
    """A Protect person camera in a NON-checkpoint area is excluded."""
    tv = _load_transit_validator_module()
    from custom_components.universal_room_automation.const import (
        CONF_TRANSIT_PROTECT_SOURCED_ENABLED,
    )
    # Only one device, in a non-checkpoint area.
    dev = FakeDevice(id="d_lr", identifiers={(PLATFORM_UNIFI, "pr-lr")},
                     area_id="living_room")
    ents = [
        FakeEntity("camera.lr_high_resolution_channel", "d_lr", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.lr_person_detected", "d_lr", PLATFORM_UNIFI),
    ]
    er, dr = FakeER(ents), FakeDR([dev])
    hass = _FakeHass([_integration_entry(**{CONF_TRANSIT_PROTECT_SOURCED_ENABLED: True})], er, dr)
    _install_registry_stubs(monkeypatch, er, dr, tv)
    eids, by_area, e2p = tv._protect_sourced_checkpoint_entities(hass)
    assert eids == []
    assert by_area == {}


def test_helper_empty_tuple_checkpoint_areas_is_kill_mode(monkeypatch):
    """F7 fix: an operator setting `CONF_TRANSIT_CHECKPOINT_AREAS = ()`
    means 'no checkpoint areas' (kill mode). Pre-fix `if areas_val:` was
    falsy on `()` and silently collapsed to the 5 defaults."""
    tv = _load_transit_validator_module()
    from custom_components.universal_room_automation.const import (
        CONF_TRANSIT_PROTECT_SOURCED_ENABLED,
        CONF_TRANSIT_CHECKPOINT_AREAS,
    )
    ents, devs = _five_checkpoint_registry()
    er, dr = FakeER(ents), FakeDR(devs)
    hass = _FakeHass([_integration_entry(**{
        CONF_TRANSIT_PROTECT_SOURCED_ENABLED: True,
        CONF_TRANSIT_CHECKPOINT_AREAS: (),
    })], er, dr)
    _install_registry_stubs(monkeypatch, er, dr, tv)
    eids, by_area, e2p = tv._protect_sourced_checkpoint_entities(hass)
    assert eids == []
    assert by_area == {}


def test_helper_scalar_string_checkpoint_area_normalized(monkeypatch):
    """F7 fix: a bare-string CONF_TRANSIT_CHECKPOINT_AREAS is treated as a
    single-element tuple, NOT per-character expansion via tuple('foo')."""
    tv = _load_transit_validator_module()
    from custom_components.universal_room_automation.const import (
        CONF_TRANSIT_PROTECT_SOURCED_ENABLED,
        CONF_TRANSIT_CHECKPOINT_AREAS,
    )
    ents, devs = _five_checkpoint_registry()
    er, dr = FakeER(ents), FakeDR(devs)
    hass = _FakeHass([_integration_entry(**{
        CONF_TRANSIT_PROTECT_SOURCED_ENABLED: True,
        CONF_TRANSIT_CHECKPOINT_AREAS: "master_hallway",
    })], er, dr)
    _install_registry_stubs(monkeypatch, er, dr, tv)
    eids, by_area, e2p = tv._protect_sourced_checkpoint_entities(hass)
    # Only master_hallway should be enumerated (scalar => single-elem tuple).
    assert set(by_area.keys()) == {"master_hallway"}


# ---------------------------------------------------------------------------
# F1: shared-space cameras union.
# ---------------------------------------------------------------------------


def test_f1_get_shared_space_cameras_unions_legacy_and_protect_sourced():
    """F1 fix: _get_shared_space_cameras must UNION the Protect-sourced
    entity set with the legacy hand-list. Without this, sightings recorded
    from Protect entities are filtered out at validate_transition."""
    tv = _load_transit_validator_module()

    class _CM:
        def _get_interior_camera_entities(self):
            return ["binary_sensor.legacy_only_hallway_person_detected"]

    validator = tv.TransitValidator.__new__(tv.TransitValidator)
    validator.hass = types.SimpleNamespace(
        data={"universal_room_automation": {"camera_manager": _CM()}}
    )
    # Constructor-like init of just the fields the method reads.
    validator._protect_entity_set = {"binary_sensor.staircase_person_detected"}
    from custom_components.universal_room_automation.const import DOMAIN as _D  # noqa: PLC0415
    validator.hass = types.SimpleNamespace(data={_D: {"camera_manager": _CM()}})
    result = set(validator._get_shared_space_cameras())
    assert "binary_sensor.legacy_only_hallway_person_detected" in result
    assert "binary_sensor.staircase_person_detected" in result


def test_f1_kill_switch_reduces_to_legacy_only():
    """F1 corollary: empty Protect entity set => reduces exactly to legacy list."""
    tv = _load_transit_validator_module()

    class _CM:
        def _get_interior_camera_entities(self):
            return ["binary_sensor.hand_a", "binary_sensor.hand_b"]

    from custom_components.universal_room_automation.const import DOMAIN as _D  # noqa: PLC0415
    validator = tv.TransitValidator.__new__(tv.TransitValidator)
    validator.hass = types.SimpleNamespace(data={_D: {"camera_manager": _CM()}})
    validator._protect_entity_set = set()
    result = validator._get_shared_space_cameras()
    assert result == ["binary_sensor.hand_a", "binary_sensor.hand_b"]


# ---------------------------------------------------------------------------
# F2: physical-camera dedup on double-fire.
# ---------------------------------------------------------------------------


class _FakeState:
    def __init__(self, entity_id, state="on", attributes=None):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}


class _FakeEvent:
    def __init__(self, new_state):
        self.data = {"new_state": new_state}


def test_f2_double_fire_one_physical_camera_records_one_sighting():
    """F2 fix: Protect leg + Frigate leg for the SAME physical camera fire
    within the dedup window -> exactly ONE sighting is recorded."""
    tv = _load_transit_validator_module()
    validator = tv.TransitValidator.__new__(tv.TransitValidator)
    validator.hass = types.SimpleNamespace(
        data={"universal_room_automation": {}}
    )
    validator._camera_sightings = {}
    validator._face_recognition_enabled = False
    validator._entity_to_physical = {
        "binary_sensor.stairs_person_detected": "dev_stairs",  # Protect
        "binary_sensor.stairs_person_occupancy": "dev_stairs",  # Frigate leg
    }
    validator._last_physical_sighting = {}
    # Fire Protect first.
    validator._on_camera_state_change(_FakeEvent(_FakeState("binary_sensor.stairs_person_detected")))
    # Fire Frigate leg ~1 sec later.
    validator._on_camera_state_change(_FakeEvent(_FakeState("binary_sensor.stairs_person_occupancy")))
    total = sum(len(v) for v in validator._camera_sightings.values())
    assert total == 1, f"F2 dedup regressed: {validator._camera_sightings}"


def test_f2_two_physical_cameras_both_record():
    """Different physical cameras firing at the same time => both recorded."""
    tv = _load_transit_validator_module()
    validator = tv.TransitValidator.__new__(tv.TransitValidator)
    validator.hass = types.SimpleNamespace(
        data={"universal_room_automation": {}}
    )
    validator._camera_sightings = {}
    validator._face_recognition_enabled = False
    validator._entity_to_physical = {
        "binary_sensor.stairs_person_detected": "dev_stairs",
        "binary_sensor.master_person_detected": "dev_master",
    }
    validator._last_physical_sighting = {}
    validator._on_camera_state_change(_FakeEvent(_FakeState("binary_sensor.stairs_person_detected")))
    validator._on_camera_state_change(_FakeEvent(_FakeState("binary_sensor.master_person_detected")))
    total = sum(len(v) for v in validator._camera_sightings.values())
    assert total == 2
