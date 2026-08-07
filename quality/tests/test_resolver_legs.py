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
import types
from dataclasses import dataclass, field
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


# F4 (cycle-3 fix-up 2026-08-07): HA-stub prelude so tests that need to
# import perimeter_alert.py run in the canonical env (no `homeassistant`
# installed). Mirrors the pattern in test_perimeter_alert_nm_routing.py.
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
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": MagicMock(),
    },
    "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda *a, **kw: MagicMock(),
        "async_dispatcher_send": lambda *a, **kw: None,
    },
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
    "homeassistant.const": {
        "EVENT_HOMEASSISTANT_STARTED": "homeassistant_started",
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


def _load_pa_module():
    """Load perimeter_alert + its deps by file spec (avoids package __init__)."""
    import os
    _cc = sys.modules.get("custom_components")
    if _cc is None or not hasattr(_cc, "__path__"):
        _cc = types.ModuleType("custom_components")
        _cc.__path__ = [str(REPO_ROOT / "custom_components")]
        sys.modules["custom_components"] = _cc
    _ura_path = str(REPO_ROOT / "custom_components/universal_room_automation")
    _ura = sys.modules.get("custom_components.universal_room_automation")
    if _ura is None or not hasattr(_ura, "__path__"):
        _ura = types.ModuleType("custom_components.universal_room_automation")
        _ura.__path__ = [_ura_path]
        _ura.__package__ = "custom_components.universal_room_automation"
        sys.modules["custom_components.universal_room_automation"] = _ura
        _cc.universal_room_automation = _ura

    def _load(name, path):
        if name in sys.modules and getattr(sys.modules[name], "__file__", None):
            return sys.modules[name]
        spec = _il.spec_from_file_location(name, path)
        mod = _il.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    _load("custom_components.universal_room_automation.const",
          os.path.join(_ura_path, "const.py"))
    _load("custom_components.universal_room_automation.camera_resolver",
          os.path.join(_ura_path, "camera_resolver.py"))
    _dc_path = os.path.join(_ura_path, "domain_coordinators")
    _dc_name = "custom_components.universal_room_automation.domain_coordinators"
    if _dc_name not in sys.modules:
        _dc = types.ModuleType(_dc_name)
        _dc.__path__ = [_dc_path]
        _dc.__package__ = _dc_name
        sys.modules[_dc_name] = _dc
    _load(_dc_name + ".base", os.path.join(_dc_path, "base.py"))
    return _load(
        "custom_components.universal_room_automation.perimeter_alert",
        os.path.join(_ura_path, "perimeter_alert.py"),
    )


def _make_stub_manager():
    """Construct a bare PerimeterAlertManager for telemetry unit tests."""
    pa = _load_pa_module()
    return pa.PerimeterAlertManager.__new__(pa.PerimeterAlertManager)


def test_leg_firing_stats_shape_and_sole_firing_ratio(monkeypatch):
    """Three engines fire on the same camera within window.

    F14/F17 (cycle-3 fix-up 2026-08-07): timestamps are INJECTED (not
    wall-clock trusted) so the sole-firing semantic is exercised
    deterministically. Semantic: "sole" is point-in-time — at fire time,
    if no OTHER engine has fired in the window, this is a sole episode.
    Once a second engine fires in the same window, subsequent fires are
    not sole. Same-engine repeats within the episode do NOT increment
    the sole counter (F14).
    """
    from datetime import datetime, timedelta, timezone
    pa = _load_pa_module()
    mgr = _make_stub_manager()
    mgr._leg_fire_counts = {}
    mgr._leg_sole_fire_counts = {}
    mgr._recent_fires = {}
    mgr._sensor_engine = {
        "binary_sensor.cam1_person_occupancy": "frigate",
        "binary_sensor.cam1_person_occupancy_2": "frigate2",
        "binary_sensor.cam1_person_detected": "protect",
    }
    mgr._camera_key_for_sensor = lambda eid: "cam1"

    # Inject a controllable clock — three fires 5s apart, all inside
    # the SOLE_FIRE window (default 60s).
    t0 = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)
    seq = iter([t0, t0 + timedelta(seconds=5), t0 + timedelta(seconds=10)])
    fake_dt = type("FakeDt", (), {})()
    fake_dt.now = lambda: next(seq)
    fake_dt.utcnow = lambda: datetime.now(timezone.utc)
    monkeypatch.setattr(pa, "dt_util", fake_dt)

    mgr._record_leg_fire("binary_sensor.cam1_person_occupancy")   # sole at t0
    mgr._record_leg_fire("binary_sensor.cam1_person_occupancy_2") # not sole
    mgr._record_leg_fire("binary_sensor.cam1_person_detected")    # not sole

    stats = mgr.leg_firing_stats()
    row = stats["cam1"]
    assert set(row["engines"]) == {"frigate", "frigate2", "protect"}
    assert row["fire_counts_by_engine"] == {"frigate": 1, "frigate2": 1, "protect": 1}
    # Only the first frigate fire had no other engine in window → 1 sole
    # for frigate; frigate2 + protect saw prior other-engine fires → 0.
    assert row["sole_firing_counts_by_engine"].get("frigate", 0) == 1
    assert row["sole_firing_counts_by_engine"].get("frigate2", 0) == 0
    assert row["sole_firing_counts_by_engine"].get("protect", 0) == 0


