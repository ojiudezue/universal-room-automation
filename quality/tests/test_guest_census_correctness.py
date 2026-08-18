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
    """D2: confidence 0.95 when both room + census fire (was 0.9).

    Review C-MED-2 (2026-08-16): upgraded from bare-substring ``"0.95" in
    block`` to a regex pinned to the assignment site. The prior form was
    trivially satisfied by any comment containing ``0.95`` (e.g.
    ``# NOTE: 0.95 removed``) even if the actual assignment was neutered
    to ``0.9``. Anchor is the exact assignment expression, not the literal.
    """
    m = re.search(
        r"if\s+guest_room_gate_armed\s+and\s+unid_gate_armed:\s*\n"
        r"\s*_d5_guest_confidence(?:\s*:\s*float)?\s*=\s*0\.95\b",
        presence_src,
    )
    assert m is not None, (
        "D2: expected assignment ``_d5_guest_confidence = 0.95`` immediately "
        "under ``if guest_room_gate_armed and unid_gate_armed:`` — a bare "
        "``0.95`` in a comment does not satisfy the anchor."
    )


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


def test_unresolvable_room_warns(caplog: pytest.LogCaptureFixture) -> None:
    """D3: an unresolvable flagged guest room must log a WARNING naming
    the room AND NOT register it in ``_guest_room_state`` (must be LOUD +
    silent-continue path is REJECTED).

    Review C-MED-1 (2026-08-16, variant-7 hollow-anchor): replaced the
    prior source-grep assertions (``"_LOGGER.warning" in body`` +
    ``"skipping registration" in body``) with a behavioural drive of
    ``_discover_guest_rooms``. Variant-7 evidence: the prior test PASSED
    when the WARNING CALL was deleted but the substrings survived in a
    comment. This test asserts the OBSERVED emit + observed non-registration,
    which comment-preservation cannot satisfy.

    Drill (D3-M2 both forms):
      (a) delete the WARNING call outright → this test FAILs (no record).
      (b) variant-7: replace the call with ``pass  # _LOGGER.warning
          "skipping registration"`` → still FAILS (no record).
    """
    import logging as _stdlogging
    from unittest.mock import patch as _patch

    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE,
        CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN,
        CONF_ROOM_IS_GUEST_ROOM,
        CONF_ROOM_NAME,
        DOMAIN,
        ENTRY_TYPE_ROOM,
    )
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as _pres_mod,
    )
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )

    # Build a bare PresenceCoordinator without running __init__ (heavy).
    pc = PresenceCoordinator.__new__(PresenceCoordinator)
    pc.hass = make_hass()
    pc._guest_room_state = {}
    pc._guest_room_unsubs = {}
    pc._guest_room_entity_to_name = {}
    pc._guest_room_known_last_true = {}

    # Config entry: guest room flagged, no matching entity in the registry.
    entry = MagicMock()
    entry.entry_id = "01KTESTUNRESOLVABLE0000000"
    entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM}
    entry.options = {
        CONF_ROOM_NAME: "Phantom Guest Room",
        CONF_ROOM_IS_GUEST_ROOM: True,
        CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN: 30,
    }
    pc.hass.config_entries.async_entries = MagicMock(return_value=[entry])

    # Registry stub returns None for the unique_id → resolution miss.
    fake_reg = MagicMock()
    fake_reg.async_get_entity_id = MagicMock(return_value=None)

    import homeassistant.helpers.entity_registry as _er_mod  # stubbed via harness
    caplog.clear()
    with caplog.at_level(_stdlogging.WARNING, logger=_pres_mod.__name__), \
            _patch.object(_er_mod, "async_get", return_value=fake_reg):
        pc._discover_guest_rooms()

    # (a) The room MUST NOT be registered (silent-continue path is rejected).
    assert "Phantom Guest Room" not in pc._guest_room_state, (
        "D3: unresolvable guest room must NOT be registered in _guest_room_state"
    )
    assert pc._guest_room_unsubs == {}, "D3: no listener subscribed on miss"

    # (b) A WARNING must have been EMITTED naming the room and the entry.
    matching = [
        r for r in caplog.records
        if r.levelno >= _stdlogging.WARNING
        and "Phantom Guest Room" in r.getMessage()
    ]
    assert matching, (
        "D3: expected WARNING record naming the unresolvable room; "
        f"got records: {[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )


def test_discover_boot_seeds_first_seen_when_occupancy_on() -> None:
    """Review B-MEDIUM-1 (2026-08-16) — identity-aware boot seed.

    ``_guest_room_state`` is RAM-only; a mid-visit HA restart otherwise
    resets the 30-min sustained clock (Path B is the only D2 arming source).
    ``_discover_guest_rooms`` must seed ``first_seen`` from the occupancy
    entity's ``last_changed`` when the entity is currently ``on`` AND no
    known person is detected in the room.

    Drill anchor: neuter the seed assignment in ``_discover_guest_rooms``
    (leave the initialisation dict as first_seen=None) → this test FAILs
    with ``first_seen == None``.
    """
    from datetime import timedelta as _td, timezone as _tz
    from unittest.mock import patch as _patch

    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE,
        CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN,
        CONF_ROOM_IS_GUEST_ROOM,
        CONF_ROOM_NAME,
        ENTRY_TYPE_ROOM,
    )
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as _pres_mod,
    )
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )

    pc = PresenceCoordinator.__new__(PresenceCoordinator)
    pc.hass = make_hass()
    pc._guest_room_state = {}
    pc._guest_room_unsubs = {}
    pc._guest_room_entity_to_name = {}
    pc._guest_room_known_last_true = {}

    entry = MagicMock()
    entry.entry_id = "01KTESTBOOTSEED0000000000"
    entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM}
    entry.options = {
        CONF_ROOM_NAME: "Downstairs Guest Bedroom",
        CONF_ROOM_IS_GUEST_ROOM: True,
        CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN: 30,
    }
    pc.hass.config_entries.async_entries = MagicMock(return_value=[entry])

    resolved_entity_id = "binary_sensor.downstairs_guest_bedroom_occupied"
    fake_reg = MagicMock()
    fake_reg.async_get_entity_id = MagicMock(return_value=resolved_entity_id)

    # Occupancy currently ON, last_changed 20 min ago (mid-visit restart).
    pre_restart_change = datetime.now(_tz.utc) - _td(minutes=20)
    occ_state = MagicMock()
    occ_state.state = "on"
    occ_state.last_changed = pre_restart_change
    pc.hass.states.get = lambda eid: occ_state if eid == resolved_entity_id else None

    # No known person in the room (person_coord unavailable → False default).
    import homeassistant.helpers.entity_registry as _er_mod  # stubbed via harness
    with _patch.object(_er_mod, "async_get", return_value=fake_reg), \
            _patch.object(
                _pres_mod, "async_track_state_change_event",
                MagicMock(return_value=lambda: None),
            ):
        pc._discover_guest_rooms()

    state = pc._guest_room_state.get("Downstairs Guest Bedroom")
    assert state is not None, "guest room must be registered when resolvable"
    assert state["first_seen"] == pre_restart_change, (
        f"boot-seed must set first_seen = occupancy.last_changed "
        f"(got {state['first_seen']!r}, expected {pre_restart_change!r})"
    )


