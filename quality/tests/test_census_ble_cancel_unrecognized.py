"""Cycle ``census_ble_cancel_unrecognized`` — area-correlated BLE subtraction.

These tests DRIVE the REAL production ``PersonCensus`` (Bug Class #60: never
re-implement production logic in tests). They exercise the
``_get_unrecognized_camera_count`` path plus the ``_ble_home_by_area`` helper
against the 8-row multi-person matrix from
PLANNING_census_ble_cancel_unrecognized.md §4.1.

Mutation anchors — each of these production sites, when neutered, MUST turn
at least one NAMED test in this file red (run manually per cycle protocol):

  M1. ``_get_unrecognized_camera_count``: neuter ``correction`` (e.g.
      ``correction = min(...) * 0``). Expected red: 9 tests including
      ``test_row1_resident_alone_face_missed``, ``test_row3_resident_plus_guest``,
      ``test_ble_cancelled_count_diagnostic_populated``.
  M2. ``_ble_home_by_area``: replace body with ``return {}``. Expected red:
      13 tests including the four helper unit tests and every matrix row
      whose ``ble_here > 0``.
  M3. Remove the area correlation in ``_get_unrecognized_camera_count``
      (change ``ble_remaining.get(area_id, 0)`` to
      ``sum(ble_remaining.values())``). Expected red:
      ``test_row7_pure_guest_still_detected``,
      ``test_ble_cancelled_count_zero_when_no_correlation``.
  M4. Remove the LOST/away guard in ``_ble_home_by_area``. Expected red:
      ``test_lost_person_does_not_cancel``.

Test-file module hygiene: uses ``sys.modules.setdefault`` (composition-safe;
does NOT clobber sibling test files' HA-module stubs). Piggybacks on the
``_provenance_harness`` bootstrap already used by
``test_census_overcount_v5_9_0.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401 — bootstraps HA module stubs (setdefault-safe).
from _provenance_harness import make_hass

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation import camera_census as _cc_mod
from custom_components.universal_room_automation.camera_census import (
    CameraInfo,
    PersonCensus,
)


# The provenance-harness stubs ``dt_util.utcnow`` as ``datetime.utcnow``
# which returns a NAIVE datetime — production uses a tz-aware UTC clock.
# The freshness compare in ``_get_unrecognized_camera_count`` mixes naive
# ``now`` with aware ``last_changed`` and raises TypeError, silently
# forcing face_is_fresh=False for tests trying to exercise the fresh
# path. Overwrite the module-level ``dt_util`` reference so the whole
# freshness path behaves as production does. Scoped to this file; no
# effect on sibling test files.
class _TzUtil:
    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def as_local(dt: datetime) -> datetime:
        return dt

    UTC = timezone.utc


_cc_mod.dt_util = _TzUtil()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Stub camera manager — the minimal subset the census hot path reads.
# ---------------------------------------------------------------------------


class _StubCameraManager:
    def __init__(self, cameras: dict[str, CameraInfo]) -> None:
        self._camera_by_entity = cameras

    def get_platform_for_camera(self, entity_id: str) -> Optional[str]:
        info = self._camera_by_entity.get(entity_id)
        return info.platform if info else None

    def get_all_frigate_cameras(self) -> list[CameraInfo]:
        return [
            c
            for c in self._camera_by_entity.values()
            if c.platform == ura_const.CAMERA_PLATFORM_FRIGATE
        ]

    def resolve_configured_cameras(
        self, camera_entity_ids: list[str],
    ) -> list[CameraInfo]:
        out: list[CameraInfo] = []
        for eid in camera_entity_ids:
            info = self._camera_by_entity.get(eid)
            if info is not None:
                out.append(info)
        return out


# ---------------------------------------------------------------------------
# Person coordinator stub — mirrors the two attributes the helper reads:
#   - ``data``: {person_id: {"location": <room_slug_or_sentinel>}}
#   - ``_area_id_to_room``: {area_id: room_name}
# ---------------------------------------------------------------------------


class _StubPersonCoordinator:
    def __init__(
        self,
        person_data: dict[str, dict[str, str]],
        area_to_room: dict[str, str],
    ) -> None:
        self.data = person_data
        self._area_id_to_room = area_to_room


def _make_person_count_state(count: int) -> MagicMock:
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


def _make_frigate_camera(stem: str, area_id: Optional[str]):
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


def _make_census(
    cameras: dict[str, CameraInfo],
    states: dict[str, MagicMock],
    person_coordinator: Optional[_StubPersonCoordinator] = None,
) -> PersonCensus:
    """Real ``PersonCensus`` wired to stubbed hass / camera_manager / person_coord.

    The census's ``_get_interior_camera_entities()`` reads
    ``CONF_CAMERA_PERSON_ENTITIES`` from the integration config entry —
    seed it with our camera keys so the real loop iterates them.
    """
    hass = make_hass()
    hass.states.get = lambda entity_id: states.get(entity_id)

    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        ura_const.CONF_CAMERA_PERSON_ENTITIES: list(cameras.keys()),
        ura_const.CONF_ENHANCED_CENSUS: True,
    }
    hass.config_entries.async_entries.return_value = [entry]

    # Wire the person coordinator into ``hass.data[DOMAIN]``.
    domain_bucket: dict = {}
    if person_coordinator is not None:
        domain_bucket["person_coordinator"] = person_coordinator
    try:
        hass.data[ura_const.DOMAIN] = domain_bucket
    except Exception:  # pragma: no cover — defensive against MagicMock hass.data
        hass.data = {ura_const.DOMAIN: domain_bucket}

    mgr = _StubCameraManager(cameras)
    census = PersonCensus(hass, mgr)  # type: ignore[arg-type]
    return census


# ===========================================================================
# _ble_home_by_area helper — unit-level
# ===========================================================================


def test_ble_home_by_area_returns_empty_when_no_person_coordinator() -> None:
    """Graceful degradation (I3) — no person_coordinator wired → ``{}``."""
    info, pc, face = _make_frigate_camera("cam", "kitchen")
    census = _make_census({info.entity_id: info}, {}, person_coordinator=None)
    assert census._ble_home_by_area() == {}


def test_ble_home_by_area_returns_empty_when_person_coordinator_has_no_data() -> None:
    """No tracked persons → ``{}`` (I3 graceful)."""
    info, _pc, _face = _make_frigate_camera("cam", "kitchen")
    pc_stub = _StubPersonCoordinator(person_data={}, area_to_room={"a1": "kitchen"})
    census = _make_census({info.entity_id: info}, {}, person_coordinator=pc_stub)
    assert census._ble_home_by_area() == {}


def test_ble_home_by_area_maps_room_to_area() -> None:
    """Resident located in room ``kitchen`` → area_id ``a1`` count 1."""
    info, _pc, _face = _make_frigate_camera("cam", "a1")
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": {"location": "kitchen"}},
        area_to_room={"a1": "kitchen"},
    )
    census = _make_census({info.entity_id: info}, {}, person_coordinator=pc_stub)
    assert census._ble_home_by_area() == {"a1": 1}


def test_ble_home_by_area_multiple_residents_same_room_stack() -> None:
    pc_stub = _StubPersonCoordinator(
        person_data={
            "oji": {"location": "kitchen"},
            "grace": {"location": "kitchen"},
        },
        area_to_room={"a1": "kitchen"},
    )
    info, _pc, _face = _make_frigate_camera("cam", "a1")
    census = _make_census({info.entity_id: info}, {}, person_coordinator=pc_stub)
    assert census._ble_home_by_area() == {"a1": 2}


def test_lost_person_does_not_cancel() -> None:
    """Mutation anchor M4: LOST/away residents excluded from the map."""
    pc_stub = _StubPersonCoordinator(
        person_data={
            "away_dude": {"location": "away"},
            "lost_dude": {"location": "unknown"},
            "home_but_unresolved": {"location": "home"},
            "real_room_dude": {"location": "kitchen"},
        },
        area_to_room={"a1": "kitchen"},
    )
    info, _pc, _face = _make_frigate_camera("cam", "a1")
    census = _make_census({info.entity_id: info}, {}, person_coordinator=pc_stub)
    # Only the real_room_dude counts.
    assert census._ble_home_by_area() == {"a1": 1}


def test_ble_home_by_area_unresolved_room_buckets_under_none() -> None:
    """Room slug that doesn't map to any area → key ``None``. That bucket
    cannot cancel any real interior camera (whose area_id is non-None)."""
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": {"location": "attic"}},  # attic not in area map
        area_to_room={"a1": "kitchen"},
    )
    info, _pc, _face = _make_frigate_camera("cam", "a1")
    census = _make_census({info.entity_id: info}, {}, person_coordinator=pc_stub)
    assert census._ble_home_by_area() == {None: 1}


# ===========================================================================
# 8-row matrix — parametrized against the real _get_unrecognized_camera_count
# ===========================================================================


def _fresh() -> datetime:
    # Freshness compare in production uses ``dt_util.utcnow()`` (tz-aware
    # UTC). Match tz-awareness so ``(now - last_changed).total_seconds()``
    # succeeds; otherwise the code falls into the exception branch and
    # treats the face as stale.
    return datetime.now(timezone.utc) - timedelta(seconds=30)


# Matrix rows from PLANNING §4.1:
#   (pc, fresh_face, ble_here, expected_unrecognized_total, label)
MATRIX = [
    (1, 0, 1, 0, "row1_resident_alone_face_missed"),
    (1, 1, 1, 0, "row2_resident_face_matched"),
    (2, 0, 1, 1, "row3_resident_plus_guest"),
    (2, 1, 1, 0, "row4_double_cover_known_limitation"),
    (2, 0, 2, 0, "row5_two_residents_no_face"),
    (3, 0, 1, 2, "row6_one_resident_two_guests"),
    (1, 0, 0, 1, "row7_pure_guest_still_detected"),
    (0, 0, 3, 0, "row8_no_detection_no_contribution"),
]


@pytest.mark.parametrize(
    "pc, fresh_face, ble_here, expected, label",
    MATRIX,
    ids=[row[4] for row in MATRIX],
)
def test_matrix(pc: int, fresh_face: int, ble_here: int, expected: int, label: str) -> None:
    """Drive the REAL ``_get_unrecognized_camera_count`` per matrix row."""
    info, pc_sensor, face_sensor = _make_frigate_camera("cam_a", "a1")
    cameras = {info.entity_id: info}
    states: dict[str, MagicMock] = {}
    if pc > 0:
        states[pc_sensor] = _make_person_count_state(pc)
        if fresh_face:
            states[face_sensor] = _make_face_state("oji_udezue", last_changed=_fresh())
        else:
            states[face_sensor] = _make_face_state("unknown")

    person_data = {
        f"resident_{i}": {"location": "kitchen"} for i in range(ble_here)
    }
    pc_stub = _StubPersonCoordinator(
        person_data=person_data,
        area_to_room={"a1": "kitchen"},
    )
    census = _make_census(cameras, states, person_coordinator=pc_stub)

    result = census._get_unrecognized_camera_count()
    assert result == expected, (
        f"[{label}] pc={pc} fresh_face={fresh_face} ble_here={ble_here} "
        f"expected={expected} got={result}"
    )


# Explicit named tests for the mutation table.


def test_row1_resident_alone_face_missed() -> None:
    """Mutation anchors M1, M2: removing correction OR the helper yields 1
    instead of 0 here (was pre-cycle FP, now cancelled)."""
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(1), face: _make_face_state("unknown")}
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": {"location": "kitchen"}},
        area_to_room={"a1": "kitchen"},
    )
    census = _make_census({info.entity_id: info}, states, person_coordinator=pc_stub)
    assert census._get_unrecognized_camera_count() == 0


def test_row3_resident_plus_guest() -> None:
    """Guest survives cancellation; 1 resident cancels 1 slot, 1 unidentified
    remains (I2 completeness)."""
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(2), face: _make_face_state("unknown")}
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": {"location": "kitchen"}},
        area_to_room={"a1": "kitchen"},
    )
    census = _make_census({info.entity_id: info}, states, person_coordinator=pc_stub)
    assert census._get_unrecognized_camera_count() == 1


def test_row7_pure_guest_still_detected() -> None:
    """I1 soundness + M3 anchor: no resident in the area — guest MUST count.
    A global-sum mutation would spuriously cancel this."""
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(1), face: _make_face_state("unknown")}
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": {"location": "elsewhere"}},  # not in area a1
        area_to_room={"a1": "kitchen", "a2": "elsewhere"},
    )
    census = _make_census({info.entity_id: info}, states, person_coordinator=pc_stub)
    assert census._get_unrecognized_camera_count() == 1


# ===========================================================================
# Invariant I1 — the LOAD-BEARING soundness test.
# ===========================================================================


def test_i1_resident_kitchen_does_not_cancel_guest_foyer() -> None:
    """Two cameras in different areas: resident BLE'd in kitchen, kitchen cam
    also sees resident face-unknown, foyer cam sees a real guest. The foyer
    camera MUST still contribute 1 to unidentified after the kitchen camera
    consumed the local resident (I1).
    """
    kitchen_cam, kc_pc, kc_face = _make_frigate_camera("kitchen_cam", "a_kitchen")
    foyer_cam, fc_pc, fc_face = _make_frigate_camera("foyer_cam", "a_foyer")
    cameras = {
        kitchen_cam.entity_id: kitchen_cam,
        foyer_cam.entity_id: foyer_cam,
    }
    states = {
        kc_pc: _make_person_count_state(1),
        kc_face: _make_face_state("unknown"),
        fc_pc: _make_person_count_state(1),
        fc_face: _make_face_state("unknown"),
    }
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": {"location": "kitchen"}},
        area_to_room={"a_kitchen": "kitchen", "a_foyer": "foyer"},
    )
    census = _make_census(cameras, states, person_coordinator=pc_stub)
    assert census._get_unrecognized_camera_count() == 1


def test_i3_monotone_no_person_coord_yields_pre_cycle_behavior() -> None:
    """When person_coordinator is unavailable, correction MUST be 0 and the
    result MUST equal the pre-cycle raw behavior (I3 — never inflates)."""
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(2), face: _make_face_state("unknown")}
    census = _make_census({info.entity_id: info}, states, person_coordinator=None)
    assert census._get_unrecognized_camera_count() == 2


def test_ble_cancelled_count_diagnostic_populated() -> None:
    """D3: _last_ble_cancelled_count reflects the correction sum."""
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(1), face: _make_face_state("unknown")}
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": {"location": "kitchen"}},
        area_to_room={"a1": "kitchen"},
    )
    census = _make_census({info.entity_id: info}, states, person_coordinator=pc_stub)
    census._get_unrecognized_camera_count()
    assert census._last_ble_cancelled_count == 1


def test_ble_cancelled_count_zero_when_no_correlation() -> None:
    """M3 anchor: with resident elsewhere and area correlation intact,
    diagnostic must read 0."""
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(1), face: _make_face_state("unknown")}
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": {"location": "elsewhere"}},
        area_to_room={"a1": "kitchen", "a2": "elsewhere"},
    )
    census = _make_census({info.entity_id: info}, states, person_coordinator=pc_stub)
    census._get_unrecognized_camera_count()
    assert census._last_ble_cancelled_count == 0