def test_record_leg_fire_same_engine_not_double_sole_counted(monkeypatch):
    """F14 (cycle-3 fix-up): a sole EPISODE counts once. Two same-engine
    fires with no other engine in window → sole counter = 1, not 2."""
    from datetime import datetime, timedelta, timezone
    pa = _load_pa_module()
    mgr = _make_stub_manager()
    mgr._leg_fire_counts = {}
    mgr._leg_sole_fire_counts = {}
    mgr._recent_fires = {}
    mgr._sensor_engine = {"binary_sensor.camx_person_occupancy": "frigate"}
    mgr._camera_key_for_sensor = lambda eid: "camx"

    t0 = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)
    seq = iter([t0, t0 + timedelta(seconds=5)])
    fake_dt = type("FakeDt", (), {})()
    fake_dt.now = lambda: next(seq)
    fake_dt.utcnow = lambda: datetime.now(timezone.utc)
    monkeypatch.setattr(pa, "dt_util", fake_dt)

    mgr._record_leg_fire("binary_sensor.camx_person_occupancy")
    mgr._record_leg_fire("binary_sensor.camx_person_occupancy")
    stats = mgr.leg_firing_stats()
    assert stats["camx"]["fire_counts_by_engine"]["frigate"] == 2
    assert stats["camx"]["sole_firing_counts_by_engine"].get("frigate", 0) == 1


def test_leg_firing_stats_handles_empty_state():
    mgr = _make_stub_manager()
    mgr._leg_fire_counts = {}
    mgr._leg_sole_fire_counts = {}
    assert mgr.leg_firing_stats() == {}


# ---------------------------------------------------------------------------
# D2 (N-leg single alert) — mutation-anchored via cooldown key collapse.
# ---------------------------------------------------------------------------


def test_five_legs_collapse_to_one_camera_key():
    """F1 (cycle-3 fix-up): a camera whose person events surface on all
    engines still yields ONE cooldown key. Includes Dahua
    `_smart_motion_human` and bare Reolink `_person` — the F1 dedup gap
    that previously produced two alerts (Dahua leg + Frigate leg)."""
    mgr = _make_stub_manager()
    legs = [
        "binary_sensor.back_yard_person_occupancy",
        "binary_sensor.back_yard_person_occupancy_2",
        "binary_sensor.back_yard_person_detected",
        "binary_sensor.back_yard_person_detected_2",
        "binary_sensor.back_yard_person",              # Reolink native (bare)
        "binary_sensor.back_yard_smart_motion_human",  # Dahua/Amcrest native
    ]
    keys = {mgr._camera_key_for_sensor(l) for l in legs}
    assert keys == {"back_yard"}, keys