def test_discover_boot_no_seed_when_occupancy_off() -> None:
    """Boot-seed must NOT seed first_seen when occupancy is currently OFF.

    Guards against a defensive-fallback shape that seeds unconditionally.
    """
    from unittest.mock import patch as _patch

    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE,
        CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN,
        CONF_ROOM_IS_GUEST_ROOM,
        CONF_ROOM_NAME,
        ENTRY_TYPE_ROOM,
    )
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as _pres_mod,
    )
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )

    pc = PresenceCoordinator.__new__(PresenceCoordinator)
    pc.hass = make_hass()
    pc._guest_room_state = {}
    pc._guest_room_unsubs = {}
    pc._guest_room_entity_to_name = {}
    pc._guest_room_known_last_true = {}

    entry = MagicMock()
    entry.entry_id = "01KTESTBOOTSEEDOFF00000000"
    entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM}
    entry.options = {
        CONF_ROOM_NAME: "Empty Guest Bedroom",
        CONF_ROOM_IS_GUEST_ROOM: True,
        CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN: 30,
    }
    pc.hass.config_entries.async_entries = MagicMock(return_value=[entry])

    resolved_entity_id = "binary_sensor.empty_guest_bedroom_occupied"
    fake_reg = MagicMock()
    fake_reg.async_get_entity_id = MagicMock(return_value=resolved_entity_id)

    occ_state = MagicMock()
    occ_state.state = "off"
    occ_state.last_changed = datetime.now(timezone.utc)
    pc.hass.states.get = lambda eid: occ_state if eid == resolved_entity_id else None

    import homeassistant.helpers.entity_registry as _er_mod  # stubbed via harness
    with _patch.object(_er_mod, "async_get", return_value=fake_reg), \
            _patch.object(
                _pres_mod, "async_track_state_change_event",
                MagicMock(return_value=lambda: None),
            ):
        pc._discover_guest_rooms()

    state = pc._guest_room_state["Empty Guest Bedroom"]
    assert state["first_seen"] is None, (
        f"boot-seed must not fire when occupancy is OFF (got {state['first_seen']!r})"
    )


