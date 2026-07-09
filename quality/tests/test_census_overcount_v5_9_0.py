"""Tests for v5.9.0 census over-count fix (Tier 2-DB, D-A + D-B + D-D + B-C1).

Per Review C: THESE TESTS DRIVE REAL PRODUCTION CODE. No hand-copied stubs.

Covered surfaces:
- ``PersonCensus._dedup_by_area`` — the shared same-area max helper
  (D-A + B-C1).
- ``PersonCensus._get_unrecognized_camera_count`` — the enhanced-census
  path's unrecognized count (B-C1: must route through the shared dedup
  so the enhanced overwrite doesn't re-inflate).
- ``PersonCensus._apply_hold_decay`` — sustain-before-latch (D-B) with
  house-only application (B-M1 property exemption).
- Constants pinned from ``const`` (D-C default = 3 min interior hold).
- ``AutoRecoverySwitch`` display name (v5.8.0 sibling assertion).

Mutation anchors (Review C): each load-bearing production site can be
mutated (edit the source, run the file, observe a specific named test
failing, restore). The tests below are the named tests referenced by
each mutation site — see the module docstring in ``camera_census.py``.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401 — bootstraps HA module stubs.
from _provenance_harness import make_hass

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation.camera_census import (
    CameraInfo,
    PersonCensus,
)


# ============================================================================
# Helpers — build a minimal PersonCensus wired to a stubbed camera manager.
# ============================================================================


class _StubCameraManager:
    """Minimal stand-in for CameraIntegrationManager.

    Only implements the two attributes / methods PersonCensus reads on
    the census hot path we exercise here:
      * ``_camera_by_entity``  — entity_id -> CameraInfo
      * ``get_platform_for_camera(entity_id)`` -> platform str
    """

    def __init__(self, cameras: dict[str, CameraInfo]):
        self._camera_by_entity = cameras

    def get_platform_for_camera(self, entity_id: str) -> str | None:
        info = self._camera_by_entity.get(entity_id)
        return info.platform if info else None

    def get_all_frigate_cameras(self) -> list[CameraInfo]:
        return [
            c for c in self._camera_by_entity.values()
            if c.platform == ura_const.CAMERA_PLATFORM_FRIGATE
        ]

    def resolve_configured_cameras(
        self, camera_entity_ids: list[str],
    ) -> list[CameraInfo]:
        """Return the CameraInfo entries whose entity_id is in the list.

        The real method resolves camera.* IDs to their person detection
        binary_sensor entities via the entity registry; in tests we skip
        that layer and pass the binary_sensor entity_ids directly.
        """
        out: list[CameraInfo] = []
        for eid in camera_entity_ids:
            info = self._camera_by_entity.get(eid)
            if info is not None:
                out.append(info)
        return out


def _make_person_count_state(count: int) -> MagicMock:
    """Return a MockState-like object matching what hass.states.get returns
    for a Frigate person_count sensor.
    """
    st = MagicMock()
    st.state = str(count)
    return st


def _make_face_state(
    value: str,
    last_changed: Optional[datetime] = None,
) -> MagicMock:
    st = MagicMock()
    st.state = value
    st.last_changed = last_changed
    return st


def _make_census(
    cameras: dict[str, CameraInfo],
    states: dict[str, MagicMock] | None = None,
    enhanced_census: bool = True,
) -> PersonCensus:
    """Build a PersonCensus that reads from ``states`` and ``cameras``.

    ``enhanced_census`` seeds an integration ConfigEntry with the given
    CONF_ENHANCED_CENSUS value so ``_is_enhanced_census_enabled()`` on
    the real code returns the requested boolean.

    The census's ``_get_interior_camera_entities()`` reads the
    integration config entry's ``CONF_CAMERA_PERSON_ENTITIES`` — we set
    that to the keys of ``cameras`` here so the real code iterates them.
    """
    hass = make_hass()
    states = states or {}
    hass.states.get = lambda entity_id: states.get(entity_id)

    entry = MagicMock()
    entry.data = {
        ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION,
    }
    entry.options = {
        ura_const.CONF_CAMERA_PERSON_ENTITIES: list(cameras.keys()),
        ura_const.CONF_ENHANCED_CENSUS: enhanced_census,
    }
    hass.config_entries.async_entries.return_value = [entry]

    mgr = _StubCameraManager(cameras)
    census = PersonCensus(hass, mgr)  # type: ignore[arg-type]
    return census


# ============================================================================
# D-C: constant pinning
# ============================================================================


def test_default_census_hold_interior_minutes_is_three() -> None:
    """D-C shipped default: 3 minutes for the interior census hold."""
    assert ura_const.DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES == 3


def test_census_peak_sustain_seconds_is_positive() -> None:
    """D-B constant must be set (nonzero) to make the gate load-bearing."""
    assert ura_const.CENSUS_PEAK_SUSTAIN_SECONDS > 0


# ============================================================================
# D-A: shared _dedup_by_area helper (drives the real staticmethod).
# ============================================================================


def test_dedup_by_area_same_area_takes_max() -> None:
    """Two contributions in the same area -> area contributes max."""
    total = PersonCensus._dedup_by_area([("kitchen", 1), ("kitchen", 1)])
    assert total == 1


def test_dedup_by_area_cross_area_sums() -> None:
    """Two contributions in different areas -> sum."""
    total = PersonCensus._dedup_by_area([("kitchen", 1), ("lounge", 1)])
    assert total == 2


def test_dedup_by_area_null_area_id_contributes_individually() -> None:
    """Null area_id -> contribute individually (sum, no dedup)."""
    total = PersonCensus._dedup_by_area([(None, 1), (None, 1)])
    assert total == 2


def test_dedup_by_area_same_area_uses_higher_count() -> None:
    """Max within an area picks the LARGER contribution."""
    total = PersonCensus._dedup_by_area([("great_room", 1), ("great_room", 2)])
    assert total == 2


def test_dedup_by_area_ignores_nonpositive() -> None:
    """Zero / negative contributions must not count."""
    total = PersonCensus._dedup_by_area([("kitchen", 0), ("kitchen", 1)])
    assert total == 1


# ============================================================================
# B-C1: _get_unrecognized_camera_count MUST route through _dedup_by_area
#       when the enhanced census path is enabled (the shipping config).
# ============================================================================


def _make_frigate_camera(
    stem: str,
    area_id: Optional[str],
) -> tuple[CameraInfo, str, str]:
    """Return (CameraInfo, person_count_sensor_id, face_sensor_id)."""
    bs = f"binary_sensor.{stem}_person_occupancy"
    pc = f"sensor.{stem}_person_count"
    face = f"sensor.{stem}_last_recognized_face"
    info = CameraInfo(
        entity_id=bs,
        platform=ura_const.CAMERA_PLATFORM_FRIGATE,
        area_id=area_id,
        person_binary_sensor=bs,
        person_count_sensor=pc,
    )
    return info, pc, face


def test_unrecognized_count_dedupes_same_area_cameras() -> None:
    """B-C1: two Frigate cameras in the same area each reporting count=1
    with unrecognized faces must contribute 1 to the unrecognized total —
    NOT 2. This is the path _apply_enhanced_house_census actually uses.
    """
    info_a, pc_a, face_a = _make_frigate_camera("cam_a", "kitchen")
    info_b, pc_b, face_b = _make_frigate_camera("cam_b", "kitchen")
    cameras = {info_a.entity_id: info_a, info_b.entity_id: info_b}
    states = {
        pc_a: _make_person_count_state(1),
        pc_b: _make_person_count_state(1),
        face_a: _make_face_state("unknown"),
        face_b: _make_face_state("unknown"),
    }
    census = _make_census(cameras, states)
    # Sanity: enhanced census is enabled — the shipping config.
    assert census._is_enhanced_census_enabled() is True
    assert census._get_unrecognized_camera_count() == 1


def test_unrecognized_count_sums_across_areas() -> None:
    """Two Frigate cameras in DIFFERENT areas each with count=1 and
    unrecognized faces -> unrecognized total = 2 (cross-area sum).
    """
    info_a, pc_a, face_a = _make_frigate_camera("cam_a", "kitchen")
    info_b, pc_b, face_b = _make_frigate_camera("cam_b", "lounge")
    cameras = {info_a.entity_id: info_a, info_b.entity_id: info_b}
    states = {
        pc_a: _make_person_count_state(1),
        pc_b: _make_person_count_state(1),
        face_a: _make_face_state("unknown"),
        face_b: _make_face_state("unknown"),
    }
    census = _make_census(cameras, states)
    assert census._get_unrecognized_camera_count() == 2


def test_unrecognized_count_missing_area_id_contributes_individually() -> None:
    """Cameras with area_id=None fall back to individual contribution."""
    info_a, pc_a, face_a = _make_frigate_camera("cam_a", None)
    info_b, pc_b, face_b = _make_frigate_camera("cam_b", None)
    cameras = {info_a.entity_id: info_a, info_b.entity_id: info_b}
    states = {
        pc_a: _make_person_count_state(1),
        pc_b: _make_person_count_state(1),
        face_a: _make_face_state("unknown"),
        face_b: _make_face_state("unknown"),
    }
    census = _make_census(cameras, states)
    assert census._get_unrecognized_camera_count() == 2


# ============================================================================
# D-A path: _calculate_house_census also routes through _dedup_by_area.
# ============================================================================


def test_house_census_same_area_dedup_via_calculate_house_census() -> None:
    """Two Frigate cameras same-area count=1 -> _calculate_house_census
    yields camera_total = 1 (via _dedup_by_area).
    """
    import asyncio
    info_a, pc_a, _face_a = _make_frigate_camera("cam_a", "kitchen")
    info_b, pc_b, _face_b = _make_frigate_camera("cam_b", "kitchen")
    cameras = {info_a.entity_id: info_a, info_b.entity_id: info_b}
    states = {
        pc_a: _make_person_count_state(1),
        pc_b: _make_person_count_state(1),
    }
    census = _make_census(cameras, states)
    result = asyncio.get_event_loop().run_until_complete(
        census._calculate_house_census(ble_persons=[], now=datetime.utcnow()),
    )
    # frigate_count is the deduped total (both cameras report 1 in the
    # same area -> 1). This is the invariant B-C1 must preserve on the
    # raw-count path.
    assert result.frigate_count == 1


# ============================================================================
# D-B: sustain-before-latch drives REAL _apply_hold_decay.
# ============================================================================


def _fresh_census() -> PersonCensus:
    """Build a PersonCensus with no state — for direct _apply_hold_decay
    calls (state stores are on the instance).
    """
    return _make_census({}, {})


def test_apply_hold_decay_first_observation_latches_immediately() -> None:
    """First observation: no prior peak to protect -> latch fresh_count."""
    census = _fresh_census()
    t0 = datetime(2026, 7, 8, 12, 0, 0)
    held, _peak_held, _age = census._apply_hold_decay(1, "house", t0)
    assert held == 1


def test_apply_hold_decay_transient_spike_does_not_latch_peak() -> None:
    """D-B: fresh=1 baseline, then fresh=2 for < sustain window, then
    fresh=1. Peak MUST NOT latch 2.
    """
    census = _fresh_census()
    t0 = datetime(2026, 7, 8, 12, 0, 0)
    census._apply_hold_decay(1, "house", t0)
    t1 = t0 + timedelta(seconds=60)
    held, _, _ = census._apply_hold_decay(2, "house", t1)
    assert held == 1, "transient spike must not bypass sustain gate"
    t2 = t1 + timedelta(seconds=5)
    held, _, _ = census._apply_hold_decay(2, "house", t2)
    assert held == 1
    # Dip clears pending.
    t3 = t2 + timedelta(seconds=1)
    held, _, _ = census._apply_hold_decay(1, "house", t3)
    assert held == 1


def test_apply_hold_decay_sustained_increase_latches_peak() -> None:
    """D-B: fresh=2 sustained past CENSUS_PEAK_SUSTAIN_SECONDS -> peak=2."""
    census = _fresh_census()
    t0 = datetime(2026, 7, 8, 12, 0, 0)
    census._apply_hold_decay(1, "house", t0)
    t1 = t0 + timedelta(seconds=60)
    census._apply_hold_decay(2, "house", t1)  # pending starts
    t2 = t1 + timedelta(
        seconds=ura_const.CENSUS_PEAK_SUSTAIN_SECONDS + 5,
    )
    held, _, _ = census._apply_hold_decay(2, "house", t2)
    assert held == 2, "sustained fresh=2 must latch after sustain window"


def test_apply_hold_decay_pending_reset_by_dip() -> None:
    """A pending latch that is undercut by a dip must be cleared."""
    census = _fresh_census()
    t0 = datetime(2026, 7, 8, 12, 0, 0)
    census._apply_hold_decay(1, "house", t0)
    t1 = t0 + timedelta(seconds=60)
    census._apply_hold_decay(2, "house", t1)
    t2 = t1 + timedelta(seconds=10)
    census._apply_hold_decay(2, "house", t2)
    # Dip: pending must clear.
    t3 = t2 + timedelta(seconds=1)
    census._apply_hold_decay(1, "house", t3)
    assert census._pending_house_peak_since is None


# ============================================================================
# B-M1: property zone is EXEMPT from the sustain gate — instant rise.
# ============================================================================


def test_apply_hold_decay_property_zone_latches_instantly() -> None:
    """B-M1: property zone bypasses the sustain gate; upward moves latch
    on the FIRST observation, matching pre-v5.9.0 exterior semantics.
    """
    census = _fresh_census()
    t0 = datetime(2026, 7, 8, 12, 0, 0)
    census._apply_hold_decay(0, "property", t0)
    t1 = t0 + timedelta(seconds=1)  # well under 15s sustain
    held, _, _ = census._apply_hold_decay(1, "property", t1)
    assert held == 1, (
        "property zone must NOT delay upward moves via the sustain gate"
    )
    # And a further rise: still instant.
    t2 = t1 + timedelta(seconds=1)
    held, _, _ = census._apply_hold_decay(2, "property", t2)
    assert held == 2


# ============================================================================
# AutoRecoverySwitch display name (v5.8.0 sibling assertion, kept in this
# cycle per operator instruction).
# ============================================================================


def test_auto_recovery_switch_display_name() -> None:
    """AutoRecoverySwitch names its entity 'Device Auto Recovery'.

    switch.py pulls in ~30 HA modules the census harness doesn't stub;
    rather than stand up the whole platform surface we read the REAL
    production source file directly and assert that the AutoRecoverySwitch
    ``__init__`` passes the display name literal to its base. This is
    still driving real code (the file that HA loads) and will fail if a
    future cycle renames the entity.
    """
    import os
    src_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..",
        "custom_components", "universal_room_automation", "switch.py",
    )
    with open(src_path, "r", encoding="utf-8") as fh:
        source = fh.read()
    # Locate the class body and check its constructor line.
    class_marker = "class AutoRecoverySwitch("
    assert class_marker in source, "AutoRecoverySwitch class missing"
    idx = source.index(class_marker)
    tail = source[idx:idx + 4000]
    assert (
        'super().__init__(coordinator, "auto_recovery", "Device Auto Recovery")'
        in tail
    ), (
        "AutoRecoverySwitch display name must remain 'Device Auto Recovery' "
        "(v5.8.0 reconcile-on-return switch)"
    )
