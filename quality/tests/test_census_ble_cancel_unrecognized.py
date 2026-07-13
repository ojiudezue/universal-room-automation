"""Cycle ``census_ble_cancel_unrecognized`` — area-correlated BLE subtraction.

These tests DRIVE the REAL production ``PersonCensus`` (Bug Class #60: never
re-implement production logic in tests). They exercise the
``_get_unrecognized_camera_count`` path, the ``_ble_home_by_area`` helper,
the ``_build_room_to_area_id_map`` helper (Fix 3), AND the end-to-end
``_apply_enhanced_house_census`` path (Fix 1) against the 8-row multi-person
matrix from PLANNING_census_ble_cancel_unrecognized.md §4.1.

Mutation anchors — each of these production sites, when neutered, MUST turn
at least one NAMED test in this file red (run manually per cycle protocol):

  M1. ``_get_unrecognized_camera_count``: neuter ``correction`` (e.g.
      set ``correction = 0`` in Step 3). Expected red: matrix rows 1/3/4/5/6,
      the row1 / row3 / diagnostic tests.
  M2. ``_ble_home_by_area``: replace body with ``return {}``. Expected red:
      helper unit tests + every matrix row whose ``ble_here > 0`` +
      diagnostic tests + end-to-end.
  M3. Remove the area correlation in ``_get_unrecognized_camera_count``
      (change ``ble_by_area.get(aid, 0)`` to ``sum(ble_by_area.values())``).
      Expected red: ``test_row7_pure_guest_still_detected``,
      ``test_ble_cancelled_count_zero_when_no_correlation``,
      ``test_i1_resident_kitchen_does_not_cancel_guest_foyer``.
  M4. Remove the LOST/away guard in ``_ble_home_by_area``. Expected red:
      ``test_lost_person_does_not_cancel``.
  M5 (Fix 1 anchor). Remove the ``ble_cancelled_count`` field from
      ``CensusZoneResult`` OR the kwarg from ``_apply_enhanced_house_census``:
      TypeError → ``test_end_to_end_apply_enhanced_house_census_ships_field``
      fails.
  M6 (Fix 2 anchor). Move the BLE subtraction back to per-camera BEFORE
      dedup: ``test_two_cameras_same_area_both_cancel`` fails (same-area
      under-cancel).
  M7 (Fix 3 anchor). Rewrite ``_build_room_to_area_id_map`` to invert
      ``person_coordinator._area_id_to_room``: ``test_renamed_area_still_cancels``
      fails (yields normalized name, not registry area_id).
  M8 (Fix 4 anchor). Restore the ``None``-bucket behavior in
      ``_ble_home_by_area``: ``test_unmapped_resident_does_not_cancel_null_area_guest``
      fails.
  M9 (Fix 5a anchor). Drop the ``tracking_status`` STALE/LOST filter:
      ``test_stale_resident_does_not_cancel`` fails.

Test-file module hygiene: uses ``sys.modules.setdefault`` (composition-safe;
does NOT clobber sibling test files' HA-module stubs). The dt_util override
is applied per-test via an autouse fixture (Fix 6 / B-L1 / C-LOW-5) so it
cannot leak into sibling test files loaded in the same process.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401 — bootstraps HA module stubs (setdefault-safe).
from _provenance_harness import make_hass

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation import camera_census as _cc_mod
from custom_components.universal_room_automation.camera_census import (
    CameraInfo,
    CensusZoneResult,
    PersonCensus,
)


# The provenance-harness stubs ``dt_util.utcnow`` as ``datetime.utcnow``
# which returns a NAIVE datetime — production uses a tz-aware UTC clock.
# The freshness compare in ``_get_unrecognized_camera_count`` mixes naive
# ``now`` with aware ``last_changed`` and raises TypeError, silently
# forcing face_is_fresh=False for tests trying to exercise the fresh
# path. Override just for this file, scoped via autouse fixture so the
# original module attr is restored after every test (Fix 6 / B-L1 /
# C-LOW-5 — the module-global assignment survived across sibling test
# files loaded in the same process; a scoped fixture cannot leak).
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


@pytest.fixture(autouse=True)
def _scoped_dt_util(monkeypatch: pytest.MonkeyPatch):
    """Replace camera_census.dt_util with a tz-aware stub for this file only."""
    monkeypatch.setattr(_cc_mod, "dt_util", _TzUtil(), raising=True)
    yield


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
# Person coordinator stub — mirrors the two attributes the helper reads.
#   - ``data``: {person_id: {"location": <room_name>, "tracking_status": ...}}
#   - ``_area_id_to_room``: production-shaped TRIPLE-KEY map (registry
#     area_id, area Name, normalized-name) all -> same room_name. See
#     ``person_coordinator._build_scanner_room_map`` (lines 563-565). The
#     Fix 3 helper MUST NOT invert this dict; it must read CONF_AREA_ID
#     from room config entries directly (which _make_census now wires).
#     We seed the map here as well so any regression that reintroduces the
#     inversion also breaks tests.
# ---------------------------------------------------------------------------


class _StubPersonCoordinator:
    def __init__(
        self,
        person_data: dict[str, dict[str, Any]],
        area_id_to_room: dict[str, str],
    ) -> None:
        self.data = person_data
        self._area_id_to_room = area_id_to_room


def _triple_key_map(
    entries: list[tuple[str, str, str]],
) -> dict[str, str]:
    """Build a production-shaped ``_area_id_to_room`` map.

    Each input entry is ``(registry_area_id, area_name, room_name)`` and
    contributes THREE keys per production semantics:
      * registry area_id → room_name
      * area name        → room_name
      * normalized name  → room_name  (lowercase, spaces → underscores)
    """
    out: dict[str, str] = {}
    for area_id, area_name, room_name in entries:
        out[area_id] = room_name
        out[area_name] = room_name
        out[area_name.lower().replace(" ", "_")] = room_name
    return out


def _person(
    location: str,
    tracking_status: str = ura_const.TRACKING_STATUS_ACTIVE,
) -> dict[str, Any]:
    """Build person_data entry with tracking_status defaulted to ACTIVE.

    ACTIVE residents cancel; STALE/LOST/away do not (Fix 5a).
    """
    return {"location": location, "tracking_status": tracking_status}


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
    *,
    room_config: Optional[list[tuple[str, str]]] = None,
) -> PersonCensus:
    """Real ``PersonCensus`` wired to stubbed hass / camera_manager / person_coord.

    ``room_config`` — list of ``(room_name, area_id)`` for the rooms that
    ``_build_room_to_area_id_map`` (Fix 3) must be able to resolve. These
    are materialized as ENTRY_TYPE_ROOM config entries because the helper
    reads room config entries directly (NOT the person_coordinator dict).
    """
    hass = make_hass()
    hass.states.get = lambda entity_id: states.get(entity_id)

    entries: list[MagicMock] = []

    integration_entry = MagicMock()
    integration_entry.data = {
        ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION,
    }
    integration_entry.options = {
        ura_const.CONF_CAMERA_PERSON_ENTITIES: list(cameras.keys()),
        ura_const.CONF_ENHANCED_CENSUS: True,
    }
    entries.append(integration_entry)

    for room_name, area_id in room_config or []:
        room_entry = MagicMock()
        room_entry.data = {
            ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_ROOM,
            ura_const.CONF_ROOM_NAME: room_name,
            ura_const.CONF_AREA_ID: area_id,
        }
        room_entry.options = {}
        entries.append(room_entry)

    hass.config_entries.async_entries.return_value = entries

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
# _build_room_to_area_id_map — Fix 3 (review A-H2) direct read of CONF_AREA_ID
# ===========================================================================


def test_build_room_to_area_id_map_reads_room_config_entries() -> None:
    """Room entries with CONF_AREA_ID → correct room_name→area_id mapping.

    Mutation M7: inverting person_coordinator._area_id_to_room would yield
    the last-wins normalized name value, NOT the registry area_id.
    """
    info, _pc, _face = _make_frigate_camera("cam", "area_uuid_kitchen")
    census = _make_census(
        {info.entity_id: info}, {},
        room_config=[("Kitchen", "area_uuid_kitchen"), ("Foyer", "area_uuid_foyer")],
    )
    result = census._build_room_to_area_id_map()
    assert result == {"Kitchen": "area_uuid_kitchen", "Foyer": "area_uuid_foyer"}


def test_build_room_to_area_id_map_empty_when_no_room_entries() -> None:
    info, _pc, _face = _make_frigate_camera("cam", "a1")
    census = _make_census({info.entity_id: info}, {}, room_config=[])
    assert census._build_room_to_area_id_map() == {}


# ===========================================================================
# _ble_home_by_area helper — unit-level
# ===========================================================================


def test_ble_home_by_area_returns_empty_when_no_person_coordinator() -> None:
    """Graceful degradation (I3) — no person_coordinator wired → ``{}``."""
    info, _pc, _face = _make_frigate_camera("cam", "a1")
    census = _make_census(
        {info.entity_id: info}, {},
        person_coordinator=None,
        room_config=[("Kitchen", "a1")],
    )
    assert census._ble_home_by_area() == {}


def test_ble_home_by_area_returns_empty_when_person_coordinator_has_no_data() -> None:
    """No tracked persons → ``{}`` (I3 graceful)."""
    info, _pc, _face = _make_frigate_camera("cam", "a1")
    pc_stub = _StubPersonCoordinator(
        person_data={},
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    census = _make_census(
        {info.entity_id: info}, {},
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1")],
    )
    assert census._ble_home_by_area() == {}


def test_ble_home_by_area_maps_room_to_area() -> None:
    """Resident located in room ``Kitchen`` → area_id ``a1`` count 1."""
    info, _pc, _face = _make_frigate_camera("cam", "a1")
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": _person("Kitchen")},
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    census = _make_census(
        {info.entity_id: info}, {},
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1")],
    )
    assert census._ble_home_by_area() == {"a1": 1}


def test_ble_home_by_area_multiple_residents_same_room_stack() -> None:
    pc_stub = _StubPersonCoordinator(
        person_data={
            "oji": _person("Kitchen"),
            "grace": _person("Kitchen"),
        },
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    info, _pc, _face = _make_frigate_camera("cam", "a1")
    census = _make_census(
        {info.entity_id: info}, {},
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1")],
    )
    assert census._ble_home_by_area() == {"a1": 2}


def test_lost_person_does_not_cancel() -> None:
    """Mutation anchor M4: away/unknown/home/lost residents excluded from the map."""
    pc_stub = _StubPersonCoordinator(
        person_data={
            "away_dude": _person("away"),
            "lost_loc_dude": _person("unknown"),
            "home_but_unresolved": _person("home"),
            "lost_status_dude": _person("Kitchen", ura_const.TRACKING_STATUS_LOST),
            "real_room_dude": _person("Kitchen"),
        },
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    info, _pc, _face = _make_frigate_camera("cam", "a1")
    census = _make_census(
        {info.entity_id: info}, {},
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1")],
    )
    # Only the real_room_dude counts.
    assert census._ble_home_by_area() == {"a1": 1}


def test_stale_resident_does_not_cancel() -> None:
    """Fix 5a / M9 anchor: STALE tracking_status excluded from the map.

    bermuda_decay keeps a departed resident's ``location`` populated for up
    to 300s under STALE. A departed resident must not cancel a real guest
    arriving in the area they just left.
    """
    pc_stub = _StubPersonCoordinator(
        person_data={
            "departed": _person("Kitchen", ura_const.TRACKING_STATUS_STALE),
        },
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(1), face: _make_face_state("unknown")}
    census = _make_census(
        {info.entity_id: info}, states,
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1")],
    )
    # STALE resident cannot cancel; guest at pc=1 must still count.
    assert census._ble_home_by_area() == {}
    assert census._get_unrecognized_camera_count() == 1


def test_unmapped_resident_dropped_not_bucketed_under_none() -> None:
    """Fix 4 / M8 anchor: room slug that doesn't map to any registered area
    is DROPPED entirely (not bucketed under None). The prior implementation
    put unmapped residents under key ``None`` which cross-cancelled with
    null-area cameras and broke I1.
    """
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": _person("Attic")},  # Attic not in room_config
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    info, _pc, _face = _make_frigate_camera("cam", "a1")
    census = _make_census(
        {info.entity_id: info}, {},
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1")],
    )
    # Attic drops entirely; no None key.
    assert census._ble_home_by_area() == {}


# ===========================================================================
# 8-row matrix — parametrized against the real _get_unrecognized_camera_count
# ===========================================================================


def _fresh() -> datetime:
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
        f"resident_{i}": _person("Kitchen") for i in range(ble_here)
    }
    pc_stub = _StubPersonCoordinator(
        person_data=person_data,
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    census = _make_census(
        cameras, states,
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1")],
    )

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
        person_data={"oji": _person("Kitchen")},
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    census = _make_census(
        {info.entity_id: info}, states,
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1")],
    )
    assert census._get_unrecognized_camera_count() == 0


def test_row3_resident_plus_guest() -> None:
    """Guest survives cancellation; 1 resident cancels 1 slot, 1 unidentified
    remains (I2 completeness)."""
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(2), face: _make_face_state("unknown")}
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": _person("Kitchen")},
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    census = _make_census(
        {info.entity_id: info}, states,
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1")],
    )
    assert census._get_unrecognized_camera_count() == 1


def test_row7_pure_guest_still_detected() -> None:
    """I1 soundness + M3 anchor: no resident in the area — guest MUST count.
    A global-sum mutation would spuriously cancel this."""
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(1), face: _make_face_state("unknown")}
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": _person("Elsewhere")},  # in Elsewhere, not Kitchen
        area_id_to_room=_triple_key_map(
            [("a1", "Kitchen", "Kitchen"), ("a2", "Elsewhere", "Elsewhere")],
        ),
    )
    census = _make_census(
        {info.entity_id: info}, states,
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1"), ("Elsewhere", "a2")],
    )
    assert census._get_unrecognized_camera_count() == 1


# ===========================================================================
# Invariant I1 — the LOAD-BEARING soundness test.
# ===========================================================================


def test_i1_resident_kitchen_does_not_cancel_guest_foyer() -> None:
    """Two cameras in different areas: resident BLE'd in kitchen; foyer cam
    sees a real guest. The foyer camera MUST still contribute 1 to
    unidentified after the kitchen camera consumed the local resident (I1).
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
        person_data={"oji": _person("Kitchen")},
        area_id_to_room=_triple_key_map(
            [("a_kitchen", "Kitchen", "Kitchen"), ("a_foyer", "Foyer", "Foyer")],
        ),
    )
    census = _make_census(
        cameras, states,
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a_kitchen"), ("Foyer", "a_foyer")],
    )
    assert census._get_unrecognized_camera_count() == 1