def test_discover_boot_no_seed_when_known_person_present() -> None:
    """Boot-seed identity-aware: MUST NOT seed when a known person is
    currently in the room (mirrors Transition 2 semantics)."""
    from datetime import timedelta as _td, timezone as _tz
    from unittest.mock import patch as _patch

    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE,
        CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN,
        CONF_ROOM_IS_GUEST_ROOM,
        CONF_ROOM_NAME,
        ENTRY_TYPE_ROOM,
    )
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as _pres_mod,
    )
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )

    pc = PresenceCoordinator.__new__(PresenceCoordinator)
    pc.hass = make_hass()
    pc._guest_room_state = {}
    pc._guest_room_unsubs = {}
    pc._guest_room_entity_to_name = {}
    pc._guest_room_known_last_true = {}
    # Force _is_known_person_in_room to return True for this test only.
    pc._is_known_person_in_room = lambda room_name: True  # type: ignore[assignment]

    entry = MagicMock()
    entry.entry_id = "01KTESTBOOTSEEDKNOWN000000"
    entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM}
    entry.options = {
        CONF_ROOM_NAME: "Resident-Occupied Guest Bedroom",
        CONF_ROOM_IS_GUEST_ROOM: True,
        CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN: 30,
    }
    pc.hass.config_entries.async_entries = MagicMock(return_value=[entry])

    resolved_entity_id = "binary_sensor.resident_occupied_guest_bedroom_occupied"
    fake_reg = MagicMock()
    fake_reg.async_get_entity_id = MagicMock(return_value=resolved_entity_id)

    occ_state = MagicMock()
    occ_state.state = "on"
    occ_state.last_changed = datetime.now(_tz.utc) - _td(minutes=20)
    pc.hass.states.get = lambda eid: occ_state if eid == resolved_entity_id else None

    import homeassistant.helpers.entity_registry as _er_mod  # stubbed via harness
    with _patch.object(_er_mod, "async_get", return_value=fake_reg), \
            _patch.object(
                _pres_mod, "async_track_state_change_event",
                MagicMock(return_value=lambda: None),
            ):
        pc._discover_guest_rooms()

    state = pc._guest_room_state["Resident-Occupied Guest Bedroom"]
    assert state["first_seen"] is None, (
        f"boot-seed must not fire when a known person is in the room "
        f"(got {state['first_seen']!r})"
    )


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


# ===========================================================================
# D2b — GUEST exit decoupling from unidentified_count.
# ===========================================================================


def test_d2b_guest_exits_when_room_clears_even_if_unidentified_stuck() -> None:
    """D2b regression guard: GUEST + guest_gate_armed=False must exit even
    when unidentified_count > 0 (the underlying cancellation gap keeps it
    pinned).

    Pre-D2b: unidentified_count > 0 latched the house in GUEST indefinitely
    on the tonight-live path (unidentified pinned at 2 by D1's expected
    residual). Mutation D2b-M1 (restore ``and unidentified_count == 0``)
    fails here.
    """
    from custom_components.universal_room_automation.domain_coordinators.house_state import (
        HouseState,
    )
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        StateInferenceEngine,
    )
    engine = StateInferenceEngine(sleep_start_hour=23, sleep_end_hour=6)
    new_state = engine.infer(
        census_count=6,
        current_state=HouseState.GUEST,
        any_zone_occupied=True,
        now=datetime(2026, 8, 16, 14, 0, 0),
        unidentified_count=2,        # D1 residual — cancellation still broken
        guest_gate_armed=False,      # guest room cleared
    )
    assert new_state == HouseState.HOME_DAY, (
        f"D2b: guest room cleared but house stuck in GUEST "
        f"(returned {new_state}) — pre-D2b terminal-state bug"
    )