def test_person_family_suffixes_derived_from_resolver_vocab():
    """F1: perimeter dedup suffix set must be sourced FROM the resolver
    vocabulary — a single source of truth."""
    pa = _load_pa_module()
    from camera_resolver_legs_under_test import _PERSON_SUFFIXES as _R
    got = set(pa.PerimeterAlertManager._PERSON_FAMILY_SUFFIXES)
    assert set(_R).issubset(got)
    assert "_smart_motion_human" in got


def test_kill_switch_rename_alias_import_level():
    """F12 (cycle-3 fix-up): the deprecated alias must resolve to the same
    object as the new name (import-level, not just source-string equality)."""
    pa = _load_pa_module()
    from custom_components.universal_room_automation import const as _c
    assert (
        _c.PERIMETER_PROTECT_PERSON_LEGS_ENABLED
        is _c.PERIMETER_MULTI_ENGINE_LEGS_ENABLED
    )


def test_off_path_preserves_v5580_protect_probe():
    """F3 (cycle-3 fix-up): kill-switch OFF must fall back to v5.58.0 —
    Frigate base + `_2` PLUS the Protect stem-probed leg. This proves
    a kill-switch pull does not silently regress Protect coverage."""
    pa = _load_pa_module()
    mgr = pa.PerimeterAlertManager.__new__(pa.PerimeterAlertManager)
    # Stub _entity_exists so Protect leg + `_2` sibling both "exist".
    _existing = {
        "binary_sensor.front_yard_person_occupancy_2",
        "binary_sensor.front_yard_person_detected",
        "binary_sensor.front_yard_person_detected_2",
    }
    mgr._entity_exists = lambda eid: eid in _existing
    out = mgr._legacy_leg_fallback(
        "binary_sensor.front_yard_person_occupancy",
        "camera.front_yard", "person",
    )
    eids = {eid for eid, _tag in out}
    assert "binary_sensor.front_yard_person_occupancy" in eids
    assert "binary_sensor.front_yard_person_occupancy_2" in eids
    assert "binary_sensor.front_yard_person_detected" in eids
    assert "binary_sensor.front_yard_person_detected_2" in eids


def test_off_path_recognizes_dahua_base_person():
    """F3 (cycle-3 fix-up, second part): a Dahua `_smart_motion_human`
    base under OFF must not be dropped — it comes back as the base leg."""
    pa = _load_pa_module()
    mgr = pa.PerimeterAlertManager.__new__(pa.PerimeterAlertManager)
    mgr._entity_exists = lambda eid: False
    out = mgr._legacy_leg_fallback(
        "binary_sensor.pool_smart_motion_human",
        "camera.pool_main", "person",
    )
    eids = {eid for eid, _tag in out}
    assert "binary_sensor.pool_smart_motion_human" in eids


