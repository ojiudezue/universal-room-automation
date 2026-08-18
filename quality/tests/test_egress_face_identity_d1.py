"""EXTERIOR-GUEST-FACE-FASTFOLLOW-1 D1 tests.

Drives PRODUCTION `transit_validator.EgressDirectionTracker` and
`camera_census.PersonCensus`. Follows the Tier 2-DB test-authority
discipline: uses an INJECTED clock (no `time.sleep`), the plan-review
C-LOW-1 requirement.

Discriminators map to plan §D1 acceptance criteria:

- helper returns None / valid name paths (I3)
- veto: face-recognized but `person.<slug>=not_home` -> None (C-LOW-2)
- house-level fuse via `_apply_enhanced_house_census`  (C-CRIT-1)
- name-normalization at BOTH fuse sites (I5)
- behavioral emit: person_id on ura_person_egress_event with clock
  advance past FACE_MATCH_WINDOW_S -> None (C-LOW-1)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import _provenance_harness  # noqa: F401 — bootstraps HA module stubs
from _provenance_harness import make_hass

# transit_validator needs area_registry + event helpers that _provenance_harness
# does not stub; add them before importing the module under test.
import sys as _sys
import types as _types
if "homeassistant.helpers.area_registry" not in _sys.modules:
    _sys.modules["homeassistant.helpers.area_registry"] = _types.ModuleType(
        "homeassistant.helpers.area_registry"
    )
    _sys.modules["homeassistant.helpers.area_registry"].async_get = (
        MagicMock()
    )
_ev_mod_name = "homeassistant.helpers.event"
if _ev_mod_name not in _sys.modules:
    _ev = _types.ModuleType(_ev_mod_name)
    _ev.async_track_state_change_event = lambda *a, **kw: (lambda: None)
    _ev.async_call_later = lambda *a, **kw: (lambda: None)
    _ev.async_track_time_interval = lambda *a, **kw: (lambda: None)
    _sys.modules[_ev_mod_name] = _ev

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation.camera_census import (
    CameraInfo,
    PersonCensus,
)
from custom_components.universal_room_automation.transit_validator import (
    EgressDirectionTracker,
)


UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubCameraManager:
    def __init__(self, cameras: dict[str, CameraInfo]):
        self._camera_by_entity = cameras

    def get_platform_for_camera(self, entity_id: str):
        info = self._camera_by_entity.get(entity_id)
        return info.platform if info else None

    def get_all_frigate_cameras(self) -> list[CameraInfo]:
        return [
            c for c in self._camera_by_entity.values()
            if c.platform == ura_const.CAMERA_PLATFORM_FRIGATE
        ]

    def resolve_configured_cameras(self, camera_entity_ids):
        out = []
        for eid in camera_entity_ids:
            info = self._camera_by_entity.get(eid)
            if info is not None:
                out.append(info)
        return out


def _make_state(value: str, last_changed: datetime | None = None) -> MagicMock:
    st = MagicMock()
    st.state = value
    st.last_changed = last_changed
    return st


def _make_census(
    cameras: dict[str, CameraInfo] | None = None,
    states: dict[str, MagicMock] | None = None,
) -> PersonCensus:
    hass = make_hass()
    st_map = dict(states or {})
    hass.states.get = lambda entity_id: st_map.get(entity_id)

    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        ura_const.CONF_ENHANCED_CENSUS: True,
        "tracked_persons": ["person.oji_udezue", "person.ezinne_udezue"],
    }
    hass.config_entries.async_entries.return_value = [entry]

    mgr = _StubCameraManager(cameras or {})
    census = PersonCensus(hass, mgr)  # type: ignore[arg-type]
    return census


def _make_tracker_with_census(
    face_sensor_id: str,
    face_value: str,
    face_last_changed: datetime | None,
    person_state: str | None = None,
) -> tuple[EgressDirectionTracker, PersonCensus, MagicMock]:
    """Wire an EgressDirectionTracker + PersonCensus sharing a fake hass
    where `sensor.<stem>_last_recognized_face` is present."""
    hass = make_hass()
    states: dict[str, MagicMock] = {}
    if face_last_changed is not None:
        states[face_sensor_id] = _make_state(face_value, face_last_changed)
    if person_state is not None:
        # face_value is Frigate first-name (e.g. "Oji"); person.<first_lower>
        slug = face_value.strip().lower().split("_", 1)[0]
        states[f"person.{slug}"] = _make_state(person_state)
    hass.states.get = lambda eid: states.get(eid)

    mgr = _StubCameraManager({})
    census = PersonCensus(hass, mgr)  # type: ignore[arg-type]
    hass.data = {ura_const.DOMAIN: {"census": census}}
    tracker = EgressDirectionTracker(hass)
    return tracker, census, hass


# ---------------------------------------------------------------------------
# _resolve_egress_face_identity — resolver correctness (I3)
# ---------------------------------------------------------------------------


def test_resolver_returns_none_when_no_face_sensor():
    """No sensor.<stem>_last_recognized_face exists -> None."""
    hass = make_hass()
    hass.states.get = lambda eid: None
    hass.data = {ura_const.DOMAIN: {"census": _make_census()}}
    tracker = EgressDirectionTracker(hass)

    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    got = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now,
    )
    assert got is None


@pytest.mark.parametrize("bad_value", ["unavailable", "unknown", "", "none"])
def test_resolver_returns_none_on_bad_state(bad_value):
    """State exists but is unavailable/unknown/empty/none -> None."""
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    tracker, _, _ = _make_tracker_with_census(
        face_id, bad_value, last_changed=now,
    ) if False else _make_tracker_with_census(
        face_id, bad_value, now,
    )
    got = tracker._resolve_egress_face_identity(
        f"binary_sensor.{stem}_person_occupancy", now,
    )
    assert got is None


def test_resolver_returns_fresh_name():
    """Fresh (age <= FACE_MATCH_WINDOW_S) recognized name -> that name."""
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    tracker, _, _ = _make_tracker_with_census(face_id, "Oji", now)
    got = tracker._resolve_egress_face_identity(
        f"binary_sensor.{stem}_person_occupancy", now,
    )
    assert got == "Oji"


def test_resolver_returns_none_when_stale():
    """Face age > FACE_MATCH_WINDOW_S -> None (I3)."""
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    old = now - timedelta(seconds=ura_const.FACE_MATCH_WINDOW_S + 1)
    tracker, _, _ = _make_tracker_with_census(face_id, "Oji", old)
    got = tracker._resolve_egress_face_identity(
        f"binary_sensor.{stem}_person_occupancy", now,
    )
    assert got is None


# ---------------------------------------------------------------------------
# C-LOW-2 veto: person.<slug> == not_home -> drop the face identity
# ---------------------------------------------------------------------------


def test_resolver_vetoes_when_person_not_home():
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    tracker, _, _ = _make_tracker_with_census(
        face_id, "Oji", now, person_state="not_home",
    )
    got = tracker._resolve_egress_face_identity(
        f"binary_sensor.{stem}_person_occupancy", now,
    )
    assert got is None, "person.oji=not_home should suppress the identity"


def test_resolver_fail_open_when_person_missing():
    """Missing person entity -> keep the identity (fail-open, matches
    _get_face_recognized_person_names behaviour)."""
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    # No person state supplied -> hass.states.get returns None for it.
    tracker, _, _ = _make_tracker_with_census(face_id, "Oji", now)
    got = tracker._resolve_egress_face_identity(
        f"binary_sensor.{stem}_person_occupancy", now,
    )
    assert got == "Oji"


# ---------------------------------------------------------------------------
# Behavioral — _resolve_direction emits person_id; injected clock advance
# past FACE_MATCH_WINDOW_S drops it (C-LOW-1: no wall-clock coupling).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_behavioral_egress_event_carries_person_id_then_expires():
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    face_ts = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    tracker, census, hass = _make_tracker_with_census(face_id, "Oji", face_ts)

    # Capture bus.async_fire calls.
    fired: list[tuple[str, dict]] = []
    hass.bus = MagicMock()
    hass.bus.async_fire = lambda topic, payload: fired.append((topic, payload))

    # Case 1: crossing 3s AFTER face-state change -> person_id = "Oji".
    crossing_1 = face_ts + timedelta(seconds=3)
    await tracker._resolve_direction(
        f"binary_sensor.{stem}_person_occupancy", crossing_1,
    )
    assert fired, "expected ura_person_egress_event to fire"
    topic, payload = fired[-1]
    assert topic == "ura_person_egress_event"
    assert payload["person_id"] == "Oji"
    # Census register happened via the emit path.
    assert "oji" in census._egress_face_ids

    # Reset dedup so a second call re-resolves.
    tracker._last_resolved.clear()

    # Case 2: crossing FACE_MATCH_WINDOW_S + 1 later (INJECTED clock via
    # the timestamp argument) -> person_id must be None (I3, C-LOW-1).
    crossing_2 = face_ts + timedelta(
        seconds=ura_const.FACE_MATCH_WINDOW_S + 1,
    )
    await tracker._resolve_direction(
        f"binary_sensor.{stem}_person_occupancy", crossing_2,
    )
    topic2, payload2 = fired[-1]
    assert payload2["person_id"] is None


# ---------------------------------------------------------------------------
# Census fuse AT HOUSE LEVEL — plan-review C-CRIT-1 discriminator.
# Exercises `_apply_enhanced_house_census` (fuse site :3391), not just
# the raw `:1855` site.
# ---------------------------------------------------------------------------


def _house_apply(census: PersonCensus, ble_persons, face_recognized_slugs):
    """Invoke `_apply_enhanced_house_census` with controlled inputs by
    monkey-patching the readers it consults.
    """
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    raw = MagicMock()
    raw.zone = "house"
    raw.confidence = ura_const.CENSUS_CONFIDENCE_HIGH
    raw.source_agreement = "single_source"
    raw.frigate_count = 0
    raw.unifi_count = 0
    raw.degraded_mode = False
    raw.active_platforms = []
    raw.timestamp = now
    # Neutralize the pre-cancel scalar so raw_total_ceiling won't clip.
    census._last_camera_total_pre_cancel = 99
    # Stub out the readers `_apply_enhanced_house_census` calls.
    with patch.object(census, "_get_unrecognized_camera_count", return_value=0), \
         patch.object(census, "_get_wifi_guest_count", return_value=0), \
         patch.object(
             census, "_get_face_recognized_person_names",
             return_value=list(face_recognized_slugs),
         ):
        return census._apply_enhanced_house_census(raw, list(ble_persons), now)


def test_house_fuse_face_and_egress_same_person_counts_once():
    """face_ids={oji} + egress={oji} -> identified_count == 1 (I1)."""
    census = _make_census()
    census.register_egress_face(
        "oji", datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC),
    )
    result = _house_apply(
        census, ble_persons=[], face_recognized_slugs=["oji_udezue"],
    )
    assert result.identified_count == 1


def test_house_fuse_face_and_egress_different_persons_counts_two():
    """face_ids={oji} + egress={ziri} -> identified_count == 2."""
    census = _make_census()
    census.register_egress_face(
        "ziri", datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC),
    )
    result = _house_apply(
        census, ble_persons=[], face_recognized_slugs=["oji_udezue"],
    )
    assert result.identified_count == 2


def test_house_fuse_egress_only_moves_house_count():
    """C-CRIT-1 discriminator: egress-face-ONLY resident (no BLE, no
    Frigate face) MUST raise house identified_count by 1. If the :3391
    fuse is missing, this test fails with count 0.
    """
    census = _make_census()
    census.register_egress_face(
        "ziri", datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC),
    )
    result = _house_apply(
        census, ble_persons=[], face_recognized_slugs=[],
    )
    assert result.identified_count == 1, (
        "egress-face-only resident must reach house identified_count "
        "(:3391 fuse missing?)"
    )


def test_house_fuse_name_normalization_i5():
    """I5: face_ids={Oji} (title case slug from Frigate) unioned with
    egress={oji} normalizes to 1, not 2."""
    census = _make_census()
    census.register_egress_face(
        "oji", datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC),
    )
    # face_recognized returns full URA slugs; simulate a case-varied one.
    result = _house_apply(
        census, ble_persons=[], face_recognized_slugs=["Oji_Udezue"],
    )
    assert result.identified_count == 1


# ---------------------------------------------------------------------------
# TTL prune on the egress register (bounded incremental identification).
# ---------------------------------------------------------------------------


def test_egress_face_register_ttl_prunes_stale_entries():
    census = _make_census()
    t0 = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    census.register_egress_face("oji", t0)
    # Just before TTL -> still fresh.
    inside = t0 + timedelta(
        seconds=ura_const.EGRESS_FACE_UNION_TTL_S - 1,
    )
    assert census._get_egress_face_ids_fresh(inside) == {"oji"}
    # After TTL -> pruned.
    after = t0 + timedelta(
        seconds=ura_const.EGRESS_FACE_UNION_TTL_S + 1,
    )
    assert census._get_egress_face_ids_fresh(after) == set()
    assert "oji" not in census._egress_face_ids