def test_d2b_real_guest_holds_when_room_still_occupied() -> None:
    """D2b preservation: room still armed → GUEST held even if
    unidentified_count == 0 (belt-and-braces: room is the authority)."""
    from custom_components.universal_room_automation.domain_coordinators.house_state import (
        HouseState,
    )
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        StateInferenceEngine,
    )
    engine = StateInferenceEngine(sleep_start_hour=23, sleep_end_hour=6)
    new_state = engine.infer(
        census_count=1,
        current_state=HouseState.GUEST,
        any_zone_occupied=True,
        now=datetime(2026, 8, 16, 14, 0, 0),
        unidentified_count=0,
        guest_gate_armed=True,       # room still occupied by unknown
    )
    # Exit predicate is False (gate armed) → not HOME_*.
    assert new_state != HouseState.HOME_DAY
    assert new_state != HouseState.HOME_NIGHT
    assert new_state != HouseState.HOME_EVENING


def test_d2b_guest_non_terminal_from_room_clear() -> None:
    """D2b terminal-state guard: from GUEST, infer() MUST return a non-None
    transition when the guest room clears (regardless of unidentified)."""
    from custom_components.universal_room_automation.domain_coordinators.house_state import (
        HouseState,
    )
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        StateInferenceEngine,
    )
    engine = StateInferenceEngine(sleep_start_hour=23, sleep_end_hour=6)
    new_state = engine.infer(
        census_count=6,
        current_state=HouseState.GUEST,
        any_zone_occupied=True,
        now=datetime(2026, 8, 16, 14, 0, 0),
        unidentified_count=6,        # cancellation still fully broken
        guest_gate_armed=False,
    )
    assert new_state is not None
    assert new_state != HouseState.GUEST


def test_d2b_exit_predicate_source_shape(presence_src: str) -> None:
    """D2b: the exit predicate must NOT include ``unidentified_count == 0``.
    Source-guard against silent revert."""
    # Find the exit predicate line (unique).
    m = re.search(
        r"if current_state == HouseState\.GUEST[^\n]*not guest_gate_armed[^\n]*:",
        presence_src,
    )
    assert m is not None, "GUEST-exit predicate not located"
    assert "unidentified_count" not in m.group(0), (
        "D2b: unidentified_count conjunct must be removed from GUEST-exit "
        "predicate (would re-latch the house terminally when D1 residual > 0)"
    )


def test_entity_to_name_init_in_ctor(presence_src: str) -> None:
    """D3: the reverse-map must be initialized in __init__ (not lazily)."""
    # Grep the module for the init assignment.
    assert re.search(
        r"self\._guest_room_entity_to_name\s*:\s*Dict\[str,\s*str\]\s*=\s*\{\}",
        presence_src,
    ), "D3 requires _guest_room_entity_to_name initialized in __init__"


# ===========================================================================
# HIGH fix-up (2026-08-16): boot-seed false-GUEST closure
# ---------------------------------------------------------------------------
# Root cause: `_discover_guest_rooms` seeded `first_seen = last_changed`
# using an identity check (`_is_known_person_in_room`) whose False fallback
# fires at boot because `person_coordinator._tracked_persons` is not yet
# populated. Once seeded, the runtime gate `_guest_room_gate_armed` uses
# only the cached `current_occupancy_known` flag (set by the state-change
# LISTENER) — a resident sitting still never toggles occupancy so the flag
# stays False and the gate fires with hours of elapsed credit.
#
# Fix — two parts:
#   Part 1: `_guest_room_gate_armed` performs a LIVE identity re-check
#           (`_is_known_person_in_room`) BEFORE firing per-room; if known
#           person present, clear first_seen, set current_occupancy_known
#           True, continue.
#   Part 2: clamp boot-seeded `first_seen` so at least
#           `GUEST_BOOT_SEED_MIN_RESIDUAL_S` remain before threshold:
#           `first_seen = max(last_changed, now - threshold_s + residual_s)`.
#
# Drill anchors:
#   FIX-M1. Delete the Part-1 live re-check in _guest_room_gate_armed →
#           `test_gate_reverify_identity_at_gate_time` fails.
#   FIX-M2. Delete the Part-2 residual clamp in _discover_guest_rooms →
#           `test_boot_seed_residual_clamp` fails.
# ===========================================================================


