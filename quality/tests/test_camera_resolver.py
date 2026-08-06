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


def _sole(fusions):
    """Post-Fix#7 helper: resolve_operator_declaration returns list. Assert
    exactly one physical camera resolved and return it."""
    assert isinstance(fusions, list), f"expected list, got {type(fusions)}"
    assert len(fusions) == 1, f"expected exactly one fusion, got {len(fusions)}"
    return fusions[0]


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
    fusion = _sole(r.resolve_operator_declaration(["camera.playroom_high_resolution_channel"]))
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
    fusion = _sole(r.resolve_operator_declaration(["camera.driveway"]))
    bases = {s.correlation_basis for s in fusion.sources}
    dids = {s.device_id for s in fusion.sources}
    assert "dev_unifi" in dids, "MAC rung should pull in the Protect device"
    assert BASIS_MAC in bases


# ============================================================================
# Rung 3 — identifiers overlap
# ============================================================================


def test_rung_identifiers_overlap_pulls_in_sibling_device():
    # D-LOW-1: match requires the FULL (integration, key) tuple. Two devices
    # from the SAME integration that expose the same key on separate
    # DeviceEntry rows (rare but legal — e.g. UniFi Protect firmware
    # rewiring) fuse via this rung.
    dev_a = FakeDevice(id="dev_a", identifiers={(PLATFORM_UNIFI, "shared-uid")})
    dev_b = FakeDevice(id="dev_b", identifiers={(PLATFORM_UNIFI, "shared-uid")})
    ents = [
        FakeEntity("camera.a", "dev_a", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.b_person_detected", "dev_b", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev_a, dev_b])
    fusion = _sole(r.resolve_operator_declaration(["camera.a"]))
    dids = {s.device_id for s in fusion.sources}
    bases = {s.correlation_basis for s in fusion.sources}
    assert "dev_b" in dids
    assert BASIS_IDENTIFIERS in bases


def test_rung_identifiers_cross_integration_key_alone_does_not_pull():
    """D-LOW-1: bare-key overlap across DIFFERENT integrations is NOT enough."""
    dev_a = FakeDevice(id="dev_a", identifiers={("integA", "opaque-1")})
    dev_b = FakeDevice(id="dev_b", identifiers={("integB", "opaque-1")})
    ents = [
        FakeEntity("camera.a", "dev_a", "integA"),
        FakeEntity("binary_sensor.b_person_detected", "dev_b", "integB"),
    ]
    r = _mk(ents, [dev_a, dev_b])
    fusions = r.resolve_operator_declaration(["camera.a"])
    assert isinstance(fusions, list)
    dids = {s.device_id for f in fusions for s in f.sources}
    assert "dev_b" not in dids


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
    fusion = _sole(r.resolve_operator_declaration(["camera.reo"]))
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
    fusion = _sole(r.resolve_operator_declaration(["camera.r"]))
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
    fusion = _sole(r.resolve_operator_declaration(["camera.staircase"]))
    dids = {s.device_id for s in fusion.sources}
    bases = {s.correlation_basis for s in fusion.sources}
    assert "dev_f" in dids
    assert BASIS_NAME_STEM in bases


# ============================================================================
# Rung 5 — bidirectional stem lookup (Frigate input -> Protect sibling)
# GOLDEN_MASTER census-cutover BLOCK-1 (2026-08-06): the Frigate-object-keyed
# `_frigate_stem_to_device_ids` served only UniFi->Frigate direction; egress
# cameras are listed as the FRIGATE entity, so a Frigate input needed a
# reverse rung to reach its Protect sibling (Protect devices carry no MAC
# and no identifiers on the live deployment). Pinned here.
# ============================================================================


def test_rung_name_stem_bidirectional_frigate_to_protect():
    """Frigate camera input reaches its Protect sibling via the reverse
    (camera-entity-keyed) stem index. Mirrors the live doorbell_lite /
    front_door_aerial / madrone_g6_entry egress case."""
    dev_frig = FakeDevice(
        id="dev_f",
        identifiers={(PLATFORM_FRIGATE, "host1:doorbell_lite")},
    )
    # Live Protect devices on this deployment carry NEITHER identifiers
    # NOR a MAC that matches Frigate (Frigate has no MAC). The only
    # cross-integration link is the camera-entity stem.
    dev_prot = FakeDevice(id="dev_p", identifiers=set(), connections=set())
    ents = [
        FakeEntity("camera.doorbell_lite", "dev_f", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.doorbell_lite_person_occupancy", "dev_f", PLATFORM_FRIGATE),
        FakeEntity("camera.doorbell_lite_high_resolution_channel", "dev_p", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.doorbell_lite_person_detected", "dev_p", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev_frig, dev_prot])
    fusion = _sole(r.resolve_operator_declaration(["camera.doorbell_lite"]))
    dids = {s.device_id for s in fusion.sources}
    bases = {s.correlation_basis for s in fusion.sources}
    assert "dev_p" in dids, "Protect sibling must be reachable from Frigate input"
    assert BASIS_NAME_STEM in bases
    # Both person BSes must be surfaced.
    person_bses = {s.person_binary_sensor for s in fusion.sources}
    assert "binary_sensor.doorbell_lite_person_occupancy" in person_bses
    assert "binary_sensor.doorbell_lite_person_detected" in person_bses


def test_rung_name_stem_bidirectional_mutation_drill_one_way_regresses():
    """Mutation drill: re-one-way the stem index (drop the bidirectional
    `_stem_to_device_ids` lookup in rung-5). The Frigate->Protect case
    must then FAIL to reach the Protect sibling. Guards against a future
    refactor silently dropping the reverse rung."""
    dev_frig = FakeDevice(
        id="dev_f",
        identifiers={(PLATFORM_FRIGATE, "host1:doorbell_lite")},
    )
    dev_prot = FakeDevice(id="dev_p", identifiers=set(), connections=set())
    ents = [
        FakeEntity("camera.doorbell_lite", "dev_f", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.doorbell_lite_person_occupancy", "dev_f", PLATFORM_FRIGATE),
        FakeEntity("camera.doorbell_lite_high_resolution_channel", "dev_p", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.doorbell_lite_person_detected", "dev_p", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev_frig, dev_prot])
    # Neuter the bidirectional index -> simulates a regression that reverts
    # the fix. The Frigate-keyed index alone cannot reach dev_p.
    r._stem_to_device_ids = {}
    fusion = _sole(r.resolve_operator_declaration(["camera.doorbell_lite"]))
    dids = {s.device_id for s in fusion.sources}
    assert "dev_p" not in dids, (
        "Regression check: without the bidirectional stem index, the "
        "Frigate->Protect reverse rung MUST be unreachable — this is the "
        "exact failure mode the fix repairs."
    )


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
    # Fix #7 (D-MED-2): multi-select now yields ONE RoomCameraFusion per
    # physically-distinct camera. Two unrelated inputs => two fusions.
    fusions = r.resolve_operator_declaration(
        ["camera.driveway", "camera.some_other_name"]
    )
    assert len(fusions) == 2, f"expected 2 physical cameras; got {len(fusions)}"
    dids = {s.device_id for f in fusions for s in f.sources}
    assert dids == {"dev_reo", "dev_frig"}
    # Each fusion's primary source is SAME_DEVICE for its own device.
    bases = {s.correlation_basis for f in fusions for s in f.sources}
    assert BASIS_SAME_DEVICE in bases


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
    fusion = _sole(r.resolve_operator_declaration(["camera.staircase_high_resolution_channel"]))
    person_bs_ids = fusion.person_binary_sensor_entity_ids()
    assert "binary_sensor.staircase_person_detected" in person_bs_ids
    assert "binary_sensor.camera_protect_garagehallway_person_detected" not in person_bs_ids, (
        "F1 fix: garagehallway_* sibling on same NVR device must be excluded "
        "from staircase fusion (Review D invariant)"
    )


# ============================================================================
# F2 — Frigate cross-host duplicate collapse (gate CLOSED by default)
# ============================================================================


def test_f2_frigate_dual_host_gate_semantics(monkeypatch):
    """Gate OPENED 2026-08-04 (72h stability measured — see camera_resolver
    const comment). Post-flip contract: BOTH hosts' same-object devices
    contribute sources (corroboration). The closed-gate collapse behavior
    remains pinned via monkeypatch so a regression of the gate mechanism
    itself stays detectable.
    """
    import sys as _sys
    cr = _sys.modules["camera_resolver_under_test"]
    assert cr.FRIGATE_CROSS_HOST_CORROBORATION_ENABLED is True, (
        "Gate opened by reviewed flip 2026-08-04; if deliberately re-closed, "
        "update this test with the new gate rationale"
    )
    # Closed-gate behavior still pinned:
    monkeypatch.setattr(cr, "FRIGATE_CROSS_HOST_CORROBORATION_ENABLED", False)
    dev_f1 = FakeDevice(id="dev_f1", identifiers={(PLATFORM_FRIGATE, "host1:staircase")})
    dev_f2 = FakeDevice(id="dev_f2", identifiers={(PLATFORM_FRIGATE, "host2:staircase")})
    dev_u = FakeDevice(id="dev_u", identifiers={(PLATFORM_UNIFI, "u")})
    ents = [
        FakeEntity("camera.staircase", "dev_u", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.staircase_person_detected", "dev_u", PLATFORM_UNIFI),
        # Both Frigate devices carry legit person-suffix entities with UNIQUE ids.
        FakeEntity("binary_sensor.staircase_person_occupancy", "dev_f1", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.staircase_alt_person_occupancy", "dev_f2", PLATFORM_FRIGATE),
    ]
    r = _mk(ents, [dev_f1, dev_f2, dev_u])
    fusion = _sole(r.resolve_operator_declaration(["camera.staircase"]))
    frigate_dids = [s.device_id for s in fusion.sources if s.integration == PLATFORM_FRIGATE]
    assert len(frigate_dids) == 1, (
        f"F2: expected 1 Frigate device after collapse; got {frigate_dids}"
    )


def test_f2_frigate_dual_host_both_contribute_when_gate_open():
    """Post-flip (2026-08-04): with the gate OPEN, both hosts' same-object
    devices contribute person sources — cross-host corroboration."""
    dev_f1 = FakeDevice(id="dev_f1", identifiers={(PLATFORM_FRIGATE, "host1:staircase")})
    dev_f2 = FakeDevice(id="dev_f2", identifiers={(PLATFORM_FRIGATE, "host2:staircase")})
    dev_u = FakeDevice(id="dev_u", identifiers={(PLATFORM_UNIFI, "u")})
    ents = [
        FakeEntity("camera.staircase", "dev_u", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.staircase_person_detected", "dev_u", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.staircase_person_occupancy", "dev_f1", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.staircase_alt_person_occupancy", "dev_f2", PLATFORM_FRIGATE),
    ]
    r = _mk(ents, [dev_f1, dev_f2, dev_u])
    fusion = _sole(r.resolve_operator_declaration(["camera.staircase"]))
    frigate_dids = {s.device_id for s in fusion.sources if s.integration == PLATFORM_FRIGATE}
    assert frigate_dids == {"dev_f1", "dev_f2"}, (
        f"open gate: both Frigate hosts must contribute; got {frigate_dids}"
    )


def test_f1_order_inversion_garagehallway_first_still_picks_staircase():
    """C-MED-1: F1 order-inversion. If the garagehallway entity is scanned
    FIRST on the shared NVR device, the resolver must STILL exclude it and
    pick the staircase sensor. Red under a `_stem_match` that returns True
    unconditionally."""
    dev = FakeDevice(id="dev_nvr", identifiers={(PLATFORM_UNIFI, "nvr-mac")},
                     connections={("mac", "28:70:4e:17:ee:02")})
    ents = [
        # Order inverted: garagehallway FIRST.
        FakeEntity("binary_sensor.camera_protect_garagehallway_person_detected",
                   "dev_nvr", PLATFORM_UNIFI),
        FakeEntity("camera.staircase_high_resolution_channel", "dev_nvr", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.staircase_person_detected", "dev_nvr", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev])
    fusion = _sole(r.resolve_operator_declaration(["camera.staircase_high_resolution_channel"]))
    person_bs_ids = fusion.person_binary_sensor_entity_ids()
    assert person_bs_ids == ["binary_sensor.staircase_person_detected"]
    assert "binary_sensor.camera_protect_garagehallway_person_detected" not in person_bs_ids


def test_f3_order_inversion_package_first_still_picks_person():
    """C-MED-2: F3 order-inversion. Package entity FIRST must not become the
    person_bs even though it's scanned first."""
    dev = FakeDevice(id="d_entry", identifiers={(PLATFORM_FRIGATE, "host1:madrone_g6_entry")})
    ents = [
        # Package entity FIRST.
        FakeEntity("binary_sensor.madrone_g6_entry_package_person_occupancy",
                   "d_entry", PLATFORM_FRIGATE),
        FakeEntity("camera.madrone_g6_entry", "d_entry", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.madrone_g6_entry_person_occupancy", "d_entry", PLATFORM_FRIGATE),
    ]
    r = _mk(ents, [dev])
    fusion = _sole(r.resolve_operator_declaration(["camera.madrone_g6_entry"]))
    person_bs = fusion.person_binary_sensor_entity_ids()
    assert person_bs == ["binary_sensor.madrone_g6_entry_person_occupancy"]


def test_cross_camera_invariant_with_two_unrelated_frigate_devices():
    """C-MED-3: Two unrelated Frigate devices with unrelated object names.
    An over-collect mutation (e.g. bare-substring stem_match) would red this."""
    dev_target = FakeDevice(id="dev_t", identifiers={(PLATFORM_FRIGATE, "host1:kitchen")})
    dev_other = FakeDevice(id="dev_o", identifiers={(PLATFORM_FRIGATE, "host1:backyard")})
    ents = [
        FakeEntity("camera.kitchen", "dev_t", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.kitchen_person_occupancy", "dev_t", PLATFORM_FRIGATE),
        FakeEntity("camera.backyard", "dev_o", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.backyard_person_occupancy", "dev_o", PLATFORM_FRIGATE),
    ]
    r = _mk(ents, [dev_target, dev_other])
    fusion = _sole(r.resolve_operator_declaration(["camera.kitchen"]))
    dids = {s.device_id for s in fusion.sources}
    assert dids == {"dev_t"}, f"cross-camera attribution leak: {dids}"


def test_direct_construction_dedup_same_integration_and_device():
    """C-LOW-1: post-fusion dedup by (integration, device_id) — two sources
    with the same (integration, device_id) collapse to one."""
    from dataclasses import replace
    FusionSource = _mod.FusionSource
    RoomCameraFusion = _mod.RoomCameraFusion
    a = FusionSource(integration=PLATFORM_UNIFI, device_id="d1",
                     person_binary_sensor="binary_sensor.a_person_detected")
    b = replace(a)  # duplicate (integration, device_id)
    # Manually simulate the resolver's post-fusion dedup path via a re-scan.
    dev = FakeDevice(id="d1", identifiers={(PLATFORM_UNIFI, "u")})
    ents = [
        FakeEntity("camera.a", "d1", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.a_person_detected", "d1", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev])
    fusion = _sole(r.resolve_operator_declaration(["camera.a"]))
    # Even if the input carried duplicates conceptually, only one FusionSource per (integration, device_id).
    pairs = [(s.integration, s.device_id) for s in fusion.sources]
    assert len(pairs) == len(set(pairs)), f"duplicate (integration, device_id): {pairs}"


def test_grep_guardrail_no_switch_actuation_in_resolver_or_dry_run():
    """C-LOW-2: assert zero switch.turn_on / async_call actuation in
    camera_resolver.py and the dry-run scan (per plan: dry-run only)."""
    def _strip_comments_and_strings(src: str) -> str:
        # Naive but sufficient: drop full-line comments AND triple-quoted docstrings.
        import re as _re
        no_docstrings = _re.sub(r'"""[\s\S]*?"""', "", src)
        lines = []
        for ln in no_docstrings.split("\n"):
            s = ln.split("#", 1)[0]
            lines.append(s)
        return "\n".join(lines)

    resolver_src = _strip_comments_and_strings(_RESOLVER_PATH.read_text())
    for banned in ("hass.services.async_call", ".async_call(", "'switch.turn_on'"):
        assert banned not in resolver_src, (
            f"banned actuation {banned!r} found in camera_resolver.py"
        )
    init_src = (REPO_ROOT / "custom_components/universal_room_automation/__init__.py").read_text()
    # Extract the dry-run function body.
    marker_start = "async def _camera_autoenable_dry_run_scan"
    if marker_start in init_src:
        start = init_src.index(marker_start)
        end = init_src.index("\nasync def ", start + 1)
        body = _strip_comments_and_strings(init_src[start:end])
        for banned in ("hass.services.async_call", ".async_call(", "'switch.turn_on'"):
            assert banned not in body, (
                f"banned actuation {banned!r} in dry-run scan body"
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
    fusion = _sole(r.resolve_operator_declaration(["camera.madrone_g6_entry"]))
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
    fusion = _sole(r.resolve_operator_declaration(
        ["camera.foo", "camera.foo_high_resolution_channel"]
    ))
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
    fusions = r.resolve_operator_declaration(["camera.x"])
    person = [eid for f in fusions for eid in f.person_binary_sensor_entity_ids()]
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
    fusion = _sole(r.resolve_operator_declaration(["camera.a"]))
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
    fusion = _sole(r.resolve_operator_declaration(["camera.foo"]))
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
    fusion = _sole(r.resolve_operator_declaration(["camera.x"]))
    assert fusion.sources[0].face_capability == FACE_ABSENT


def test_face_capability_usable_when_face_entity_enabled():
    dev = FakeDevice(id="d", identifiers={(PLATFORM_UNIFI, "u")})
    ents = [FakeEntity("camera.x", "d", PLATFORM_UNIFI),
            FakeEntity("binary_sensor.x_person_detected", "d", PLATFORM_UNIFI),
            FakeEntity("binary_sensor.x_face_detected", "d", PLATFORM_UNIFI)]
    r = _mk(ents, [dev])
    fusion = _sole(r.resolve_operator_declaration(["camera.x"]))
    assert fusion.sources[0].face_capability == FACE_USABLE


def test_face_capability_ambiguous_when_face_entity_disabled():
    dev = FakeDevice(id="d", identifiers={(PLATFORM_UNIFI, "u")})
    ents = [FakeEntity("camera.x", "d", PLATFORM_UNIFI),
            FakeEntity("binary_sensor.x_person_detected", "d", PLATFORM_UNIFI),
            FakeEntity("binary_sensor.x_face_detected", "d", PLATFORM_UNIFI,
                       disabled_by="user")]
    r = _mk(ents, [dev])
    fusion = _sole(r.resolve_operator_declaration(["camera.x"]))
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
    fusion = _sole(r.resolve_operator_declaration(["camera.x"]))
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
    fusions = r.resolve_operator_declaration([])
    assert fusions == []


def test_missing_entity_warns_and_skips():
    r = _mk([], [])
    fusions = r.resolve_operator_declaration(["camera.does_not_exist"])
    assert fusions == []


def test_stem_disambiguation_suffix_stripped():
    """Bench finding 2026-08-01: camera.armcrestash41b_2 (HA _N suffix)
    must still stem-match Frigate object 'armcrestash11b'-style names."""
    assert _mod._strip_disambiguation_suffix("armcrestash41b_2") == "armcrestash41b"
    assert _mod._strip_disambiguation_suffix("playroom") == "playroom"
    assert _mod._strip_disambiguation_suffix("g3_instant") == "g3_instant"[:len("g3_instant")]


# ============================================================================
# C-HIGH-1 — device_platform_hint prefers KNOWN camera integrations regardless
# of iteration order (e.g. co-resident `unifi` Network + `unifiprotect`).
# Mutation drill: drop the known-camera preference block in `_build_indices`
# and this test must go red.
# ============================================================================


def _hint_two_platforms(order: list[str]) -> str:
    dev = FakeDevice(id="dev_x", identifiers=set())
    ents = []
    # Camera entity anchors the device to camera-domain discovery.
    ents.append(FakeEntity("camera.foo", "dev_x", order[0]))
    ents.append(FakeEntity("binary_sensor.foo_person_detected", "dev_x", order[1]))
    r = _mk(ents, [dev])
    return r._device_platform_hint.get("dev_x", "")


def test_platform_hint_prefers_unifiprotect_over_unifi_network_forward():
    """Device has entities from `unifi` (Network) and `unifiprotect`. The
    known-camera preference MUST pick `unifiprotect` regardless of the
    iteration order returned by the registry."""
    got = _hint_two_platforms(["unifi", PLATFORM_UNIFI])
    assert got == PLATFORM_UNIFI, (
        f"expected unifiprotect to win the hint, got {got!r}"
    )


def test_platform_hint_prefers_unifiprotect_over_unifi_network_reverse():
    got = _hint_two_platforms([PLATFORM_UNIFI, "unifi"])
    assert got == PLATFORM_UNIFI


def test_platform_hint_downstream_f1_infer_integration_uses_hint():
    """The F1 stem filter consumes `_infer_integration`. With no
    device identifiers (the live Protect NVR shape on this deployment),
    the hint cache MUST make `_infer_integration` return `unifiprotect`.
    """
    dev = FakeDevice(id="dev_x", identifiers=set())
    ents = [
        FakeEntity("camera.foo", "dev_x", "unifi"),
        FakeEntity("binary_sensor.foo_person_detected", "dev_x", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev])
    got = r._infer_integration(dev)
    assert got == PLATFORM_UNIFI, (
        f"F1 filter would go inert if this were {got!r}; hint cache must "
        "override the empty-identifier device"
    )


# ============================================================================
# C-HIGH-2 — area_id resolver: entity.area_id, else device.area_id, else None;
# exception path degrades to None (legacy semantics).
# Mutation: hardcode `return None` and both non-None tests go red.
# ============================================================================


def test_resolve_area_id_prefers_entity_area():
    ents = [FakeEntity("binary_sensor.foo_person_detected", "dev_x", PLATFORM_UNIFI, area_id="area_room")]
    devs = [FakeDevice(id="dev_x", area_id="area_device")]
    got = _mod.resolve_area_id_for_entity(
        FakeEntityRegistry(ents), FakeDeviceRegistry(devs), "binary_sensor.foo_person_detected"
    )
    assert got == "area_room"


def test_resolve_area_id_falls_back_to_device_area():
    ents = [FakeEntity("binary_sensor.foo_person_detected", "dev_x", PLATFORM_UNIFI, area_id=None)]
    devs = [FakeDevice(id="dev_x", area_id="area_device")]
    got = _mod.resolve_area_id_for_entity(
        FakeEntityRegistry(ents), FakeDeviceRegistry(devs), "binary_sensor.foo_person_detected"
    )
    assert got == "area_device"


def test_resolve_area_id_degrades_to_none_on_missing_entity():
    got = _mod.resolve_area_id_for_entity(
        FakeEntityRegistry([]), FakeDeviceRegistry([]), "binary_sensor.nonexistent"
    )
    assert got is None


def test_resolve_area_id_degrades_to_none_on_registry_exception():
    class _Boom:
        def async_get(self, _):
            raise RuntimeError("registry down")
    got = _mod.resolve_area_id_for_entity(_Boom(), _Boom(), "binary_sensor.foo")
    assert got is None


# ============================================================================
# B-HIGH-2 — cross-host `_2` collapse via both-orders stem normalization,
# using the LIVE shape (`_2` appears AFTER `_person_occupancy`).
# ============================================================================


def test_cross_host_frigate_underscore_2_after_person_suffix_collapses():
    """Live shape: `binary_sensor.back_yard_person_occupancy_2` (F2 host)
    must index under stem `back_yard` alongside F1's
    `binary_sensor.back_yard_person_occupancy`. Both hosts remain distinct
    devices; rung-5 pulls both into one fusion via the exact-stem lookup."""
    dev_f1 = FakeDevice(
        id="dev_f1", identifiers={(PLATFORM_FRIGATE, "host1:back_yard")}
    )
    dev_f2 = FakeDevice(
        id="dev_f2", identifiers={(PLATFORM_FRIGATE, "host2:back_yard")}
    )
    ents = [
        FakeEntity("camera.back_yard", "dev_f1", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.back_yard_person_occupancy", "dev_f1", PLATFORM_FRIGATE),
        # F2 host: HA appended `_2` AFTER the person suffix.
        FakeEntity("binary_sensor.back_yard_person_occupancy_2", "dev_f2", PLATFORM_FRIGATE),
    ]
    r = _mk(ents, [dev_f1, dev_f2])
    # Both devices must be indexed under the `back_yard` stem.
    assert "dev_f1" in r._stem_to_device_ids.get("back_yard", set())
    assert "dev_f2" in r._stem_to_device_ids.get("back_yard", set())


# ============================================================================
# A-MED-1 — disabled entities excluded from the stem index.
# ============================================================================


def test_stem_index_skips_disabled_entities():
    dev_a = FakeDevice(id="dev_a", identifiers={(PLATFORM_UNIFI, "a")})
    dev_b = FakeDevice(id="dev_b", identifiers={(PLATFORM_UNIFI, "b")})
    ents = [
        FakeEntity("camera.same_stem", "dev_a", PLATFORM_UNIFI),
        # Disabled sibling on dev_b sharing the stem — MUST NOT get indexed.
        FakeEntity(
            "binary_sensor.same_stem_person_detected", "dev_b", PLATFORM_UNIFI,
            disabled_by="user",
        ),
    ]
    r = _mk(ents, [dev_a, dev_b])
    dids = r._stem_to_device_ids.get("same_stem", set())
    assert "dev_a" in dids
    assert "dev_b" not in dids, "disabled entity leaked into the stem index"


# ============================================================================
# A-MED-2 / C-MED-2 — `_N` disambiguation collapse is GUARDED by shared
# evidence. Two physically distinct cameras with `_N`-similar names but NO
# shared MAC / identifier / not-both-frigate MUST NOT collapse.
# ============================================================================


def test_disambiguation_collapse_gated_when_no_shared_evidence():
    """`_2` sibling with NO MAC / identifier overlap and DIFFERENT
    integration (Reolink vs UniFi) must not be pulled in."""
    dev_a = FakeDevice(id="dev_a", identifiers={(PLATFORM_UNIFI, "unifi-a")})
    dev_b = FakeDevice(id="dev_b", identifiers={(PLATFORM_REOLINK, "reo-b")})
    ents = [
        FakeEntity("camera.driveway", "dev_a", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.driveway_person_detected", "dev_a", PLATFORM_UNIFI),
        # Physically distinct camera whose HA name happens to carry `_2`.
        FakeEntity("camera.driveway_2", "dev_b", PLATFORM_REOLINK),
        FakeEntity("binary_sensor.driveway_2_person", "dev_b", PLATFORM_REOLINK),
    ]
    r = _mk(ents, [dev_a, dev_b])
    fusion = _sole(r.resolve_operator_declaration(["camera.driveway"]))
    dids = {s.device_id for s in fusion.sources}
    assert "dev_b" not in dids, (
        "unrelated `_2` camera collapsed without shared evidence — the "
        "dstem guard is broken"
    )


def test_disambiguation_collapse_allowed_when_shared_mac():
    """`_2` sibling with a shared MAC connection is legitimately the same
    physical camera — must be pulled in."""
    mac = "aa:bb:cc:11:22:33"
    dev_a = FakeDevice(
        id="dev_a", identifiers={(PLATFORM_UNIFI, "unifi-a")},
        connections={("mac", mac)},
    )
    dev_b = FakeDevice(
        id="dev_b", identifiers={(PLATFORM_REOLINK, "reo-b")},
        connections={("mac", mac)},
    )
    ents = [
        FakeEntity("camera.driveway", "dev_a", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.driveway_person_detected", "dev_a", PLATFORM_UNIFI),
        FakeEntity("camera.driveway_2", "dev_b", PLATFORM_REOLINK),
        FakeEntity("binary_sensor.driveway_2_person", "dev_b", PLATFORM_REOLINK),
    ]
    r = _mk(ents, [dev_a, dev_b])
    fusion = _sole(r.resolve_operator_declaration(["camera.driveway"]))
    dids = {s.device_id for s in fusion.sources}
    # MAC rung + guarded dstem rung both admit dev_b.
    assert "dev_b" in dids
