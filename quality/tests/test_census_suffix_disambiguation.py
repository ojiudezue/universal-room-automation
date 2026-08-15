"""CENSUS-SUFFIX-FIX tests (2026-08-15).

Wire-in anchors + mutation drills for the disambiguation-tolerant suffix
matching that restores per-camera counts after the F1 Frigate host retirement
(AUDIT_census_accuracy_regression.md). Every surviving Frigate person entity
carries HA's ``_2`` suffix (``sensor.<cam>_person_count_2``); strict
``endswith`` matchers silently dropped them, pinning house census at the
identified count.

These tests DRIVE the real production modules (no local stub) so a mutation
that removes the strip call at a load-bearing site (e.g. deleting the
``_strip_disambiguation_suffix`` call in the count-sensor branch of
``_scan_device_entities``, or in the legacy ``camera_census`` frigate branch)
turns a named test in this file red.

Encoded both sides of the regression: the fixed behavior (count sensor maps
to the real ``_2`` entity_id, so ``person_count_sensor`` is populated), and
the OLD binary-fallback behavior (asserted symbolically by demonstrating that
without the count sensor the fusion would pin at 1 per camera).
"""
from __future__ import annotations

import importlib.util as _il
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_RESOLVER_PATH = REPO_ROOT / "custom_components/universal_room_automation/camera_resolver.py"
_spec = _il.spec_from_file_location("camera_resolver_suffix_ut", _RESOLVER_PATH)
_mod = _il.module_from_spec(_spec)
sys.modules["camera_resolver_suffix_ut"] = _mod
_spec.loader.exec_module(_mod)

CameraResolver = _mod.CameraResolver
PLATFORM_FRIGATE = _mod.PLATFORM_FRIGATE


# ---------------------------------------------------------------------------
# Duck-typed registry fixtures (shape-copied from test_camera_resolver.py)
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


def _mk(entities, devices) -> "CameraResolver":
    return CameraResolver(FakeEntityRegistry(entities), FakeDeviceRegistry(devices))


# ---------------------------------------------------------------------------
# Fixture: playroom Frigate device where EVERY entity is `_2`-suffixed.
# Matches the live registry state after F1 retirement (audit §H1).
# ---------------------------------------------------------------------------


def _playroom_all_suffixed():
    dev = FakeDevice(
        id="dev_play_f2",
        identifiers={(PLATFORM_FRIGATE, "playroom")},
    )
    ents = [
        FakeEntity("camera.playroom", "dev_play_f2", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.playroom_person_occupancy_2", "dev_play_f2", PLATFORM_FRIGATE),
        FakeEntity("sensor.playroom_person_count_2", "dev_play_f2", PLATFORM_FRIGATE),
    ]
    return dev, ents


# ---------------------------------------------------------------------------
# Wire-in anchor + first mutation drill target (count-sensor branch).
# ---------------------------------------------------------------------------


def test_suffix_disambiguated_count_sensor_maps():
    """A Frigate device whose entities are ALL `_2`-suffixed still resolves
    a `person_count_sensor`. If the strip call at the count-sensor branch
    in `_scan_device_entities` is removed, this test goes red."""
    dev, ents = _playroom_all_suffixed()
    r = _mk(ents, [dev])
    fusions = r.resolve_operator_declaration(["camera.playroom"])
    assert isinstance(fusions, list) and len(fusions) == 1
    src = fusions[0].sources[0]
    assert src.person_count_sensor == "sensor.playroom_person_count_2", (
        "must map to REAL disambiguated entity_id (never fabricate a canonical id)"
    )


# ---------------------------------------------------------------------------
# Second mutation drill target (person-binary branch).
# ---------------------------------------------------------------------------


def test_suffix_disambiguated_person_binary_maps():
    """A Frigate device whose person binary is `_2`-only still resolves a
    `person_binary_sensor`. Neutering the strip in the person-binary branch
    of `_scan_device_entities` reverts this to `None` and turns this red."""
    dev, ents = _playroom_all_suffixed()
    r = _mk(ents, [dev])
    fusions = r.resolve_operator_declaration(["camera.playroom"])
    src = fusions[0].sources[0]
    assert src.person_binary_sensor == "binary_sensor.playroom_person_occupancy_2"


# ---------------------------------------------------------------------------
# Ambiguity guard: canonical wins over `_2` when both are registered.
# ---------------------------------------------------------------------------


def test_ambiguity_prefers_canonical_over_disambiguated(caplog):
    dev = FakeDevice(id="dev_amb", identifiers={(PLATFORM_FRIGATE, "playroom")})
    ents = [
        FakeEntity("camera.playroom", "dev_amb", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.playroom_person_occupancy", "dev_amb", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.playroom_person_occupancy_2", "dev_amb", PLATFORM_FRIGATE),
        FakeEntity("sensor.playroom_person_count_2", "dev_amb", PLATFORM_FRIGATE),
        FakeEntity("sensor.playroom_person_count", "dev_amb", PLATFORM_FRIGATE),
    ]
    r = _mk(ents, [dev])
    with caplog.at_level("WARNING"):
        fusions = r.resolve_operator_declaration(["camera.playroom"])
    src = fusions[0].sources[0]
    assert src.person_binary_sensor == "binary_sensor.playroom_person_occupancy"
    assert src.person_count_sensor == "sensor.playroom_person_count"
    warn_msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("preferring canonical" in m for m in warn_msgs), warn_msgs


# ---------------------------------------------------------------------------
# Regression shape: with a mapped `_2` count sensor reporting 4 while
# identified=4, the census fusion has a real count path (total >= 8 possible
# because unrecognized = max(0, camera_total - identified) > 0). Without the
# fix, `person_count_sensor` would be None -> binary-fallback pins at 1 per
# camera and unrecognized collapses to 0. We prove the routing here; the
# arithmetic path itself is covered by test_camera_census / fusion tests.
# ---------------------------------------------------------------------------


def test_regression_mapped_count_enables_unrecognized_path():
    """Encodes both sides of the 08-13 regression: mapped `_2` count means
    the fusion carries a real count sensor (>1 possible); the OLD strict
    matcher would have left `person_count_sensor=None`, degrading to binary
    fallback (max 1/camera) and pinning census at identified count."""
    dev, ents = _playroom_all_suffixed()
    r = _mk(ents, [dev])
    src = r.resolve_operator_declaration(["camera.playroom"])[0].sources[0]

    # FIX side: count sensor is populated -> integer counts flow through.
    assert src.person_count_sensor is not None
    assert src.person_count_sensor.endswith("_person_count_2")

    # OLD side (symbolic): using the pre-fix strict matcher against the
    # same entity name would have failed and left the slot None. Prove the
    # matcher shape rather than re-run the whole pipeline.
    name = src.person_count_sensor.split(".", 1)[1]
    assert not name.endswith("_person_count"), (
        "if the raw name endswith _person_count the strip is not being exercised"
    )
    from camera_resolver_suffix_ut import _strip_disambiguation_suffix
    assert _strip_disambiguation_suffix(name).endswith("_person_count")