def _seed_bare_pc_with_guest_room(
    room_name: str,
    entry_id: str,
    entity_id: str,
    last_changed,
    is_known_at_boot: bool,
    threshold_min: int = 30,
):
    """Shared helper: build a bare PresenceCoordinator + config + registry
    stub, run _discover_guest_rooms with the given identity oracle, and
    return the coordinator."""
    from unittest.mock import patch as _patch

    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE,
        CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN,
        CONF_ROOM_IS_GUEST_ROOM,
        CONF_ROOM_NAME,
        ENTRY_TYPE_ROOM,
    )
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as _pres_mod,
    )
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )

    pc = PresenceCoordinator.__new__(PresenceCoordinator)
    pc.hass = make_hass()
    pc._guest_room_state = {}
    pc._guest_room_unsubs = {}
    pc._guest_room_entity_to_name = {}
    pc._guest_room_known_last_true = {}
    pc._guest_detection_enabled = True

    # Mutable identity oracle — tests can flip after boot.
    identity_flag = {"known": is_known_at_boot}
    pc._is_known_person_in_room = lambda rn, _f=identity_flag: _f["known"]  # type: ignore[assignment]

    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM}
    entry.options = {
        CONF_ROOM_NAME: room_name,
        CONF_ROOM_IS_GUEST_ROOM: True,
        CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN: threshold_min,
    }
    pc.hass.config_entries.async_entries = MagicMock(return_value=[entry])

    fake_reg = MagicMock()
    fake_reg.async_get_entity_id = MagicMock(return_value=entity_id)

    occ_state = MagicMock()
    occ_state.state = "on"
    occ_state.last_changed = last_changed
    pc.hass.states.get = lambda eid: occ_state if eid == entity_id else None

    import homeassistant.helpers.entity_registry as _er_mod
    with _patch.object(_er_mod, "async_get", return_value=fake_reg), \
            _patch.object(
                _pres_mod, "async_track_state_change_event",
                MagicMock(return_value=lambda: None),
            ):
        pc._discover_guest_rooms()

    return pc, identity_flag


def test_gate_reverify_identity_at_gate_time() -> None:
    """Regression for the boot false-GUEST hole (operator HIGH, 2026-08-16).

    Scenario: resident in a designated guest room across HA restart.
      * pre-restart occupancy toggled ON hours ago (last_changed = -3h).
      * At boot, person_coordinator not yet populated →
        `_is_known_person_in_room` returns False → seed happens.
      * Post-boot the substrate populates and the room IS occupied by a
        known person.
      * The very next inference tick calls `_guest_room_gate_armed`.

    Fixed behaviour: the gate performs a LIVE identity re-check per room
    before firing; because a known person is now present, it clears
    first_seen, sets current_occupancy_known=True, and returns False.

    Pre-fix: gate consults ONLY the cached `current_occupancy_known` flag
    (event-driven, still False from init because occupancy never toggled)
    and fires with elapsed >> threshold.
    """
    from datetime import timedelta as _td, timezone as _tz

    now_boot = datetime.now(_tz.utc)
    last_changed = now_boot - _td(hours=3)

    pc, identity_flag = _seed_bare_pc_with_guest_room(
        room_name="Downstairs Guest Bedroom",
        entry_id="01KTESTFALSEGUEST00000001",
        entity_id="binary_sensor.downstairs_guest_bedroom_occupied",
        last_changed=last_changed,
        is_known_at_boot=False,   # substrate cold → seed plants
        threshold_min=30,
    )

    # Precondition: seed planted (bug reachable).
    state = pc._guest_room_state["Downstairs Guest Bedroom"]
    assert state["first_seen"] is not None, (
        "precondition: boot seed must have planted first_seen (bug prereq)"
    )
    assert state["current_occupancy_known"] is False, (
        "precondition: current_occupancy_known init-False (bug prereq)"
    )

    # Substrate now populated: a known person IS in the room.
    identity_flag["known"] = True

    # First inference tick — well past the 30-min threshold.
    tick_now = now_boot + _td(minutes=1)
    fired = pc._guest_room_gate_armed(now=tick_now)

    assert fired is False, (
        "gate must NOT fire: a known person is present at gate-check time "
        "(live re-check should catch the stale seed). Firing here is the "
        "false-GUEST-at-boot regression."
    )
    # And the stale seed must have been cleared by the live re-check.
    state = pc._guest_room_state["Downstairs Guest Bedroom"]
    assert state["first_seen"] is None, (
        "live re-check must clear stale first_seen (Transition 2 semantics)"
    )
    assert state["current_occupancy_known"] is True, (
        "live re-check must set current_occupancy_known=True"
    )