def test_i3_monotone_no_person_coord_yields_pre_cycle_behavior() -> None:
    """When person_coordinator is unavailable, correction MUST be 0 and the
    result MUST equal the pre-cycle raw behavior (I3 — never inflates)."""
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(2), face: _make_face_state("unknown")}
    census = _make_census(
        {info.entity_id: info}, states,
        person_coordinator=None,
        room_config=[("Kitchen", "a1")],
    )
    assert census._get_unrecognized_camera_count() == 2


def test_ble_cancelled_count_diagnostic_populated() -> None:
    """D3: _last_ble_cancelled_count reflects the correction sum."""
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(1), face: _make_face_state("unknown")}
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": _person("Kitchen")},
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    census = _make_census(
        {info.entity_id: info}, states,
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1")],
    )
    census._get_unrecognized_camera_count()
    assert census._last_ble_cancelled_count == 1


def test_ble_cancelled_count_zero_when_no_correlation() -> None:
    """M3 anchor: with resident elsewhere and area correlation intact,
    diagnostic must read 0."""
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(1), face: _make_face_state("unknown")}
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": _person("Elsewhere")},
        area_id_to_room=_triple_key_map(
            [("a1", "Kitchen", "Kitchen"), ("a2", "Elsewhere", "Elsewhere")],
        ),
    )
    census = _make_census(
        {info.entity_id: info}, states,
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1"), ("Elsewhere", "a2")],
    )
    census._get_unrecognized_camera_count()
    assert census._last_ble_cancelled_count == 0


