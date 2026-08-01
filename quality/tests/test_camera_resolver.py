"""Tests for the CameraResolver shared primitive (2026-08-01 fusion cycle).

Bug Class #62 discipline: these tests drive the REAL production module
(``custom_components.universal_room_automation.camera_resolver``), NOT a
local stub. Synthetic registry fixtures duck-type the entity/device
registry shape the resolver reads (attributes: ``entity_id``, ``device_id``,
``domain``, ``platform``, ``name``, ``disabled_by``; and for devices
``id``, ``identifiers``, ``connections``). Fixture shapes are copied from
the D0 AUDIT (``docs/planning/AUDIT_camera_resolver_pairing_dryrun.md``).

Coverage:
  - Ladder rungs (same-device, MAC, identifiers, network-inventory,
    name-stem, operator-declared) each with a named test.
  - Per-limb mutation drills — each rung has its OWN named fixture; a
    real code mutation in the resolver that neuters a specific rung will
    turn its named test red without affecting the others.
  - Correlation classes (same-device, cross-device MAC, name-stem-only,
    operator-declared-only including Frigate-ingests-Reolink).
  - Negative controls: disabled entities excluded; _package_ excluded;
    F1 multi-camera Protect NVR de-fusion; F2 same-object Frigate
    collapse; cross-camera attribution impossible (Review D invariant).
  - Face-never-auto-enabled drill.
  - Face capability tri-state (absent / usable / ambiguous).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

# Add repo root so custom_components imports resolve.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import the REAL module under test WITHOUT triggering the package __init__
# (which imports homeassistant). Load the source file directly via importlib.
import importlib.util as _il

_RESOLVER_PATH = REPO_ROOT / "custom_components/universal_room_automation/camera_resolver.py"
_spec = _il.spec_from_file_location("camera_resolver_under_test", _RESOLVER_PATH)
_mod = _il.module_from_spec(_spec)
sys.modules["camera_resolver_under_test"] = _mod
_spec.loader.exec_module(_mod)

BASIS_IDENTIFIERS = _mod.BASIS_IDENTIFIERS
BASIS_MAC = _mod.BASIS_MAC
BASIS_NAME_STEM = _mod.BASIS_NAME_STEM
BASIS_NETWORK_INVENTORY = _mod.BASIS_NETWORK_INVENTORY
BASIS_OPERATOR_DECLARED = _mod.BASIS_OPERATOR_DECLARED
BASIS_SAME_DEVICE = _mod.BASIS_SAME_DEVICE
CAMERA_AUTOENABLE_DRY_RUN = _mod.CAMERA_AUTOENABLE_DRY_RUN
CameraResolver = _mod.CameraResolver
FACE_ABSENT = _mod.FACE_ABSENT
FACE_AMBIGUOUS = _mod.FACE_AMBIGUOUS
FACE_USABLE = _mod.FACE_USABLE
FRIGATE_CROSS_HOST_CORROBORATION_ENABLED = _mod.FRIGATE_CROSS_HOST_CORROBORATION_ENABLED
PLATFORM_AMCREST = _mod.PLATFORM_AMCREST
PLATFORM_FRIGATE = _mod.PLATFORM_FRIGATE
PLATFORM_REOLINK = _mod.PLATFORM_REOLINK
PLATFORM_UNIFI = _mod.PLATFORM_UNIFI
collect_person_switches_to_enable = _mod.collect_person_switches_to_enable


# ============================================================================
# Synthetic registry fixtures — duck-typed to the real HA registry shape.
# ============================================================================


@dataclass
class FakeEntity:
    entity_id: str
    device_id: str | None = None
    platform: str = ""
    name: str = ""
    disabled_by: Any = None

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]


@dataclass
class FakeDevice:
    id: str
    identifiers: set = field(default_factory=set)
    connections: set = field(default_factory=set)


class FakeEntityRegistry:
    def __init__(self, entities: list[FakeEntity]):
        self.entities = {e.entity_id: e for e in entities}

    def async_get(self, entity_id: str):
        return self.entities.get(entity_id)


class FakeDeviceRegistry:
    def __init__(self, devices: list[FakeDevice]):
        self.devices = {d.id: d for d in devices}

    def async_get(self, device_id: str):
        return self.devices.get(device_id)


def _mk(entities: list[FakeEntity], devices: list[FakeDevice]) -> CameraResolver:
    return CameraResolver(
        FakeEntityRegistry(entities), FakeDeviceRegistry(devices)
    )


# ============================================================================
# Rung 1 — same-device (Frigate + Protect co-resident on one device)
# ============================================================================


def test_rung_same_device_finds_frigate_and_protect_on_one_device():
    """AUDIT §3 row 1: playroom_high_resolution_channel resolves same-device."""
    dev = FakeDevice(
        id="dev_play",
        identifiers={(PLATFORM_UNIFI, "mac-play")},
        connections={("mac", "aa:bb:01")},
    )
    ents = [
        FakeEntity("camera.playroom_high_resolution_channel", "dev_play", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.playroom_person_detected", "dev_play", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.playroom_person_occupancy", "dev_play", PLATFORM_FRIGATE),
        FakeEntity("sensor.playroom_person_count", "dev_play", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.playroom_last_recognized_face", "dev_play", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev])
    fusion = r.resolve_operator_declaration(["camera.playroom_high_resolution_channel"])
    assert len(fusion.sources) >= 1
    src = fusion.sources[0]
    assert src.device_id == "dev_play"
    assert src.correlation_basis == BASIS_SAME_DEVICE
    # Person + count present.
    assert src.person_binary_sensor in (
        "binary_sensor.playroom_person_detected",
        "binary_sensor.playroom_person_occupancy",
    )
    assert src.person_count_sensor == "sensor.playroom_person_count"
    # Face capability = usable (enabled face entity present).
    assert src.face_capability == FACE_USABLE


# ============================================================================
# Rung 2 — MAC join across integrations
# ============================================================================


def test_rung_mac_correlates_reolink_and_protect_by_shared_mac():
    mac = "aa:bb:cc:11:22:33"
    dev_reo = FakeDevice(id="dev_reo", identifiers={(PLATFORM_REOLINK, "reo-uid")},
                         connections={("mac", mac)})
    dev_unifi = FakeDevice(id="dev_unifi", identifiers={(PLATFORM_UNIFI, "unifi-mac")},
                           connections={("mac", mac)})
    ents = [
        FakeEntity("camera.driveway", "dev_reo", PLATFORM_REOLINK),
        FakeEntity("binary_sensor.driveway_person", "dev_reo", PLATFORM_REOLINK),
        # Protect side — deliberate different name-stem so ONLY MAC can link.
        FakeEntity("binary_sensor.unifi_driveway_person_detected", "dev_unifi", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev_reo, dev_unifi])
    fusion = r.resolve_operator_declaration(["camera.driveway"])
    bases = {s.correlation_basis for s in fusion.sources}
    dids = {s.device_id for s in fusion.sources}
    assert "dev_unifi" in dids, "MAC rung should pull in the Protect device"
    assert BASIS_MAC in bases


# ============================================================================
# Rung 3 — identifiers overlap
# ============================================================================


def test_rung_identifiers_overlap_pulls_in_sibling_device():
    dev_a = FakeDevice(id="dev_a", identifiers={("integA", "shared-uid")})
    dev_b = FakeDevice(id="dev_b", identifiers={("integB", "shared-uid")})
    ents = [
        FakeEntity("camera.a", "dev_a", "integA"),
        FakeEntity("binary_sensor.b_person_detected", "dev_b", "integB"),
    ]
    r = _mk(ents, [dev_a, dev_b])
    fusion = r.resolve_operator_declaration(["camera.a"])
    dids = {s.device_id for s in fusion.sources}
    bases = {s.correlation_basis for s in fusion.sources}
    assert "dev_b" in dids
    assert BASIS_IDENTIFIERS in bases


# ============================================================================
# Rung 4 — network-inventory (IP/hostname -> MAC via stub provider)
# ============================================================================


def test_rung_network_inventory_join_via_ip_stub():
    mac = "de:ad:be:ef:00:01"
    dev_reo = FakeDevice(id="dev_reo", identifiers={(PLATFORM_REOLINK, "reo")},
                         connections={("ip", "192.168.1.50")})
    dev_unifi = FakeDevice(id="dev_unifi", identifiers={(PLATFORM_UNIFI, "u1")},
                           connections={("mac", mac)})
    ents = [
        FakeEntity("camera.reo", "dev_reo", PLATFORM_REOLINK),
        FakeEntity("binary_sensor.reo_person", "dev_reo", PLATFORM_REOLINK),
        FakeEntity("binary_sensor.u1_person_detected", "dev_unifi", PLATFORM_UNIFI),
    ]

    def inventory(ip_or_host: str) -> str | None:
        return mac if ip_or_host == "192.168.1.50" else None

    r = CameraResolver(FakeEntityRegistry(ents), FakeDeviceRegistry([dev_reo, dev_unifi]),
                       network_inventory=inventory)
    fusion = r.resolve_operator_declaration(["camera.reo"])
    dids = {s.device_id for s in fusion.sources}
    bases = {s.correlation_basis for s in fusion.sources}
    assert "dev_unifi" in dids
    assert BASIS_NETWORK_INVENTORY in bases


def test_rung_network_inventory_absent_provider_no_op():
    """Without a network_inventory provider, the rung silently degrades."""
    dev = FakeDevice(id="dev_reo", identifiers={(PLATFORM_REOLINK, "r")},
                     connections={("ip", "10.0.0.1")})
    ents = [FakeEntity("camera.r", "dev_reo", PLATFORM_REOLINK),
            FakeEntity("binary_sensor.r_person", "dev_reo", PLATFORM_REOLINK)]
    r = _mk(ents, [dev])
    fusion = r.resolve_operator_declaration(["camera.r"])
    # Only the same-device source; no crash from missing provider.
    assert all(s.correlation_basis != BASIS_NETWORK_INVENTORY for s in fusion.sources)


# ============================================================================
# Rung 5 — name-stem via Frigate identifier index
# ============================================================================


def test_rung_name_stem_frigate_device_pulled_in():
    """A Frigate device whose object-name matches the input camera stem is
    pulled in via the name-stem rung (not MAC, since Frigate has no MAC)."""
    dev_unifi = FakeDevice(id="dev_u", identifiers={(PLATFORM_UNIFI, "u")},
                           connections={("mac", "aa:00")})
    dev_frig = FakeDevice(id="dev_f",
                          identifiers={(PLATFORM_FRIGATE, "host1:staircase")})
    ents = [
        FakeEntity("camera.staircase", "dev_u", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.staircase_person_detected", "dev_u", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.staircase_person_occupancy", "dev_f", PLATFORM_FRIGATE),
    ]
    r = _mk(ents, [dev_unifi, dev_frig])
    fusion = r.resolve_operator_declaration(["camera.staircase"])
    dids = {s.device_id for s in fusion.sources}
    bases = {s.correlation_basis for s in fusion.sources}
    assert "dev_f" in dids
    assert BASIS_NAME_STEM in bases


# ============================================================================
# Rung 6 — operator-declared (Frigate ingests Reolink, no MAC/stem parity)
# ============================================================================


def test_rung_operator_declared_frigate_ingests_reolink_no_parity():
    """Two entities with NO MAC/identifier/stem parity, listed together by
    the operator, MUST fuse as one physical camera per amendment #1."""
    dev_reo = FakeDevice(id="dev_reo", identifiers={(PLATFORM_REOLINK, "reo-1")})
    dev_frig = FakeDevice(id="dev_frig",
                          identifiers={(PLATFORM_FRIGATE, "host1:some_other_name")})
    ents = [
        FakeEntity("camera.driveway", "dev_reo", PLATFORM_REOLINK),
        FakeEntity("binary_sensor.driveway_person", "dev_reo", PLATFORM_REOLINK),
        FakeEntity("camera.some_other_name", "dev_frig", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.some_other_name_person_occupancy", "dev_frig", PLATFORM_FRIGATE),
    ]
    r = _mk(ents, [dev_reo, dev_frig])
    fusion = r.resolve_operator_declaration(
        ["camera.driveway", "camera.some_other_name"]
    )
    dids = {s.device_id for s in fusion.sources}
    assert dids == {"dev_reo", "dev_frig"}
    bases = {s.correlation_basis for s in fusion.sources}
    # dev_reo is same_device (listed first); dev_frig is operator_declared
    # (no MAC/identifier/stem linked it to dev_reo).
    assert BASIS_SAME_DEVICE in bases
    assert BASIS_OPERATOR_DECLARED in bases


# ============================================================================
# F1 — CRITICAL: Protect NVR device conflates two physical cameras
# ============================================================================


def test_f1_protect_nvr_device_defuses_by_entity_name_stem():
    """AUDIT §F1: Staircase device also hosts garagehallway_* entities.
    Resolver MUST NOT pull the garagehallway person sensor into the
    staircase fusion (silent false positive)."""
    dev = FakeDevice(id="dev_nvr", identifiers={(PLATFORM_UNIFI, "nvr-mac")},
                     connections={("mac", "28:70:4e:17:ee:02")})
    ents = [
        FakeEntity("camera.staircase_high_resolution_channel", "dev_nvr", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.staircase_person_detected", "dev_nvr", PLATFORM_UNIFI),
        # WRONG-CAMERA sibling on the same NVR device:
        FakeEntity("binary_sensor.camera_protect_garagehallway_person_detected",
                   "dev_nvr", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev])
    fusion = r.resolve_operator_declaration(["camera.staircase_high_resolution_channel"])
    person_bs_ids = fusion.person_binary_sensor_entity_ids()
    assert "binary_sensor.staircase_person_detected" in person_bs_ids
    assert "binary_sensor.camera_protect_garagehallway_person_detected" not in person_bs_ids, (
        "F1 fix: garagehallway_* sibling on same NVR device must be excluded "
        "from staircase fusion (Review D invariant)"
    )


# ============================================================================
# F2 — Frigate cross-host duplicate collapse (gate CLOSED by default)
# ============================================================================


def test_f2_frigate_dual_host_same_object_collapsed_when_gate_closed():
    """Two Frigate devices with the SAME object name ("staircase") from
    different hosts collapse to one source until the F1<->F2 stability gate
    opens (FRIGATE_CROSS_HOST_CORROBORATION_ENABLED)."""
    assert FRIGATE_CROSS_HOST_CORROBORATION_ENABLED is False, (
        "Gate must remain rung-1 CLOSED until 72h stability measured"
    )
    dev_f1 = FakeDevice(id="dev_f1", identifiers={(PLATFORM_FRIGATE, "host1:staircase")})
    dev_f2 = FakeDevice(id="dev_f2", identifiers={(PLATFORM_FRIGATE, "host2:staircase")})
    dev_u = FakeDevice(id="dev_u", identifiers={(PLATFORM_UNIFI, "u")})
    ents = [
        FakeEntity("camera.staircase", "dev_u", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.staircase_person_detected", "dev_u", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.staircase_person_occupancy", "dev_f1", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.staircase_person_occupancy", "dev_f2", PLATFORM_FRIGATE),
    ]
    # (Two entities share entity_id here — in real HA that's impossible; use
    # distinct ids to keep the fixture legal.)
    ents[3] = FakeEntity("binary_sensor.staircase_person_occupancy_2", "dev_f2", PLATFORM_FRIGATE)
    r = _mk(ents, [dev_f1, dev_f2, dev_u])
    fusion = r.resolve_operator_declaration(["camera.staircase"])
    frigate_dids = [s.device_id for s in fusion.sources if s.integration == PLATFORM_FRIGATE]
    assert len(frigate_dids) == 1, (
        f"F2: expected 1 Frigate device after collapse; got {frigate_dids}"
    )


# ============================================================================
# F3 — MEDIUM: package-object detector excluded
# ============================================================================


def test_f3_package_person_detector_excluded():
    """AUDIT §F3: binary_sensor.*_package_person_occupancy must NOT count as
    a person source for the camera."""
    dev = FakeDevice(id="d_entry", identifiers={(PLATFORM_FRIGATE, "host1:madrone_g6_entry")})
    ents = [
        FakeEntity("camera.madrone_g6_entry", "d_entry", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.madrone_g6_entry_person_occupancy", "d_entry", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.madrone_g6_entry_package_person_occupancy",
                   "d_entry", PLATFORM_FRIGATE),
        FakeEntity("sensor.madrone_g6_entry_person_count", "d_entry", PLATFORM_FRIGATE),
        FakeEntity("sensor.madrone_g6_entry_package_person_count", "d_entry", PLATFORM_FRIGATE),
    ]
    r = _mk(ents, [dev])
    fusion = r.resolve_operator_declaration(["camera.madrone_g6_entry"])
    person_bs = fusion.person_binary_sensor_entity_ids()
    assert person_bs == ["binary_sensor.madrone_g6_entry_person_occupancy"]
    assert all("_package_" not in e for e in person_bs)


# ============================================================================
# F4 — dedup by (integration, device_id) after fusion
# ============================================================================


def test_f4_post_fusion_dedup_by_device_id():
    """Two camera.* entities on the same device (high-res + medium-res
    channels) must resolve to a SINGLE FusionSource."""
    dev = FakeDevice(id="d", identifiers={(PLATFORM_UNIFI, "d")})
    ents = [
        FakeEntity("camera.foo", "d", PLATFORM_UNIFI),
        FakeEntity("camera.foo_high_resolution_channel", "d", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.foo_person_detected", "d", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev])
    fusion = r.resolve_operator_declaration(
        ["camera.foo", "camera.foo_high_resolution_channel"]
    )
    dids = [s.device_id for s in fusion.sources]
    assert dids == ["d"]


# ============================================================================
# Negative controls
# ============================================================================


def test_negative_disabled_person_entity_excluded():
    """A disabled person binary_sensor must NOT be a fusion source."""
    dev = FakeDevice(id="d", identifiers={(PLATFORM_UNIFI, "u")})
    ents = [
        FakeEntity("camera.x", "d", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.x_person_detected", "d", PLATFORM_UNIFI,
                   disabled_by="user"),
    ]
    r = _mk(ents, [dev])
    fusion = r.resolve_operator_declaration(["camera.x"])
    person = fusion.person_binary_sensor_entity_ids()
    assert person == []


def test_negative_cross_camera_attribution_impossible_review_d_invariant():
    """Review D invariant: an entity from a genuinely DIFFERENT physical
    camera (no shared MAC / identifier / stem / operator declaration) MUST
    NEVER be attributed to a resolved fusion."""
    dev_a = FakeDevice(id="dev_a", identifiers={(PLATFORM_UNIFI, "a")},
                       connections={("mac", "aa:00")})
    dev_b = FakeDevice(id="dev_b", identifiers={(PLATFORM_UNIFI, "b")},
                       connections={("mac", "bb:00")})
    ents = [
        FakeEntity("camera.a", "dev_a", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.a_person_detected", "dev_a", PLATFORM_UNIFI),
        # Unrelated camera b — different MAC, different stem, not listed.
        FakeEntity("camera.b", "dev_b", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.b_person_detected", "dev_b", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev_a, dev_b])
    fusion = r.resolve_operator_declaration(["camera.a"])
    dids = {s.device_id for s in fusion.sources}
    assert dids == {"dev_a"}, f"Cross-camera attribution leak: {dids}"


def test_negative_ambiguous_multi_candidate_requires_operator_confirm_never_guess():
    """Two candidate name-stem matches on truly unrelated devices — the
    resolver MUST NOT silently guess. Both are legitimately name-stem
    correlated once the input stem matches, but the invariant here is:
    they are ONLY pulled in via the name-stem rung (never presented as a
    stronger correlation than the evidence supports)."""
    dev_a = FakeDevice(id="dev_a", identifiers={(PLATFORM_UNIFI, "a")})
    dev_b = FakeDevice(id="dev_b", identifiers={(PLATFORM_FRIGATE, "h1:foo")})
    dev_c = FakeDevice(id="dev_c", identifiers={(PLATFORM_FRIGATE, "h1:foo_typo")})
    ents = [
        FakeEntity("camera.foo", "dev_a", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.foo_person_detected", "dev_a", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.foo_person_occupancy", "dev_b", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.foo_typo_person_occupancy", "dev_c", PLATFORM_FRIGATE),
    ]
    r = _mk(ents, [dev_a, dev_b, dev_c])
    fusion = r.resolve_operator_declaration(["camera.foo"])
    # dev_c has a different object name ("foo_typo") — must NOT be pulled in.
    dids = {s.device_id for s in fusion.sources}
    assert "dev_c" not in dids
    # dev_b (exact object-name match) IS pulled in via name-stem.
    assert "dev_b" in dids
    b_src = [s for s in fusion.sources if s.device_id == "dev_b"][0]
    assert b_src.correlation_basis == BASIS_NAME_STEM


# ============================================================================
# Face capability tri-state
# ============================================================================


def test_face_capability_absent_when_no_face_entity():
    dev = FakeDevice(id="d", identifiers={(PLATFORM_UNIFI, "u")})
    ents = [FakeEntity("camera.x", "d", PLATFORM_UNIFI),
            FakeEntity("binary_sensor.x_person_detected", "d", PLATFORM_UNIFI)]
    r = _mk(ents, [dev])
    fusion = r.resolve_operator_declaration(["camera.x"])
    assert fusion.sources[0].face_capability == FACE_ABSENT


def test_face_capability_usable_when_face_entity_enabled():
    dev = FakeDevice(id="d", identifiers={(PLATFORM_UNIFI, "u")})
    ents = [FakeEntity("camera.x", "d", PLATFORM_UNIFI),
            FakeEntity("binary_sensor.x_person_detected", "d", PLATFORM_UNIFI),
            FakeEntity("binary_sensor.x_face_detected", "d", PLATFORM_UNIFI)]
    r = _mk(ents, [dev])
    fusion = r.resolve_operator_declaration(["camera.x"])
    assert fusion.sources[0].face_capability == FACE_USABLE


def test_face_capability_ambiguous_when_face_entity_disabled():
    dev = FakeDevice(id="d", identifiers={(PLATFORM_UNIFI, "u")})
    ents = [FakeEntity("camera.x", "d", PLATFORM_UNIFI),
            FakeEntity("binary_sensor.x_person_detected", "d", PLATFORM_UNIFI),
            FakeEntity("binary_sensor.x_face_detected", "d", PLATFORM_UNIFI,
                       disabled_by="user")]
    r = _mk(ents, [dev])
    fusion = r.resolve_operator_declaration(["camera.x"])
    assert fusion.sources[0].face_capability == FACE_AMBIGUOUS


# ============================================================================
# D4 auto-enable — face NEVER included in the switch list (invariant)
# ============================================================================


def test_d4_face_switch_never_in_auto_enable_list():
    """The auto-enable helper collects PERSON switches only; face switches
    live only on the inventory attribute."""
    dev = FakeDevice(id="d", identifiers={(PLATFORM_UNIFI, "u")})
    ents = [
        FakeEntity("camera.x", "d", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.x_person_detected", "d", PLATFORM_UNIFI),
        FakeEntity("switch.x_detections_person", "d", PLATFORM_UNIFI),
        FakeEntity("switch.x_detections_face", "d", PLATFORM_UNIFI),
        FakeEntity("switch.x_smart_detect_face", "d", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev])
    fusion = r.resolve_operator_declaration(["camera.x"])
    person_switches = fusion.person_detect_switch_entity_ids()
    face_switches = fusion.face_detect_switch_entity_ids()
    assert "switch.x_detections_person" in person_switches
    assert all("face" not in e for e in person_switches), (
        f"face switch leaked into person auto-enable list: {person_switches}"
    )
    # Face inventory sees at least one of the face switches.
    assert any("face" in e for e in face_switches)
    # collect_person_switches_to_enable returns the OFF-state person switch.
    to_enable = collect_person_switches_to_enable(
        [fusion], state_getter=lambda eid: type("S", (), {"state": "off"})(),
    )
    assert "switch.x_detections_person" in to_enable
    assert all("face" not in e for e in to_enable)


def test_d4_dry_run_flag_default_true():
    """First release is dry-run only per plan; flipping is a reviewed change."""
    assert CAMERA_AUTOENABLE_DRY_RUN is True


# ============================================================================
# Config-key migration guard: CONF_ROOM_CAMERAS distinct from CONF_CAMERA_PERSON_ENTITIES
# ============================================================================


def test_conf_room_cameras_key_is_distinct_from_migration_target():
    """The v3.4.5 migration strips CONF_CAMERA_PERSON_ENTITIES from room
    options. CONF_ROOM_CAMERAS must be a different string to sidestep it."""
    const_src = (REPO_ROOT / "custom_components/universal_room_automation/const.py").read_text()
    # Both constants defined; distinct string values.
    assert 'CONF_ROOM_CAMERAS: Final = "room_cameras"' in const_src
    assert 'CONF_CAMERA_PERSON_ENTITIES: Final = "camera_person_entities"' in const_src
    # Also grep-assert: the migration code path targets the OLD key.
    init_src = Path(REPO_ROOT / "custom_components/universal_room_automation/__init__.py").read_text()
    assert "if k != CONF_CAMERA_PERSON_ENTITIES" in init_src, (
        "Migration must key on CONF_CAMERA_PERSON_ENTITIES, not the new room-cameras key"
    )
    assert "CONF_ROOM_CAMERAS" not in init_src.split(
        "async def _migrate_room_cameras_to_integration"
    )[1].split("async def ")[0], (
        "Migration function body must NOT reference CONF_ROOM_CAMERAS "
        "(would defeat the sidestep)"
    )


# ============================================================================
# Empty-input safety
# ============================================================================


def test_empty_input_returns_empty_fusion():
    r = _mk([], [])
    fusion = r.resolve_operator_declaration([])
    assert fusion.sources == []
    assert fusion.physical_camera_id == ""


def test_missing_entity_warns_and_skips():
    r = _mk([], [])
    fusion = r.resolve_operator_declaration(["camera.does_not_exist"])
    assert fusion.sources == []