def test_boot_seed_residual_clamp() -> None:
    """Part 2: boot-seed must never be already-expired.

    Seed from a very old `last_changed` (hours ago) with identity substrate
    cold at boot → the clamp must guarantee at least
    GUEST_BOOT_SEED_MIN_RESIDUAL_S seconds of residual dwell remain before
    threshold at the moment of boot.
    """
    from datetime import timedelta as _td, timezone as _tz

    from custom_components.universal_room_automation.const import (
        GUEST_BOOT_SEED_MIN_RESIDUAL_S,
    )

    threshold_min = 30
    threshold_s = threshold_min * 60
    now_boot = datetime.now(_tz.utc)
    ancient = now_boot - _td(hours=5)

    pc, _ = _seed_bare_pc_with_guest_room(
        room_name="Ancient Guest Bedroom",
        entry_id="01KTESTBOOTCLAMP0000000001",
        entity_id="binary_sensor.ancient_guest_bedroom_occupied",
        last_changed=ancient,
        is_known_at_boot=False,
        threshold_min=threshold_min,
    )

    state = pc._guest_room_state["Ancient Guest Bedroom"]
    first_seen = state["first_seen"]
    assert first_seen is not None, "seed must plant"

    # Compute observed elapsed at boot; requirement: elapsed <= threshold - residual.
    # We approximate 'boot time' with a slightly-later tick since we can't
    # freeze exact utcnow() inside _discover_guest_rooms.
    tick = datetime.now(_tz.utc) + _td(seconds=1)
    elapsed_s = (tick - first_seen).total_seconds()
    # F-HIGH-1 fix (2026-08-17): use a HARD-CODED expected bound derived
    # from the documented product value (30-min threshold, 300s residual),
    # not the imported constant. If the two collapsed together (as they did
    # pre-fix), setting GUEST_BOOT_SEED_MIN_RESIDUAL_S to its documented
    # kill-switch value 0 would still leave the test green — a hollow
    # oracle. A separate contract assertion below guards the constant's
    # value so a drift there also fails.
    EXPECTED_RESIDUAL_S = 300  # test-local literal (30-min default × 5-min floor)
    EXPECTED_MAX_ELAPSED_S = (30 * 60) - EXPECTED_RESIDUAL_S + 2  # +2s test slack
    assert elapsed_s <= EXPECTED_MAX_ELAPSED_S, (
        f"clamp violated: elapsed={elapsed_s}s, "
        f"expected <= {EXPECTED_MAX_ELAPSED_S}s "
        f"(30-min threshold minus {EXPECTED_RESIDUAL_S}s residual)"
    )
    # Contract assertion: keep the production constant pinned to the
    # value this test's oracle is built around. If it drifts, review
    # this test and the operator-facing documented default together.
    assert GUEST_BOOT_SEED_MIN_RESIDUAL_S == EXPECTED_RESIDUAL_S, (
        f"GUEST_BOOT_SEED_MIN_RESIDUAL_S drift: "
        f"got {GUEST_BOOT_SEED_MIN_RESIDUAL_S}, expected {EXPECTED_RESIDUAL_S}. "
        f"Update this test AND the operator-facing default together."
    )