# ===========================================================================
# Fix 2 — per-area redesign: same-area under-cancel + order-independence +
# min-bound (C-HIGH-2 anchor).
# ===========================================================================


def test_two_cameras_same_area_both_cancel() -> None:
    """Fix 2 / M6 anchor: TWO cameras cover the same playroom area, resident
    BLE-there. Prior per-camera-with-decrementing-budget code cancelled only
    ONE camera, then ``_dedup_by_area`` took max → resident re-armed the
    gate via camera B. Per-area redesign: same-area max = 1, ble_here = 1,
    correction = 1, final = 0.
    """
    cam_a, ca_pc, ca_face = _make_frigate_camera("playroom_a", "a_playroom")
    cam_b, cb_pc, cb_face = _make_frigate_camera("playroom_b", "a_playroom")
    cameras = {cam_a.entity_id: cam_a, cam_b.entity_id: cam_b}
    states = {
        ca_pc: _make_person_count_state(1),
        ca_face: _make_face_state("unknown"),
        cb_pc: _make_person_count_state(1),
        cb_face: _make_face_state("unknown"),
    }
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": _person("Playroom")},
        area_id_to_room=_triple_key_map(
            [("a_playroom", "Playroom", "Playroom")],
        ),
    )
    census = _make_census(
        cameras, states,
        person_coordinator=pc_stub,
        room_config=[("Playroom", "a_playroom")],
    )
    assert census._get_unrecognized_camera_count() == 0
    assert census._last_ble_cancelled_count == 1