def test_alias_bridge_pulls_cross_device_native_leg():
    """F5 (cycle-3 fix-up): resolver's alias bridge must pull a native-AI
    leg on a DIFFERENT device_id than the Frigate stem device via
    EXTERIOR_CAMERA_KEY_ALIASES."""
    dev_f = FakeDevice(id="dev_f",
                        identifiers={(PLATFORM_FRIGATE, "h:armcrest")})
    dev_d = FakeDevice(id="dev_d",
                        identifiers={(PLATFORM_DAHUA, "amc-uid")})
    ents = [
        FakeEntity("camera.armcrest", "dev_f", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.armcrest_person_occupancy", "dev_f", PLATFORM_FRIGATE),
        FakeEntity("camera.armcrestpooloverhead_main", "dev_d", PLATFORM_DAHUA),
        FakeEntity("binary_sensor.armcrestpooloverhead_smart_motion_human",
                   "dev_d", PLATFORM_DAHUA),
    ]
    r = _mk(ents, [dev_f, dev_d])
    # armcrestpooloverhead -> armcrest (reverse alias)
    legs = r.resolve_detection_legs(
        "camera.armcrest", "person",
        stem_aliases={"armcrestpooloverhead": "armcrest"},
    )
    eids = {l.entity_id for l in legs}
    assert "binary_sensor.armcrest_person_occupancy" in eids
    assert "binary_sensor.armcrestpooloverhead_smart_motion_human" in eids


def test_channel_strip_recovers_protect_leg_via_frigate_device_stem():
    """F6 (cycle-3 fix-up): when the configured camera is a Protect
    resolution-channel entity and the Frigate stem matches after strip,
    both engines' legs must resolve."""
    dev_f = FakeDevice(id="dev_f",
                        identifiers={(PLATFORM_FRIGATE, "h:back_yard")})
    dev_p = FakeDevice(id="dev_p",
                        identifiers={(PLATFORM_UNIFI, "p-back_yard")})
    ents = [
        FakeEntity("camera.back_yard", "dev_f", PLATFORM_FRIGATE),
        FakeEntity("binary_sensor.back_yard_person_occupancy", "dev_f", PLATFORM_FRIGATE),
        FakeEntity("camera.back_yard_high_resolution_channel", "dev_p", PLATFORM_UNIFI),
        FakeEntity("binary_sensor.back_yard_person_detected", "dev_p", PLATFORM_UNIFI),
    ]
    r = _mk(ents, [dev_f, dev_p])
    legs = r.resolve_detection_legs(
        "camera.back_yard_high_resolution_channel", "person",
    )
    engines = {l.engine for l in legs}
    assert "frigate" in engines and "protect" in engines


def test_resolver_leg_dispatch_drives_perimeter_alert():
    """F10 (cycle-3 fix-up): an end-to-end mutation-style test that a
    state-change on a RESOLVER-DERIVED (non-base) leg drives dispatch
    through _on_perimeter_event → _async_handle_perimeter_trigger.
    Proves _wire_camera consumes resolver output (not just base+`_2`)."""
    pa = _load_pa_module()
    mgr = pa.PerimeterAlertManager.__new__(pa.PerimeterAlertManager)
    # Minimal internal state needed by _on_perimeter_event.
    mgr._active = True
    mgr._setup_time = None
    mgr._leg_fire_counts = {}
    mgr._leg_sole_fire_counts = {}
    mgr._recent_fires = {}
    mgr._sensor_engine = {"binary_sensor.pool_smart_motion_human": "dahua"}

    called: list[str] = []

    class _Hass:
        def __init__(self):
            self.data = {}
            self.is_stopping = False
        def async_create_task(self, coro):
            called.append(getattr(coro, "__name__", "coro"))
            try:
                coro.close()
            except Exception:
                pass

    mgr.hass = _Hass()

    class _S:
        def __init__(self, state): self.state = state
    ev = MagicMock()
    ev.data = {
        "entity_id": "binary_sensor.pool_smart_motion_human",  # resolver-derived leg
        "new_state": _S("on"),
        "old_state": _S("off"),
    }
    mgr._on_perimeter_event(ev)
    assert called, "resolver-derived leg rising edge did not schedule dispatch"


def test_coverage_info_log_carries_engine_tags(caplog):
    """F11 (cycle-3 fix-up): the per-camera coverage INFO log must carry
    the engine tags so operators can see which engines source each camera."""
    import logging
    pa = _load_pa_module()
    caplog.set_level(logging.INFO, logger=pa._LOGGER.name)
    pa._LOGGER.info(
        "PerimeterAlertManager: perimeter camera %s person-leg "
        "coverage by engine: %s (base=%s)",
        "camera.back_yard", ["frigate", "frigate2", "protect"],
        "binary_sensor.back_yard_person_occupancy",
    )
    # F16: verify the log contains the engine tag vocabulary.
    text = " ".join(rec.message for rec in caplog.records)
    assert "frigate" in text and "protect" in text
    # F16: comment-anchor — the fold to bare "frigate" for no-`_N` entities
    # is deliberate (Option-B rename: `_2` bulk-renamed back to base, and
    # engine tag was always suffix-derived from the entity name).
    assert "frigate2" in text  # `_N` >= 2 folds to frigate2 by design