def test_boot_seed_preserves_genuine_guest_credit() -> None:
    """Part 2 anti-over-correction: a genuine guest scenario must still
    benefit from the boot seed — pre-restart credit is preserved, not
    reset to `now`, so a restart mid-visit does not cost the full 30 min.

    Scenario: occupancy ON since 15 min ago (within threshold, well
    outside the residual clamp). After boot, first_seen should equal the
    pre-restart last_changed (unclamped), so a tick at 30-min mark still
    fires per the intended feature.
    """
    from datetime import timedelta as _td, timezone as _tz

    threshold_min = 30
    now_boot = datetime.now(_tz.utc)
    last_changed = now_boot - _td(minutes=15)

    pc, _ = _seed_bare_pc_with_guest_room(
        room_name="Genuine Guest Bedroom",
        entry_id="01KTESTBOOTGENUINE00000001",
        entity_id="binary_sensor.genuine_guest_bedroom_occupied",
        last_changed=last_changed,
        is_known_at_boot=False,
        threshold_min=threshold_min,
    )
    state = pc._guest_room_state["Genuine Guest Bedroom"]
    fs = state["first_seen"]
    # Not reset to ~now: at least 10 minutes of pre-restart credit preserved.
    tick_at_boot = datetime.now(_tz.utc) + _td(seconds=1)
    elapsed_at_boot_s = (tick_at_boot - fs).total_seconds()
    assert elapsed_at_boot_s >= 10 * 60, (
        f"genuine-guest credit lost: elapsed at boot only {elapsed_at_boot_s}s "
        "(clamp over-corrected — expected ~15 min preserved)"
    )

    # And the gate fires at the 30-min mark from original arrival.
    tick_fire = last_changed + _td(minutes=threshold_min, seconds=1)
    assert pc._guest_room_gate_armed(now=tick_fire) is True, (
        "genuine guest with 30-min sustained pre-restart occupancy must "
        "still fire the gate (feature not neutered by clamp)"
    )


# ===========================================================================
# GUEST-CENSUS CRIT (2026-08-17): _is_known_person_in_room helper tests
# ---------------------------------------------------------------------------
# Regression against a helper that was silently returning False in
# production due to (a) wrong coordinator lookup and (b) wrong attribute.
# These tests exercise the UNPATCHED helper against a fixture shaped like
# the real ``PersonCoordinator.data``, reached via the real
# ``hass.data[DOMAIN]["person_coordinator"]`` path — the same access the
# 7 sibling sites in presence.py use.
# ===========================================================================


def _pc_with_real_person_coord(person_data: dict):
    """Build a bare PresenceCoordinator whose ``hass.data`` carries a
    real-shape person_coordinator stub keyed under DOMAIN."""
    from custom_components.universal_room_automation.const import DOMAIN
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )

    pc = PresenceCoordinator.__new__(PresenceCoordinator)
    pc.hass = make_hass()
    pc._guest_room_known_last_true = {}

    person_coord = MagicMock()
    person_coord.data = person_data
    pc.hass.data = {DOMAIN: {"person_coordinator": person_coord}}
    return pc


def test_is_known_person_reads_canonical_person_coordinator_path():
    """CRIT-REVERT-DRILL (a): if the lookup regresses to
    ``manager.coordinators.get("person")``, this test MUST fail. The
    helper's ONLY route to the substrate is
    ``hass.data[DOMAIN]["person_coordinator"]``.
    """
    pc = _pc_with_real_person_coord({
        "oji": {"location": "Guest Bedroom 1"},
    })
    assert pc._is_known_person_in_room("Guest Bedroom 1") is True


def test_is_known_person_reads_data_location_shape():
    """CRIT-REVERT-DRILL (b): if the attribute regresses to
    ``getattr(person_coord, "_tracked_persons", {})``, this test MUST
    fail — the real store is ``person_coord.data[name]["location"]``
    (person_coordinator.py:452, 528).
    """
    pc = _pc_with_real_person_coord({
        "jaya": {"location": "Jaya Bedroom"},
        "ziri": {"location": "Ziri Bathroom"},
    })
    assert pc._is_known_person_in_room("Jaya Bedroom") is True
    assert pc._is_known_person_in_room("Ziri Bathroom") is True


def test_is_known_person_returns_false_when_no_one_in_room():
    pc = _pc_with_real_person_coord({
        "oji": {"location": "Master Bedroom"},
    })
    assert pc._is_known_person_in_room("Guest Bedroom 1") is False