def test_order_permutation_yields_identical_result() -> None:
    """Fix 2 — result must be independent of camera iteration order.

    Ship two configurations with the cameras swapped in the CONF list; the
    result must be identical.
    """
    def _run(order: str) -> int:
        cam_a, ca_pc, ca_face = _make_frigate_camera("playroom_a", "a_playroom")
        cam_b, cb_pc, cb_face = _make_frigate_camera("playroom_b", "a_playroom")
        if order == "ab":
            cameras = {cam_a.entity_id: cam_a, cam_b.entity_id: cam_b}
        else:
            cameras = {cam_b.entity_id: cam_b, cam_a.entity_id: cam_a}
        states = {
            ca_pc: _make_person_count_state(2),
            ca_face: _make_face_state("unknown"),
            cb_pc: _make_person_count_state(1),
            cb_face: _make_face_state("unknown"),
        }
        pc_stub = _StubPersonCoordinator(
            person_data={"oji": _person("Playroom")},
            area_id_to_room=_triple_key_map(
                [("a_playroom", "Playroom", "Playroom")],
            ),
        )
        census = _make_census(
            cameras, states,
            person_coordinator=pc_stub,
            room_config=[("Playroom", "a_playroom")],
        )
        return census._get_unrecognized_camera_count()

    ab = _run("ab")
    ba = _run("ba")
    assert ab == ba, f"order-dependent: ab={ab} ba={ba}"
    # Same-area max = 2; ble_here = 1; correction = 1; final = 1.
    assert ab == 1


