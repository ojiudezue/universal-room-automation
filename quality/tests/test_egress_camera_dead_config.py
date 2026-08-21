"""Tests for EGRESS-CAMERA-DEAD-CONFIG-1.

Covers:
- Part A: aggregate warn-once — an unresolved configured camera logs WARNING
  exactly once across repeated resolve calls (no per-tick log storm).
- Part B: diagnostic surface — `get_unresolved_configured_cameras()` reports
  the offender and the URAPersonsInHouseSensor attribute reflects it.
- Part C non-goal: NO automatic `_N`-suffix substitution — an absent
  `camera.foo` with a live `camera.foo_2` present resolves to NOTHING.
- Wire-in anchor: removing the diagnostic call site from the sensor
  extra_state_attributes fails this test (mutation drill target).
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

# Stubs needed to import sensor.py under the harness (mirrors
# test_guest_count_dedup_migrate.py preamble).
import sys as _sys
import types as _types
if "homeassistant.helpers.restore_state" not in _sys.modules:
    _rs = _types.ModuleType("homeassistant.helpers.restore_state")
    class _RestoreEntity:  # noqa: D401
        """Stub RestoreEntity."""
    _rs.RestoreEntity = _RestoreEntity
    _sys.modules["homeassistant.helpers.restore_state"] = _rs
import homeassistant.helpers.update_coordinator as _uc  # type: ignore
if not hasattr(_uc, "CoordinatorEntity"):
    class _CoordinatorEntityMeta(type):
        def __getitem__(cls, item):
            return cls
    class _CoordinatorEntity(metaclass=_CoordinatorEntityMeta):  # noqa: D401
        def __init__(self, *a, **kw):
            pass
    _uc.CoordinatorEntity = _CoordinatorEntity
if not hasattr(_uc, "DataUpdateCoordinator"):
    _uc.DataUpdateCoordinator = type("DataUpdateCoordinator", (), {})
if not hasattr(_uc, "UpdateFailed"):
    _uc.UpdateFailed = Exception

from custom_components.universal_room_automation.camera_census import (
    CameraIntegrationManager,
)


@pytest.fixture(autouse=True)
def _restore_entity_registry_module():
    import homeassistant.helpers.entity_registry as er_mod
    sentinel = object()
    saved = {
        name: getattr(er_mod, name, sentinel)
        for name in ("async_get", "async_entries_for_platform")
    }
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is sentinel:
                if hasattr(er_mod, name):
                    delattr(er_mod, name)
            else:
                setattr(er_mod, name, value)


def _install_registry(entities: dict[str, object]) -> None:
    """Stub entity_registry.async_get(hass).async_get(entity_id).

    `entities` maps entity_id -> registry entry (or None for absent).
    """
    import homeassistant.helpers.entity_registry as er_mod

    class _Reg:
        def async_get(self, entity_id):
            return entities.get(entity_id)

    er_mod.async_get = lambda _hass: _Reg()


def _make_manager() -> CameraIntegrationManager:
    hass = make_hass()
    # Silence lazy-listener registration path — bus.async_listen returns unsub.
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=lambda: None)
    return CameraIntegrationManager(hass)


def test_part_a_warn_once_per_entity_no_storm(caplog):
    """Absent configured camera logs WARNING exactly once across many resolve
    calls (Part A — no per-tick log storm)."""
    _install_registry({})  # camera.garage_a absent
    mgr = _make_manager()

    caplog.set_level(logging.WARNING, logger="custom_components.universal_room_automation.camera_census")

    for _ in range(50):
        mgr.resolve_configured_cameras(["camera.garage_a"])

    warns = [r for r in caplog.records if "camera.garage_a" in r.getMessage() and r.levelno == logging.WARNING]
    assert len(warns) == 1, f"expected exactly one WARNING, got {len(warns)}"


def test_part_b_diagnostic_surface_lists_unresolved():
    """Part B: unresolved configured cameras are readable via public accessor."""
    _install_registry({})
    mgr = _make_manager()
    mgr.record_unresolved_for_scope(
        "egress_cameras", ["camera.garage_a", "camera.garage_b"]
    )
    mgr.resolve_configured_cameras(["camera.garage_a", "camera.garage_b"])
    unresolved = mgr.get_unresolved_configured_cameras()
    assert set(unresolved.keys()) == {"camera.garage_a", "camera.garage_b"}
    assert all(v == "not_in_registry" for v in unresolved.values())


def test_removal_from_config_self_corrects():
    """DEFECT FIX: an entity dropped from the stored list must NOT linger in
    the diagnostic. Resolve once with a missing entity — appears; resolve
    the SAME scope with that entity removed — gone. This is the exact
    operator apply-flow (swap camera.garage_a -> camera.garage_a_2).
    """
    live_entry = SimpleNamespace(device_id="dev_ok")
    entities = {"camera.garage_a_2": live_entry}
    _install_registry(entities)
    mgr = _make_manager()
    mgr._resolved_devices["dev_ok"] = [object()]

    # First pass — pre-fix state: bare name configured, absent.
    mgr.record_unresolved_for_scope(
        "egress_cameras", ["camera.garage_a", "camera.garage_a_2"]
    )
    assert "camera.garage_a" in mgr.get_unresolved_configured_cameras()

    # Second pass — operator repointed the list to the _2 name only.
    mgr.record_unresolved_for_scope("egress_cameras", ["camera.garage_a_2"])
    unresolved = mgr.get_unresolved_configured_cameras()
    assert "camera.garage_a" not in unresolved, (
        "removed-from-config entity must not linger; got " + repr(unresolved)
    )
    assert unresolved == {}


def test_scopes_do_not_clobber_each_other():
    """Per-scope snapshots: an unresolved entity in list A survives a
    resolve pass over list B. Fails on any single-flat-dict design that
    clears everything on entry.
    """
    _install_registry({})  # both cameras absent
    mgr = _make_manager()

    mgr.record_unresolved_for_scope("egress_cameras", ["camera.only_in_a"])
    assert "camera.only_in_a" in mgr.get_unresolved_configured_cameras()

    # A resolve over a DIFFERENT scope must not disturb A's finding.
    mgr.record_unresolved_for_scope("perimeter_cameras", ["camera.only_in_b"])
    both = mgr.get_unresolved_configured_cameras()
    assert "camera.only_in_a" in both, "scope B call clobbered scope A finding"
    assert "camera.only_in_b" in both


def test_part_c_no_automatic_suffix_substitution():
    """Part C non-goal: absent `camera.foo` with live `camera.foo_2` present
    MUST resolve to NOTHING (not substitute _2). Guard against future
    well-meaning 'improvement'."""
    live_entry = SimpleNamespace(device_id="dev_xyz")
    _install_registry({
        # Only the _2 sibling exists; the bare-named one is absent.
        "camera.foo_2": live_entry,
    })
    mgr = _make_manager()
    # Short-circuit device-resolution so we only test the missing-entity gate.
    mgr._resolved_devices["dev_xyz"] = [object()]

    result = mgr.resolve_configured_cameras(["camera.foo"])
    assert result == [], "resolver must NOT substitute the _2 sibling"
    mgr.record_unresolved_for_scope("camera_person_entities", ["camera.foo"])
    assert "camera.foo" in mgr.get_unresolved_configured_cameras()
    # And explicitly: the _2 sibling was not silently pulled in.
    assert "camera.foo_2" not in mgr.get_unresolved_configured_cameras()


def test_part_a_re_warns_once_after_registry_reset(caplog):
    """After the registry-invalidation hook clears `_unresolved_warned` (the
    effect of EVENT_ENTITY_REGISTRY_UPDATED), a subsequent burst emits
    exactly one WARNING again — never per-tick."""
    _install_registry({})
    mgr = _make_manager()
    caplog.set_level(logging.WARNING, logger="custom_components.universal_room_automation.camera_census")

    for _ in range(10):
        mgr.resolve_configured_cameras(["camera.garage_a"])
    first_warns = [r for r in caplog.records if "camera.garage_a" in r.getMessage()]
    assert len(first_warns) == 1

    # Simulate the invalidator firing (registry changed).
    mgr._unresolved_warned.clear()
    caplog.clear()

    for _ in range(10):
        mgr.resolve_configured_cameras(["camera.garage_a"])
    second_warns = [r for r in caplog.records if "camera.garage_a" in r.getMessage()]
    assert len(second_warns) == 1


def test_wire_in_anchor_get_integration_camera_list_calls_recorder():
    """CALL-SITE wire-in: PersonCensus._get_integration_camera_list must
    invoke ``record_unresolved_for_scope`` on the manager for the conf_key
    it is reading. Neuter that call site (guard flipped to False) and this
    test fails — proving the recorder isn't dead-called via the helper only.
    """
    from custom_components.universal_room_automation.camera_census import (
        PersonCensus,
    )
    from custom_components.universal_room_automation import const as ura_const

    calls: list[tuple[str, list[str]]] = []

    class _CaptureMgr:
        def resolve_configured_cameras(self, entity_ids):
            return []
        def record_unresolved_for_scope(self, scope, entity_ids):
            calls.append((scope, list(entity_ids)))

    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION,
                  ura_const.CONF_EGRESS_CAMERAS: ["camera.garage_a", "camera.garage_b"]}
    entry.options = {}

    hass = make_hass()
    hass.config_entries.async_entries.return_value = [entry]

    census = PersonCensus.__new__(PersonCensus)
    census.hass = hass
    census._camera_manager = _CaptureMgr()

    census._get_integration_camera_list(ura_const.CONF_EGRESS_CAMERAS)

    assert calls, (
        "recorder never invoked — _get_integration_camera_list must call "
        "record_unresolved_for_scope"
    )
    assert calls[0][0] == ura_const.CONF_EGRESS_CAMERAS
    assert calls[0][1] == ["camera.garage_a", "camera.garage_b"]


def test_wire_in_anchor_sensor_publishes_unresolved_attribute():
    """Wire-in anchor for Part B: URAPersonsInHouseSensor.extra_state_attributes
    MUST include 'unresolved_configured_cameras' and
    'unresolved_configured_cameras_count'. Removing the call site (or the
    manager accessor) fails this test — it is the guard against a silent
    de-wire.
    """
    from custom_components.universal_room_automation.const import DOMAIN
    from custom_components.universal_room_automation import sensor as sensor_mod

    # Minimal fake census + result skeleton.
    house = SimpleNamespace(
        total_persons=0, identified_count=0, unidentified_count=0,
        confidence="none", source_agreement="single",
        frigate_count=0, unifi_count=0, degraded_mode=False,
        active_platforms=[], enhanced_census=False,
    )
    result = SimpleNamespace(house=house, timestamp=None)

    class _CamMgr:
        def get_unresolved_configured_cameras(self):
            return {"camera.garage_a": "not_in_registry",
                    "camera.garage_b": "not_in_registry"}

    class _Census:
        last_result = result
        _camera_manager = _CamMgr()
        def get_stuck_cameras(self):
            return []
        def get_pending_peak_info(self, *_a, **_k):
            return None
        _last_area_contributions = {}
        _last_enhanced_area_contributions = None
        _last_area_raw_max_pre_cancel = {}
        _last_ble_by_area = {}
        _last_ble_cancel_enabled = False
        _last_camera_total_pre_cancel = 0
        _last_raw_pre_dedup_sum = 0
        _last_count_as_of = None
        _peak_refresh_suppressed_count = 0

    hass = make_hass()
    hass.data = {DOMAIN: {"census": _Census()}}

    entry = MagicMock()
    entry.entry_id = "e1"
    entry.data = {}
    entry.options = {}

    s = sensor_mod.URAPersonsInHouseSensor.__new__(sensor_mod.URAPersonsInHouseSensor)
    s.hass = hass
    s._entry = entry

    attrs = sensor_mod.URAPersonsInHouseSensor.extra_state_attributes.fget(s)
    assert "unresolved_configured_cameras" in attrs
    assert "unresolved_configured_cameras_count" in attrs
    assert attrs["unresolved_configured_cameras_count"] == 2
    assert set(attrs["unresolved_configured_cameras"]) == {
        "camera.garage_a", "camera.garage_b",
    }