def test_is_known_person_ignores_unknown_and_away_locations():
    """A person whose location is 'unknown' / 'away' / '' is NOT in the room."""
    pc = _pc_with_real_person_coord({
        "oji": {"location": "unknown"},
        "jaya": {"location": "away"},
        "ziri": {"location": ""},
    })
    assert pc._is_known_person_in_room("unknown") is False
    assert pc._is_known_person_in_room("away") is False


def test_is_known_person_normalizes_case_and_spaces():
    """Vocabularies verified match directly on live mount (2026-08-17):
    both `location` and `room_name` derive from CONF_ROOM_NAME. The
    normalization is defensive symmetry, not a papered-over mismatch.
    """
    pc = _pc_with_real_person_coord({
        "oji": {"location": "guest_bedroom_1"},
    })
    assert pc._is_known_person_in_room("Guest Bedroom 1") is True


def test_is_known_person_returns_false_when_person_coordinator_absent():
    """Absent PC → False (safe default). NOT crash. Substrate may not
    exist during unit-test-shaped calls."""
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )
    pc = PresenceCoordinator.__new__(PresenceCoordinator)
    pc.hass = make_hass()
    pc._guest_room_known_last_true = {}
    # hass.data is {} → get(DOMAIN, {}).get("person_coordinator") is None.
    assert pc._is_known_person_in_room("Guest Bedroom 1") is False


def test_is_known_person_sticky_absorbs_transient_flap():
    """GUEST-CENSUS 2026-08-17: BLE flap tolerance.

    Sequence:
      1. Substrate places resident in room → helper returns True and
         stamps last_true.
      2. Substrate flaps: same resident momentarily resolves to
         'unknown' (documented Bermuda BLE behaviour).
      3. Helper called again within sticky window → returns True from
         the latch, NOT False from the live substrate. This prevents an
         un-exclusion at the exact instant `_guest_room_gate_armed`
         runs its live re-check, which would fire GUEST on a resident.
    """
    from custom_components.universal_room_automation.const import DOMAIN

    pc = _pc_with_real_person_coord({"oji": {"location": "Guest Bedroom 1"}})
    assert pc._is_known_person_in_room("Guest Bedroom 1") is True

    # Flap: resident's location drops to 'unknown'.
    pc.hass.data[DOMAIN]["person_coordinator"].data = {
        "oji": {"location": "unknown"},
    }
    # Within sticky window, exclusion still holds.
    assert pc._is_known_person_in_room("Guest Bedroom 1") is True


def test_is_known_person_sticky_expires_after_window():
    """Sticky is a short latch, not a permanent lock. After the window
    passes with no live hit, the exclusion releases."""
    from datetime import timedelta as _td
    from custom_components.universal_room_automation.const import (
        DOMAIN, GUEST_KNOWN_STICKY_S,
    )

    # F2-MED-1 (Bug Class #64, oracle-echo): the expiry window is a TEST-LOCAL
    # literal, NOT derived from the production constant — otherwise ageing by
    # `GUEST_KNOWN_STICKY_S + 5` would pass for ANY value (incl. 0 and 86400).
    # A separate contract assertion pins the constant to the literal, so a real
    # change to the knob turns a NAMED test red (drill: set constant -> test fails).
    EXPECTED_STICKY_S = 120
    assert GUEST_KNOWN_STICKY_S == EXPECTED_STICKY_S, (
        "GUEST_KNOWN_STICKY_S changed; update EXPECTED_STICKY_S and re-derive "
        f"the sticky-latch test expectations. got {GUEST_KNOWN_STICKY_S}, "
        f"expected {EXPECTED_STICKY_S}."
    )

    pc = _pc_with_real_person_coord({"oji": {"location": "Guest Bedroom 1"}})
    assert pc._is_known_person_in_room("Guest Bedroom 1") is True

    # Age the last_true stamp past the sticky window (test-local literal).
    pc._guest_room_known_last_true["Guest Bedroom 1"] = (
        pc._guest_room_known_last_true["Guest Bedroom 1"]
        - _td(seconds=EXPECTED_STICKY_S + 5)
    )
    # Substrate no longer places anyone in the room; latch has expired.
    pc.hass.data[DOMAIN]["person_coordinator"].data = {
        "oji": {"location": "unknown"},
    }
    assert pc._is_known_person_in_room("Guest Bedroom 1") is False