def test_two_residents_same_area_pc_one_cancels_at_most_one() -> None:
    """C-HIGH-2 min-bound anchor: 2 residents BLE-in-area, pc=1 →
    cancelled==1 (min(raw_max=1, ble_here=2) = 1), NOT 2.
    """
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(1), face: _make_face_state("unknown")}
    pc_stub = _StubPersonCoordinator(
        person_data={
            "oji": _person("Kitchen"),
            "grace": _person("Kitchen"),
        },
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    census = _make_census(
        {info.entity_id: info}, states,
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1")],
    )
    assert census._get_unrecognized_camera_count() == 0
    # min(raw_max=1, ble_here=2) = 1 — never 2.
    assert census._last_ble_cancelled_count == 1


# ===========================================================================
# Fix 3 — renamed-area case (production triple-key map inversion pitfall).
# ===========================================================================


def test_renamed_area_still_cancels() -> None:
    """Fix 3 / M7 anchor: HA area was renamed from "Old Kitchen Name" to
    "Kitchen", so the registry area_id is unchanged (``area_uuid_abc``) but
    the area's *display Name* differs from the URA room_name. Production
    ``_area_id_to_room`` writes THREE keys: {area_uuid_abc, Old Kitchen Name,
    old_kitchen_name} all → "Kitchen". Inverting this dict is last-wins over
    those three keys and typically yields the normalized-name value —
    NOT the registry area_id. ``CameraInfo.area_id`` is the registry
    area_id, so an inverted-dict helper silently never cancels.

    ``_build_room_to_area_id_map`` (Fix 3) reads CONF_AREA_ID directly from
    the room config entry, sidestepping the inversion problem entirely.
    """
    info, pcs, face = _make_frigate_camera("cam", "area_uuid_abc")
    states = {pcs: _make_person_count_state(1), face: _make_face_state("unknown")}
    # Room name = "Kitchen"; HA area display name = "Old Kitchen Name"
    # (differs from room name — the classic rename case).
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": _person("Kitchen")},
        area_id_to_room=_triple_key_map(
            [("area_uuid_abc", "Old Kitchen Name", "Kitchen")],
        ),
    )
    census = _make_census(
        {info.entity_id: info}, states,
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "area_uuid_abc")],
    )
    # Resident cancels; unrecognized = 0.
    assert census._get_unrecognized_camera_count() == 0


# ===========================================================================
# Fix 4 — null-area camera + unmapped resident: guest arms.
# ===========================================================================


