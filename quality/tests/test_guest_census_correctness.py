"""GUEST-CENSUS CORRECTNESS cycle — D1 clamp, D2 composition, D3 registry.

Covers three deliverables from
``docs/planning/PLANNING_guest_census_correctness.md`` (rev-2, commit
``3b373d3db``):

* **D1** — INV-CENSUS-ATTRIBUTION clamp on the enhanced house census.
  Ceiling MUST use the **PRE-BLE-cancel** scalar
  ``_last_camera_total_pre_cancel`` (Step 2 of
  ``_get_unrecognized_camera_count``) so a real guest is preserved once
  BLE-cancel/face defenses are repaired (reviewer counter-example,
  plan-review P1).

* **D2** — home-like branch guest composition: ``guest_armed =
  guest_room_gate_armed`` (Path B leads; Path A is a corroborator only).

* **D3** — guest-room occupied entity resolved via entity registry using
  ``f"{entry_id}_occupied"`` unique_id, NOT slug-string construction.

Mutation anchors (per plan §Tier 2-DB Review C):
  D1-M1. Retarget the clamp ceiling to ``camera_unrecognized`` (POST-cancel)
         → ``test_clamp_repaired_defenses_preserves_guest`` fails.
  D1-M2. Delete the clamp / restore ``total = identified_count +
         held_unidentified`` → ``test_clamp_tonight_live_shape`` fails
         with observed ``total=10``.
  D1-M3. Comment out the ``self._last_camera_total_pre_cancel = ...``
         publication → the same tonight test fails (getattr default 0
         → clamped_total = max(0, id) = id).
  D2-M1. ``guest_armed = unid_gate_armed or guest_room_gate_armed`` (revert)
         → ``test_home_like_guest_armed_is_room_only`` fails.
  D3-M1. Restore string-build ``f"binary_sensor.{room_slug}_occupied"``
         → ``test_discover_uses_registry_lookup`` fails.
  D3-M2. Delete the WARNING on unresolvable → ``test_unresolvable_room_warns``
         fails.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation import camera_census as _cc_mod
from custom_components.universal_room_automation.camera_census import (
    CameraInfo,
    CensusZoneResult,
    PersonCensus,
)


# ---------------------------------------------------------------------------
# tz-aware dt_util (mirrors test_census_ble_cancel_unrecognized.py hygiene).
# ---------------------------------------------------------------------------
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
    monkeypatch.setattr(_cc_mod, "dt_util", _TzUtil(), raising=True)
    yield


# ---------------------------------------------------------------------------
# Minimal census fixture — small subset of _make_census from the sibling
# file, inlined so this test file has no cross-file coupling.
# ---------------------------------------------------------------------------


class _StubCameraManager:
    def __init__(self, cameras: dict[str, CameraInfo]) -> None:
        self._camera_by_entity = cameras

    def get_platform_for_camera(self, entity_id: str) -> Optional[str]:
        info = self._camera_by_entity.get(entity_id)
        return info.platform if info else None

    def resolve_configured_cameras(
        self, camera_entity_ids: list[str],
    ) -> list[CameraInfo]:
        return [
            self._camera_by_entity[eid]
            for eid in camera_entity_ids
            if eid in self._camera_by_entity
        ]

    def get_all_frigate_cameras(self) -> list[CameraInfo]:
        return [
            c for c in self._camera_by_entity.values()
            if c.platform == ura_const.CAMERA_PLATFORM_FRIGATE
        ]


def _make_bare_census() -> PersonCensus:
    hass = make_hass()
    hass.states.get = lambda entity_id: None
    integration_entry = MagicMock()
    integration_entry.data = {
        ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION,
    }
    integration_entry.options = {
        ura_const.CONF_CAMERA_PERSON_ENTITIES: [],
        ura_const.CONF_ENHANCED_CENSUS: True,
    }
    hass.config_entries.async_entries.return_value = [integration_entry]
    try:
        hass.data[ura_const.DOMAIN] = {}
    except Exception:  # pragma: no cover
        hass.data = {ura_const.DOMAIN: {}}
    return PersonCensus(hass, _StubCameraManager({}))  # type: ignore[arg-type]


def _minimal_raw_result(unid: int = 0) -> CensusZoneResult:
    return CensusZoneResult(
        zone="house",
        identified_count=0,
        identified_persons=[],
        unidentified_count=unid,
        total_persons=unid,
        confidence=ura_const.CENSUS_CONFIDENCE_MEDIUM,
        source_agreement=ura_const.CENSUS_AGREEMENT_SINGLE,
        frigate_count=unid,
        unifi_count=0,
    )


def _stub_camera_producer(
    census: PersonCensus,
    *,
    camera_unrecognized_return: int,
    pre_cancel: int,
) -> None:
    """Override _get_unrecognized_camera_count to set the pre-cancel scalar
    AND return camera_unrecognized in one call (mirrors production ordering)."""

    def _stub() -> int:
        census._last_camera_total_pre_cancel = pre_cancel
        return camera_unrecognized_return

    census._get_unrecognized_camera_count = _stub  # type: ignore[assignment]


def _stub_hold_decay(census: PersonCensus, held: int) -> None:
    """Bypass hold/decay — return ``held`` directly."""

    def _stub(raw: int, zone: str, now: datetime):
        return held, False, 0

    census._apply_hold_decay = _stub  # type: ignore[assignment]


def _make_ble_persons(_census: PersonCensus, names: list[str]) -> list[str]:
    """Return ble_persons list (identified_count = len(recognized_set))."""
    return names


# ===========================================================================
# D1 — clamp arithmetic
# ===========================================================================


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_clamp_tonight_live_shape() -> None:
    """Tonight (5-person household, both defenses broken): id=4, pre_cancel=6,
    camera_unrecognized=6, held=6 → total=6, unidentified=2 (NOT 10).

    Discriminator: without the clamp the enhanced additive shape returns
    total=10, unidentified=6.
    """
    census = _make_bare_census()
    _stub_camera_producer(census, camera_unrecognized_return=6, pre_cancel=6)
    _stub_hold_decay(census, held=6)
    result = census._apply_enhanced_house_census(
        _minimal_raw_result(unid=6),
        ble_persons=["oji", "ezinne", "jaya", "ziri"],
        now=_now(),
    )
    assert result.identified_count == 4
    assert result.total_persons == 6, f"expected clamp to 6, got {result.total_persons}"
    assert result.unidentified_count == 2


def test_clamp_repaired_defenses_preserves_guest() -> None:
    """Reviewer P1 counter-example (repaired defenses, 5-person household):
    id=4, pre_cancel=5, camera_unrecognized=1 (residents cancelled),
    held=1 → total=5, unidentified=1.

    Under the OLD (POST-cancel) ceiling this returns total=4, unidentified=0
    (guest SUPPRESSED). This test MUST fail if the ceiling is retargeted to
    ``camera_unrecognized`` — the load-bearing rev-1 vs rev-2 discriminator.
    """
    census = _make_bare_census()
    _stub_camera_producer(census, camera_unrecognized_return=1, pre_cancel=5)
    _stub_hold_decay(census, held=1)
    result = census._apply_enhanced_house_census(
        _minimal_raw_result(unid=1),
        ble_persons=["oji", "ezinne", "jaya", "ziri"],
        now=_now(),
    )
    assert result.identified_count == 4
    assert result.total_persons == 5, (
        f"guest suppressed: total={result.total_persons} "
        f"(POST-cancel ceiling bug — plan-review P1)"
    )
    assert result.unidentified_count == 1


def test_clamp_partial_cancel_preserves_guest() -> None:
    """Partial-cancel case (2 residents same area, ble_here=1): id=4,
    pre_cancel=5, camera_unrecognized=2, held=2 → total=5, unidentified=1.
    """
    census = _make_bare_census()
    _stub_camera_producer(census, camera_unrecognized_return=2, pre_cancel=5)
    _stub_hold_decay(census, held=2)
    result = census._apply_enhanced_house_census(
        _minimal_raw_result(unid=2),
        ble_persons=["oji", "ezinne", "jaya", "ziri"],
        now=_now(),
    )
    assert result.total_persons == 5
    assert result.unidentified_count == 1


def test_clamp_no_op_when_within_ceiling() -> None:
    """Healthy tick: id=2, pre_cancel=3, held=1 → additive=3 <= ceiling=3,
    clamp does not fire; unidentified passes through unchanged."""
    census = _make_bare_census()
    _stub_camera_producer(census, camera_unrecognized_return=1, pre_cancel=3)
    _stub_hold_decay(census, held=1)
    result = census._apply_enhanced_house_census(
        _minimal_raw_result(unid=1),
        ble_persons=["oji", "ezinne"],
        now=_now(),
    )
    assert result.total_persons == 3
    assert result.unidentified_count == 1


def test_clamp_zero_held_no_unidentified() -> None:
    """No unidentified: total = identified, unidentified = 0."""
    census = _make_bare_census()
    _stub_camera_producer(census, camera_unrecognized_return=0, pre_cancel=0)
    _stub_hold_decay(census, held=0)
    result = census._apply_enhanced_house_census(
        _minimal_raw_result(unid=0),
        ble_persons=["oji"],
        now=_now(),
    )
    assert result.total_persons == 1
    assert result.unidentified_count == 0


def test_pre_cancel_scalar_published_at_step2() -> None:
    """G2: after _get_unrecognized_camera_count, the four PRE-cancel
    diagnostics are populated (discriminating for cancel-ran-vs-never)."""
    from custom_components.universal_room_automation.camera_census import (
        CameraInfo as _CI,
    )
    info = _CI(
        entity_id="binary_sensor.cam_person_occupancy",
        platform=ura_const.CAMERA_PLATFORM_FRIGATE,
        area_id="a1",
        person_binary_sensor="binary_sensor.cam_person_occupancy",
        person_count_sensor="sensor.cam_person_count",
    )
    hass = make_hass()
    person_state = MagicMock(); person_state.state = "2"
    face_state = MagicMock(); face_state.state = "unknown"; face_state.last_changed = None
    states = {
        "sensor.cam_person_count": person_state,
        "sensor.cam_last_recognized_face": face_state,
    }
    hass.states.get = lambda eid: states.get(eid)
    integration_entry = MagicMock()
    integration_entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    integration_entry.options = {
        ura_const.CONF_CAMERA_PERSON_ENTITIES: [info.entity_id],
        ura_const.CONF_ENHANCED_CENSUS: True,
    }
    hass.config_entries.async_entries.return_value = [integration_entry]
    try:
        hass.data[ura_const.DOMAIN] = {}
    except Exception:  # pragma: no cover
        hass.data = {ura_const.DOMAIN: {}}
    census = PersonCensus(hass, _StubCameraManager({info.entity_id: info}))  # type: ignore[arg-type]
    _ = census._get_unrecognized_camera_count()
    # 1 camera, count=2, face=unknown → area_raw_max = {a1: 2}; pre_cancel=2.
    assert census._last_camera_total_pre_cancel == 2
    assert census._last_area_raw_max_pre_cancel == {"a1": 2}
    # ble_cancel_enabled reflects the LIVE kill-switch (default True today).
    assert isinstance(census._last_ble_cancel_enabled, bool)
    # ble_by_area is a dict (may be empty when no person_coordinator).
    assert isinstance(census._last_ble_by_area, dict)


# ===========================================================================
# D2 — composition inversion (source-grep style, matches project convention).
# ===========================================================================


@pytest.fixture(scope="module")
def presence_src() -> str:
    with open(
        "custom_components/universal_room_automation/domain_coordinators/presence.py"
    ) as f:
        return f.read()


def _method_body(src: str, needle: str, span: int = 6000) -> str:
    idx = src.find(needle)
    assert idx >= 0, f"needle not found: {needle!r}"
    return src[idx: idx + span]


def test_home_like_guest_armed_is_room_only(presence_src: str) -> None:
    """D2: the home-like branch must set ``guest_armed = guest_room_gate_armed``
    (Path B leads). The ``or`` composition must be gone from the branch.

    Mutation D2-M1 (revert to OR) will fail this — the exact discriminator.
    """
    body = _method_body(presence_src, "if current_state in _home_like_states:", span=1500)
    assert "guest_armed = guest_room_gate_armed" in body, (
        "D2 requires guest_armed = guest_room_gate_armed in the home-like branch"
    )
    # The OR composition must not survive in the SAME branch.
    assert "unid_gate_armed or guest_room_gate_armed" not in body, (
        "D2 requires removal of ``unid_gate_armed or guest_room_gate_armed`` "
        "from the home-like branch (Path A is a corroborator only)"
    )


def test_confidence_bump_when_both_gates_fire(presence_src: str) -> None:
    """D2: confidence 0.95 when both room + census fire (was 0.9)."""
    # Look near the confidence block.
    idx = presence_src.find("if guest_room_gate_armed and unid_gate_armed:")
    assert idx >= 0
    block = presence_src[idx: idx + 400]
    assert "0.95" in block, "D2 must set confidence 0.95 for room+census corroboration"


def test_inside_guest_branch_unchanged(presence_src: str) -> None:
    """D2: the ``elif current_state == HouseState.GUEST`` branch must still
    set ``guest_armed = guest_room_gate_armed`` (unchanged from pre-cycle)."""
    idx = presence_src.find("elif current_state == HouseState.GUEST:")
    assert idx >= 0
    block = presence_src[idx: idx + 600]
    assert "guest_armed = guest_room_gate_armed" in block


# ===========================================================================
# D3 — registry-based guest-room entity resolution (source-grep + behavior).
# ===========================================================================


def test_discover_uses_registry_lookup(presence_src: str) -> None:
    """D3: _discover_guest_rooms must resolve via
    ``ent_reg.async_get_entity_id("binary_sensor", DOMAIN,
    f"{entry.entry_id}_occupied")`` — NOT the slug-built string.

    Mutation D3-M1 (restore ``f"binary_sensor.{room_slug}_occupied"``)
    will fail this.
    """
    body = _method_body(presence_src, "def _discover_guest_rooms(", span=4000)
    assert "async_get_entity_id" in body, (
        "D3 requires entity-registry-based resolution"
    )
    assert 'f"{entry.entry_id}_occupied"' in body, (
        "D3 requires the well-known unique_id shape from entity.py:34"
    )
    # Slug-string construction of the occupied entity_id must be gone.
    assert 'f"binary_sensor.{room_slug}_occupied"' not in body, (
        "D3 requires removal of slug-string construction "
        "(broke on Upstairs Guestroom rename)"
    )


def test_unresolvable_room_warns(presence_src: str) -> None:
    """D3: an unresolvable flagged guest room must log a WARNING naming
    the room (must be LOUD, not silent)."""
    body = _method_body(presence_src, "def _discover_guest_rooms(", span=4000)
    assert "_LOGGER.warning" in body, "D3 requires WARNING log on registry miss"
    assert "skipping registration" in body


def test_entity_to_name_reverse_map_populated(presence_src: str) -> None:
    """D3: the reverse-map attribute exists and is populated."""
    body = _method_body(presence_src, "def _discover_guest_rooms(", span=4000)
    assert "self._guest_room_entity_to_name[" in body, (
        "D3 requires populating _guest_room_entity_to_name"
    )


def test_handler_uses_reverse_map_not_slug_loop(presence_src: str) -> None:
    """D3: _handle_guest_room_occupancy_change must use the reverse-map
    lookup, not the slug-built for-loop."""
    body = _method_body(
        presence_src, "def _handle_guest_room_occupancy_change(", span=3000
    )
    assert "self._guest_room_entity_to_name.get(entity_id)" in body, (
        "D3 requires reverse-map lookup in the occupancy handler"
    )
    # Slug reverse-loop must be gone.
    assert 'f"binary_sensor.{rn_slug}_occupied"' not in body


def test_reconfigure_clears_entity_map(presence_src: str) -> None:
    """D3: reconfigure-without-restart must clear the reverse map (Bug
    Class #38-style — stale mappings would misroute callbacks)."""
    body = _method_body(presence_src, "def _discover_guest_rooms(", span=4000)
    assert "self._guest_room_entity_to_name.clear()" in body


def test_entity_to_name_init_in_ctor(presence_src: str) -> None:
    """D3: the reverse-map must be initialized in __init__ (not lazily)."""
    # Grep the module for the init assignment.
    assert re.search(
        r"self\._guest_room_entity_to_name\s*:\s*Dict\[str,\s*str\]\s*=\s*\{\}",
        presence_src,
    ), "D3 requires _guest_room_entity_to_name initialized in __init__"
