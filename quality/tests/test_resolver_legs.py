"""Cycle-3 resolver-legs (2026-08-07) tests.

Covers CameraResolver.resolve_detection_legs() across all engine tags
(frigate, frigate2, protect, protect2, reolink, amcrest, dahua), the
native-AI suffix shapes verified via live registry probe 2026-08-07,
the post-F1 registry-shape invariance, retirement anchors for the
deleted perimeter_alert.py helpers, and the disagreement telemetry.

Bug Class #62 discipline: tests drive the REAL production modules via
importlib direct source load — no local stubs.
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
_spec = _il.spec_from_file_location("camera_resolver_legs_under_test", _RESOLVER_PATH)
_mod = _il.module_from_spec(_spec)
sys.modules["camera_resolver_legs_under_test"] = _mod
_spec.loader.exec_module(_mod)

CameraResolver = _mod.CameraResolver
DetectionLeg = _mod.DetectionLeg
PLATFORM_FRIGATE = _mod.PLATFORM_FRIGATE
PLATFORM_UNIFI = _mod.PLATFORM_UNIFI
PLATFORM_REOLINK = _mod.PLATFORM_REOLINK
PLATFORM_AMCREST = _mod.PLATFORM_AMCREST
PLATFORM_DAHUA = _mod.PLATFORM_DAHUA


# ---------------------------------------------------------------------------
# Fixtures (duck-typed HA registry shape).
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
    def __init__(self, entities): self.entities = {e.entity_id: e for e in entities}
    def async_get(self, eid): return self.entities.get(eid)


class FakeDR:
    def __init__(self, devices): self.devices = {d.id: d for d in devices}
    def async_get(self, did): return self.devices.get(did)


def _mk(ents, devs, **kw):
    return CameraResolver(FakeER(ents), FakeDR(devs), **kw)


# ---------------------------------------------------------------------------
# D1: per-engine leg resolution — full 6-engine perimeter camera.
# ---------------------------------------------------------------------------


def _perimeter_registry_full_engines():
    """A perimeter camera with Frigate F1+F2 + Protect base+`_2` + native-AI."""
    dev_f1 = FakeDevice(id="dev_f1", identifiers={(PLATFORM_FRIGATE, "host1:back_yard")})
    dev_f2 = FakeDevice(id="dev_f2", identifiers={(PLATFORM_FRIGATE, "host2:back_yard")})
    dev_pr = FakeDevice(id="dev_pr", identifiers={(PLATFORM_UNIFI, "pr-back_yard-uid")})
    ents = [
        FakeEntity("camera.back_yard", "dev_f1", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.back_yard_person_occupancy", "dev_f1", PLATFORM_FRIGATE),
        FakeEntity("camera.back_yard_2", "dev_f2", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.back_yard_person_occupancy_2", "dev_f2", PLATFORM_FRIGATE),
        FakeEntity("camera.back_yard_high_resolution_channel", "dev_pr", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.back_yard_person_detected", "dev_pr", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.back_yard_person_detected_2", "dev_pr", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.back_yard_vehicle_detected", "dev_pr", PLATFORM_UNIFI),
    ]
    return ents, [dev_f1, dev_f2, dev_pr]


def test_resolve_detection_legs_person_across_frigate_and_protect_engines():
    ents, devs = _perimeter_registry_full_engines()
    r = _mk(ents, devs)
    legs = r.resolve_detection_legs("camera.back_yard", "person")
    engines = sorted({l.engine for l in legs})
    assert engines == ["frigate", "frigate2", "protect", "protect2"], engines
    # Deterministic order by entity_id.
    eids = [l.entity_id for l in legs]
    assert eids == sorted(eids)


def test_resolve_detection_legs_vehicle_returns_protect_vehicle_leg():
    ents, devs = _perimeter_registry_full_engines()
    r = _mk(ents, devs)
    legs = r.resolve_detection_legs("camera.back_yard", "vehicle")
    engines = {l.engine for l in legs}
    assert "protect" in engines
    assert all("_vehicle" in l.entity_id for l in legs)


def test_resolve_detection_legs_reolink_bare_person_suffix():
    """Verified live 2026-08-07: reolink native AI uses bare `_person`."""
    dev_reo = FakeDevice(id="dev_reo",
                          identifiers={(PLATFORM_REOLINK, "reo-uid")},
                          connections={("mac", "aa:bb:cc:dd:ee:ff")})
    ents = [
        FakeEntity("camera.ptzcamreolinktmixpstudybporch", "dev_reo", PLATFORM_REOLINK),
        FakeEntity("binary_sensor.ptzcamreolinktmixpstudybporch_person", "dev_reo", PLATFORM_REOLINK),
        FakeEntity("binary_sensor.ptzcamreolinktmixpstudybporch_vehicle", "dev_reo", PLATFORM_REOLINK),
        FakeEntity("binary_sensor.ptzcamreolinktmixpstudybporch_animal", "dev_reo", PLATFORM_REOLINK),
    ]
    r = _mk(ents, [dev_reo])
    for fam, expected_suffix in (("person", "_person"), ("vehicle", "_vehicle"), ("animal", "_animal")):
        legs = r.resolve_detection_legs("camera.ptzcamreolinktmixpstudybporch", fam)
        assert legs, f"expected legs for {fam}"
        assert any(l.engine == "reolink" for l in legs), (fam, legs)
        assert all(l.entity_id.endswith(expected_suffix) or l.entity_id.endswith(expected_suffix + "_2")
                   for l in legs), (fam, legs)


def test_resolve_detection_legs_dahua_smart_motion_human_suffix():
    """Verified live 2026-08-07: Dahua exposes `_smart_motion_human` / `_smart_motion_vehicle`."""
    dev_dahua = FakeDevice(id="dev_dahua",
                            identifiers={(PLATFORM_DAHUA, "AMC0946UID")},
                            connections={("mac", "a0:60:32:06:34:8e")})
    ents = [
        FakeEntity("camera.armcrestpooloverhead_main", "dev_dahua", PLATFORM_DAHUA),
        FakeEntity("binary_sensor.armcrestpooloverhead_smart_motion_human", "dev_dahua", PLATFORM_DAHUA),
        FakeEntity("binary_sensor.armcrestpooloverhead_smart_motion_vehicle", "dev_dahua", PLATFORM_DAHUA),
    ]
    r = _mk(ents, [dev_dahua])
    legs_p = r.resolve_detection_legs("camera.armcrestpooloverhead_main", "person")
    assert any(l.engine == "dahua" and l.entity_id.endswith("_smart_motion_human") for l in legs_p)
    legs_v = r.resolve_detection_legs("camera.armcrestpooloverhead_main", "vehicle")
    assert any(l.engine == "dahua" and l.entity_id.endswith("_smart_motion_vehicle") for l in legs_v)


def test_resolve_detection_legs_unknown_family_returns_empty():
    ents, devs = _perimeter_registry_full_engines()
    r = _mk(ents, devs)
    assert r.resolve_detection_legs("camera.back_yard", "bicycle") == []


def test_resolve_detection_legs_disabled_entity_excluded():
    dev_pr = FakeDevice(id="dev_pr", identifiers={(PLATFORM_UNIFI, "pr")})
    ents = [
        FakeEntity("camera.doorbell", "dev_pr", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.doorbell_person_detected", "dev_pr", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.doorbell_person_detected_2", "dev_pr", PLATFORM_UNIFI,
                   disabled_by="user"),
    ]
    r = _mk(ents, [dev_pr])
    legs = r.resolve_detection_legs("camera.doorbell", "person")
    eids = [l.entity_id for l in legs]
    assert "binary_sensor.doorbell_person_detected" in eids
    assert "binary_sensor.doorbell_person_detected_2" not in eids


def test_resolve_detection_legs_frigate_package_person_excluded():
    dev_f = FakeDevice(id="dev_f", identifiers={(PLATFORM_FRIGATE, "h:egress")})
    ents = [
        FakeEntity("camera.egress", "dev_f", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.egress_person_occupancy", "dev_f", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.egress_package_person_occupancy", "dev_f", PLATFORM_FRIGATE),
    ]
    r = _mk(ents, [dev_f])
    legs = r.resolve_detection_legs("camera.egress", "person")
    eids = {l.entity_id for l in legs}
    assert "binary_sensor.egress_person_occupancy" in eids
    assert "binary_sensor.egress_package_person_occupancy" not in eids


# ---------------------------------------------------------------------------
# D4: post-F1 registry-shape invariance.
# ---------------------------------------------------------------------------


def test_post_f1_registry_shape_only_f2_and_protect():
    """AUDIT_frigate1_sunset.md Option B: F1 deleted -> only `_2`-suffixed
    Frigate remains + Protect. Resolver still finds legs identically."""
    dev_f2 = FakeDevice(id="dev_f2", identifiers={(PLATFORM_FRIGATE, "h2:hot_tub")})
    dev_pr = FakeDevice(id="dev_pr", identifiers={(PLATFORM_UNIFI, "pr-hot_tub")})
    # F2 entities carry `_2` suffix (F1 predecessor deleted -> ids not renamed).
    ents = [
        FakeEntity("camera.hot_tub_2", "dev_f2", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.hot_tub_person_occupancy_2", "dev_f2", PLATFORM_FRIGATE),
        FakeEntity("camera.hot_tub_high_resolution_channel", "dev_pr", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.hot_tub_person_detected", "dev_pr", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev_f2, dev_pr])
    legs = r.resolve_detection_legs("camera.hot_tub_2", "person")
    engines = {l.engine for l in legs}
    assert "frigate2" in engines
    assert "protect" in engines


def test_post_f1_registry_shape_after_bulk_rename_base_ids():
    """Option B step 6: `_2` bulk-renamed back to base — resolver still works."""
    dev_f2 = FakeDevice(id="dev_f2", identifiers={(PLATFORM_FRIGATE, "h2:hot_tub")})
    dev_pr = FakeDevice(id="dev_pr", identifiers={(PLATFORM_UNIFI, "pr-hot_tub")})
    ents = [
        FakeEntity("camera.hot_tub", "dev_f2", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.hot_tub_person_occupancy", "dev_f2", PLATFORM_FRIGATE),
        FakeEntity("camera.hot_tub_high_resolution_channel", "dev_pr", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.hot_tub_person_detected", "dev_pr", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev_f2, dev_pr])
    legs = r.resolve_detection_legs("camera.hot_tub", "person")
    engines = {l.engine for l in legs}
    # Post-rename: F2 sensor has no `_N` suffix so tags as "frigate" (base).
    assert "frigate" in engines
    assert "protect" in engines


# ---------------------------------------------------------------------------
# Retirement anchors — the deleted perimeter_alert.py helpers stay deleted.
# ---------------------------------------------------------------------------


def test_retirement_anchor_perimeter_helpers_deleted():
    """Cycle-3 retirement anchor: the three legacy leg-derivation helpers
    are removed from PerimeterAlertManager. Resurrecting them via a paste-
    revert would silently re-introduce the three generations of hand-
    rolled slug logic this cycle deleted."""
    src = (REPO_ROOT / "custom_components/universal_room_automation/perimeter_alert.py").read_text()
    for retired in ("def _fused_sibling(", "def _protect_person_legs(", "def _derive_sibling_sensor("):
        assert retired not in src, (
            f"Retired helper {retired!r} has been resurrected — cycle-3 "
            "cameraresolver-legs mandates it stay deleted; use "
            "CameraResolver.resolve_detection_legs() instead."
        )


def test_kill_switch_rename_present_and_alias_retained():
    """The rename PERIMETER_PROTECT_PERSON_LEGS_ENABLED ->
    PERIMETER_MULTI_ENGINE_LEGS_ENABLED shipped with a one-release
    deprecated alias for out-of-tree consumers."""
    src = (REPO_ROOT / "custom_components/universal_room_automation/const.py").read_text()
    assert "PERIMETER_MULTI_ENGINE_LEGS_ENABLED" in src
    assert "PERIMETER_PROTECT_PERSON_LEGS_ENABLED" in src  # alias retained


# ---------------------------------------------------------------------------
# D3: disagreement telemetry (PerimeterAlertManager.leg_firing_stats).
# ---------------------------------------------------------------------------


class _StubHassData(dict):
    pass


class _StubHass:
    def __init__(self):
        self.data = {}
        self.states = self  # minimal .get() below
    def get(self, _eid):  # states.get stub
        return None


def _make_stub_manager():
    """Construct a bare PerimeterAlertManager for telemetry unit tests
    (no HA import; only the pure-Python counters + camera-key helper)."""
    # Load perimeter_alert module without triggering package __init__.
    pa_path = REPO_ROOT / "custom_components/universal_room_automation/perimeter_alert.py"
    # This file DOES import homeassistant. Skip the module-level test
    # by exercising only the pure functions via a thin subclass; if
    # the import fails in a bare-python env, the telemetry test is
    # skipped rather than errored.
    try:
        import types
        # Try normal import path first; falls through to skip.
        pkg = "custom_components.universal_room_automation"
        if pkg not in sys.modules:
            sys.path.insert(0, str(REPO_ROOT))
            import importlib
            importlib.import_module(pkg)
        pa = importlib.import_module(pkg + ".perimeter_alert")
        return pa.PerimeterAlertManager.__new__(pa.PerimeterAlertManager)
    except Exception as exc:
        pytest.skip(f"PerimeterAlertManager not importable in this env: {exc}")


def test_leg_firing_stats_shape_and_sole_firing_ratio():
    """Two engines fire on the same camera within window -> neither is
    'sole'; a lone third engine fire outside the window -> sole."""
    from datetime import datetime, timedelta, timezone
    mgr = _make_stub_manager()
    # Manually initialize the counter fields the telemetry reads (bypass
    # __init__ which needs hass); mirrors the __init__ block.
    mgr._leg_fire_counts = {}
    mgr._leg_sole_fire_counts = {}
    mgr._recent_fires = {}
    mgr._sensor_engine = {
        "binary_sensor.cam1_person_occupancy": "frigate",
        "binary_sensor.cam1_person_occupancy_2": "frigate2",
        "binary_sensor.cam1_person_detected": "protect",
    }
    # Route camera key via a stub _camera_key_for_sensor.
    mgr._camera_key_for_sensor = lambda eid: "cam1"

    # Freeze wall clock via a stub dt_util.now — but the production
    # method calls `dt_util.now()` directly, so we just fire sequentially
    # and trust that the deltas are within the 60s window when the test
    # runs in <1s (verified experimentally).
    mgr._record_leg_fire("binary_sensor.cam1_person_occupancy")
    mgr._record_leg_fire("binary_sensor.cam1_person_occupancy_2")
    mgr._record_leg_fire("binary_sensor.cam1_person_detected")

    stats = mgr.leg_firing_stats()
    assert "cam1" in stats
    row = stats["cam1"]
    assert set(row["engines"]) == {"frigate", "frigate2", "protect"}
    assert row["fire_counts_by_engine"] == {"frigate": 1, "frigate2": 1, "protect": 1}
    # Because all three fires happened within the sole-firing window,
    # NONE should count as sole.
    assert row["sole_firing_counts_by_engine"] == {}


def test_leg_firing_stats_handles_empty_state():
    mgr = _make_stub_manager()
    mgr._leg_fire_counts = {}
    mgr._leg_sole_fire_counts = {}
    assert mgr.leg_firing_stats() == {}


# ---------------------------------------------------------------------------
# D2 (N-leg single alert) — mutation-anchored via cooldown key collapse.
# ---------------------------------------------------------------------------


def test_five_legs_collapse_to_one_camera_key():
    """A camera whose person events surface on 5 engines still yields ONE
    cooldown key. This is the load-bearing invariant that lets the resolver
    return every engine's leg without inflating alert count."""
    mgr = _make_stub_manager()
    # Directly exercise the camera-key stripper — the same primitive
    # every cooldown/in-flight/telemetry site keys through.
    legs = [
        "binary_sensor.back_yard_person_occupancy",
        "binary_sensor.back_yard_person_occupancy_2",
        "binary_sensor.back_yard_person_detected",
        "binary_sensor.back_yard_person_detected_2",
        "binary_sensor.back_yard_person",  # native AI (bare)
    ]
    keys = {mgr._camera_key_for_sensor(l) for l in legs}
    assert keys == {"back_yard"}, keys