def test_unmapped_resident_does_not_cancel_null_area_guest() -> None:
    """Fix 4 / M8 anchor (I1 breach guard).

    A camera whose ``area_id`` is None (unassigned in HA registry) plus a
    resident whose ``location`` doesn't resolve to any known room — the
    prior code bucketed the resident under key None, which cancelled the
    null-area camera's contribution. That's a real-guest suppression: the
    resident is somewhere unmapped and the guest is on a null-area camera.

    After Fix 4 the unmapped resident is dropped from ``_ble_home_by_area``
    entirely; the null-area camera contributes its guest.
    """
    info, pcs, face = _make_frigate_camera("cam", None)  # null area_id
    states = {pcs: _make_person_count_state(1), face: _make_face_state("unknown")}
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": _person("Attic")},  # Attic not in room_config
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    census = _make_census(
        {info.entity_id: info}, states,
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1")],
    )
    # Null-area camera's guest MUST still contribute.
    assert census._get_unrecognized_camera_count() == 1
    assert census._last_ble_cancelled_count == 0


# ===========================================================================
# Fix 1 — end-to-end: _apply_enhanced_house_census ships ble_cancelled_count.
# ===========================================================================


def test_end_to_end_apply_enhanced_house_census_ships_field() -> None:
    """Fix 1 / M5 anchor.

    Exercises the REAL end-to-end construction path
    ``_apply_enhanced_house_census`` → ``CensusZoneResult(...)``. Without
    the ``ble_cancelled_count`` field on the dataclass (or without the
    kwarg on the constructor call), this test fails with a TypeError on
    every enhanced-census cycle — the bug the prior build silently
    swallowed.
    """
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(1), face: _make_face_state("unknown")}
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": _person("Kitchen")},
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    census = _make_census(
        {info.entity_id: info}, states,
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1")],
    )

    # Raw stub result — the enhanced path preserves its shape but sets
    # its own unidentified_count. Use a minimal valid CensusZoneResult.
    raw = CensusZoneResult(
        zone="house",
        identified_count=0,
        identified_persons=[],
        unidentified_count=1,
        total_persons=1,
        confidence=ura_const.CENSUS_CONFIDENCE_MEDIUM,
        source_agreement=ura_const.CENSUS_AGREEMENT_SINGLE,
        frigate_count=1,
        unifi_count=0,
    )

    result = census._apply_enhanced_house_census(
        raw, ble_persons=["oji"], now=datetime.now(timezone.utc),
    )
    # The very existence of ``ble_cancelled_count`` on the returned object
    # proves the construction path did not raise.
    assert hasattr(result, "ble_cancelled_count")
    # Resident cancelled at the camera → count == 1.
    assert result.ble_cancelled_count == 1


def test_end_to_end_ble_cancelled_count_zero_default() -> None:
    """Fix 1: with no correlation, field defaults to 0 (not omitted / None)."""
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(1), face: _make_face_state("unknown")}
    census = _make_census(
        {info.entity_id: info}, states,
        person_coordinator=None,
        room_config=[("Kitchen", "a1")],
    )
    raw = CensusZoneResult(
        zone="house",
        identified_count=0,
        identified_persons=[],
        unidentified_count=1,
        total_persons=1,
        confidence=ura_const.CENSUS_CONFIDENCE_MEDIUM,
        source_agreement=ura_const.CENSUS_AGREEMENT_SINGLE,
        frigate_count=1,
        unifi_count=0,
    )
    result = census._apply_enhanced_house_census(
        raw, ble_persons=[], now=datetime.now(timezone.utc),
    )
    assert result.ble_cancelled_count == 0


# ===========================================================================
# H3 (2026-07-13) — BLE-cancel kill switch
# ===========================================================================


def _make_census_with_ble_cancel(enabled: bool) -> tuple[PersonCensus, MagicMock]:
    """Build a census fixture and expose the integration entry so the
    test can toggle CONF_CENSUS_BLE_CANCEL_ENABLED live.

    Returns (census, integration_entry). Mutating integration_entry.options
    then reading `census._get_unrecognized_camera_count()` on the next
    call exercises the live options-read pattern.
    """
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(2), face: _make_face_state("unknown")}
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": _person("Kitchen")},
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    hass = make_hass()
    hass.states.get = lambda entity_id: states.get(entity_id)
    integration_entry = MagicMock()
    integration_entry.data = {
        ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION,
    }
    integration_entry.options = {
        ura_const.CONF_CAMERA_PERSON_ENTITIES: [info.entity_id],
        ura_const.CONF_ENHANCED_CENSUS: True,
        ura_const.CONF_CENSUS_BLE_CANCEL_ENABLED: enabled,
    }
    room_entry = MagicMock()
    room_entry.data = {
        ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_ROOM,
        ura_const.CONF_ROOM_NAME: "Kitchen",
        ura_const.CONF_AREA_ID: "a1",
    }
    room_entry.options = {}
    hass.config_entries.async_entries.return_value = [integration_entry, room_entry]
    try:
        hass.data[ura_const.DOMAIN] = {"person_coordinator": pc_stub}
    except Exception:  # pragma: no cover
        hass.data = {ura_const.DOMAIN: {"person_coordinator": pc_stub}}
    mgr = _StubCameraManager({info.entity_id: info})
    census = PersonCensus(hass, mgr)  # type: ignore[arg-type]
    return census, integration_entry


def test_h3_gate_off_skips_subtraction() -> None:
    """H3: kill switch OFF — subtraction skipped. 2 people at the camera,
    1 resident BLE-here: WITHOUT cancellation, unrecognized count == 2
    (both flow through as raw). Contrast with gate ON: count == 1.

    Drives the REAL _get_unrecognized_camera_count function.
    """
    census, _entry = _make_census_with_ble_cancel(enabled=False)
    assert census._get_unrecognized_camera_count() == 2


def test_h3_gate_on_default_still_subtracts() -> None:
    """H3: kill switch ON (default) — subtraction ACTIVE, resident cancels."""
    census, _entry = _make_census_with_ble_cancel(enabled=True)
    assert census._get_unrecognized_camera_count() == 1


def test_h3_default_is_true_when_option_absent() -> None:
    """H3: when the option is absent from entry.options, default is True.

    This preserves current behavior for existing installations that
    haven't seen the new field.
    """
    info, pcs, face = _make_frigate_camera("cam", "a1")
    states = {pcs: _make_person_count_state(2), face: _make_face_state("unknown")}
    pc_stub = _StubPersonCoordinator(
        person_data={"oji": _person("Kitchen")},
        area_id_to_room=_triple_key_map([("a1", "Kitchen", "Kitchen")]),
    )
    # Standard fixture — CONF_CENSUS_BLE_CANCEL_ENABLED NOT set.
    census = _make_census(
        {info.entity_id: info}, states,
        person_coordinator=pc_stub,
        room_config=[("Kitchen", "a1")],
    )
    # Default = True → subtraction ACTIVE → count == 1.
    assert census._get_unrecognized_camera_count() == 1
    # And the accessor reports True.
    assert census._get_ble_cancel_enabled() is True


def test_h3_options_read_live_across_ticks() -> None:
    """H3: the accessor reads options LIVE per call (same pattern as
    _get_hold_seconds). Mutating integration_entry.options between
    ticks flips behavior without any explicit reload."""
    census, entry = _make_census_with_ble_cancel(enabled=True)
    assert census._get_unrecognized_camera_count() == 1  # gate ON, cancelled
    # Flip live — no restart, no _make_census rebuild.
    entry.options = {**entry.options, ura_const.CONF_CENSUS_BLE_CANCEL_ENABLED: False}
    assert census._get_unrecognized_camera_count() == 2  # gate OFF, raw


def test_h3_mutation_anchor_gate_removed(monkeypatch) -> None:
    """Behavior test (2026-07-13 relabel per C-MED-2): the docstring
    previously claimed 'MUTATION ANCHOR' but the test SIMULATES the
    absence of the gate by monkeypatching the ACCESSOR to always
    return True, rather than editing the production call site. It
    proves the gate is READ at that site (the aggregate is load-
    bearing), but a real per-site source mutation is provided below
    by ``test_c_med_1_h3_options_round_trip_real_source_mutation``.
    """
    census, _entry = _make_census_with_ble_cancel(enabled=False)
    # Mutation: force the gate accessor True regardless of options.
    monkeypatch.setattr(
        census, "_get_ble_cancel_enabled", lambda: True,
    )
    # Under the mutation the subtraction still runs → count == 1.
    assert census._get_unrecognized_camera_count() == 1
    # (The non-mutated invariant is count == 2 under gate=OFF, proven
    # by test_h3_gate_off_skips_subtraction above.)
